"""Graph summary, sanity checks + example queries against the imported graph (read-only).

Run: uv run python src/verify_graph.py
"""
from kg import rows


def q(title, cypher, **params):
    rs = rows(cypher, **params)
    print(f"\n== {title}")
    for r in rs:
        print("  ", r)
    return rs


def summary():
    n = {r["l"]: r["n"] for r in rows("MATCH (n) RETURN labels(n)[0] AS l, count(*) AS n")}
    r = {x["t"]: x["n"] for x in rows("MATCH ()-[r]->() RETURN type(r) AS t, count(*) AS n")}
    print("STREETSCAPE KNOWLEDGE GRAPH\n")
    for k in ("Street", "StreetDesignElement", "Place"):
        print(f"{k:22} {n.get(k, 0)}")
    print()
    for k in ("CONNECTED_TO", "HAS_ELEMENT", "HAS_PLACE"):
        print(f"{k:22} {r.get(k, 0)}")
    for rel in ("HAS_ELEMENT", "HAS_PLACE"):
        print(f"\n{rel} link methods")
        for x in rows(f"MATCH ()-[r:{rel}]->() RETURN r.link_method AS m, count(*) AS n ORDER BY m"):
            print(f"  {x['m']:20} {x['n']}")
    for label in ("StreetDesignElement", "Place"):
        u = rows(f"MATCH (n:{label}) WHERE NOT ()-->(n) RETURN count(n) AS n")[0]["n"]
        print(f"\nUnlinked {label}s: {u}")
    print("\nStreet highway classes (OSM source classification)")
    for x in rows("MATCH (s:Street) RETURN s.highway AS h, count(*) AS n ORDER BY n DESC"):
        print(f"  {x['h']:20} {x['n']}")


summary()
try:  # analysis connections must not be able to modify the graph
    rows("CREATE (:ReadOnlyProbe)")
    raise SystemExit("FAIL: write succeeded in a read transaction")
except Exception as e:
    print(f"\nRead-only check: write rejected ({getattr(e, 'message', e)})")
assert rows("MATCH (n) WHERE 'ReadOnlyProbe' IN labels(n) RETURN count(n) AS n")[0]["n"] == 0

counts = q("Node counts", "MATCH (n) RETURN labels(n)[0] AS label, count(*) AS n ORDER BY label")
rels = q("Relationship counts", "MATCH ()-[r]->() RETURN type(r) AS type, r.link_method AS method, count(*) AS n ORDER BY type, method")
assert {"Street", "StreetDesignElement", "Place"} <= {r["label"] for r in counts}  # + optional visual layer

# Checks: every tag-derived SDE is attached to exactly its own street; nothing links to itself.
assert q("Tag-derived SDEs without their street",
         "MATCH (e:StreetDesignElement {derived_from:'osm_way_tag'}) "
         "WHERE NOT (:Street {osm_id: e.osm_id})-[:HAS_ELEMENT]->(e) RETURN count(e) AS n")[0]["n"] == 0
assert q("Self-connected streets", "MATCH (s:Street)-[:CONNECTED_TO]-(s) RETURN count(*) AS n")[0]["n"] == 0
assert q("Duplicate SDE nodes for one OSM object (junction elements must be shared)",
         "MATCH (e:StreetDesignElement) WHERE e.derived_from <> 'osm_way_tag' "
         "WITH e.osm_type AS t, e.osm_id AS id, count(*) AS c WHERE c > 1 RETURN count(*) AS n")[0]["n"] == 0
assert q("Pedestrian areas (area=yes) without polygon",
         "MATCH (s:Street {area:'yes'}) WHERE s.is_area IS NULL OR s.area_wkt IS NULL RETURN count(s) AS n")[0]["n"] == 0
assert q("Streets missing osm_id/geometry/source",
         "MATCH (s:Street) WHERE s.osm_id IS NULL OR s.geometry_wkt IS NULL OR s.source <> 'OSM' RETURN count(s) AS n")[0]["n"] == 0

q("Connectivity: degree distribution of focus streets",
  "MATCH (s:Street) WHERE s.highway IN ['primary','secondary','tertiary','residential','living_street','pedestrian'] "
  "RETURN COUNT { (s)-[:CONNECTED_TO]-(:Street) } AS degree, count(*) AS streets ORDER BY degree")
q("Isolated streets (no CONNECTED_TO)",
  "MATCH (s:Street) WHERE NOT (s)-[:CONNECTED_TO]-() RETURN s.osm_id AS osm_id, s.highway AS highway, s.name AS name")

q("SDE categories by provenance",
  "MATCH (e:StreetDesignElement) RETURN e.category AS category, e.derived_from AS derived_from, count(*) AS n "
  "ORDER BY category, derived_from")
q("Sample SDEs",
  "MATCH (e:StreetDesignElement) WHERE e.subtype IN ['tree','crossing','bench','lane'] "
  "WITH e.subtype AS st, collect(e)[0] AS e OPTIONAL MATCH (s:Street)-[r:HAS_ELEMENT]->(e) "
  "RETURN e.uid AS uid, e.category AS category, e.subtype AS subtype, e.derived_from AS derived_from, "
  "e.source_tag AS source_tag, s.name AS street, r.link_method AS link, r.distance_m AS dist")

q("Place categories (top 15)", "MATCH (p:Place) RETURN p.category AS category, count(*) AS n ORDER BY n DESC LIMIT 15")
q("Sample places", "MATCH (s:Street)-[r:HAS_PLACE]->(p:Place) WHERE p.name IS NOT NULL "
  "RETURN p.uid AS uid, p.name AS name, p.category AS category, s.name AS street, r.distance_m AS dist LIMIT 5")

street = "Louisenstraße"
q(f"Elements on {street} (all its ways)",
  "MATCH (s:Street {name: $n})-[:HAS_ELEMENT]->(e) RETURN e.category AS category, e.subtype AS subtype, count(*) AS n "
  "ORDER BY n DESC", n=street)
q(f"Places on {street}",
  "MATCH (s:Street {name: $n})-[:HAS_PLACE]->(p) RETURN p.category AS category, count(*) AS n ORDER BY n DESC LIMIT 10",
  n=street)
q(f"Streets connected to {street}",
  "MATCH (s:Street {name: $n})-[:CONNECTED_TO]-(o:Street) WHERE coalesce(o.name,'') <> $n "
  "RETURN o.name AS name, o.highway AS highway, count(*) AS links ORDER BY links DESC LIMIT 10", n=street)
q("Streets with trees AND street-level parking",
  "MATCH (s:Street) WHERE EXISTS { (s)-[:HAS_ELEMENT]->(:StreetDesignElement {subtype:'tree'}) } "
  "AND EXISTS { (s)-[:HAS_ELEMENT]->(:StreetDesignElement {category:'parking', derived_from:'osm_way_tag'}) } "
  "RETURN s.name AS name, s.osm_id AS osm_id, COUNT { (s)-[:HAS_ELEMENT]->({subtype:'tree'}) } AS trees "
  "ORDER BY trees DESC LIMIT 10")
q("Streets with a cycle lane or track",
  "MATCH (s:Street)-[:HAS_ELEMENT]->(e {category:'cycleway'}) RETURN s.name AS name, s.highway AS highway, "
  "collect(e.source_tag) AS tags")
q("Focus streets by OSM highway class (ways, km, SDEs, places)",
  "MATCH (s:Street) WHERE s.highway IN ['primary','secondary','tertiary','residential','living_street','pedestrian'] "
  "RETURN s.highway AS highway, count(*) AS ways, round(sum(CASE WHEN s.is_area THEN 0 ELSE s.length_m END)/1000, 2) AS km, "
  "sum(COUNT { (s)-[:HAS_ELEMENT]->() }) AS sdes, sum(COUNT { (s)-[:HAS_PLACE]->() }) AS places ORDER BY ways DESC")
q("Unlinked SDEs / Places (> 30 m from focus streets, not on a way)",
  "MATCH (n) WHERE (n:StreetDesignElement OR n:Place) AND NOT ()-->(n) "
  "RETURN labels(n)[0] AS label, coalesce(n.subtype, n.category) AS kind, count(*) AS n ORDER BY n DESC LIMIT 10")

# --- Phase 5 visual layer (MapillaryImage / VisualObservation), if imported --------------------------
V2 = "b1-prompt-v2"
vis = rows("MATCH (i:MapillaryImage) RETURN count(i) AS n")[0]["n"]
if vis:
    print("\n\nVISUAL LAYER (Phase 5)")
    c = rows("RETURN COUNT { (:MapillaryImage) } AS images, COUNT { (:VisualObservation) } AS observations, "
             "COUNT { ()-[:LOCATED_NEAR]->() } AS located_near, COUNT { ()-[:HAS_OBSERVATION]->() } AS has_observation")[0]
    print(c)
    checks = {
        "duplicate mapillary_id": "MATCH (i:MapillaryImage) WITH i.mapillary_id AS k, count(*) AS c WHERE c > 1 RETURN count(*) AS n",
        "duplicate observation uid": "MATCH (o:VisualObservation) WITH o.uid AS k, count(*) AS c WHERE c > 1 RETURN count(*) AS n",
        "observations missing provenance": "MATCH (o:VisualObservation) WHERE o.image_id IS NULL OR o.prompt_version IS NULL "
            "OR o.model IS NULL OR o.source IS NULL OR o.schema_version IS NULL OR o.inference_timestamp IS NULL "
            "OR o.confidence_is_uncalibrated IS NULL OR o.confidence_is_uncalibrated <> true RETURN count(o) AS n",
        "invalid confidence": "MATCH (o:VisualObservation) WHERE NOT o.confidence >= 0 OR NOT o.confidence <= 1 "
            "OR o.confidence IS NULL RETURN count(o) AS n",
        "invalid status": "MATCH (o:VisualObservation) WHERE NOT o.status IN ['visible','not_visible','uncertain'] RETURN count(o) AS n",
        "observations without exactly one source image": "MATCH (o:VisualObservation) "
            "WHERE COUNT { (:MapillaryImage)-[:HAS_OBSERVATION]->(o) } <> 1 RETURN count(o) AS n",
        "observation image_id != its image": "MATCH (i:MapillaryImage)-[:HAS_OBSERVATION]->(o) "
            "WHERE o.image_id <> i.mapillary_id RETURN count(o) AS n",
        "non-v2 observations imported": "MATCH (o:VisualObservation) WHERE o.prompt_version <> $v2 RETURN count(o) AS n",
        "images missing mapillary_id/source": "MATCH (i:MapillaryImage) WHERE i.mapillary_id IS NULL OR i.source <> 'Mapillary' "
            "RETURN count(i) AS n",
        "LOCATED_NEAR missing method/distance": "MATCH ()-[l:LOCATED_NEAR]->() WHERE l.method IS NULL OR l.distance_m IS NULL "
            "RETURN count(l) AS n",
        "visual nodes linked to OSM SDE/Place (layers must stay separate)":
            "MATCH (v)--(x) WHERE (v:VisualObservation OR v:MapillaryImage) AND (x:StreetDesignElement OR x:Place) "
            "RETURN count(*) AS n",
        "VisualObservation linked to anything but its image": "MATCH (o:VisualObservation)--(x) WHERE NOT x:MapillaryImage "
            "RETURN count(*) AS n",
    }
    for name, cy in checks.items():
        n = rows(cy, v2=V2)[0]["n"]
        print(f"  {name}: {n}")
        assert n == 0, name
    print(f"  unlinked images (no LOCATED_NEAR): "
          f"{rows('MATCH (i:MapillaryImage) WHERE NOT (i)-[:LOCATED_NEAR]->() RETURN count(i) AS n')[0]['n']}")
    print(f"  observation status: {rows('MATCH (o:VisualObservation) RETURN o.status AS s, count(*) AS n ORDER BY s')}")

print("\nAll checks passed.")
