"""Settings for the photo search prototype."""

from pathlib import Path

# Fixed labels the vision model fills by looking at the image.
# Each label only allows the values listed here, and "unknown" is always allowed.
ATTRIBUTES = {
    "main_subject": [
        "people",
        "food or drinks",
        "animal",
        "nature or scenery",
        "building or place",
        "vehicle",
        "object",
        "unknown",
    ],
    "location_type": [
        "beach",
        "cafe or restaurant",
        "home",
        "street or city",
        "nature or park",
        "event venue",
        "other",
        "unknown",
    ],
    "people_count": [
        "none",
        "one",
        "two",
        "small group",
        "large group",
        "unknown",
    ],
    "time_of_day": [
        "day",
        "sunset or evening",
        "night",
        "unknown",
    ],
    "setting": [
        "indoor",
        "outdoor",
        "unknown",
    ],
    "season": [
        "summer",
        "winter",
        "rainy",
        "unknown",
    ],
    "clothing_colour": [
        "white",
        "black",
        "grey",
        "red",
        "pink",
        "orange",
        "yellow",
        "green",
        "blue",
        "purple",
        "brown",
        "beige",
        "multicolour or patterned",
        "none",
        "unknown",
    ],
}

# These labels store a list of allowed values. Every other label stores one value.
# A list is used when one photo can have several answers, such as clothing colours.
# main_subject keeps at most two values, for example people and animal.
LIST_ATTRIBUTES = ("main_subject", "clothing_colour")

# How many values a list label may keep. Other list labels keep every allowed value.
LIST_LIMITS = {
    "main_subject": 2,
}

# Everyday words a search might use for each label value.
# If a search mentions one of these, every photo with that label is a candidate.
# Each label in ATTRIBUTES has an entry here, including values added later.
LABEL_SYNONYMS = {
    "main_subject": {
        "people": [
            "people",
            "person",
        ],
        "food or drinks": [
            "food or drinks",
            "food",
            "drink",
            "drinks",
        ],
        "animal": [
            "animal",
            "animals",
        ],
        "nature or scenery": [
            "nature or scenery",
            "scenery",
        ],
        "building or place": [
            "building or place",
            "building",
        ],
        "vehicle": [
            "vehicle",
            "vehicles",
        ],
        "object": [
            "object",
        ],
        "unknown": [
            "unknown",
        ],
    },
    "location_type": {
        "beach": [
            "beach",
            "beaches",
            "seaside",
            "seashore",
            "shore",
            "shoreline",
            "coast",
            "coastline",
            "sea",
            "ocean",
            "sandy beach",
            "by the sea",
            "at the beach",
            "beachside",
        ],
        "cafe or restaurant": [
            "cafe",
            "café",
            "cafes",
            "cafés",
            "coffee shop",
            "coffeehouse",
            "coffee house",
            "coffee bar",
            "restaurant",
            "restaurants",
            "diner",
            "bistro",
            "eatery",
            "cafeteria",
            "cafe or restaurant",
        ],
        "home": [
            "home",
            "house",
            "apartment",
            "flat",
            "residence",
            "living room",
            "kitchen",
            "bedroom",
            "at home",
        ],
        "street or city": [
            "street",
            "streets",
            "city",
            "cities",
            "downtown",
            "urban",
            "town",
            "road",
            "sidewalk",
            "skyline",
            "city street",
            "avenue",
            "street or city",
        ],
        "nature or park": [
            "nature",
            "park",
            "parks",
            "forest",
            "woods",
            "woodland",
            "garden",
            "countryside",
            "meadow",
            "hiking trail",
            "nature or park",
        ],
        "event venue": [
            "event venue",
            "venue",
            "wedding",
            "wedding venue",
            "party venue",
            "banquet",
            "banquet hall",
            "wedding reception",
            "conference hall",
        ],
        "other": [
            "other",
            "somewhere else",
        ],
        "unknown": [
            "unknown",
        ],
    },
    "people_count": {
        "none": [
            "none",
            "nobody",
            "no people",
            "no one",
            "without people",
        ],
        "one": [
            "one",
            "one person",
            "a person",
            "solo",
            "alone",
            "single person",
        ],
        "two": [
            "two",
            "two people",
            "a couple",
            "couple",
            "pair of people",
        ],
        "small group": [
            "small group",
            "a few people",
            "few people",
            "handful of people",
        ],
        "large group": [
            "large group",
            "crowd",
            "big group",
            "many people",
            "lots of people",
        ],
        "unknown": [
            "unknown",
        ],
    },
    "time_of_day": {
        "day": [
            "day",
            "daytime",
            "day time",
            "during the day",
            "in the daytime",
            "morning",
            "afternoon",
            "midday",
            "noon",
        ],
        "sunset or evening": [
            "sunset",
            "evening",
            "dusk",
            "sundown",
            "golden hour",
            "twilight",
            "sunset or evening",
        ],
        "night": [
            "night",
            "nighttime",
            "night time",
            "at night",
            "after dark",
        ],
        "unknown": [
            "unknown",
        ],
    },
    "setting": {
        "indoor": [
            "indoor",
            "indoors",
            "inside",
            "interior",
        ],
        "outdoor": [
            "outdoor",
            "outdoors",
            "outside",
            "exterior",
            "open air",
        ],
        "unknown": [
            "unknown",
        ],
    },
    "season": {
        "summer": [
            "summer",
            "summertime",
            "summer time",
        ],
        "winter": [
            "winter",
            "wintertime",
            "winter time",
        ],
        "rainy": [
            "rainy",
            "raining",
            "rain",
            "rainfall",
            "in the rain",
            "wet weather",
        ],
        "unknown": [
            "unknown",
        ],
    },
}

# Casual or regional words rewritten to a more "standard" word before a
# search is embedded and re-ranked (not before label matching - that is
# LABEL_SYNONYMS's job, feeding add_label_matches instead).
#
# This is a small, hand-curated map, not a thesaurus: add an entry only
# once a real query shows the gap, the way "frock" -> "dress" was found
# by tests/test_queries.csv's "girl in white frock" case (see
# docs/search_and_questions_improvement_plan.md §2.3).
FREE_TEXT_SYNONYMS = {
    "frock": "dress",
    "pram": "stroller",
    "specs": "glasses",
    "snaps": "photos",
    "fag": "cigarette",
    "telly": "television",
}

# Date labels. The vision model does not fill these.
# They come from the photo's EXIF date, a made-up date when EXIF is missing,
# or assign_dates.py when date_source is "assigned".
# When asking, capture_year offers only years that appear in the current results.
# capture_month is offered as the four parts of the year in CAPTURE_MONTH_GROUPS.
DATE_ATTRIBUTES = ("capture_year", "capture_month")

# How capture_month is grouped when it is asked as a question.
CAPTURE_MONTH_GROUPS = (
    "Jan–Mar",
    "Apr–Jun",
    "Jul–Sep",
    "Oct–Dec",
)

# Order in which clarifying questions are asked.
# Ask main_subject first. Skip people and clothing when the answer is not people.
# Ask capture_month only after capture_year has been answered with a year.
# Ask clothing_colour only when the current photos mostly show people.
QUESTION_ORDER = (
    "main_subject",
    "location_type",
    "people_count",
    "clothing_colour",
    "time_of_day",
    "capture_year",
    "capture_month",
    "setting",
    "season",
)

# The question shown for each label. The user answers by tapping a button.
QUESTIONS = {
    "main_subject": "What was the photo mainly of?",
    "location_type": "Where was it?",
    "people_count": "Who was in the photo?",
    "clothing_colour": "What colour were they wearing?",
    "time_of_day": "What time of day was it?",
    "capture_year": "Roughly which year?",
    "capture_month": "Which part of the year?",
    "setting": "Were you inside or outside?",
    "season": "What season was it?",
}

# Button that means "do not filter on this question."
NOT_SURE_LABEL = "Not sure"

# Button that means "stop asking and show the photos now."
SHOW_NOW_LABEL = "Show results now"

# Sentence-embedding model used to compare the search text with photo descriptions.
EMBEDDING_MODEL = "BAAI/bge-small-en-v1.5"

# Cross-encoder that re-orders the first-stage candidates.
# Search uses this model's raw scores, with no sigmoid.
RERANK_MODEL = "BAAI/bge-reranker-base"

# Hide a photo when its raw re-ranker score is below this.
# If every photo is below it, the search returns no photos.
#
# Calibrated against tests/test_queries.csv rather than picked blindly:
# -4.0 let a true match ("girl in white frock", raw -5.23) get discarded
# while letting an unrelated query ("penguin", raw -3.92) return a photo.
# -3.6 sits strictly between those two measured scores, so it fixes the
# false-positive without needing to touch the false-empty case (that one
# is instead fixed on the input side - see FREE_TEXT_SYNONYMS below,
# which turns "frock" into "dress" before scoring and lifts its raw score
# well above either value).
RERANK_MIN_SCORE = -3.6

# Final order mixes two scores. The re-ranker score is scaled to 0–1
# across the candidates, then combined with the first-stage similarity.
# final = RERANK_WEIGHT * scaled_rerank + SIMILARITY_WEIGHT * similarity
RERANK_WEIGHT = 0.1
SIMILARITY_WEIGHT = 0.9

# How many of the closest embedding matches are sent to the re-ranker.
# Bumped from 30 (§2.8): at 102 photos the cost difference is small
# (~0.2-0.3s per search) and a slightly wider net gives the re-ranker a
# few more real candidates to work with before RERANK_MIN_SCORE trims it
# back down. Revisit again as the library grows well past this size.
RERANK_TOP_N = 40

# Added in front of search text only. Photo descriptions are embedded without it.
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "

# Vision models tried in this order. The first one that still works is used.
VISION_MODELS = [
    "gemini-3.6-flash",
    "gemini-3.5-flash",
    "gemini-3.5-flash-lite",
    "gemini-3-flash-preview",
]

# Vision model that reads each photo and fills ATTRIBUTES.
# analyze_photos.py starts with the first name in VISION_MODELS.
VISION_MODEL = "gemini-3.6-flash"

# A photo is shown only if its score is at least this high.
MIN_SCORE_FLOOR = 0.35

# A photo is shown only if its score is within this much of the best score.
MAX_GAP_FROM_TOP = 0.08

# If the search still has more photos than this, keep asking questions.
MAX_RESULTS_BEFORE_QUESTIONS = 2

# Skip a question when at least this share of the current results already agree.
# 0.9 means skip it when 90% of the photos share one answer.
SKIP_QUESTION_IF_SHARE = 0.9

# Skip a question when fewer than this share of the current results even
# have a known (non-"unknown") value for it. A question that half the
# library can't answer anyway (season: 51/102 "unknown" at the time this
# was measured) is a weak use of the question budget - the other
# attributes sit at 0.85-1.00 known, so 0.6 only catches genuinely
# sparse ones. See docs/search_and_questions_improvement_plan.md §2.5.
MIN_KNOWN_SHARE_FOR_QUESTION = 0.6

# Ask at most this many narrowing questions for one search.
MAX_QUESTIONS = 3

# Stop asking after this many "Not sure" taps.
MAX_NOT_SURE = 2

# Inclusive range for a made-up capture date when a photo has no EXIF date.
# Stored as year-month, from January 2019 through August 2026.
MADE_UP_DATE_RANGE = ("2019-01", "2026-08")

# Folders that were all taken in one month. The gallery keeps that month together.
# bali is one trip. Birthday photos are one party.
FOLDER_CAPTURE_DATES = {
    "bali": (2025, 11),
    "Birthday photos": (2026, 1),
}

# Folder of photos this prototype searches.
PHOTOS_DIR = Path(__file__).resolve().parent / "photos"

# Folder where generated files (descriptions, embeddings, and similar) are saved.
DATA_DIR = Path(__file__).resolve().parent / "data"
