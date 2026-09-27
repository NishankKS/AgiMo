"""Checks for run_vlm.py: validator, prompts, cache separation, retry/pacing (no live API calls).

Run: uv run python src/test_run_vlm.py
"""
import io
import json
import tempfile
import urllib.error
from pathlib import Path

import run_vlm as v


def resp(**over):
    obs = [{"category": c, "status": "not_visible", "observation": "not visible", "confidence": 0.5}
           for c in v.CATEGORIES]
    for c, patch in over.items():
        next(o for o in obs if o["category"] == c).update(patch)
    return {"image_quality": {"usable": True, "issues": []}, "observations": obs}


# --- validator -------------------------------------------------------------
ok = json.dumps(resp())
assert len(v.CATEGORIES) == 16 and v.STATUS == {"visible", "not_visible", "uncertain"}
assert v.parse_and_validate(ok)[1] == []
assert v.parse_and_validate("```json\n" + ok + "\n```")[1] == [], "markdown fences are tolerated"
assert v.parse_and_validate("<think>{bad}</think>" + ok)[1] == [], "think block is stripped"
assert v.parse_and_validate("not json")[0] is None
assert "invalid JSON" in str(v.parse_and_validate('{"observations": [}')[1])
assert "invalid confidence 1.5" in str(v.parse_and_validate(json.dumps(resp(roadway={"confidence": 1.5})))[1])
assert "invalid confidence True" in str(v.parse_and_validate(json.dumps(resp(roadway={"confidence": True})))[1])
assert "invalid confidence '0.9'" in str(v.parse_and_validate(json.dumps(resp(roadway={"confidence": "0.9"})))[1])
assert "invalid status" in str(v.parse_and_validate(json.dumps(resp(curb={"status": "absent"})))[1])
r = resp(); r["observations"].pop(0)
assert "missing categories: ['sidewalk']" in str(v.parse_and_validate(json.dumps(r))[1])
r = resp(); r["observations"].append(dict(r["observations"][0]))
assert "duplicate categories" in str(v.parse_and_validate(json.dumps(r))[1])
r = resp(); r["observations"].append({"category": "vibe", "status": "visible", "observation": "x", "confidence": 1})
assert "unknown category" in str(v.parse_and_validate(json.dumps(r))[1])
w = v.parse_and_validate(json.dumps(resp(trees_vegetation={"observation": "a pleasant green street"})))[2]
assert w == ["trees_vegetation: normative wording 'pleasant'"], w
assert "normative wording 'undesirable'" in str(
    v.parse_and_validate(json.dumps(resp(roadway={"observation": "undesirable layout"})))[2])
w = v.parse_and_validate(json.dumps(resp(lighting={"observation": "Street lighting is absent."})))[2]
assert w == ["lighting: absence claim 'absent' for not_visible"], w
assert v.parse_and_validate(json.dumps(resp(lighting={
    "observation": "No physical street-light fixture can be determined from this view."})))[2] == []

# --- prompts ---------------------------------------------------------------
p2 = v.PROMPT_V2
assert all(c in p2 for c in v.CATEGORIES)
assert "IGNORE the image-capture setup" in p2 and "handlebars" in p2
assert "ONLY physical street-lighting fixtures" in p2 and "Daylight" in p2 and "overhead wires" in p2
assert "does NOT mean the element is absent" in p2 and "rail_vehicle" in p2 and "Never call a rail vehicle a bus" in p2
assert "Not inferred\n  from colour or material differences alone" in p2
assert v.PROMPT_V1 != p2 and set(v.PROMPTS) == {"v1", "v2"}

# --- cache separation --------------------------------------------------------
assert v.raw_path("1", "v1") != v.raw_path("1", "v2") and v.raw_path("1", "v2").name == "1__b1-prompt-v2.json"
with tempfile.TemporaryDirectory() as d:
    v.RAW = Path(d)
    v.raw_path("1", "v1").write_text(json.dumps({"validation": {"errors": []}}))
    v.raw_path("2", "v2").write_text(json.dumps({"validation": {"errors": ["missing categories"]}}))
    assert v.has_valid("1", "v1") and not v.has_valid("1", "v2"), "v1 cache does not satisfy v2"
    assert not v.has_valid("2", "v2"), "an invalid response is not a cache hit"


# --- retries / pacing (fake opener, sleep and clock) ------------------------
class Fake:
    def __init__(self, outcomes):
        self.outcomes, self.t, self.slept, self.calls = list(outcomes), 0.0, [], 0

    def clock(self):
        return self.t

    def sleep(self, s):
        self.slept.append(round(s, 2))
        self.t += s

    def opener(self, req, timeout):
        self.calls += 1
        o = self.outcomes.pop(0)
        if isinstance(o, int):
            hdrs = {"Retry-After": self.retry_after} if getattr(self, "retry_after", None) else {}
            raise urllib.error.HTTPError(req.full_url, o, "err", hdrs, io.BytesIO(f"echo {v.KEY}".encode()))
        return io.BytesIO(json.dumps(o).encode())


def run(outcomes, retry_after=None):
    v._last_request[0] = -1e9
    f = Fake(outcomes)
    f.retry_after = retry_after
    try:
        out = v.post({"x": 1}, opener=f.opener, sleep=f.sleep, clock=f.clock)
        return f, out, None
    except v.VLMError as e:
        return f, None, e


f, (body, st), _ = run([429, {"ok": 1}])
assert body == {"ok": 1} and st["attempts"] == 2 and st["retries"] == 1 and st["http_429"] == 1
assert 2 in f.slept, f.slept
f, _, _ = run([503, {"ok": 1}], retry_after="7")
assert 7 in f.slept, "Retry-After respected"
f, _, _ = run([503, {"ok": 1}], retry_after="999")
assert v.MAX_RETRY_AFTER_S in f.slept, "Retry-After capped"
f, _, e = run([503, 503, 503, 503, {"never": 1}])
assert e.kind == "service_overloaded" and e.stats["attempts"] == 4 and e.stats["retries"] == 3
assert e.stats["http_503"] == 4 and f.calls == 4, "bounded: 1 + 3 retries"
assert [s for s in f.slept if s in (2, 5, 10)] == [2, 5, 10], f.slept
for code, kind in ((401, "authentication_failed"), (400, "malformed_request"), (404, "model_or_endpoint_not_found"),
                   (500, "model_or_api_error")):
    f, _, e = run([code, {"ok": 1}])
    assert e.kind == kind and f.calls == 1, f"{code} must not be retried"
    assert v.KEY not in str(e), "key never in error messages"
f = Fake([{"a": 1}, {"b": 2}])
v._last_request[0] = -1e9
v.post({}, opener=f.opener, sleep=f.sleep, clock=f.clock)
v.post({}, opener=f.opener, sleep=f.sleep, clock=f.clock)
assert f.slept == [v.MIN_INTERVAL_S], f"second request paced: {f.slept}"
assert v.KEY not in v.safe(f"x {v.KEY}")
print("run_vlm checks passed")
