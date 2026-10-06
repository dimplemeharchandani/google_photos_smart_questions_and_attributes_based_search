"""Checks for the tap questions. Uses small made-up photo lists, not the library."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import config
from questions import apply_answer, next_question, search_mentions_colour, summary_line


def photo(index, **fields):
    """One made-up photo. Date fields sit on the photo. Other labels sit in attributes."""
    record = {"id": index, "attributes": {}}
    for key, value in fields.items():
        if key in ("capture_year", "capture_month", "path"):
            record[key] = value
        else:
            record["attributes"][key] = value
    return record


def fill(count, **fields):
    return [photo(index, **fields) for index in range(count)]


class QuestionTests(unittest.TestCase):
    def test_no_question_when_two_or_fewer_photos_remain(self):
        photos = [
            photo(0, main_subject=["people"]),
            photo(1, main_subject=["animal"]),
        ]
        self.assertIsNone(next_question(photos, "somewhere", {}))

    def test_main_subject_is_asked_first_when_useful(self):
        photos = []
        for index in range(6):
            photos.append(
                photo(
                    index,
                    main_subject=["people"] if index % 2 == 0 else ["food or drinks"],
                    location_type="beach" if index % 2 == 0 else "home",
                    people_count="one" if index % 2 == 0 else "two",
                )
            )
        question = next_question(photos, "a photo", {})
        self.assertEqual(question["key"], "main_subject")
        self.assertEqual(question["text"], "What was the photo mainly of?")

    def test_other_subjects_skip_people_and_colour_questions(self):
        photos = []
        for index in range(8):
            subject = "food or drinks" if index < 4 else "animal"
            photos.append(
                photo(
                    index,
                    main_subject=[subject],
                    location_type="home" if index % 2 == 0 else "beach",
                    people_count="one" if index % 2 == 0 else "two",
                    clothing_colour=["red"] if index % 2 == 0 else ["blue"],
                    time_of_day="day" if index % 2 == 0 else "night",
                )
            )
        for choice in ("food or drinks", "animal"):
            kept = apply_answer(photos, "main_subject", choice)
            question = next_question(kept, "a photo", {"main_subject": choice})
            self.assertIsNotNone(question)
            self.assertNotIn(question["key"], ("people_count", "clothing_colour"))
            self.assertEqual(question["key"], "location_type")

        people = []
        for index in range(6):
            people.append(
                photo(
                    index,
                    main_subject=["people"],
                    location_type="beach",
                    people_count="one" if index % 2 == 0 else "two",
                    clothing_colour=["red"] if index % 2 == 0 else ["blue"],
                    time_of_day="day" if index % 2 == 0 else "night",
                )
            )
        still_asks_who = next_question(people, "a photo", {"main_subject": "people"})
        self.assertEqual(still_asks_who["key"], "people_count")

        no_people = next_question(
            people,
            "a photo",
            {"main_subject": "people", "people_count": "none"},
        )
        self.assertEqual(no_people["key"], "time_of_day")

    def test_no_people_is_an_option_for_people_count(self):
        photos = []
        for index in range(6):
            photos.append(
                photo(
                    index,
                    main_subject=["people"],
                    location_type="beach",
                    people_count="none" if index < 2 else "one",
                    clothing_colour=["blue"],
                )
            )
        question = next_question(photos, "a photo", {})
        self.assertEqual(question["key"], "people_count")
        values = [option["value"] for option in question["options"]]
        labels = [option["label"] for option in question["options"]]
        self.assertIn("none", values)
        self.assertIn("No people (2)", labels)

    def test_questions_continue_until_two_or_fewer(self):
        photos = [
            photo(0, main_subject=["people"]),
            photo(1, main_subject=["animal"]),
            photo(2, main_subject=["food or drinks"]),
        ]
        question = next_question(photos, "a photo", {})
        self.assertEqual(question["key"], "main_subject")
        self.assertGreater(len(photos), 2)
        self.assertIsNone(next_question(photos[:2], "a photo", {}))

    def test_question_skipped_when_95_percent_share_one_value(self):
        photos = []
        for index in range(20):
            photos.append(
                photo(
                    index,
                    location_type="home" if index == 0 else "beach",
                    people_count="one" if index < 10 else "two",
                )
            )
        question = next_question(photos, "a day out", {})
        self.assertIsNotNone(question)
        self.assertEqual(question["key"], "people_count")
        self.assertNotEqual(question["key"], "location_type")

    def test_not_sure_keeps_all_photos(self):
        photos = [
            photo(1, location_type="beach"),
            photo(2, location_type="home"),
            photo(3, location_type="unknown"),
        ]
        kept = apply_answer(photos, "location_type", config.NOT_SURE_LABEL)
        self.assertEqual([item["id"] for item in kept], [1, 2, 3])

    def test_capture_month_is_never_asked_before_a_year(self):
        photos = []
        for index in range(12):
            photos.append(
                photo(
                    index,
                    location_type="beach",
                    people_count="one",
                    clothing_colour=["blue"],
                    time_of_day="day",
                    setting="outdoor",
                    season="summer",
                    capture_year=2019 if index < 6 else 2020,
                    capture_month=1 if index % 2 == 0 else 8,
                )
            )
        question = next_question(photos, "a beach day", {})
        self.assertEqual(question["key"], "capture_year")

        blocked = next_question(
            photos,
            "a beach day",
            {},
            asked=["capture_year"],
        )
        self.assertTrue(blocked is None or blocked["key"] != "capture_month")

        opened = next_question(photos, "a beach day", {"capture_year": 2020})
        self.assertEqual(opened["key"], "capture_month")
        group_names = {option["value"] for option in opened["options"]}
        self.assertIn(config.CAPTURE_MONTH_GROUPS[0], group_names)
        self.assertIn(config.CAPTURE_MONTH_GROUPS[2], group_names)
        self.assertNotIn(config.CAPTURE_MONTH_GROUPS[1], group_names)

    def test_colour_question_skipped_when_photos_have_no_people(self):
        photos = []
        for index in range(12):
            photos.append(
                photo(
                    index,
                    location_type="beach",
                    people_count="none",
                    clothing_colour=["red"] if index % 2 == 0 else ["blue"],
                    time_of_day="day" if index % 2 == 0 else "night",
                )
            )
        question = next_question(photos, "a quiet place", {})
        self.assertEqual(question["key"], "time_of_day")

    def test_colour_question_skipped_when_the_search_mentions_a_colour(self):
        photos = []
        for index in range(12):
            photos.append(
                photo(
                    index,
                    location_type="beach",
                    people_count="one",
                    clothing_colour=["red"] if index < 6 else ["blue"],
                    time_of_day="day" if index % 2 == 0 else "night",
                )
            )
        self.assertTrue(search_mentions_colour("a red coat"))
        self.assertFalse(search_mentions_colour("required reading"))
        skipped = next_question(photos, "a red coat", {})
        self.assertEqual(skipped["key"], "time_of_day")
        asked = next_question(photos, "a coat", {})
        self.assertEqual(asked["key"], "clothing_colour")

    def test_options_are_counts_from_the_current_photos(self):
        photos = fill(6, location_type="beach")
        photos.extend(fill(5, location_type="home"))
        for index, item in enumerate(photos):
            item["id"] = index
        photos.extend(
            photo(100 + index, location_type="unknown")
            for index in range(3)
        )
        question = next_question(photos, "outside", {})
        labels = [option["label"] for option in question["options"]]
        values = [option["value"] for option in question["options"]]
        self.assertEqual(labels[0], "Beach (6)")
        self.assertEqual(labels[1], "Home (5)")
        self.assertNotIn("unknown", values)
        self.assertNotIn("none", values)
        self.assertEqual(labels[-2], config.NOT_SURE_LABEL)
        self.assertEqual(labels[-1], config.SHOW_NOW_LABEL)
        self.assertEqual(
            summary_line({"location_type": "beach", "people_count": "small group"}),
            "Where: Beach · Who: A small group",
        )

    def test_exact_matches_stay_ahead_of_unknown(self):
        photos = [
            photo(1, location_type="home"),
            photo(2, location_type="beach"),
            photo(3, location_type="unknown"),
            photo(4, location_type="beach"),
        ]
        kept = apply_answer(photos, "location_type", "beach")
        self.assertEqual([item["id"] for item in kept], [2, 4, 3])

        coloured = [
            photo(1, clothing_colour=["red"]),
            photo(2, clothing_colour=["blue"]),
            photo(3, clothing_colour=["unknown"]),
            photo(4, clothing_colour=["none"]),
            photo(5, clothing_colour=["blue", "white"]),
        ]
        kept_colours = apply_answer(coloured, "clothing_colour", "blue")
        self.assertEqual([item["id"] for item in kept_colours], [2, 5, 3])

    def test_most_narrowing_question_is_asked_even_if_later_in_order(self):
        """A lopsided split (location_type) should lose to an even one
        (people_count) even though location_type comes first in
        QUESTION_ORDER - see §2.4."""
        photos = []
        for index in range(10):
            photos.append(
                photo(
                    index,
                    main_subject=["people"],
                    location_type="beach" if index < 9 else "home",
                    people_count="one" if index < 5 else "two",
                )
            )
        question = next_question(photos, "a photo", {})
        self.assertEqual(question["key"], "people_count")

    def test_question_skipped_when_most_photos_have_no_known_value(self):
        """A question almost nobody can answer (season, in the real
        library) should be skipped even when its known photos split
        evenly - see §2.5."""
        photos = []
        for index in range(20):
            photos.append(
                photo(
                    index,
                    location_type="beach" if index % 2 == 0 else "home",
                    season="summer" if index < 3 else ("winter" if index < 6 else "unknown"),
                )
            )
        question = next_question(photos, "a photo", {})
        self.assertEqual(question["key"], "location_type")

        few_unknowns = [
            photo(index, season="summer" if index % 2 == 0 else "winter")
            for index in range(20)
        ]
        still_asked = next_question(few_unknowns, "a photo", {})
        self.assertEqual(still_asked["key"], "season")

    def test_stop_after_question_limits(self):
        photos = []
        for index in range(12):
            photos.append(
                photo(
                    index,
                    location_type="beach" if index % 2 == 0 else "home",
                    people_count="one" if index % 2 == 0 else "two",
                )
            )
        self.assertIsNone(
            next_question(photos, "a day", {}, questions_asked=config.MAX_QUESTIONS)
        )
        self.assertIsNone(
            next_question(photos, "a day", {}, not_sure_count=config.MAX_NOT_SURE)
        )
        self.assertIsNone(next_question(photos, "a day", {}, stopped=True))


if __name__ == "__main__":
    unittest.main()
