"""Stage 5 checks: baselines frozen, Groq data separate and well-formed, no secrets/Authorization in outputs,
report scripts make no API calls and never touch Neo4j or the Stage 3 importer. Structure only, never correctness.

Run: uv run python src/test_vlm_stage5.py [extra log files to scan ...]
"""
import csv
import hashlib
import io
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

from dotenv import load_dotenv

import run_vlm as v

load_dotenv()

# --- frozen baselines: 6 original V1/V2 files + full Stage 4 raw state --------------------------------------------
for manifest in ("data/processed/vlm_baseline_sha256.json", "data/processed/vlm_stage4_raw_sha256.json"):
    for path, digest in json.loads(Path(manifest).read_text())["sha256"].items():
        assert hashlib.sha256(Path(path).read_bytes()).hexdigest() == digest, f"changed: {path} ({manifest})"
assert len(list(v.RAW.glob("*.json"))) == 32, "no new NVIDIA raw files in Stage 5"

# --- Groq stored separately, with provider metadata ------------------------------------------------------------------
nv = [json.loads(line) for line in v.OUT.read_text().splitlines()]
assert all(r["source"] == "NVIDIA hosted VLM" and "provider" not in r for r in nv), "no Groq in production JSONL"
assert not any("groq" in r["model"].lower() or "qwen" in r["model"].lower() for r in nv)
gq = [json.loads(line) for line in v.GROQ.out.read_text().splitlines()]
assert gq, "Groq observations exist"
for r in gq:
    assert r["provider"] == "groq" and r["model"] == "qwen/qwen3.8-27b" and r["prompt_version"] == "v2-groq-comparison"
    assert r["source"] == "Groq hosted VLM" and r["schema_version"] == v.SCHEMA_VERSION and r["inference_timestamp"]
    assert r["model_version"] is None, "model version not invented"
    assert r["category"] in v.CATEGORIES and r["status"] in v.STATUS and r["observation"].strip()
    assert isinstance(r["confidence"], float) and 0 <= r["confidence"] <= 1 and r["confidence_is_uncalibrated"] is True
    assert "manual_label" not in r, "manual review kept separate from VLM fields"
per_image = {}
for r in gq:
    per_image.setdefault(r["image_id"], []).append(r["category"])
assert all(sorted(c) == sorted(v.CATEGORIES) for c in per_image.values()), "exactly 16 categories per image"
raws = [json.loads(p.read_text()) for p in v.GROQ.raw.glob("*.json")]
assert raws and all(r["provider"] == "groq" and r["prompt_source_version"] == "b1-prompt-v2" for r in raws)
assert all(r["prompt_sha256"] == hashlib.sha256(v.PROMPT_V2.encode()).hexdigest() for r in raws), "same V2 prompt"
sample_ids = [s["image_id"] for s in json.loads(Path("data/processed/groq_vlm_evaluation_sample.json").read_text())["images"]]
assert len(sample_ids) == 5 == len(set(sample_ids)) and set(per_image) <= set(sample_ids), "only the 5 sample images"

# --- Groq review CSV: VLM fields match the Groq output; labels are separate columns -------------------------------
rows = list(csv.DictReader(open("data/processed/vlm_groq_quality_review_observations.csv")))
g = {(r["image_id"], r["category"]): r for r in gq}
assert len(rows) == len(gq) and all(r["groq_status"] == g[(r["image_id"], r["category"])]["status"] for r in rows)
assert {"manual_label", "manual_note", "nvidia_manual_label"} <= set(rows[0])

# --- provider path: pacing/retry/fatal behaviour with a fake opener (no network) -------------------------------------
class Resp(io.BytesIO):
    headers = {"x-ratelimit-limit-tokens": "8000", "Authorization": "must-not-be-kept"}


def fake(outcomes, seen):
    def opener(req, timeout):
        seen.append(req.full_url)
        o = outcomes.pop(0)
        if isinstance(o, int):
            raise urllib.error.HTTPError(req.full_url, o, "e", {"Retry-After": "3"}, io.BytesIO(b"err"))
        return Resp(json.dumps(o).encode())
    return opener


slept, seen = [], []
v._last_request[0] = -1e9
body, st = v.post({}, opener=fake([429, {"ok": 1}], seen), sleep=slept.append, clock=lambda: 0.0, provider=v.GROQ)
assert body == {"ok": 1} and st["http_429"] == 1 and 3 in slept, "429 honours Retry-After"
assert st["rate_limit_headers"] == {"x-ratelimit-limit-tokens": "8000"}, "only rate-limit headers kept"
assert all(u.startswith(v.GROQ.base_url) for u in seen), "groq provider never calls NVIDIA"
for code in (400, 401, 403):
    seen = []
    try:
        v.post({}, opener=fake([code, {"ok": 1}], seen), sleep=lambda s: None, clock=lambda: 0.0, provider=v.GROQ)
        raise AssertionError("must fail")
    except v.VLMError as e:
        assert len(seen) == 1, f"{code} not retried"
assert v.request_body(Path(v.RAW / "../mapillary/images/904858026737408.jpg"), v.PROMPT_V2)["model"] == v.MODEL
assert v.GROQ_KEY not in v.safe(f"x {v.GROQ_KEY}") and v.KEY not in v.safe(f"x {v.KEY}")

# --- unit checks: diagnosis + manual-review summary ---------------------------------------------------------------
import analyze_manual_review as amr  # noqa: E402
import diagnose_vlm_invalid as dvi  # noqa: E402

ok = json.dumps({"image_quality": {"usable": True, "issues": []}, "observations": [
    {"category": c, "status": "visible", "observation": "x", "confidence": 0.5} for c in v.CATEGORIES]})
assert dvi.diagnose("\n" + ok + "}")["locally_recoverable"] is True
assert dvi.diagnose(ok[:40])["class"] == "malformed/truncated/garbage answer"
assert dvi.diagnose('{"observations": []}')["class"] == "schema mismatch"
assert dvi.diagnose(ok + " note: {x}")["locally_recoverable"] is False
d = json.loads(Path("data/processed/vlm_invalid_diagnosis.json").read_text())
assert len(d) == 8 and sum(x["locally_recoverable"] for x in d) == 6
s, bad = amr.summarise([{"image_id": "1", "category": "curb", "manual_label": "correct", "manual_note": ""},
                        {"image_id": "1", "category": "lighting", "manual_label": "", "manual_note": "looks wrong"},
                        {"image_id": "1", "category": "roadway", "manual_label": "maybe", "manual_note": ""}])
assert s["curb"]["correct"] == 1 and s["lighting"]["unreviewed"] == 1 and s["lighting"]["incorrect"] == 0, \
    "notes are never converted into labels"
assert bad == [("1", "roadway", "maybe")]

# --- report scripts: no API calls, no Neo4j, no Stage 3 importer ----------------------------------------------------
def no_network(*a, **k):
    raise AssertionError("network call from a report script")


v.post, urllib.request.urlopen = no_network, no_network
import compare_vlm_providers  # noqa: E402
import evaluate_vlm_quality  # noqa: E402
import select_groq_sample  # noqa: E402

argv = sys.argv
sys.argv = ["x"]
for mod in (dvi, amr, select_groq_sample, compare_vlm_providers, evaluate_vlm_quality):
    out = io.StringIO()
    stdout, sys.stdout = sys.stdout, out
    try:
        mod.main()
    finally:
        sys.stdout = stdout
sys.argv = argv
assert "neo4j" not in sys.modules, "Stage 5 analysis must not load the Neo4j driver"
assert "import_visual_observations" not in sys.modules, "Stage 3 importer not used"
assert [s["image_id"] for s in json.loads(Path("data/processed/groq_vlm_evaluation_sample.json").read_text())["images"]] \
    == sample_ids, "deterministic Groq sample"

# --- no secrets and no Authorization headers in generated files or logs ----------------------------------------------
secrets = [os.environ[k].encode() for k in ("MAPILLARY_ACCESS_TOKEN", "NVIDIA_API_KEY", "GROQ_API_KEY") if os.environ.get(k)]
files = [p for d in ("data/processed", "data/raw/vlm", "data/raw/vlm_groq", "data/raw/mapillary", "data/visualizations",
                     "docs") for p in Path(d).rglob("*") if p.is_file() and p.suffix != ".jpg"]
files += [Path(x) for x in sys.argv[1:]] + [Path("README.md")]
assert not [str(p) for p in files if any(s in p.read_bytes() for s in secrets)], "credential in output"
# a logged header = an "Authorization" key/value or "Bearer <token-like string>"; prose mentions in docs are fine
auth = [str(p) for p in files if re.search(rb'"authorization"\s*:|authorization:\s*(bearer|oauth)\s+\S{12,}|'
                                          rb'bearer\s+[A-Za-z0-9_\-]{12,}', p.read_bytes(), re.I)]
assert not auth, f"Authorization header text found in: {auth}"
print(f"stage 5 checks passed ({len(files)} files scanned)")
