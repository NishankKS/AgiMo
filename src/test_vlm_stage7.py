"""Stage 7 checks: annotation infrastructure is safe (idempotent, non-destructive merge; labels never touch model
fields; notes never become labels; reviewer 1 and 2 kept apart), analyses handle missing labels, all earlier data
frozen, no API / Neo4j / importer. Never checks whether any observation is visually correct.

Run: uv run python src/test_vlm_stage7.py
"""
import csv
import hashlib
import io
import json
import sys
import urllib.request
from pathlib import Path

import analyze_inter_reviewer as air
import compare_vlm_providers as cmp
import merge_manual_labels as mml
import run_vlm as v
import select_second_reviewer_sample as ssr

MODEL_FIELDS = ["image_id", "category", "status", "observation", "confidence", "model", "prompt_version", "vlm_source"]
ALLOWED = {"correct", "incorrect", "uncertain", ""}

# --- frozen data ------------------------------------------------------------------------------------------------
for m in ("vlm_baseline_sha256.json", "vlm_stage4_raw_sha256.json", "vlm_groq_stage5_sha256.json"):
    for path, digest in json.loads(Path("data/processed", m).read_text())["sha256"].items():
        assert hashlib.sha256(Path(path).read_bytes()).hexdigest() == digest, f"changed: {path}"

# --- label vocabularies + separation of reviewer 1 / reviewer 2 --------------------------------------------------
r1 = list(csv.DictReader(open(mml.TARGETS["nvidia"][0])))
r2 = list(csv.DictReader(open(mml.TARGETS["second"][0])))
assert all(r["manual_label"] in ALLOWED for r in r1) and all(r["reviewer2_label"] in ALLOWED for r in r2)
assert not {"reviewer2_label", "reviewer2_note"} & set(r1[0]), "reviewer 2 fields not in reviewer 1 file"
assert not {"manual_label", "manual_note"} & set(r2[0]), "second-reviewer sample exposes no reviewer 1 label/note"
assert list(r2[0]) == ssr.FIELDS
print(f"(info) human labels: reviewer 1 = {sum(bool(r['manual_label']) for r in r1)}, "
      f"reviewer 2 = {sum(bool(r['reviewer2_label']) for r in r2)}")

# --- recovered observations stay identifiable ------------------------------------------------------------------------
assert sum(r["vlm_source"] == "recovered_v2" for r in r1) == 96
assert all(json.loads(line)["recovery_method"] == "remove_one_trailing_stray_brace"
           for line in Path("data/processed/vlm_recovered_observations.jsonl").read_text().splitlines())

# --- second-reviewer sample: deterministic, priority categories, mixed statuses, recovered images only -------------
rec = [json.loads(line) for line in ssr.RECOVERED.read_text().splitlines()]
a, b = ssr.select(rec), ssr.select(rec)
assert [(o["image_id"], o["category"]) for o in a] == [(o["image_id"], o["category"]) for o in b], "deterministic"
assert len(a) == 24 and {o["category"] for o in a} == set(ssr.CATEGORIES)
assert {o["status"] for o in a} == {"visible", "not_visible", "uncertain"}
assert [(r["image_id"], r["category"]) for r in r2] == [(o["image_id"], o["category"]) for o in a]
assert all(r["vlm_source"] == "recovered_v2" for r in r2)

# --- merge: idempotent, non-destructive, model fields untouched, notes never become labels -------------------------
base = [{"image_id": "1", "category": "curb", "status": "visible", "observation": "o", "confidence": "0.9",
         "model": "m", "prompt_version": "p", "vlm_source": "recovered_v2", "manual_label": "", "manual_note": ""},
        {"image_id": "1", "category": "lighting", "status": "not_visible", "observation": "o2", "confidence": "0.9",
         "model": "m", "prompt_version": "p", "vlm_source": "recovered_v2", "manual_label": "incorrect",
         "manual_note": "lamp on wire"}]
inp = [{"image_id": "1", "category": "curb", "manual_label": "correct", "manual_note": "edge visible"},
       {"image_id": "1", "category": "lighting", "manual_label": "", "manual_note": ""}]  # exported unlabelled row
new, ch, err, conf = mml.merge(base, inp)
assert not err and len(ch) == 1 and new[0]["manual_label"] == "correct"
assert new[1]["manual_label"] == "incorrect" and new[1]["manual_note"] == "lamp on wire", "empty input never clears"
again, ch2, _, _ = mml.merge(new, inp)
assert again == new and ch2 == [], "idempotent"
_, ch3, _, conf3 = mml.merge(new, [{"image_id": "1", "category": "lighting", "manual_label": "correct"}])
assert ch3 == [] and len(conf3) == 1, "existing different label not overwritten"
ow, ch4, _, _ = mml.merge(new, [{"image_id": "1", "category": "lighting", "manual_label": "correct"}], overwrite=True)
assert ow[1]["manual_label"] == "correct" and len(ch4) == 1, "--overwrite is explicit"
nl, ch5, _, _ = mml.merge(base, [{"image_id": "1", "category": "curb", "manual_label": "", "manual_note": "looks wrong"}])
assert nl[0]["manual_label"] == "" and ch5 == [], "a note alone never creates a label"
assert all(r[f] == b0[f] for r, b0 in zip(ow, base) for f in MODEL_FIELDS), "model fields never modified"
assert mml.merge(base, [{"image_id": "1", "category": "curb", "manual_label": "wrong"}])[2], "invalid label rejected"
sec, _, _, _ = mml.merge([{"image_id": "1", "category": "curb", "reviewer2_label": "", "reviewer2_note": ""}],
                         [{"image_id": "1", "category": "curb", "manual_label": "uncertain"}],
                         cols=("reviewer2_label", "reviewer2_note"))
assert sec[0]["reviewer2_label"] == "uncertain" and "manual_label" not in sec[0]

# --- provider comparison (single human label, status level) -------------------------------------------------------
O = cmp.outcome
assert O("", "visible", "visible") == ("unresolved", "") and O("correct", "visible", "")[0] == "unresolved"
assert O("correct", "visible", "visible")[0] == "both agree with human"
assert O("correct", "visible", "not_visible")[0] == "NVIDIA agrees / Groq disagrees"
assert O("incorrect", "not_visible", "visible") == ("Groq agrees / NVIDIA disagrees", "visible")
assert O("incorrect", "not_visible", "not_visible")[0] == "both disagree"
assert O("incorrect", "visible", "not_visible")[0] == "Groq agrees / NVIDIA disagrees"
assert O("incorrect", "visible", "visible")[0] == "unresolved", "Groq's own visible claim is not judged"
assert O("uncertain", "visible", "visible")[0] == O("correct", "uncertain", "visible")[0] == "human uncertain"
assert O("incorrect", "uncertain", "visible")[0] == "unresolved"

# --- inter-reviewer comparison ------------------------------------------------------------------------------------
R1 = [{"image_id": "1", "category": "curb", "manual_label": "correct", "manual_note": "n1"},
      {"image_id": "1", "category": "lighting", "manual_label": "incorrect", "manual_note": ""},
      {"image_id": "2", "category": "curb", "manual_label": "", "manual_note": ""}]
R2 = [{"image_id": "1", "category": "curb", "reviewer2_label": "correct", "reviewer2_note": "", "status": "visible",
       "observation": "o"},
      {"image_id": "1", "category": "lighting", "reviewer2_label": "uncertain", "reviewer2_note": "dark",
       "status": "not_visible", "observation": "o"},
      {"image_id": "2", "category": "curb", "reviewer2_label": "correct", "reviewer2_note": "", "status": "visible",
       "observation": "o"}]
res = air.compare(R1, R2)
assert res["joint"] == 2 and res["agree"] == 1 and len(res["disagreements"]) == 1 and res["uncertain_disagreements"] == 1
assert air.compare(R1, [])["joint"] == 0

# --- analysis scripts: no API calls, no Neo4j, no importer ----------------------------------------------------------
def no_network(*x, **k):
    raise AssertionError("network call in Stage 7")


v.post, urllib.request.urlopen = no_network, no_network
import analyze_manual_review as amr  # noqa: E402
import review_vlm_results as rvr  # noqa: E402

argv, stdout = sys.argv, sys.stdout
try:
    for mod, args in ((amr, []), (amr, ["--batch", "recovered"]), (air, []), (cmp, []), (ssr, []),
                      (rvr, ["--html"]), (rvr, ["--html", "--provider", "second"])):
        sys.argv, sys.stdout = ["x", *args], io.StringIO()
        mod.main()
finally:
    sys.argv, sys.stdout = argv, stdout
assert "neo4j" not in sys.modules and "import_visual_observations" not in sys.modules
page2 = Path("data/visualizations/vlm_second_reviewer_review.html").read_text()
assert "manual_note" not in page2 or all(r["manual_note"] not in page2 for r in r1 if r["manual_note"]), \
    "reviewer 1 notes never shown to reviewer 2"
print("stage 7 checks passed")
