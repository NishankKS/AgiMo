"""Stage 7 (Phase 5): compare reviewer 1 and reviewer 2 labels on the second-reviewer subset (local files, read-only).

Run: uv run python src/analyze_inter_reviewer.py

Reviewer 1: manual_label/manual_note in data/processed/vlm_quality_review_observations.csv
Reviewer 2: reviewer2_label/reviewer2_note in data/processed/manual_review_second_reviewer_sample.csv
Small subset: this is a check whether the category definitions are understandable, not a formal reliability study.
Neither reviewer is treated as correct.
"""
import csv
from collections import Counter
from pathlib import Path

R1 = Path("data/processed/vlm_quality_review_observations.csv")
R2 = Path("data/processed/manual_review_second_reviewer_sample.csv")
LABELS = ("correct", "incorrect", "uncertain")


def compare(r1_rows, r2_rows):
    """Returns dict with joint, agree, disagreements [(row2, label1, note1)], per-category counts."""
    r1 = {(r["image_id"], r["category"]): r for r in r1_rows}
    joint, agree, dis, per_cat = 0, 0, [], Counter()
    for r in r2_rows:
        a = r1.get((r["image_id"], r["category"]), {})
        l1, l2 = (a.get("manual_label") or "").strip().lower(), (r.get("reviewer2_label") or "").strip().lower()
        if l1 not in LABELS or l2 not in LABELS:
            continue
        joint += 1
        per_cat[(r["category"], l1 == l2)] += 1
        if l1 == l2:
            agree += 1
        else:
            dis.append((r, l1, a.get("manual_note", "")))
    return {"subset": len(r2_rows), "joint": joint, "agree": agree, "disagreements": dis,
            "uncertain_disagreements": sum("uncertain" in (l1, r["reviewer2_label"].strip().lower()) for r, l1, _ in dis),
            "per_category": per_cat}


def main():
    res = compare(list(csv.DictReader(R1.open())), list(csv.DictReader(R2.open())))
    print(f"Second-reviewer subset: {res['subset']} observations; jointly labelled by both reviewers: {res['joint']}")
    if not res["joint"]:
        print("No jointly labelled observations yet: inter-reviewer agreement unresolved / no labels.")
        return
    print(f"Exact agreement: {res['agree']} / {res['joint']}; disagreements: {len(res['disagreements'])} "
          f"(of which involving 'uncertain': {res['uncertain_disagreements']})")
    print("Per category (agree / disagree):")
    for c in sorted({c for c, _ in res["per_category"]}):
        print(f"  {c:24} {res['per_category'][(c, True)]} / {res['per_category'][(c, False)]}")
    print("Disagreements (neither reviewer is treated as correct):")
    for r, l1, n1 in res["disagreements"]:
        print(f"  {r['image_id']} {r['category']:22} model: {r['status']} '{r['observation']}'\n"
              f"      reviewer 1: {l1:9} note: {n1}\n      reviewer 2: {r['reviewer2_label']:9} note: {r['reviewer2_note']}")
    print("Small subset: not a formal reliability estimate.")


if __name__ == "__main__":
    main()
