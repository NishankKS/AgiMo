# VLM prompt V3: design preparation only (Phase 5, Stage 6)

**V3 is not created and not run.** `b1-prompt-v2` stays the production prompt. Each proposal below has an
evidence status:

- **supported:** shown by structural or diagnostic evidence from Stages 4–5 (no human labels needed)
- **pending:** a semantic hypothesis that needs the Stage 6 human labels before it is adopted

The meaning of `not_visible` ("insufficient visual evidence in this image", **not** absence) stays
unchanged. Confidence stays uncalibrated (`confidence_is_uncalibrated = true`); V3 does not calibrate it.

## Output-format changes

| Proposal | Evidence | Status |
|---|---|---|
| One JSON object only: no markdown, no text before or after | 6 of 8 invalid NVIDIA answers had one stray `}` after a complete object (Stage 5 diagnosis) | supported |
| Exactly 16 entries, one per category, fixed order | already enforced by the validator; 0 violations among valid answers | supported (keep) |
| Where the API allows it, enforce the schema at the API level (strict `json_schema`) | Groq strict mode: 5 of 5 valid; NVIDIA free-text JSON: 18 of 26 valid in Stage 4 | supported for Groq; NVIDIA structured-output support not yet checked |
| Parser: accept the first complete JSON object and record a warning | recovers 6 of 8 without changing content (Stage 6 recovery) | supported as a *validator* option; a decision is still needed |
| Validator warning for status/text contradiction (for example `visible` + "No … visible") | 1 NVIDIA case (709179964757083, cyclists) | supported as a warning; not a prompt change |

## Evidence rules

| Proposal | Evidence | Status |
|---|---|---|
| Claim only objects visible in the image; never infer typical or hidden infrastructure | V2 already says this; unverified furniture claims recur | pending (size of problem unknown) |
| Lighting = a visible fixture only; daylight is never lighting; a pole without a visible lamp head → `uncertain` | 1 daylight mention in Stage 4; provider disagreements on lamps | pending |
| A parked bicycle is not cycling infrastructure; a bicycle being ridden → cyclists | model statements; 1 hallucinated person with a bicycle (spot check) | pending |
| A drainage gutter or cobblestone strip is not a curb without a visible raised edge; rails need visible rail profiles to count as tram tracks | 904858026737408 spot check; curb visible in 20 of 21 | pending |
| Do not transcribe sign text unless clearly legible | "Treiberegt" for "Freiberger" (spot check) | pending |

## Category-definition changes

Only after the human review shows where the boundary lies. Candidates, all **pending**:
- **Bicycle racks:** street_furniture (V2 definition) or cycling_infrastructure (what both models report). This
  is a research decision about the B1 SDE concept, not a model fix.
- **Fences, railings and bollards:** one category, or both street_furniture and barriers? The rule should
  prevent the same object being counted twice.
- **Signs and advertising columns:** signage vs street_furniture.

No new categories are proposed. Categories are not added because a model made mistakes.

## Ambiguity rules

`uncertain` is almost unused: 1 of 336 in Stage 4, 1 of 96 recovered, 0 of 80 for Groq. The proposal
(**pending**): use `uncertain` when the object type cannot be determined at the image resolution, is
partially occluded, or could belong to a neighbouring category. Keep `visible` for a clear view. Keep
`not_visible` for no sufficient evidence.

## How V3 would be evaluated (later stage)

The same 27 labelled NVIDIA images (and the 5 Groq images) with the same human labels. Report per category
correct, incorrect, uncertain and unreviewed, as for V2. No overall score and no ranking.

## Stage 7 note

No new human evidence yet (0 labels), so no proposal changed status. The provider comparison now uses one
human label per image/category, compared at status level for Groq (`docs/vlm_stage7.md`). The V3 decision
criteria are listed in `docs/vlm_stage7.md` §10.
