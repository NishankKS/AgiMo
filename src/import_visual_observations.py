"""Stage 3 (Phase 5): import V2 visual observations into Neo4j as a separate evidence layer. WRITES to Neo4j.

Run: uv run python src/import_visual_observations.py [--dry-run]

Adds (additively, idempotent via MERGE on stable uids):
  (:MapillaryImage {uid:'mapillary/<id>'})-[:LOCATED_NEAR {method, distance_m}]->(:Street)   Stage 1 association
  (:MapillaryImage)-[:HAS_OBSERVATION]->(:VisualObservation {uid:'mapillary/<id>/<prompt_version>/<category>'})
Only prompt_version b1-prompt-v2 is imported. Existing Street/StreetDesignElement/Place data is never touched,
and VisualObservations are never linked to OSM elements. No NVIDIA or Mapillary API calls.
"""
import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path

from dotenv import load_dotenv
from neo4j import GraphDatabase

from run_vlm import CATEGORIES, STATUS

PROMPT_VERSION = "b1-prompt-v2"
OBS = Path("data/processed/vlm_observations.jsonl")
IMAGES = Path("data/processed/mapillary_images.geojson")
REQUIRED = ["image_id", "category", "status", "observation", "confidence", "confidence_is_uncalibrated", "model",
            "prompt_version", "schema_version", "inference_timestamp", "source", "raw_response_path"]
IMAGE_PROPS = ["mapillary_id", "latitude", "longitude", "captured_at", "geometry_source", "compass_angle", "is_pano",
               "camera_type", "sequence_id", "local_image_path", "mapillary_url", "source"]


def build(records, features, street_ids):
    """Validate + shape rows. Returns (plan, errors, skipped_other_versions). Writes nothing."""
    errors, obs, seen = [], [], set()
    by_id = Counter(f["properties"].get("mapillary_id") for f in features)
    errors += [f"duplicate mapillary_id in {IMAGES}: {i}" for i, n in by_id.items() if n > 1]
    feats = {f["properties"].get("mapillary_id"): f for f in features}
    skipped = Counter()
    for n, r in enumerate(records, 1):
        pv = r.get("prompt_version")
        if not pv:
            errors.append(f"record {n}: missing prompt_version")
            continue
        if pv != PROMPT_VERSION:
            skipped[pv] += 1
            continue
        where = f"record {n} ({r.get('image_id')}/{r.get('category')})"
        missing = [k for k in REQUIRED if r.get(k) in (None, "")]
        if missing:
            errors.append(f"{where}: missing {missing}")
            continue
        if r["category"] not in CATEGORIES:
            errors.append(f"{where}: invalid category {r['category']!r}")
        if r["status"] not in STATUS:
            errors.append(f"{where}: invalid status {r['status']!r}")
        c = r["confidence"]
        if not isinstance(c, (int, float)) or isinstance(c, bool) or not 0 <= c <= 1:
            errors.append(f"{where}: invalid confidence {c!r}")
        if r["confidence_is_uncalibrated"] is not True:
            errors.append(f"{where}: confidence_is_uncalibrated must be true")
        if str(r["image_id"]) not in feats:
            errors.append(f"{where}: image_id not in {IMAGES}")
        uid = f"mapillary/{r['image_id']}/{pv}/{r['category']}"
        if uid in seen:
            errors.append(f"{where}: duplicate observation {uid}")
        seen.add(uid)
        obs.append({"uid": uid, "image_uid": f"mapillary/{r['image_id']}", "image_id": str(r["image_id"]),
                    **{k: r[k] for k in ("category", "status", "observation", "confidence", "confidence_is_uncalibrated",
                                         "model", "model_version", "prompt_version", "schema_version",
                                         "inference_timestamp", "source", "raw_response_path", "image_usable",
                                         "validation_warnings")}})

    images, near = [], []
    for image_id in sorted({o["image_id"] for o in obs if o["image_id"] in feats}):
        p = feats[image_id]["properties"]
        images.append({"uid": f"mapillary/{image_id}", **{k: p.get(k) for k in IMAGE_PROPS}})
        if p.get("association_status") == "linked":
            if p.get("street_id") not in street_ids:
                errors.append(f"image {image_id}: associated Street way/{p.get('street_id')} not in Neo4j")
                continue
            near.append({"image_uid": f"mapillary/{image_id}", "street_uid": f"way/{p['street_id']}",
                         "method": p["association_method"], "distance_m": p["association_distance_m"]})
    return {"images": images, "observations": obs, "located_near": near}, errors, skipped


WRITES = [
    ("images", "UNWIND $rows AS r MERGE (i:MapillaryImage {uid: r.uid}) SET i += r, "
               "i.location = point({longitude: r.longitude, latitude: r.latitude})"),
    ("located_near", "UNWIND $rows AS r MATCH (i:MapillaryImage {uid: r.image_uid}), (s:Street {uid: r.street_uid}) "
                     "MERGE (i)-[l:LOCATED_NEAR]->(s) SET l.method = r.method, l.distance_m = r.distance_m"),
    ("observations", "UNWIND $rows AS r MATCH (i:MapillaryImage {uid: r.image_uid}) "
                     "MERGE (o:VisualObservation {uid: r.uid}) SET o += r.props "
                     "MERGE (i)-[:HAS_OBSERVATION]->(o)"),
]


def write(driver, plan):
    for q in ("CREATE CONSTRAINT mapillaryimage_uid IF NOT EXISTS FOR (n:MapillaryImage) REQUIRE n.uid IS UNIQUE",
              "CREATE CONSTRAINT mapillaryimage_mapillary_id IF NOT EXISTS FOR (n:MapillaryImage) "
              "REQUIRE n.mapillary_id IS UNIQUE",
              "CREATE CONSTRAINT visualobservation_uid IF NOT EXISTS FOR (n:VisualObservation) REQUIRE n.uid IS UNIQUE"):
        driver.execute_query(q)

    def tx(t):
        total = Counter()
        for key, q in WRITES:
            if key == "observations":  # node props = row minus the join key; None (model_version) stays unset
                rows = [{"uid": r["uid"], "image_uid": r["image_uid"],
                         "props": {k: v for k, v in r.items() if k != "image_uid" and v is not None}}
                        for r in plan[key]]
            else:
                rows = [{k: v for k, v in r.items() if v is not None} for r in plan[key]]
            c = t.run(q, rows=rows).consume().counters
            total.update(nodes=c.nodes_created, rels=c.relationships_created, props=c.properties_set)
        return total
    with driver.session() as s:
        return s.execute_write(tx)  # one transaction: all or nothing


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="validate and report, write nothing")
    a = ap.parse_args()
    load_dotenv()
    records = [json.loads(line) for line in OBS.read_text().splitlines() if line.strip()]
    features = json.loads(IMAGES.read_text())["features"]
    driver = GraphDatabase.driver(os.environ["NEO4J_URI"], auth=(os.environ["NEO4J_USER"], os.environ["NEO4J_PASSWORD"]))
    street_ids = {r["id"] for r in driver.execute_query("MATCH (s:Street) RETURN s.osm_id AS id").records}

    plan, errors, skipped = build(records, features, street_ids)
    print(f"{OBS}: {len(records)} records; {PROMPT_VERSION}: {len(plan['observations'])}; "
          f"not imported (other prompt versions): {dict(skipped)}")
    print(f"Plan: {len(plan['images'])} MapillaryImage, {len(plan['observations'])} VisualObservation, "
          f"{len(plan['located_near'])} LOCATED_NEAR, {len(plan['observations'])} HAS_OBSERVATION")
    print(f"Categories: {dict(Counter(o['category'] for o in plan['observations']))}")
    for i in plan["images"]:
        ln = next((l for l in plan["located_near"] if l["image_uid"] == i["uid"]), None)
        target = f"{ln['street_uid']} ({ln['distance_m']} m, {ln['method']})" if ln else "no Street within threshold"
        print(f"  {i['uid']} {i['captured_at'][:10]} -> {target}")
    if errors:
        print(f"\nVALIDATION FAILED ({len(errors)}), nothing written:")
        for e in errors:
            print("  " + e)
        sys.exit(1)
    if a.dry_run:
        print("\nDry run: validation passed, nothing written.")
        return
    c = write(driver, plan)
    driver.close()
    print(f"\nWritten: {c['nodes']} nodes created, {c['rels']} relationships created, {c['props']} properties set")


if __name__ == "__main__":
    main()
