"""Stage 5 (Phase 5), Part I/J: NVIDIA V2 vs Groq on the 5-image comparison sample (local files only, no API calls).

Run: uv run python src/compare_vlm_providers.py

Reads:  data/processed/groq_vlm_evaluation_sample.json, data/raw/vlm/*__b1-prompt-v2.json, data/raw/vlm_groq/*.json,
        manual labels from data/processed/vlm_quality_review_observations.csv (NVIDIA) and the Groq review CSV
Writes: data/processed/vlm_provider_comparison.csv                 side-by-side, all 16 categories x 5 images
        data/processed/vlm_groq_quality_review_observations.csv    Groq review file (existing manual labels kept)
No correctness is decided here: without a human label a pair is 'unresolved'. No ranking, no score.
Stage 7: one human label per image/category (NVIDIA review file) serves both providers; see outcome().
"""
import csv
import json
from collections import Counter
from pathlib import Path

from run_vlm import CATEGORIES, GROQ, RAW

SAMPLE = Path("data/processed/groq_vlm_evaluation_sample.json")
NVIDIA_REVIEW = Path("data/processed/vlm_quality_review_observations.csv")
GROQ_REVIEW = Path("data/processed/vlm_groq_quality_review_observations.csv")
SIDE_BY_SIDE = Path("data/processed/vlm_provider_comparison.csv")
FOCUS = ["cycling_infrastructure", "street_furniture", "barriers", "curb", "lighting", "public_transport", "signage"]


def outcome(label, nvidia_status, groq_status):
    """Stage 7: ONE human label per image/category (it judges NVIDIA's statement against the image) is used for both
    providers. Groq is compared at STATUS level with the status the label implies; Groq's own text is not judged.
    Returns (class, human_status)."""
    label = (label or "").strip().lower()
    if not label or not groq_status:
        return "unresolved", ""
    if label == "uncertain" or (label == "correct" and nvidia_status == "uncertain"):
        return "human uncertain", "uncertain"
    if label == "correct":
        human = nvidia_status                                   # visible / not_visible confirmed
    elif nvidia_status == "not_visible":
        human = "visible"                                       # incorrect: the category is clearly visible
    elif nvidia_status == "visible" and groq_status == "not_visible":
        human = "not_supported"                                 # NVIDIA's visible claim unsupported; Groq agrees
    else:
        return "unresolved", "unsupported NVIDIA claim; Groq statement unjudged"
    nvidia_ok, groq_ok = label == "correct", groq_status == human or (human == "not_supported")
    return {(True, True): "both agree with human", (True, False): "NVIDIA agrees / Groq disagrees",
            (False, True): "Groq agrees / NVIDIA disagrees", (False, False): "both disagree"}[(nvidia_ok, groq_ok)], human


def raw(provider, image_id):
    p = RAW / f"{image_id}__b1-prompt-v2.json" if provider == "nvidia" else GROQ.raw / f"{image_id}__{GROQ.label}.json"
    return json.loads(p.read_text()) if p.exists() else None


def labels(path):
    if not path.exists():
        return {}
    return {(r["image_id"], r["category"]): (r.get("manual_label", "").strip(), r.get("manual_note", "").strip())
            for r in csv.DictReader(path.open())}


def provider_stats(recs, requested):
    got = [r for r in recs if r]
    valid = [r for r in got if not r["validation"]["errors"]]
    stats = [r.get("api_stats") or {} for r in got]
    obs = [o for r in valid for o in r["parsed"]["observations"]]
    return {"requested": requested, "responses": len(got), "failed_no_response": requested - len(got),
            "valid": len(valid), "invalid": len(got) - len(valid),
            "invalid_reasons": [e for r in got for e in r["validation"]["errors"]],
            "retries": sum(s.get("retries", 0) for s in stats),
            "http_errors": dict(Counter(e.split()[1] for s in stats for e in s.get("errors", []) if e.startswith("HTTP"))),
            "latency_s": sorted(s.get("latency_s") for s in stats if s.get("latency_s")),
            "tokens_total": sorted((r["raw_response"].get("usage") or {}).get("total_tokens") for r in got),
            "observations": len(obs), "status": dict(Counter(o["status"] for o in obs)),
            "confidence_ge_0_9": f"{sum(o['confidence'] >= 0.9 for o in obs)}/{len(obs)}",
            "confidence_eq_1": sum(o["confidence"] == 1 for o in obs),
            "models": sorted({r["model"] for r in got}),
            "fingerprints": sorted({str(r["raw_response"].get("system_fingerprint")) for r in got})}


def main():
    sample = json.loads(SAMPLE.read_text())["images"]
    ids = [s["image_id"] for s in sample]
    street = {s["image_id"]: s["street_name"] or f"way/{s['street_osm_id']}" for s in sample}
    N = {i: raw("nvidia", i) for i in ids}
    G = {i: raw("groq", i) for i in ids}
    nl, gl = labels(NVIDIA_REVIEW), labels(GROQ_REVIEW)  # gl: only to keep the Stage 5 review file intact

    print("== STRUCTURED OUTPUT / API (5 images)")
    for name, R in (("nvidia", N), ("groq", G)):
        print(f"  {name}:")
        for k, v in provider_stats(list(R.values()), len(ids)).items():
            print(f"      {k}: {v}")

    obs = lambda R, i: {o["category"]: o for o in R[i]["parsed"]["observations"]} if R[i] and R[i]["parsed"] and \
        not R[i]["validation"]["errors"] else {}
    rows, agree = [], Counter()
    for i in ids:
        n, g = obs(N, i), obs(G, i)
        for c in CATEGORIES:
            a, b = n.get(c, {}), g.get(c, {})
            nlab, glab = nl.get((i, c), ("", ""))[0], gl.get((i, c), ("", ""))[0]
            cls, human = outcome(nlab, a.get("status", ""), b.get("status", ""))
            same = a.get("status") == b.get("status")
            agree[(c, same)] += 1
            rows.append({"image_id": i, "street": street[i], "category": c,
                         "nvidia_status": a.get("status", ""), "nvidia_observation": a.get("observation", ""),
                         "groq_status": b.get("status", ""), "groq_observation": b.get("observation", ""),
                         "status_same": same, "human_label": nlab, "human_status_implied": human,
                         "resolution": cls})
    with SIDE_BY_SIDE.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)

    # Groq review file: keep any labels already entered; NVIDIA labels are NOT copied (they judge a different
    # statement) but shown for reference in nvidia_manual_label.
    with GROQ_REVIEW.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["image_id", "category", "groq_status", "groq_observation", "groq_confidence", "manual_label",
                    "manual_note", "nvidia_manual_label"])
        for i in ids:
            for c, o in obs(G, i).items():
                lab, note = gl.get((i, c), ("", ""))
                w.writerow([i, c, o["status"], o["observation"], o["confidence"], lab, note, nl.get((i, c), ("", ""))[0]])

    print("\n== STATUS AGREEMENT PER CATEGORY (same status / different; says nothing about correctness)")
    for c in CATEGORIES:
        print(f"  {c:24} same {agree[(c, True)]}  different {agree[(c, False)]}")
    print(f"  total: same {sum(v for (c, s), v in agree.items() if s)}, different "
          f"{sum(v for (c, s), v in agree.items() if not s)} of {len(rows)}")

    res = Counter(r["resolution"] for r in rows)
    print("\n== HUMAN-LABEL OUTCOMES (per image/category; no ranking, no global score, 5 images only)")
    print("  (one human label per image/category from the NVIDIA review file; Groq compared at status level)")
    for k in ("both agree with human", "NVIDIA agrees / Groq disagrees", "Groq agrees / NVIDIA disagrees",
              "both disagree", "human uncertain", "unresolved"):
        print(f"  {k:32} {res[k]}")
    for r in rows:
        if r["resolution"] != "unresolved":
            print(f"    {r['image_id']} {r['category']:22} {r['resolution']}: NVIDIA {r['nvidia_status']} "
                  f"| Groq {r['groq_status']} | human label [{r['human_label']}] -> {r['human_status_implied']}")

    print("\n== SIDE BY SIDE, focus categories (unresolved unless a human label exists)")
    for r in rows:
        if r["category"] in FOCUS:
            mark = " " if r["status_same"] else "*"
            print(f"{mark} {r['image_id']} {r['street'][:18]:18} {r['category']:22}\n"
                  f"      NVIDIA {r['nvidia_status']:11} {r['nvidia_observation']}\n"
                  f"      Groq   {r['groq_status']:11} {r['groq_observation']}\n      [{r['resolution']}]")
    print(f"\nWrote {SIDE_BY_SIDE} and {GROQ_REVIEW}")


if __name__ == "__main__":
    main()
