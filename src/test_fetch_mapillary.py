"""Parser/selection checks for fetch_mapillary.py on dummy records (no API calls).

Run: uv run python src/test_fetch_mapillary.py
"""
import fetch_mapillary as fm

pt = lambda x, y: {"type": "Point", "coordinates": [x, y]}
imgs = [
    {"id": 1, "computed_geometry": pt(13.75, 51.065), "geometry": pt(13.7501, 51.0651), "captured_at": 1},
    {"id": 2, "geometry": pt(13.75, 51.065), "captured_at": 2},                 # raw GPS only
    {"id": 3, "captured_at": 3},                                               # no GPS
    {"id": 4, "geometry": pt(13.75, 51.065), "captured_at": 9, "is_pano": True},  # newest but pano
    {"id": 5, "geometry": pt(13.757, 51.068), "captured_at": 5},               # other cell
]
assert fm.location(imgs[0])[1] == "computed_geometry" and fm.location(imgs[1])[1] == "geometry"
assert fm.location(imgs[2]) == (None, None)
picked = fm.select(imgs, 10)
assert 3 not in [i["id"] for i in picked], "no-GPS image must not be selected"
assert len({i["id"] for i in picked}) == len(picked) == 4, "no duplicates"
assert fm.select(imgs, 2)[0]["id"] in (2, 5) and 4 not in [i["id"] for i in fm.select(imgs, 2)], \
    "one per cell first, newest non-pano preferred"
assert fm.TOKEN not in fm.safe(f"error {fm.TOKEN} x") and "***" in fm.safe(f"e {fm.TOKEN}")
print("fetch_mapillary checks passed")
