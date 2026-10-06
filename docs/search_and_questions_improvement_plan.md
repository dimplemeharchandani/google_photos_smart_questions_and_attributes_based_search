# Search & Question-Quality Improvement Plan

Status: §2.1-§2.5, §2.7, §2.8 implemented on `backend-optimisations`.
§2.6 (richer vision prompt) intentionally skipped - it needs a Gemini
API key and a ~12-minute re-run across the whole library, which is a
cost/time call for whoever has that key, not something to do silently.
Scope: `search.py`, `questions.py`, `config.py`, `app.py`, `analyze_photos.py`.
Library size at time of writing: 102 photos. All numbers below are measured
against the current `data/` snapshot and `tests/test_queries.csv`
(baseline: **11/17 passing**), not estimated.

---

## 1. Why this doc exists

Two threads led here:

1. A backend review of `search.py` / `questions.py` looking for ways to improve
   match quality and question quality, done by running the existing test
   suite and probing specific failures with real numbers.
2. A concrete live bug report: searching **"beach and book"** still asks
   *"What was the photo mainly of?"* with "Nature or scenery" as an option,
   even though "beach" was already typed. Investigated below in §3 — it
   turned out to point at the same root cause as the top item from the
   backend review (§2.1), so the two threads converge into one plan.

---

## 2. Findings, in priority order

### 2.1 Query-mentioned attributes are detected, then thrown away ⭐ highest leverage

`search.py` already has `mentioned_labels(text)`, which maps query words to
attribute values via `config.LABEL_SYNONYMS` (e.g. "beach" → `location_type:
beach`). Today this is used **only** to widen the first-stage candidate pool
(`add_label_matches`). It never reaches `questions.py`, never becomes a
pre-filled answer, and never appears in the answers rail.

Effect: the app silently "forgets" what you typed as soon as the result list
is built. Every clarifying question *looks* like it's ignoring your query,
even on the (common) occasions where that question is still genuinely useful
for a different attribute. See §3 for the full walkthrough with real numbers.

- **Impact:** High — this is a trust/communication problem on effectively
  every search that names a recognizable attribute value (location, time of
  day, setting, etc.), not just an edge case.
- **Effort:** Low–Medium. The detection already exists; the work is wiring
  it into `start_search` (pre-fill `st.session_state.answers`), `asked`, and
  the rail, plus deciding how to log it (`log_answer`) so it reads naturally
  ("Where: Beach" vs. a tap-shaped entry).
- **Risk:** Needs care around `clothing_colour`, which already has its own
  bespoke check (`search_mentions_colour`) for a *different* purpose (skip
  the question entirely) — the two mechanisms should be unified, not
  duplicated.

### 2.2 One fixed re-ranker floor produces both false-empties and false-positives

`RERANK_MIN_SCORE = -4.0` is a single global cutoff applied to every query
regardless of vocabulary.

- **"girl in white frock" → 0 results.** The correct photo (`beach3.jpg`)
  ranked #2 in the first stage (similarity 0.52) and was the *top*
  re-ranked candidate, but its raw score (-5.23) sat under the floor by 1.2.
  The cross-encoder just doesn't parse "frock" well; a good match is
  discarded outright.
- **"penguin" (expected: nothing) → wrongly returns a dog photo.** Its score
  (-3.92) squeaked inside the same floor by only 0.08.
- A single absolute threshold can't serve both cases — it needs to be
  relative to the query's own score distribution (e.g. a margin-above-floor
  check, or a percentile-based cutoff) rather than one hardcoded number.
- **Impact:** High — directly flips both a real FAIL and a real false
  positive in the existing test set.
- **Effort:** Low–Medium. Pure logic/tuning in `search.py`; no
  reprocessing. Needs a few calibration passes against
  `tests/test_queries.csv` so fixing one case doesn't regress another.

### 2.3 No synonym expansion on the free-text side

`LABEL_SYNONYMS` only normalizes words *into* fixed attribute values for
recall. There's no equivalent for casual/regional vocabulary feeding the
embedding + re-ranker directly ("frock" never becomes "dress" before
scoring). A small hand-curated expansion map, applied in `search()` before
embedding, would fix the "frock" case without needing to touch the vision
pipeline at all.

- **Impact:** High for affected queries, cheap to extend over time.
- **Effort:** Low.

### 2.4 Smarter question ordering (ask what narrows most, not what's first)

`next_question` walks the fixed `QUESTION_ORDER` and returns the first
question that would narrow the results at all — not the one that would
narrow them the *most*. With `MAX_QUESTIONS = 3`, a question that only
weakly splits the current set (see §2.5) can use up a budget slot that a
more decisive question would have spent better.

- **Impact:** Medium–High, compounds with §2.5.
- **Effort:** Medium. `_option_counts` / `_choice_narrows` already provide
  what's needed to score candidate questions by narrowing power — the
  change is picking the max-scoring eligible question instead of the first.
  **Touches `tests/test_questions.py`:** some existing tests assert a fixed
  first-question (e.g. "main_subject asked first when useful") that are
  themselves written around the fixed-order assumption and would need
  rewriting, not just the implementation.

### 2.5 Low-signal questions get asked anyway (e.g. `season`)

Distribution pulled from `data/photos.json`:

```
season: {'summer': 44, 'winter': 7, 'unknown': 51}
```

`_skip_reason`'s "already agree" check (`SKIP_QUESTION_IF_SHARE = 0.9`) only
looks at whether one value dominates the *options* — it doesn't check
whether the dataset even has enough *known* values to make the question
worthwhile. With half the library "unknown" (which just rejoins every
answer per `apply_answer`'s unknown-passthrough rule), `season` often gets
asked for a weak payoff.

- **Impact:** Medium — frees up question budget for more decisive questions.
- **Effort:** Low. Add a "known-value share" check in `_skip_reason`.

### 2.6 "man with white beard" → 0 results (data/prompt gap, not a logic bug)

The expected photo (`beach2.jpg`) has rich `everyday_words` (old man,
elderly man, cap, walking stick, barefoot…) but never mentions "beard" —
`analyze_photos.py`'s prompt asks for general-words-only people descriptions
and doesn't explicitly request distinguishing physical features.

- **Impact:** Medium.
- **Effort:** Medium. The prompt fix is a one-liner, but requires re-running
  `analyze_photos.py` against the Gemini API for all 102 photos (~7s pacing
  between calls ⇒ roughly 12 minutes + API cost) and rebuilding embeddings.

### 2.7 Feedback is collected but goes nowhere

`render_feedback` only shows a thank-you toast; 👍/👎 and the triggering
query/answers aren't logged anywhere. This is the data that would turn every
item above from "looks right in a few test queries" into "measured against
real usage."

- **Impact:** Medium, compounding over time.
- **Effort:** Low. Append query + answers + verdict to a log file, same
  shape as the existing `data/test_results.csv`.

### 2.8 Minor / lower priority

- **`RERANK_TOP_N = 30`** is a static first-stage cutoff — fine at 102
  photos, worth revisiting if the library grows. Trivial to bump, cheap to
  test (+0.2–0.3s at this scale).
- **Numeric warnings** (`divide by zero / overflow / invalid value in
  matmul`) fire on every search. Results aren't NaN today, but it's an
  unexplained BLAS/Accelerate quirk worth root-causing for robustness.

---

## 3. The "beach and book" walkthrough (measured)

```
query = "beach and book"
mentioned_labels(query)        → [('location_type', 'beach')]
search(query)                  → 31 photos
next_question(...)             → key = "main_subject"
  options: people (22), nature or scenery (19), building or place (3),
           food or drinks (3), vehicle (3), animal (2), object (2)

location_type among the 31 results: beach (28), cafe or restaurant (2),
                                     nature or park (1)
```

Two separate things are true at once:

1. **"beach" was already understood** (`mentioned_labels` detected it,
   28/31 results already are `location_type: beach`) — but nothing in the
   UI reflects that, so the next question *feels* like it ignored you.
2. **`main_subject` is still a legitimate question.** I simulated crediting
   `location_type: beach` as a pre-filled answer before asking anything, and
   `main_subject` is *still* the next question Streamlit would pick — the
   people/scenery split just narrows slightly (21 vs. 17 instead of 22 vs.
   19). A beach photo can genuinely be mainly about people *or* mainly about
   scenery; location and subject are different axes, and the system isn't
   wrong to ask about both.

**Conclusion: §2.1 (credit query-mentioned attributes) is the fix for this
case** — not because it changes which question gets asked next, but because
it closes the gap between "what the system actually knows" and "what the
user can see it knows." Concretely, after the fix, the moment you search
"beach and book" the answers rail would already show **"Where: Beach"**,
the result count would already read 28 instead of 31, and the later
`location_type` question (which today might or might not auto-skip,
depending on how dominant the location is) would never be asked again. The
`main_subject` question would still appear — correctly, since it's asking
about something you haven't told it yet.

---

## 4. Suggested rollout order

| Phase | Items | Why this grouping |
|---|---|---|
| 1 | §2.1 credit query-mentioned attributes, §2.7 log feedback | Zero reprocessing, immediate UX win, and starts generating the data needed to validate everything after it |
| 2 | §2.3 query-side synonym expansion, §2.2 relative re-ranker floor | Both are calibration-sensitive; validate together against `tests/test_queries.csv` so a fix to one case doesn't quietly break another |
| 3 | §2.5 skip low-signal questions (e.g. `season`) | Small, low-risk, independent |
| 4 | §2.4 narrowing-aware question ordering | Larger change; touches `tests/test_questions.py` assertions that assume fixed ordering — do this once the above are stable |
| 5 | §2.6 richer vision prompt (physical features) | Needs a ~12-minute Gemini re-run across all 102 photos plus an embeddings rebuild; batch this separately from pure-logic changes |
| — | §2.8 `RERANK_TOP_N`, numeric warnings | Opportunistic, no dependency on anything else |

## 5. Open questions before implementing

- For §2.1: when a query mentions an attribute, should it be a *hard*
  pre-filled answer (narrows results immediately, shown in the rail as if
  tapped) or a *soft* hint (shown in the rail, but the question can still be
  asked again if the user wants to override it)? This changes both the UX
  and how aggressively it should narrow results.
- For §2.2: is a small number of regressions acceptable while recalibrating
  the floor, as long as net pass rate improves? (`tests/test_queries.csv`
  only has 17 rows — worth growing this set before and after, to be
  confident.)
- For §2.6: are we comfortable re-running the vision model (API cost +
  ~12 minutes) on the full library for a prompt tweak, or should this wait
  until there's a batch of prompt improvements worth doing together?
