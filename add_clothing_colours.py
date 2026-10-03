"""Add clothing colours to photos that do not have them yet.

Reads data/photos.json. Photos without a clothing_colour list are sent
to Gemini as text only, ten descriptions at a time. Each reply is checked
against the allowed colours, then saved before the next batch.
"""

import json
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai import types

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import config
from analyze_photos import (
    BUSY_TRIES,
    BUSY_WAIT_SECONDS,
    DailyQuotaError,
    RATE_LIMIT_TRIES,
    RATE_LIMIT_WAIT_SECONDS,
    RequestPacer,
    clean_choice_list,
    error_code,
    is_daily_quota,
    load_saved,
    next_model,
    save_records,
)

BATCH_SIZE = 10


def allowed_colours():
    return config.ATTRIBUTES["clothing_colour"]


def build_prompt(batch):
    """Ask for clothing colours for each photo id. Descriptions only, no images."""
    choices = ", ".join(f'"{value}"' for value in allowed_colours())
    lines = []
    for record in batch:
        description = " ".join(str(record.get("description") or "").split())
        lines.append(f'{record["id"]}: {description}')
    photos = "\n".join(lines)
    return f"""Reply with JSON only. No markdown and no extra words.

You will get photo descriptions, each with an id. For every id, list the main clothing colours worn by the people in that photo.
Choose colours only from this list: {choices}.
A photo can include several colours, because several people may wear different colours.
Use ["none"] if there are no people in the photo.
Use ["unknown"] if the description does not mention clothing colours.
Do not invent colours the description does not mention.

Use exactly this shape:
{{
  "photos": [
    {{"id": 1, "clothing_colour": ["blue"]}}
  ]
}}

Photos:
{photos}
"""


def generate_text(client, model_name, prompt, pacer):
    """Send text only. Wait out per-minute limits and busy errors, then raise."""
    pacer.wait_for_next_request()
    rate_tries = 0
    busy_tries = 0
    request = types.GenerateContentConfig(
        temperature=0.2,
        response_mime_type="application/json",
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )
    while True:
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
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


def parse_batch(text):
    """Map photo id to a cleaned clothing_colour list. Skip items that are not usable."""
    raw = (text or "").strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1]
        if raw.endswith("```"):
            raw = raw[:-3]
        raw = raw.strip()
    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end == -1 or end < start:
        start = raw.find("[")
        end = raw.rfind("]")
    if start == -1 or end == -1 or end < start:
        raise ValueError("reply did not contain JSON")
    data = json.loads(raw[start : end + 1])
    if isinstance(data, dict):
        items = data.get("photos")
        if items is None:
            items = data.get("items")
        if items is None and data and all(str(key).isdigit() for key in data):
            items = [{"id": key, "clothing_colour": value} for key, value in data.items()]
    elif isinstance(data, list):
        items = data
    else:
        raise ValueError("reply JSON was not a list of photos")
    if not isinstance(items, list):
        raise ValueError("reply JSON had no photo list")

    found = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        photo_id = item.get("id")
        try:
            photo_id = int(photo_id)
        except (TypeError, ValueError):
            continue
        colours = item.get("clothing_colour")
        if colours is None and isinstance(item.get("attributes"), dict):
            colours = item["attributes"].get("clothing_colour")
        if colours is None:
            print(f"id {photo_id}: reply had no clothing_colour list", flush=True)
            continue
        found[photo_id] = clean_choice_list(colours, allowed_colours())
    return found


def ask_batch(client, model_name, batch, pacer):
    """Ask once. If the reply is not JSON, ask one more time."""
    prompt = build_prompt(batch)
    reply = generate_text(client, model_name, prompt, pacer)
    try:
        return parse_batch(reply)
    except (ValueError, json.JSONDecodeError) as first_error:
        print(f"Reply was not valid JSON ({first_error}). Retrying once.", flush=True)
        reply = generate_text(client, model_name, prompt, pacer)
        return parse_batch(reply)


def has_clothing_colour(record):
    """True when attributes already hold a non-empty list of allowed colours."""
    attributes = record.get("attributes")
    if not isinstance(attributes, dict):
        return False
    colours = attributes.get("clothing_colour")
    if not isinstance(colours, list) or not colours:
        return False
    allowed = set(allowed_colours())
    return all(isinstance(colour, str) and colour in allowed for colour in colours)


def missing_colours(records):
    """Photos that do not yet have a clothing_colour list."""
    return [record for record in records if not has_clothing_colour(record)]


def print_table(records):
    """Print path, people_count, and clothing_colour for every photo."""
    rows = sorted(records, key=lambda record: record.get("id", 0))
    print(f"\n{'path':<40} {'people_count':<14} clothing_colour", flush=True)
    for record in rows:
        attributes = record.get("attributes") if isinstance(record.get("attributes"), dict) else {}
        people = attributes.get("people_count", "")
        colours = attributes.get("clothing_colour", "")
        if isinstance(colours, list):
            colours = ", ".join(colours)
        print(f"{record.get('path', ''):<40} {str(people):<14} {colours}", flush=True)


def main():
    load_dotenv(ROOT / ".env")
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise SystemExit("GEMINI_API_KEY is missing from final_mvp/.env")
    if not config.VISION_MODELS:
        raise SystemExit("VISION_MODELS is empty.")
    if "clothing_colour" not in config.ATTRIBUTES:
        raise SystemExit("ATTRIBUTES has no clothing_colour list.")

    records = load_saved()
    if not records:
        raise SystemExit("No photo records. Run analyze_photos.py first.")

    pending = missing_colours(records)
    if not pending:
        print(f"All {len(records)} photos already have clothing colours.", flush=True)
        print_table(records)
        return

    by_id = {record["id"]: record for record in records}
    client = genai.Client(api_key=api_key)
    pacer = RequestPacer()
    quota_used = set()
    model_name = next_model(quota_used)
    print(f"Using vision model: {model_name}", flush=True)
    print(f"{len(pending)} photos need clothing colours.", flush=True)

    filled = 0
    failed_ids = []
    batches = [pending[start : start + BATCH_SIZE] for start in range(0, len(pending), BATCH_SIZE)]
    for batch_index, batch in enumerate(batches, start=1):
        ids = [record["id"] for record in batch]
        print(f"Batch {batch_index}/{len(batches)}: ids {ids[0]}–{ids[-1]}", flush=True)
        found = {}
        while True:
            try:
                if not found:
                    found = ask_batch(client, model_name, batch, pacer)
                missing = [record for record in batch if record["id"] not in found]
                if missing:
                    print(
                        f"Retrying {len(missing)} photos that had no usable colour list.",
                        flush=True,
                    )
                    found.update(ask_batch(client, model_name, missing, pacer))
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
            except (ValueError, json.JSONDecodeError) as error:
                print(f"Batch {batch_index} reply could not be used: {error}", flush=True)
                break
            except Exception as error:
                print(f"Batch {batch_index} failed: {error}", flush=True)
                break

        for record in batch:
            colours = found.get(record["id"])
            if not colours:
                failed_ids.append(record["id"])
                print(f"No clothing colours saved for id {record['id']}.", flush=True)
                continue
            attributes = by_id[record["id"]].get("attributes")
            if not isinstance(attributes, dict):
                attributes = {}
                by_id[record["id"]]["attributes"] = attributes
            attributes["clothing_colour"] = colours
            filled += 1
        save_records(list(by_id.values()))
        print(f"Saved batch {batch_index}.", flush=True)

    saved = list(by_id.values())
    still_missing = len(missing_colours(saved))
    print(
        f"Summary: {filled} photos updated, {still_missing} still missing clothing colours.",
        flush=True,
    )
    print_table(saved)
    if failed_ids:
        raise SystemExit(f"Clothing colours were not saved for ids: {failed_ids}")


if __name__ == "__main__":
    main()
