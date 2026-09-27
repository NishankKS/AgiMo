# Stage 5: VLM diagnostics, human-review setup and a small Groq comparison (Phase 5)

All scripts named here read local files, except `run_vlm.py --provider groq` (5 calls). Nothing was imported
into Neo4j, and NVIDIA was not called in this stage. This document gives no overall score and no ranking.

## 1. Objective

Stage 4 showed that NVIDIA V2 is not ready to scale: 8 of 26 answers were invalid, and several category
confusions recurred. This stage:
- (A) finds out exactly why those answers were invalid
- (B) sets up human review
- (C–J) runs the same V2 instructions on a second, separate provider (Groq) for 5 images, to separate
  provider/model effects from prompt effects

Groq does **not** replace NVIDIA. Its data is stored separately and never mixed into the production V2 files.

## 2. NVIDIA invalid-output diagnosis

`uv run python src/diagnose_vlm_invalid.py` writes `data/processed/vlm_invalid_diagnosis.json`.

| Image | Class | Locally recoverable | Cause |
|---|---|---|---|
| 1391393364587653, 2653450758168746, 463348118303970, 524573645227846, 748701757218369, 932582530826779 | other parser/formatting problem | **yes** (6) | A complete, well-formed JSON object followed by **one stray `}`**. There is no markdown, no `<think>` tag and no surrounding text (only a leading newline). The production extractor takes everything from the first `{` to the last `}`, so it includes the stray brace and `json.loads` reports "Extra data". The first object passes the existing strict validator **unchanged**. |
| 386064122572974 | malformed/truncated/garbage | no | The JSON breaks after **338 `<unk>` tokens** and turns into a markdown list (960 completion tokens). |
| 3071421596475336 | malformed/truncated/garbage | no | A **12-token** output: `{"image_quality_</think>ce\n%0`. |

No invalid answer was a schema mismatch. All 8 finished with `finish_reason=stop`, so none was cut off by
the token limit. The production validator was **not** changed, and no raw data was rewritten. Accepting the
first complete object would recover 6 answers without any new API calls. That is a decision for the next
stage.

## 3. Human-review methodology

- **Files:** NVIDIA: `data/processed/vlm_quality_review_observations.csv`. Groq:
  `data/processed/vlm_groq_quality_review_observations.csv`.
- **Labels:** in `manual_label`, write `correct`, `incorrect` or `uncertain`; empty means not reviewed.
  `manual_note` is free text and is **never** converted into a label.
- **What is judged:** the statement against the image only, not against OSM. `not_visible` is judged as "no
  sufficient visual evidence in this image".
- **Separate labels per provider:** a label judges one provider's statement, so NVIDIA labels are *not*
  copied into Groq's `manual_label`. The Groq file shows them read-only in `nvidia_manual_label`.
- **Summary:** `uv run python src/analyze_manual_review.py [--file …]`. It counts reviewed / correct /
  incorrect / uncertain per category, in the review-priority order (street_furniture,
  cycling_infrastructure, barriers, curb, lighting, public_transport, pedestrians, cyclists,
  trees_vegetation, motor_vehicles, then the rest). It gives no overall score.
- **Current coverage: 0 of 336 NVIDIA observations and 0 of 80 Groq observations are labelled.** No human
  labels exist yet. The assistant's visual spot checks in Stages 2 and 4 are documented in the prose, but
  they are **not** entered as labels.

## 4. Groq model and provider setup

- **Model:** `qwen/qwen3.8-27b`. The account's `/models` endpoint lists it as active, with input `text` and
  `image`, a 131,072-token context and features `json_mode` and `reasoning`.
- **Endpoint:** `https://api.groq.com/openai/v1/chat/completions`, called by `run_vlm.py --provider groq`.
  NVIDIA remains the default provider and its code path is unchanged: the rebuilt NVIDIA JSONL is
  byte-identical.
- **Request:** one image per request, sent as a base64 data URL.
- **Structured output:** `response_format = json_schema`, `strict: true`, with the V2 structure (16-category
  enum, 3-status enum). Groq's docs say strict mode constrains output at the token level for Qwen 3.8 27B.
  Exactly-one-per-category and the confidence range are still checked by the existing validator.
- **Reasoning:** `reasoning_effort: "none"` and `reasoning_format: "hidden"`, the equivalent of NVIDIA's
  `enable_thinking=false`.
- **Sampling:** `temperature 0` and `seed 0`. Groq has no `top_k`, so this is the closest to NVIDIA's
  `top_k 1`. **This differs from the NVIDIA settings.**
- **Prompt:** the V2 text, byte-identical (the SHA-256 is recorded in every raw file), labelled
  `v2-groq-comparison`. There is no V3.
- **Storage:**
  - `data/raw/vlm_groq/<id>__v2-groq-comparison.json`: request settings, prompt hash, raw response,
    validation, rate-limit headers.
  - `data/processed/vlm_groq_observations.jsonl`: each record has `provider='groq'`,
    `source='Groq hosted VLM'` and `confidence_is_uncalibrated=true`.
  - `model_version` is null. The API returns only a `system_fingerprint`, which is recorded separately and
    not treated as a version.
- **Free-tier use, as observed in the response headers:** `x-ratelimit-limit-requests: 1000` (per day),
  `x-ratelimit-limit-tokens: 8000` (per minute). The per-minute request limit was not exposed. No account
  upgrade was made.
- **Rate handling:** requests are sequential and at least 6 s apart (≤ 10/min). 429s are handled by
  honouring `Retry-After`, then backing off 2, 5 and 10 s. 5xx gets a bounded retry, and 400/401/403/404
  stop the run.

## 5. Five-image comparison sample

`uv run python src/select_groq_sample.py` writes `data/processed/groq_vlm_evaluation_sample.json`. It is
deterministic with seed 0 and needs no downloads.

The candidates are Stage 4 images with a *valid* NVIDIA V2 response, which is required for a side-by-side.
Each condition is detected from NVIDIA's own claims, which may be wrong.

| Image | Street | Conditions met |
|---|---|---|
| 904858026737408 | way/585204095 (unnamed) | bicycle parking reported, curb on cobblestone, tram infrastructure reported |
| 478782403204273 | Bautzner Straße | fence/barrier, lighting |
| 399936865459221 | unlinked | fence/barrier |
| 709179964757083 | way/369367302 (unnamed) | bicycle parking |
| 1172482813194388 | Louisenstraße | diversity fill |

All five conditions are covered, across 5 different street groups.

## 6. Structured-output reliability

`uv run python src/compare_vlm_providers.py`

| | NVIDIA V2 (Stage 4 responses) | Groq (this stage) |
|---|---|---|
| Requested / responses / valid / invalid | 5 / 5 / 5 / 0 | 5 / 5 / 5 / 0 |
| Retries, HTTP errors | 2 retries, 2 × 503 | 4 retries, 4 × 429 |
| Latency per call | 13.7–26.2 s | 1.8–2.0 s |
| Tokens per call | 2,165–2,424 | 2,305–3,397 |
| Observations | 80 (50 visible / 29 not_visible / 1 uncertain) | 80 (49 / 31 / 0) |
| Confidence (uncalibrated) | 79/80 ≥ 0.9, 8 × 1.0 | 68/80 ≥ 0.9, 6 × 1.0 |

**Caveat:** NVIDIA's 5/5 is **true by construction**, because only images with a valid NVIDIA answer
were eligible. NVIDIA's real Stage 4 rate is 18 of 26 valid answers. Groq's 5/5 comes from 5 fresh calls
with strict schema mode, and 5 calls say little about its long-run rate.

The Groq 429s came from the 8,000 tokens-per-minute limit (about 2,300–3,400 tokens per image), not from
the request rate. Two different `system_fingerprint`s appeared across the 5 calls, so the backend
configuration changed during the experiment.

## 7. Semantic observations

The two providers agree on status for 67 of 80 image/category pairs and differ on 13. **Every difference
is unresolved, because there are no human labels.** Full side-by-side:
`data/processed/vlm_provider_comparison.csv`. The main differences in the focus categories:

| Image | Category | NVIDIA V2 | Groq |
|---|---|---|---|
| 904858026737408 | public_transport | visible: "Tram tracks run along the roadway" | not_visible |
| 904858026737408 | cycling_infrastructure | visible: bicycle rack | not_visible |
| 904858026737408 | lighting | not_visible | visible: lamp on the right-hand façade |
| 904858026737408 | cyclists / pedestrians | visible: person pushing a bicycle / pedestrians near the DHL truck | not_visible / not_visible |
| 478782403204273 | public_transport | not_visible | visible: "overhead wires for trams or trolleybuses" |
| 478782403204273 | street_furniture | visible: street-light and signal poles | visible: metal railing (both outside the V2 definition) |
| 709179964757083 | lighting | not_visible | visible: lamp posts in the background, shop lights |
| 1172482813194388 | curb | uncertain | visible, both sides |
| 1172482813194388 | street_furniture | not_visible | visible: "possibly a kiosk or utility box" |

**Assistant spot check, not a human label:** `904858026737408` was inspected by eye in Stage 4. There were
no tram tracks (cobblestone gutters), no person with a bicycle, and distant pedestrians near the truck. On
this one image, Groq's `not_visible` for tram tracks and the cyclist is consistent with that check, and its
`not_visible` for pedestrians is not. One image cannot support a general statement.

**Patterns shared by both providers** (visible in the text itself, no image judgement needed):
- **Bicycle racks as `cycling_infrastructure`** (709179964757083, both providers), although the V2
  definition puts racks under street_furniture.
- **Curb:** `visible` in at least 4 of 5 images for both.
- **Street furniture:** both put signs or advertising columns under street_furniture, as well as signage.

**NVIDIA-only inconsistency:** the `cyclists` entry for 709179964757083 has status **visible** but the text
says "No people are visible riding or pushing bicycles". The status contradicts the text.

## 8. Limitations

- 5 images. The sample was selected from NVIDIA-valid images using NVIDIA's own claims, so it is biased.
- No human labels, so no correctness statement is possible for either provider.
- Different sampling settings (NVIDIA `top_k 1` vs Groq `temperature 0`), different hardware, and possibly
  changing backends. Neither provider reports a model version.
- Groq strict mode prevents malformed JSON. It does not prevent wrong or inconsistent content.
- Confidence is uncalibrated for both providers. `not_visible` is not absence.

## 9. Implications for a future V3 (not created)

- The category boundaries are the main semantic weakness, and **both** models show it: bicycle racks
  (cycling_infrastructure vs street_furniture), fences and railings (street_furniture vs barriers), signs
  and advertising columns (street_furniture vs signage). V3 would need an explicit research decision on
  these boundaries, not just stronger wording.
- `uncertain` is almost never used (1 of 336 in Stage 4, 0 of 80 for Groq). Curb over-claiming persists.
- The status/text contradiction suggests adding a consistency warning to the validator. That is a
  validator change, not a prompt change.
- Structured-output enforcement at the API level (Groq strict mode) removed the formatting failure class
  in this small run. NVIDIA's failures were 75 % locally recoverable.

## 10. Next-stage decision (proposal only)

1. **Human-label** the 80 + 80 statements for the 5 comparison images, and the priority categories for the
   21 NVIDIA images. Without this, no provider or category decision is justified.
2. **Decide** whether to accept the first complete JSON object, with a recorded warning, in the NVIDIA
   validator. That recovers 6 of 8 answers without new calls.
3. **Decide the category boundaries** (bicycle racks, fences, signs) as a research decision. Only then draft
   V3, and test it on the same labelled images.
4. **If Groq is used further:** pace by tokens (8,000 per minute ≈ 2–3 images per minute) and respect
   1,000 requests per day.
