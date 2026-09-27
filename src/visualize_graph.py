"""Interactive HTML view of the real Streetscape KG (read-only, vis-network).

Run:
  uv run python src/visualize_graph.py                          # default example: Jordanstraße way/9043371
  uv run python src/visualize_graph.py --street-id 9043371      # one OSM way + neighbourhood
  uv run python src/visualize_graph.py --street "Alaunstraße"   # all ways with that name as centres
  uv run python src/visualize_graph.py --street-id 9043371 --depth 1 --network focus
  uv run python src/visualize_graph.py --overview               # all Streets + CONNECTED_TO only
Output: data/visualizations/streetscape_graph.html (override with --out). Open it in a browser.
"""
import argparse
import html as htmllib
import json
from datetime import datetime
from pathlib import Path

from kg import FOCUS, evidence, rows

DEFAULT_STREET_ID = 9043371  # Jordanstraße: 6 connected ways, 14 SDEs, 10 places
SDE_COLORS = {"vegetation": "#2e7d32", "lighting": "#f9a825", "crossing": "#6a1b9a", "traffic_control": "#c62828",
              "street_furniture": "#8d6e63", "barrier": "#546e7a", "bicycle_infrastructure": "#00838f",
              "parking": "#1565c0", "public_transport": "#ad1457", "utility": "#78909c",
              "sidewalk": "#9e9d24", "cycleway": "#00838f"}
LINK_DASHES = {"osm_way_tag": [2, 4], "osm_node_ref": False, "nearest_street": [10, 6]}


def fmt(props, keys):
    return "\n".join(f"{k}: {props[k]}" for k in keys if props.get(k) is not None)


def street_node(s, centre):
    focus = s["highway"] in FOCUS
    label = f"{s.get('name') or '(unnamed)'}\n{s['highway']}{' [area]' if s.get('is_area') else ''} · way/{s['osm_id']}"
    return {"id": s["uid"], "kind": "Street", "label": label, "shape": "box",
            "color": {"background": "#ffd54f" if centre else "#1f4e79" if focus else "#cfd8dc",
                      "border": "#e65100" if centre else "#0d2a45"},
            "font": {"color": "#000" if centre or not focus else "#fff", "size": 18 if centre else 13},
            "borderWidth": 4 if centre else 1,
            "title": "Street (one OSM way)\n" + fmt(s, ["name", "osm_id", "highway", "length_m", "is_area", "area_m2",
                                                         "maxspeed", "lanes", "sidewalk", "lit"])
                     + "\nOSM highway = source class, not a B1 street type"}


def sde_node(e):
    tag = e["derived_from"] == "osm_way_tag"
    label = f"{e['source_tag']}\n(street attribute)" if tag else e["subtype"].replace("_", " ")
    return {"id": e["uid"], "kind": "SDE", "label": label, "shape": "diamond" if tag else "dot",
            "size": 9 if tag else 12, "color": SDE_COLORS.get(e["category"], "#999"),
            "font": {"size": 11},
            "title": f"StreetDesignElement — {evidence(e)}\n" + fmt(e, ["category", "subtype", "uid", "derived_from",
                                                                         "source_tag", "name"])
                     + ("\nlit=yes: street is lit; NOT a count of lamps" if e["subtype"] == "lit" else "")}


def place_node(p):
    return {"id": p["uid"], "kind": "Place", "label": p.get("name") or p["osm_value"], "shape": "triangle",
            "size": 11, "color": "#ef6c00", "font": {"size": 11},
            "title": "Place\n" + fmt(p, ["name", "category", "uid"])}


def rel_edge(a, b, typ, r):
    m = r.get("link_method")
    title = f"{typ}\nlink_method: {m}" + (f"\ndistance: {r['distance_m']} m (derived, not ground truth)"
                                          if r.get("distance_m") is not None else "")
    return {"from": a, "to": b, "arrows": "to", "dashes": LINK_DASHES.get(m, False), "title": title,
            "label": f"{r['distance_m']:.0f} m" if r.get("distance_m") is not None else "",
            "font": {"size": 9, "color": "#666"}, "width": 2 if m == "osm_node_ref" else 1,
            "color": "#43a047" if typ == "HAS_ELEMENT" else "#ef6c00"}


def neighbourhood(centres, depth, network):
    cids = [c["uid"] for c in centres]
    nb = rows("MATCH (c:Street)-[:CONNECTED_TO]-(n:Street) WHERE c.uid IN $c AND ($net = 'all' OR n.highway IN $f) "
              "RETURN DISTINCT properties(n) AS s", c=cids, net=network, f=FOCUS)
    streets = {c["uid"]: c for c in centres} | {r["s"]["uid"]: r["s"] for r in nb}
    detail = list(streets) if depth >= 2 else cids
    nodes = [street_node(s, s["uid"] in cids) for s in streets.values()]
    edges = [{"from": r["a"], "to": r["b"], "width": 4, "color": "#455a64", "label": "CONNECTED_TO",
              "font": {"size": 9, "color": "#455a64", "strokeWidth": 3},
              "title": f"CONNECTED_TO\nshared OSM nodes: {r['n']}"}
             for r in rows("MATCH (a:Street)-[c:CONNECTED_TO]->(b:Street) WHERE a.uid IN $s AND b.uid IN $s "
                           "AND (a.uid IN $c OR b.uid IN $c OR $depth >= 2) "
                           "RETURN a.uid AS a, b.uid AS b, c.shared_node_ids AS ids, size(c.shared_node_ids) AS n",
                           s=list(streets), c=cids, depth=depth)]
    seen = set()
    for r in rows("MATCH (s:Street)-[r:HAS_ELEMENT|HAS_PLACE]->(x) WHERE s.uid IN $d "
                  "RETURN s.uid AS s, type(r) AS t, properties(r) AS r, properties(x) AS x", d=detail):
        x = r["x"]
        if x["uid"] not in seen:
            seen.add(x["uid"])
            nodes.append(sde_node(x) if r["t"] == "HAS_ELEMENT" else place_node(x))
        edges.append(rel_edge(r["s"], x["uid"], r["t"], r["r"]))
    return nodes, edges


def overview(network):
    ss = rows("MATCH (s:Street) WHERE $net = 'all' OR s.highway IN $f "
              "RETURN properties(s) AS s, COUNT { (s)-[:HAS_ELEMENT]->() } AS sde, COUNT { (s)-[:HAS_PLACE]->() } AS pl",
              net=network, f=FOCUS)
    nodes = []
    for r in ss:
        n = street_node(r["s"], False)
        n.update(shape="dot", size=6 + min(r["sde"] + r["pl"], 40) / 2, label=r["s"].get("name") or "",
                 title=n["title"] + f"\nSDE links: {r['sde']}, Place links: {r['pl']}")
        n["font"] = {"size": 10}
        nodes.append(n)
    ids = {r["s"]["uid"] for r in ss}
    edges = [{"from": r["a"], "to": r["b"], "color": "#90a4ae", "title": "CONNECTED_TO"}
             for r in rows("MATCH (a:Street)-[:CONNECTED_TO]->(b:Street) RETURN a.uid AS a, b.uid AS b")
             if r["a"] in ids and r["b"] in ids]
    return nodes, edges


HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Streetscape KG</title>
<script src="https://cdn.jsdelivr.net/npm/vis-network@9.1.9/standalone/umd/vis-network.min.js"></script>
<style>
 body{margin:0;font:14px system-ui,sans-serif;display:flex;height:100vh;color:#222;background:#fafafa}
 #graph{flex:1;border-right:1px solid #ddd;background:#fff}
 #side{width:340px;overflow:auto;padding:12px}
 h1{font-size:17px;margin:0 0 4px} h2{font-size:14px;margin:14px 0 4px}
 .k{display:inline-block;width:14px;height:14px;vertical-align:middle;margin-right:6px}
 pre{white-space:pre-wrap;word-break:break-word;background:#f3f3f3;padding:8px;font-size:12px}
 div.vis-tooltip{white-space:pre-line;font-size:12px}
 small{color:#666}
</style></head><body>
<div id="graph"></div>
<div id="side">
 <h1>Streetscape Knowledge Graph</h1>
 <div>__TITLE__</div>
 <small>Real data from Neo4j (OSM, Dresden Äußere Neustadt). Generated __TS__.<br>__COUNTS__</small>
 <h2>Show</h2>
 <label><input type="checkbox" data-g="Street" checked> Street</label>
 <label><input type="checkbox" data-g="SDE" checked> StreetDesignElement</label>
 <label><input type="checkbox" data-g="Place" checked> Place</label>
 <h2>Nodes</h2>
 <div><span class="k" style="background:#ffd54f;border:2px solid #e65100"></span>selected Street (one OSM way)</div>
 <div><span class="k" style="background:#1f4e79"></span>Street, focus class (primary…pedestrian)</div>
 <div><span class="k" style="background:#cfd8dc"></span>Street, small way (footway, service, path…)</div>
 <div><span class="k" style="background:#2e7d32;border-radius:50%"></span>SDE: mapped OSM object (colour = category)</div>
 <div><span class="k" style="background:#f9a825;transform:rotate(45deg) scale(.8)"></span>SDE: street attribute tag (e.g. lit=yes)</div>
 <div><span class="k" style="width:0;height:0;border-left:8px solid transparent;border-right:8px solid transparent;border-bottom:14px solid #ef6c00"></span>Place</div>
 <h2>Relationships</h2>
 <div><span class="k" style="height:4px;background:#455a64"></span>CONNECTED_TO (shared OSM node)</div>
 <div><span class="k" style="height:2px;background:#43a047"></span>HAS_ELEMENT — solid: osm_node_ref</div>
 <div><span class="k" style="height:0;border-top:2px dotted #43a047"></span>HAS_ELEMENT — dotted: osm_way_tag</div>
 <div><span class="k" style="height:0;border-top:2px dashed #43a047"></span>dashed + metres: nearest_street (derived)</div>
 <div><span class="k" style="height:2px;background:#ef6c00"></span>HAS_PLACE (dashed = nearest_street)</div>
 <h2>Details</h2><pre id="details">Click a node or edge.</pre>
</div>
<script>
const nodes = new vis.DataSet(__NODES__), edges = new vis.DataSet(__EDGES__), props = __PROPS__;
const net = new vis.Network(document.getElementById('graph'), {nodes, edges}, {
  physics: {solver: 'forceAtlas2Based', forceAtlas2Based: {gravitationalConstant: -60, springLength: 90},
            stabilization: {iterations: 400}},
  interaction: {hover: true, tooltipDelay: 120}, edges: {smooth: false}});
net.once('stabilizationIterationsDone', () => net.setOptions({physics: false}));
net.on('click', p => {
  const d = document.getElementById('details');
  if (p.nodes.length) d.textContent = JSON.stringify(props[p.nodes[0]], null, 1);
  else if (p.edges.length) d.textContent = edges.get(p.edges[0]).title;
});
document.querySelectorAll('input[data-g]').forEach(cb => cb.onchange = () =>
  nodes.update(nodes.get({filter: n => n.kind === cb.dataset.g}).map(n => ({id: n.id, hidden: !cb.checked}))));
</script></body></html>
"""


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--street-id", type=int, help="OSM way ID of the selected Street (preferred)")
    g.add_argument("--street", help="street name; every OSM way with that name becomes a centre")
    g.add_argument("--overview", action="store_true", help="all Streets + CONNECTED_TO, no SDEs/Places")
    ap.add_argument("--depth", type=int, choices=[1, 2], default=2,
                    help="1: elements/places of the selected street only; 2: also of connected streets (default)")
    ap.add_argument("--network", choices=["all", "focus"], default="all",
                    help="connected streets: full OSM network or focus classes only")
    ap.add_argument("--out", default="data/visualizations/streetscape_graph.html")
    a = ap.parse_args()

    if a.overview:
        nodes, edges = overview(a.network)
        title = f"Overview: Street network ({a.network}), size = linked SDEs + Places"
    else:
        centres = [r["s"] for r in rows("MATCH (s:Street) WHERE s.osm_id = $id OR s.name = $n "
                                        "RETURN properties(s) AS s", id=a.street_id or (None if a.street else DEFAULT_STREET_ID),
                                        n=a.street)]
        if not centres:
            raise SystemExit("No matching Street")
        nodes, edges = neighbourhood(centres, a.depth, a.network)
        names = htmllib.escape(", ".join(sorted({f"{c.get('name') or '(unnamed)'} way/{c['osm_id']}" for c in centres})))
        title = f"<b>Selected:</b> {names}<br>depth {a.depth}, connected streets: {a.network}"

    props = {n["id"]: None for n in nodes}
    for r in rows("MATCH (n) WHERE n.uid IN $ids RETURN n.uid AS uid, labels(n)[0] AS label, properties(n) AS p",
                  ids=list(props)):
        p = {k: (v[:300] + "…" if isinstance(v, str) and len(v) > 300 else v) for k, v in r["p"].items()
             if k != "location"}
        props[r["uid"]] = {"label": r["label"], **dict(sorted(p.items()))}
    counts = {g: sum(n["kind"] == g for n in nodes) for g in ("Street", "SDE", "Place")}
    counts_txt = f"{counts['Street']} Streets, {counts['SDE']} SDEs, {counts['Place']} Places, {len(edges)} relationships"

    js = lambda o: json.dumps(o, ensure_ascii=False).replace("</", "<\\/")
    html = (HTML.replace("__NODES__", js(nodes)).replace("__EDGES__", js(edges)).replace("__PROPS__", js(props))
            .replace("__TITLE__", title).replace("__COUNTS__", counts_txt)
            .replace("__TS__", datetime.now().strftime("%Y-%m-%d %H:%M")))
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html)
    print(f"Wrote {out} ({counts_txt}). Open: xdg-open {out}")


if __name__ == "__main__":
    main()
