"""Stage 2 (Phase 5): Mapillary images -> NVIDIA-hosted VLM -> validated visual observations.

Run:
  uv run python src/run_vlm.py --limit 3                                   # prompt v1 (default)
  uv run python src/run_vlm.py --prompt-version v2 --image-ids 1514293340184582 2302498470581445 379860519858209
  uv run python src/run_vlm.py --prompt-version v2 --sample data/processed/vlm_evaluation_sample.json   # Stage 4
  uv run python src/run_vlm.py --provider groq --prompt-version v2 --sample data/processed/groq_vlm_evaluation_sample.json
Providers: nvidia (default, production V2) | groq (separate Stage 5 comparison; own raw dir + JSONL, never mixed).
Options: --force re-runs images that already have a VALID response for that prompt version.

Input:  data/processed/mapillary_images.geojson (selected, camera_type=perspective, local image present)
Output: data/raw/vlm/<image_id>__b1-prompt-<v>.json   request metadata + raw API response + validation + API stats
        data/processed/vlm_observations.jsonl        normalized observations of all versions (rebuilt from raw files)

Requests are sequential, paced to <= 30/min, with bounded retries on 429/503/transient errors.
VLM observations describe one image at one time. They are not ground truth and never modify OSM data.
Confidence is model-reported and uncalibrated.
"""
import argparse
import base64
import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import geopandas as gpd
import pandas as pd
from dotenv import load_dotenv

load_dotenv()
KEY = os.environ["NVIDIA_API_KEY"]
MODEL = os.environ["NIM_MODEL"]
BASE_URL = os.environ.get("NIM_BASE_URL") or "https://integrate.api.nvidia.com/v1"
RAW = Path("data/raw/vlm")
OUT = Path("data/processed/vlm_observations.jsonl")
IMAGES = Path("data/processed/mapillary_images.geojson")

SCHEMA_VERSION = "b1-visual-obs-v1"  # JSON structure unchanged in prompt v2
CATEGORIES = [  # B1 street design elements + street-space / use characteristics (B1_CONTEXT.md)
    "sidewalk", "roadway", "curb", "crossing", "cycling_infrastructure", "parking", "trees_vegetation",
    "street_furniture", "lighting", "signage", "barriers", "public_transport", "building_frontage",
    "pedestrians", "cyclists", "motor_vehicles",
]
STATUS = {"visible", "not_visible", "uncertain"}
NORMATIVE = re.compile(r"\b(livab\w*|safe|unsafe|pleasant|unpleasant|attractive|unattractive|ugly|good|bad|"
                       r"better|worse|should|human-centered|walkable|friendly|preferred?|desirable|undesirable|"
                       r"poor|excellent)\b", re.I)
ABSENCE = re.compile(r"\b(absent|does not exist|do not exist|there (is|are) no|lacks?|lacking|without any)\b", re.I)
PARAMS = {"max_tokens": 2048, "temperature": 1.0, "top_k": 1, "chat_template_kwargs": {"enable_thinking": False}}

OBS_SCHEMA = {  # JSON Schema of the V2 output structure (used for Groq strict structured output)
    "type": "object", "additionalProperties": False, "required": ["image_quality", "observations"],
    "properties": {
        "image_quality": {"type": "object", "additionalProperties": False, "required": ["usable", "issues"],
                          "properties": {"usable": {"type": "boolean"},
                                         "issues": {"type": "array", "items": {"type": "string"}}}},
        "observations": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["category", "status", "observation", "confidence"],
            "properties": {"category": {"type": "string", "enum": CATEGORIES},
                           "status": {"type": "string", "enum": sorted(STATUS)},
                           "observation": {"type": "string"}, "confidence": {"type": "number"}}}}}}
GROQ_KEY = os.environ.get("GROQ_API_KEY", "")
GROQ = SimpleNamespace(  # Stage 5 experimental backend (free tier); separate from the production NVIDIA dataset
    base_url="https://api.groq.com/openai/v1", model="qwen/qwen3.8-27b", raw=Path("data/raw/vlm_groq"),
    out=Path("data/processed/vlm_groq_observations.jsonl"), label="v2-groq-comparison", source="Groq hosted VLM",
    min_interval=6.0,  # <= 10 requests/min, well below the documented free-tier 30 RPM
    params={"max_completion_tokens": 2048, "temperature": 0, "seed": 0,  # no top_k on Groq: closest to greedy
            "reasoning_effort": "none", "reasoning_format": "hidden",   # thinking off (as NVIDIA enable_thinking=False)
            "response_format": {"type": "json_schema", "json_schema": {
                "name": "b1_visual_observations", "strict": True, "schema": OBS_SCHEMA}}},
    headers={"User-Agent": "agimo-b1-prototype/0.1"})

MIN_INTERVAL_S = 2.0            # <= 30 requests/min, conservative vs. the hosted endpoint's working limit
BACKOFF_S = [2, 5, 10]          # bounded retries (3), overridden upward by Retry-After (capped)
MAX_RETRY_AFTER_S = 60
RETRYABLE = {429: "rate_limited", 502: "service_overloaded", 503: "service_overloaded", 504: "service_overloaded"}
FATAL = {400: "malformed_request", 401: "authentication_failed", 403: "authentication_failed",
         404: "model_or_endpoint_not_found", 413: "malformed_request", 422: "malformed_request"}

JSON_SHAPE = """Return ONLY valid JSON, no markdown, with exactly this structure:
{{"image_quality": {{"usable": true|false, "issues": ["blur"|"occlusion"|"low_light"|"overexposure"|"distortion"|"obstructed_view"|...]}},
 "observations": [{{"category": "<category>", "status": "visible"|"not_visible"|"uncertain",
                   "observation": "<short factual description, <= 25 words>", "confidence": <0.0-1.0>}}]}}"""

PROMPT_V1 = f"""You are annotating one street-level photograph for a streetscape research dataset.
Report ONLY what is directly visible in this image. Do not infer hidden or likely objects.
Do not judge quality, safety, livability, attractiveness or preferences. Do not give recommendations.
Describe observations factually (e.g. "three mature street trees along the right sidewalk"),
not interpretations (e.g. "a green, pleasant street").

{JSON_SHAPE.format()}

Include exactly one entry for EACH of these categories, in this order:
{", ".join(CATEGORIES)}
Use status "not_visible" when the element cannot be seen (this does not mean it is absent),
and "uncertain" when it may be present but is unclear. confidence = how sure you are of the entry."""

PROMPT_V2 = f"""You are annotating one street-level photograph for a streetscape research dataset.
Report ONLY what is directly visible. Do not infer hidden, likely or typical objects.
Describe, do not evaluate: never judge quality, safety, livability, attractiveness, design or preferences,
and give no recommendations.

Inspect the whole image before answering: foreground, middle ground, background, left and right side,
roadway, sidewalks, building edges, the space above the street, poles, overhead wires and intersections.

IGNORE the image-capture setup: the capture car (hood, dashboard, mirrors), the capture bicycle
(handlebars, frame, wheel), helmet, camera rig and the person carrying the camera. They are never
streetscape elements, vehicles, cyclists or pedestrians.

Category definitions:
- sidewalk: a visibly distinct pedestrian walking surface beside or separated from the roadway.
- roadway: the visible vehicle carriageway.
- curb: a clearly visible physical raised edge between the roadway and another distinct space. Not inferred
  from colour or material differences alone; if unclear use "uncertain".
- crossing: a marked or physically defined pedestrian/cycle crossing (zebra, marked or signalised crossing).
  An intersection alone is not a crossing.
- cycling_infrastructure: infrastructure built for cycling (cycle lane, cycle track, bicycle road marking,
  bicycle racks count under street_furniture). Bicycles and people cycling are NOT infrastructure.
- parking: marked parking spaces, or vehicles clearly parked at the kerb or in a parking area
  (not vehicles merely stopped or moving in traffic).
- trees_vegetation: trees, shrubs, planting beds, grass or other greenery.
- street_furniture: benches, bins, bicycle racks, public seating, bollards and similar public-space objects.
- lighting: ONLY physical street-lighting fixtures (lamp posts, street lamps, lamps hanging on overhead wires,
  lamps fixed to buildings). Daylight, sunlight, shadows or brightness are NOT lighting.
- signage: traffic, parking, street-name, wayfinding or other public signs.
- barriers: guardrails, fences, barrier posts or access barriers functioning as barriers.
- public_transport: trams, buses, tram tracks, stops, platforms, shelters. If a rail vehicle is visible but
  tram vs. other rail vehicle is unclear, write "rail_vehicle". Never call a rail vehicle a bus.
- building_frontage: building facades along the street (continuous or detached; ground-floor shops only if
  visibly supported). Do not infer economic activity.
- pedestrians: people walking or standing in the street space (not the capture person).
- cyclists: people riding or pushing bicycles, separate from the capture bicycle.
- motor_vehicles: cars, vans, trucks, buses, motorcycles (not the capture vehicle).

Status:
- "visible": clearly seen in this image.
- "uncertain": possibly present but the image is unclear.
- "not_visible": this image gives no sufficient visual evidence. It does NOT mean the element is absent from
  the street. Phrase it as "No <element> can be determined from this view.", never as "there is no" / "absent".

{JSON_SHAPE.format()}

Include exactly one entry for EACH of these categories, in this order:
{", ".join(CATEGORIES)}
confidence = your own certainty for the entry (it is not a measured accuracy)."""

PROMPTS = {"v1": PROMPT_V1, "v2": PROMPT_V2}
_last_request = [0.0]


def safe(msg):
    msg = str(msg)
    for secret in (KEY, GROQ_KEY):
        if secret:
            msg = msg.replace(secret, "***")
    return msg


class VLMError(RuntimeError):
    def __init__(self, kind, msg, stats):
        super().__init__(f"{kind}: {msg}")
        self.kind, self.stats = kind, stats


def rate_headers(headers):
    """Only rate-limit metadata (never Authorization) is kept from response headers."""
    return {k.lower(): v for k, v in (headers.items() if headers else [])
            if k.lower().startswith("x-ratelimit") or k.lower() == "retry-after"}


def post(body, opener=urllib.request.urlopen, sleep=time.sleep, clock=time.monotonic, provider=None):
    """POST with pacing + bounded retries. Returns (response_json, stats). provider=None -> NVIDIA (unchanged)."""
    url, key, min_interval, extra = ((f"{BASE_URL}/chat/completions", KEY, MIN_INTERVAL_S, {}) if provider is None else
                                     (f"{provider.base_url}/chat/completions", GROQ_KEY, provider.min_interval,
                                      provider.headers))
    req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                 headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                                          "Accept": "application/json", **extra})
    stats = {"attempts": 0, "retries": 0, "http_429": 0, "http_503": 0, "errors": [], "latency_s": None}
    for attempt in range(len(BACKOFF_S) + 1):
        wait = _last_request[0] + min_interval - clock()
        if wait > 0:
            sleep(wait)
        _last_request[0] = clock()
        stats["attempts"] += 1
        t0 = clock()
        try:
            with opener(req, timeout=180) as r:
                stats["latency_s"] = round(clock() - t0, 2)
                if provider is not None:
                    stats["rate_limit_headers"] = rate_headers(getattr(r, "headers", None))
                return json.load(r), stats
        except urllib.error.HTTPError as e:
            code, detail = e.code, safe(e.read()[:300].decode(errors="replace"))
            stats["http_429"] += code == 429
            stats["http_503"] += code == 503
            kind = RETRYABLE.get(code) or FATAL.get(code) or ("model_or_api_error" if code >= 500 else "http_error")
            stats["errors"].append(f"HTTP {code} {kind}")
            if provider is not None:
                stats["rate_limit_headers"] = rate_headers(e.headers)
            if code not in RETRYABLE or attempt == len(BACKOFF_S):
                raise VLMError(kind, f"HTTP {code}: {detail}", stats) from None
            retry_after = e.headers.get("Retry-After") if e.headers else None
            delay = BACKOFF_S[attempt]
            if retry_after and retry_after.strip().isdigit():
                delay = min(max(delay, int(retry_after)), MAX_RETRY_AFTER_S)
        except (urllib.error.URLError, TimeoutError) as e:
            stats["errors"].append(f"network {type(e).__name__}")
            if attempt == len(BACKOFF_S):
                raise VLMError("network_error", safe(e), stats) from None
            delay = BACKOFF_S[attempt]
        stats["retries"] += 1
        print(f"  retry {stats['retries']}/{len(BACKOFF_S)} in {delay} s ({stats['errors'][-1]})")
        sleep(delay)


def request_body(image_path, prompt, provider=None):
    b64 = base64.b64encode(image_path.read_bytes()).decode()
    model, params = (MODEL, PARAMS) if provider is None else (provider.model, provider.params)
    return {"model": model, "messages": [{"role": "user", "content": [
        {"type": "text", "text": prompt},
        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}]}], **params}


def parse_and_validate(text):
    """Returns (parsed or None, errors, warnings). Strict: every category exactly once."""
    errors, warnings = [], []
    m = re.search(r"\{.*\}", re.sub(r"<think>.*?</think>", "", text or "", flags=re.S), re.S)
    try:
        data = json.loads(m.group(0)) if m else None
    except json.JSONDecodeError as e:
        return None, [f"invalid JSON: {e}"], warnings
    if not isinstance(data, dict) or not isinstance(data.get("observations"), list):
        return None, ["missing 'observations' list"], warnings
    seen = []
    for i, o in enumerate(data["observations"]):
        c = o.get("category") if isinstance(o, dict) else None
        if c not in CATEGORIES:
            errors.append(f"obs {i}: unknown category {c!r}")
            continue
        seen.append(c)
        if o.get("status") not in STATUS:
            errors.append(f"{c}: invalid status {o.get('status')!r}")
        conf = o.get("confidence")
        if not isinstance(conf, (int, float)) or isinstance(conf, bool) or not 0 <= conf <= 1:
            errors.append(f"{c}: invalid confidence {conf!r}")
        text_ = o.get("observation")
        if not isinstance(text_, str) or not text_.strip():
            errors.append(f"{c}: empty observation")
            continue
        if NORMATIVE.search(text_):
            warnings.append(f"{c}: normative wording '{NORMATIVE.search(text_).group(0)}'")
        if o.get("status") == "not_visible" and ABSENCE.search(text_):
            warnings.append(f"{c}: absence claim '{ABSENCE.search(text_).group(0)}' for not_visible")
    missing = [c for c in CATEGORIES if c not in seen]
    dupes = sorted({c for c in seen if seen.count(c) > 1})
    if missing:
        errors.append(f"missing categories: {missing}")
    if dupes:
        errors.append(f"duplicate categories: {dupes}")
    if not isinstance(data.get("image_quality"), dict):
        warnings.append("missing image_quality")
    return data, errors, warnings


def raw_path(image_id, version, provider=None):
    if provider is not None:
        return provider.raw / f"{image_id}__{provider.label}.json"
    return RAW / f"{image_id}__b1-prompt-{version}.json"


def has_valid(image_id, version, provider=None):
    p = raw_path(image_id, version, provider)
    return p.exists() and not json.loads(p.read_text())["validation"]["errors"]


def pick(limit, image_ids=None, sample=None):
    if sample:  # Stage 4 evaluation sample (select_vlm_sample.py); keeps its order
        return [SimpleNamespace(mapillary_id=r["image_id"], local_image_path=r["local_image_path"],
                                street_id=r["street_osm_id"] if r["street_osm_id"] is not None else float("nan"),
                                street_name=r["street_name"])
                for r in json.loads(Path(sample).read_text())["images"]]
    g = gpd.read_file(IMAGES)
    if image_ids:
        g = g[g.mapillary_id.isin(image_ids)]
        missing = set(image_ids) - set(g.mapillary_id)
        if missing:
            raise SystemExit(f"image ids not in {IMAGES}: {sorted(missing)}")
        return [r for i in image_ids for r in g[g.mapillary_id == i].itertuples()]
    g = g[g.selected & (g.camera_type == "perspective") & g.local_image_path.notna()].sort_values("mapillary_id")
    first = g.drop_duplicates("street_name")  # one image per street first, then the rest
    return (list(first.itertuples()) + [r for r in g.itertuples() if r.Index not in first.index])[:limit]


def rebuild_jsonl(provider=None):
    raw_dir, out = (RAW, OUT) if provider is None else (provider.raw, provider.out)
    n = 0
    with out.open("w") as f:
        for p in sorted(raw_dir.glob("*.json")):
            rec = json.loads(p.read_text())
            if rec["validation"]["errors"]:
                continue
            for o in rec["parsed"]["observations"]:
                f.write(json.dumps({
                    "image_id": rec["image_id"], "local_image_path": rec["local_image_path"],
                    "category": o["category"], "status": o["status"], "observation": o["observation"].strip(),
                    "confidence": float(o["confidence"]), "confidence_is_uncalibrated": True,
                    "model": rec["model"], "model_version": rec["model_version"],
                    "inference_timestamp": rec["inference_timestamp"], "schema_version": rec["schema_version"],
                    "prompt_version": rec["prompt_version"],
                    **({"source": "NVIDIA hosted VLM"} if provider is None else
                       {"source": provider.source, "provider": "groq"}),
                    "raw_response_path": str(p), "image_usable": rec["parsed"].get("image_quality", {}).get("usable"),
                    "validation_warnings": [w for w in rec["validation"]["warnings"]
                                            if w.startswith(o["category"] + ":")],
                }, ensure_ascii=False) + "\n")
                n += 1
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=3, help="number of images to send (default 3)")
    ap.add_argument("--prompt-version", choices=sorted(PROMPTS), default="v1")
    ap.add_argument("--image-ids", nargs="+", help="exact Mapillary image IDs (overrides --limit selection)")
    ap.add_argument("--sample", help="evaluation sample JSON (e.g. data/processed/vlm_evaluation_sample.json)")
    ap.add_argument("--force", action="store_true", help="re-run images that already have a valid response")
    ap.add_argument("--provider", choices=["nvidia", "groq"], default="nvidia")
    a = ap.parse_args()
    provider = GROQ if a.provider == "groq" else None
    if provider and (a.prompt_version != "v2" or not GROQ_KEY):
        raise SystemExit("groq comparison requires --prompt-version v2 and GROQ_API_KEY in .env")
    (RAW if provider is None else provider.raw).mkdir(parents=True, exist_ok=True)
    version, prompt = a.prompt_version, PROMPTS[a.prompt_version]
    pv = f"b1-prompt-{version}" if provider is None else provider.label

    total = {"calls": 0, "answered": 0, "valid": 0, "failed": 0, "attempts": 0, "retries": 0, "http_429": 0,
             "http_503": 0}
    for r in pick(a.limit, a.image_ids, a.sample):
        if has_valid(r.mapillary_id, version, provider) and not a.force:
            print(f"cached   {r.mapillary_id} ({pv})")
            continue
        img = Path(r.local_image_path)
        ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
        total["calls"] += 1
        try:
            resp, stats = post(request_body(img, prompt, provider), provider=provider)
        except VLMError as e:
            total["failed"] += 1
            for k in ("attempts", "retries", "http_429", "http_503"):
                total[k] += e.stats[k]
            print(f"FAILED   {r.mapillary_id}: {safe(e)}")
            if provider is not None and e.kind in ("malformed_request", "authentication_failed",
                                                   "model_or_endpoint_not_found"):
                print("Stopping: fatal error for the experimental provider (not retried, next images not sent).")
                break
            continue
        for k in ("attempts", "retries", "http_429", "http_503"):
            total[k] += stats[k]
        total["answered"] += 1
        text = resp["choices"][0]["message"].get("content") if resp.get("choices") else None
        parsed, errors, warnings = parse_and_validate(text)
        total["valid"] += not errors
        extra = {} if provider is None else {
            "provider": "groq", "system_fingerprint": resp.get("system_fingerprint"), "model_version": None,
            "prompt_source_version": "b1-prompt-v2", "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest()}
        raw_path(r.mapillary_id, version, provider).write_text(json.dumps({
            "image_id": r.mapillary_id, "local_image_path": str(img),
            "image_sha256": hashlib.sha256(img.read_bytes()).hexdigest(),
            "street_id": None if pd.isna(r.street_id) else int(r.street_id),
            "model": MODEL if provider is None else provider.model, "response_model": resp.get("model"),
            "model_version": resp.get("system_fingerprint"),  # None: the hosted API reports no version
            "endpoint": f"{BASE_URL if provider is None else provider.base_url}/chat/completions",
            "params": PARAMS if provider is None else provider.params, "prompt_version": pv, "schema_version": SCHEMA_VERSION, "prompt": prompt,
            "inference_timestamp": ts, "api_stats": stats, "raw_response": resp, "parsed": parsed,
            "validation": {"errors": errors, "warnings": warnings}, **extra,
        }, ensure_ascii=False, indent=1))
        u = (resp.get("usage") or {})
        print(f"{'valid' if not errors else 'INVALID':8} {r.mapillary_id} ({r.street_name}) {stats['latency_s']} s, "
              f"tokens {u.get('prompt_tokens')}/{u.get('completion_tokens')}, retries {stats['retries']}, "
              f"errors={errors} warnings={warnings}")

    n = rebuild_jsonl(provider)
    print(f"\n{pv}: {total}")
    print(f"Raw responses: {RAW if provider is None else provider.raw}/  |  Observations: {n} lines in "
          f"{OUT if provider is None else provider.out}")


if __name__ == "__main__":
    main()
