"""Merge HUMAN labels (CSV downloaded from a review page, or any CSV with image_id, category, manual_label,
manual_note) into a review file. Only the label/note columns change; VLM fields are never touched.

Run: uv run python src/merge_manual_labels.py --input manual_labels_nvidia.csv [--target nvidia|second] [--dry-run]
     [--overwrite]

Rules (idempotent, non-destructive):
- empty label in the input  -> no change to the label (an exported page lists every row, labelled or not)
- existing empty label      -> set label (+ note)
- existing identical label  -> no change (note filled in only if the existing note is empty)
- existing different label  -> CONFLICT: skipped and reported, unless --overwrite is given
- a note alone never creates a label
Targets: nvidia = reviewer 1 (manual_label/manual_note in the main review file);
         second = reviewer 2 (reviewer2_label/reviewer2_note in the second-reviewer sample).
"""
import argparse
import csv
from pathlib import Path

LABELS = {"correct", "incorrect", "uncertain", ""}
TARGETS = {"nvidia": (Path("data/processed/vlm_quality_review_observations.csv"), "manual_label", "manual_note"),
           "second": (Path("data/processed/manual_review_second_reviewer_sample.csv"), "reviewer2_label",
                      "reviewer2_note")}


def merge(review_rows, label_rows, overwrite=False, cols=("manual_label", "manual_note")):
    """Return (new_rows, changes, errors, conflicts). Pure: validates all input before changing anything."""
    lab_col, note_col = cols
    keys = {(r["image_id"], r["category"]): n for n, r in enumerate(review_rows)}
    errors, updates = [], {}
    for n, r in enumerate(label_rows, 2):
        k = (r.get("image_id", "").strip(), r.get("category", "").strip())
        label = (r.get("manual_label") or "").strip().lower()
        if k not in keys:
            errors.append(f"line {n}: {k} not in review file")
        elif label not in LABELS:
            errors.append(f"line {n}: invalid label {r.get('manual_label')!r} (allowed: correct, incorrect, uncertain, empty)")
        else:
            updates[k] = (label, (r.get("manual_note") or "").strip())
    if errors:
        return review_rows, [], errors, []
    new, changes, conflicts = [dict(r) for r in review_rows], [], []
    for k, (label, note) in updates.items():
        row = new[keys[k]]
        old_label, old_note = row[lab_col], row[note_col]
        if not label:  # empty label never clears or creates a label
            continue
        if old_label and old_label != label and not overwrite:
            conflicts.append((k, old_label, label))
            continue
        new_note = note if (old_label != label or not old_note or overwrite) else old_note
        if (old_label, old_note) != (label, new_note):
            changes.append((k, old_label, label))
            row[lab_col], row[note_col] = label, new_note
    return new, changes, [], conflicts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", "--labels", dest="input", type=Path, required=True)
    ap.add_argument("--target", choices=sorted(TARGETS), default="nvidia")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--overwrite", action="store_true", help="replace existing different labels (explicit only)")
    a = ap.parse_args()
    path, lab_col, note_col = TARGETS[a.target]
    rows = list(csv.DictReader(path.open()))
    fields = list(rows[0])
    new, changes, errors, conflicts = merge(rows, list(csv.DictReader(a.input.open())), a.overwrite,
                                            (lab_col, note_col))
    if errors:
        raise SystemExit("Nothing merged:\n  " + "\n  ".join(errors))
    for (i, c), old, lab in changes:
        print(f"  {i} {c}: {old or '(unreviewed)'} -> {lab}")
    for (i, c), old, lab in conflicts:
        print(f"  CONFLICT (kept existing) {i} {c}: existing {old!r}, input {lab!r}; use --overwrite to replace")
    if not a.dry_run and changes:
        with path.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            w.writerows(new)
    print(f"{len(changes)} label changes, {len(conflicts)} conflicts "
          f"{'(dry run, not written)' if a.dry_run else ('written to ' + str(path) if changes else '(nothing to write)')}")


if __name__ == "__main__":
    main()
