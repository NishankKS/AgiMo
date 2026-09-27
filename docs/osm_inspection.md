# OSM data inspection — Phase 2

## Study area

Dresden, Äußere Neustadt (southern part, incl. Bautzner Straße / Glacisstraße).
Bbox (S,W,N,E): `51.0630,13.7480,51.0690,13.7580`, about 0.67 × 0.70 km.
A dense 19th-century grid with a primary arterial, residential streets, living
streets and pedestrian zones; OSM mapping here is detailed (parking lanes,
sidewalks, trees).

- Source: Overpass API (`overpass-api.de`), a single read-only request
- OSM data timestamp: 2026-09-25T21:36:05Z
- Raw file: `data/raw/osm_51.0630_13.7480_51.0690_13.7580.json` (691 KB, includes the exact query)
- License: ODbL, © OpenStreetMap contributors

Reproduce with `uv run python src/fetch_osm.py` and `uv run python src/inspect_osm.py`.

## What was retrieved

1,921 elements: **536 ways** and **1,385 tagged nodes**. Relations were not queried.

| Group | Count |
|---|---|
| `highway=*` ways | 521 |
| of which car-accessible streets (primary, tertiary, residential, living_street, unclassified, pedestrian) | 115 ways, 27 distinct street names |
| footway / path / steps / cycleway | 252 |
| service | 153 |
| `amenity=parking` areas, `area:highway=traffic_island` | 14, 1 |
| tagged nodes | 1,385 |

Named streets are split into several OSM ways (for example, Bautzner Straße is 22 ways).
Sidewalks are mostly tagged on the street (`sidewalk=both` on 71 ways); only 3 are
mapped as separate `footway=sidewalk` ways.

## Useful tags

**Streets / road network**: `highway` ways. Each way's `nodes` list holds the node IDs,
and `geometry` holds lat/lon for each node.

**Street classification / type** (on the street way):
- `highway`: primary 21, tertiary 2, residential 64, living_street 13, pedestrian 12, unclassified 3
- `maxspeed` (30: 58, 50: 20, 20: 13, walk: 7), `zone:maxspeed`, `lanes` (1–4), `oneway`
- `name`, `wikidata`, `ref`

**Street-design-related**:

| Kind | On the street way (attribute) | As a separate OSM object |
|---|---|---|
| Sidewalk | `sidewalk` (both/right/no), `sidewalk:*:surface` | 3 `footway=sidewalk` ways |
| Parking | `parking:{both,left,right}` (lane/street_side/no), `*:orientation`, `*:condition` | 14 `amenity=parking` areas, 11 nodes |
| Bicycle infrastructure | `cycleway`, `cycleway:{both,left,right}` (lane/no), `oneway:bicycle` | 89 `amenity=bicycle_parking` nodes, 1 cycleway way |
| Crossing | — | 21 `highway=crossing` nodes (`crossing=traffic_signals/unmarked/…`), 4 `footway=crossing` ways, 1 traffic island |
| Trees / vegetation | — | 205 `natural=tree` nodes (`leaf_type`, `denotation`) |
| Lighting | `lit` (yes 253 / no 28) | 19 `highway=street_lamp` nodes |
| Street furniture | — | 19 bench, 35 waste_basket, 7 picnic_table, 13 bollard |
| Surface / quality | `surface`, `smoothness`, `width` (47 ways) | — |
| Traffic control | — | 10 `highway=traffic_signals` |
| Frontage / place function | — | ~200 shop/amenity POIs (restaurant, bar, café, shops …), entrances |

**Network connectivity**: across the 521 highway ways there are 1,294 distinct nodes;
523 of them are shared by two or more ways (junctions), and only 3 ways share no node
with another way. `CONNECTED_TO` can therefore be derived directly from shared node IDs.
No geometric snapping is needed.

## Observations / caveats

- Many SDEs appear **both** as attributes of the street way (parking, sidewalk, cycleway, lit) and as
  separate point objects (trees, lamps, benches, crossings). Point objects are not linked to a
  street in OSM, so a spatial nearest-street assignment is needed (a GeoPandas step).
- One named street consists of many ways. Decision for later: should a Street node be an OSM way
  (a segment) or a merged named street?
- The ~500 non-street highway ways (footway, service, path, steps) are real network parts but
  noisy. It is probably better to include only the car-accessible and pedestrian street classes at first.
- Node-level `highway=crossing` and `traffic_signals` sit on the street ways themselves (they are
  way nodes), so they can be linked through node IDs without spatial matching.
- Completeness varies: `width` is present on only 47 ways, and `parking:*` on roughly 110.
  Missing tags mean "unknown", not "absent".

## Proposed minimal mapping (for discussion, not final ontology)

```
(:Street {osm_id, name, highway, maxspeed, lanes, oneway, surface, lit, geometry_wkt, source:'OSM'})
(:StreetType {name})                      # initially = highway value (primary, residential, living_street, …)
(:StreetDesignElement {osm_id?, category, subtype, geometry_wkt?, source:'OSM', derived_from})

(Street)-[:HAS_TYPE]->(StreetType)
(Street)-[:HAS_ELEMENT]->(StreetDesignElement)
(Street)-[:CONNECTED_TO]->(Street)         # the two ways share an OSM node
```

StreetDesignElements from two routes, kept apart by `derived_from`:

| category | from street tag (`derived_from:'way_tag'`) | from OSM object (`derived_from:'osm_node'` / `'osm_way'`, linked spatially or by node ref) |
|---|---|---|
| sidewalk | `sidewalk=both/left/right` | `footway=sidewalk` |
| parking | `parking:*=lane/street_side` (+ orientation) | `amenity=parking` |
| bicycle_infrastructure | `cycleway*=lane/track` | `amenity=bicycle_parking`, `highway=cycleway` |
| crossing | — | `highway=crossing` (node ref on street) |
| tree | — | `natural=tree` (nearest street) |
| lighting | `lit=yes` | `highway=street_lamp` (nearest street) |
| street_furniture | — | bench, waste_basket, bollard, picnic_table |

Open decisions for the next phase:
1. Street = OSM way or merged named street?
2. Which highway classes are in scope?
3. Should StreetType stay `highway` for now or become a derived B1 type?
4. Should POIs (shops/restaurants) be modelled now, as place function, or skipped?
