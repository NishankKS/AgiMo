"""Summarise a raw Overpass response: object counts, tags, connectivity.

Run: uv run python src/inspect_osm.py [data/raw/osm_....json]
"""
import json
import sys
from collections import Counter
from pathlib import Path

path = Path(sys.argv[1]) if len(sys.argv) > 1 else sorted(Path("data/raw").glob("osm_*.json"))[-1]
elements = json.loads(path.read_text())["elements"]
ways = [e for e in elements if e["type"] == "way"]
nodes = [e for e in elements if e["type"] == "node"]
highways = [w for w in ways if "highway" in w.get("tags", {})]

def top(counter, n=30):
    for k, v in counter.most_common(n):
        print(f"  {v:5}  {k}")

print(f"File: {path}\nElements: {Counter(e['type'] for e in elements)}")
print(f"\nHighway ways: {len(highways)}  by highway=*:")
top(Counter(w["tags"]["highway"] for w in highways))

print("\nTag keys on highway ways (count of ways carrying the key):")
top(Counter(k for w in highways for k in w["tags"]), 60)

print("\nOther ways (non-highway):")
top(Counter(next(f"{k}={w['tags'][k]}" for k in ("amenity", "area:highway", "natural") if k in w["tags"])
            for w in ways if w not in highways))

print("\nTagged nodes by primary tag:")
PRIMARY = ("highway", "natural", "amenity", "leisure", "shop", "tourism", "man_made",
           "emergency", "barrier", "public_transport", "railway", "traffic_sign", "entrance")
top(Counter(next((f"{k}={n['tags'][k]}" for k in PRIMARY if k in n["tags"]),
                 "(other: " + ",".join(sorted(n["tags"])[:3]) + ")") for n in nodes), 50)

# Connectivity: node shared by >=2 highway ways, or used >=3 times overall (incl. mid-way T-junctions).
use = Counter(ref for w in highways for ref in w["nodes"])
ways_per_node = Counter(ref for w in highways for ref in set(w["nodes"]))
junctions = [r for r in use if ways_per_node[r] >= 2]
print(f"\nConnectivity: {len(use)} distinct highway nodes, {len(junctions)} shared by >=2 highway ways")
isolated = [w for w in highways if all(ways_per_node[r] == 1 for r in w["nodes"])]
print(f"  highway ways not sharing any node with another highway way: {len(isolated)}")
