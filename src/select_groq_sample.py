"""Stage 5 (Phase 5), Part C: pick 5 already-downloaded Stage 4 images for the Groq comparison (no API calls).

Run: uv run python src/select_groq_sample.py
Writes: data/processed/groq_vlm_evaluation_sample.json

Candidates: Stage 4 images with a VALID NVIDIA V2 response (needed for a side-by-side). Each condition is met by
an image whose NVIDIA V2 output reports it (a model claim, possibly wrong - that is the point of comparing).
Rarest condition first; within a condition: unused street first, then seeded order (seed 0).
"""
import json
import random
import re
from pathlib import Path

from evaluate_vlm_quality import load

OUT = Path("data/processed/groq_vlm_evaluation_sample.json")
SIZE, SEED = 5, 0
CONDITIONS = {  # name -> predicate over one NVIDIA V2 observation
    "cycling infrastructure / bicycle parking reported":
        lambda o: (o["category"] == "cycling_infrastructure" and o["status"] == "visible")
        or (o["category"] == "street_furniture" and re.search(r"bicycle rack", o["observation"], re.I)),
    "fence/barrier reported": lambda o: o["category"] == "barriers" and o["status"] == "visible",
    "curb on cobblestone (shared-surface curb question)":
        lambda o: o["category"] == "curb" and re.search(r"cobble", o["observation"], re.I),
    "lighting infrastructure reported": lambda o: o["category"] == "lighting" and o["status"] == "visible",
    "public transport / tram infrastructure reported":
        lambda o: o["category"] == "public_transport" and o["status"] == "visible",
}


def select(sample, obs, raws, size=SIZE, seed=SEED):
    valid = [s for s in sample if s["image_id"] in raws and not raws[s["image_id"]]["validation"]["errors"]]
    order = sorted(s["image_id"] for s in valid)
    random.Random(seed).shuffle(order)
    rank = {i: n for n, i in enumerate(order)}
    meets = {name: {o["image_id"] for o in obs if f(o)} for name, f in CONDITIONS.items()}
    by_id = {s["image_id"]: s for s in valid}
    street = lambda i: by_id[i]["street_name"] or str(by_id[i]["street_osm_id"])
    picked, used_streets = [], set()
    for name in sorted(CONDITIONS, key=lambda n: (len(meets[n]), n)):  # rarest first
        if any(i in meets[name] for i in picked) or len(picked) >= size:
            continue
        cands = sorted((i for i in meets[name] if i not in picked), key=lambda i: (street(i) in used_streets, rank[i]))
        if cands:
            picked.append(cands[0])
            used_streets.add(street(cands[0]))
    for i in sorted(by_id, key=lambda i: (street(i) in used_streets, rank[i])):  # fill up with new streets
        if len(picked) >= size:
            break
        if i not in picked:
            picked.append(i)
            used_streets.add(street(i))
    unmet = [n for n in CONDITIONS if not any(i in meets[n] for i in picked)]
    rows = [{"image_id": i, "street_name": by_id[i]["street_name"], "street_osm_id": by_id[i]["street_osm_id"],
             "sequence_id": by_id[i]["sequence_id"], "captured_at": by_id[i]["captured_at"],
             "local_image_path": by_id[i]["local_image_path"],
             "selection_reason": [n for n in CONDITIONS if i in meets[n]] or ["diversity fill"]} for i in picked]
    return rows, unmet


def main():
    sample, obs, raws = load()
    rows, unmet = select(sample, obs, raws)
    OUT.write_text(json.dumps({"size": len(rows), "seed": SEED, "source": "Stage 4 sample, valid NVIDIA V2 only",
                               "note": "conditions detected from NVIDIA V2 claims, not verified truth",
                               "unmet_conditions": unmet, "images": rows}, indent=1, ensure_ascii=False))
    for r in rows:
        print(f"{r['image_id']:>18} {r['captured_at'][:10]} {str(r['street_name'] or r['street_osm_id']):22} {r['selection_reason']}")
    print(f"unmet conditions: {unmet or 'none'}\nWrote {OUT}")


if __name__ == "__main__":
    main()
