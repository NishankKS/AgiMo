"""Stage 5 (Phase 5), Part A: diagnose invalid NVIDIA V2 responses from the stored raw files (no API calls).

Run: uv run python src/diagnose_vlm_invalid.py
Writes: data/processed/vlm_invalid_diagnosis.json. Raw files and the production validator are not modified.

locally_recoverable = the response contains one complete JSON object that passes the existing strict validator
unchanged, and the only extra text is formatting (whitespace, stray closing braces). Nothing is rewritten.
"""
import json
import re
from pathlib import Path

from run_vlm import RAW, parse_and_validate

OUT = Path("data/processed/vlm_invalid_diagnosis.json")
PV = "b1-prompt-v2"


def diagnose(text):
    """Classify one model output. Returns dict (no side effects)."""
    text = text or ""
    d = {"length": len(text), "has_markdown_fence": "```" in text, "has_think_tag": "<think>" in text or "</think>" in text,
         "has_unk_tokens": text.count("<unk>"), "leading_text": text[:text.find("{")].strip() if "{" in text else text.strip()}
    start = text.find("{")
    try:
        obj, end = json.JSONDecoder().raw_decode(text, start) if start >= 0 else (None, 0)
    except json.JSONDecodeError as e:
        return {**d, "class": "malformed/truncated/garbage answer", "locally_recoverable": False,
                "reason": f"no complete JSON object: {e.msg} at char {e.pos}"}
    trailing = text[end:]
    _, errors, warnings = parse_and_validate(json.dumps(obj))
    d.update(trailing_text=trailing, first_object_validation_errors=errors)
    if errors:
        return {**d, "class": "schema mismatch", "locally_recoverable": False,
                "reason": f"first JSON object fails the schema: {errors}"}
    if re.fullmatch(r"[\s}]*", trailing):
        return {**d, "class": "other parser/formatting problem", "locally_recoverable": True,
                "reason": f"complete valid JSON object followed by {trailing.count('}')} stray '}}'; the production "
                          "extractor takes first '{' to last '}', so json.loads sees 'Extra data'"}
    return {**d, "class": "other parser/formatting problem", "locally_recoverable": False,
            "reason": f"complete JSON object followed by non-formatting text: {trailing[:60]!r}"}


def main():
    results = []
    for p in sorted(RAW.glob(f"*__{PV}.json")):
        rec = json.loads(p.read_text())
        if not rec["validation"]["errors"]:
            continue
        msg = rec["raw_response"]["choices"][0]["message"]
        r = diagnose(msg.get("content"))
        results.append({"image_id": rec["image_id"], "raw_response_path": str(p),
                        "finish_reason": rec["raw_response"]["choices"][0].get("finish_reason"),
                        "completion_tokens": (rec["raw_response"].get("usage") or {}).get("completion_tokens"),
                        "stored_validation_errors": rec["validation"]["errors"], **r})
    OUT.write_text(json.dumps(results, indent=1, ensure_ascii=False))
    for r in results:
        print(f"{r['image_id']:>18}  {r['class']:36} recoverable={r['locally_recoverable']!s:5}  "
              f"finish={r['finish_reason']} tokens={r['completion_tokens']} fence={r['has_markdown_fence']} "
              f"think={r['has_think_tag']} unk={r['has_unk_tokens']}\n{'':20}{r['reason']}")
    n = sum(r["locally_recoverable"] for r in results)
    print(f"\nInvalid V2 responses: {len(results)}; locally recoverable: {n}; not recoverable: {len(results) - n}")
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()
