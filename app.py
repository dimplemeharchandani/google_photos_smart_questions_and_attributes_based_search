"""Search photos by describing one you half-remember.

Type a short description, and the app finds photos whose saved
description is close to those words. When many photos match, tap a
button to narrow them. No typing after the search.

With an empty search, every photo is shown in a month-by-month timeline.
"""

import io
import sys
from pathlib import Path

import streamlit as st
from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import config
from questions import apply_answer, change_line, next_question, shown_value, summary_line
from search import clean_text, load_library, search

# Some originals are very large. The page only shows a small copy.
Image.MAX_IMAGE_PIXELS = None

THUMB_DIR = config.DATA_DIR / "thumbnails"

# Every thumbnail is a square of this many pixels, cropped from the centre.
THUMB_SIDE = 320

# Photos and answer buttons use this many columns.
COLUMNS = 4

# A long question shows this many answers, then a button for the rest.
VISIBLE_ANSWERS = 6
MORE_OPTIONS = "More options"

MONTH_NAMES = (
    "",
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)

SHORT_MONTHS = (
    "",
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
)

DETAIL_FIELDS = (
    ("main_subject", "Mainly of"),
    ("location_type", "Where"),
    ("people_count", "Who"),
    ("clothing_colour", "Clothing"),
    ("time_of_day", "Time of day"),
    ("setting", "Inside or outside"),
    ("season", "Season"),
)

PAGE_STYLE = """
<style>
div[data-testid="stButton"] button,
div[data-testid="stButton"] button p,
div[data-testid="stButton"] button div {
  white-space: normal !important;
  height: auto !important;
  overflow: visible !important;
  text-overflow: clip !important;
}
div[data-testid="stButton"] button {
  min-height: 2.4rem;
}
button[data-testid="stPopoverButton"] {
  min-height: 1.6rem;
  padding: 0.05rem 0.4rem;
  line-height: 1;
}
button[data-testid="stPopoverButton"] [aria-hidden="true"] {
  display: none;
}
div[data-testid="stPopoverBody"] {
  max-width: 22rem;
}
div[data-testid="stImage"] img {
  aspect-ratio: 1 / 1;
  object-fit: cover;
  object-position: center;
}
</style>
"""


@st.cache_data(show_spinner=False)
def thumbnail(relative_path, source_mtime):
    """Make a square JPEG once and reuse it on the next visit."""
    source = config.PHOTOS_DIR / relative_path
    if not source.is_file():
        return None

    THUMB_DIR.mkdir(parents=True, exist_ok=True)
    safe_name = relative_path.replace("/", "__")
    dest = THUMB_DIR / f"{safe_name}.square.jpg"
    if dest.is_file() and dest.stat().st_size > 0 and dest.stat().st_mtime >= source_mtime:
        return dest.read_bytes()

    with Image.open(source) as image:
        image = ImageOps.exif_transpose(image).convert("RGB")
        width, height = image.size
        side = min(width, height)
        left = (width - side) // 2
        top = (height - side) // 2
        image = image.crop((left, top, left + side, top + side))
        image = image.resize((THUMB_SIDE, THUMB_SIDE), Image.Resampling.LANCZOS)
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=80)
        data = buffer.getvalue()
    dest.write_bytes(data)
    return data


def whole_number(value):
    """Read a year or month stored as a number or a digit string."""
    if isinstance(value, bool) or isinstance(value, float):
        return None
    if isinstance(value, int):
        return value
    text = str(value or "").strip()
    if text.isdigit():
        return int(text)
    return None


def date_key(photo):
    """(year, month) when both are present, otherwise None."""
    year = whole_number(photo.get("capture_year"))
    month = whole_number(photo.get("capture_month"))
    if year is None or month is None or month < 1 or month > 12:
        return None
    return (year, month)


def group_by_date(items, photo_of):
    """Group items by month, newest first. Undated items stay in their order."""
    buckets = {}
    unknown = []
    for item in items:
        key = date_key(photo_of(item))
        if key is None:
            unknown.append(item)
            continue
        buckets.setdefault(key, []).append(item)
    ordered = [(key, buckets[key]) for key in sorted(buckets, reverse=True)]
    return ordered, unknown


def photo_count_label(count):
    if count == 1:
        return "1 photo"
    return f"{count} photos"


def group_heading(title, count):
    """Month header with how many photos are in that month."""
    st.subheader(f"{title} · {photo_count_label(count)}")


def library_months(photos):
    """Every year-month in the library, oldest first."""
    found = set()
    for photo in photos:
        key = date_key(photo)
        if key is not None:
            found.add(key)
    return sorted(found)


def month_chip(key):
    """Short slider label, such as Dec 2023."""
    year, month = key
    return f"{SHORT_MONTHS[month]} {year}"


def show_date_slider(photos):
    """Month range from the earliest photo to the latest. Full range is the default."""
    months = library_months(photos)
    if len(months) < 2:
        st.session_state.pop("date_bounds", None)
        return
    st.session_state.date_bounds = (months[0], months[-1])
    value = (months[0], months[-1]) if "date_span" not in st.session_state else None
    if value is None:
        st.select_slider(
            "Dates",
            options=months,
            format_func=month_chip,
            key="date_span",
        )
        return
    st.select_slider(
        "Dates",
        options=months,
        value=value,
        format_func=month_chip,
        key="date_span",
    )


def span_ends():
    """(start, end, full) for the slider, or None when every photo is shown."""
    bounds = st.session_state.get("date_bounds")
    picked = st.session_state.get("date_span")
    if not bounds or not isinstance(picked, (tuple, list)) or len(picked) != 2:
        return None
    start, end = picked
    if start > end:
        start, end = end, start
    return start, end, (start, end) == tuple(bounds)


def photo_in_span(photo):
    """True when this photo falls inside the chosen months.

    Photos with no date stay visible only while the slider covers every month.
    """
    span = span_ends()
    if span is None:
        return True
    start, end, full = span
    key = date_key(photo)
    if key is None:
        return full
    return start <= key <= end


def filter_photos(photos):
    return [photo for photo in photos if photo_in_span(photo)]


def filter_matches(matches):
    return [(photo, score) for photo, score in matches if photo_in_span(photo)]


def detail_text(key, value):
    """One readable value for the details menu."""
    if isinstance(value, list):
        parts = [
            shown_value(key, item)
            for item in value
            if isinstance(item, str) and item.strip()
        ]
        return ", ".join(parts) if parts else "Unknown"
    if value is None or value == "":
        return "Unknown"
    return shown_value(key, value)


def show_photo_menu(photo, score=None):
    """Small menu at the top-right of a photo. Opens that photo's details."""
    _spacer, menu = st.columns([6, 1])
    with menu:
        with st.popover("⋮", key=f"menu-{photo.get('path')}"):
            key = date_key(photo)
            if key is None:
                date_text = "Date unknown"
            else:
                date_text = f"{MONTH_NAMES[key[1]]} {key[0]}"
            st.markdown(f"**Date:** {date_text}")
            attributes = photo.get("attributes") if isinstance(photo.get("attributes"), dict) else {}
            for field, title in DETAIL_FIELDS:
                st.markdown(f"**{title}:** {detail_text(field, attributes.get(field))}")
            st.markdown("**Description:**")
            st.write(photo.get("description") or "Unknown")
            st.markdown(f"**File:** {photo.get('path') or ''}")
            if score is not None:
                st.markdown(f"**Score:** {score:.2f}")


def show_thumb(photo):
    source = config.PHOTOS_DIR / photo["path"]
    source_mtime = source.stat().st_mtime if source.is_file() else 0
    image = thumbnail(photo["path"], source_mtime)
    if image is not None:
        st.image(image, width="stretch")


def show_grid(entries, show_details=False, with_score=False):
    """Four equal square photos per row. A short last row stays the same size."""
    for start in range(0, len(entries), COLUMNS):
        row = entries[start : start + COLUMNS]
        columns = st.columns(COLUMNS)
        for column, entry in zip(columns, row):
            with column:
                if with_score:
                    photo, score = entry
                else:
                    photo, score = entry, None
                show_photo_menu(photo, score if with_score else None)
                show_thumb(photo)
                if score is not None:
                    st.caption(f"{score:.2f}")
                if with_score and show_details:
                    st.write(photo.get("description") or "")


def show_date_groups(groups, unknown, show_details=False, with_score=False):
    for (year, month), items in groups:
        group_heading(f"{MONTH_NAMES[month]} {year}", len(items))
        show_grid(items, show_details=show_details, with_score=with_score)
    if unknown:
        group_heading("Date unknown", len(unknown))
        show_grid(unknown, show_details=show_details, with_score=with_score)


def show_timeline(photos):
    """Photos inside the date range, grouped by month and year, newest first."""
    visible = filter_photos(photos)
    groups, unknown = group_by_date(visible, lambda photo: photo)
    if not groups and not unknown:
        st.write("No photos in this date range.")
        return
    show_date_groups(groups, unknown)


def show_results(matches, show_details, sort_by):
    """Search results, best match first, or grouped by date when asked."""
    if not matches:
        st.write("No close matches found. Try describing it differently.")
        return

    st.write(f"{len(matches)} photos found")
    if sort_by == "Date":
        groups, unknown = group_by_date(matches, lambda item: item[0])
        show_date_groups(groups, unknown, show_details=show_details, with_score=True)
        return
    show_grid(matches, show_details=show_details, with_score=True)


def reset_search():
    """Clear the search, the questions, and the answers."""
    st.session_state.active_query = ""
    st.session_state.results = []
    st.session_state.answers = {}
    st.session_state.asked = []
    st.session_state.questions_asked = 0
    st.session_state.not_sure_count = 0
    st.session_state.stopped = False
    st.session_state.last_change = ""
    st.session_state.show_more_for = ""
    st.session_state.pop("result_sort", None)
    st.session_state.pop("date_span", None)
    st.session_state.pop("date_bounds", None)
    st.session_state.search_round = st.session_state.get("search_round", 0) + 1


def remember_question_state():
    """Fill question memory the first time a search is shown."""
    st.session_state.setdefault("answers", {})
    st.session_state.setdefault("asked", [])
    st.session_state.setdefault("questions_asked", 0)
    st.session_state.setdefault("not_sure_count", 0)
    st.session_state.setdefault("stopped", False)
    st.session_state.setdefault("last_change", "")
    st.session_state.setdefault("show_more_for", "")


def start_search(query):
    """Run one search and forget any questions from the previous search."""
    st.session_state.active_query = query
    st.session_state.results = search(query) if query else []
    st.session_state.answers = {}
    st.session_state.asked = []
    st.session_state.questions_asked = 0
    st.session_state.not_sure_count = 0
    st.session_state.stopped = False
    st.session_state.last_change = ""
    st.session_state.show_more_for = ""
    st.session_state.result_sort = "Best match"


def apply_tap(question, choice):
    """Keep the photos the tap allows, and remember that this question was used."""
    results = st.session_state.results
    visible_before = [photo for photo, _score in results if photo_in_span(photo)]
    before = len(visible_before)
    photos = [photo for photo, _score in results]
    scores = {id(photo): score for photo, score in results}
    kept = apply_answer(photos, question["key"], choice)
    st.session_state.results = [(photo, scores[id(photo)]) for photo in kept]
    after = len([photo for photo in kept if photo_in_span(photo)])
    st.session_state.asked = list(st.session_state.asked) + [question["key"]]
    st.session_state.questions_asked += 1
    st.session_state.show_more_for = ""
    if choice == config.NOT_SURE_LABEL:
        st.session_state.not_sure_count += 1
    elif choice == config.SHOW_NOW_LABEL:
        st.session_state.stopped = True
    else:
        answers = dict(st.session_state.answers)
        answers[question["key"]] = choice
        st.session_state.answers = answers
    st.session_state.last_change = change_line(before, after)


def buttons_for(question):
    """Answers in rows, with the less common ones hidden until asked."""
    choices = []
    always = []
    for option in question["options"]:
        if option["value"] in (config.NOT_SURE_LABEL, config.SHOW_NOW_LABEL):
            always.append(option)
        else:
            choices.append(option)

    showing_more = st.session_state.get("show_more_for") == question["key"]
    if showing_more or len(choices) <= VISIBLE_ANSWERS:
        visible = list(choices)
    else:
        visible = list(choices[:VISIBLE_ANSWERS])
        visible.append({"value": MORE_OPTIONS, "label": MORE_OPTIONS})
    return visible + always


def show_question(question):
    """Buttons in rows of four. Returns the tapped answer, or None.

    "More options" only reveals the rest. It is not an answer.
    """
    options = buttons_for(question)
    for start in range(0, len(options), COLUMNS):
        row = options[start : start + COLUMNS]
        columns = st.columns(COLUMNS)
        for column, option in zip(columns, row):
            key = f"answer-{question['key']}-{option['value']}"
            if column.button(option["label"], key=key, width="stretch"):
                if option["value"] == MORE_OPTIONS:
                    st.session_state.show_more_for = question["key"]
                    st.rerun()
                return option
    return None


def main():
    st.set_page_config(page_title="Photo search", layout="wide")
    st.markdown(PAGE_STYLE, unsafe_allow_html=True)
    st.title("Photo search")
    st.write("Describe a photo you half-remember")

    if st.session_state.pop("do_reset", False):
        reset_search()

    photos, _, saved_model, problem = load_library()
    if problem:
        st.error(problem)
        return

    # Old embeddings cannot be compared with a different model.
    if saved_model != config.EMBEDDING_MODEL:
        built_with = saved_model or "an unknown model"
        st.warning(
            f"These embeddings were built with {built_with}, "
            f"but this app searches with {config.EMBEDDING_MODEL}. "
            "Re-run build_embeddings.py, then refresh this page."
        )
        return

    # Enter inside the box submits the form, same as the Search button.
    # A new form key on Start over clears the box. A form keeps its own text.
    search_round = st.session_state.get("search_round", 0)
    with st.form(f"search-{search_round}"):
        search_text = st.text_input("Search text", label_visibility="collapsed")
        submitted = st.form_submit_button("Search")

    detail_column, reset_column = st.columns([3, 1])
    with detail_column:
        show_details = st.checkbox("Show details")
    with reset_column:
        start_over = st.button("Start over", width="stretch")

    if start_over:
        st.session_state.do_reset = True
        st.rerun()

    if submitted:
        start_search(clean_text(search_text))

    show_date_slider(photos or [])

    query = st.session_state.get("active_query", "")
    if not query:
        show_timeline(photos or [])
        return

    remember_question_state()
    if "results" not in st.session_state:
        start_search(query)

    results = st.session_state.results
    visible = filter_matches(results)
    current = [photo for photo, _score in visible]
    question = next_question(
        current,
        query,
        st.session_state.answers,
        asked=st.session_state.asked,
        questions_asked=st.session_state.questions_asked,
        not_sure_count=st.session_state.not_sure_count,
        stopped=st.session_state.stopped,
    )

    answers_so_far = summary_line(st.session_state.answers)
    if answers_so_far:
        st.write(answers_so_far)
    # This line is filled only inside apply_tap, so it stays hidden until a tap.
    if st.session_state.last_change:
        st.write(st.session_state.last_change)
    if question is not None:
        st.write(question["text"])
        tapped = show_question(question)
        if tapped is not None:
            apply_tap(question, tapped["value"])
            st.rerun()

    sort_by = st.segmented_control(
        "Sort by",
        ["Best match", "Date"],
        default="Best match",
        key="result_sort",
        required=True,
        width="content",
    )
    if results and not visible:
        st.write("No photos in this date range.")
        return
    show_results(visible, show_details, sort_by)


if __name__ == "__main__":
    main()
