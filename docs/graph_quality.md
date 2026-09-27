# Streetscape KG — data quality and interpretation (Phase 4)

Study area: Dresden Äußere Neustadt, bbox `51.0630,13.7480,51.0690,13.7580`, OSM data from 2026-09-25.
All numbers below come from the current Neo4j graph and can be regenerated with:

```bash
uv run python src/verify_graph.py    # summary + consistency checks
uv run python src/diagnostics.py     # issue-by-issue diagnostics (source of the numbers below)
```

Graph: 521 Street, 990 StreetDesignElement (SDE), 538 Place; 676 CONNECTED_TO, 896 HAS_ELEMENT,
502 HAS_PLACE.

This is a research prototype. The choices below are prototype decisions, not a B1 ontology.

---

## 1. OSM way → Street

One OSM `highway=*` way is one `Street` node (`uid = way/<id>`, `osm_id`, full `geometry_wkt`).
Ways that share a name are **not** merged. Bautzner Straße, for example, is 22 separate ways.
Queries by name (`{name:'…'}`) therefore return several Streets. Use `osm_id` to select exactly one.

## 2. OSM highway = source classification, not B1 StreetType

`Street.highway` is the OSM classification. There are no `StreetType` nodes and no B1 type
assignment. B1 generic street types will later combine network, spatial, design, place-function,
usage and user-need evidence.

## 3. Street attributes vs explicit SDE nodes

SDEs come from two kinds of evidence, recorded in `derived_from`:

| Evidence | `derived_from` | Count | Meaning |
|---|---|---|---|
| Mapped OSM object | `osm_node` / `osm_way` | 563 | A physical object mapped at a location (tree, bench, lamp, crossing, parking area…) |
| Tag on the street way | `osm_way_tag` | 427 | An attribute of the street (`sidewalk=both`, `parking:left=lane`, `cycleway:right=lane`, `lit=yes`). No location of its own, and no count of objects. |

Tag-derived SDEs keep `source_tag` (e.g. `parking:both=lane`). The original tags also remain properties
on the Street.

## 4. Nearest-street association (derived, not ground truth)

| Relationship | `link_method` | n |
|---|---|---|
| HAS_ELEMENT | `osm_way_tag`: tag on the street itself | 427 |
| HAS_ELEMENT | `osm_node_ref`: the object is a node of the street way | 77 |
| HAS_ELEMENT | `nearest_street`: nearest linking-scope street ≤ 30 m | 392 |
| HAS_PLACE | `nearest_street` | 501 |
| HAS_PLACE | `osm_node_ref` | 1 |

The linking scope is primary, secondary, tertiary, unclassified, residential, living_street and pedestrian.

Distances (`distance_m` on the relationship):

| | n | min | median | mean | max | 0–5 m | 5–10 | 10–20 | 20–30 |
|---|---|---|---|---|---|---|---|---|---|
| HAS_ELEMENT | 392 | 0.0 | 5.2 | 9.1 | 29.6 | 178 | 113 | 25 | 76 |
| HAS_PLACE | 501 | 0.5 | 9.3 | 9.8 | 30.0 | 42 | 258 | 186 | 15 |

Places cluster at 5–20 m, which is typical for building-front positions. The 76 elements at 20–30 m
are mostly trees and objects in courtyards, where the association is weak.

Known ambiguity, **not auto-corrected**:
- **Corner cases:** 115 nearest-street links have a street with a *different name* within 3 m of the
  assigned distance. Examples: a hairdresser assigned to Martin-Luther-Straße (7.1 m) rather than
  Martin-Luther-Platz (9.2 m), and a parking area equidistant (9.0 m) to Görlitzer Straße and
  Seifhennersdorfer Straße.
- **Footpath cases:** in 143 links, a footway, path or service way is at least 5 m closer than the
  assigned street. Examples: trees 2 m from path way/32966756, assigned to Böhmische Straße at about 21 m,
  and a traffic island 1.4 m from a service way, assigned to Glacisstraße at 16 m.

Use `link_method` and `distance_m` to filter, for example `WHERE r.link_method <> 'nearest_street' OR r.distance_m < 10`.

## 5. Unlinked objects

154 objects have no street relationship: 118 SDEs and 36 Places. They are kept in the graph.
**Unlinked does not mean invalid.** They are valid OSM objects outside the current street-association scope.

- SDEs: 78 trees, 12 bicycle parking, 8 benches, 7 parking, 6 waste baskets, 4 picnic tables,
  2 car sharing, 1 fountain.
- Places: 36 of various kinds, e.g. 4 office=company, 3 doctors, 2 nightclubs, 2 playgrounds and 2 fitness centres.
- Distance to the nearest linking-scope street: min 30 m, median 43 m, max 103 m.
- The nearest imported way of *any* class is a service road for 77 of them, a footway for 42,
  a path for 25, and steps for 2. Only 8 have a street as nearest way (they are just over 30 m away).
  These objects are in courtyards and inner blocks reached by small ways, not along streets.
- None lie inside a pedestrian-area polygon.

The 30 m threshold is an implementation choice, not a validated value. It was not raised in Phase 4.

## 6. Ambiguous parking values

17 street-level parking SDEs have `parking:*=yes`, for example `parking:both=yes` on Bautzner Straße
way/9706536. This means parking is indicated but its type (lane, street_side, on_kerb) is unspecified.
The value is kept as is (`subtype:'yes'`), and profiles label it "type unspecified".

## 7. sidewalk=separate

5 Streets (4 Königsbrücker Straße ways, 1 Bautzner Straße way) have `sidewalk:both|right=separate`.
The sidewalk is mapped as its own way. This does **not** mean "no sidewalk", so no sidewalk SDE is
created from these tags. None of the 5 are CONNECTED_TO a `footway=sidewalk` way. The separate
sidewalks are either tagged differently or lie along the street without sharing a node. They were
not merged into the Street, which would need geometric matching.

## 8. Missing tags = unknown

A missing tag means **unknown / not mapped**, never "absent". Profiles print `unknown (not mapped)`.
Coverage on the 112 focus streets:

| tag | mapped | unknown |
|---|---|---|
| surface | 112 | 0 |
| lit | 111 | 1 |
| parking* | 96 | 16 |
| maxspeed | 94 | 18 |
| sidewalk* | 91 | 21 |
| cycleway* | 90 | 22 |
| lanes | 81 | 31 |
| oneway | 48 | 64 |
| width | 35 | 77 |

A Street with no tree SDE likewise means "no tree mapped/associated", not "no trees".

## 9. Lighting evidence

| Evidence | Where | n |
|---|---|---|
| Lighting indication (`lit=yes`/`automatic`, street attribute) | SDE `subtype:'lit'`, `derived_from:'osm_way_tag'` | 259 |
| Physical lamp (mapped OSM object) | SDE `subtype:'street_lamp'`, `derived_from:'osm_node'` | 19 |

- `lit` on focus streets: 108 yes, 3 no, 1 unknown. On other ways: 145 yes, 6 automatic, 25 no, 233 unknown.
- Only 7 of 259 lit Streets have a linked mapped lamp. All 19 lamps are linked by `nearest_street`,
  and all 19 to streets tagged `lit=yes`.
- `lit=yes` says the street is lit. It does not count or locate lamps. The visualization draws it as a
  diamond labelled "lit=yes (street attribute)", and a lamp as a dot labelled "street lamp".

## 10. Junction elements

One OSM object is one SDE node, with possibly several HAS_ELEMENT relationships. The check confirms
0 duplicate SDE nodes. 17 SDEs are shared by more than one Street: crossings (8×2, 2×3, 1×4 streets),
traffic signals (1 each × 2, 3, 4 streets) and bollards (3×2). Examples:

- `node/3137622103`: crossing on Görlitzer Straße, Rothenburger Straße and two Louisenstraße ways
- `node/67273166`: traffic signals on three Bautzner Straße ways

## 11. Full vs filtered connectivity

All CONNECTED_TO relationships are kept. Each is stored once and should be queried undirected.

| Network | Streets | Edges | Components |
|---|---|---|---|
| Full OSM (all highway ways) | 521 | 676 | 8 (largest 501) |
| Street-focused (primary…pedestrian) | 112 | 144 | 10 (largest 99) |

Edge classes: 144 focus–focus, 189 focus–small, 343 small–small. Mean degree of focus streets is 4.3 in the
full network and 2.6 in the focus-only network. 6 focus streets have no focus neighbour; they connect only through
footways or service roads. Connections to small ways are real OSM topology, not import errors.
Filter with `WHERE o.highway IN [...]`, or use `--network focus` in the visualization.

## 12. Current classification choices (prototype, may change)

| OSM | Current mapping | n |
|---|---|---|
| tourism=artwork | Place | 10 |
| club=* | Place | 10 |
| vending=parking_tickets | SDE parking / parking_ticket_machine | 41 |
| amenity=car_sharing | SDE parking / car_sharing | 6 |
| amenity=taxi | SDE parking / taxi | 3 |
| barrier=gate | not imported | 50 |
| entrance=* | not imported | 69 |
| man_made=surveillance | not imported | 15 |
| historic=memorial | not imported | 16 |

These choices are made in `SDE_RULES`, `PLACE_KEYS` and `NOT_PLACE` in `src/import_osm.py`. They are
prototype choices, not ontology decisions. Public art, for example, could equally be a design element.

## 13. Pedestrian areas

9 Streets are closed ways with `highway=pedestrian` and `area=yes`, e.g. Scheune Vorplatz (way/390899603,
1,014 m²) and Bunte Ecke (way/33472108, 804 m²). The other 7 are unnamed, 137–485 m².

**Phase 4 change (small, additive):** these Streets now carry `is_area: true`, `area_wkt` (POLYGON) and
`area_m2`. `geometry_wkt` still holds the ring as a LINESTRING, and `length_m` is its **perimeter**, not a
street length. The analysis excludes them from km totals; pedestrian ways total 0.16 km plus 9 areas.
Nearest-street distances to these areas are measured to the ring, not the polygon. A point inside a
plaza therefore gets a distance > 0.

## 14. Study-area edge

56 of 521 Streets (28 focus streets) reach or cross the bbox boundary. Their full geometry is kept, but
neighbours outside the bbox are not imported. Of the 18 focus streets with degree ≤ 2, 11 are at the
boundary. Examples: Sebnitzer Straße way/794709696 and Glacisstraße way/795220344 have degree 1 and
**continue outside the study area**. **A low degree does not mean a dead end.** Street profiles flag
"reaches/crosses the bbox boundary".

---

# Phase 5: Mapillary imagery and VLM visual observations

Regenerate with `uv run python src/fetch_mapillary.py`, `src/compare_vlm.py` and `src/verify_graph.py`.
The prompt comparison is in `docs/vlm_prompt_comparison.md`.

1. **Mapillary images:** 1,357 in the study bbox, below the API's cap of 2,000 per search. 20 were
   downloaded as a spread sample (1024-px thumbnails). 3 perspective images were sent to the VLM, and
   those 3 are the only ones imported into Neo4j.
2. **Spatial coverage:** 13.74740, 51.06276 to 13.75816, 51.06908, in 75 sequences. Coverage is uneven:
   550 panoramas, 115 fisheye, 653 perspective and 39 with no camera type.
3. **Capture dates:** 2014-03-01 to 2026-06-07. 555 are from 2025 and 263 from 2024; there are none from
   2020, 2021 or 2023. Different images of one street can be years apart.
4. **Image-to-street distance** (nearest linking-scope Street, threshold 30 m): 0.0–27.6 m, median
   3.0 m, over all images. The 3 imported images are at 4.8, 3.5 and 6.3 m.
5. **Unlinked images:** 25 of 1,357 are more than 30 m from a street. They stay in the GeoJSON as
   `unlinked_over_30m`. None of the 3 imported images is unlinked.
6. **Missing metadata:** no image lacks a position or capture date. 39 have only the raw GPS `geometry`
   (the rest use Mapillary's `computed_geometry`), and 39 have no `camera_type`.
7. **VLM model:** `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning`, NVIDIA-hosted
   (`integrate.api.nvidia.com/v1`), with reasoning off, `temperature 1.0` and `top_k 1`.
8. **Model version:** not provided by the API. `model_version` is null in the files and absent from the
   Neo4j nodes.
9. **VLM calls:** 10 in total. v1: 7 calls (3 kept, 2 repeated because of a provenance bug of mine, 2
   failed with 503). v2: 3 calls.
10. **Successful / failed calls:** 8 answered and 2 failed. Both failures were HTTP 503 "worker request
    limit reached" from NVIDIA's shared capacity, not rate limiting. All 6 kept responses are valid JSON.
11. **Observations in the KG** (v2 only): 48, which is 16 categories × 3 images, each category 3 times.
    26 `visible`, 22 `not_visible`, 0 `uncertain`.
12. **Invalid or doubtful outputs:** 0 validation errors, no value-judgement words, no absence claims.
    The image review found these content problems in v2:
    - a curb over-claim on a shared surface
    - overhead lamps described as "on poles"
    - an unverified bicycle rack and unverified benches
    - one fence counted as both street furniture and barrier
    - the left-side sidewalk not reported

    They are imported as-is, not corrected. See `docs/vlm_prompt_comparison.md`.
13. **Provenance:**
    - `MapillaryImage`: `mapillary_id`, position with `geometry_source`, `captured_at`, `camera_type`,
      `sequence_id`, `local_image_path`, `mapillary_url`, `source='Mapillary'`.
    - `LOCATED_NEAR`: `{method:'nearest_street', distance_m}`, the Stage 1 association.
    - `VisualObservation`: `image_id`, `model`, `prompt_version='b1-prompt-v2'`,
      `schema_version='b1-visual-obs-v1'`, `inference_timestamp`, `source='NVIDIA hosted VLM'`,
      `raw_response_path` (the raw file also holds the full request settings, prompt and image SHA-256),
      `validation_warnings`, `confidence_is_uncalibrated=true`.
14. **Known limitations:**
    - Mapillary coverage is not uniform, and images come from different contributors, dates, cameras
      and seasons.
    - One image is one viewpoint at one moment; objects can be occluded, out of frame or too small at
      1024 px.
    - VLM output is probabilistic and not ground truth. The same prompt can produce different wording
      on another model version.
    - **Confidence is model-reported and uncalibrated.** It is not a probability, accuracy or ranking
      score. It must not be aggregated into street scores.
    - **`not_visible` means the image gives insufficient evidence. It does not mean the feature is
      absent.** For example, Bautzner Straße way/383734605 is tagged `cycleway:track` and `lit=yes` in
      OSM, while its image reports both as `not_visible`.
    - OSM and Mapillary/VLM are separate evidence layers. There are no relationships between
      `VisualObservation` and OSM `StreetDesignElement` or `Place`, and `verify_graph.py` checks this.
    - Nearest-street association of images is approximate. An image near a corner may show the cross
      street.
    - Observations are image-level: no object positions, boxes or geometries.
    - 3 images is a pipeline demonstration, not a dataset. This prototype is not yet a complete
      streetscape understanding system.
