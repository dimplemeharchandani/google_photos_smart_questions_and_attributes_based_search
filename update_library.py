"""Refresh the photo library in one step.

Runs analyze_photos.py, then add_everyday_words.py, then
add_clothing_colours.py, then add_main_subject.py, then build_embeddings.py.
Use this after adding photos so descriptions, everyday words, clothing
colours, main subjects, and embeddings stay in step.

A photo whose date_source is "assigned" keeps that capture year and month.
If a step replaces one of those dates, this script puts it back.
"""

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import config

STEPS = (
    "analyze_photos.py",
    "add_everyday_words.py",
    "add_clothing_colours.py",
    "add_main_subject.py",
    "build_embeddings.py",
)

PHOTOS_PATH = config.DATA_DIR / "photos.json"


def assigned_capture_dates(path):
    """Map photo path to (year, month) for dates that must be kept."""
    if not path.exists():
        return {}
    with path.open() as handle:
        records = json.load(handle)
    kept = {}
    if not isinstance(records, list):
        return kept
    for record in records:
        if not isinstance(record, dict) or record.get("date_source") != "assigned":
            continue
        photo_path = record.get("path")
        if isinstance(photo_path, str):
            kept[photo_path] = (record.get("capture_year"), record.get("capture_month"))
    return kept


def restore_assigned_capture_dates(path, assigned):
    """Put assigned dates back. Other fields stay as the last step left them."""
    if not assigned or not path.exists():
        return
    with path.open() as handle:
        records = json.load(handle)
    if not isinstance(records, list):
        return
    changed = False
    for record in records:
        if not isinstance(record, dict):
            continue
        photo_path = record.get("path")
        if photo_path not in assigned:
            continue
        year, month = assigned[photo_path]
        if (
            record.get("capture_year") == year
            and record.get("capture_month") == month
            and record.get("date_source") == "assigned"
        ):
            continue
        record["capture_year"] = year
        record["capture_month"] = month
        record["date_source"] = "assigned"
        changed = True
    if not changed:
        return
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(records, indent=2, ensure_ascii=False) + "\n")
    temporary.replace(path)
    print("Restored assigned capture dates.", flush=True)


def main():
    assigned = assigned_capture_dates(PHOTOS_PATH)
    try:
        for name in STEPS:
            script = ROOT / name
            print(f"\n=== {name} ===", flush=True)
            result = subprocess.run([sys.executable, str(script)], cwd=ROOT)
            if result.returncode != 0:
                raise SystemExit(f"{name} failed with exit code {result.returncode}.")
    finally:
        restore_assigned_capture_dates(PHOTOS_PATH, assigned)
    print("\nLibrary update finished.", flush=True)


if __name__ == "__main__":
    main()
