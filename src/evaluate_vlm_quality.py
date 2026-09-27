"""Stage 4 (Phase 5): descriptive quality evaluation of V2 observations on the evaluation sample. Local files only.

Run: uv run python src/evaluate_vlm_quality.py

Reads:  data/processed/vlm_evaluation_sample.json, data/processed/vlm_observations.jsonl, data/raw/vlm/*__b1-prompt-v2.json
Writes: data/processed/vlm_quality_review.csv               one row per image (+ status per category)
        data/processed/vlm_quality_review_observations.csv  one row per observation, empty manual_* columns for reviewers
No Neo4j access, no API calls. Flags below are keyword prompts for MANUAL review, not correctness judgements.
"""
import csv
import json
import re
import statistics
from collections import Counter, defaultdict
from pathlib import Path

from run_vlm import CATEGORIES, OUT as OBS, RAW, STATUS

PV = "b1-prompt-v2"
SAMPLE = Path("data/processed/vlm_evaluation_sample.json")
REVIEW = Path("data/processed/vlm_quality_review.csv")
REVIEW_OBS = Path("data/processed/vlm_quality_review_observations.csv")

# Known Stage 2 failure modes -> (category, status filter or None, regex). Hits need a human look at the image.
FLAGS = {
    "vehicle type: public transport described as bus": ("public_transport", "visible", r"\bbus"),
    "lighting described via daylight/sun/shadow": ("lighting", None, r"daylight|sunlight|\bsun\b|shadow|bright"),
    "lighting visible (check fixture type, e.g. overhead wire lamps)": ("lighting", "visible", r"."),
    "capture equipment mentioned": (None, None, r"handlebar|dashboard|\bhood\b|mirror|camera|capture|helmet"),
    "curb visible (check for over-claim on shared surfaces)": ("curb", "visible", r"."),
    "street furniture visible (check for hallucination)": ("street_furniture", "visible", r"."),
    "cycling infrastructure visible (check it is infrastructure)": ("cycling_infrastructure", "visible", r"."),
    "sidewalk on one side only": ("sidewalk", "visible", r"^(?!.*\bboth\b).*\b(left|right)\b"),
}


def load(sample_path=SAMPLE, obs_path=OBS, raw_dir=RAW):
    sample = json.loads(Path(sample_path).read_text())["images"]
    ids = [s["image_id"] for s in sample]
    recs = [json.loads(line) for line in Path(obs_path).read_text().splitlines() if line.strip()]
    obs = [r for r in recs if r.get("prompt_version") == PV and r.get("image_id") in ids]
    raws = {i: json.loads((Path(raw_dir) / f"{i}__{PV}.json").read_text())
            for i in ids if (Path(raw_dir) / f"{i}__{PV}.json").exists()}
    return sample, obs, raws


def flags(obs):
    """{flag: [(image_id, category, observation)]} plus fence/barrier double counting."""
    out = defaultdict(list)
    for o in obs:
        for name, (cat, status, pat) in FLAGS.items():
            if (cat in (None, o["category"])) and status in (None, o["status"]) and re.search(pat, o["observation"], re.I):
                if cat is None and o["status"] != "visible":
                    continue
                out[name].append((o["image_id"], o["category"], o["observation"]))
    by = {(o["image_id"], o["category"]): o for o in obs}
    for i in {o["image_id"] for o in obs}:
        sf, ba = by.get((i, "street_furniture")), by.get((i, "barriers"))
        if sf and ba and sf["status"] == ba["status"] == "visible":
            shared = set(re.findall(r"fence|railing|bollard|barrier|post", sf["observation"], re.I)) & \
                     set(re.findall(r"fence|railing|bollard|barrier|post", ba["observation"], re.I))
            if shared:
                out["same object in street_furniture and barriers"].append((i, "street_furniture+barriers",
                                                                             f"{sorted(shared)}"))
    return out


def evaluate(sample, obs, raws):
    ids = [s["image_id"] for s in sample]
    r = {"sample": {}, "vlm": {}, "diversity": {}}
    street = lambda s: s["street_name"] or (f"way/{s['street_osm_id']}" if s["street_osm_id"] else "unlinked")
    per_street = Counter(street(s) for s in sample)
    r["sample"] = {"images": len(sample), "perspective": sum(s["camera_type"] == "perspective" and not s["is_pano"]
                                                              for s in sample),
                   "street_names": len(per_street), "street_ways": len({s["street_osm_id"] for s in sample if s["street_osm_id"]}),
                   "sequences": len({s["sequence_id"] for s in sample}),
                   "years": dict(sorted(Counter(s["captured_at"][:4] for s in sample).items())),
                   "images_per_street": dict(per_street.most_common()),
                   "linked": sum(s["association_status"] == "linked" for s in sample),
                   "unlinked": sum(s["association_status"] != "linked" for s in sample)}
    valid = [i for i in ids if i in raws and not raws[i]["validation"]["errors"]]
    keys = Counter((o["image_id"], o["category"]) for o in obs)
    conf = [o["confidence"] for o in obs]
    stats = [raws[i].get("api_stats") or {} for i in valid]
    usage = [raws[i]["raw_response"].get("usage") or {} for i in valid]
    r["vlm"] = {
        "valid_responses": len(valid), "missing_or_invalid_responses": [i for i in ids if i not in valid],
        "observations": len(obs), "observations_per_image": dict(Counter(Counter(o["image_id"] for o in obs).values())),
        "duplicates": sum(n - 1 for n in keys.values() if n > 1),
        "unexpected_categories": sorted({o["category"] for o in obs} - set(CATEGORIES)),
        "unexpected_statuses": sorted({o["status"] for o in obs} - STATUS),
        "missing_categories": {i: [c for c in CATEGORIES if (i, c) not in keys] for i in valid
                               if any((i, c) not in keys for c in CATEGORIES)},
        "status": dict(Counter(o["status"] for o in obs)),
        "by_category": {c: dict(Counter(o["status"] for o in obs if o["category"] == c)) for c in CATEGORIES},
        "confidence": {"min": min(conf), "median": statistics.median(conf), "max": max(conf),
                       "share_ge_0_9": round(sum(c >= 0.9 for c in conf) / len(conf), 3),
                       "values": dict(sorted(Counter(conf).items()))} if conf else {},
        "uncalibrated_flag_all_true": all(o.get("confidence_is_uncalibrated") is True for o in obs),
        "validation_warnings": [w for i in valid for w in raws[i]["validation"]["warnings"]],
        "models": sorted({o["model"] for o in obs}), "model_versions": sorted({str(o["model_version"]) for o in obs}),
        "prompt_versions": sorted({o["prompt_version"] for o in obs}),
        "schema_versions": sorted({o["schema_version"] for o in obs}),
        "api": {"retries": sum(s.get("retries", 0) for s in stats), "http_429": sum(s.get("http_429", 0) for s in stats),
                "http_503": sum(s.get("http_503", 0) for s in stats),
                "latency_s": [min(s["latency_s"] for s in stats if s.get("latency_s")),
                              max(s["latency_s"] for s in stats if s.get("latency_s"))] if stats else None,
                "prompt_tokens": sorted(u.get("prompt_tokens") for u in usage),
                "completion_tokens": sorted(u.get("completion_tokens") for u in usage)},
    }
    for dim, counts in (("street", per_street), ("sequence", Counter(s["sequence_id"] for s in sample)),
                        ("year", Counter(s["captured_at"][:4] for s in sample))):
        top, n = counts.most_common(1)[0]
        r["diversity"][dim] = {"groups": len(counts), "largest_group": top, "largest_share": round(n / len(sample), 3),
                               "top3_share": round(sum(v for _, v in counts.most_common(3)) / len(sample), 3),
                               "singletons": sum(v == 1 for v in counts.values())}
    return r


RECOVERED = Path("data/processed/vlm_recovered_observations.jsonl")  # Stage 6 local recoveries (separate file)


def review_observations(obs):
    """Valid V2 observations + locally recovered ones (Stage 6), each tagged with vlm_source. No duplicates."""
    rows = [{**o, "vlm_source": "valid_v2"} for o in obs]
    have = {(o["image_id"], o["category"]) for o in obs}
    if RECOVERED.exists():
        for line in RECOVERED.read_text().splitlines():
            o = json.loads(line)
            if (o["image_id"], o["category"]) not in have:
                rows.append({**o, "vlm_source": "recovered_v2"})
    return rows


def existing_labels(path=None):
    """Human labels already entered, keyed by (image_id, category); never overwritten when regenerating."""
    path = path or REVIEW_OBS  # resolved at call time
    if not path.exists():
        return {}
    return {(r["image_id"], r["category"]): (r.get("manual_label", ""), r.get("manual_note", ""))
            for r in csv.DictReader(path.open())}


def write_review(sample, obs, raws):
    labels = existing_labels()
    by = defaultdict(dict)
    for o in review_observations(obs):
        by[o["image_id"]][o["category"]] = o
    with REVIEW.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["image_id", "street_name", "street_osm_id", "captured_at", "sequence_id", "local_image_path",
                    "vlm_source", "observation_count", "visible_count", "not_visible_count", "uncertain_count"]
                   + [f"{c}_status" for c in CATEGORIES])
        for s in sample:
            o = by.get(s["image_id"], {})
            st = Counter(x["status"] for x in o.values())
            src = next(iter({x["vlm_source"] for x in o.values()}), "no_valid_v2")
            w.writerow([s["image_id"], s["street_name"], s["street_osm_id"], s["captured_at"], s["sequence_id"],
                        s["local_image_path"], src, len(o), st["visible"], st["not_visible"], st["uncertain"]]
                       + [o.get(c, {}).get("status", "") for c in CATEGORIES])
    with REVIEW_OBS.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["image_id", "street_name", "captured_at", "sequence_id", "local_image_path", "vlm_source",
                    "category", "status", "observation", "confidence", "confidence_is_uncalibrated", "model",
                    "prompt_version", "raw_response_path", "manual_label", "manual_note"])  # manual_* = human review
        for s in sample:
            for c in CATEGORIES:
                o = by.get(s["image_id"], {}).get(c)
                if o:
                    lab, note = labels.get((s["image_id"], c), ("", ""))
                    w.writerow([s["image_id"], s["street_name"], s["captured_at"], s["sequence_id"],
                                s["local_image_path"], o["vlm_source"], c, o["status"], o["observation"],
                                o["confidence"], o["confidence_is_uncalibrated"], o["model"], o["prompt_version"],
                                o["raw_response_path"], lab, note])


def main():
    sample, obs, raws = load()
    r = evaluate(sample, obs, raws)
    write_review(sample, obs, raws)
    s, v, d = r["sample"], r["vlm"], r["diversity"]
    print("== SAMPLE")
    for k, x in s.items():
        print(f"  {k}: {x}")
    print("\n== VLM OUTPUT (V2)")
    for k in ("valid_responses", "missing_or_invalid_responses", "observations", "observations_per_image", "duplicates",
              "unexpected_categories", "unexpected_statuses", "missing_categories", "status", "confidence",
              "uncalibrated_flag_all_true", "validation_warnings", "models", "model_versions", "prompt_versions",
              "schema_versions", "api"):
        print(f"  {k}: {v[k]}")
    n_img = v["valid_responses"] or 1
    print("\n== STATUS BY CATEGORY (n images = %d)" % v["valid_responses"])
    print(f"  {'category':24} {'visible':>12} {'not_visible':>12} {'uncertain':>12}")
    for c, st in v["by_category"].items():
        print(f"  {c:24} " + " ".join(f"{st.get(k, 0):>4} ({100 * st.get(k, 0) / n_img:4.0f}%)"
                                      for k in ("visible", "not_visible", "uncertain")))
    print("\n== DIVERSITY")
    for k, x in d.items():
        print(f"  {k}: {x}")
    print("\n== KNOWN FAILURE MODES: flags for manual review (not correctness judgements)")
    for name, hits in flags(obs).items():
        print(f"  {name}: {len(hits)}")
        for h in hits[:40]:
            print(f"      {h[0]} {h[1]}: {h[2]}")
    print(f"\nWrote {REVIEW} and {REVIEW_OBS}")


if __name__ == "__main__":
    main()
