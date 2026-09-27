"""Download raw OSM data for the study area from Overpass (read-only, one request).

Run: uv run python src/fetch_osm.py [--force]
Output: data/raw/osm_<bbox>.json (skipped if it exists, unless --force).
"""
import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()
url = os.environ["OVERPASS_URL"]
bbox = os.environ["STUDY_BBOX"]

# Road network ways + streetscape-related ways + every tagged node in the bbox.
# `out body geom` keeps node refs (for connectivity) and coordinates (for geometry).
# Per-statement bbox (not global [bbox:]): full, unclipped way geometry; the global
# setting combined with `out geom` also returned 504s from overpass-api.de.
QUERY = f"""
[out:json][timeout:60];
(
  way["highway"]({bbox});
  way["amenity"="parking"]({bbox});
  way["area:highway"]({bbox});
  way["natural"="tree_row"]({bbox});
  node({bbox})(if:count_tags() > 0);
);
out body geom;
"""

out = Path("data/raw") / f"osm_{bbox.replace(',', '_')}.json"
if out.exists() and "--force" not in sys.argv:
    sys.exit(f"{out} exists, not re-downloading (use --force)")

req = urllib.request.Request(
    url,
    data=urllib.parse.urlencode({"data": QUERY}).encode(),
    headers={"User-Agent": "AgiMo-B1-KG-prototype/0.1 (research PoC)"},
)
with urllib.request.urlopen(req, timeout=90) as resp:
    data = json.load(resp)

data["query"] = QUERY  # provenance: keep the exact query next to the response
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(data, ensure_ascii=False))
print(f"Saved {len(data['elements'])} elements to {out} (OSM base {data['osm3s']['timestamp_osm_base']})")
