"""Stage 6 checks: local recovery is exact and separate, review files keep VLM fields and human labels apart,
merge/compare handle labels safely, all earlier files are frozen, no API / Neo4j / importer use, no secrets.
Structure and provenance only; never whether an observation is visually correct.

Run: uv run python src/test_vlm_stage6.py
"""
import csv
import hashlib
import io
import json
import os
import re
import shutil
import sys
import tempfile
import urllib.request
from pathlib import Path

from dotenv import load_dotenv

import compare_vlm_providers as cmp
import evaluate_vlm_quality as ev
import merge_manual_labels as mml
import recover_vlm_json as rec
import run_vlm as v

load_dotenv()
KNOWN = {"1391393364587653", "2653450758168746", "463348118303970", "524573645227846", "748701757218369",
         "932582530826779"}

# --- frozen files: V1 + original V2 (6), all Stage 4 raw (32), Stage 5 Groq raw + JSONL --------------------------
for m in ("vlm_baseline_sha256.json", "vlm_stage4_raw_sha256.json", "vlm_groq_stage5_sha256.json"):
    for path, digest in json.loads(Path("data/processed", m).read_text())["sha256"].items():
        assert hashlib.sha256(Path(path).read_bytes()).hexdigest() == digest, f"changed: {path}"

# --- recovery: exactly the known six, one brace only, separate, validator unchanged ------------------------------
assert set(rec.CANDIDATES) == KNOWN and not set(rec.NOT_RECOVERABLE) & KNOWN
ok_obj = json.dumps({"image_quality": {"usable": True, "issues": []}, "observations": [
    {"category": c, "status": "visible", "observation": "x", "confidence": 0.5} for c in v.CATEGORIES]})
assert rec.recover_text(ok_obj + "}")[0] == ok_obj
assert rec.recover_text("\n" + ok_obj + "\n}")[0] == "\n" + ok_obj + "\n"
assert rec.recover_text(ok_obj + "}}")[0] is None, "two braces: not the known pattern"
assert rec.recover_text(ok_obj + " note")[0] is None and rec.recover_text(ok_obj)[0] is None
assert rec.recover_text('{"a": <unk><unk>')[0] is None and rec.recover_text("")[0] is None
report = json.loads(rec.REPORT.read_text())
assert report["candidate_count"] == 6 == report["recovered_count"] and report["rejected_count"] == 0
recovered = [json.loads(line) for line in rec.OUT.read_text().splitlines()]
assert {r["image_id"] for r in recovered} == KNOWN and len(recovered) == 96
for image_id in KNOWN:  # recovered records == what the unchanged validator parses from raw minus one brace
    raw = json.loads((v.RAW / f"{image_id}__b1-prompt-v2.json").read_text())
    text = raw["raw_response"]["choices"][0]["message"]["content"]
    fixed, _ = rec.recover_text(text)
    assert len(fixed) == len(text) - 1
    parsed, errors, _ = v.parse_and_validate(fixed)
    assert errors == [] and v.parse_and_validate(text)[1], "original still invalid; recovered valid"
    got = {r["category"]: (r["status"], r["observation"], r["confidence"]) for r in recovered if r["image_id"] == image_id}
    assert got == {o["category"]: (o["status"], o["observation"].strip(), float(o["confidence"]))
                   for o in parsed["observations"]}
assert all(r["recovery_method"] == "remove_one_trailing_stray_brace" and r["confidence_is_uncalibrated"] is True
           and r["source"] == "NVIDIA hosted VLM" and r["prompt_version"] == "b1-prompt-v2" for r in recovered)
production = [json.loads(line) for line in v.OUT.read_text().splitlines()]
assert not {r["image_id"] for r in production} & (KNOWN | set(rec.NOT_RECOVERABLE)), "production JSONL untouched"

# --- review file: 27 images, VLM fields == sources, labels separate and valid ------------------------------------
rows = list(csv.DictReader(ev.REVIEW_OBS.open()))
src = {(r["image_id"], r["category"]): r for r in production if r["prompt_version"] == "b1-prompt-v2"}
src.update({(r["image_id"], r["category"]): r for r in recovered})
assert len({r["image_id"] for r in rows}) == 27 and len(rows) == 432 == len({(r["image_id"], r["category"]) for r in rows})
assert not {r["image_id"] for r in rows} & set(rec.NOT_RECOVERABLE)
for r in rows:
    s = src[(r["image_id"], r["category"])]
    assert (r["status"], r["observation"], float(r["confidence"])) == (s["status"], s["observation"], s["confidence"])
    assert r["manual_label"] in ("correct", "incorrect", "uncertain", "")
assert {r["vlm_source"] for r in rows} == {"valid_v2", "recovered_v2"}
for path in (Path("data/processed/vlm_groq_quality_review_observations.csv"),):  # Stage 5 file, not used for labels
    assert all(r["manual_label"] in ("correct", "incorrect", "uncertain", "") for r in csv.DictReader(path.open()))

# regenerating the review files keeps human labels and never alters VLM fields
with tempfile.TemporaryDirectory() as d:
    ev.REVIEW, ev.REVIEW_OBS = Path(d, "review.csv"), Path(d, "review_obs.csv")
    shutil.copy("data/processed/vlm_quality_review_observations.csv", ev.REVIEW_OBS)
    tmp = list(csv.DictReader(ev.REVIEW_OBS.open()))
    tmp[0]["manual_label"], tmp[0]["manual_note"] = "incorrect", "test note"
    with ev.REVIEW_OBS.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(tmp[0]))
        w.writeheader()
        w.writerows(tmp)
    ev.write_review(*ev.load())
    again = list(csv.DictReader(ev.REVIEW_OBS.open()))
    assert (again[0]["manual_label"], again[0]["manual_note"]) == ("incorrect", "test note"), "labels preserved"
    assert [(r["status"], r["observation"]) for r in again] == [(r["status"], r["observation"]) for r in rows]

# --- merge: only manual columns change; invalid input changes nothing ----------------------------------------------
base = [{"image_id": "1", "category": "curb", "status": "visible", "observation": "o", "manual_label": "",
         "manual_note": ""}]
new, changes, errors, _ = mml.merge(base, [{"image_id": "1", "category": "curb", "manual_label": "Correct",
                                            "manual_note": "raised edge visible"}])
assert errors == [] and new[0]["manual_label"] == "correct" and new[0]["status"] == "visible" and len(changes) == 1
assert base[0]["manual_label"] == "", "input not mutated"
assert mml.merge(base, [{"image_id": "1", "category": "curb", "manual_label": "maybe"}])[2]
assert mml.merge(base, [{"image_id": "9", "category": "curb", "manual_label": "correct"}])[2]

# --- provider comparison: missing labels -> unresolved (Stage 7 single-label method) --------------------------------
assert cmp.outcome("", "visible", "visible")[0] == "unresolved" and cmp.outcome("correct", "visible", "")[0] == "unresolved"
assert cmp.outcome("correct", "visible", "visible")[0] == "both agree with human"

# --- no API calls, no Neo4j, no importer ----------------------------------------------------------------------------
def no_network(*a, **k):
    raise AssertionError("network call in Stage 6")


v.post, urllib.request.urlopen = no_network, no_network
import analyze_manual_review as amr  # noqa: E402
import review_vlm_results as rvr  # noqa: E402

argv, stdout = sys.argv, sys.stdout
try:
    ev.REVIEW, ev.REVIEW_OBS = Path("data/processed/vlm_quality_review.csv"), Path(
        "data/processed/vlm_quality_review_observations.csv")
    for mod, args in ((rec, []), (amr, []), (cmp, []), (rvr, ["--html"])):
        sys.argv, sys.stdout = ["x", *args], io.StringIO()
        mod.main()
finally:
    sys.argv, sys.stdout = argv, stdout
assert "neo4j" not in sys.modules and "import_visual_observations" not in sys.modules

# --- no secrets, no Authorization headers in outputs -----------------------------------------------------------------
secrets = [os.environ[k].encode() for k in ("MAPILLARY_ACCESS_TOKEN", "NVIDIA_API_KEY", "GROQ_API_KEY") if os.environ.get(k)]
files = [p for d in ("data/processed", "data/raw/vlm", "data/raw/vlm_groq", "data/visualizations", "docs")
         for p in Path(d).rglob("*") if p.is_file() and p.suffix != ".jpg"] + [Path("README.md")]
assert not [str(p) for p in files if any(s in p.read_bytes() for s in secrets)], "credential in output"
assert not [str(p) for p in files if re.search(rb'"authorization"\s*:|bearer\s+[A-Za-z0-9_\-]{12,}', p.read_bytes(), re.I)]
print(f"stage 6 checks passed ({len(files)} files scanned)")
