"""Stage 6 (Phase 5), Part 1: locally recover the 6 known NVIDIA V2 answers that end with one stray '}' (no API calls).

Run: uv run python src/recover_vlm_json.py

Only the 6 image IDs below are considered. Each raw file must match the frozen Stage 4 checksum, contain one complete
JSON object followed by exactly one '}' (optionally after whitespace), and the text without that single brace must
pass the EXISTING strict validator (run_vlm.parse_and_validate) unchanged. Raw files are never modified.

Writes: data/processed/vlm_recovered_observations.jsonl (separate from vlm_observations.jsonl)
        data/processed/vlm_recovery_report.json
"""
import hashlib
import json
from pathlib import Path

from run_vlm import RAW, parse_and_validate

CANDIDATES = ["1391393364587653", "2653450758168746", "463348118303970", "524573645227846", "748701757218369",
              "932582530826779"]
NOT_RECOVERABLE = ["386064122572974", "3071421596475336"]  # genuine malformed output: never recovered
MANIFEST = Path("data/processed/vlm_stage4_raw_sha256.json")
OUT = Path("data/processed/vlm_recovered_observations.jsonl")
REPORT = Path("data/processed/vlm_recovery_report.json")
METHOD = "remove_one_trailing_stray_brace"


def recover_text(text):
    """Return (recovered_text, reason) or (None, reason). Only removes one trailing '}' after a complete object."""
    start = (text or "").find("{")
    if start < 0:
        return None, "no JSON object"
    try:
        _, end = json.JSONDecoder().raw_decode(text, start)
    except json.JSONDecodeError as e:
        return None, f"no complete JSON object ({e.msg})"
    trailing = text[end:]
    if trailing.strip() != "}":
        return None, f"trailing text is not exactly one '}}': {trailing[:40]!r}"
    recovered = text[:end] + trailing[:trailing.rindex("}")] + trailing[trailing.rindex("}") + 1:]
    assert len(recovered) == len(text) - 1 and recovered.strip() == text[:end].strip(), "only one character removed"
    return recovered, "complete JSON object followed by exactly one stray '}'"


def main():
    manifest = json.loads(MANIFEST.read_text())["sha256"]
    records, report = [], []
    for image_id in CANDIDATES:
        p = RAW / f"{image_id}__b1-prompt-v2.json"
        entry = {"image_id": image_id, "raw_response_path": str(p)}
        digest = hashlib.sha256(p.read_bytes()).hexdigest()
        if manifest.get(str(p)) != digest:
            report.append({**entry, "recovered": False, "reason": "raw file does not match frozen Stage 4 checksum"})
            continue
        rec = json.loads(p.read_text())
        text = rec["raw_response"]["choices"][0]["message"].get("content")
        recovered, reason = recover_text(text)
        parsed, errors, warnings = parse_and_validate(recovered) if recovered else (None, [reason], [])
        ok = recovered is not None and not errors
        report.append({**entry, "raw_sha256": digest, "recovered": ok, "reason": reason,
                       "original_validation_errors": rec["validation"]["errors"],
                       "validation_after_recovery": {"errors": errors, "warnings": warnings}})
        if not ok:
            continue
        for o in parsed["observations"]:
            records.append({
                "image_id": image_id, "local_image_path": rec["local_image_path"], "category": o["category"],
                "status": o["status"], "observation": o["observation"].strip(), "confidence": float(o["confidence"]),
                "confidence_is_uncalibrated": True, "model": rec["model"], "model_version": rec["model_version"],
                "inference_timestamp": rec["inference_timestamp"], "schema_version": rec["schema_version"],
                "prompt_version": rec["prompt_version"], "source": "NVIDIA hosted VLM", "raw_response_path": str(p),
                "image_usable": parsed.get("image_quality", {}).get("usable"),
                "validation_warnings": [w for w in warnings if w.startswith(o["category"] + ":")],
                "recovery_method": METHOD, "recovered_from_sha256": digest})
    OUT.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records))
    summary = {"candidate_count": len(CANDIDATES), "recovered_count": sum(r["recovered"] for r in report),
               "rejected_count": sum(not r["recovered"] for r in report), "recovery_method": METHOD,
               "not_attempted_genuine_failures": NOT_RECOVERABLE, "candidates": report}
    REPORT.write_text(json.dumps(summary, indent=1, ensure_ascii=False))
    for r in report:
        print(f"{r['image_id']:>18} recovered={r['recovered']!s:5} {r['reason']}"
              f"{'' if r['recovered'] else ' | ' + str(r.get('validation_after_recovery'))}")
    print(f"\nRecovered {summary['recovered_count']}/{len(CANDIDATES)}; {len(records)} observations -> {OUT}; "
          f"report -> {REPORT}\nNot attempted (genuine failures): {NOT_RECOVERABLE}")


if __name__ == "__main__":
    main()
