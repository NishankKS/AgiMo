# VLM prompt comparison: b1-prompt-v1 vs b1-prompt-v2 (Phase 5, Stage 2)

This is a controlled comparison: the same 3 perspective Mapillary images, the same model and settings,
and the same schema (`b1-visual-obs-v1`, 16 categories). Only the prompt differs.
Regenerate the tables with `uv run python src/compare_vlm.py`.

- Model: `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning` via `https://integrate.api.nvidia.com/v1/chat/completions`.
  The API reports no model version.
- Settings: `enable_thinking=false`, `temperature 1.0`, `top_k 1`, `max_tokens 2048`.
- Images: `1514293340184582` (Bautzner Straße, 2026), `2302498470581445` (Alaunstraße, 2026),
  `379860519858209` (Julie-Salinger-Weg, 2018).
- Raw records: `data/raw/vlm/<id>__b1-prompt-v1.json` and `…__b1-prompt-v2.json`. Normalized observations for
  both versions are in `data/processed/vlm_observations.jsonl` (field `prompt_version`).

Three images are too few for an accuracy figure. Below are the concrete changes, checked by looking at the
images. Automated keyword flags only help that review; they do not score anything.

## Summary

| | v1 | v2 |
|---|---|---|
| Valid, complete JSON | 3/3 | 3/3 |
| Duplicate / unknown categories | 0 / 0 | 0 / 0 |
| Normative wording / absence claims | 0 / 0 | 0 / 0 |
| Status visible / not_visible / uncertain | 26 / 21 / 1 | 26 / 22 / 0 |
| Confidence (uncalibrated) | 0.6–1.0; 44/48 ≥ 0.9; 12 at 1.0 | 0.9–0.99; 48/48 ≥ 0.9; 0 at 1.0 |
| Prompt tokens per image | 916–1,236 | 1,484–1,804 |
| Completion tokens per image | 702–745 | 714–745 |
| API: calls / retries / 429 / 503 | 7 calls: 3 kept, 2 re-run after a provenance bug of mine, 2 × 503 (not recorded per call) | 3 / 0 / 0 / 0 |
| Latency per call | not recorded | 12.3–16.9 s |

## Targeted v1 problems

| Problem (v1) | v2 result | Checked against the image |
|---|---|---|
| Tram called an "articulated bus" (Bautzner) | "A yellow tram is visible…" | **Fixed.** It is a tram. |
| `lighting` described daylight and shadows (Bautzner) | `not_visible`: "No physical street-lighting fixtures are visible." | **Fixed the category misuse.** Tall poles are visible, but no lamp head can be identified at this resolution, so `not_visible` is defensible. |
| Overhead lamps on wires missed (Alaunstraße) | `visible`: "Street lamps are mounted on poles and attached to buildings along the street." | **Partly.** The status is now correct, but the description is inaccurate: the main lamps hang from wires across the street, and "on poles" is not visible. |
| Capture bicycle handlebars reported as `cycling_infrastructure` and `cyclists` (Alaunstraße) | Both `not_visible` | **Fixed.** |
| Curb claimed on a shared cobblestone surface (Julie-Salinger-Weg) | `visible` 0.9: "A raised curb is visible along the edge of the sidewalk on the left." | **Not fixed.** The left strip is different paving; a raised edge is not evident. The model did not use `uncertain` even though the prompt asks for it. |

## Other changes, and new issues in v2

- **Street furniture (Bautzner):** changed from `not_visible` to `visible` with "benches … and a trash bin".
  There are small dark objects on the left sidewalk, which could be a bench or bicycles. Cannot be
  confirmed at 1024 px.
- **Street furniture and barriers (Alaunstraße):** both changed to `visible`, and both cite the same
  metal fence on the right. The fence is real, but it is counted twice even though the prompt asks not
  to. The "bicycle rack near a parked car on the left" is not evident; there is a parked scooter.
- **Sidewalk (Alaunstraße):** v2 reports a sidewalk on the right side only. The left sidewalk is visible,
  so v1's "both sides" was more complete. This is a regression.
- **Signage (Julie-Salinger-Weg):** v2 adds a yellow vertical sign. Correct, although it is a
  commercial sign.
- **Signage (Bautzner):** changed from `uncertain` to `not_visible`. Traffic lights are visible but are
  not signs; this is consistent with the definition.
- **Pedestrians (Julie-Salinger-Weg):** v2 says the person is "pushing a bicycle", which is more precise
  and correct.
- **Wording of `not_visible`:** v2 says "No X are visible", not the requested "No X can be determined from
  this view". Neither version claims absence.
- **`uncertain` has disappeared:** 0 uses in v2. Uncertain cases such as the curb are reported as
  `visible`.

## Confidence

Confidence is model-reported and **uncalibrated** (`confidence_is_uncalibrated: true` on every normalized
observation). In v2 every value is between 0.9 and 0.99, including observations that the image review
found wrong or doubtful: 0.90 for the curb, 0.94 for the bicycle rack, 0.95 for "lamps on poles". It
must not be used to rank images or streets, or for quantitative B1 conclusions. It is kept only for
provenance and for possible later calibration against manual labels.

## Conclusion

v2 fixed the three category-semantics problems it targeted: the tram, lighting-as-daylight, and the
capture bicycle. It did not fix the curb over-claim, and it introduced some new unverified or
double-counted claims, plus one completeness regression (the left sidewalk). The output is still a set
of per-image candidate observations that need review. It is not ground truth.
