"""Give groups of photos a realistic capture year and month.

Updates capture_year and capture_month in data/photos.json.
A fixed random seed makes every run write the same dates.
Years stay inside the made-up date range (January 2019 through August 2026).

Rules, in order:
  1. Goa beaches: two trips, each trip one month in October–March.
  2. A folder listed in FOLDER_CAPTURE_DATES shares that one month.
     bali is November 2025. Birthday photos are January 2026.
  3. Every other photo is placed in small groups, a few photos to a month,
     so the gallery is not a row of months with only one photo.
     Those months skip the Goa trips and the folder dates above.

Photos changed here get date_source "assigned".
"""

import json
import random
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import config

PHOTOS_PATH = config.DATA_DIR / "photos.json"
RANDOM_SEED = 20190826
GOA_MONTHS = (10, 11, 12, 1, 2, 3)

GROUP_ORDER = (
    "Goa half 1",
    "Goa half 2",
    "Bali",
    "Birthday",
    "everyday",
)

# How many everyday photos share a month. The last group may be a little larger
# so a month is never left with one photo.
EVERYDAY_GROUP_SIZE = 3


def year_month(text):
    year_text, month_text = text.split("-", 1)
    return int(year_text), int(month_text)


def months_between(start, end):
    """Every (year, month) from start through end, including both."""
    year, month = start
    months = []
    while (year, month) <= end:
        months.append((year, month))
        month += 1
        if month == 13:
            year += 1
            month = 1
    return months


def name_sort_key(path):
    """Sort file names so beach2 comes before beach10."""
    name = Path(path).name.casefold()
    key = []
    for piece in re.split(r"(\d+)", name):
        if piece.isdigit():
            key.append((0, int(piece)))
        else:
            key.append((1, piece))
    return key


def parent_folder(path):
    parent = Path(path).parent.as_posix()
    return "" if parent == "." else parent


def is_goa(path):
    return parent_folder(path) == "beach" and Path(path).name.startswith("goa_beaches")


def is_other_beach(path):
    return parent_folder(path) == "beach" and not is_goa(path)


def folder_capture_date(path):
    """The shared month for a whole folder, or None when the folder is not fixed."""
    pair = config.FOLDER_CAPTURE_DATES.get(parent_folder(path))
    if pair is None:
        return None
    return (int(pair[0]), int(pair[1]))


def reserved_months():
    """Months held for a whole folder, such as the Bali trip."""
    return {tuple(pair) for pair in config.FOLDER_CAPTURE_DATES.values()}


def split_in_half(items):
    """First half, then second half. An odd extra photo stays in the first half."""
    mid = (len(items) + 1) // 2
    return items[:mid], items[mid:]


def pick_goa_trips(rng, pool):
    """Two Goa-season months that differ in both year and month."""
    season = [pair for pair in pool if pair[1] in GOA_MONTHS]
    if len(season) < 2:
        raise SystemExit("Not enough Goa-season months in the date range.")
    options = list(season)
    rng.shuffle(options)
    first = options[0]
    for second in options[1:]:
        if second[0] != first[0] and second[1] != first[1]:
            return first, second
    raise SystemExit("Could not pick two different Goa trip dates.")


def groups_of_several(items, size):
    """Split photos into groups of about `size`. No group is a single photo."""
    if not items:
        return []
    if len(items) == 1:
        return [list(items)]
    groups = []
    index = 0
    while index < len(items):
        remaining = len(items) - index
        if remaining <= size + 1:
            groups.append(list(items[index:]))
            break
        groups.append(list(items[index : index + size]))
        index += size
    if len(groups) >= 2 and len(groups[-1]) == 1:
        groups[-2].extend(groups.pop())
    return groups


def spread_months(count, pool):
    """`count` different months, spaced across the whole range."""
    if count == 0:
        return []
    if count > len(pool):
        raise SystemExit("Not enough free months to fill the gallery.")
    if count == 1:
        return [pool[len(pool) // 2]]
    step = (len(pool) - 1) / (count - 1)
    chosen = []
    used = set()
    for slot in range(count):
        index = int(round(slot * step))
        while index in used:
            index += 1
        if index >= len(pool):
            raise SystemExit("Could not space the months across the date range.")
        used.add(index)
        chosen.append(pool[index])
    return chosen


def set_date(record, year_month_pair, group, groups):
    year, month = year_month_pair
    record["capture_year"] = year
    record["capture_month"] = month
    record["date_source"] = "assigned"
    groups[record["path"]] = group


def check_rules(records, groups, before, start, end):
    """Stop if a written date breaks a rule or an untouched photo changed."""
    by_group = {label: [] for label in GROUP_ORDER}
    for record in records:
        path = record["path"]
        label = groups.get(path)
        if label is None:
            current = (
                record.get("capture_year"),
                record.get("capture_month"),
                record.get("date_source"),
            )
            if current != before[path]:
                raise SystemExit(f"Date changed outside the rules: {path}")
            continue
        if record.get("date_source") != "assigned":
            raise SystemExit(f"{path} was changed but date_source is not assigned.")
        pair = (record["capture_year"], record["capture_month"])
        if not (start <= pair <= end):
            raise SystemExit(f"{path} is outside {start}–{end}: {pair}")
        by_group[label].append(record)

    for label in ("Goa half 1", "Goa half 2"):
        pairs = {(record["capture_year"], record["capture_month"]) for record in by_group[label]}
        if len(by_group[label]) == 0:
            raise SystemExit(f"{label} has no photos.")
        if len(pairs) != 1:
            raise SystemExit(f"{label} does not share one date.")
        _, month = next(iter(pairs))
        if month not in GOA_MONTHS:
            raise SystemExit(f"{label} is not in the Goa season.")
    first = (
        by_group["Goa half 1"][0]["capture_year"],
        by_group["Goa half 1"][0]["capture_month"],
    )
    second = (
        by_group["Goa half 2"][0]["capture_year"],
        by_group["Goa half 2"][0]["capture_month"],
    )
    if first[0] == second[0] or first[1] == second[1]:
        raise SystemExit("The two Goa trips must differ in both year and month.")

    held = reserved_months()
    for folder, pair in config.FOLDER_CAPTURE_DATES.items():
        pair = (int(pair[0]), int(pair[1]))
        label = "Bali" if folder == "bali" else "Birthday"
        rows = by_group[label]
        if not rows:
            continue
        found = {(record["capture_year"], record["capture_month"]) for record in rows}
        if found != {pair}:
            raise SystemExit(f"{folder} photos are not all in {pair[0]}-{pair[1]:02d}.")

    everyday = by_group["everyday"]
    everyday_counts = {}
    for record in everyday:
        pair = (record["capture_year"], record["capture_month"])
        if pair in held or pair in (first, second):
            raise SystemExit(f"{record['path']} landed on a trip or party month.")
        everyday_counts[pair] = everyday_counts.get(pair, 0) + 1
    for pair, count in everyday_counts.items():
        if count < 2:
            raise SystemExit(f"{pair[0]}-{pair[1]:02d} has only one photo.")


def load_records():
    if not PHOTOS_PATH.exists():
        raise SystemExit(f"No photo records at {PHOTOS_PATH}. Run analyze_photos.py first.")
    with PHOTOS_PATH.open() as handle:
        records = json.load(handle)
    if not isinstance(records, list):
        raise SystemExit(f"{PHOTOS_PATH.name} must be a JSON list of photo records.")
    return records


def save_records(records):
    PHOTOS_PATH.parent.mkdir(parents=True, exist_ok=True)
    ordered = sorted(records, key=lambda record: record["id"])
    temporary = PHOTOS_PATH.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(ordered, indent=2, ensure_ascii=False) + "\n")
    temporary.replace(PHOTOS_PATH)


def print_groups(records, groups):
    by_path = {record["path"]: record for record in records}
    for title in GROUP_ORDER:
        paths = [path for path, label in groups.items() if label == title]
        paths.sort(key=name_sort_key)
        print(f"\n{title}")
        print(f"{'path':<42} {'capture_year':>13} {'capture_month':>14}  date_source")
        if not paths:
            print("(none)")
            continue
        for path in paths:
            record = by_path[path]
            print(
                f"{record['path']:<42} {record['capture_year']:>13} "
                f"{record['capture_month']:>14}  {record['date_source']}"
            )


def main():
    records = load_records()
    before = {
        record["path"]: (
            record.get("capture_year"),
            record.get("capture_month"),
            record.get("date_source"),
        )
        for record in records
    }
    start = year_month(config.MADE_UP_DATE_RANGE[0])
    end = year_month(config.MADE_UP_DATE_RANGE[1])
    pool = months_between(start, end)
    if not pool:
        raise SystemExit("The date range does not contain any months.")

    rng = random.Random(RANDOM_SEED)
    groups = {}
    held = reserved_months()

    goa = sorted(
        (record for record in records if is_goa(record["path"])),
        key=lambda record: name_sort_key(record["path"]),
    )
    first_half, second_half = split_in_half(goa)
    trip_one, trip_two = pick_goa_trips(rng, [pair for pair in pool if pair not in held])
    for record in first_half:
        set_date(record, trip_one, "Goa half 1", groups)
    for record in second_half:
        set_date(record, trip_two, "Goa half 2", groups)

    folder_labels = {
        "bali": "Bali",
        "Birthday photos": "Birthday",
    }
    for record in records:
        fixed = folder_capture_date(record["path"])
        if fixed is None:
            continue
        set_date(record, fixed, folder_labels[parent_folder(record["path"])], groups)

    taken = held | {trip_one, trip_two}
    free_months = [pair for pair in pool if pair not in taken]
    everyday = [
        record
        for record in records
        if record["path"] not in groups
    ]
    by_folder = {}
    for record in everyday:
        by_folder.setdefault(parent_folder(record["path"]), []).append(record)
    chunks = []
    singles = []
    for folder in sorted(by_folder):
        folder_records = sorted(by_folder[folder], key=lambda record: name_sort_key(record["path"]))
        if len(folder_records) == 1:
            singles.extend(folder_records)
            continue
        chunks.extend(groups_of_several(folder_records, EVERYDAY_GROUP_SIZE))
    if singles:
        if not chunks:
            chunks.append(singles)
        else:
            chunks[0].extend(singles)
    rng.shuffle(chunks)
    months = spread_months(len(chunks), free_months)
    for chunk, date in zip(chunks, months):
        for record in chunk:
            set_date(record, date, "everyday", groups)

    check_rules(records, groups, before, start, end)
    save_records(records)
    print(f"Updated {len(groups)} photos in {PHOTOS_PATH.name} (seed {RANDOM_SEED}).")
    print_groups(records, groups)


if __name__ == "__main__":
    main()
