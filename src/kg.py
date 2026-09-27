"""Shared read-only Neo4j access + definitions for the Phase 4 analysis scripts."""
import os

from dotenv import load_dotenv
from neo4j import GraphDatabase, RoutingControl
from shapely.geometry import box

load_dotenv()

# Street-focused network for analysis (B1 focus classes). Linking scope in import_osm.py
# additionally includes 'unclassified'.
FOCUS = ["primary", "secondary", "tertiary", "residential", "living_street", "pedestrian"]
_s, _w, _n, _e = map(float, os.environ["STUDY_BBOX"].split(","))
STUDY_AREA = box(_w, _s, _e, _n)  # lon/lat polygon of the bbox

_driver = GraphDatabase.driver(os.environ["NEO4J_URI"],
                               auth=(os.environ["NEO4J_USER"], os.environ["NEO4J_PASSWORD"]))


def rows(cypher, **params):
    """Run a query in a READ transaction: the server rejects any write."""
    return [r.data() for r in _driver.execute_query(cypher, params, routing_=RoutingControl.READ).records]


def evidence(sde):
    """Physical mapped object vs. attribute tag on the street way."""
    return "street attribute (tag)" if sde.get("derived_from") == "osm_way_tag" else "mapped OSM object"
