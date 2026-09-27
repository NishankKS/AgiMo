# AgiMo B1 Streetscape Knowledge Graph (prototype)

Small proof-of-concept for a Streetscape Knowledge Graph in Neo4j.
See `B1_CONTEXT.md` for background.

## Requirements

- Docker + Docker Compose
- Python 3.11+ and [uv](https://docs.astral.sh/uv/)

## Setup

```bash
cp .env.example .env          # then set NEO4J_PASSWORD (min. 8 chars)
docker compose up -d          # start Neo4j
uv sync                       # create .venv and install dependencies
```

Neo4j Browser: http://localhost:7474 (login with the credentials from `.env`).

## Check connectivity

```bash
uv run python src/check_neo4j.py
```

Expected output: `Connected to bolt://localhost:7687: Neo4j Kernel 5.x (community)`.

## OSM data (Phase 2)

```bash
uv run python src/fetch_osm.py      # one Overpass request -> data/raw/osm_<bbox>.json (skips if present; --force to refetch)
uv run python src/inspect_osm.py    # print object/tag/connectivity summary
```

The study area bbox and the Overpass endpoint are set in `.env` (`STUDY_BBOX`, `OVERPASS_URL`).
The inspection report is in `docs/osm_inspection.md`. OSM data © OpenStreetMap contributors, ODbL.

## Import into Neo4j (Phase 3)

```bash
uv run python src/import_osm.py     # raw OSM JSON -> Neo4j (replaces Street/StreetDesignElement/Place)
uv run python src/verify_graph.py   # sanity checks + example queries
```

Graph model:

```
(:Street)               one per OSM highway way (uid 'way/<id>', osm_id, name, highway, maxspeed,
                        lanes, surface, sidewalk*, cycleway*, parking*, lit, width, ...,
                        osm_tags JSON, geometry_wkt, length_m, source='OSM')
(:StreetDesignElement)  category/subtype, derived_from = osm_node | osm_way | osm_way_tag,
                        source_tag (for osm_way_tag), geometry_wkt + location point (objects only)
(:Place)                shops, amenities, offices, ... (category 'shop=clothes', name, location)

(Street)-[:HAS_ELEMENT {link_method, distance_m}]->(StreetDesignElement)
(Street)-[:HAS_PLACE   {link_method, distance_m}]->(Place)
(Street)-[:CONNECTED_TO {shared_node_ids}]->(Street)   # stored once; query undirected: -[:CONNECTED_TO]-
```

`link_method`: `osm_way_tag` (tag on the street), `osm_node_ref` (node is part of the way),
or `nearest_street` (nearest primary/secondary/tertiary/unclassified/residential/living_street/pedestrian
street within 30 m). The OSM highway class is only source data; no B1 street type is assigned yet.

Example queries (Neo4j Browser, http://localhost:7474):

```cypher
// elements and places on a street (all its ways)
MATCH (s:Street {name:'Louisenstraße'})-[:HAS_ELEMENT]->(e) RETURN e.category, e.subtype, count(*);
MATCH (s:Street {name:'Louisenstraße'})-[:HAS_PLACE]->(p)   RETURN p.category, p.name;
// connected streets
MATCH (s:Street {name:'Louisenstraße'})-[:CONNECTED_TO]-(o) RETURN DISTINCT o.name, o.highway;
// streets with trees
MATCH (s:Street)-[:HAS_ELEMENT]->(:StreetDesignElement {subtype:'tree'}) RETURN s.name, count(*) ORDER BY count(*) DESC;
// streets by OSM highway class
MATCH (s:Street {highway:'living_street'}) RETURN s.name, s.length_m;
// visual: a street with its neighbourhood
MATCH p=(s:Street {name:'Alaunstraße'})-[*1]-() RETURN p;
```

## Analysis, diagnostics and visualization (Phase 4)

All Phase 4 scripts are **read-only**: they query Neo4j in READ transactions, so the server rejects writes.

```bash
uv run python src/verify_graph.py                          # graph summary + consistency checks
uv run python src/diagnostics.py                           # data-quality diagnostics (9 Phase 3 issues)
uv run python src/analyze_streets.py                       # descriptive overview queries (no ranking)
uv run python src/analyze_streets.py --street-id 9043371   # profile of one OSM way
uv run python src/analyze_streets.py --street "Jordanstraße"  # profile of every way with that name
```

The interpretation of the diagnostics is in `docs/graph_quality.md`: link methods, unlinked objects,
unknown vs absent, lighting evidence, study-area edge, and so on.

A street profile shows the OSM highway class and length, the OSM attributes (missing = `unknown (not mapped)`),
the network context (full and street-focused degree, neighbouring classes, boundary flag), SDEs split into
mapped objects and street attributes, Places, and provenance (link methods, distances, ambiguous values).

### Knowledge-graph visualization

```bash
uv run python src/visualize_graph.py                        # default: Jordanstraße way/9043371
uv run python src/visualize_graph.py --street-id <OSM_WAY_ID>
uv run python src/visualize_graph.py --street "Alaunstraße" # every way with that name as centre
uv run python src/visualize_graph.py --street-id 9043371 --depth 1 --network focus
uv run python src/visualize_graph.py --overview --out data/visualizations/network_overview.html
xdg-open data/visualizations/streetscape_graph.html
```

Output: `data/visualizations/streetscape_graph.html` (change with `--out`). The page is a single HTML
file that loads vis-network from jsdelivr, so opening it needs internet access.

What it shows: the selected Street (yellow), its CONNECTED_TO Streets, and the StreetDesignElements and
Places of the selected Street. With `--depth 2` (the default) it also shows those of the connected
Streets.

- **Streets** are boxes: dark = focus class, grey = footway/service/path etc.
- **SDEs**: a dot is a mapped OSM object (colour = category); a diamond is a street-attribute tag such as
  `lit=yes (street attribute)`.
- **Places** are orange triangles.
- **HAS_ELEMENT/HAS_PLACE** edges are solid for `osm_node_ref`, dotted for `osm_way_tag`, and dashed with
  the distance in metres for `nearest_street`.
- **CONNECTED_TO** edges are thick grey.
- Hover a node or edge for a tooltip. Click one to see all its properties. Checkboxes hide node types.
- `--network focus` shows only focus-class neighbours. `--overview` shows all 521 Streets and CONNECTED_TO,
  with no SDEs or Places.

### Neo4j Browser queries (http://localhost:7474)

```cypher
// streets and their design elements
MATCH (s:Street)-[r:HAS_ELEMENT]->(e:StreetDesignElement) RETURN s,r,e LIMIT 100;

// street network
MATCH (s1:Street)-[r:CONNECTED_TO]->(s2:Street) RETURN s1,r,s2 LIMIT 100;

// focused: one street + connected streets + its SDEs + its Places
MATCH (s:Street {osm_id: 9043371})
OPTIONAL MATCH p1=(s)-[:CONNECTED_TO]-(:Street)
OPTIONAL MATCH p2=(s)-[:HAS_ELEMENT]->(:StreetDesignElement)
OPTIONAL MATCH p3=(s)-[:HAS_PLACE]->(:Place)
RETURN s, collect(DISTINCT p1), collect(DISTINCT p2), collect(DISTINCT p3);

// street-focused network only
MATCH (a:Street)-[r:CONNECTED_TO]->(b:Street)
WHERE a.highway IN ['primary','secondary','tertiary','residential','living_street','pedestrian']
  AND b.highway IN ['primary','secondary','tertiary','residential','living_street','pedestrian']
RETURN a,r,b;

// lighting evidence: attribute vs mapped lamp
MATCH (s:Street)-[r:HAS_ELEMENT]->(e:StreetDesignElement {category:'lighting'})
RETURN e.subtype AS evidence, e.derived_from, r.link_method, count(*);

// junction element shared by several streets
MATCH (s:Street)-[:HAS_ELEMENT]->(e:StreetDesignElement {uid:'node/3137622103'}) RETURN s, e;

// streets with trees AND benches (descriptive, no ranking)
MATCH (s:Street) WHERE EXISTS { (s)-[:HAS_ELEMENT]->({subtype:'tree'}) }
  AND EXISTS { (s)-[:HAS_ELEMENT]->({subtype:'bench'}) } RETURN s.osm_id, s.name, s.highway;

// unlinked objects (kept: unlinked != invalid)
MATCH (n) WHERE (n:StreetDesignElement OR n:Place) AND NOT ()-->(n)
RETURN labels(n)[0], coalesce(n.subtype, n.category) AS kind, count(*);
```

## Mapillary imagery + VLM observations (Phase 5)

Required `.env` variables (values never printed or written to files; see `.env.example`):
`MAPILLARY_ACCESS_TOKEN`, `NVIDIA_API_KEY`, `NIM_MODEL`, optional `NIM_BASE_URL`, and `GROQ_API_KEY` (Stage 5 only).
Read them only through Python (`python-dotenv`). Never `source .env` in a shell: token values contain `|`.

### Stage 1: Mapillary sample, GeoJSON, street association

```bash
uv run python src/fetch_mapillary.py --limit 20     # --max-distance 30, --force to re-query/re-download
uv run python src/test_fetch_mapillary.py           # parser/selection checks (dummy records, no API)
```

- API: Mapillary Graph API v4 `GET https://graph.mapillary.com/images?bbox=<W,S,E,N>&fields=...&limit=2000`,
  token in the `Authorization: OAuth` header. For each selected image, one entity request
  (`GET /<image_id>?fields=...,thumb_1024_url`) and one thumbnail download.
- Selection: a spatially spread sample. The bbox is split into grid cells of about 35 x 55 m; cells are
  visited in seeded-random order, and each gives its newest non-panorama image, or a panorama if the cell
  has only panoramas.
- Raw files: `data/raw/mapillary/search_<bbox>.json` (all images found) and
  `data/raw/mapillary/images/<id>.json|.jpg` (selected images). Cached, so re-runs do not re-download.
- `data/processed/mapillary_images.geojson`: one POINT per image found. Open it directly in QGIS; filter
  `"selected" = true` for the downloaded sample.
  - Properties: `mapillary_id`, `latitude`/`longitude` (`geometry_source`: `computed_geometry` or raw
    `geometry`), `captured_at` (UTC), `compass_angle`, `is_pano`, `camera_type`, `sequence_id`,
    `creator_id`, `local_image_path`, `mapillary_url`, `association_status`, `street_id`, `street_name`,
    `street_highway`, `association_method` (`nearest_street`), `association_distance_m`, `source`.
  - Association: the nearest Street (same linking scope as the OSM import) within 30 m. Images beyond
    30 m stay in the file as `unlinked_over_30m`.
- Mapillary imagery is CC BY-SA 4.0 (© Mapillary contributors).

### Stage 2: NVIDIA-hosted VLM observations

```bash
uv run python src/run_vlm.py --limit 3     # prompt v1 (default); perspective images only
uv run python src/run_vlm.py --prompt-version v2 --image-ids 1514293340184582 2302498470581445 379860519858209
uv run python src/compare_vlm.py           # v1 vs v2 on the same images (no API calls)
uv run python src/test_run_vlm.py          # validator, prompt, cache, retry/pacing checks (no API calls)
```

- Requests are sequential, paced to at most 30 per minute. On 429, 502–504 or network errors the script
  retries up to 3 times, waiting 2, 5 and 10 s, or the server's `Retry-After` if longer (capped at 60 s).
  400/401/403/404/413/422 and other 5xx errors fail immediately and are classified.
- Cache: a *valid* raw response for the same image and prompt version is never requested again, unless
  you pass `--force`. v1 and v2 files are kept side by side.
- Results of the comparison: `docs/vlm_prompt_comparison.md`.

- API: OpenAI-compatible `POST {NIM_BASE_URL or https://integrate.api.nvidia.com/v1}/chat/completions`
  with model `NIM_MODEL`. The image is sent as a base64 data URL. Reasoning is off
  (`chat_template_kwargs.enable_thinking=false`, `temperature 1.0`, `top_k 1`). On 429/503 capacity errors
  the script retries once.
- Prompts `b1-prompt-v1` and `b1-prompt-v2` (v2 adds category definitions and tells the model to ignore the capture equipment); schema `b1-visual-obs-v1`. The response must list each of
  16 categories once, with `status` = `visible`, `not_visible` or `uncertain`, a factual
  `observation` and a `confidence` between 0 and 1. The model has no structured-output mode, so the
  JSON is validated in code; normative wording is flagged as a warning.
- `data/raw/vlm/<image_id>__<prompt_version>.json`: request metadata, prompt, image SHA-256, raw API
  response and validation result.
- `data/processed/vlm_observations.jsonl`: one normalized observation per line, rebuilt from the valid
  raw files.
- VLM output describes one image at one moment. It is not ground truth, and `not_visible` does not
  mean absent. The confidence is the model's own estimate, not a measured accuracy (`confidence_is_uncalibrated: true`).

### Stage 3: visual layer in Neo4j (WRITE script)

```bash
uv run python src/import_visual_observations.py --dry-run   # validate + show what would be imported
uv run python src/import_visual_observations.py             # write (idempotent; re-running adds nothing)
uv run python src/verify_graph.py                           # includes the visual-layer checks
uv run python src/test_import_visual_observations.py        # importer validation checks (no writes)
```

`import_visual_observations.py` is a **write** script, like `import_osm.py`. `verify_graph.py`,
`diagnostics.py`, `analyze_streets.py` and `visualize_graph.py` remain read-only.

Added alongside the OSM graph, without changing it:

```
(:MapillaryImage {uid:'mapillary/<id>', mapillary_id, latitude, longitude, location, captured_at, camera_type,
                  sequence_id, local_image_path, mapillary_url, source:'Mapillary'})
  -[:LOCATED_NEAR {method:'nearest_street', distance_m}]->(:Street)          # Stage 1 association, <= 30 m
(:MapillaryImage)-[:HAS_OBSERVATION]->(:VisualObservation {uid:'mapillary/<id>/b1-prompt-v2/<category>',
                  image_id, category, status, observation, confidence, confidence_is_uncalibrated:true,
                  model, prompt_version, schema_version, inference_timestamp, source:'NVIDIA hosted VLM',
                  raw_response_path, validation_warnings})
```

- **Only `b1-prompt-v2`** observations are imported. v1 stays in the files for comparison.
- **Validation:** the importer checks everything before writing and writes in a single transaction.
  Any invalid record, duplicate, or missing Street stops the import, and nothing is written.
- **Separate from OSM:** VisualObservations are **not** StreetDesignElements. A VLM observation is one
  model's reading of one image, at one capture date. An OSM SDE is a mapped object. They are never
  linked, merged or used to overwrite each other.
- **`status`:** `visible`, `not_visible` or `uncertain`. `not_visible` means the image gives insufficient
  evidence; it does **not** mean the feature is absent.
- **`confidence`:** model-reported and uncalibrated. Do not rank or score streets with it.
- **`model_version`:** not provided by the NVIDIA API, so the property is absent.

Neo4j Browser queries (read-only, descriptive):

```cypher
// Mapillary images and the Street each is located near
MATCH (i:MapillaryImage)-[l:LOCATED_NEAR]->(s:Street)
RETURN i.mapillary_id, left(i.captured_at,10) AS captured, s.osm_id, s.name, l.distance_m, l.method;

// all visual observations of one image
MATCH (i:MapillaryImage {mapillary_id:'2302498470581445'})-[:HAS_OBSERVATION]->(o:VisualObservation)
RETURN o.category, o.status, o.observation, o.confidence ORDER BY o.category;

// a Street with its images and their observations (graph view)
MATCH p=(s:Street {osm_id:1112487557})<-[:LOCATED_NEAR]-(:MapillaryImage)-[:HAS_OBSERVATION]->(:VisualObservation)
RETURN p;

// OSM evidence and visual evidence side by side (not merged, not equivalent)
MATCH (s:Street)<-[:LOCATED_NEAR]-(i:MapillaryImage)
OPTIONAL MATCH (s)-[:HAS_ELEMENT]->(e:StreetDesignElement)
WITH s, i, collect(DISTINCT e.category + ':' + e.subtype) AS osm_elements
MATCH (i)-[:HAS_OBSERVATION]->(o:VisualObservation {status:'visible'})
RETURN s.name, s.osm_id, osm_elements, i.mapillary_id, collect(o.category) AS vlm_visible_in_this_image;

// lighting: OSM lit tag + mapped lamps vs. what one image shows
MATCH (s:Street)<-[:LOCATED_NEAR]-(i:MapillaryImage)-[:HAS_OBSERVATION]->(o:VisualObservation {category:'lighting'})
RETURN s.name, coalesce(s.lit,'unknown') AS osm_lit_tag,
       COUNT { (s)-[:HAS_ELEMENT]->(:StreetDesignElement {subtype:'street_lamp'}) } AS osm_mapped_lamps,
       i.mapillary_id, o.status AS vlm_status, o.observation;
```

### Stage 4: V2 quality evaluation on 30 perspective images (no Neo4j import)

The V2 prompt and schema are unchanged. The purpose is to evaluate output quality before scaling. The new
observations are **not** imported into Neo4j; the graph keeps the 3 images and 48 observations from Stage 3.

```bash
uv run python src/select_vlm_sample.py            # 30 perspective images, greedy diversity, seed 0; downloads missing thumbnails
uv run python src/run_vlm.py --prompt-version v2 --sample data/processed/vlm_evaluation_sample.json
uv run python src/evaluate_vlm_quality.py         # descriptive report + review CSVs (local files only)
uv run python src/review_vlm_results.py --html    # data/visualizations/vlm_quality_review.html
uv run python src/review_vlm_results.py --image-id <id>   # or --all, in the terminal
uv run python src/test_vlm_evaluation.py          # sanity checks (no API, no Neo4j)
```

- **Sample:** `data/processed/vlm_evaluation_sample.json`. It holds the 3 original V2 images plus 27
  perspective images (panoramas and fisheye excluded). Each pick minimises repetition of street name,
  Mapillary sequence and capture year. Every entry records its `sample_reason`.
- **Review files:**
  - `data/processed/vlm_quality_review.csv`: one row per image, with status counts and the status of each
    category.
  - `data/processed/vlm_quality_review_observations.csv`: one row per observation, with empty
    `manual_label` and `manual_note` columns for human reviewers.
- **Review page:** `data/visualizations/vlm_quality_review.html` shows each image next to its 16
  observations. Red "review" notes mark keyword hits for known failure modes. They are prompts for a
  human to check, not correctness judgements.
- **Baseline protection:** `data/processed/vlm_baseline_sha256.json` freezes the V1 raw files and the
  original 3 V2 raw files; the tests check them.
- Results and decision criteria: `docs/vlm_quality_evaluation.md`.
- **Caveat:** `vlm_observations.jsonl` now contains V2 observations for all 30 images. Running
  `import_visual_observations.py` again would import all of them. Do not run it until the Stage 4
  results have been reviewed.

### Stage 5: invalid-output diagnosis, human-review setup, small Groq comparison (no Neo4j import)

V2 is **not ready to scale** (see Stage 4). This stage:
- diagnoses NVIDIA's invalid answers, with no API calls
- sets up human review
- tries the **same V2 instructions** on a separate provider, **Groq** `qwen/qwen3.8-27b` (free tier), for
  **5 already-downloaded perspective images**

Groq does **not** replace NVIDIA. NVIDIA stays the default provider and the production V2 dataset. Groq data
is stored separately and never mixed in, and nothing is imported into Neo4j.

```bash
uv run python src/diagnose_vlm_invalid.py        # why 8 NVIDIA answers were invalid (6 locally recoverable)
uv run python src/analyze_manual_review.py       # human labels per category (--file for the Groq review CSV)
uv run python src/select_groq_sample.py          # 5 images, deterministic (seed 0)
uv run python src/run_vlm.py --provider groq --prompt-version v2 --sample data/processed/groq_vlm_evaluation_sample.json
uv run python src/compare_vlm_providers.py       # NVIDIA V2 vs Groq side by side (no API calls)
uv run python src/test_vlm_stage5.py             # Stage 5 checks (no API, no Neo4j)
```

- **Human review:** fill `manual_label` (`correct` / `incorrect` / `uncertain`, empty = not reviewed) and
  `manual_note` in `data/processed/vlm_quality_review_observations.csv` (NVIDIA) and
  `data/processed/vlm_groq_quality_review_observations.csv` (Groq). Labels judge one provider's statement
  against the image. Notes are never turned into labels.
- **Groq request:** strict `json_schema` structured output, reasoning off, `temperature 0` and `seed 0`,
  sequential with at least 6 s between requests, honouring `Retry-After` on 429.
- **Free-tier limits observed** in the response headers: 1,000 requests per day and 8,000 tokens per
  minute. The token limit is the binding one, at about 2–3 images per minute.
- **Outputs:**
  - Groq: `data/raw/vlm_groq/`, `data/processed/vlm_groq_observations.jsonl`
  - comparison: `data/processed/vlm_provider_comparison.csv`
  - diagnosis: `data/processed/vlm_invalid_diagnosis.json`
  - frozen Stage 4 raw state: `data/processed/vlm_stage4_raw_sha256.json`
- **Write-up:** `docs/vlm_stage5.md`.

### Stage 6: human-labelled evaluation (no API calls, no Neo4j changes)

- **Local recovery:** 6 NVIDIA V2 answers that ended with one stray `}` are recovered locally, with no new
  API calls and the unchanged validator. They are stored separately in
  `data/processed/vlm_recovered_observations.jsonl`, with `recovery_method` set; the report is in
  `vlm_recovery_report.json`. The 2 genuinely malformed outputs stay failures.
- **Review set:** 27 images and 432 observations (21 valid + 6 recovered; the `vlm_source` column says
  which). A human labels them in a browser page that separates MODEL OUTPUT from HUMAN REVIEW.
- **Priority categories:** cycling_infrastructure, street_furniture, barriers, curb, lighting,
  public_transport; then signage, pedestrians, cyclists, motor_vehicles.
- **Provider comparison:** only on the 5 Groq images. It uses human labels only; each label judges one
  provider's own statement. A pair without both labels is `unresolved`. No ranking, no global score.

```bash
uv run python src/recover_vlm_json.py                     # 6 local recoveries (no API)
uv run python src/evaluate_vlm_quality.py                 # regenerate review CSVs (existing labels are kept)
uv run python src/review_vlm_results.py --html            # data/visualizations/vlm_quality_review.html
uv run python src/merge_manual_labels.py --input ~/Downloads/manual_labels_nvidia.csv --dry-run   # Stage 7 interface
uv run python src/analyze_manual_review.py                # per category: reviewed/correct/incorrect/uncertain
uv run python src/compare_vlm_providers.py                # human-label outcomes for NVIDIA vs Groq
uv run python src/test_vlm_stage6.py
```

- **Labels:** `correct` / `incorrect` / `uncertain`, empty = unreviewed. They judge the statement against the
  image only. For `not_visible`: `correct` if the image gives no sufficient evidence, `incorrect` if the
  element is clearly visible.
- **Write-ups:** `docs/vlm_stage6.md`, `docs/vlm_category_boundary_analysis.md`,
  `docs/vlm_prompt_v3_design.md` (design only; V3 is not run).
- **Frozen files:** `data/processed/vlm_baseline_sha256.json`, `vlm_stage4_raw_sha256.json` and
  `vlm_groq_stage5_sha256.json`.

### Stage 7: human annotation and a small inter-reviewer check (no API calls, no Neo4j changes)

Human annotation starts here. **Labels come from human reviewers only**, never from an AI system; earlier
assistant notes are not labels. First target: the **6 locally recovered images** (96 observations),
priority categories first. Partial labelling is fine.

```bash
uv run python src/review_vlm_results.py --html                  # recovered images first ("FIRST BATCH")
uv run python src/merge_manual_labels.py --input manual_labels_nvidia.csv --dry-run
uv run python src/merge_manual_labels.py --input manual_labels_nvidia.csv
uv run python src/analyze_manual_review.py --batch recovered
uv run python src/compare_vlm_providers.py                      # one human label per image/category; Groq at status level
uv run python src/select_second_reviewer_sample.py              # 24 observations, no reviewer-1 labels shown
uv run python src/review_vlm_results.py --html --provider second
uv run python src/merge_manual_labels.py --target second --input manual_labels_second.csv
uv run python src/analyze_inter_reviewer.py
uv run python src/test_vlm_stage7.py
```

- **Merge rules:** the merge is non-destructive and idempotent. Empty input labels never clear anything;
  existing different labels are kept and reported as conflicts unless you pass `--overwrite`; model fields
  are never written.
- **Reviewer 1:** `manual_label` / `manual_note` in `data/processed/vlm_quality_review_observations.csv`.
- **Reviewer 2:** `reviewer2_label` / `reviewer2_note` in `data/processed/manual_review_second_reviewer_sample.csv`.
- **Rules and results:** `docs/vlm_stage7.md`. Until labels are entered, every dependent result reads
  "unresolved / no labels".

## Stop

```bash
docker compose down           # keeps data (volume neo4j_data)
docker compose down -v        # also deletes the database
```

Note: the password in `.env` is applied only when the database volume is
first created. To change it later, run `docker compose down -v` first.

## Layout

```
src/            Python code
data/raw/       raw downloaded source data (kept for reproducibility)
data/visualizations/  generated HTML graph views
data/sample/    small sample/dummy data for development
docs/           references and notes
```
