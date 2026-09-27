"""Stage 1 (Phase 5): Mapillary images for the study bbox -> small cached sample -> GeoJSON + street association.

Run: uv run python src/fetch_mapillary.py [--limit 20] [--max-distance 30] [--force]

API: Mapillary Graph API v4, GET https://graph.mapillary.com/images?bbox=...  (token in the
Authorization header, never in URLs or files). Reads Streets from Neo4j (read-only).

Outputs:
  data/raw/mapillary/search_<bbox>.json       raw search response (all images in bbox, metadata only)
  data/raw/mapillary/images/<id>.json|.jpg    raw entity response + 1024px thumbnail of selected images
  data/processed/mapillary_images.geojson     one POINT per image found (selected ones have a local image)
"""
import argparse
import json
import os
import random
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
from shapely import wkt
from shapely.geometry import Point

from import_osm import FOCUS_HIGHWAYS, METRIC_CRS
from kg import rows

API = "https://graph.mapillary.com"
TOKEN = os.environ["MAPILLARY_ACCESS_TOKEN"]  # loaded from .env by kg
BBOX = os.environ["STUDY_BBOX"]  # south,west,north,east
RAW = Path("data/raw/mapillary")
OUT = Path("data/processed/mapillary_images.geojson")
SEARCH_FIELDS = "id,captured_at,geometry,computed_geometry,compass_angle,is_pano,sequence,creator,camera_type,make,model,width,height"
ENTITY_FIELDS = SEARCH_FIELDS + ",thumb_1024_url"
CELL_DEG = 0.0005  # ~35 x 55 m grid for spreading the sample


def safe(msg):
    return str(msg).replace(TOKEN, "***")


def get(url, binary=False):
    req = urllib.request.Request(url, headers={"Authorization": f"OAuth {TOKEN}"} if url.startswith(API) else {})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.read() if binary else json.load(r)
    except urllib.error.HTTPError as e:
        raise RuntimeError(safe(f"HTTP {e.code} for {url.split('?')[0]}: {e.read()[:300]!r}")) from None


def search(force):
    s, w, n, e = BBOX.split(",")
    path = RAW / f"search_{BBOX.replace(',', '_')}.json"
    if path.exists() and not force:
        return json.loads(path.read_text()), path, True
    params = {"bbox": f"{w},{s},{e},{n}", "fields": SEARCH_FIELDS, "limit": 2000}
    data = get(f"{API}/images?{urllib.parse.urlencode(params)}")
    data["_request"] = {"endpoint": f"{API}/images", "params": params,
                        "retrieved_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False))
    return data, path, False


def location(img):
    """(Point, source) preferring Mapillary's SfM-corrected position over raw GPS."""
    for key in ("computed_geometry", "geometry"):
        if img.get(key) and img[key].get("coordinates"):
            return Point(img[key]["coordinates"]), key
    return None, None


def select(images, limit):
    """Spread the sample: newest non-pano image per grid cell, cells in seeded-random order, round-robin."""
    cells = {}
    for img in images:
        p, _ = location(img)
        if p is None:
            continue
        cells.setdefault((int(p.y / CELL_DEG), int(p.x / CELL_DEG)), []).append(img)
    queues = [sorted(v, key=lambda i: (bool(i.get("is_pano")), -i.get("captured_at", 0)))
              for _, v in sorted(cells.items())]
    random.Random(0).shuffle(queues)  # fixed seed: reproducible, spatially spread cell order
    picked = []
    while len(picked) < limit and any(queues):
        for q in queues:
            if q and len(picked) < limit:
                picked.append(q.pop(0))
    return picked


def download(img_id, force):
    """Entity metadata + 1024px thumbnail, cached. Returns (status, jpg path)."""
    meta_p, jpg_p = RAW / "images" / f"{img_id}.json", RAW / "images" / f"{img_id}.jpg"
    if jpg_p.exists() and meta_p.exists() and not force:
        return "cached", jpg_p
    meta = get(f"{API}/{img_id}?fields={ENTITY_FIELDS}")
    url = meta.get("thumb_1024_url")
    if not url:
        raise RuntimeError("no thumb_1024_url")
    jpg_p.parent.mkdir(parents=True, exist_ok=True)
    jpg_p.write_bytes(get(url, binary=True))
    meta["_retrieved_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    meta_p.write_text(json.dumps(meta, ensure_ascii=False))
    return "downloaded", jpg_p


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=20, help="number of images to download (default 20)")
    ap.add_argument("--max-distance", type=float, default=30, help="street association threshold in m")
    ap.add_argument("--force", action="store_true", help="re-query the API and re-download images")
    a = ap.parse_args()

    data, search_path, cached = search(a.force)
    images = data.get("data", [])
    print(f"Search: {len(images)} images in bbox {BBOX} ({'cached' if cached else 'API'}: {search_path})")
    if len(images) >= 2000:
        print("  note: API limit 2000 reached; the bbox may contain more images")

    picked = select(images, a.limit)
    status, paths, failed = {}, {}, []
    for img in picked:
        try:
            status[img["id"]], paths[img["id"]] = download(img["id"], a.force)
        except Exception as e:  # keep going; report
            failed.append((img["id"], safe(e)))

    # Street association (same linking scope as the OSM import).
    streets = rows("MATCH (s:Street) WHERE s.highway IN $h RETURN s.osm_id AS osm_id, s.name AS name, "
                   "s.highway AS highway, s.geometry_wkt AS wkt", h=sorted(FOCUS_HIGHWAYS))
    st = gpd.GeoDataFrame(streets, geometry=[wkt.loads(s.pop("wkt")) for s in streets], crs="EPSG:4326").to_crs(METRIC_CRS)

    picked_ids = {i["id"] for i in picked}
    recs, geoms = [], []
    for img in images:
        p, src = location(img)
        ts = img.get("captured_at")
        recs.append({
            "mapillary_id": str(img["id"]),
            "latitude": p.y if p else None, "longitude": p.x if p else None, "geometry_source": src,
            "captured_at": datetime.fromtimestamp(ts / 1000, timezone.utc).isoformat() if ts else None,
            "compass_angle": img.get("compass_angle"), "is_pano": img.get("is_pano"),
            "sequence_id": img.get("sequence"), "creator_id": (img.get("creator") or {}).get("id"),
            "camera_type": img.get("camera_type"), "make": img.get("make"), "model": img.get("model"),
            "selected": img["id"] in picked_ids,
            "local_image_path": str(paths[img["id"]]) if img["id"] in paths else None,
            "mapillary_url": f"https://www.mapillary.com/app/?pKey={img['id']}",
            "source": "Mapillary",
        })
        geoms.append(p)
    gdf = gpd.GeoDataFrame(recs, geometry=geoms, crs="EPSG:4326")

    has_gps = gdf[gdf.geometry.notna()].to_crs(METRIC_CRS)
    near = gpd.sjoin_nearest(has_gps, st[["osm_id", "name", "highway", "geometry"]], max_distance=a.max_distance,
                             distance_col="dist")
    near = near[~near.index.duplicated()]
    gdf["association_status"] = "no_gps"
    gdf.loc[has_gps.index, "association_status"] = f"unlinked_over_{a.max_distance:g}m"
    gdf.loc[near.index, "association_status"] = "linked"
    gdf.loc[near.index, "street_id"] = near.osm_id.astype("Int64")
    gdf.loc[near.index, "street_name"] = near["name"]
    gdf.loc[near.index, "street_highway"] = near.highway
    gdf.loc[near.index, "association_method"] = "nearest_street"
    gdf.loc[near.index, "association_distance_m"] = near.dist.round(1)
    gdf["street_id"] = gdf["street_id"].astype("Int64")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    gdf.to_file(OUT, driver="GeoJSON")

    # Summary
    sel = gdf[gdf.selected]
    dates = gdf.captured_at.dropna().sort_values()
    print(f"Selected: {len(picked)} (limit {a.limit}); downloaded {sum(v == 'downloaded' for v in status.values())}, "
          f"cached {sum(v == 'cached' for v in status.values())}, failed {len(failed)}")
    for i, err in failed:
        print(f"  failed {i}: {err}")
    print(f"GPS: {len(has_gps)} with, {len(gdf) - len(has_gps)} without "
          f"(computed_geometry {sum(gdf.geometry_source == 'computed_geometry')}, raw geometry "
          f"{sum(gdf.geometry_source == 'geometry')})")
    if len(dates):
        print(f"Capture dates (all): {dates.iloc[0][:10]} .. {dates.iloc[-1][:10]}; "
              f"selected: {sel.captured_at.min()[:10]} .. {sel.captured_at.max()[:10]}")
        print("Images per year (all):", dict(sorted(gdf.captured_at.dropna().str[:4].value_counts().items())))
    b = gdf.total_bounds
    print(f"Extent (lon/lat): {b[0]:.5f},{b[1]:.5f} .. {b[2]:.5f},{b[3]:.5f}; sequences {gdf.sequence_id.nunique()}, "
          f"panoramas {int(gdf.is_pano.fillna(False).sum())}")
    for label, df in (("all", gdf), ("selected", sel)):
        c = df.association_status.value_counts().to_dict()
        d = df.association_distance_m.dropna()
        print(f"Street association ({label}): {c}" + (f"; distance min {d.min()} / median {d.median():.1f} / "
                                                     f"max {d.max()} m" if len(d) else ""))
    print("Examples:")
    for r in sel.head(5).itertuples():
        print(f"  {r.mapillary_id} {r.captured_at[:10]} {r.local_image_path} -> "
              f"{'way/' + str(r.street_id) + ' ' + (r.street_name if isinstance(r.street_name, str) else '(unnamed)') + f' ({r.association_distance_m} m)' if r.association_status == 'linked' else r.association_status}")
    print(f"GeoJSON: {OUT} ({len(gdf)} points, {len(sel)} selected)")


if __name__ == "__main__":
    main()
