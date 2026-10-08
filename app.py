"""Search photos by describing one you half-remember.

Type a short description, and the app finds photos whose saved
description is close to those words. When many photos match, tap a
button to narrow them. No typing after the search.

With an empty search, every photo is shown in a month-by-month timeline.
"""

import csv
import html
import io
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import streamlit as st
from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import config
from questions import SUMMARY_NAMES, apply_answer, change_line, next_question, shown_value, summary_line
from search import clean_text, load_library, mentioned_labels, search

# One row per thumbs up / down, so §2.1-§2.5 can eventually be judged
# against real usage instead of just tests/test_queries.csv.
FEEDBACK_LOG_PATH = config.DATA_DIR / "feedback_log.csv"
FEEDBACK_LOG_FIELDS = ("timestamp", "query", "answers", "result_count", "verdict")

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

GITHUB_URL = (
    "https://github.com/dimplemeharchandani/"
    "google_photos_smart_questions_and_attributes_based_search"
)

# Example half-remembered descriptions. Tapping one runs that search,
# the same as typing it in and pressing the search button.
EXAMPLE_PROMPTS = (
    "a birthday cake with string lights, maybe last winter",
    "us at the beach with mountains behind us",
    "a rainy evening selfie somewhere in the city",
)

# The four semicircles of the Google Photos mark: yellow, red, green, blue.
PHOTOS_LOGO = """
<svg class="brand-logo" viewBox="0 0 256 256" role="img" aria-label="Google Photos">
  <path fill="#34A853" d="M58.222 192C58.222 156.672 86.894 128 122.222 128H128V250.222C128 253.44 125.367 256 122.222 256C86.894 256 58.222 227.328 58.222 192Z"/>
  <path fill="#FBBC04" d="M64 58.222C99.328 58.222 128 86.894 128 122.222V128H5.778C2.56 128 0 125.367 0 122.222C0 86.894 28.672 58.222 64 58.222Z"/>
  <path fill="#EA4335" d="M197.778 64C197.778 99.328 169.106 128 133.778 128H128V5.778C128 2.56 130.633 0 133.778 0C169.106 0 197.778 28.672 197.778 64Z"/>
  <path fill="#4285F4" d="M192 197.778C156.672 197.778 128 169.106 128 133.778V128H250.222C253.44 128 256 130.633 256 133.778C256 169.106 227.328 197.778 192 197.778Z"/>
</svg>
"""


def _icon(path):
    """An 18px line icon. Every sidebar icon uses this same box."""
    return (
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" '
        'stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">'
        f"{path}</svg>"
    )


ICON_REPO = _icon(
    '<polyline points="16 18 22 12 16 6"/>'
    '<polyline points="8 6 2 12 8 18"/>'
)

# Icons used only on the "How it works" page, one per step of either flow.
ICON_EYE = _icon('<path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/>')
ICON_TAG = _icon(
    '<path d="M20.59 13.41 13.42 20.58a2 2 0 0 1-2.83 0L2 12V2h10l8.59 8.59a2 2 0 0 1 0 2.82z"/>'
    '<line x1="7" y1="7" x2="7.01" y2="7"/>'
)
ICON_GRID = _icon(
    '<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/>'
    '<rect x="14" y="14" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/>'
)
ICON_CHECK = _icon(
    '<path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/>'
)
ICON_PENCIL = _icon(
    '<path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/>'
    '<path d="M18.5 2.5a2.12 2.12 0 0 1 3 3L12 15l-4 1 1-4Z"/>'
)
ICON_SEARCH = _icon('<circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>')
ICON_LAYERS = _icon(
    '<polygon points="12 2 2 7 12 12 22 7 12 2"/>'
    '<polyline points="2 17 12 22 22 17"/><polyline points="2 12 12 17 22 12"/>'
)
ICON_MESSAGE = _icon(
    '<path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a'
    '8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"/>'
)
ICON_POINTER = _icon('<path d="M3 3l7.07 16.97 2.51-7.39 7.39-2.51L3 3z"/><path d="M13 13l6 6"/>')
ICON_REPEAT = _icon(
    '<polyline points="17 1 21 5 17 9"/><path d="M3 11V9a4 4 0 0 1 4-4h14"/>'
    '<polyline points="7 23 3 19 7 15"/><path d="M21 13v2a4 4 0 0 1-4 4H3"/>'
)
ICON_PHOTO = _icon(
    '<rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/>'
    '<polyline points="21 15 16 10 5 21"/>'
)
ICON_CALENDAR = _icon(
    '<rect x="3" y="4" width="18" height="18" rx="2"/><line x1="16" y1="2" x2="16" y2="6"/>'
    '<line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/>'
)
ICON_SKIP = _icon('<polygon points="5 4 15 12 5 20 5 4"/><line x1="19" y1="5" x2="19" y2="19"/>')
ICON_STOP = _icon('<circle cx="12" cy="12" r="10"/><rect x="9" y="9" width="6" height="6" rx="1"/>')

PAGE_STYLE = """
<style>
  :root {
    --ink: #1f1f1f;
    --muted: #5f6368;
    --line: #e6e8ee;
    --blue: #1a73e8;
    --blue-soft: #e8f0fe;
    --pill: #f0f4f9;
    --sidebar-w: 312px;
  }

  header[data-testid="stHeader"], #MainMenu, footer { display: none; }
  [data-testid="stSidebarHeader"],
  [data-testid="stSidebarCollapseButton"],
  [data-testid="stSidebarCollapsedControl"],
  [data-testid="collapsedControl"] { display: none !important; }

  [data-testid="stSidebar"] {
    background: #ffffff !important;
    border-right: 1px solid #eceff1;
    box-sizing: border-box !important;
    width: var(--sidebar-w) !important;
    min-width: var(--sidebar-w) !important;
    max-width: var(--sidebar-w) !important;
    transform: none !important;
  }

  .stApp, [data-testid="stAppViewContainer"], [data-testid="stMain"] {
    background: #ffffff;
  }
  .stApp::before {
    content: "";
    position: fixed;
    top: 0; left: 0; right: 0;
    height: 3px;
    z-index: 999999;
    pointer-events: none;
    background: linear-gradient(90deg, #FBBC04, #EA4335, #4285F4, #34A853);
  }

  /* margin: auto keeps everything centred within whatever width is left
     of the sidebar, on any screen size - not flush against its left edge. */
  [data-testid="stMain"] .block-container {
    padding-top: 1.1rem;
    padding-bottom: 2rem;
    padding-left: 1.4rem;
    padding-right: 1.4rem;
    max-width: 1180px;
    margin-left: auto;
    margin-right: auto;
  }

  /* ---------------- Sidebar ---------------- */
  /* Streamlit's own sidebar chrome clips horizontal overflow (it only
     expects vertical scrolling), which was silently hiding every nav
     tooltip/popover since they're positioned just past the sidebar's
     right edge. Force the whole ancestor chain to let them escape. */
  [data-testid="stSidebar"],
  [data-testid="stSidebarContent"],
  [data-testid="stSidebarUserContent"],
  [data-testid="stSidebar"] [data-testid="stVerticalBlockBorderWrapper"],
  [data-testid="stSidebar"] [data-testid="stVerticalBlock"],
  [data-testid="stSidebar"] [data-testid="stElementContainer"] {
    overflow: visible !important;
  }
  [data-testid="stSidebarContent"] { padding: 11px 16px 0 !important; }
  [data-testid="stSidebarUserContent"] { padding-left: 0 !important; padding-right: 0 !important; }
  [data-testid="stSidebar"] [data-testid="stVerticalBlock"] { gap: 0 !important; }
  [data-testid="stSidebar"] [data-testid="stElementContainer"],
  [data-testid="stSidebar"] [data-testid="stButton"] {
    width: 100% !important;
    margin: 0 !important;
    padding: 0 !important;
    flex: 0 0 auto !important;
    min-height: unset !important;
    height: auto !important;
    overflow: visible !important;
  }
  [data-testid="stSidebar"] button {
    width: 100% !important;
    min-height: 40px !important;
    height: 40px !important;
    margin: 0 !important;
    padding: 0 10px !important;
    gap: 12px !important;
    display: flex !important;
    align-items: center !important;
    justify-content: flex-start !important;
    background: transparent !important;
    border: none !important;
    border-radius: 10px !important;
    box-shadow: none !important;
    outline: none !important;
    color: #3c4043 !important;
    font-size: 17px !important;
    font-weight: 500 !important;
    text-align: left !important;
    line-height: 1.2 !important;
  }
  [data-testid="stSidebar"] button > div,
  [data-testid="stSidebar"] button p {
    margin: 0 !important;
    width: auto !important;
    flex: 0 1 auto !important;
    background: transparent !important;
    font-size: 17px !important;
    font-weight: 500 !important;
    line-height: 1.2 !important;
    text-align: left !important;
    color: #3c4043 !important;
  }
  [data-testid="stSidebar"] button:hover {
    background: #f1f3f4 !important;
    color: #3c4043 !important;
  }

  .st-key-brand button { min-height: 56px !important; height: 56px !important; margin-bottom: 10px !important; }
  .st-key-brand button p { font-size: 21px !important; font-weight: 600 !important; letter-spacing: -0.02em; color: #1f1f1f !important; }
  .st-key-brand button::before {
    content: "";
    width: 29px; height: 29px; flex: 0 0 29px;
    background: center / 29px 29px no-repeat url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 256 256'%3E%3Cpath fill='%2334A853' d='M58.2 192C58.2 156.7 86.9 128 122.2 128H128v122.2c0 3.2-2.6 5.8-5.8 5.8C86.9 256 58.2 227.3 58.2 192z'/%3E%3Cpath fill='%23FBBC04' d='M64 58.2C99.3 58.2 128 86.9 128 122.2V128H5.8C2.6 128 0 125.4 0 122.2 0 86.9 28.7 58.2 64 58.2z'/%3E%3Cpath fill='%23EA4335' d='M197.8 64c0 35.3-28.7 64-64 64H128V5.8C128 2.6 130.6 0 133.8 0 169.1 0 197.8 28.7 197.8 64z'/%3E%3Cpath fill='%234285F4' d='M192 197.8c-35.3 0-64-28.7-64-64V128h122.2c3.2 0 5.8 2.6 5.8 5.8 0 35.3-28.7 64-64 64z'/%3E%3C/svg%3E");
  }
  .st-key-nav-new button::before,
  .st-key-nav-library button::before,
  .st-key-nav-flow button::before {
    content: "";
    width: 22px; height: 22px; flex: 0 0 22px;
    background: center / 22px 22px no-repeat;
  }
  .st-key-nav-new button::before {
    background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%233c4043' stroke-width='1.75' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M12 20h9'/%3E%3Cpath d='M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z'/%3E%3C/svg%3E");
  }
  .st-key-nav-library button::before {
    background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%233c4043' stroke-width='1.75' stroke-linecap='round' stroke-linejoin='round'%3E%3Crect x='3' y='3' width='18' height='18' rx='2'/%3E%3Ccircle cx='8.5' cy='8.5' r='1.75'/%3E%3Cpath d='M21 15l-5-5-4 4-3-3-5 5'/%3E%3C/svg%3E");
  }
  .st-key-nav-flow button::before {
    background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%233c4043' stroke-width='1.75' stroke-linecap='round' stroke-linejoin='round'%3E%3Crect x='9' y='2' width='6' height='5' rx='1'/%3E%3Crect x='3' y='17' width='6' height='5' rx='1'/%3E%3Crect x='15' y='17' width='6' height='5' rx='1'/%3E%3Cpath d='M12 7v3M12 10H8a2 2 0 0 0-2 2v5M12 10h4a2 2 0 0 1 2 2v5'/%3E%3C/svg%3E");
  }

  .st-key-brand, .st-key-nav-new, .st-key-nav-library, .st-key-nav-flow {
    position: relative;
    overflow: visible !important;
  }
  .st-key-brand::after, .st-key-nav-new::after, .st-key-nav-library::after, .st-key-nav-flow::after,
  .st-key-brand::before, .st-key-nav-new::before, .st-key-nav-library::before, .st-key-nav-flow::before {
    display: none;
    pointer-events: none;
  }
  .st-key-brand::after, .st-key-nav-new::after, .st-key-nav-library::after, .st-key-nav-flow::after {
    position: absolute;
    left: calc(100% + 8px);
    top: 50%;
    transform: translateY(-50%);
    z-index: 40;
    width: max-content;
    padding: 7px 10px;
    border-radius: 8px;
    background: #1f1f1f;
    color: #fff;
    font-size: 13px;
    font-weight: 400;
    line-height: 1.35;
    white-space: nowrap;
    box-shadow: 0 6px 18px rgba(32, 33, 36, .18);
  }
  .st-key-brand::before, .st-key-nav-new::before, .st-key-nav-library::before, .st-key-nav-flow::before {
    content: "";
    position: absolute;
    left: calc(100% + 2px);
    top: 50%;
    transform: translateY(-50%);
    z-index: 41;
    border: 6px solid transparent;
    border-right-color: #1f1f1f;
  }
  .st-key-brand:hover::after, .st-key-nav-new:hover::after, .st-key-nav-library:hover::after, .st-key-nav-flow:hover::after,
  .st-key-brand:hover::before, .st-key-nav-new:hover::before, .st-key-nav-library:hover::before, .st-key-nav-flow:hover::before { display: block; }
  .st-key-brand::after { content: "Back to Quick Find."; }
  .st-key-nav-new::after { content: "Clear the search and start over."; }
  .st-key-nav-library::after { content: "Browse every photo, grouped by month."; }
  .st-key-nav-flow::after { content: "See how search and the questions work."; }
  .st-key-nav-library button[kind="primary"],
  .st-key-nav-flow button[kind="primary"] {
    background: #e8eaed !important;
    color: #3c4043 !important;
  }

  /* ---------------- Photo library ---------------- */
  .library-title {
    font-size: 1.55rem;
    font-weight: 500;
    letter-spacing: -0.02em;
    color: var(--ink);
    margin: .6rem 0 1.2rem;
  }

  .nav-item {
    position: relative;
    display: flex;
    align-items: center;
    gap: 12px;
    width: 100%;
    box-sizing: border-box;
    min-height: 40px;
    height: 40px;
    padding: 0 10px;
    border-radius: 10px;
    color: #3c4043 !important;
    text-decoration: none !important;
    font-size: 17px;
    font-weight: 500;
  }
  .nav-item:hover { background: #f1f3f4; }
  .nav-ico { width: 22px; height: 22px; flex: 0 0 22px; display: flex; align-items: center; justify-content: center; color: #3c4043; }
  .nav-ico svg { width: 22px; height: 22px; display: block; }
  .nav-item .tip {
    display: none;
    position: absolute;
    left: calc(100% + 8px);
    top: 50%;
    transform: translateY(-50%);
    z-index: 40;
    width: max-content;
    max-width: 220px;
    padding: 7px 10px;
    border-radius: 8px;
    background: #1f1f1f;
    color: #fff;
    font-size: 13px;
    white-space: nowrap;
    box-shadow: 0 6px 18px rgba(32, 33, 36, .18);
  }
  .nav-item:hover .tip { display: block; }

  .side-note {
    position: fixed;
    left: 0; bottom: 0;
    width: var(--sidebar-w);
    margin: 0;
    padding: 12px 16px;
    box-sizing: border-box;
    background: #fff;
    border-right: 1px solid #eceff1;
    border-top: 1px solid #eceff1;
    font-size: 12px;
    line-height: 1.45;
    color: #80868b;
    z-index: 40;
  }

  /* ---------------- Hero ---------------- */
  /* The idle homepage (hero + search + prompts) is wrapped in this one
     container (see .st-key-idle-stage below) so the whole group can be
     centred as a unit, both horizontally and vertically in the viewport -
     not just left/right-centred text sitting near the top. */
  .st-key-idle-stage {
    display: flex !important;
    flex-direction: column !important;
    align-items: center !important;
    justify-content: center !important;
    min-height: calc(100vh - 5rem);
    width: 100%;
  }
  .hero { text-align: center; padding: 6vh 1rem 1.4rem; }
  .hero.hero-idle { padding: 0 1rem 1.8rem; }
  .hero h1 {
    font-size: 2.3rem;
    font-weight: 500;
    letter-spacing: -0.03em;
    color: #202124;
    margin: 0;
  }
  .hero.hero-compact h1 { font-size: 1.4rem; }
  .hero p {
    margin: .85rem auto 0;
    max-width: 42rem;
    color: var(--muted);
    font-size: 1.1rem;
    line-height: 1.5;
  }
  .hero.hero-compact p { display: none; }

  /* The key class lands on the vertical block itself (there is no nested
     stVerticalBlock to target), so the row/centre layout goes here. */
  .st-key-prompts {
    display: flex !important;
    flex-direction: row !important;
    flex-wrap: wrap !important;
    justify-content: center !important;
    gap: 12px !important;
  }
  .st-key-prompts [data-testid="stElementContainer"] { margin: 0 !important; width: auto !important; }
  .st-key-prompts [data-testid="stButton"] { width: fit-content !important; }
  .st-key-prompts button {
    width: auto !important;
    min-height: 0 !important;
    height: auto !important;
    font-style: italic !important;
    font-size: 16px !important;
    font-weight: 400 !important;
    color: #80868b !important;
    background: #fff !important;
    border: 1px solid #e3e6ea !important;
    border-radius: 999px !important;
    padding: 10px 18px !important;
    margin: 0 !important;
  }
  .st-key-prompts button:hover {
    color: #3c4043 !important;
    border-color: #dadce0 !important;
    background: #f8f9fa !important;
  }

  /* "Not sure" / "Show results now" (and the date question's "Apply
     range" / "Not sure") always sit in this fixed footer row, directly
     below whatever choice rows a question has - same spot every time,
     so the layout doesn't shift between a question with 2 choices and
     one with 6. */
  .st-key-question-footer {
    margin-top: .5rem;
    padding-top: .7rem;
    border-top: 1px solid var(--line);
  }
  /* Filled "secondary" treatment - a notch more prominent than the plain
     outlined choice buttons above, without competing with an actual
     primary (blue) action like "Start over". */
  .st-key-question-footer div[data-testid="stButton"] > button {
    background: #f1f3f4 !important;
    border: 1px solid #dadce0 !important;
    color: #3c4043 !important;
    font-weight: 600 !important;
  }
  .st-key-question-footer div[data-testid="stButton"] > button:hover {
    background: #e8eaed !important;
    border-color: #c4c7ca !important;
    color: #202124 !important;
  }

  /* ---------------- Toolbar ---------------- */
  .st-key-toolbar {
    background: #f8f9fa;
    border: 1px solid var(--line);
    border-radius: 14px;
    padding: .7rem .9rem .3rem;
    margin: 0 0 1.1rem;
  }
  .st-key-toolbar [data-testid="stButton"] button {
    border-radius: 999px;
    min-height: 2.4rem;
  }

  /* ---------------- Pinned search bar ---------------- */
  [data-testid="stForm"] {
    height: auto !important;
    margin: 0 !important;
    background: #fff;
    border: 1px solid #e3e6ea;
    border-radius: 999px;
    box-shadow: 0 1px 2px rgba(32, 33, 36, .06), 0 8px 20px rgba(32, 33, 36, .10);
    padding: .3rem .4rem .3rem 1.1rem;
  }
  /* Idle "New search": a Google-style search bar, centred in the normal
     page flow, sitting between the hero and the example prompts. */
  .st-key-search-center {
    margin: 1.6rem 0 1.6rem !important;
  }
  /* Streamlit stretches stLayoutWrapper to 100% of its parent, which is
     what actually holds the form - centering the outer block with flex
     has nothing to centre, since that wrapper already fills it. Capping
     and centering this wrapper itself is what moves the form. */
  .st-key-search-center [data-testid="stLayoutWrapper"] {
    max-width: 640px;
    margin: 0 auto;
  }
  .st-key-search-center [data-testid="stForm"] {
    width: 100%;
  }
  .st-key-search-center [data-testid="stForm"]:hover,
  .st-key-search-center [data-testid="stForm"]:focus-within {
    box-shadow: 0 1px 6px rgba(32, 33, 36, .12), 0 2px 10px rgba(32, 33, 36, .08);
  }
  /* ---------------- Top bar (every phase after the first search) ---------------- */
  .st-key-top-bar { margin: .1rem 0 1.6rem; }
  .st-key-top-bar [data-testid="stHorizontalBlock"] {
    align-items: center !important;
    gap: .8rem !important;
  }
  /* The query sits here, unclickable, while questions are being asked -
     shaped like a search bar so it reads as "your search", not a label. */
  .top-query-pill {
    display: flex;
    align-items: center;
    background: #f1f3f4;
    color: #3c4043;
    border: 1px solid var(--line);
    border-radius: 999px;
    padding: .7rem 1.2rem;
    font-size: .98rem;
    line-height: 1.3;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .st-key-top-bar div[data-testid="stButton"] > button {
    min-height: 2.6rem;
  }
  /* "Start over" is the one real action once a search is running, so it
     gets Streamlit's primary (filled) treatment instead of the plain
     outline every other button here uses. */
  .st-key-top-start-over button[kind="primary"] {
    background: var(--blue) !important;
    border-color: var(--blue) !important;
    color: #fff !important;
    font-weight: 600 !important;
  }
  .st-key-top-start-over button[kind="primary"]:hover {
    background: #174ea6 !important;
    border-color: #174ea6 !important;
    color: #fff !important;
  }

  /* ---------------- Answers rail (right of the conversation) ---------------- */
  .st-key-answers-rail { position: sticky; top: 1.2rem; }
  .rail-title {
    font-size: .95rem;
    font-weight: 600;
    letter-spacing: -0.01em;
    color: var(--ink);
    margin-bottom: .6rem;
  }
  .rail-empty { color: var(--muted); font-size: .84rem; line-height: 1.55; }
  .answer-tiles { display: flex; flex-direction: column; gap: .55rem; }
  .answer-tile {
    border: 1px solid var(--line);
    border-left: 3px solid var(--blue);
    border-radius: 10px;
    padding: .55rem .7rem;
    background: #fff;
    animation: tile-in .22s ease;
  }
  @keyframes tile-in {
    from { opacity: 0; transform: translateY(6px); }
    to { opacity: 1; transform: translateY(0); }
  }
  .answer-tile-label {
    font-size: .68rem;
    font-weight: 600;
    letter-spacing: .04em;
    text-transform: uppercase;
    color: #174ea6;
  }
  .answer-tile-value {
    font-size: .9rem;
    color: var(--ink);
    margin-top: .15rem;
    line-height: 1.35;
  }

  /* Quick thumbs up/down, boxed and sitting right below "Your answers"
     in the rail - not down at the bottom of the results. */
  .st-key-feedback-box {
    border: 1px solid var(--line);
    border-radius: 12px;
    padding: .9rem .9rem 1rem;
    margin-top: .9rem;
    background: #fff;
  }
  .st-key-feedback-box [data-testid="stMarkdownContainer"] p {
    font-size: .9rem;
    font-weight: 600;
    color: var(--ink);
    margin: 0 0 .6rem;
  }
  .st-key-feedback-box [data-testid="stHorizontalBlock"] { gap: .5rem !important; }
  .st-key-feedback-box div[data-testid="stButton"] button {
    font-size: 1.05rem;
    min-height: 2.3rem;
    border-radius: 999px;
  }
  .st-key-feedback-box .stCaption { margin-top: .5rem; }

  [data-testid="stForm"] [data-testid="stVerticalBlock"] {
    flex-direction: row !important;
    align-items: center !important;
    height: auto !important;
    min-height: 0 !important;
    gap: .35rem;
  }
  [data-testid="stForm"] [data-testid="stElementContainer"] { margin-bottom: 0 !important; }
  [data-testid="stForm"] [data-testid="stElementContainer"]:first-child { flex: 1 1 auto; }
  [data-testid="stForm"] [data-testid="stTextInput"] div,
  [data-testid="stForm"] [data-testid="stTextInput"] input {
    border: none !important;
    background: transparent !important;
    box-shadow: none !important;
    font-size: 18px !important;
  }
  [data-testid="stForm"] [data-testid="stFormSubmitButton"] {
    width: 48px !important;
    height: 48px !important;
    flex: 0 0 48px !important;
    display: flex !important;
    align-items: center !important;
    justify-content: center !important;
  }
  [data-testid="stForm"] [data-testid="stFormSubmitButton"] button {
    position: relative;
    width: 48px !important;
    height: 48px !important;
    min-width: 48px !important;
    min-height: 48px !important;
    padding: 0 !important;
    margin: 0 !important;
    border: none !important;
    border-radius: 50% !important;
    box-shadow: none !important;
    display: flex !important;
    align-items: center !important;
    justify-content: center !important;
    background:
      radial-gradient(circle at center, #fff 0 17px, transparent 18px),
      conic-gradient(#FBBC04 0 90deg, #EA4335 90deg 180deg, #4285F4 180deg 270deg, #34A853 270deg 360deg) !important;
  }
  [data-testid="stForm"] [data-testid="stFormSubmitButton"] button p,
  [data-testid="stForm"] [data-testid="stFormSubmitButton"] [data-testid="stIconMaterial"] { display: none !important; }
  [data-testid="stForm"] [data-testid="stFormSubmitButton"] button::after {
    content: "";
    position: absolute;
    left: 50%; top: 50%;
    width: 23px; height: 23px;
    transform: translate(-50%, -50%);
    background: center / 22px 22px no-repeat url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'%3E%3Cpath fill='%23000' stroke='%23000' stroke-width='1.35' stroke-linejoin='round' stroke-linecap='round' d='M13 19V7.83l4.88 4.88c.39.39 1.03.39 1.42 0a.996.996 0 000-1.41l-6.59-6.59a.996.996 0 00-1.41 0l-6.6 6.58a.996.996 0 101.41 1.41L11 7.83V19c0 .55.45 1 1 1s1-.45 1-1z'/%3E%3C/svg%3E");
  }

  /* ---------------- Buttons & controls elsewhere ---------------- */
  div[data-testid="stButton"] button,
  div[data-testid="stButton"] button p,
  div[data-testid="stButton"] button div {
    white-space: normal !important;
    height: auto !important;
    overflow: visible !important;
    text-overflow: clip !important;
  }
  [data-testid="stMain"] div[data-testid="stButton"] > button {
    border-radius: 999px;
    background: #fff;
    border: 1px solid var(--line);
    color: var(--ink);
    font-weight: 500;
    box-shadow: none;
    min-height: 2.4rem;
  }
  [data-testid="stMain"] div[data-testid="stButton"] > button:hover {
    background: var(--blue-soft);
    border-color: #c6dafc;
    color: #174ea6;
  }
  button[data-testid="stPopoverButton"] {
    min-height: 1.6rem;
    padding: 0.05rem 0.4rem;
    line-height: 1;
    border-radius: 999px;
  }
  button[data-testid="stPopoverButton"] [aria-hidden="true"] { display: none; }
  div[data-testid="stPopoverBody"] { max-width: 22rem; }

  /* ---------------- Photo grid ---------------- */
  div[data-testid="stImage"] img {
    aspect-ratio: 1 / 1;
    object-fit: cover;
    object-position: center;
    border-radius: 10px;
  }
  /* Each photo card. The image's own built-in fullscreen button is
     stretched to cover the whole photo and hidden, so a click anywhere
     on the photo opens it full screen - no visible button needed. A
     small "i" sits on top, in front of that invisible button, and only
     shows its details on hover. */
  [class*="st-key-photocard-"] {
    position: relative;
    border-radius: 10px;
    gap: 0 !important;
  }
  /* Lets the hover tooltip float above neighbouring photos instead of
     being clipped to this card's own box. */
  [class*="st-key-photocard-"]:hover {
    z-index: 30;
  }
  /* The extra wrapper around each photo confuses Streamlit's own
     width-to-column-width measurement for st.image, so the rendered
     width is forced here instead of relying on that. */
  [class*="st-key-photocard-"] [data-testid="stElementContainer"],
  [class*="st-key-photocard-"] [data-testid="stFullScreenFrame"],
  [class*="st-key-photocard-"] [data-testid="stImage"],
  [class*="st-key-photocard-"] [data-testid="stImageContainer"] {
    width: 100% !important;
    display: block !important;
  }
  [class*="st-key-photocard-"] [data-testid="stImage"] img {
    width: 100% !important;
    height: auto !important;
    max-width: 100% !important;
  }
  [class*="st-key-photocard-"] [data-testid="stElementToolbar"] {
    opacity: 1 !important;
    top: 0 !important;
    right: 0 !important;
    left: 0 !important;
    bottom: 0 !important;
    width: 100% !important;
    height: 100% !important;
    background: transparent !important;
    z-index: 5;
  }
  [class*="st-key-photocard-"] [data-testid="stElementToolbarButtonContainer"],
  [class*="st-key-photocard-"] [data-testid="stElementToolbarButton"],
  [class*="st-key-photocard-"] .stTooltipHoverTarget {
    width: 100% !important;
    height: 100% !important;
    display: block !important;
    background: transparent !important;
    box-shadow: none !important;
    border: none !important;
    border-radius: 0 !important;
  }
  /* Only the "open" trigger is stretched and hidden. The "Close
     fullscreen" button (shown once the photo is already expanded)
     keeps its normal small, visible, clickable corner icon. */
  [class*="st-key-photocard-"] button[data-testid="stBaseButton-elementToolbar"][aria-label="Fullscreen"] {
    width: 100% !important;
    height: 100% !important;
    opacity: 0 !important;
    background: transparent !important;
    box-shadow: none !important;
    border: none !important;
    padding: 0 !important;
    border-radius: 0 !important;
    cursor: pointer;
  }
  .photo-info {
    position: absolute;
    top: 8px;
    right: 8px;
    z-index: 20;
  }
  .photo-info-dot {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 18px;
    height: 18px;
    border-radius: 50%;
    background: rgba(32, 33, 36, .35);
    color: rgba(255, 255, 255, .9);
    font-size: 11px;
    font-weight: 700;
    font-style: italic;
    font-family: Georgia, "Times New Roman", serif;
    cursor: default;
    user-select: none;
    opacity: .65;
    transition: opacity .15s ease;
  }
  .photo-info:hover .photo-info-dot {
    opacity: 1;
  }
  .photo-info-tip {
    display: none;
    position: absolute;
    top: 26px;
    right: 0;
    z-index: 25;
    width: 230px;
    max-width: 60vw;
    padding: 10px 12px;
    border-radius: 10px;
    background: #1f1f1f;
    color: #fff;
    font-size: 12px;
    line-height: 1.5;
    text-align: left;
    box-shadow: 0 6px 18px rgba(32, 33, 36, .25);
  }
  .photo-info-tip div { margin: 2px 0; }
  .photo-info-tip b { font-weight: 600; }
  .photo-info:hover .photo-info-tip { display: block; }

  [data-testid="stMain"] h3 {
    font-size: 1.1rem !important;
    font-weight: 500 !important;
    letter-spacing: -0.01em;
    color: var(--ink) !important;
    margin: 1.4rem 0 .6rem !important;
  }

  @media (max-width: 900px) {
    [data-testid="stSidebar"] { min-width: 0; max-width: none; }
    .hero { padding-top: 3rem; }
    .hero h1 { font-size: 1.5rem; }
  }

  /* ---------------- How it works ---------------- */
  .st-key-flow-page { max-width: 1000px; margin: 0 auto; }
  .flow-hero { text-align: center; padding: .6rem 1rem 2rem; }
  .flow-hero h1 {
    font-size: 1.7rem;
    font-weight: 500;
    letter-spacing: -0.02em;
    color: #202124;
    margin: 0 0 .6rem;
  }
  .flow-hero p {
    color: var(--muted);
    font-size: 1rem;
    line-height: 1.55;
    max-width: 40rem;
    margin: 0 auto;
  }

  .flow-section { margin: 1.6rem 0 1.4rem; }
  .flow-section-eyebrow {
    font-size: .72rem;
    font-weight: 700;
    letter-spacing: .08em;
    text-transform: uppercase;
    color: var(--blue);
    margin-bottom: .35rem;
  }
  .flow-section-title {
    font-size: 1.3rem;
    font-weight: 500;
    letter-spacing: -0.01em;
    color: var(--ink);
    margin: 0 0 .45rem;
  }
  .flow-section-sub {
    color: var(--muted);
    font-size: .92rem;
    line-height: 1.55;
    max-width: 48rem;
    margin: 0 0 1.3rem;
  }

  .flow-row {
    display: flex;
    align-items: stretch;
    flex-wrap: wrap;
    gap: 0;
    margin: 0 0 2.2rem;
  }
  .flow-card {
    flex: 1 1 190px;
    min-width: 170px;
    background: #fff;
    border: 1px solid var(--line);
    border-top: 3px solid var(--accent, var(--blue));
    border-radius: 14px;
    padding: 1rem 1.1rem 1.2rem;
    display: flex;
    flex-direction: column;
    gap: .5rem;
  }
  .flow-card-icon {
    width: 36px;
    height: 36px;
    border-radius: 10px;
    background: var(--accent-soft, var(--blue-soft));
    color: var(--accent, var(--blue));
    display: flex;
    align-items: center;
    justify-content: center;
  }
  .flow-card-icon svg { width: 19px; height: 19px; }
  .flow-card-step {
    font-size: .68rem;
    font-weight: 700;
    letter-spacing: .06em;
    text-transform: uppercase;
    color: #9aa0a6;
  }
  .flow-card-title {
    font-size: .98rem;
    font-weight: 600;
    color: var(--ink);
    line-height: 1.3;
  }
  .flow-card-desc {
    font-size: .85rem;
    color: var(--muted);
    line-height: 1.5;
  }
  .flow-card-outcome {
    border-color: #cde9d4;
    background: #f5fbf6;
    box-shadow: 0 2px 12px rgba(52, 168, 83, .1);
  }

  .flow-arrow {
    flex: 0 0 34px;
    display: flex;
    align-items: center;
    justify-content: center;
    color: #c6cace;
    font-size: 1.3rem;
  }
  .flow-arrow-labelled {
    flex: 0 0 96px;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: .2rem;
    color: #9aa0a6;
    font-size: .68rem;
    line-height: 1.3;
    text-align: center;
    padding: 0 .3rem;
  }
  .flow-arrow-labelled .glyph { font-size: 1.3rem; color: #c6cace; }

  .flow-loop-note {
    display: flex;
    align-items: center;
    gap: .5rem;
    margin: .3rem 0 1.4rem;
    padding: .65rem .9rem;
    background: #f8f9fa;
    border: 1px dashed #dadce0;
    border-radius: 10px;
    color: var(--muted);
    font-size: .84rem;
    line-height: 1.5;
  }
  .flow-loop-note svg { width: 17px; height: 17px; flex: 0 0 17px; color: #80868b; }

  .flow-rules {
    display: grid;
    grid-template-columns: repeat(2, 1fr);
    gap: .8rem;
  }
  .flow-rule {
    display: flex;
    gap: .7rem;
    align-items: flex-start;
    background: #fff;
    border: 1px solid var(--line);
    border-radius: 12px;
    padding: .85rem .95rem;
  }
  .flow-rule-icon {
    flex: 0 0 28px;
    width: 28px;
    height: 28px;
    border-radius: 50%;
    background: var(--blue-soft);
    color: #174ea6;
    display: flex;
    align-items: center;
    justify-content: center;
  }
  .flow-rule-icon svg { width: 15px; height: 15px; }
  .flow-rule-title { font-weight: 600; font-size: .88rem; color: var(--ink); margin-bottom: .15rem; }
  .flow-rule-desc { font-size: .82rem; color: var(--muted); line-height: 1.5; }

  @media (max-width: 860px) {
    .flow-row { flex-direction: column; }
    .flow-arrow { transform: rotate(90deg); flex-basis: 26px; }
    .flow-arrow-labelled { flex-direction: row; justify-content: flex-start; text-align: left; }
    .flow-arrow-labelled .glyph { transform: rotate(90deg); }
    .flow-rules { grid-template-columns: 1fr; }
  }
</style>
"""


def render_sidebar():
    """Brand, New search, Photo library, a How it works placeholder, and Repository."""
    view = st.session_state.get("view", "home")
    with st.sidebar:
        if st.button("Quick Find", key="brand", width="stretch"):
            st.session_state.view = "home"
            st.rerun()
        if st.button("New search", key="nav-new", width="stretch"):
            st.session_state.view = "home"
            st.query_params["page"] = "home"
            st.session_state.do_reset = True
            st.rerun()
        if st.button(
            "Photo library",
            key="nav-library",
            type="primary" if view == "library" else "secondary",
            width="stretch",
        ):
            st.session_state.view = "library"
            st.query_params["page"] = "library"
            st.rerun()
        if st.button(
            "How it works",
            key="nav-flow",
            type="primary" if view == "flow" else "secondary",
            width="stretch",
        ):
            st.session_state.view = "flow"
            st.query_params["page"] = "flow"
            st.rerun()
        st.markdown(
            f"<a class='nav-item' href='{GITHUB_URL}' target='_blank' rel='noopener'>"
            f"<span class='nav-ico'>{ICON_REPO}</span>"
            "<span class='nav-text'>Repository</span>"
            "<span class='tip'>Open this project on GitHub.</span></a>",
            unsafe_allow_html=True,
        )
        st.markdown(
            "<div class='side-note'>Note - Everything runs in this browser "
            "session. Refreshing the page clears the current search.</div>",
            unsafe_allow_html=True,
        )


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
    """Month range from the earliest photo to the latest. Full range is the default.

    This is a single two-handle range slider (st.select_slider with a
    tuple value), so both ends live on one track instead of two separate
    sliders.

    The ``value`` argument must be passed as a 2-tuple on *every* run, not
    only the first. Streamlit's select_slider decides whether a run's
    stored widget state should be read back as a range (a tuple) or a
    single scalar by looking at whether the live Python call this run
    passed a sequence as ``value`` - it does not infer this from the
    widget's own history. Omitting ``value`` once the key already exists
    in session_state (the previous approach here) makes that check see
    ``None``, which is not a sequence, so the slider's own two-ended
    selection gets deserialized back down to just its first handle - the
    live widget still has two handles, but every rerun quietly re-sends a
    single-value default to the frontend, which is what made the second
    handle stop moving. Always rebuilding the tuple from whatever is
    already in session_state (or the full range, the first time) keeps
    both handles independently draggable across reruns.
    """
    months = library_months(photos)
    if len(months) < 2:
        for key in ("date_bounds", "date_months", "date_range"):
            st.session_state.pop(key, None)
        return
    st.session_state.date_months = months
    last_index = len(months) - 1
    st.session_state.date_bounds = (0, last_index)

    def label(index):
        return month_chip(months[index])

    current = st.session_state.get("date_range", (0, last_index))
    start_index = max(0, min(current[0], last_index))
    end_index = max(0, min(current[1], last_index))

    st.select_slider(
        "Date range",
        options=range(len(months)),
        value=(start_index, end_index),
        format_func=label,
        key="date_range",
        label_visibility="collapsed",
    )


def span_ends():
    """(start, end, full) month keys for the chosen range, or None when every photo is shown.

    This reads the *committed* indexes (date_start_index / date_end_index),
    not the live date_range slider widget directly. Streamlit
    quietly drops a widget's stored value once that widget stops being
    instantiated on later runs (which happens as soon as the date question
    is answered and show_date_slider is no longer called) - so the chosen
    range is copied into these plain, never-pruned keys the moment the
    question is answered, and that copy is what every later run reads.
    """
    bounds = st.session_state.get("date_bounds")
    months = st.session_state.get("date_months")
    start_index = st.session_state.get("date_start_index")
    end_index = st.session_state.get("date_end_index")
    if not bounds or not months or start_index is None or end_index is None:
        return None
    if start_index > end_index:
        start_index, end_index = end_index, start_index
    full = (start_index, end_index) == tuple(bounds)
    return months[start_index], months[end_index], full


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


def results_photos():
    """The photos still in play for the active search (ignores the date filter)."""
    return [photo for photo, _score in st.session_state.get("results", [])]


def date_question_pending():
    """True while the date-range question still needs to be asked.

    The slider's min/max come from the *current search's* photos, not the
    whole library, so skip entirely when those results do not span at
    least two months (show_date_slider would have nothing useful to ask).
    """
    if st.session_state.get("date_done", False):
        return False
    return len(library_months(results_photos())) >= 2


def answer_label(question_key):
    """The short name shown on a tile, e.g. 'main_subject' -> 'Mainly of'."""
    return SUMMARY_NAMES.get(question_key, question_key.replace("_", " ").title())


def log_answer(label, value):
    """Record one answered (or "Not sure"-d) question for the rail.

    Every tap is logged here, including "Not sure" - that is still useful
    context ("you weren't sure about the season"), so it stays visible
    rather than silently vanishing the way a skipped question used to.
    """
    log = list(st.session_state.get("answer_log", []))
    log.append((label, value))
    st.session_state.answer_log = log


def credit_mentioned_attributes(query):
    """Pre-fill answers for attributes the query already named (§2.1).

    mentioned_labels() is what add_label_matches already uses to widen
    the candidate pool - it maps words like "beach" to a fixed attribute
    value. Until now that detection never left search.py: the rail
    stayed empty and the result count didn't reflect it, so the next
    question could look like it was ignoring what you just typed even
    when it already knew. Crediting it here - narrowing the results and
    adding a rail tile, exactly as if it had been tapped - closes that
    gap. See docs/search_and_questions_improvement_plan.md §2.1 and §3.

    A label is only credited when the query names exactly one of its
    values; a query naming two values for the same attribute (e.g.
    "beach and cafe") is left alone rather than guessing which one.
    """
    found = mentioned_labels(query)
    if not found:
        return
    by_label = {}
    for label, value in found:
        by_label.setdefault(label, set()).add(value)

    results = st.session_state.results
    photos = [photo for photo, _score in results]
    scores = {id(photo): score for photo, score in results}
    answers = dict(st.session_state.answers)
    asked = list(st.session_state.asked)
    before_total = len(photos)

    for label in config.QUESTION_ORDER:
        values = by_label.get(label)
        if not values or len(values) != 1 or label in answers:
            continue
        value = next(iter(values))
        photos = apply_answer(photos, label, value)
        answers[label] = value
        asked.append(label)
        log_answer(answer_label(label), shown_value(label, value))

    st.session_state.results = [(photo, scores[id(photo)]) for photo in photos]
    st.session_state.answers = answers
    st.session_state.asked = asked
    after_total = len(photos)
    if after_total != before_total:
        st.session_state.last_change = change_line(before_total, after_total)


def render_answers_rail():
    """The right-hand panel: every answer (and "Not sure") given so far.

    One tile per tap, in the order the questions were asked - a running
    record of the conversation, not just a single summary line.
    """
    with st.container(key="answers-rail"):
        st.markdown("<div class='rail-title'>Your answers</div>", unsafe_allow_html=True)
        tiles = st.session_state.get("answer_log", [])
        if not tiles:
            st.markdown(
                "<div class='rail-empty'>Your answers will show up here as you "
                "respond to each question.</div>",
                unsafe_allow_html=True,
            )
            return
        cards = "".join(
            "<div class='answer-tile'>"
            f"<div class='answer-tile-label'>{html.escape(label)}</div>"
            f"<div class='answer-tile-value'>{html.escape(value)}</div>"
            "</div>"
            for label, value in tiles
        )
        st.markdown(f"<div class='answer-tiles'>{cards}</div>", unsafe_allow_html=True)


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


def photo_info_html(photo, score=None):
    """A small 'i' for the top-right corner. Hovering it shows the details."""
    key = date_key(photo)
    date_text = f"{MONTH_NAMES[key[1]]} {key[0]}" if key is not None else "Date unknown"
    attributes = photo.get("attributes") if isinstance(photo.get("attributes"), dict) else {}
    rows = [("Date", date_text)]
    rows += [(title, detail_text(field, attributes.get(field))) for field, title in DETAIL_FIELDS]
    lines = "".join(
        f"<div><b>{html.escape(title)}:</b> {html.escape(str(value))}</div>"
        for title, value in rows
    )
    description = html.escape(photo.get("description") or "Unknown")
    file_line = html.escape(photo.get("path") or "")
    score_line = f"<div><b>Score:</b> {score:.2f}</div>" if score is not None else ""
    return (
        "<div class='photo-info'>"
        "<span class='photo-info-dot'>i</span>"
        "<div class='photo-info-tip'>"
        f"{lines}"
        f"<div><b>Description:</b> {description}</div>"
        f"<div><b>File:</b> {file_line}</div>"
        f"{score_line}"
        "</div></div>"
    )


def show_photo_card(photo, score=None):
    """One photo. An info icon overlays its top-right corner on hover;
    clicking the photo itself opens it full screen (no separate button).
    """
    with st.container(key=f"photocard-{id(photo)}"):
        st.markdown(photo_info_html(photo, score), unsafe_allow_html=True)
        source = config.PHOTOS_DIR / photo["path"]
        source_mtime = source.stat().st_mtime if source.is_file() else 0
        image = thumbnail(photo["path"], source_mtime)
        if image is not None:
            st.image(image, width="stretch")


def show_grid(entries, with_score=False):
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
                show_photo_card(photo, score if with_score else None)
                if score is not None:
                    st.caption(f"{score:.2f}")


def show_date_groups(groups, unknown, with_score=False):
    for (year, month), items in groups:
        group_heading(f"{MONTH_NAMES[month]} {year}", len(items))
        show_grid(items, with_score=with_score)
    if unknown:
        group_heading("Date unknown", len(unknown))
        show_grid(unknown, with_score=with_score)


def show_timeline(photos):
    """Photos inside the date range, grouped by month and year, newest first."""
    visible = filter_photos(photos)
    groups, unknown = group_by_date(visible, lambda photo: photo)
    if not groups and not unknown:
        st.write("No photos in this date range.")
        return
    show_date_groups(groups, unknown)


def show_results(matches, sort_by):
    """Search results, best match first, or grouped by date when asked."""
    if not matches:
        st.write("No close matches found. Try describing it differently.")
        return

    st.write(f"{len(matches)} photos found")
    if sort_by == "Date":
        groups, unknown = group_by_date(matches, lambda item: item[0])
        show_date_groups(groups, unknown, with_score=True)
        return
    show_grid(matches, with_score=True)


def reset_search():
    """Clear the search, the questions, and the answers."""
    st.session_state.active_query = ""
    st.session_state.pending_query = ""
    st.session_state.results = []
    st.session_state.answers = {}
    st.session_state.asked = []
    st.session_state.questions_asked = 0
    st.session_state.not_sure_count = 0
    st.session_state.stopped = False
    st.session_state.last_change = ""
    st.session_state.show_more_for = ""
    st.session_state.phase = "idle"
    st.session_state.date_done = False
    st.session_state.answer_log = []
    st.session_state.pop("feedback", None)
    st.session_state.pop("result_sort", None)
    st.session_state.pop("date_range", None)
    st.session_state.pop("date_bounds", None)
    st.session_state.pop("date_months", None)
    st.session_state.pop("date_start_index", None)
    st.session_state.pop("date_end_index", None)
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
    st.session_state.setdefault("phase", "idle")
    st.session_state.setdefault("date_done", False)
    st.session_state.setdefault("answer_log", [])


def start_search(query):
    """Queue one search and forget any questions from the previous search.

    The actual search() call - which can take several seconds the first
    time it runs a session, since that is when it loads the embedding and
    re-ranking models - is deliberately *not* made here. Doing it here
    would run it synchronously before the next rerun, so the screen would
    sit frozen (no spinner, no feedback) for however long that takes.
    Instead this only records which query is pending; render_loading_search
    does the real work from inside a spinner, so every phase of a search -
    this one included - gives the same immediate, visible feedback.
    """
    st.session_state.active_query = query
    st.session_state.pending_query = query
    st.session_state.results = []
    st.session_state.answers = {}
    st.session_state.asked = []
    st.session_state.questions_asked = 0
    st.session_state.not_sure_count = 0
    st.session_state.stopped = False
    st.session_state.last_change = ""
    st.session_state.show_more_for = ""
    # Popped, not assigned: result_sort is also a widget key (its
    # "Sort by" segmented_control sets default="Best match"), and Streamlit
    # forbids giving a widget both a default and a directly-assigned value.
    # Removing the key lets that default take over cleanly for this search.
    st.session_state.pop("result_sort", None)
    st.session_state.date_done = False
    st.session_state.phase = "loading_search" if query else "idle"
    st.session_state.answer_log = []
    st.session_state.pop("feedback", None)
    st.session_state.pop("date_range", None)
    st.session_state.pop("date_bounds", None)
    st.session_state.pop("date_months", None)
    st.session_state.pop("date_start_index", None)
    st.session_state.pop("date_end_index", None)


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
        log_answer(answer_label(question["key"]), config.NOT_SURE_LABEL)
    elif choice == config.SHOW_NOW_LABEL:
        st.session_state.stopped = True
    else:
        answers = dict(st.session_state.answers)
        answers[question["key"]] = choice
        st.session_state.answers = answers
        log_answer(answer_label(question["key"]), shown_value(question["key"], choice))
    st.session_state.last_change = change_line(before, after)


def buttons_for(question):
    """Answers in rows, with the less common ones hidden until asked.

    "Not sure" and "Show results now" are returned separately from the
    real choices (not appended onto the end of the same list) so they can
    always be rendered on their own fixed last row - see show_question -
    instead of landing wherever the choice count happens to leave off,
    which used to shift them around from question to question.
    """
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
    return visible, always


def show_question(question):
    """Real choices in rows of four, then "Not sure" / "Show results now"
    pinned to their own fixed row underneath. Returns the tapped answer,
    or None.

    Keeping that pair on a row of their own - rather than wherever they'd
    fall inside the same grid as the real choices - means they sit in the
    same place every time, regardless of how many choices a question has.
    "More options" only reveals the rest. It is not an answer.
    """
    visible, always = buttons_for(question)

    def tap(options_row):
        columns = st.columns(len(options_row))
        for column, option in zip(columns, options_row):
            key = f"answer-{question['key']}-{option['value']}"
            if column.button(option["label"], key=key, width="stretch"):
                if option["value"] == MORE_OPTIONS:
                    st.session_state.show_more_for = question["key"]
                    st.rerun()
                return option
        return None

    for start in range(0, len(visible), COLUMNS):
        tapped = tap(visible[start : start + COLUMNS])
        if tapped is not None:
            return tapped

    if always:
        with st.container(key="question-footer"):
            tapped = tap(always)
            if tapped is not None:
                return tapped
    return None


def render_hero():
    """The idle headline, Google-homepage style. Only shown before a search starts."""
    heading = "Half-remember a photo? Just describe it."
    sub = (
        "Type whatever you recall, a place, a color, a season. "
        "We'll ask a couple of quick smart questions to narrow thousands of "
        "photos down to the one you're after."
    )
    st.markdown(
        f"<div class='hero hero-idle'><h1>{heading}</h1><p>{sub}</p></div>",
        unsafe_allow_html=True,
    )


def render_search_form(centered):
    """The search bar. Centred (Google-style) on the idle screen, otherwise
    pinned to the bottom of the viewport so a new search is always reachable.

    Enter inside the box submits the form, same as the Search button.
    A new form key on Start over clears the box. A form keeps its own text.
    """
    search_round = st.session_state.get("search_round", 0)
    wrapper_key = "search-center" if centered else "search-pinned"
    with st.container(key=wrapper_key):
        with st.form(f"search-{search_round}"):
            search_text = st.text_input(
                "Search text",
                label_visibility="collapsed",
                placeholder="Describe the photo you're looking for\u2026",
            )
            submitted = st.form_submit_button("Search")
    return submitted, search_text


def render_top_bar():
    """The row above every phase once a search is running.

    The typed search sits here as a plain, unclickable pill for the whole
    conversation - including once results are shown, so attention stays on
    "Start over" rather than inviting another edit mid-flow. That button
    is the one real action here, so it gets the primary (filled) style.
    """
    query = st.session_state.get("active_query", "")
    with st.container(key="top-bar"):
        bar_column, reset_column = st.columns([5, 1])
        with bar_column:
            st.markdown(
                f"<div class='top-query-pill'>{html.escape(query)}</div>",
                unsafe_allow_html=True,
            )
        with reset_column:
            start_over = st.button(
                "Start over", key="top-start-over", type="primary", width="stretch"
            )

    if start_over:
        st.session_state.do_reset = True
        st.rerun()


def render_prompts():
    """Example half-remembered descriptions. Tapping one runs that search."""
    with st.container(key="prompts"):
        for i, example in enumerate(EXAMPLE_PROMPTS):
            if st.button(example, key=f"prompt-{i}"):
                start_search(clean_text(example))
                st.rerun()


def render_date_question():
    """The date range, asked like any other narrowing question.

    The slider's min and max come from the photos in the *current*
    search results (not the whole library), so dragging either end
    always narrows a range that actually matches this search.

    Two buttons: "Apply range" keeps whatever the slider is set to,
    "Not sure" resets it to the full range (no date filtering at all).
    """
    with st.container(key="question-card"):
        st.markdown(
            "<p class='question-card-text'>Roughly when was this taken?</p>",
            unsafe_allow_html=True,
        )
        show_date_slider(results_photos())
        # Same fixed footer row as every attribute question (show_question)
        # uses for "Not sure" / "Show results now" - so the two actions
        # always land in the same place, question to question.
        with st.container(key="question-footer"):
            apply_column, skip_column = st.columns(2)
            with apply_column:
                apply_clicked = st.button("Apply range", key="date-apply", width="stretch")
            with skip_column:
                skip_clicked = st.button(config.NOT_SURE_LABEL, key="date-skip", width="stretch")
    if not (apply_clicked or skip_clicked):
        return
    before = len(st.session_state.results)
    st.session_state.date_done = True
    months = st.session_state.get("date_months") or []
    last_index = len(months) - 1 if months else 0
    if skip_clicked:
        start_index, end_index = 0, last_index
    else:
        start_index, end_index = st.session_state.get("date_range", (0, last_index))
    # Commit into plain keys (see span_ends) rather than writing back to
    # the date_range widget itself - both because Streamlit
    # forbids reassigning a widget's value after it has rendered this run,
    # and because those widget keys will be pruned once this question is
    # no longer shown.
    st.session_state.date_start_index = start_index
    st.session_state.date_end_index = end_index
    # "Apply range" always logs a tile - even when the slider was left at
    # its full default span - since the user still made a deliberate
    # choice there, distinct from "Not sure". Only "Not sure" skips
    # straight to the full range without a user-picked one to show.
    if skip_clicked:
        log_answer("Dates", config.NOT_SURE_LABEL)
    else:
        log_answer("Dates", f"{month_chip(months[start_index])} \u2013 {month_chip(months[end_index])}")
    after = len(filter_matches(st.session_state.results))
    st.session_state.last_change = change_line(before, after)
    st.session_state.loading_message = "Finding more ways to narrow your search\u2026"
    st.session_state.phase = "loading_next"
    st.rerun()


def render_attribute_question(photos):
    """The next attribute question, or move on to the results if none remain."""
    query = st.session_state.get("active_query", "")
    visible = filter_matches(st.session_state.results)
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
    if question is None:
        st.session_state.phase = "loading_results"
        st.rerun()
        return
    with st.container(key="question-card"):
        st.markdown(
            f"<p class='question-card-text'>{html.escape(question['text'])}</p>",
            unsafe_allow_html=True,
        )
        tapped = show_question(question)
    if tapped is not None:
        apply_tap(question, tapped["value"])
        st.session_state.loading_message = "Finding more ways to narrow your search\u2026"
        st.session_state.phase = "loading_next"
        st.rerun()


def render_asking(photos):
    """Exactly one question at a time: the date range first, then attributes.

    Earlier answers now live in the rail on the right (render_answers_rail),
    not repeated here - this column only ever shows the current question.
    """
    # This line is filled only inside apply_tap / render_date_question, so it
    # stays hidden until the first tap.
    if st.session_state.last_change:
        st.write(st.session_state.last_change)

    if date_question_pending():
        render_date_question()
        return
    render_attribute_question(photos)


def render_loading(message, seconds):
    """A short, deliberate pause with a spinner message."""
    with st.spinner(message):
        time.sleep(seconds)


def render_loading_search():
    """Run the real search() call inside a spinner.

    This is the one loading phase that does genuine work rather than a
    deliberate pause - the first search of a session also loads the
    embedding and re-ranking models, which can take several seconds. That
    cost is real either way; the point of this phase is only to make sure
    it always happens behind a spinner instead of a frozen screen.
    """
    query = st.session_state.get("pending_query", "")
    with st.spinner("Searching your library\u2026"):
        st.session_state.results = search(query) if query else []
    if query:
        credit_mentioned_attributes(query)
    st.session_state.phase = "loading_questions"
    st.rerun()


def render_loading_questions():
    render_loading("Intelligently curating questions to refine your search\u2026", 1.5)
    st.session_state.phase = "asking"
    st.rerun()


def render_loading_next(photos):
    message = st.session_state.get(
        "loading_message", "Finding more ways to narrow your search\u2026"
    )
    render_loading(message, 1.2)
    if date_question_pending():
        st.session_state.phase = "asking"
        st.rerun()
        return
    query = st.session_state.get("active_query", "")
    visible = filter_matches(st.session_state.results)
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
    st.session_state.phase = "asking" if question is not None else "loading_results"
    st.rerun()


def render_loading_results():
    render_loading("Curating your best matches\u2026", 1.5)
    st.session_state.phase = "results"
    st.rerun()


def log_feedback(verdict):
    """Append one query + its answers + the tapped verdict to a CSV log.

    §2.7: feedback used to only show a toast and vanish. This is the
    data that would eventually turn "looks right in a few test queries"
    into "measured against real usage" - same spirit as the existing
    data/test_results.csv, just one row per real search instead of per
    saved test case.
    """
    FEEDBACK_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    is_new = not FEEDBACK_LOG_PATH.exists()
    with FEEDBACK_LOG_PATH.open("a", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FEEDBACK_LOG_FIELDS)
        if is_new:
            writer.writeheader()
        writer.writerow(
            {
                "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "query": st.session_state.get("active_query", ""),
                "answers": summary_line(st.session_state.get("answers", {})),
                "result_count": len(st.session_state.get("results", [])),
                "verdict": verdict,
            }
        )


def render_feedback():
    """Single-click thumbs up / thumbs down, logged to FEEDBACK_LOG_PATH.

    Lives in a bordered box in the rail, right below "Your answers" -
    not at the bottom of the results, so it's visible without scrolling.
    """
    with st.container(key="feedback-box"):
        st.write("Was this helpful?")
        up_column, down_column = st.columns(2)
        with up_column:
            if st.button("\U0001F44D", key="feedback-up", width="stretch"):
                st.session_state.feedback = "up"
                log_feedback("up")
                st.toast("Thanks for the feedback!")
        with down_column:
            if st.button("\U0001F44E", key="feedback-down", width="stretch"):
                st.session_state.feedback = "down"
                log_feedback("down")
                st.toast("Thanks for the feedback!")
        # Checked after both buttons, so the caption appears on the very
        # same run as the click that set it (not only on the next rerun).
        if st.session_state.get("feedback"):
            st.caption("Feedback recorded, thank you.")


def render_results_phase(photos):
    """Final results: sort control, then the photos.

    The answers that got here are listed in the rail on the right (along
    with the thumbs up/down feedback box, right below them), "Start over"
    lives in the top bar, and each photo's details already show on hover
    over its "i" icon - so there is nothing else to toggle here.
    """
    results = st.session_state.results
    visible = filter_matches(results)
    if results and not visible:
        st.write("No photos in this date range.")
        return

    sort_by = st.segmented_control(
        "Sort by",
        ["Best match", "Date"],
        default="Best match",
        key="result_sort",
        width="content",
    )
    show_results(visible, sort_by)


def flow_card(step, title, desc, icon, accent, outcome=False):
    """One box in a how-it-works flow: a step number, an icon, a title, a line of text."""
    classes = "flow-card flow-card-outcome" if outcome else "flow-card"
    style = "" if outcome else f" style='--accent:{accent[0]};--accent-soft:{accent[1]}'"
    step_html = f"<div class='flow-card-step'>{html.escape(step)}</div>" if step else ""
    return (
        f"<div class='{classes}'{style}>"
        f"<div class='flow-card-icon'>{icon}</div>"
        f"{step_html}"
        f"<div class='flow-card-title'>{html.escape(title)}</div>"
        f"<div class='flow-card-desc'>{html.escape(desc)}</div>"
        "</div>"
    )


def flow_arrow():
    return "<div class='flow-arrow'>&#8594;</div>"


def flow_arrow_labelled(text):
    return (
        "<div class='flow-arrow-labelled'>"
        "<span class='glyph'>&#8594;</span>"
        f"<span>{html.escape(text)}</span>"
        "</div>"
    )


# The four Google colours, each paired with a pale tint for a card's icon chip.
_BLUE = ("#4285F4", "#e8f0fe")
_RED = ("#EA4335", "#fce8e6")
_YELLOW = ("#FBBC04", "#fef7e0")
_GREEN = ("#34A853", "#e6f4ea")


def render_how_it_works():
    """A plain-English walkthrough of the two flows behind this app:
    getting photos ready to search (once), and answering a search (every time).
    """
    with st.container(key="flow-page"):
        _render_how_it_works_body()


def _render_how_it_works_body():
    st.markdown(
        "<div class='flow-hero'>"
        "<h1>How Quick Find works</h1>"
        "<p>No magic, just a few clear steps. Photos are read and labelled once, "
        "ahead of time. Every search then compares meaning, not just words, and asks "
        "at most a couple of quick questions when there is still too much to show you.</p>"
        "</div>",
        unsafe_allow_html=True,
    )

    # ---- Section 1: one-time setup ----
    st.markdown(
        "<div class='flow-section'>"
        "<div class='flow-section-eyebrow'>Happens once, ahead of time</div>"
        "<div class='flow-section-title'>Teaching the app about your photos</div>"
        "<div class='flow-section-sub'>Before anyone can search, every photo in the "
        "library is looked at and described. This only has to happen once per photo.</div>"
        "</div>",
        unsafe_allow_html=True,
    )
    setup_cards = [
        ("Step 1", "An AI reads each photo", "It writes a short description, plus simple details such as who's in it, where it is, and what season it looks like.", ICON_EYE, _BLUE),
        ("Step 2", "The details are saved", "The description and details are stored right next to the photo, like a label only the app can read.", ICON_TAG, _RED),
        ("Step 3", "It's turned into numbers", "Each description becomes an \u201cembedding\u201d, a list of numbers that captures its meaning rather than its exact words.", ICON_GRID, _YELLOW),
        ("Step 4", "The library is ready", "Once every photo has its numbers saved, the whole library can be searched instantly.", ICON_CHECK, _GREEN),
    ]
    row = ["<div class='flow-row'>"]
    for index, (step, title, desc, icon, accent) in enumerate(setup_cards):
        if index:
            row.append(flow_arrow())
        row.append(flow_card(step, title, desc, icon, accent))
    row.append("</div>")
    st.markdown("".join(row), unsafe_allow_html=True)

    # ---- Section 2: a search begins ----
    st.markdown(
        "<div class='flow-section'>"
        "<div class='flow-section-eyebrow'>Happens every time you search</div>"
        "<div class='flow-section-title'>Finding the photo you described</div>"
        "<div class='flow-section-sub'>A half-remembered sentence is enough. The app "
        "looks for the closest meaning first, then double-checks the top candidates.</div>"
        "</div>",
        unsafe_allow_html=True,
    )
    search_cards = [
        ("Step 1", "You describe it", "Type whatever you remember, even if it's vague, like \u201ca birthday cake with string lights, maybe last winter\u201d.", ICON_PENCIL, _BLUE),
        ("Step 2", "Meaning is compared", "Your words are turned into the same kind of numbers, then compared against every photo to find the closest meanings.", ICON_SEARCH, _RED),
        ("Step 3", "Top matches are double-checked", "A second, more careful model re-reads the closest candidates against your exact words and re-orders them.", ICON_LAYERS, _YELLOW),
        ("Step 4", "A shortlist comes back", "The best-matching photos are lined up, ready to be narrowed further if there are still a lot of them.", ICON_PHOTO, _GREEN),
    ]
    row = ["<div class='flow-row'>"]
    for index, (step, title, desc, icon, accent) in enumerate(search_cards):
        if index:
            row.append(flow_arrow())
        row.append(flow_card(step, title, desc, icon, accent))
    row.append("</div>")
    st.markdown("".join(row), unsafe_allow_html=True)

    # ---- Section 3: the narrowing loop ----
    st.markdown(
        "<div class='flow-section'>"
        "<div class='flow-section-eyebrow'>Only when there's still a lot to choose from</div>"
        "<div class='flow-section-title'>Narrowing it down together</div>"
        "<div class='flow-section-sub'>Instead of dumping every match on screen, the "
        "app asks one simple question at a time and narrows the list with each tap.</div>"
        "</div>",
        unsafe_allow_html=True,
    )
    loop_cards = [
        ("", "Roughly when?", "First, a date range: drag a slider over the months your photo could be from.", ICON_CALENDAR, _BLUE),
        ("", "One quick question", "Then a single tap question, such as \u201cWhere was it?\u201d or \u201cWho was in the photo?\u201d.", ICON_MESSAGE, _RED),
        ("", "You tap an answer", "Matching photos stay, the rest drop out, instantly, or you can tap \u201cNot sure\u201d to skip it.", ICON_POINTER, _YELLOW),
    ]
    row = ["<div class='flow-row'>"]
    for index, (step, title, desc, icon, accent) in enumerate(loop_cards):
        if index:
            row.append(flow_arrow())
        row.append(flow_card(step, title, desc, icon, accent))
    row.append(flow_arrow_labelled("repeats up to 3 times"))
    row.append(
        flow_card(
            "",
            "Your best matches",
            "Once only a handful of photos remain, enough questions are answered, or you say \u201cNot sure\u201d too often, the search stops and shows the results.",
            ICON_PHOTO,
            _GREEN,
            outcome=True,
        )
    )
    row.append("</div>")
    st.markdown("".join(row), unsafe_allow_html=True)
    st.markdown(
        "<div class='flow-loop-note'>"
        f"{ICON_REPEAT}"
        "<span>Every tap narrows a live list, so the question and photo count you see "
        "always reflect everything you've answered so far, not the full library.</span>"
        "</div>",
        unsafe_allow_html=True,
    )

    # ---- Section 4: what makes a question worth asking ----
    st.markdown(
        "<div class='flow-section'>"
        "<div class='flow-section-eyebrow'>Behind the scenes</div>"
        "<div class='flow-section-title'>What makes a question worth asking</div>"
        "<div class='flow-section-sub'>A question is only shown when answering it would "
        "actually help. Four simple rules keep things short and relevant.</div>"
        "</div>",
        unsafe_allow_html=True,
    )
    rules = [
        (ICON_SKIP, "Never repeats itself", "A question already answered, or already covered by your search text, is never asked again."),
        (ICON_GRID, "Skips questions that won't help", "If almost every remaining photo already shares one answer, or no answer would actually shrink the list, that question is left out."),
        (ICON_CHECK, "Stays relevant to earlier answers", "Clothing colour is only asked when most remaining photos show people, and a specific month is only asked after a year has been chosen."),
        (ICON_STOP, "Knows when to stop", "Asking stops once only a couple of photos remain, three questions have been asked, or \u201cNot sure\u201d has been tapped twice."),
    ]
    tiles = ["<div class='flow-rules'>"]
    for icon, title, desc in rules:
        tiles.append(
            "<div class='flow-rule'>"
            f"<div class='flow-rule-icon'>{icon}</div>"
            "<div>"
            f"<div class='flow-rule-title'>{html.escape(title)}</div>"
            f"<div class='flow-rule-desc'>{html.escape(desc)}</div>"
            "</div></div>"
        )
    tiles.append("</div>")
    st.markdown("".join(tiles), unsafe_allow_html=True)


def render_library(photos):
    """Every photo, grouped by month, newest first. No search, no filters."""
    st.markdown("<div class='library-title'>Photo library</div>", unsafe_allow_html=True)
    groups, unknown = group_by_date(photos or [], lambda photo: photo)
    if not groups and not unknown:
        st.write("No photos yet.")
        return
    show_date_groups(groups, unknown)


def main():
    st.set_page_config(page_title="Quick Find", page_icon="🔍", layout="wide")
    st.markdown(PAGE_STYLE, unsafe_allow_html=True)
    # A fresh browser tab has no session state yet, but the URL's "page"
    # query param survives a refresh, so that is what decides the section.
    st.session_state.setdefault("view", st.query_params.get("page", "home"))
    render_sidebar()

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

    if st.session_state.view == "library":
        render_library(photos)
        return

    if st.session_state.view == "flow":
        render_how_it_works()
        return

    remember_question_state()

    phase = st.session_state.phase

    if phase == "idle":
        # Google-homepage style: hero, the search bar, then the example
        # prompts, all centred - both horizontally and vertically in the
        # viewport, like a real homepage - nothing else on screen yet.
        with st.container(key="idle-stage"):
            render_hero()
            submitted, search_text = render_search_form(centered=True)
            render_prompts()
        if submitted:
            cleaned = clean_text(search_text)
            if cleaned:
                start_search(cleaned)
                st.rerun()
        return

    # Every other phase: the conversation (or the results) on the left,
    # a running record of the answers given so far on the right - the
    # same idea as a references rail, just for this app's own questions.
    main_column, rail_column = st.columns([2.3, 1], gap="large")
    with main_column:
        render_top_bar()
        if phase == "loading_search":
            render_loading_search()
        elif phase == "loading_questions":
            render_loading_questions()
        elif phase == "asking":
            render_asking(photos or [])
        elif phase == "loading_next":
            render_loading_next(photos or [])
        elif phase == "loading_results":
            render_loading_results()
        else:
            render_results_phase(photos or [])
    with rail_column:
        render_answers_rail()
        # Thumbs up/down only makes sense once results are on screen, so
        # it only joins the rail in that final phase - right below the
        # list of answers, boxed, same as the "expected" mock.
        if phase not in (
            "loading_search", "loading_questions", "asking",
            "loading_next", "loading_results",
        ):
            render_feedback()


if __name__ == "__main__":
    main()
