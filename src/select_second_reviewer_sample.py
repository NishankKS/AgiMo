"""Stage 7 (Phase 5): deterministic second-reviewer subset from the 6 recovered images (local files only).

Run: uv run python src/select_second_reviewer_sample.py
Writes: data/processed/manual_review_second_reviewer_sample.csv

4 observations per priority category (24 total), mixing statuses where available; seed 0. The file contains image
metadata and model output ONLY: reviewer 1 labels/notes and provider comparisons are never included, so reviewer 2
judges independently. Existing reviewer2_label / reviewer2_note values are kept when the file is regenerated.
"""
import csv
import json
import random
from collections import defaultdict
from pathlib import Path

RECOVERED = Path("data/processed/vlm_recovered_observations.jsonl")
SAMPLE = Path("data/processed/vlm_evaluation_sample.json")
OUT = Path("data/processed/manual_review_second_reviewer_sample.csv")
CATEGORIES = ["cycling_infrastructure", "street_furniture", "barriers", "curb", "lighting", "public_transport"]
PER_CATEGORY, SEED = 4, 0
FIELDS = ["image_id", "category", "street_name", "captured_at", "sequence_id", "local_image_path", "model",
          "prompt_version", "vlm_source", "status", "observation", "confidence", "confidence_is_uncalibrated",
          "reviewer2_label", "reviewer2_note"]


def select(obs, per_category=PER_CATEGORY, seed=SEED):
    """Per category: round-robin over statuses (fixed order), images in seeded order. Deterministic."""
    rng = random.Random(seed)
    picked = []
    for c in CATEGORIES:
        by_status = defaultdict(list)
        for o in sorted((o for o in obs if o["category"] == c), key=lambda o: o["image_id"]):
            by_status[o["status"]].append(o)
        for lst in by_status.values():
            rng.shuffle(lst)
        queues = [by_status[s] for s in ("uncertain", "visible", "not_visible") if by_status[s]]
        n = 0
        while n < per_category and any(queues):
            for q in queues:
                if q and n < per_category:
                    picked.append(q.pop(0))
                    n += 1
    return picked


def main():
    obs = [json.loads(line) for line in RECOVERED.read_text().splitlines()]
    meta = {s["image_id"]: s for s in json.loads(SAMPLE.read_text())["images"]}
    kept = {}
    if OUT.exists():
        kept = {(r["image_id"], r["category"]): (r["reviewer2_label"], r["reviewer2_note"])
                for r in csv.DictReader(OUT.open())}
    rows = []
    for o in select(obs):
        m = meta[o["image_id"]]
        lab, note = kept.get((o["image_id"], o["category"]), ("", ""))
        rows.append({"image_id": o["image_id"], "category": o["category"], "street_name": m["street_name"],
                     "captured_at": m["captured_at"], "sequence_id": m["sequence_id"],
                     "local_image_path": o["local_image_path"], "model": o["model"],
                     "prompt_version": o["prompt_version"], "vlm_source": "recovered_v2", "status": o["status"],
                     "observation": o["observation"], "confidence": o["confidence"],
                     "confidence_is_uncalibrated": o["confidence_is_uncalibrated"],
                     "reviewer2_label": lab, "reviewer2_note": note})
    with OUT.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    by = defaultdict(lambda: defaultdict(int))
    for r in rows:
        by[r["category"]][r["status"]] += 1
    print(f"Wrote {OUT}: {len(rows)} observations from {len({r['image_id'] for r in rows})} images")
    for c in CATEGORIES:
        print(f"  {c:24} {dict(by[c])}")


if __name__ == "__main__":
    main()
