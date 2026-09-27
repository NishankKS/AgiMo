# V2 VLM quality evaluation on 30 perspective images (Phase 5, Stage 4)

The numbers come from `uv run python src/evaluate_vlm_quality.py`, which reads only local files. This is a
descriptive evaluation. It gives no overall quality score and does not rank images or streets. VLM output
is not ground truth.

## 1. Objective

To decide whether the unchanged `b1-prompt-v2` pipeline is reliable enough to run on more images, before any
larger visual layer goes into Neo4j. The 30-image output is **not imported**. Neo4j still holds the
Stage 3 layer of 3 images and 48 observations.

## 2. Sample selection

`src/select_vlm_sample.py` writes `data/processed/vlm_evaluation_sample.json`.

- **Pool:** 653 perspective images (`camera_type == 'perspective'`, not panorama). Excluded: 550
  panoramas, 115 fisheye and 39 with no camera type.
- **Rule:** always keep the 3 original V2 images. Then, greedily, take the image that minimises
  max(street-name use, sequence use), then their sum, then capture-year use. Ties go to images already
  downloaded, then to a seeded random order (seed 0). Each pick records its `sample_reason`.
- **My first attempt** ordered by street use first. That put one sequence into the sample 5 times, so it
  was replaced by the minimax rule above.
- **Downloads:** 27 thumbnails via the Stage 1 code: 25 for the first selection (23 of which are reused in
  the final sample) and 2 for the final one.
- **Result:** 30 images (all perspective), 14 street names (19 street ways, including 2 unnamed), 25
  sequences. 28 are linked to a street and 2 are unlinked.
- **Years:** 2014: 3, 2015: 2, 2016: 3, 2017: 5, 2018: 4, 2019: 3, 2022: 2, 2024: 4, 2026: 4.
- **Pool limits:** the perspective pool has no 2025 images, and it covers only 11 street names, so only 14
  street groups can appear.

## 3. V2 configuration (unchanged)

- Model `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning`, NVIDIA-hosted. Reasoning off, `temperature 1.0`,
  `top_k 1`, `max_tokens 2048`.
- Prompt `b1-prompt-v2` and schema `b1-visual-obs-v1`, with 16 categories and statuses
  `visible`/`not_visible`/`uncertain`.
- Every record has `confidence_is_uncalibrated = true`. The API reports no model version.
- Requests are sequential, paced to at most 30 per minute, with up to 3 retries (2, 5 and 10 s, or
  `Retry-After`) on 429/503. Valid responses are cached.

## 4. Results

**Inference (27 new images; the 3 originals were cached):**

| | n |
|---|---|
| API calls | 27 (42 attempts, 15 retries, 16 × HTTP 503, 0 × HTTP 429) |
| Answered | 26 |
| Failed (HTTP 503 after 3 retries, NVIDIA shared capacity) | 1: `510142960122831` |
| Answered but **invalid** (strict validator) | **8** |
| Valid | 18 new + 3 original = **21 of 30** |

The 8 invalid responses:
- **6 × a stray extra `}` after a complete, well-formed JSON object.** All 16 observations are there,
  but the parser rejects the output. Images: 2653450758168746, 748701757218369, 524573645227846,
  463348118303970, 1391393364587653, 932582530826779.
- **1 × degenerate generation** (`386064122572974`): a run of `<unk>` tokens followed by a markdown
  list.
- **1 × a 30-character garbled fragment** (`3071421596475336`): `{"image_quality_</think>ce…`.

The validator was deliberately not relaxed during this stage. Format reliability is itself a finding:
**8 of 26 answers (31 %) were not valid JSON.**

**Valid output (21 images):**
- 336 observations, 16 per image. 0 duplicates, 0 unexpected categories or statuses, 0 missing categories.
- 0 value-judgement words, and 0 absence claims on `not_visible` entries.
- Status: 197 visible, 138 not_visible, **1 uncertain**.
- Confidence (uncalibrated): min 0.6, median 0.98, max 1.0. 99.1 % are ≥ 0.9, and **116 of 336 are
  exactly 1.0**; in Stage 2, V2 produced none at 1.0.
- Latency 8.2–30.7 s per call. 1,452–1,804 prompt tokens and 666–791 completion tokens per image.

## 5. Category / status distributions (21 valid images)

| category | visible | not_visible | uncertain |
|---|---|---|---|
| sidewalk | 20 (95 %) | 1 (5 %) | 0 |
| roadway | 20 (95 %) | 1 (5 %) | 0 |
| curb | 20 (95 %) | 0 | 1 (5 %) |
| crossing | 0 | 21 (100 %) | 0 |
| cycling_infrastructure | 5 (24 %) | 16 (76 %) | 0 |
| parking | 15 (71 %) | 6 (29 %) | 0 |
| trees_vegetation | 15 (71 %) | 6 (29 %) | 0 |
| street_furniture | 16 (76 %) | 5 (24 %) | 0 |
| lighting | 4 (19 %) | 17 (81 %) | 0 |
| signage | 16 (76 %) | 5 (24 %) | 0 |
| barriers | 7 (33 %) | 14 (67 %) | 0 |
| public_transport | 4 (19 %) | 17 (81 %) | 0 |
| building_frontage | 21 (100 %) | 0 | 0 |
| pedestrians | 12 (57 %) | 9 (43 %) | 0 |
| cyclists | 5 (24 %) | 16 (76 %) | 0 |
| motor_vehicles | 17 (81 %) | 4 (19 %) | 0 |

These counts say what the model reported. They are not frequencies of the features in the street.

## 6. Sample diversity

- **Street:** 14 groups. The largest (Bautzner Straße) has 10 % of the sample, the top 3 have 30 %,
  and 3 groups have one image.
- **Sequence:** 25 groups. The largest has 10 % and the top 3 have 23 %; 21 sequences have one image.
- **Year:** 9 groups. The largest (2017) has 17 % and the top 3 have 43 %.
- **Concentration:** no dimension is dominated by one group. The remaining limits come from the pool:
  11 street names, and no perspective images from 2025. Invalid or failed responses remove 9 images unevenly:
  all 3 Glacisstraße images and the only Jordanstraße image are among them.

## 7. Known failure modes: do they recur?

Keyword flags (`FLAGS` in `evaluate_vlm_quality.py`) point to candidates for manual review. They do not
judge correctness. I also looked at 3 more images by eye: `904858026737408`, `508680623658739`, and the
invalid `2653450758168746`. Together with the 3 Stage 2 images, that is 5 valid images and 1 invalid
image inspected. The other 16 valid images are **not yet manually reviewed**.

| Failure mode | What Stage 4 shows |
|---|---|
| Vehicle type confusion | No bus/tram mix-up in the valid output. `2653450758168746` (invalid) says "yellow bus", which looks plausible. **New related error:** on `904858026737408` the cobblestone drainage gutters are called "tram tracks" (roadway + public_transport); no tracks exist. The tram tracks on `508680623658739` and on Bautzner Straße are real. |
| Lighting as daylight | 1 case: "No physical street-lighting fixtures are visible; the scene is lit by daylight" (status not_visible, so only the wording). |
| Overhead lighting | lighting is visible in only 4 of 21 images. One is "recessed spotlights on the ceiling of the corridor" in a passage, which is arguably not street lighting. Whether lamps are missed needs manual review. |
| Capture artefacts | No capture equipment reported as a streetscape element. The one flag is a false positive ("walking away from the camera"). |
| Curb over-claim | curb is visible in 20 of 21 images and `uncertain` in 1. The Julie-Salinger-Weg shared-surface claim from Stage 2 is still there. Very likely over-reported; needs manual labels. |
| Street-furniture hallucination | Unverified claims recur: benches (Bautzner), a "bicycle rack" that looks like a parked bicycle (`904858026737408`). The category also collects things outside its definition: fences, a parked bicycle, signs, street-light and traffic-signal poles, an advertising pillar, a wall and gate. |
| Bicycle-infrastructure confusion | **Recurring:** all 5 `visible` cycling_infrastructure entries describe bicycle racks, which the V2 prompt assigns to street_furniture. No cycle lanes were reported in the valid output, although `2653450758168746` (invalid) visibly has a red cycle lane with a bicycle symbol. |
| Fence counted as furniture and barrier | **Recurring:** 4 images (2302498470581445, 460745525028316, 1616802312752146, 2692011060961999). |
| Incomplete sidewalk | 12 of 20 visible sidewalk entries mention one side only. This may be correct for the viewpoint; needs manual review. |
| Overconfident confidence | **Worse than Stage 2:** 116 of 336 at exactly 1.0, and 99.1 % ≥ 0.9, including the errors found above. |
| **New: format failures** | 6 stray trailing braces and 2 degenerate outputs (31 % of answers). |
| **New: hallucinated person** | `904858026737408`: "A person is pushing a bicycle"; only a parked bicycle is visible. |
| **New: text reading** | `904858026737408`: the "Freiberger" sign is read as "Treiberegt". |

## 8. Manual review procedure

1. Run `uv run python src/review_vlm_results.py --html` and open `data/visualizations/vlm_quality_review.html`.
   Each image is shown next to its 16 observations, with red "review" notes. For one image in the terminal:
   `uv run python src/review_vlm_results.py --image-id <id>`.
2. For each observation, fill in `manual_label` in `data/processed/vlm_quality_review_observations.csv` with
   one of `correct`, `incorrect` or `uncertain`; empty means not reviewed. You can add a `manual_note`. Judge
   against the image only, not against OSM. `not_visible` is judged as "no sufficient evidence in this
   image". Notes are never converted into labels. (Label set as specified in Stage 5.)
3. Summarise per category with `uv run python src/analyze_manual_review.py` (descriptive; no overall score).

## 9. Limitations

- 21 valid images is small, and only 5 of them have been inspected by eye.
- The keyword flags are recall aids and have false positives, such as "camera".
- The sample is limited by the pool: 11 street names, and no 2025 perspective images. The
  invalid/failed images are not random with respect to street.
- One image per location and moment. The images are 1024-px thumbnails.
- The model output is probabilistic. The hosted model may change without a version number, because
  none is reported.
- Confidence is uncalibrated and must not be used for filtering or ranking.
- `not_visible` is not absence.

## 10. Decision criteria for the next stage (not implemented)

Before V2 output is scaled up or imported:

1. **Format reliability:** decide how to handle the 31 % invalid answers. Options: a stricter
   retry-on-invalid policy (more API calls), or accepting the first complete JSON object with a recorded
   warning, which would recover the 6 stray-brace cases without new calls. Also decide whether to re-run
   the 1 failed and 2 degenerate images.
2. **Human labels:** complete `manual_label` for the 21 valid images, so there is a reference to compare
   against.
3. **Per-category decision:** based on those labels, decide per category whether V2 is usable as is,
   usable only with caveats, or not usable. Likely problem categories from this stage: curb,
   street_furniture, cycling_infrastructure, public_transport (the gutter case) and lighting.
4. **Confidence:** decide whether to exclude it from all analyses, since 116 of 336 values are exactly 1.0
   and it is not informative.
5. **Only then** consider a prompt revision (V3), panorama or fisheye experiments, or a larger import.
