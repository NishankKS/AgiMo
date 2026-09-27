# Stage 6: human-labelled evaluation (Phase 5)

No API calls (NVIDIA, Groq or Mapillary), no V3, no Neo4j changes. All earlier raw files are frozen by
checksum manifests.

## 1. Objective

Build a small, explicit, human-reviewed reference set for the problem categories before V3 is designed.
This stage provides the recovery, the review tooling, the analysis and the documents. **The labels
themselves have to come from a human reviewer.** At the time of writing none have been entered, and the
assistant deliberately did not fill them in.

## 2. Local NVIDIA recovery

`uv run python src/recover_vlm_json.py`

- **Scope:** only the 6 known IDs (1391393364587653, 2653450758168746, 463348118303970, 524573645227846,
  748701757218369, 932582530826779).
- **Checks for each:** the raw file matches the frozen Stage 4 checksum; it contains a complete JSON object
  followed by exactly one `}` (after a newline in 524573645227846); exactly one character is removed; the
  **unchanged** `run_vlm.parse_and_validate` then passes.
- **Result: 6 of 6 recovered.** 96 observations (57 visible, 38 not_visible, 1 uncertain) and 0 validation
  warnings, saved separately in `data/processed/vlm_recovered_observations.jsonl` with
  `recovery_method = "remove_one_trailing_stray_brace"` and the raw file's SHA-256. The report is in
  `data/processed/vlm_recovery_report.json`.
- **Genuine failures, not attempted:** 386064122572974 (`<unk>` run, then a markdown list) and
  3071421596475336 (a 12-token fragment).
- The raw files and the production `vlm_observations.jsonl` are unchanged (checked by test).

## 3. Human annotation methodology

- **Reference set:** 27 images and 432 observations. That is the 21 valid V2 images (336 observations) plus
  the 6 recovered images (96). The `vlm_source` column says `valid_v2` or `recovered_v2`. There are no
  duplicates.
- **Tool:** `uv run python src/review_vlm_results.py --html` opens `data/visualizations/vlm_quality_review.html`.
  - The page shows the image, ID, street, capture date and sequence. Per category, a grey **MODEL OUTPUT**
    block shows status, observation and confidence. A separate yellow, dashed-border **HUMAN REVIEW** block
    holds correct / incorrect / uncertain / unreviewed buttons and a note field.
  - Keyword flags are deliberately not shown on this page, to avoid steering the reviewer.
  - The page autosaves in the browser. "Download labels CSV" exports the labels.
- **Merge:** `uv run python src/merge_manual_labels.py --input manual_labels_nvidia.csv` (Stage 7 interface;
  it was a positional argument in Stage 6). It changes only
  `manual_label` and `manual_note`. It rejects unknown image/category keys and labels other than `correct`,
  `incorrect`, `uncertain` or empty. Every change is listed. Use `--dry-run` first.
  - Alternatively, edit `data/processed/vlm_quality_review_observations.csv` directly.
  - Re-running `evaluate_vlm_quality.py` now **keeps** existing labels. It used to reset them; that bug was
    fixed in this stage.
- **Groq (superseded in Stage 7):** Stage 6 had a separate Groq labelling page and merge target. Stage 7 removed
  them: one human label per image/category is used for both providers (see `docs/vlm_stage7.md`). In Stage 6 NVIDIA
  labels were shown only as reference, because
  each label judges one provider's own statement.
- **Rules:**
  - Judge each statement against the image only, not against OSM or the other provider.
  - For a `not_visible` statement: `correct` if the image really gives no sufficient evidence, `uncertain`
    if it is ambiguous, `incorrect` if the element is clearly visible.
  - Do not infer hidden infrastructure.
  - Notes are never converted into labels or error reasons.

## 4. Priority categories

Review first: cycling_infrastructure, street_furniture, barriers, curb, lighting, public_transport (shown in
bold on the page). Then signage, pedestrians, cyclists, motor_vehicles, and the rest if practical. For the
27 images, the six priority categories are 162 statements. Adding the next four gives 270.

## 5. Human-review results

`uv run python src/analyze_manual_review.py`

**Current state: 0 of 432 observations reviewed (0 images).** Every category shows reviewed = 0. Nothing
can be said about correctness yet. The tool reports, per category, reviewed / correct / incorrect /
uncertain / unreviewed, plus disagreement examples with verbatim notes and the boundary-group table.

## 6. Provider comparison where labels exist

`uv run python src/compare_vlm_providers.py`

For each of the 80 image/category pairs of the 5 Groq images, the outcome is one of: both agree with the
human label; NVIDIA agrees and Groq does not; Groq agrees and NVIDIA does not; both disagree; human label
uncertain; or **unresolved** (a label is missing).

**Current state: 80 of 80 unresolved.** There is no ranking, no global score, and no extrapolation from 5
images.

## 7. Category-boundary findings

See `docs/vlm_category_boundary_analysis.md`. It holds the model-statement groupings and the questions for
the reviewer. **There are no human-supported findings yet.**

## 8. V3 design implications

See `docs/vlm_prompt_v3_design.md`.
- **Output-format changes** are supported by the Stage 4–5 diagnostics: one JSON object only; strict schema
  where the API supports it; a validator option to accept the first complete object; a warning for
  status/text contradictions.
- **Evidence rules, category definitions and ambiguity rules** are **pending** human labels.

## 9. Limitations

- **No human labels yet.** The reference set exists as tooling and data only.
- 27 images, with a pool limited to 11 street names; 1024-px thumbnails.
- The recovered observations come from answers that were originally invalid. They are kept distinguishable
  (`vlm_source`) in case their quality differs.
- A single reviewer's labels are one person's judgement. Consider a second reviewer on a subset.
- Confidence is uncalibrated and is not used anywhere.

## 10. Next-stage decision

1. **A human labels at least the 6 priority categories for the 27 images** (162 statements), and the 5
   Groq images (both providers: 2 × 5 × 16 = 160, or 2 × 5 × 6 = 60 for priority only).
2. Re-run `analyze_manual_review.py` and `compare_vlm_providers.py`, then write the human-supported
   sections of the boundary analysis.
3. Only then decide the category boundaries and whether to adopt the first-object parser, and draft V3.
