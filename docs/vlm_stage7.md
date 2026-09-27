# Stage 7: human annotation and a small inter-reviewer check (Phase 5)

No API calls (NVIDIA, Groq or Mapillary), no V3, no Neo4j changes. Human labels are entered **only by
people**. No AI system, Claude Code included, generates or infers them, and earlier visual notes by the
assistant are not labels.

**Status at the time of writing: human labels = 0** (reviewer 1: 0 of 432; reviewer 2: 0 of 24). Every result
section below is therefore **unresolved / no labels**. The scripts produce the results without any change
of method once labels are merged.

## 1. Objective

Create the first human reference data: a focused first batch (the 6 locally recovered images, 96
observations), plus a small second-reviewer subset. The aim is to learn whether the model statements are
supported by the images, and whether the category definitions are clear enough for humans to apply
consistently.

## 2. Annotation protocol

The reviewer answers one question per statement: **"Is the VLM's status and observation supported by the
visible image?"** The labels are `correct`, `incorrect`, `uncertain`, or blank (unreviewed). The reviewer
does not rewrite model output, does not compare providers, and does not judge the model in general.

| Model status | correct | incorrect | uncertain |
|---|---|---|---|
| visible | the described object/category is visibly supported | it is clearly not supported | ambiguous visual evidence |
| not_visible (= insufficient evidence, **not** absence) | the image does not provide enough visible evidence | the object/category is clearly visible | cannot tell whether it is visible |
| uncertain | the model was right to express uncertainty | the evidence clearly supports visible or not_visible | genuinely ambiguous |

- `manual_note` is free text and is never converted into a label or an error reason.
- Partial labelling is supported: unlabelled rows simply stay unreviewed.
- Model confidence is shown with the mark "uncalibrated" and is not used.

## 3. First annotation batch

```bash
uv run python src/review_vlm_results.py --html          # the 6 recovered images come first, marked FIRST BATCH
xdg-open data/visualizations/vlm_quality_review.html     # label; the page autosaves in the browser
# click "Download labels CSV" -> manual_labels_nvidia.csv
uv run python src/merge_manual_labels.py --input manual_labels_nvidia.csv --dry-run
uv run python src/merge_manual_labels.py --input manual_labels_nvidia.csv
uv run python src/analyze_manual_review.py --batch recovered
```

- **Label order within each image:** cycling_infrastructure, street_furniture, barriers, curb, lighting,
  public_transport (bold on the page), then signage, pedestrians, cyclists, motor_vehicles, then the rest.
- **Merge rules:**
  - An empty label in the input never clears or creates a label. The export lists every row, labelled or not.
  - An existing different label is a *conflict*: it is kept and reported, unless `--overwrite` is given
    explicitly.
  - The merge is idempotent: running it twice changes nothing the second time.
  - Model fields are never written.
- **Fixed in this stage:** the Stage 6 merge would have **cleared** existing labels when a page export with
  empty rows was merged.

## 4. Human-label results

`uv run python src/analyze_manual_review.py [--batch recovered]` reports, per category, reviewed / correct /
incorrect / uncertain / unreviewed. It marks categories with at least 5 labels as inspectable. It lists
every incorrect or uncertain row with image, category, provider/model, model status and observation,
label, and the verbatim note. It gives no overall score.

**Current: 0 of 96 labelled in the first batch, 0 of 432 overall. Unresolved / no labels.**

## 5. Category-boundary evidence

`docs/vlm_category_boundary_analysis.md` is to be updated **only** with findings supported by human labels.
**Current: no human-supported findings (0 labels).** A single labelled error would count as evidence of an
error, not as a boundary rule.

## 6. Groq/NVIDIA comparison where labels exist

- **Method (changed in Stage 7):** there is **one human label per image/category**, in the NVIDIA review
  file. It is used for both providers; there are no separate Groq labels, and the Stage 6 Groq labelling
  page and merge target are removed.
- **NVIDIA:** judged directly by the label.
- **Groq:** compared at **status level**, against the status the label implies:
  - correct → NVIDIA's status is confirmed
  - `not_visible` + incorrect → the category is visible
  - `visible` + incorrect → NVIDIA's claim is unsupported
  - If NVIDIA's `visible` claim was judged incorrect and Groq also says `visible`, the case is
    **unresolved**. Groq may be describing a different object, and the label doesn't judge Groq's text.
- **Classes:** both agree with human / NVIDIA agrees, Groq disagrees / Groq agrees, NVIDIA disagrees /
  both disagree / human uncertain / unresolved. No winner, no ranking, no generalisation from 5 images.
- **Current: 80 of 80 unresolved.** Note also that the 5 Groq images are *not* in the first batch (the
  recovered images). Labelling the first batch alone will leave the provider comparison unresolved.

## 7. Second-reviewer subset

- **Created by:** `uv run python src/select_second_reviewer_sample.py`, which writes
  `data/processed/manual_review_second_reviewer_sample.csv`.
- **Content:** 24 observations from the 6 recovered images, 4 per priority category, deterministic (seed 0),
  mixing statuses where the data allows. Overall 11 visible, 12 not_visible and 1 uncertain. Curb has no
  `not_visible` statements in these images.
- **Independence:** the file and its page (`--provider second`, `data/visualizations/vlm_second_reviewer_review.html`)
  contain image metadata and model output only. There are **no reviewer 1 labels or notes** and no provider
  comparison. Reviewer 2's labels go into separate columns (`reviewer2_label`, `reviewer2_note`) via
  `merge_manual_labels.py --target second --input manual_labels_second.csv`.

## 8. Inter-reviewer agreement

`uv run python src/analyze_inter_reviewer.py` reports:
- the number jointly labelled
- the exact agreement count
- the disagreements, and how many involve `uncertain`
- each disagreement with both labels and both notes

Neither reviewer is treated as correct. 24 observations is a comprehensibility check, not a formal
reliability study.

**Current: 0 jointly labelled. Unresolved / no labels.**

## 9. Limitations

- **No labels yet.**
- The first batch is 6 images, all originally *invalid* answers that were recovered. They may not represent
  the other 21 images.
- One or two reviewers; small subsets. The Groq comparison is status-level only.
- 1024-px thumbnails, one viewpoint per location. Confidence is not used.

## 10. Decision criteria for V3

A V3 draft needs, at minimum:
1. **Human labels for the priority categories** in the first batch, and ideally in the 5 Groq images and the
   remaining 21 images, enough per category to see a pattern rather than single cases.
2. **Second-reviewer labels** on the 24-observation subset. Where reviewers disagree often in a category,
   the definition itself must be clarified first; a model prompt can't fix that.
3. **Category-boundary decisions** (bicycle racks, fences/railings, signs, curb vs gutter) made as research
   decisions from 1 and 2, documented in `docs/vlm_category_boundary_analysis.md`.
4. **The output-format changes** already supported by Stages 4–6: one JSON object; strict schema where
   available; the first-object parser option; the status/text contradiction warning.
