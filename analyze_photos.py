"""Read each photo with Gemini and save a description, labels, and a date."""

import hashlib
import io
import json
import os
import random
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai import types
from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import config
from assign_dates import folder_capture_date

# A few photos are very large. We only shrink them, then send the smaller copy.
Image.MAX_IMAGE_PIXELS = None

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png"}
OUTPUT_PATH = config.DATA_DIR / "photos.json"
MAX_SIDE = 1024
PAUSE_SECONDS = 7
RATE_LIMIT_WAIT_SECONDS = 60
RATE_LIMIT_TRIES = 5
BUSY_WAIT_SECONDS = 30
BUSY_TRIES = 5
EXIF_DATETIME_ORIGINAL = 36867
EXIF_IFD = 0x8769

class DailyQuotaError(Exception):
    """This model's free daily limit is used up."""


def build_prompt():
    """Ask for a description and the allowed attribute values."""
    attribute_lines = []
    for label, values in config.ATTRIBUTES.items():
        choices = ", ".join(f'"{value}"' for value in values)
        if label in config.LIST_ATTRIBUTES:
            attribute_lines.append(f'    "{label}": ["one or more of {choices}"]')
        else:
            attribute_lines.append(f'    "{label}": one of {choices}')
    attributes_shape = "\n".join(attribute_lines)
    return f"""Look at this photo and reply with JSON only. No markdown and no extra words.

Use exactly this shape:
{{
  "description": "a detailed paragraph of 3 to 5 sentences",
  "attributes": {{
{attributes_shape}
  }},
  "everyday_words": ["15 to 25 everyday words and short phrases"]
}}

The description must cover:
- the people, in general words only, such as baby, toddler, girl, young woman, old man, or group of friends. Never guess a person's name.
- their clothing, including colours
- all visible objects and food items
- the place and the background
- what is happening
- the mood
- any readable text
Where a general category fits, use words such as "food", "animal", or "vehicle".

For each attribute that is not a list, choose only one of the allowed values. If you cannot tell, use "unknown".

clothing_colour is a list of the main clothing colours worn by the people. Several people may wear different colours, so include each of those colours. Use ["none"] when there are no people. Use ["unknown"] when you cannot tell the clothing colours. Choose only the allowed colour values.

main_subject is a list of what the photo is mainly of, with at most two values from the allowed list. A photo of a person with a dog can be ["people", "animal"]. Use ["unknown"] when you cannot tell. Choose only the allowed values.

everyday_words is 15 to 25 everyday words and short phrases a person might type when searching for this photo.
Include casual names for clothing, objects, people and places.
For example, a knitted beanie can be called a cap, a woolly hat, a winter hat, or a beanie.
A toddler can be called a kid, a baby, a little boy, or a little girl, whichever the photo shows.
Never include a person's name. Only include words the photo supports.
"""


PROMPT = build_prompt()


def is_daily_quota(error):
    """True when a 429 says the daily free limit is used up."""
    return error_code(error) == 429 and "PerDay" in str(error)


def error_code(error):
    code = getattr(error, "code", None)
    if code in (429, 503):
        return code
    text = str(error)
    if "RESOURCE_EXHAUSTED" in text or "429" in text:
        return 429
    if "UNAVAILABLE" in text or "503" in text:
        return 503
    return code


class RequestPacer:
    """Keep a gap between API calls. The first call does not wait."""

    def __init__(self):
        self._has_sent = False

    def wait_for_next_request(self):
        if self._has_sent:
            time.sleep(PAUSE_SECONDS)
        self._has_sent = True


def generate(client, model_name, image_bytes, prompt, pacer, json_mode):
    """Send one image. Wait out per-minute limits and busy errors, then raise."""
    pacer.wait_for_next_request()
    rate_tries = 0
    busy_tries = 0
    config_kwargs = {
        "temperature": 0.2,
        "automatic_function_calling": types.AutomaticFunctionCallingConfig(disable=True),
    }
    if json_mode:
        config_kwargs["response_mime_type"] = "application/json"
    request = types.GenerateContentConfig(**config_kwargs)
    while True:
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=[
                    types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"),
                    prompt,
                ],
                config=request,
            )
            return (response.text or "").strip()
        except Exception as error:
            if is_daily_quota(error):
                raise DailyQuotaError(str(error)) from error
            code = error_code(error)
            if code == 429 and rate_tries < RATE_LIMIT_TRIES:
                rate_tries += 1
                print(
                    f"Rate limit (429). Waiting {RATE_LIMIT_WAIT_SECONDS} seconds, "
                    f"then trying again ({rate_tries}/{RATE_LIMIT_TRIES}).",
                    flush=True,
                )
                time.sleep(RATE_LIMIT_WAIT_SECONDS)
                continue
            if code == 503 and busy_tries < BUSY_TRIES:
                busy_tries += 1
                print(
                    f"Model busy (503). Waiting {BUSY_WAIT_SECONDS} seconds, "
                    f"then trying again ({busy_tries}/{BUSY_TRIES}).",
                    flush=True,
                )
                time.sleep(BUSY_WAIT_SECONDS)
                continue
            raise


def next_model(quota_used):
    """The next listed model that still has daily quota, or stop the run."""
    for name in config.VISION_MODELS:
        if name not in quota_used:
            return name
    raise SystemExit("Daily free quota used up for all models. Run again tomorrow.")


def image_paths():
    """Every jpg, jpeg, and png under the photos folder, in a stable order."""
    names = []
    for path in config.PHOTOS_DIR.rglob("*"):
        if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS:
            names.append(path.relative_to(config.PHOTOS_DIR).as_posix())
    return sorted(names)


def load_saved():
    if not OUTPUT_PATH.exists():
        return []
    with OUTPUT_PATH.open() as handle:
        saved = json.load(handle)
    if not isinstance(saved, list):
        raise SystemExit(f"{OUTPUT_PATH} must be a JSON list of photo records.")
    return saved


def save_records(records):
    """Write the full list after each photo so a stopped run can continue."""
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    ordered = sorted(records, key=lambda record: record["id"])
    temporary = OUTPUT_PATH.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(ordered, indent=2, ensure_ascii=False) + "\n")
    temporary.replace(OUTPUT_PATH)


def assigned_dates_by_path(records):
    """Capture dates marked assigned. Later saves in this run must keep them."""
    kept = {}
    for record in records:
        if record.get("date_source") != "assigned":
            continue
        path = record.get("path")
        if isinstance(path, str):
            kept[path] = (record.get("capture_year"), record.get("capture_month"))
    return kept


def keep_assigned_dates(records, assigned):
    """Put assigned capture dates back so a new description cannot replace them."""
    for record in records:
        path = record.get("path")
        if path not in assigned:
            continue
        year, month = assigned[path]
        record["capture_year"] = year
        record["capture_month"] = month
        record["date_source"] = "assigned"


def assign_ids(paths, existing_by_path, previous_ids):
    """Keep ids already saved. New photos get the next numbers, in path order."""
    next_id = max(previous_ids, default=0) + 1
    ids = {}
    for path in paths:
        existing = existing_by_path.get(path)
        if existing is not None:
            ids[path] = existing["id"]
            continue
        ids[path] = next_id
        next_id += 1
    return ids


def resized_jpeg(path):
    """Shrink the photo so its longest side is at most 1024 pixels."""
    with Image.open(path) as image:
        image = ImageOps.exif_transpose(image)
        image = image.convert("RGB")
        image.thumbnail((MAX_SIDE, MAX_SIDE), Image.Resampling.LANCZOS)
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=85)
        return buffer.getvalue()


def clean_everyday_words(raw):
    """Keep 15 to 25 unique phrases. Raise when the list is too short."""
    if not isinstance(raw, list):
        raise ValueError("reply JSON had no everyday_words list")
    words = []
    seen = set()
    for item in raw:
        if not isinstance(item, str):
            continue
        phrase = " ".join(item.split())
        if not phrase:
            continue
        key = phrase.casefold()
        if key in seen:
            continue
        seen.add(key)
        words.append(phrase)
    if len(words) < 15:
        raise ValueError(f"everyday_words had {len(words)} items, expected 15 to 25")
    return words[:25]


def parse_reply(text):
    raw = (text or "").strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1]
        if raw.endswith("```"):
            raw = raw[:-3]
        raw = raw.strip()
    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("reply did not contain a JSON object")
    data = json.loads(raw[start : end + 1])
    if not isinstance(data, dict):
        raise ValueError("reply JSON was not an object")
    description = data.get("description")
    attributes = data.get("attributes")
    if not isinstance(description, str) or not description.strip():
        raise ValueError("reply JSON had no description text")
    if not isinstance(attributes, dict):
        raise ValueError("reply JSON had no attributes object")
    return description.strip(), attributes, clean_everyday_words(data.get("everyday_words"))


def clean_choice(value, allowed):
    """Return the allowed spelling, or "unknown" when the value is not allowed."""
    if not isinstance(value, str):
        return "unknown"
    text = value.strip()
    if text in allowed:
        return text
    folded = text.casefold()
    return next((item for item in allowed if item.casefold() == folded), "unknown")


def clean_choice_list(raw, allowed, max_count=None):
    """Keep allowed list values, in order. Anything else becomes "unknown".

    max_count keeps only the first that many values, when a label has a limit.
    """
    if isinstance(raw, str):
        items = [part.strip() for part in raw.split(",") if part.strip()]
    elif isinstance(raw, list):
        items = raw
    else:
        items = []
    cleaned = []
    seen = set()
    for item in items:
        value = clean_choice(item, allowed)
        if value in seen:
            continue
        seen.add(value)
        cleaned.append(value)
    if max_count is not None and max_count > 0:
        cleaned = cleaned[:max_count]
    if not cleaned:
        return ["unknown"]
    return cleaned


def clean_attributes(raw_attributes):
    """Keep only allowed values. Anything else becomes "unknown"."""
    cleaned = {}
    for label, allowed in config.ATTRIBUTES.items():
        value = raw_attributes.get(label)
        if label in config.LIST_ATTRIBUTES:
            cleaned[label] = clean_choice_list(
                value,
                allowed,
                max_count=config.LIST_LIMITS.get(label),
            )
            continue
        cleaned[label] = clean_choice(value, allowed)
    return cleaned


def read_exif_date(path):
    """Return (year, month) from DateTimeOriginal, or None when it is missing."""
    with Image.open(path) as image:
        exif = image.getexif()
        if not exif:
            return None
        raw = exif.get(EXIF_DATETIME_ORIGINAL)
        if not raw:
            raw = exif.get_ifd(EXIF_IFD).get(EXIF_DATETIME_ORIGINAL)
    if not isinstance(raw, str):
        return None
    try:
        date_part = raw.strip().split(" ", 1)[0]
        year_text, month_text, _day_text = date_part.split(":")
        year = int(year_text)
        month = int(month_text)
    except (ValueError, IndexError):
        return None
    if not (1 <= month <= 12 and 1900 <= year <= 2100):
        return None
    return year, month


def months_in_range():
    """Every year-month from MADE_UP_DATE_RANGE, including both ends."""
    start_text, end_text = config.MADE_UP_DATE_RANGE
    start_year, start_month = (int(part) for part in start_text.split("-"))
    end_year, end_month = (int(part) for part in end_text.split("-"))
    months = []
    year, month = start_year, start_month
    while (year, month) <= (end_year, end_month):
        months.append((year, month))
        month += 1
        if month == 13:
            month = 1
            year += 1
    if not months:
        raise SystemExit("MADE_UP_DATE_RANGE does not contain any months.")
    return months


def made_up_dates(paths_without_exif):
    """Give photos in one folder the same month or a neighbouring month.

    The choice depends only on the folder name and the photo's place in that
    folder, so a later run gives the same photo the same made-up date.
    """
    months = [
        pair
        for pair in months_in_range()
        if pair not in {tuple(item) for item in config.FOLDER_CAPTURE_DATES.values()}
    ]
    by_folder = {}
    for relative in paths_without_exif:
        folder = Path(relative).parent.as_posix()
        if folder == ".":
            folder = ""
        by_folder.setdefault(folder, []).append(relative)

    chosen = {}
    window = 3 if len(months) >= 3 else len(months)
    for folder, folder_paths in by_folder.items():
        digest = hashlib.sha256(folder.encode()).digest()
        center = int.from_bytes(digest[:4], "big") % (len(months) - window + 1)
        for index, relative in enumerate(sorted(folder_paths)):
            chosen[relative] = months[center + (index % window)]
    return chosen


def ask_for_photo(client, model_name, image_bytes, pacer):
    """Ask once. If the reply is not JSON, ask one more time."""
    reply = generate(client, model_name, image_bytes, PROMPT, pacer, json_mode=True)
    try:
        return parse_reply(reply)
    except (ValueError, json.JSONDecodeError) as first_error:
        print(f"Reply was not valid JSON ({first_error}). Retrying once.", flush=True)
        reply = generate(client, model_name, image_bytes, PROMPT, pacer, json_mode=True)
        return parse_reply(reply)


def show_random_records(records):
    if not records:
        print("No records to show.", flush=True)
        return
    sample = records if len(records) <= 3 else random.sample(records, 3)
    print("3 random records:" if len(sample) == 3 else f"{len(sample)} records:", flush=True)
    print(json.dumps(sample, indent=2, ensure_ascii=False), flush=True)


def main():
    load_dotenv(ROOT / ".env")
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise SystemExit("GEMINI_API_KEY is missing from final_mvp/.env")

    if not config.VISION_MODELS:
        raise SystemExit("VISION_MODELS is empty.")

    client = genai.Client(api_key=api_key)
    pacer = RequestPacer()
    quota_used = set()
    model_name = next_model(quota_used)
    print(f"Using vision model: {model_name}", flush=True)

    paths = image_paths()
    if not paths:
        raise SystemExit(f"No photos found in {config.PHOTOS_DIR}")

    saved = load_saved()
    assigned_dates = assigned_dates_by_path(saved)
    existing_by_path = {}
    for record in saved:
        path = record.get("path")
        if isinstance(path, str):
            existing_by_path[path] = record

    def save_current(current_records):
        keep_assigned_dates(current_records, assigned_dates)
        save_records(current_records)

    ids = assign_ids(paths, existing_by_path, [record["id"] for record in saved if "id" in record])

    needs_made_up_date = []
    exif_dates = {}
    fixed_dates = {}
    for relative in paths:
        if relative in existing_by_path:
            continue
        # A whole trip or party stays in its month, even when the file has no date.
        fixed = folder_capture_date(relative)
        if fixed is not None:
            fixed_dates[relative] = fixed
            continue
        exif_date = read_exif_date(config.PHOTOS_DIR / relative)
        if exif_date is None:
            needs_made_up_date.append(relative)
        else:
            exif_dates[relative] = exif_date
    invented = made_up_dates(needs_made_up_date)

    records_by_path = dict(existing_by_path)
    described = 0
    skipped = 0
    failed = 0
    total = len(paths)

    for index, relative in enumerate(paths, start=1):
        if relative in existing_by_path:
            # Leave the saved record as it is, including an assigned capture date.
            skipped += 1
            print(f"{index}/{total} already saved: {relative}", flush=True)
            continue
        try:
            image_bytes = resized_jpeg(config.PHOTOS_DIR / relative)
        except Exception as error:
            failed += 1
            print(f"Skipping {relative}: {error}", flush=True)
            current_records = [records_by_path[path] for path in paths if path in records_by_path]
            save_current(current_records)
            continue

        while True:
            try:
                description, raw_attributes, everyday_words = ask_for_photo(
                    client, model_name, image_bytes, pacer
                )
                if relative in fixed_dates:
                    year, month = fixed_dates[relative]
                    date_source = "assigned"
                elif relative in exif_dates:
                    year, month = exif_dates[relative]
                    date_source = "exif"
                else:
                    year, month = invented[relative]
                    date_source = "made_up"
                records_by_path[relative] = {
                    "id": ids[relative],
                    "path": relative,
                    "description": description,
                    "attributes": clean_attributes(raw_attributes),
                    "everyday_words": everyday_words,
                    "capture_year": year,
                    "capture_month": month,
                    "date_source": date_source,
                }
                described += 1
                print(f"{index}/{total} done: {relative}", flush=True)
                break
            except DailyQuotaError:
                print(
                    f"{model_name} has used its daily free quota. Switching to the next model.",
                    flush=True,
                )
                quota_used.add(model_name)
                model_name = next_model(quota_used)
                print(f"Using vision model: {model_name}", flush=True)
                continue
            except (ValueError, json.JSONDecodeError):
                failed += 1
                print(
                    f"Skipping {relative}: the reply was not valid JSON after one retry.",
                    flush=True,
                )
                break
            except Exception as error:
                failed += 1
                print(f"Skipping {relative}: {error}", flush=True)
                break
        # Save even when this photo failed, so earlier photos in this run are kept.
        current_records = [records_by_path[path] for path in paths if path in records_by_path]
        save_current(current_records)

    current_records = [records_by_path[path] for path in paths if path in records_by_path]
    save_current(current_records)
    exif_count = sum(1 for record in current_records if record.get("date_source") == "exif")
    made_up_count = sum(1 for record in current_records if record.get("date_source") == "made_up")
    assigned_count = sum(1 for record in current_records if record.get("date_source") == "assigned")
    print(
        f"Summary: {described} described, {skipped} already saved, {failed} failed. "
        f"{len(current_records)} records in {OUTPUT_PATH.name} "
        f"({exif_count} exif dates, {made_up_count} made-up dates, "
        f"{assigned_count} assigned dates).",
        flush=True,
    )
    show_random_records(current_records)


if __name__ == "__main__":
    main()
