"""Import the raw Overpass response into Neo4j as a streetscape graph.

Run: uv run python src/import_osm.py [data/raw/osm_....json]

Nodes:  Street (one per OSM highway way), StreetDesignElement, Place
Rels:   Street-HAS_ELEMENT->StreetDesignElement, Street-HAS_PLACE->Place,
        Street-CONNECTED_TO->Street (shared OSM node IDs)

Re-running replaces all Street/StreetDesignElement/Place nodes.
"""
import json
import os
import sys
from collections import defaultdict
from itertools import combinations
from pathlib import Path

import geopandas as gpd
from dotenv import load_dotenv
from neo4j import GraphDatabase
from shapely.geometry import LineString, Point, Polygon

METRIC_CRS = "EPSG:25833"  # ETRS89 / UTM 33N, metres, fits Dresden
MAX_LINK_M = 30  # max distance for nearest-street linking of unconnected elements/places
FOCUS_HIGHWAYS = {"primary", "secondary", "tertiary", "unclassified",
                  "residential", "living_street", "pedestrian"}

# OSM (key, value) -> (SDE category, subtype). First matching rule wins.
SDE_RULES = {
    ("natural", "tree"): ("vegetation", "tree"),
    ("highway", "street_lamp"): ("lighting", "street_lamp"),
    ("highway", "crossing"): ("crossing", "crossing"),
    ("highway", "traffic_signals"): ("traffic_control", "traffic_signals"),
    ("highway", "give_way"): ("traffic_control", "give_way"),
    ("highway", "stop"): ("traffic_control", "stop"),
    ("amenity", "bench"): ("street_furniture", "bench"),
    ("leisure", "picnic_table"): ("street_furniture", "picnic_table"),
    ("amenity", "waste_basket"): ("street_furniture", "waste_basket"),
    ("amenity", "recycling"): ("street_furniture", "recycling"),
    ("amenity", "post_box"): ("street_furniture", "post_box"),
    ("amenity", "fountain"): ("street_furniture", "fountain"),
    ("amenity", "clock"): ("street_furniture", "clock"),
    ("barrier", "bollard"): ("barrier", "bollard"),
    ("barrier", "block"): ("barrier", "block"),
    ("amenity", "bicycle_parking"): ("bicycle_infrastructure", "bicycle_parking"),
    ("amenity", "bicycle_repair_station"): ("bicycle_infrastructure", "bicycle_repair_station"),
    ("amenity", "bicycle_rental"): ("bicycle_infrastructure", "bicycle_rental"),
    ("amenity", "parking"): ("parking", "parking"),
    ("amenity", "motorcycle_parking"): ("parking", "motorcycle_parking"),
    ("amenity", "car_sharing"): ("parking", "car_sharing"),
    ("amenity", "charging_station"): ("parking", "charging_station"),
    ("amenity", "taxi"): ("parking", "taxi"),
    ("vending", "parking_tickets"): ("parking", "parking_ticket_machine"),
    ("public_transport", "platform"): ("public_transport", "platform"),
    ("railway", "tram_stop"): ("public_transport", "tram_stop"),
    ("emergency", "fire_hydrant"): ("utility", "fire_hydrant"),
    ("man_made", "street_cabinet"): ("utility", "street_cabinet"),
    ("area:highway", "traffic_island"): ("crossing", "traffic_island"),
}
PLACE_KEYS = ("shop", "amenity", "office", "craft", "healthcare", "tourism", "leisure", "club")
NOT_PLACE = {("amenity", "vending_machine"), ("shop", "vending_machine"), ("amenity", "parking_entrance")}

# Street-level tags that describe an SDE on the street way (side suffixes only).
WAY_TAG_SDE = {f"{base}{side}": base for base in ("sidewalk", "cycleway", "parking")
               for side in ("", ":both", ":left", ":right")}
WAY_TAG_SKIP = {"no", "none", "separate", "crossing"}  # separate = mapped as own way

STREET_PROPS = ["name", "highway", "service", "footway", "maxspeed", "zone:maxspeed", "lanes",
                "oneway", "oneway:bicycle", "surface", "smoothness", "width", "lit", "access",
                "bicycle", "foot", "area", "layer", "tunnel", "bridge", "ref"] + list(WAY_TAG_SDE)


def geometry(e):
    coords = [(p["lon"], p["lat"]) for p in e.get("geometry", [])] if e["type"] == "way" else [(e["lon"], e["lat"])]
    if e["type"] == "node":
        return Point(coords[0])
    if e["nodes"][0] == e["nodes"][-1] and "highway" not in e["tags"] and len(coords) >= 4:
        return Polygon(coords)
    return LineString(coords)


def sde_rule(tags):
    return next((SDE_RULES[kv] for kv in tags.items() if kv in SDE_RULES), None)


def place_category(tags):
    return next((f"{k}={tags[k]}" for k in PLACE_KEYS
                 if k in tags and (k, tags[k]) not in NOT_PLACE), None)


def build(elements):
    """Turn Overpass elements into plain dicts for Neo4j."""
    streets, sdes, places, has_element, has_place = [], [], [], [], []
    unlinked = []  # (kind, uid, geometry) for nearest-street linking

    highway_ways = [e for e in elements if e["type"] == "way" and "highway" in e.get("tags", {})]
    ways_by_node = defaultdict(list)
    for w in highway_ways:
        for ref in set(w["nodes"]):
            ways_by_node[ref].append(w["id"])

    for w in highway_ways:
        t, geom = w["tags"], geometry(w)
        streets.append({"uid": f"way/{w['id']}", "osm_type": "way", "osm_id": w["id"],
                        **{k: t[k] for k in STREET_PROPS if k in t},
                        "osm_tags": json.dumps(t, ensure_ascii=False), "geometry_wkt": geom.wkt,
                        "source": "OSM"})
        # Pedestrian areas (closed way + area=yes): keep the line, add the polygon (length_m = perimeter).
        if t.get("area") == "yes" and w["nodes"][0] == w["nodes"][-1]:
            streets[-1].update(is_area=True, area_wkt=Polygon(geom.coords).wkt)
        # SDEs described by tags on the street way itself.
        for key, base in WAY_TAG_SDE.items():
            if key not in t or t[key] in WAY_TAG_SKIP:
                continue
            side = key.split(":")[1] if ":" in key else (t[key] if t[key] in ("both", "left", "right") else None)
            uid = f"way/{w['id']}/{key}"
            sdes.append({"uid": uid, "osm_type": "way", "osm_id": w["id"], "category": base,
                         "subtype": t[key], "side": side, "source_tag": f"{key}={t[key]}",
                         "orientation": t.get(f"{key}:orientation"),
                         "derived_from": "osm_way_tag", "source": "OSM"})
            has_element.append({"street": f"way/{w['id']}", "uid": uid, "link_method": "osm_way_tag"})
        if t.get("lit") in ("yes", "automatic"):
            uid = f"way/{w['id']}/lit"
            sdes.append({"uid": uid, "osm_type": "way", "osm_id": w["id"], "category": "lighting",
                         "subtype": "lit", "source_tag": f"lit={t['lit']}",
                         "derived_from": "osm_way_tag", "source": "OSM"})
            has_element.append({"street": f"way/{w['id']}", "uid": uid, "link_method": "osm_way_tag"})

    # Separately mapped OSM objects (nodes, non-highway ways).
    for e in elements:
        t = e.get("tags", {})
        if "highway" in t and e["type"] == "way":
            continue
        rule, place = sde_rule(t), None if sde_rule(t) else place_category(t)
        if not rule and not place:
            continue
        uid, geom = f"{e['type']}/{e['id']}", geometry(e)
        c = geom.centroid
        common = {"uid": uid, "osm_type": e["type"], "osm_id": e["id"], "name": t.get("name"),
                  "osm_tags": json.dumps(t, ensure_ascii=False), "geometry_wkt": geom.wkt,
                  "lon": c.x, "lat": c.y, "source": "OSM"}
        if rule:
            sdes.append({**common, "category": rule[0], "subtype": rule[1], "derived_from": f"osm_{e['type']}"})
        else:
            key, value = place.split("=", 1)
            places.append({**common, "category": place, "osm_key": key, "osm_value": value})
        street_ids = ways_by_node.get(e["id"], []) if e["type"] == "node" else []
        if street_ids:  # the node is part of a highway way: OSM topology gives the link
            for sid in street_ids:
                (has_element if rule else has_place).append(
                    {"street": f"way/{sid}", "uid": uid, "link_method": "osm_node_ref"})
        else:
            unlinked.append(("sde" if rule else "place", uid, geom))

    # Nearest focus street within MAX_LINK_M for everything not on a way.
    # ponytail: nearest-centreline heuristic, corner objects may pick the cross street.
    st = gpd.GeoDataFrame(
        [{"street": s["uid"]} for s, w in zip(streets, highway_ways) if w["tags"]["highway"] in FOCUS_HIGHWAYS],
        geometry=[geometry(w) for w in highway_ways if w["tags"]["highway"] in FOCUS_HIGHWAYS],
        crs="EPSG:4326").to_crs(METRIC_CRS)
    pts = gpd.GeoDataFrame([{"kind": k, "uid": u} for k, u, _ in unlinked],
                           geometry=[g for *_, g in unlinked], crs="EPSG:4326").to_crs(METRIC_CRS)
    near = gpd.sjoin_nearest(pts, st, max_distance=MAX_LINK_M, distance_col="distance_m")
    near = near[~near.index.duplicated()]  # equidistant ties: keep one
    for r in near.itertuples():
        (has_element if r.kind == "sde" else has_place).append(
            {"street": r.street, "uid": r.uid, "link_method": "nearest_street", "distance_m": round(r.distance_m, 1)})

    lengths = gpd.GeoSeries([geometry(w) for w in highway_ways], crs="EPSG:4326").to_crs(METRIC_CRS).length
    for s, length in zip(streets, lengths):
        s["length_m"] = round(float(length), 1)
        if "area_wkt" in s:
            s["area_m2"] = round(float(gpd.GeoSeries.from_wkt([s["area_wkt"]], crs="EPSG:4326").to_crs(METRIC_CRS).area[0]))

    connected = defaultdict(list)
    for ref, ids in ways_by_node.items():
        for a, b in combinations(sorted(ids), 2):
            connected[(a, b)].append(ref)
    connected_to = [{"a": f"way/{a}", "b": f"way/{b}", "shared_node_ids": refs} for (a, b), refs in connected.items()]

    return {"streets": streets, "sdes": sdes, "places": places, "has_element": has_element,
            "has_place": has_place, "connected_to": connected_to, "unlinked": len(unlinked) - len(near)}


CYPHER = [
    ("streets", "UNWIND $rows AS r CREATE (s:Street) SET s = r"),
    ("sdes", "UNWIND $rows AS r CREATE (e:StreetDesignElement) SET e = r "
             "SET e.location = CASE WHEN r.lon IS NULL THEN null ELSE point({longitude: r.lon, latitude: r.lat}) END "
             "REMOVE e.lon, e.lat"),
    ("places", "UNWIND $rows AS r CREATE (p:Place) SET p = r "
               "SET p.location = point({longitude: r.lon, latitude: r.lat}) REMOVE p.lon, p.lat"),
    ("has_element", "UNWIND $rows AS r MATCH (s:Street {uid: r.street}), (e:StreetDesignElement {uid: r.uid}) "
                    "CREATE (s)-[:HAS_ELEMENT {link_method: r.link_method, distance_m: r.distance_m}]->(e)"),
    ("has_place", "UNWIND $rows AS r MATCH (s:Street {uid: r.street}), (p:Place {uid: r.uid}) "
                  "CREATE (s)-[:HAS_PLACE {link_method: r.link_method, distance_m: r.distance_m}]->(p)"),
    ("connected_to", "UNWIND $rows AS r MATCH (a:Street {uid: r.a}), (b:Street {uid: r.b}) "
                     "CREATE (a)-[:CONNECTED_TO {shared_node_ids: r.shared_node_ids}]->(b)"),
]


def load(driver, g, raw_file, osm_timestamp):
    driver.execute_query("MATCH (n) WHERE n:Street OR n:StreetDesignElement OR n:Place DETACH DELETE n")
    for label in ("Street", "StreetDesignElement", "Place"):
        driver.execute_query(f"CREATE CONSTRAINT {label.lower()}_uid IF NOT EXISTS "
                             f"FOR (n:{label}) REQUIRE n.uid IS UNIQUE")
    for key, query in CYPHER:
        rows = [{**r, "raw_file": raw_file, "osm_timestamp": osm_timestamp} if key in ("streets", "sdes", "places") else r
                for r in g[key]]
        rows = [{k: v for k, v in r.items() if v is not None} for r in rows]
        driver.execute_query(query, rows=rows)


if __name__ == "__main__":
    load_dotenv()
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else sorted(Path("data/raw").glob("osm_*.json"))[-1]
    raw = json.loads(path.read_text())
    g = build(raw["elements"])
    auth = (os.environ["NEO4J_USER"], os.environ["NEO4J_PASSWORD"])
    with GraphDatabase.driver(os.environ["NEO4J_URI"], auth=auth) as driver:
        load(driver, g, str(path), raw["osm3s"]["timestamp_osm_base"])
    print(f"Imported from {path}:")
    for k in ("streets", "sdes", "places", "has_element", "has_place", "connected_to"):
        print(f"  {k:13} {len(g[k])}")
    print(f"  not linked to any street (>{MAX_LINK_M} m from focus streets): {g['unlinked']}")
