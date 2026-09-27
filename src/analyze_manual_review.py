"""Summarise HUMAN review labels per category (local files only, read-only). No overall score, no ranking.

Run: uv run python src/analyze_manual_review.py [--file <review csv>]   # default: NVIDIA review file (27 images)
     uv run python src/analyze_manual_review.py --file data/processed/vlm_groq_quality_review_observations.csv

Reviewers fill `manual_label` with: correct | incorrect | uncertain (empty = not reviewed) and optionally `manual_note`.
Labels judge the VLM statement against the image only. Notes are shown verbatim, never converted into labels or reasons.
Boundary groups are keyword groupings of the MODEL's statements (what the model said it saw), to support the
category-boundary analysis; they are not ground-truth object types.
"""
import argparse
import csv
import re
from collections import Counter
from pathlib import Path

from run_vlm import CATEGORIES

LABELS = ("correct", "incorrect", "uncertain")
PRIORITY = ["cycling_infrastructure", "street_furniture", "barriers", "curb", "lighting", "public_transport",
            "signage", "pedestrians", "cyclists", "motor_vehicles"]
ORDER = PRIORITY + [c for c in CATEGORIES if c not in PRIORITY]
DEFAULT = Path("data/processed/vlm_quality_review_observations.csv")
INSPECTABLE = 5  # categories with at least this many human labels are marked as worth inspecting (not significant)
BOUNDARY_GROUPS = {  # category -> [(group, regex over the model statement)], first match wins
    "cycling_infrastructure": [("bicycle rack / bicycle parking", r"rack|bicycle parking|parked bicycle"),
                               ("cycle lane / track / marking", r"lane|track|marking|path")],
    "street_furniture": [("bench", r"bench"), ("bin", r"\bbin|trash|waste"), ("bollard", r"bollard"),
                         ("bicycle rack", r"bicycle rack|bike rack"), ("fence / railing", r"fence|railing"),
                         ("sign / advertising", r"sign|advertis|pillar|column|poster"),
                         ("pole", r"pole"), ("other object", r".")],
    "barriers": [("fence", r"fence"), ("railing / guardrail", r"railing|guardrail|rail\b"),
                 ("bollard / post", r"bollard|post"), ("gate", r"gate"), ("other", r".")],
    "curb": [("raised curb", r"raised"), ("cobblestone", r"cobble"), ("gutter / drainage", r"gutter|drain"),
             ("other edge", r".")],
    "lighting": [("lamp on pole / lamp post", r"pole|post"), ("facade / building lamp", r"facade|façade|building"),
                 ("overhead / wire", r"overhead|wire|hanging"), ("daylight wording", r"daylight|sun"), ("other", r".")],
    "public_transport": [("tram / tracks / overhead wires", r"tram|track|rail|overhead"), ("bus", r"\bbus"),
                         ("stop / platform / shelter", r"stop|platform|shelter"), ("other", r".")],
}


def fields(r):
    """Normalise NVIDIA and Groq review rows to (status, observation, confidence)."""
    return (r.get("status") or r.get("groq_status", ""), r.get("observation") or r.get("groq_observation", ""),
            r.get("confidence") or r.get("groq_confidence", ""))


def summarise(rows):
    """{category: Counter(label)}, plus rows with labels outside the allowed set."""
    out, bad = {c: Counter() for c in ORDER}, []
    for r in rows:
        label = (r.get("manual_label") or "").strip().lower()
        if label and label not in LABELS:
            bad.append((r["image_id"], r["category"], r["manual_label"]))
            continue
        out.setdefault(r["category"], Counter())[label or "unreviewed"] += 1
    return out, bad


def boundary(rows):
    """{category: {group: Counter(label)}} over VISIBLE statements only (what the model claimed to see)."""
    out = {}
    for r in rows:
        status, obs, _ = fields(r)
        if r["category"] not in BOUNDARY_GROUPS or status != "visible":
            continue
        group = next(g for g, pat in BOUNDARY_GROUPS[r["category"]] + [("other", r".")] if re.search(pat, obs, re.I))
        label = (r.get("manual_label") or "").strip().lower() or "unreviewed"
        out.setdefault(r["category"], {}).setdefault(group, Counter())[label] += 1
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", type=Path, default=DEFAULT)
    ap.add_argument("--examples", type=int, default=40, help="max disagreement examples to print")
    ap.add_argument("--batch", choices=["all", "recovered"], default="all",
                    help="recovered = Stage 7 first annotation batch (6 locally recovered images)")
    a = ap.parse_args()
    rows = list(csv.DictReader(a.file.open()))
    if a.batch == "recovered":
        rows = [r for r in rows if r.get("vlm_source") == "recovered_v2"]
    s, bad = summarise(rows)
    labelled = [r for r in rows if (r.get("manual_label") or "").strip().lower() in LABELS]
    print(f"{a.file}: {len(rows)} observations in {len({r['image_id'] for r in rows})} images; "
          f"{len(labelled)} reviewed in {len({r['image_id'] for r in labelled})} images; "
          f"{sum(bool((r.get('manual_note') or '').strip()) for r in rows)} notes")
    if "vlm_source" in rows[0]:
        print("by VLM source (reviewed/total):", {src: f"{sum(r in labelled for r in rows if r['vlm_source'] == src)}/"
                                                       f"{sum(r['vlm_source'] == src for r in rows)}"
                                                 for src in sorted({r['vlm_source'] for r in rows})})
    print(f"\n{'category (review priority order)':34} {'reviewed':>8} {'correct':>8} {'incorrect':>9} {'uncertain':>9} "
          f"{'unreviewed':>10}")
    for c in ORDER:
        x = s.get(c, Counter())
        n = sum(x[k] for k in LABELS)
        print(f"{c:34} {n:>8} {x['correct']:>8} {x['incorrect']:>9} {x['uncertain']:>9} {x['unreviewed']:>10}"
              f"{'   <- inspectable (>= %d labels)' % INSPECTABLE if n >= INSPECTABLE else ''}")
    if bad:
        print(f"\nLabels outside {LABELS} (not counted): {bad}")

    print("\n== Model statements by boundary group (visible only) and human label")
    for c, groups in boundary(rows).items():
        print(f"  {c}")
        for g, cnt in groups.items():
            print(f"      {g:34} {dict(cnt)}")

    dis = [r for r in labelled if r["manual_label"].strip().lower() in ("incorrect", "uncertain")]
    print(f"\n== Disagreements / uncertain human labels: {len(dis)} (notes verbatim; reasons not inferred)")
    for r in sorted(dis, key=lambda r: (ORDER.index(r["category"]) if r["category"] in ORDER else 99, r["image_id"]))[
            :a.examples]:
        status, obs, _ = fields(r)
        print(f"  {r['image_id']} {r['category']:22} [{r.get('model', 'groq')} {r.get('vlm_source', '')}] "
              f"model: {status:11} {obs}\n      human: {r['manual_label']:9} note: {r.get('manual_note', '')}")
    if not labelled:
        print("\nNo human labels yet: nothing can be concluded about correctness.")


if __name__ == "__main__":
    main()
