"""Add a main subject to photos that do not have one yet.

Reads data/photos.json. Photos without a main_subject list are sent
to Gemini as text only, ten descriptions at a time. Each reply is checked
against the allowed values, then saved before the next batch.
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


def allowed_subjects():
    return config.ATTRIBUTES["main_subject"]


def subject_limit():
    return config.LIST_LIMITS.get("main_subject", 2)


def build_prompt(batch):
    """Ask what each photo is mainly of. Descriptions only, no images."""
    choices = ", ".join(f'"{value}"' for value in allowed_subjects())
    lines = []
    for record in batch:
        description = " ".join(str(record.get("description") or "").split())
        lines.append(f'{record["id"]}: {description}')
    photos = "\n".join(lines)
    return f"""Reply with JSON only. No markdown and no extra words.

You will get photo descriptions, each with an id. For every id, say what the photo is mainly of.
Choose only from this list: {choices}.
Use at most two values. A photo of a person with a dog can be ["people", "animal"].
Use ["unknown"] when the description does not show what the photo is mainly of.
Do not invent a subject the description does not support.

Use exactly this shape:
{{
  "photos": [
    {{"id": 1, "main_subject": ["people"]}}
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
    """Map photo id to a cleaned main_subject list. Skip items that are not usable."""
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
            items = [{"id": key, "main_subject": value} for key, value in data.items()]
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
        subject = item.get("main_subject")
        if subject is None and isinstance(item.get("attributes"), dict):
            subject = item["attributes"].get("main_subject")
        if subject is None:
            print(f"id {photo_id}: reply had no main_subject list", flush=True)
            continue
        found[photo_id] = clean_choice_list(
            subject,
            allowed_subjects(),
            max_count=subject_limit(),
        )
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


def has_main_subject(record):
    """True when attributes already hold one or two allowed main subjects."""
    attributes = record.get("attributes")
    if not isinstance(attributes, dict):
        return False
    subjects = attributes.get("main_subject")
    if not isinstance(subjects, list) or not subjects:
        return False
    if len(subjects) > subject_limit():
        return False
    allowed = set(allowed_subjects())
    return all(isinstance(subject, str) and subject in allowed for subject in subjects)


def missing_subjects(records):
    """Photos that do not yet have a main_subject list."""
    return [record for record in records if not has_main_subject(record)]


def print_table(records):
    """Print path and main_subject for every photo."""
    rows = sorted(records, key=lambda record: record.get("id", 0))
    print(f"\n{'path':<40} main_subject", flush=True)
    for record in rows:
        attributes = record.get("attributes") if isinstance(record.get("attributes"), dict) else {}
        subjects = attributes.get("main_subject", "")
        if isinstance(subjects, list):
            subjects = ", ".join(subjects)
        print(f"{record.get('path', ''):<40} {subjects}", flush=True)


def main():
    load_dotenv(ROOT / ".env")
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise SystemExit("GEMINI_API_KEY is missing from final_mvp/.env")
    if not config.VISION_MODELS:
        raise SystemExit("VISION_MODELS is empty.")
    if "main_subject" not in config.ATTRIBUTES:
        raise SystemExit("ATTRIBUTES has no main_subject list.")

    records = load_saved()
    if not records:
        raise SystemExit("No photo records. Run analyze_photos.py first.")

    pending = missing_subjects(records)
    if not pending:
        print(f"All {len(records)} photos already have a main subject.", flush=True)
        print_table(records)
        return

    by_id = {record["id"]: record for record in records}
    client = genai.Client(api_key=api_key)
    pacer = RequestPacer()
    quota_used = set()
    model_name = next_model(quota_used)
    print(f"Using vision model: {model_name}", flush=True)
    print(f"{len(pending)} photos need a main subject.", flush=True)

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
                        f"Retrying {len(missing)} photos that had no usable main subject.",
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
            subjects = found.get(record["id"])
            if not subjects:
                failed_ids.append(record["id"])
                print(f"No main subject saved for id {record['id']}.", flush=True)
                continue
            attributes = by_id[record["id"]].get("attributes")
            if not isinstance(attributes, dict):
                attributes = {}
                by_id[record["id"]]["attributes"] = attributes
            attributes["main_subject"] = subjects
            filled += 1
        save_records(list(by_id.values()))
        print(f"Saved batch {batch_index}.", flush=True)

    saved = list(by_id.values())
    still_missing = len(missing_subjects(saved))
    print(
        f"Summary: {filled} photos updated, {still_missing} still missing a main subject.",
        flush=True,
    )
    print_table(saved)
    if failed_ids:
        raise SystemExit(f"Main subjects were not saved for ids: {failed_ids}")


if __name__ == "__main__":
    main()
