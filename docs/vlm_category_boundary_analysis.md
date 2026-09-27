# VLM category-boundary analysis (Phase 5, Stage 6)

**Status: human labels pending.** As of this writing, 0 of 432 NVIDIA review observations and 0 of 80 Groq
review observations carry a human label. This document therefore records:
- **(a)** what the models *claim*, from their own text
- **(b)** the boundary questions the human review must answer

It states **no human-supported finding yet**. Regenerate the evidence with
`uv run python src/analyze_manual_review.py`. Its "boundary group" table fills in with human labels as they
are entered. No ontology change is made here.

Evidence base: the 27-image NVIDIA V2 review set (21 valid images plus 6 locally recovered, 432
observations) and the 5-image Groq comparison. The boundary groups are keyword groupings of *visible* model
statements. If a statement mentions several objects, only the first keyword group matched is counted.

## cycling_infrastructure

| Model statement group (NVIDIA, visible) | n |
|---|---|
| bicycle rack / bicycle parking | 6 |
| cycle lane / track / marking | 1 |

- The V2 definition puts bicycle racks under street_furniture. Both NVIDIA and Groq nevertheless report
  racks as cycling_infrastructure (for example 709179964757083 in both).
- **Questions for the human review:** When a rack is visible, is a `cycling_infrastructure: visible` rack
  statement judged correct under the *current* definition? Or should the reviewer note that the definition
  itself is questionable? Keep separate: bicycle racks, parked bicycles without a rack, cycle
  lanes/tracks/markings, and bicycles being ridden (those belong under cyclists).
- Known from the invalid Stage 4 image 2653450758168746: a red cycle lane with a bicycle symbol is
  visible, but that response is recovered and not yet reviewed.

## street_furniture

| Model statement group (NVIDIA, visible) | n |
|---|---|
| bicycle rack | 5 |
| bin | 5 |
| bench | 3 |
| bollard | 3 |
| sign / advertising | 2 |
| fence / railing | 2 |

- Statements also mention light or signal poles, a wall, a gate and a parked bicycle, but those are counted
  under the first matching group. Groq additionally files a railing (478782403204273) and an information
  sign (399936865459221) under street_furniture.
- **Questions:** Which of benches, bins, bollards, signs, poles, railings, fences, bicycle racks and
  advertising columns does the reviewer accept as street furniture? Should objects counted under two
  categories (a fence under street_furniture and barriers) be labelled once or twice? Record the rationale
  in `manual_note`.

## barriers

| Model statement group (NVIDIA, visible) | n |
|---|---|
| fence | 4 |
| railing / guardrail | 2 |
| other | 2 |

- The same fence is also listed under street_furniture in 4 Stage 4 images.
- **Questions:** Separate fences, railings and guardrails, bollards, and gates. Is a building fence a
  street barrier?

## curb

| Model statement group (NVIDIA, visible) | n |
|---|---|
| raised curb | 16 |
| other edge | 7 |
| cobblestone | 2 |

- NVIDIA reports curb as `visible` in 20 of 21 valid images. Groq reports it in 5 of 5.
- Stage 2 and Stage 4 spot checks by the assistant (not human labels) found a curb claimed on a shared
  cobblestone surface (379860519858209), and cobblestone drainage gutters read as tram tracks
  (904858026737408).
- **Questions:** Separate a raised curb, a flush pavement edge, a drainage gutter or cobblestone strip,
  and a road/sidewalk transition without a raised edge.

## lighting

| Model statement group (NVIDIA, visible) | n |
|---|---|
| lamp on pole / lamp post | 4 |
| other (for example corridor ceiling spotlights) | 2 |

- 1 Stage 4 statement mentions daylight (status not_visible). NVIDIA and Groq differ on 2 of the 5
  comparison images (façade lamp, background lamp posts).
- **Questions:** Separate a lamp fixture, a pole without a visible fixture, a façade-mounted lamp, an
  overhead or wire-hung lamp, a traffic signal, and daylight or indoor light.

## public_transport

| Model statement group (NVIDIA, visible) | n |
|---|---|
| tram / tracks / overhead wires | 4 |
| bus | 1 |

- Tram tracks on Bautzner Straße and Rothenburger Straße (508680623658739) were confirmed by the
  assistant's Stage 4 spot check. The gutter case (904858026737408) was not.
- Groq reports overhead tram or trolleybus wires on 478782403204273, where NVIDIA reports nothing.
- **Questions:** Separate tram tracks, overhead wires, stops and platforms, transit vehicles, and ordinary
  road vehicles.

## Human-supported findings

*None yet. This section is to be written from `analyze_manual_review.py` output once labels exist.*

## Stage 7 update

Human labels at the time of the Stage 7 check: **0** (reviewer 1: 0 of 432; reviewer 2: 0 of 24). **No
human-supported boundary finding can be added yet.** The sections above remain model-statement evidence and
open questions only. Once labels are merged, run:

```bash
uv run python src/analyze_manual_review.py --batch recovered   # the first batch: the 6 recovered images
uv run python src/analyze_inter_reviewer.py                    # whether humans apply the definitions consistently
```

Add findings here only when they are supported by labels, and give the label counts behind each one.
