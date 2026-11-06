import unittest

from kahoot_core import KahootError, extract_uuid, parse_quiz, quiz_as_text

UUID = "fba5cd05-96af-4506-b8ce-388ff9b33fbb"


def quiz_with(*questions):
    return parse_quiz({"kahoot": {"uuid": UUID, "title": "T", "questions": list(questions)}})


class ExtractUuid(unittest.TestCase):
    def test_accepts_known_link_shapes(self):
        for link in (
            f"https://create.kahoot.it/details/some-quiz/{UUID}",
            f"https://play.kahoot.it/v2/?quizId={UUID}",
            f"  {UUID.upper()}\n",
        ):
            self.assertEqual(extract_uuid(link), UUID)

    def test_game_pin_is_explained(self):
        with self.assertRaisesRegex(KahootError, "PIN"):
            extract_uuid("1234567")

    def test_rejects_empty_and_garbage(self):
        for link in ("", "   ", "https://example.com/quiz"):
            with self.assertRaises(KahootError):
                extract_uuid(link)


class ParseQuestions(unittest.TestCase):
    def test_quiz_keeps_only_correct_answers(self):
        q = quiz_with({
            "type": "quiz",
            "question": "<b>Tom &amp; Jerry?</b>",
            "choices": [{"answer": "a", "correct": False}, {"answer": "b", "correct": True}],
        }).questions[0]
        self.assertEqual(q.text, "Tom & Jerry?")
        self.assertEqual(q.answers, ["b"])
        self.assertEqual(q.wrong, ["a"])

    def test_jumble_uses_list_order_and_ignores_flags(self):
        q = quiz_with({
            "type": "jumble",
            "question": "q",
            "choices": [{"answer": "GA", "correct": False}, {"answer": "UC", "correct": True}],
        }).questions[0]
        self.assertEqual(q.answers, ["1. GA", "2. UC"])

    def test_survey_has_no_correct_answers(self):
        q = quiz_with({
            "type": "survey",
            "question": "q",
            "choices": [{"answer": "a", "correct": True}],
        }).questions[0]
        self.assertEqual(q.answers, [])
        self.assertIn("Brak poprawnej", q.note)

    def test_slider_reads_choice_range(self):
        q = quiz_with({
            "type": "slider",
            "question": "q",
            "choiceRange": {"start": 10.0, "end": 999.0, "correct": 336.0, "tolerance": 0.1},
        }).questions[0]
        self.assertEqual(q.answers, ["336"])
        self.assertIn("0.1", q.note)

    def test_image_only_answer_is_not_blank(self):
        q = quiz_with({
            "type": "quiz",
            "question": "q",
            "choices": [{"image": "https://media.kahoot.it/x", "correct": True}],
        }).questions[0]
        self.assertEqual(q.answers, ["[obrazek] https://media.kahoot.it/x"])

    def test_unknown_type_with_no_choices_does_not_crash(self):
        q = quiz_with({"type": "future_type", "question": "q"}).questions[0]
        self.assertEqual(q.answers, [])
        self.assertTrue(q.note)

    def test_content_slides_are_skipped_in_numbering(self):
        quiz = quiz_with(
            {"type": "content", "title": "Przerwa"},
            {"type": "quiz", "question": "q", "choices": []},
        )
        self.assertEqual([q.number for q in quiz.questions], [1])

    def test_missing_questions_raises(self):
        with self.assertRaises(KahootError):
            parse_quiz({})

    def test_text_export_lists_answers(self):
        quiz = quiz_with({
            "type": "quiz",
            "question": "q",
            "choices": [{"answer": "b", "correct": True}],
        })
        self.assertIn("-> b", quiz_as_text(quiz))


if __name__ == "__main__":
    unittest.main()
