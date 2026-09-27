"""Phase 4 data-quality diagnostics for the 9 issues found in Phase 3 (read-only).

Run: uv run python src/diagnostics.py
All numbers come from the current Neo4j graph (+ the raw OSM file for excluded objects).
"""
import json
import statistics
from collections import Counter
from pathlib import Path

import geopandas as gpd
from shapely import wkt

from import_osm import FOCUS_HIGHWAYS, MAX_LINK_M, METRIC_CRS
from kg import FOCUS, STUDY_AREA, rows

SMALL_GAP_M = 3  # corner case: another street within this many metres of the assigned one


def h(title):
    print(f"\n{'=' * 78}\n{title}\n{'=' * 78}")


def table(rs, limit=None):
    for r in rs[:limit]:
        print("  " + " | ".join(f"{k}={v}" for k, v in r.items()))
    if limit and len(rs) > limit:
        print(f"  ... ({len(rs) - limit} more)")


streets = rows("MATCH (s:Street) RETURN s.uid AS uid, s.osm_id AS osm_id, s.name AS name, s.highway AS highway, "
               "s.geometry_wkt AS wkt")
st = gpd.GeoDataFrame(streets, geometry=[wkt.loads(s["wkt"]) for s in streets], crs="EPSG:4326").to_crs(METRIC_CRS)
link_scope = st[st.highway.isin(FOCUS_HIGHWAYS)]


def nearest(geom_ll, frame):
    """(distance_m, street row) of the nearest street in frame, plus the full sorted distance series."""
    g = gpd.GeoSeries([geom_ll], crs="EPSG:4326").to_crs(METRIC_CRS)[0]
    d = frame.distance(g).sort_values()
    return d, frame.loc[d.index]


# ---------------------------------------------------------------------------
h("1. UNLINKED OBJECTS (no HAS_ELEMENT / HAS_PLACE)")
unl = rows("MATCH (n) WHERE (n:StreetDesignElement OR n:Place) AND NOT ()-->(n) "
           "RETURN labels(n)[0] AS label, n.uid AS uid, coalesce(n.subtype, n.category) AS kind, "
           "n.category AS category, n.geometry_wkt AS wkt")
print(f"Unlinked total: {len(unl)}  " + str(dict(Counter(r['label'] for r in unl))))
print("By kind:")
table([{"label": l, "kind": k, "n": n} for (l, k), n in Counter((r["label"], r["kind"]) for r in unl).most_common()])
print(f"Unlinked trees: {sum(r['kind'] == 'tree' for r in unl)}")
near_class, near_d, in_area = Counter(), [], 0
areas = rows("MATCH (s:Street {is_area: true}) RETURN s.area_wkt AS wkt")
area_polys = [wkt.loads(a["wkt"]) for a in areas]
for r in unl:
    g = wkt.loads(r["wkt"])
    d, fr = nearest(g, st)
    near_class[fr.iloc[0].highway] += 1
    near_d.append(nearest(g, link_scope)[0].iloc[0])
    in_area += any(p.contains(g.centroid) for p in area_polys)
print(f"Distance to nearest linking-scope street: min {min(near_d):.0f} m, median {statistics.median(near_d):.0f} m, "
      f"max {max(near_d):.0f} m (all > {MAX_LINK_M} m by construction)")
print("Nearest imported highway way of ANY class (where they actually sit):", dict(near_class.most_common()))
print(f"Inside a pedestrian area polygon: {in_area}")
print("Interpretation: unlinked != invalid. Valid OSM objects outside the street-association scope.")

# ---------------------------------------------------------------------------
h("2. LINK METHODS AND NEAREST-STREET ASSOCIATIONS")
table(rows("MATCH ()-[r:HAS_ELEMENT|HAS_PLACE]->() RETURN type(r) AS rel, r.link_method AS link_method, count(*) AS n "
           "ORDER BY rel, link_method"))
ns = rows("MATCH (s:Street)-[r {link_method:'nearest_street'}]->(o) RETURN type(r) AS rel, r.distance_m AS d, "
          "s.uid AS street, s.name AS street_name, o.uid AS uid, coalesce(o.subtype, o.category) AS kind, "
          "o.geometry_wkt AS wkt")
for rel in ("HAS_ELEMENT", "HAS_PLACE"):
    d = [r["d"] for r in ns if r["rel"] == rel]
    print(f"{rel} nearest_street: n={len(d)}, min {min(d)} m, max {max(d)} m, mean {statistics.mean(d):.1f} m, "
          f"median {statistics.median(d):.1f} m")
    bins = Counter("0-5" if x < 5 else "5-10" if x < 10 else "10-20" if x < 20 else "20-30" for x in d)
    print("   distance ranges (m):", {k: bins[k] for k in ("0-5", "5-10", "10-20", "20-30")})
corner, footpath = [], []
for r in ns:
    g = wkt.loads(r["wkt"])
    d, fr = nearest(g, link_scope)
    other = [(dist, row["name"] or row.uid) for dist, (_, row) in zip(d, fr.iterrows())
             if row.uid != r["street"] and (row["name"] or row.uid) != r["street_name"]]
    if other and other[0][0] - r["d"] <= SMALL_GAP_M:
        corner.append({"uid": r["uid"], "kind": r["kind"], "assigned": f"{r['street_name']} ({r['d']} m)",
                       "alternative": f"{other[0][1]} ({other[0][0]:.1f} m)"})
    da, fa = nearest(g, st)
    if fa.iloc[0].highway not in FOCUS_HIGHWAYS and da.iloc[0] <= r["d"] - 5:
        footpath.append({"uid": r["uid"], "kind": r["kind"], "assigned": f"{r['street_name']} ({r['d']} m)",
                         "closer_way": f"{fa.iloc[0].highway} way/{fa.iloc[0].osm_id} ({da.iloc[0]:.1f} m)"})
print(f"\nCorner ambiguity (another street name within {SMALL_GAP_M} m of the assigned distance): {len(corner)}")
table(corner, 6)
print(f"\nNear a footway/path/service way (>= 5 m closer than the assigned street): {len(footpath)}")
table(footpath, 6)
print("These are NOT auto-fixed: nearest_street is a derived association, not ground truth.")

# ---------------------------------------------------------------------------
h("3. AMBIGUOUS VALUES AND MISSING TAGS")
print("parking:*=yes (parking indicated, type unspecified):")
table(rows("MATCH (s:Street)-[:HAS_ELEMENT]->(e {category:'parking', subtype:'yes'}) "
           "RETURN s.osm_id AS osm_id, s.name AS name, e.source_tag AS tag ORDER BY name"))
print("\nsidewalk*=separate (sidewalk mapped as own way; NOT 'no sidewalk'):")
table(rows("MATCH (s:Street) WITH s, [k IN ['sidewalk','sidewalk:both','sidewalk:left','sidewalk:right'] "
           "WHERE s[k] = 'separate' | k] AS keys WHERE size(keys) > 0 "
           "OPTIONAL MATCH (s)-[:CONNECTED_TO]-(f:Street {footway:'sidewalk'}) "
           "RETURN s.osm_id AS osm_id, s.name AS name, keys, collect(f.osm_id) AS connected_sidewalk_ways"))
print("\nTag coverage on focus streets (missing = unknown / not mapped, NOT absent):")
cov = rows("MATCH (s:Street) WHERE s.highway IN $f RETURN count(*) AS n, "
           "count(s.lit) AS lit, count(s.maxspeed) AS maxspeed, count(s.surface) AS surface, count(s.lanes) AS lanes, "
           "count(s.width) AS width, count(s.oneway) AS oneway, "
           "sum(CASE WHEN any(k IN keys(s) WHERE k STARTS WITH 'sidewalk') THEN 1 ELSE 0 END) AS sidewalk, "
           "sum(CASE WHEN any(k IN keys(s) WHERE k STARTS WITH 'cycleway') THEN 1 ELSE 0 END) AS cycleway, "
           "sum(CASE WHEN any(k IN keys(s) WHERE k STARTS WITH 'parking') THEN 1 ELSE 0 END) AS parking", f=FOCUS)[0]
n = cov.pop("n")
for k, v in cov.items():
    print(f"  {k:9} mapped on {v:3}/{n} ({100 * v / n:3.0f}%)  unknown on {n - v}")

# ---------------------------------------------------------------------------
h("4. LIGHTING EVIDENCE: lit=* attribute vs mapped lamps")
table(rows("MATCH (s:Street) RETURN CASE WHEN s.highway IN $f THEN 'focus' ELSE 'other' END AS streets, "
           "coalesce(s.lit, 'UNKNOWN (not mapped)') AS lit, count(*) AS n ORDER BY streets, n DESC", f=FOCUS))
table(rows("MATCH (e:StreetDesignElement {category:'lighting'}) RETURN e.subtype AS subtype, e.derived_from AS derived_from, "
           "count(*) AS n"))
table(rows("MATCH (s:Street) WHERE s.lit IN ['yes','automatic'] RETURN "
           "sum(CASE WHEN EXISTS { (s)-->(:StreetDesignElement {subtype:'street_lamp'}) } THEN 1 ELSE 0 END) "
           "AS lit_streets_with_linked_lamp, count(*) AS lit_streets"))
table(rows("MATCH (s:Street)-[r]->(e {subtype:'street_lamp'}) RETURN coalesce(s.lit,'UNKNOWN') AS street_lit, "
           "r.link_method AS link, count(*) AS lamps"))
print(f"Unlinked lamps: {sum(r['kind'] == 'street_lamp' for r in unl)}")
print("lit=yes says the street is lit; it does not count or locate lamps.")

# ---------------------------------------------------------------------------
h("5. JUNCTION ELEMENTS (one SDE node, several streets)")
dup = rows("MATCH (e:StreetDesignElement) WHERE e.derived_from <> 'osm_way_tag' "
           "WITH e.osm_type AS t, e.osm_id AS id, count(*) AS c WHERE c > 1 RETURN count(*) AS n")[0]["n"]
print(f"Duplicate SDE nodes for the same OSM object: {dup}")
table(rows("MATCH (s:Street)-[:HAS_ELEMENT]->(e) WITH e, count(s) AS streets WHERE streets > 1 "
           "RETURN e.subtype AS subtype, streets, count(*) AS elements ORDER BY subtype, streets"))
print("Example:")
table(rows("MATCH (s:Street)-[:HAS_ELEMENT]->(e {subtype:'traffic_signals'}) WITH e, collect(s) AS ss "
           "WHERE size(ss) > 2 RETURN e.uid AS element, [x IN ss | x.highway + ' ' + coalesce(x.name,'(unnamed)') "
           "+ ' way/' + x.osm_id] AS streets LIMIT 2"))

# ---------------------------------------------------------------------------
h("6. CONNECTIVITY: full OSM network vs street-focused vs small ways")
cls = rows("MATCH (a:Street)-[:CONNECTED_TO]->(b:Street) RETURN "
           "CASE WHEN a.highway IN $f AND b.highway IN $f THEN 'focus-focus' "
           "WHEN a.highway IN $f OR b.highway IN $f THEN 'focus-small' ELSE 'small-small' END AS pair, count(*) AS n "
           "ORDER BY pair", f=FOCUS)
table(cls)
edges = rows("MATCH (a:Street)-[:CONNECTED_TO]->(b:Street) RETURN a.uid AS a, b.uid AS b, a.highway AS ha, b.highway AS hb")


def components(nodes, es):
    parent = {n: n for n in nodes}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    for a, b in es:
        parent[find(a)] = find(b)
    return Counter(find(n) for n in nodes)


full = components([s["uid"] for s in streets], [(e["a"], e["b"]) for e in edges])
focus_nodes = [s["uid"] for s in streets if s["highway"] in FOCUS]
foc = components(focus_nodes, [(e["a"], e["b"]) for e in edges if e["ha"] in FOCUS and e["hb"] in FOCUS])
print(f"Full network: {len(streets)} streets, {len(edges)} edges, {len(full)} components (largest {max(full.values())})")
print(f"Focus-only network: {len(focus_nodes)} streets, {cls[0]['n']} edges, {len(foc)} components "
      f"(largest {max(foc.values())}, sizes {sorted(foc.values(), reverse=True)[:6]})")
deg = rows("MATCH (s:Street) WHERE s.highway IN $f RETURN COUNT { (s)-[:CONNECTED_TO]-() } AS full, "
           "COUNT { (s)-[:CONNECTED_TO]-(o) WHERE o.highway IN $f } AS focus", f=FOCUS)
print(f"Focus streets: mean degree full {statistics.mean(d['full'] for d in deg):.1f}, "
      f"focus-only {statistics.mean(d['focus'] for d in deg):.1f}; "
      f"focus streets with 0 focus neighbours: {sum(d['focus'] == 0 for d in deg)}")

# ---------------------------------------------------------------------------
h("7. CURRENT PROTOTYPE CLASSIFICATION CHOICES (may change with the B1 ontology)")
table(rows("MATCH (p:Place) WHERE p.category IN ['tourism=artwork'] OR p.osm_key = 'club' "
           "RETURN 'Place' AS as, p.category AS category, count(*) AS n"))
table(rows("MATCH (e:StreetDesignElement) WHERE e.subtype IN ['parking_ticket_machine','taxi','car_sharing'] "
           "RETURN 'SDE parking' AS as, e.subtype AS subtype, count(*) AS n"))
raw = json.loads(sorted(Path("data/raw").glob("osm_*.json"))[-1].read_text())["elements"]
ex = Counter()
for e in raw:
    t = e.get("tags", {})
    for label, hit in (("barrier=gate", t.get("barrier") == "gate"), ("entrance=*", "entrance" in t),
                       ("man_made=surveillance", t.get("man_made") == "surveillance"),
                       ("historic=memorial", t.get("historic") == "memorial")):
        ex[label] += hit
print("Not imported (in raw file):", dict(ex))

# ---------------------------------------------------------------------------
h("8. PEDESTRIAN AREAS (closed way + area=yes)")
table(rows("MATCH (s:Street {is_area: true}) RETURN s.osm_id AS osm_id, coalesce(s.name,'(unnamed)') AS name, "
           "s.length_m AS perimeter_m, s.area_m2 AS area_m2, COUNT { (s)-[:CONNECTED_TO]-() } AS degree, "
           "COUNT { (s)-[:HAS_ELEMENT|HAS_PLACE]->() } AS linked ORDER BY osm_id"))
print("geometry_wkt keeps the ring as LINESTRING; area_wkt holds the POLYGON; length_m is the perimeter.")

# ---------------------------------------------------------------------------
h("9. STUDY-AREA EDGE (geometry reaches/crosses the bbox)")
st_ll = st.to_crs("EPSG:4326")
edge_uids = set(st_ll[~st_ll.within(STUDY_AREA)].uid)
deg_all = {r["uid"]: r for r in rows("MATCH (s:Street) RETURN s.uid AS uid, s.highway AS highway, s.name AS name, "
                                     "s.osm_id AS osm_id, COUNT { (s)-[:CONNECTED_TO]-() } AS degree")}
focus_edge = [u for u in edge_uids if deg_all[u]["highway"] in FOCUS]
print(f"Streets reaching the boundary: {len(edge_uids)} of {len(streets)} ({len(focus_edge)} focus)")
low = [deg_all[u] for u in deg_all if deg_all[u]["highway"] in FOCUS and deg_all[u]["degree"] <= 2]
print(f"Focus streets with degree <= 2: {len(low)}, of which reach the boundary: "
      f"{sum(r['uid'] in edge_uids for r in low)}")
table(sorted(({"osm_id": r["osm_id"], "name": r["name"], "highway": r["highway"], "degree": r["degree"],
               "at_boundary": r["uid"] in edge_uids} for r in low), key=lambda r: r["degree"]), 12)
print("Low degree at the boundary = likely continues outside the study area, not a dead end.")
