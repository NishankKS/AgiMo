"""Compare two prompt versions on the same images from the raw VLM records (no API calls).

Run: uv run python src/compare_vlm.py [--a v1] [--b v2]
Confidence is model-reported and uncalibrated: shown for provenance only, never as accuracy.
"""
import argparse
import json
import re
from collections import Counter
from pathlib import Path

from run_vlm import ABSENCE, CATEGORIES, NORMATIVE, RAW

CHECKS = {  # keyword flags on VISIBLE entries for the v1 problems (aids manual review, not scores)
    "lighting mentions daylight/sun/shadow": ("lighting", r"daylight|sunlight|sun\b|shadow|bright"),
    "public_transport says 'bus'": ("public_transport", r"\bbus"),
    "public_transport says tram/rail": ("public_transport", r"tram|rail"),
    "cycling_infrastructure mentions handlebars/capture": ("cycling_infrastructure", r"handlebar|capture|foreground"),
    "cyclists mentions handlebars/capture": ("cyclists", r"handlebar|capture"),
}


def load(version):
    return {json.loads(p.read_text())["image_id"]: json.loads(p.read_text())
            for p in sorted(RAW.glob(f"*__b1-prompt-{version}.json"))}


def obs(rec):
    return {o["category"]: o for o in rec["parsed"]["observations"]} if rec["parsed"] else {}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--a", default="v1")
    ap.add_argument("--b", default="v2")
    a = ap.parse_args()
    A, B = load(a.a), load(a.b)
    ids = [i for i in A if i in B]
    print(f"Images with both {a.a} and {a.b}: {ids}\n")

    for i in ids:
        oa, ob = obs(A[i]), obs(B[i])
        print(f"### {i}  ({A[i]['local_image_path']})")
        for c in CATEGORIES:
            x, y = oa.get(c, {}), ob.get(c, {})
            changed = "*" if x.get("status") != y.get("status") else " "
            print(f"{changed} {c:22} {a.a}: {x.get('status', '-'):11} {x.get('confidence', '-')!s:4} {x.get('observation', '')}")
            print(f"  {'':22} {a.b}: {y.get('status', '-'):11} {y.get('confidence', '-')!s:4} {y.get('observation', '')}")
        print()

    for v, R in ((a.a, A), (a.b, B)):
        recs = [R[i] for i in ids]
        allo = [o for r in recs for o in obs(r).values()]
        conf = [o["confidence"] for o in allo]
        stats = [r.get("api_stats") for r in recs]
        usage = [r["raw_response"].get("usage", {}) for r in recs]
        print(f"== {v}")
        print(f"  valid JSON / complete: {sum(not r['validation']['errors'] for r in recs)}/{len(recs)}; "
              f"validation errors: {[e for r in recs for e in r['validation']['errors']]}")
        print(f"  normative-wording hits: {sum(bool(NORMATIVE.search(o['observation'])) for o in allo)}; "
              f"absence claims on not_visible: "
              f"{sum(o['status'] == 'not_visible' and bool(ABSENCE.search(o['observation'])) for o in allo)}")
        print(f"  status: {dict(Counter(o['status'] for o in allo))}")
        print(f"  confidence (uncalibrated): min {min(conf)}, max {max(conf)}, >=0.9: {sum(c >= 0.9 for c in conf)}"
              f"/{len(conf)}, ==1.0: {sum(c == 1.0 for c in conf)}, values {dict(sorted(Counter(conf).items()))}")
        print(f"  tokens prompt/completion: {[(u.get('prompt_tokens'), u.get('completion_tokens')) for u in usage]}")
        print("  API stats: " + (str([{k: s[k] for k in ('attempts', 'retries', 'http_429', 'http_503', 'latency_s')}
                                      for s in stats]) if all(stats) else "not recorded for this version"))
        for name, (cat, pat) in CHECKS.items():
            hits = [i for i in ids if obs(R[i]).get(cat, {}).get("status") == "visible"
                    and re.search(pat, obs(R[i])[cat]["observation"], re.I)]
            print(f"  {name}: {len(hits)} {hits}")
        print(f"  curb status: {[obs(R[i]).get('curb', {}).get('status') for i in ids]}")


if __name__ == "__main__":
    main()
