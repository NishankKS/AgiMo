"""Stage 4 (Phase 5): select a diverse, deterministic perspective-only evaluation sample and download missing images.

Run: uv run python src/select_vlm_sample.py [--size 30] [--seed 0]

Input:  data/processed/mapillary_images.geojson (Stage 1, all images in the bbox)
Output: data/processed/vlm_evaluation_sample.json
        data/raw/mapillary/images/<id>.json|.jpg for images not yet cached (Stage 1 download code)
Only camera_type == 'perspective' and not is_pano. The 3 original V2 images are always included.
"""
import argparse
import json
import random
from collections import Counter
from pathlib import Path

GEOJSON = Path("data/processed/mapillary_images.geojson")
OUT = Path("data/processed/vlm_evaluation_sample.json")
ORIGINAL_V2 = ["1514293340184582", "2302498470581445", "379860519858209"]
IMAGES_DIR = Path("data/raw/mapillary/images")


def is_perspective(p):
    return p.get("camera_type") == "perspective" and not p.get("is_pano")


def select(props, size, seed=0, downloaded=frozenset()):
    """Greedy max-diversity: take the candidate minimising the worst repetition of its street name / sequence,
    then their sum, then year use. Ties: already downloaded first, then a seeded random order. -> [(props, reason)]"""
    by_id = {p["mapillary_id"]: p for p in props if is_perspective(p)}
    order = sorted(by_id)
    random.Random(seed).shuffle(order)
    rank = {i: n for n, i in enumerate(order)}
    street = lambda p: p.get("street_name") or (f"way/{p['street_id']}" if p.get("street_id") else "unlinked")
    used = {"street": Counter(), "sequence": Counter(), "year": Counter()}
    picked = []

    def take(p, reason):
        picked.append((p, reason))
        used["street"][street(p)] += 1
        used["sequence"][p.get("sequence_id")] += 1
        used["year"][p["captured_at"][:4]] += 1

    for i in ORIGINAL_V2:
        take(by_id[i], "original_v2_image")
    pool = [p for i, p in by_id.items() if i not in ORIGINAL_V2]
    while len(picked) < size and pool:
        def key(p):
            st, sq = used["street"][street(p)], used["sequence"][p.get("sequence_id")]
            return (max(st, sq), st + sq, used["year"][p["captured_at"][:4]], p["mapillary_id"] not in downloaded,
                    rank[p["mapillary_id"]])
        p = min(pool, key=key)
        new = [d for d, v in (("street", street(p)), ("sequence", p.get("sequence_id")),
                              ("year", p["captured_at"][:4])) if used[d][v] == 0]
        take(p, "new " + "+".join(new) if new else "least-used street/sequence/year")
        pool.remove(p)
    return picked


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--size", type=int, default=30)
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    props = [f["properties"] for f in json.loads(GEOJSON.read_text())["features"]]
    downloaded = {p.stem for p in IMAGES_DIR.glob("*.jpg")}
    picked = select(props, a.size, a.seed, downloaded)

    from fetch_mapillary import download, safe  # Stage 1 code: token from .env via header, cached
    rows, fetched, failed = [], 0, []
    for p, reason in picked:
        try:
            status, path = download(p["mapillary_id"], force=False)
            fetched += status == "downloaded"
        except Exception as e:
            failed.append((p["mapillary_id"], safe(e)))
            continue
        rows.append({"image_id": p["mapillary_id"], "street_osm_id": p.get("street_id"), "street_name": p.get("street_name"),
                     "street_highway": p.get("street_highway"), "association_status": p["association_status"],
                     "association_distance_m": p.get("association_distance_m"), "captured_at": p["captured_at"],
                     "sequence_id": p.get("sequence_id"), "camera_type": p["camera_type"], "is_pano": p["is_pano"],
                     "latitude": p["latitude"], "longitude": p["longitude"], "local_image_path": str(path),
                     "sample_reason": reason})
    OUT.write_text(json.dumps({"size": len(rows), "seed": a.seed, "criteria": "perspective only; greedy: minimise max(street-name use, sequence use), "
                               "then their sum, then capture-year use; ties: cached first, then seeded random",
                               "images": rows}, indent=1, ensure_ascii=False))
    print(f"Selected {len(picked)}; downloaded {fetched} new, {len(rows) - fetched} cached, failed {len(failed)}")
    for i, e in failed:
        print(f"  failed {i}: {e}")
    print(f"Streets: {len({r['street_name'] or r['street_osm_id'] for r in rows})}, street ways: "
          f"{len({r['street_osm_id'] for r in rows})}, sequences: {len({r['sequence_id'] for r in rows})}, years: "
          f"{dict(sorted(Counter(r['captured_at'][:4] for r in rows).items()))}")
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()
