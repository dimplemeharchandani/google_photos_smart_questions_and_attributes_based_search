"""Decide the next tap question and apply the answer.

Plain Python only. The photos, the search text, and the answers so far
are enough. No model is called.
"""

import re

import config

# Ask about clothing colour only when at least this share of photos show people.
PEOPLE_SHARE_FOR_COLOUR = 0.7

# Short names for the line above the question, in question order.
SUMMARY_NAMES = {
    "main_subject": "Mainly of",
    "location_type": "Where",
    "people_count": "Who",
    "clothing_colour": "Colour",
    "time_of_day": "Time of day",
    "capture_year": "Year",
    "capture_month": "Time of year",
    "setting": "Inside or outside",
    "season": "Season",
}

# Spoken answers where capitalising the stored value is not enough.
ANSWER_WORDS = {
    "people_count": {
        "none": "No people",
        "one": "One",
        "two": "Two",
        "small group": "A small group",
        "large group": "A large group",
    },
}

# Months inside each capture_month button, in CAPTURE_MONTH_GROUPS order.
_GROUP_MONTHS = ((1, 2, 3), (4, 5, 6), (7, 8, 9), (10, 11, 12))


def month_groups():
    """Map each group name to the month numbers it covers."""
    names = config.CAPTURE_MONTH_GROUPS
    return {name: months for name, months in zip(names, _GROUP_MONTHS)}


def photo_value(photo, key):
    """The stored answer for this question, or None when the photo has none."""
    if key in config.DATE_ATTRIBUTES:
        return photo.get(key)
    attributes = photo.get("attributes")
    if not isinstance(attributes, dict):
        return None
    return attributes.get(key)


def shown_value(question_key, value):
    """The words on a button and in the answers line."""
    words = ANSWER_WORDS.get(question_key, {})
    if value in words:
        return words[value]
    text = str(value)
    if not text:
        return text
    return text[0].upper() + text[1:]


def summary_line(answers):
    """One line of the answers chosen so far, or an empty string."""
    if not isinstance(answers, dict):
        return ""
    parts = []
    for key in config.QUESTION_ORDER:
        if key not in answers:
            continue
        value = answers[key]
        if value in (config.NOT_SURE_LABEL, config.SHOW_NOW_LABEL):
            continue
        name = SUMMARY_NAMES.get(key, shown_value(key, key.replace("_", " ")))
        parts.append(f"{name}: {shown_value(key, value)}")
    return " · ".join(parts)


def change_line(before, after):
    """How many photos a tap left, for example 14 → 5 photos."""
    word = "photo" if after == 1 else "photos"
    return f"{before} → {after} {word}"


def _comparable(value):
    if isinstance(value, list):
        return tuple(value)
    return value


def _is_unknown(value):
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip().casefold() in ("", "unknown")
    if isinstance(value, list):
        parts = [item.strip() for item in value if isinstance(item, str) and item.strip()]
        return not parts or all(item.casefold() == "unknown" for item in parts)
    return False


def _colour_parts(value):
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str)]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _year_number(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def _month_number(value):
    number = _year_number(value)
    if number is None or not 1 <= number <= 12:
        return None
    return number


def _is_year_answer(value):
    return _year_number(value) is not None


def _people_share(photos):
    if not photos:
        return 0.0
    with_people = 0
    for photo in photos:
        if photo_value(photo, "people_count") != "none":
            with_people += 1
    return with_people / len(photos)


def _colour_words():
    return [
        colour
        for colour in config.ATTRIBUTES.get("clothing_colour", [])
        if colour not in ("none", "unknown")
    ]


def search_mentions_colour(search_text):
    """True when the search already names a clothing colour from the allowed list."""
    folded = " ".join(str(search_text or "").lower().split())
    if not folded:
        return False
    for colour in sorted(_colour_words(), key=len, reverse=True):
        pattern = r"(?<!\w)" + re.escape(colour.lower()) + r"(?!\w)"
        if re.search(pattern, folded):
            return True
    return False


def _same_value_share(photos, key):
    if not photos:
        return 1.0
    counts = {}
    for photo in photos:
        marker = _comparable(photo_value(photo, key))
        counts[marker] = counts.get(marker, 0) + 1
    return max(counts.values()) / len(photos)


def _option_counts(photos, key):
    """Value to how many current photos have it. Skips unknown and none."""
    counts = {}
    if key == "capture_year":
        for photo in photos:
            year = _year_number(photo.get("capture_year"))
            if year is None:
                continue
            counts[year] = counts.get(year, 0) + 1
        return counts
    if key == "capture_month":
        groups = month_groups()
        for photo in photos:
            month = _month_number(photo.get("capture_month"))
            if month is None:
                continue
            for name, months in groups.items():
                if month in months:
                    counts[name] = counts.get(name, 0) + 1
                    break
        return counts
    if key in config.LIST_ATTRIBUTES:
        for photo in photos:
            for part in _colour_parts(photo_value(photo, key)):
                if part == "unknown":
                    continue
                # Only the clothing question hides "none". Other lists may show it.
                if part == "none" and key == "clothing_colour":
                    continue
                counts[part] = counts.get(part, 0) + 1
        return counts
    for photo in photos:
        value = photo_value(photo, key)
        if not isinstance(value, str):
            continue
        if value == "unknown":
            continue
        if value == "none" and key == "clothing_colour":
            continue
        counts[value] = counts.get(value, 0) + 1
    return counts


def _sorted_options(question_key, counts):
    ranked = sorted(counts.items(), key=lambda item: (-item[1], shown_value(question_key, item[0]).casefold()))
    options = []
    for value, count in ranked:
        options.append(
            {
                "value": value,
                "count": count,
                "label": f"{shown_value(question_key, value)} ({count})",
            }
        )
    return options


def apply_answer(photos, question_key, choice):
    """Return the photos still in play, exact matches first.

    "Not sure" and "Show results now" keep every photo in the same order.
    Any other choice keeps exact matches, then photos whose value is unknown.
    Inside each of those groups the previous order stays as it was.
    A clothing colour also drops photos marked none.
    """
    if choice in (config.NOT_SURE_LABEL, config.SHOW_NOW_LABEL):
        return list(photos)

    if question_key in config.LIST_ATTRIBUTES:
        exact = []
        unknown = []
        for photo in photos:
            parts = _colour_parts(photo_value(photo, question_key))
            if choice in parts:
                exact.append(photo)
                continue
            # Clothing "none" means there is no colour to keep. Other lists do not.
            if question_key == "clothing_colour" and "none" in parts and "unknown" not in parts:
                continue
            if "unknown" in parts or not parts:
                unknown.append(photo)
        return exact + unknown

    if question_key == "capture_year":
        chosen = _year_number(choice)
        exact = []
        unknown = []
        for photo in photos:
            year = _year_number(photo.get("capture_year"))
            if chosen is not None and year == chosen:
                exact.append(photo)
                continue
            if year is None:
                unknown.append(photo)
        return exact + unknown

    if question_key == "capture_month":
        months = month_groups().get(choice, ())
        exact = []
        unknown = []
        for photo in photos:
            month = _month_number(photo.get("capture_month"))
            if month is not None and month in months:
                exact.append(photo)
                continue
            if month is None:
                unknown.append(photo)
        return exact + unknown

    exact = []
    unknown = []
    for photo in photos:
        value = photo_value(photo, question_key)
        if value == choice:
            exact.append(photo)
            continue
        if _is_unknown(value):
            unknown.append(photo)
    return exact + unknown


def _choice_narrows(photos, question_key, value):
    return len(apply_answer(photos, question_key, value)) < len(photos)


def _not_about_people(answers):
    """True when the user already said the photo is not about people."""
    subject = answers.get("main_subject")
    if subject not in (None, "people"):
        return True
    return answers.get("people_count") == "none"


def _skip_reason(key, photos, search_text, answers, asked):
    """Why this question should not be asked, or None when it is still open."""
    if key in asked or key in answers:
        return "asked"
    if key not in config.QUESTIONS:
        return "no question text"
    if key == "capture_month" and not _is_year_answer(answers.get("capture_year")):
        return "year not chosen"
    if key in ("people_count", "clothing_colour") and _not_about_people(answers):
        return "not about people"
    if key == "clothing_colour":
        if _people_share(photos) < PEOPLE_SHARE_FOR_COLOUR:
            return "few people"
        if search_mentions_colour(search_text):
            return "colour already in the search"
    if _same_value_share(photos, key) >= config.SKIP_QUESTION_IF_SHARE:
        return "already agree"
    counts = _option_counts(photos, key)
    options = [value for value in counts if _choice_narrows(photos, key, value)]
    if not options:
        return "would not narrow"
    return None


def next_question(
    photos,
    search_text,
    answers,
    asked=(),
    questions_asked=0,
    not_sure_count=0,
    stopped=False,
):
    """The next question dict, or None when asking should stop.

    Each option has value, count, and label. The last two options are
    always Not sure and Show results now.
    """
    if stopped:
        return None
    if questions_asked >= config.MAX_QUESTIONS:
        return None
    if not_sure_count >= config.MAX_NOT_SURE:
        return None
    if len(photos) <= config.MAX_RESULTS_BEFORE_QUESTIONS:
        return None

    if not isinstance(answers, dict):
        answers = {}
    asked = set(asked) | set(answers)

    for key in config.QUESTION_ORDER:
        if _skip_reason(key, photos, search_text, answers, asked):
            continue
        counts = _option_counts(photos, key)
        options = _sorted_options(key, {value: count for value, count in counts.items() if _choice_narrows(photos, key, value)})
        if not options:
            continue
        options.append({"value": config.NOT_SURE_LABEL, "count": None, "label": config.NOT_SURE_LABEL})
        options.append({"value": config.SHOW_NOW_LABEL, "count": None, "label": config.SHOW_NOW_LABEL})
        return {"key": key, "text": config.QUESTIONS[key], "options": options}
    return None
