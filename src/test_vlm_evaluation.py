"""Stage 4 sanity checks: sample selection, V2 outputs, baseline preservation, credentials, no Neo4j writes.
Checks structure and provenance only; never whether an observation is visually correct.

Run: uv run python src/test_vlm_evaluation.py
"""
import csv
import hashlib
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

import select_vlm_sample as sel
from evaluate_vlm_quality import PV, REVIEW, REVIEW_OBS, SAMPLE, evaluate, load
from run_vlm import ABSENCE, CATEGORIES, STATUS

load_dotenv()

# --- selection logic (dummy records) ---------------------------------------------------------------------
def p(i, cam="perspective", pano=False, street="A", seq="s1", year="2020"):
    return {"mapillary_id": i, "camera_type": cam, "is_pano": pano, "street_name": street, "street_id": 1,
            "sequence_id": seq, "captured_at": f"{year}-01-01T00:00:00"}


dummy = [p(i) for i in sel.ORIGINAL_V2] + [p("f", cam="fisheye"), p("pano", cam="spherical", pano=True),
                                            p("n", cam=None)] + \
        [p(f"x{k}", street=f"S{k % 4}", seq=f"q{k}", year=str(2014 + k % 5)) for k in range(12)]
a = sel.select(dummy, 10, seed=0)
assert [x["mapillary_id"] for x, _ in a] == [x["mapillary_id"] for x, _ in sel.select(dummy, 10, seed=0)], "deterministic"
ids = [x["mapillary_id"] for x, _ in a]
assert len(ids) == len(set(ids)) == 10, "no duplicates"
assert not {"f", "pano", "n"} & set(ids), "only perspective"
assert ids[:3] == sel.ORIGINAL_V2 and all(r == "original_v2_image" for _, r in a[:3])
assert len({x["street_name"] for x, _ in a[3:7]}) == 4, "new streets first"

# --- the real sample file ----------------------------------------------------------------------------------
sample = json.loads(SAMPLE.read_text())["images"]
sids = [s["image_id"] for s in sample]
assert len(sids) == len(set(sids)), "no duplicate image ids in sample"
assert all(s["camera_type"] == "perspective" and not s["is_pano"] for s in sample), "perspective only"
assert set(sel.ORIGINAL_V2) <= set(sids)
assert all(Path(s["local_image_path"]).exists() for s in sample)

# --- V2 outputs for the sample -------------------------------------------------------------------------------
sample, obs, raws = load()
r = evaluate(sample, obs, raws)["vlm"]
assert {o["prompt_version"] for o in obs} == {PV}, "V2 only"
per_image = {}
for o in obs:
    per_image.setdefault(o["image_id"], []).append(o["category"])
assert all(sorted(c) == sorted(CATEGORIES) for c in per_image.values()), "exactly the 16 categories per image"
assert r["duplicates"] == 0 and not r["unexpected_categories"] and not r["unexpected_statuses"]
assert all(o["status"] in STATUS for o in obs)
assert all(isinstance(o["confidence"], (int, float)) and not isinstance(o["confidence"], bool)
           and 0 <= o["confidence"] <= 1 for o in obs)
assert all(o["confidence_is_uncalibrated"] is True for o in obs)
assert not any(o["status"] == "absent" for o in obs), "not_visible is never converted to absent"
for f in (REVIEW, REVIEW_OBS):  # our generated files must not introduce 'absent'
    for row in csv.DictReader(f.open()):
        assert "absent" not in {v for k, v in row.items() if k.endswith("status")}, f
n_abs = sum(o["status"] == "not_visible" and bool(ABSENCE.search(o["observation"])) for o in obs)
print(f"(info) model-written absence wording on not_visible: {n_abs}")

# --- baseline V1/V2 raw files untouched ----------------------------------------------------------------------
manifest = json.loads(Path("data/processed/vlm_baseline_sha256.json").read_text())["sha256"]
for path, digest in manifest.items():
    assert hashlib.sha256(Path(path).read_bytes()).hexdigest() == digest, f"baseline changed: {path}"

# --- credentials never in generated files or logs ------------------------------------------------------------
secrets = [os.environ[k].encode() for k in ("MAPILLARY_ACCESS_TOKEN", "NVIDIA_API_KEY") if os.environ.get(k)]
scan = [p for d in ("data/processed", "data/raw/vlm", "data/raw/mapillary", "data/visualizations", "docs", "src")
        for p in Path(d).rglob("*") if p.is_file() and p.suffix != ".jpg"]
scan += [Path(x) for x in sys.argv[1:]]  # optional extra log files
leaks = [str(p) for p in scan if any(s in p.read_bytes() for s in secrets)]
assert not leaks, f"credential found in: {leaks}"

# --- evaluation/review never touch Neo4j ----------------------------------------------------------------------
import review_vlm_results  # noqa: E402,F401
assert "neo4j" not in sys.modules, "evaluation/review code must not load the Neo4j driver"
print(f"vlm evaluation checks passed ({len(scan)} files scanned for credentials)")
