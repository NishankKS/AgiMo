"""Checks for import_visual_observations.build() on dummy records (no Neo4j writes, no API calls).

Run: uv run python src/test_import_visual_observations.py
"""
import copy

from import_visual_observations import PROMPT_VERSION, build
from run_vlm import CATEGORIES


def feature(i, linked=True, street=100):
    return {"properties": {"mapillary_id": i, "latitude": 51.06, "longitude": 13.75, "captured_at": "2026-01-01T00:00:00",
                           "source": "Mapillary", "association_status": "linked" if linked else "unlinked_over_30m",
                           "street_id": street if linked else None, "association_method": "nearest_street" if linked else None,
                           "association_distance_m": 4.2 if linked else None}}


def rec(i, cat, pv=PROMPT_VERSION, **over):
    r = {"image_id": i, "category": cat, "status": "visible", "observation": "x", "confidence": 0.9,
         "confidence_is_uncalibrated": True, "model": "m", "model_version": None, "prompt_version": pv,
         "schema_version": "s", "inference_timestamp": "t", "source": "NVIDIA hosted VLM",
         "raw_response_path": "p", "image_usable": True, "validation_warnings": []}
    r.update(over)
    return r


full = [rec("1", c) for c in CATEGORIES]
v1 = [rec("1", c, pv="b1-prompt-v1") for c in CATEGORIES]
F = [feature("1")]

# V2-only filtering; V1 never imported
plan, err, skipped = build(v1 + full, F, {100})
assert err == [] and len(plan["observations"]) == 16 and skipped == {"b1-prompt-v1": 16}
assert all(o["prompt_version"] == PROMPT_VERSION for o in plan["observations"])
assert build(v1, F, {100})[0]["observations"] == [], "only v1 present -> nothing imported"
assert len(plan["images"]) == 1 and plan["located_near"] == [
    {"image_uid": "mapillary/1", "street_uid": "way/100", "method": "nearest_street", "distance_m": 4.2}]
assert plan["observations"][0]["uid"] == f"mapillary/1/{PROMPT_VERSION}/sidewalk", "deterministic id"
assert plan == build(v1 + full, F, {100})[0], "same input -> same plan (idempotent keys)"


def errors(records, features=F, streets=frozenset({100})):
    return " | ".join(build(records, features, streets)[1])


assert "duplicate observation" in errors(full + [rec("1", "roadway")])
assert "duplicate mapillary_id" in errors(full, F + [feature("1")])
assert "missing ['image_id']" in errors([rec(None, "roadway")])
assert "image_id not in" in errors([rec("999", "roadway")])
assert "invalid category 'vibe'" in errors([rec("1", "vibe")])
assert "invalid status 'absent'" in errors([rec("1", "roadway", status="absent")])
assert "invalid confidence 1.2" in errors([rec("1", "roadway", confidence=1.2)])
assert "invalid confidence True" in errors([rec("1", "roadway", confidence=True)])
assert "invalid confidence '0.9'" in errors([rec("1", "roadway", confidence="0.9")])
assert "missing ['model']" in errors([rec("1", "roadway", model="")])
assert "missing ['source']" in errors([rec("1", "roadway", source=None)])
assert "confidence_is_uncalibrated must be true" in errors([rec("1", "roadway", confidence_is_uncalibrated=False)])
r = rec("1", "roadway"); del r["prompt_version"]
assert "missing prompt_version" in errors([r])

# Street association: missing Street is an error; unlinked image gets no LOCATED_NEAR
assert "not in Neo4j" in errors(full, F, set())
plan, err, _ = build([rec("2", c) for c in CATEGORIES], [feature("2", linked=False)], {100})
assert err == [] and len(plan["images"]) == 1 and plan["located_near"] == []

# model_version None is carried as None (not invented)
assert build(full, F, {100})[0]["observations"][0]["model_version"] is None
assert copy.deepcopy(full) == full
print("import_visual_observations checks passed")
