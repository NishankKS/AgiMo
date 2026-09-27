"""Descriptive B1-oriented street analysis (read-only). No street types, no ranking.

Run:
  uv run python src/analyze_streets.py --street-id 9043371     # profile of one OSM way
  uv run python src/analyze_streets.py --street "Jordanstraße" # profile of every way with that name
  uv run python src/analyze_streets.py                         # descriptive overview queries
"""
import argparse
import statistics
from collections import Counter

from shapely import wkt

from kg import FOCUS, STUDY_AREA, evidence, rows

ATTRS = ["lanes", "maxspeed", "zone:maxspeed", "oneway", "surface", "smoothness", "width", "lit", "access"]
SIDED = ["sidewalk", "cycleway", "parking"]  # plain key + :both/:left/:right
UNKNOWN = "unknown (not mapped)"


def section(title):
    print(f"\n{title}\n{'-' * 48}")


def sided(s, base):
    vals = {k: s[k] for k in (base, f"{base}:both", f"{base}:left", f"{base}:right") if k in s}
    if not vals:
        return UNKNOWN
    note = {"separate": " [mapped as separate way, not 'no']", "yes": " [type unspecified]"}
    return ", ".join(f"{k}={v}{note.get(v, '')}" for k, v in vals.items())


def profile(s):
    uid = s["uid"]
    section("STREET")
    print(f"OSM way ID        {s['osm_id']}  (https://www.openstreetmap.org/way/{s['osm_id']})")
    print(f"Name              {s.get('name') or '(unnamed)'}")
    print(f"OSM highway class {s['highway']}   (source classification, not a B1 street type)")
    if s.get("is_area"):
        print(f"Geometry          pedestrian AREA, {s['area_m2']} m², perimeter {s['length_m']} m")
    else:
        print(f"Length            {s['length_m']} m")
    at_edge = not wkt.loads(s["geometry_wkt"]).within(STUDY_AREA)
    print(f"Study-area edge   {'reaches/crosses the bbox boundary' if at_edge else 'inside study area'}")

    section("STREET ATTRIBUTES (OSM tags on the way; missing = unknown, not absent)")
    for k in ATTRS:
        print(f"{k:17} {s.get(k, UNKNOWN)}")
    for base in SIDED:
        print(f"{base:17} {sided(s, base)}")

    section("NETWORK CONTEXT")
    nb = rows("MATCH (s:Street {uid:$u})-[c:CONNECTED_TO]-(o:Street) RETURN o.osm_id AS osm_id, o.name AS name, "
              "o.highway AS highway, size(c.shared_node_ids) AS shared ORDER BY o.highway, o.name", u=uid)
    focus_nb = [n for n in nb if n["highway"] in FOCUS]
    print(f"Degree (full OSM network)      {len(nb)}")
    print(f"Degree (street-focused only)   {len(focus_nb)}")
    print(f"Neighbouring highway classes   {dict(Counter(n['highway'] for n in nb))}")
    for n in nb:
        print(f"  - way/{n['osm_id']:<11} {n['highway']:14} {n['name'] or '(unnamed)'}")
    if at_edge:
        print("  note: street reaches the study boundary; neighbours outside the bbox are not imported")

    els = rows("MATCH (s:Street {uid:$u})-[r:HAS_ELEMENT]->(e) RETURN e.uid AS uid, e.category AS category, "
               "e.subtype AS subtype, e.derived_from AS derived_from, e.source_tag AS source_tag, "
               "r.link_method AS link, r.distance_m AS d, COUNT { (:Street)-[:HAS_ELEMENT]->(e) } AS streets", u=uid)
    section("STREET DESIGN ELEMENTS")
    objs = [e for e in els if e["derived_from"] != "osm_way_tag"]
    tags = [e for e in els if e["derived_from"] == "osm_way_tag"]
    print(f"Mapped OSM objects ({len(objs)}):")
    for (cat, sub), n in sorted(Counter((e["category"], e["subtype"]) for e in objs).items()):
        print(f"  {cat:24} {sub:24} {n}")
    print(f"Street attributes as elements ({len(tags)}):")
    for e in tags:
        print(f"  {e['category']:24} {e['source_tag']}")
    lamps = sum(e["subtype"] == "street_lamp" for e in objs)
    print(f"Lighting: attribute lit={s.get('lit', UNKNOWN)}; mapped lamp objects linked: {lamps} "
          "(lit=yes does not count lamps)")

    pl = rows("MATCH (s:Street {uid:$u})-[r:HAS_PLACE]->(p) RETURN p.category AS category, p.name AS name, "
              "r.link_method AS link, r.distance_m AS d ORDER BY category", u=uid)
    section(f"PLACES ({len(pl)})")
    for cat, n in sorted(Counter(p["category"] for p in pl).items()):
        names = [p["name"] for p in pl if p["category"] == cat and p["name"]]
        print(f"  {cat:28} {n}  {', '.join(names)[:70]}")

    section("PROVENANCE / DATA QUALITY")
    links = Counter(e["link"] for e in els) + Counter(f"place:{p['link']}" for p in pl)
    print(f"Link methods      {dict(links)}")
    d = [x["d"] for x in els + pl if x["d"] is not None]
    if d:
        print(f"nearest_street    n={len(d)}, min {min(d)} m, median {statistics.median(d)} m, max {max(d)} m, "
              f"> 20 m: {sum(x > 20 for x in d)}")
    junction = [e["uid"] for e in objs if e["streets"] > 1]
    print(f"Shared with other streets (junction elements): {junction or 'none'}")
    missing = [k for k in ATTRS if k not in s] + [b for b in SIDED if sided(s, b) == UNKNOWN]
    print(f"Unknown / not mapped: {missing or 'none'}")
    amb = [e["source_tag"] for e in tags if e["subtype"] == "yes"] + \
          [k for k in s if k.startswith("sidewalk") and s[k] == "separate"]
    print(f"Ambiguous values:  {amb or 'none'}")


def overview():
    def show(title, cypher, **p):
        rs = rows(cypher, f=FOCUS, **p)
        print(f"\n== {title}")
        for r in rs:
            print("  " + " | ".join(f"{k}={v}" for k, v in r.items()))

    has = "MATCH (s:Street) WHERE EXISTS { (s)-[:HAS_ELEMENT]->(:StreetDesignElement {%s}) } "
    agg = ("RETURN count(s) AS ways, count(DISTINCT s.name) AS named_streets, "
           "collect(DISTINCT s.name)[..8] AS examples")
    for title, cond in [("trees", "subtype:'tree'"), ("benches", "subtype:'bench'"),
                        ("mapped street lamps", "subtype:'street_lamp'"),
                        ("lit=yes attribute (not lamps)", "subtype:'lit'"),
                        ("crossings", "category:'crossing'"),
                        ("bicycle infrastructure (objects)", "category:'bicycle_infrastructure'"),
                        ("cycleway attribute", "category:'cycleway'"),
                        ("parking (mapped objects)", "category:'parking', derived_from:'osm_node'"),
                        ("parking (street attribute)", "category:'parking', derived_from:'osm_way_tag'")]:
        show(f"Streets with {title}", has % cond + agg)
    show("Streets with trees AND benches AND bicycle parking",
         "MATCH (s:Street) WHERE all(t IN ['tree','bench','bicycle_parking'] WHERE "
         "EXISTS { (s)-[:HAS_ELEMENT]->(:StreetDesignElement {subtype: t}) }) " + agg)
    show("Streets with Places (by Place key)",
         "MATCH (s:Street)-[:HAS_PLACE]->(p) RETURN p.osm_key AS key, count(DISTINCT s) AS ways, count(p) AS places "
         "ORDER BY key")
    show("Streets by OSM highway class (area = pedestrian areas; km excludes areas)",
         "MATCH (s:Street) RETURN s.highway AS highway, s.highway IN $f AS focus, count(*) AS ways, "
         "count(s.is_area) AS areas, round(sum(CASE WHEN s.is_area THEN 0 ELSE s.length_m END)/1000, 2) AS km "
         "ORDER BY focus DESC, highway")
    show("Network degree distribution of focus streets (full | street-focused)",
         "MATCH (s:Street) WHERE s.highway IN $f WITH COUNT { (s)-[:CONNECTED_TO]-() } AS full, "
         "COUNT { (s)-[:CONNECTED_TO]-(o) WHERE o.highway IN $f } AS focus "
         "RETURN full, focus, count(*) AS streets ORDER BY full, focus")
    show("Neighbouring highway classes (from class -> to class, connections)",
         "MATCH (a:Street)-[:CONNECTED_TO]-(b:Street) WHERE a.highway IN $f "
         "RETURN a.highway AS from, b.highway AS neighbour, count(*) AS n ORDER BY from, neighbour")
    show("Combined: focus street profiles (degree, SDE objects, SDE attributes, places) — first 15 by name",
         "MATCH (s:Street) WHERE s.highway IN $f AND s.name IS NOT NULL "
         "RETURN s.osm_id AS osm_id, s.name AS name, s.highway AS highway, "
         "COUNT { (s)-[:CONNECTED_TO]-() } AS degree, "
         "COUNT { (s)-[:HAS_ELEMENT]->(e:StreetDesignElement WHERE e.derived_from <> 'osm_way_tag') } AS objects, "
         "COUNT { (s)-[:HAS_ELEMENT]->(:StreetDesignElement {derived_from:'osm_way_tag'}) } AS attributes, "
         "COUNT { (s)-[:HAS_PLACE]->() } AS places ORDER BY name, osm_id LIMIT 15")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--street-id", type=int, help="OSM way ID (unique)")
    g.add_argument("--street", help="street name (may match several OSM ways)")
    a = ap.parse_args()
    if a.street_id is None and a.street is None:
        overview()
    else:
        found = rows("MATCH (s:Street) WHERE s.osm_id = $id OR s.name = $n RETURN properties(s) AS s ORDER BY s.osm_id",
                     id=a.street_id, n=a.street)
        if not found:
            raise SystemExit("No matching Street")
        if a.street:
            print(f"'{a.street}' matches {len(found)} OSM ways (not merged).")
        for r in found:
            print("\n" + "#" * 60)
            profile(r["s"])
