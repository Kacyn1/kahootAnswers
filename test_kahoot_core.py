import unittest

from kahoot_core import (
    KahootError,
    clean,
    extract_uuid,
    fetch_image_bytes,
    parse_quiz,
    quiz_as_text,
)

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


class CleanText(unittest.TestCase):
    def test_html_scripts_become_unicode(self):
        self.assertEqual(clean("H<sub>0</sub>: R<sup>2</sup> &gt; 0"), "H₀: R² > 0")

    def test_script_without_unicode_form_stays_readable(self):
        self.assertEqual(clean("x<sub>b,c</sub>"), "x_(b,c)")

    def test_plain_comparison_is_not_mistaken_for_a_tag(self):
        self.assertEqual(clean("x<y oraz z>3"), "x<y oraz z>3")
        self.assertEqual(clean("p < 0.05 i t > 2"), "p < 0.05 i t > 2")

    def test_break_tags_separate_words(self):
        self.assertEqual(clean("a<br>b"), "a b")

    def test_regression_formula(self):
        self.assertEqual(
            clean(r"<latex>\hat{y}=\beta_0+\beta_1x+\epsilon</latex>"),
            "y\u0302=β₀+β₁x+ε",
        )

    def test_accent_keeps_subscript(self):
        self.assertEqual(clean(r"<latex>\hat{\beta_1}</latex>"), "β\u0302₁")

    def test_multi_letter_accent_is_spelled_out(self):
        self.assertEqual(clean(r"<latex>\bar{xy}</latex>"), "bar(xy)")

    def test_fractions(self):
        self.assertEqual(clean(r"<latex>\frac{5}{8}</latex>"), "5/8")
        self.assertEqual(clean(r"<latex>\frac{a+b}{c}</latex>"), "(a+b)/c")
        self.assertEqual(clean(r"<latex>\frac{\sigma^2}{n}</latex>"), "σ²/n")

    def test_nested_fraction_and_root(self):
        self.assertEqual(
            clean(r"<latex>\sqrt{\frac{1}{n-1}}</latex>"), "√(1/(n-1))"
        )
        self.assertEqual(clean(r"<latex>\sqrt[3]{x}</latex>"), "³√(x)")

    def test_comparison_inside_latex_survives(self):
        self.assertEqual(clean("<latex>H_A:p&lt;0.60</latex>"), "H_A:p<0.60")
        self.assertEqual(clean("<latex>a<b</latex> i <latex>c>d</latex>"), "a<b i c>d")

    def test_transpose_and_inequalities(self):
        self.assertEqual(clean(r"<latex>X^\top X</latex>"), "Xᵀ X")
        self.assertEqual(clean(r"<latex>R_i^2\ge 0.9</latex>"), "Rᵢ²≥ 0.9")

    def test_delimiters_and_functions(self):
        self.assertEqual(clean(r"<latex>\left(\ln x\right)</latex>"), "(ln x)")
        self.assertEqual(clean(r"<latex>\sum_{i=1}^{n}x_i</latex>"), "∑ᵢ₌₁ⁿxᵢ")

    def test_mixed_number_keeps_whole_part_separate(self):
        self.assertEqual(clean(r"<latex>3\frac{1}{2}</latex>"), "3 1/2")

    def test_fraction_next_to_a_variable_is_bracketed(self):
        self.assertEqual(clean(r"<latex>y=\frac{1}{2}x-4</latex>"), "y=(1/2)x-4")
        self.assertEqual(clean(r"<latex>a\frac{1}{2}</latex>"), "a(1/2)")
        self.assertEqual(clean(r"<latex>\frac{1}{2}\beta</latex>"), "(1/2)β")

    def test_fraction_inside_brackets_is_not_doubled(self):
        self.assertEqual(clean(r"<latex>\left(\frac{1}{2}\right)</latex>"), "(1/2)")

    def test_encoded_break_tag_is_removed(self):
        self.assertEqual(clean("Co to GCF? &lt;br&gt;"), "Co to GCF?")

    def test_malformed_latex_does_not_crash(self):
        for source in (r"\frac{1", "}{", "^", "_", "\\", r"\sqrt[", r"\hat", "{{{"):
            clean(f"<latex>{source}</latex>")


class Images(unittest.TestCase):
    def test_crop_target_is_a_size(self):
        q = quiz_with({
            "type": "quiz",
            "question": "q",
            "image": "https://media.kahoot.it/x",
            "imageMetadata": {
                "width": 1000, "height": 500,
                "crop": {"origin": {"x": 100, "y": 50}, "target": {"x": 600, "y": 400}},
            },
            "choices": [],
        }).questions[0]
        self.assertEqual(q.image_crop, (0.1, 0.1, 0.7, 0.9))

    def test_missing_crop(self):
        q = quiz_with({
            "type": "quiz", "question": "q", "image": "https://x/y", "choices": [],
        }).questions[0]
        self.assertIsNone(q.image_crop)

    def test_non_https_image_is_refused(self):
        with self.assertRaises(ValueError):
            fetch_image_bytes("file:///C:/Windows/win.ini")


class FixedFailures(unittest.TestCase):
    def test_quiz_id_wins_over_host_id(self):
        other = "00000000-1111-2222-3333-444444444444"
        link = f"https://play.kahoot.it/v2/?hostId={other}&quizId={UUID}"
        self.assertEqual(extract_uuid(link), UUID)

    def test_unknown_type_is_not_shown_as_correct(self):
        q = quiz_with({
            "type": "future_poll",
            "question": "q",
            "choices": [{"answer": "a", "correct": True}, {"answer": "b", "correct": True}],
        }).questions[0]
        self.assertEqual(q.answers, [])
        self.assertIn("Nieznany typ", q.note)
        self.assertIn("a, b", q.note)

    def test_slider_with_empty_value(self):
        q = quiz_with({
            "type": "slider", "question": "q", "choiceRange": {"correct": None},
        }).questions[0]
        self.assertEqual(q.answers, [])
        self.assertTrue(q.note)


if __name__ == "__main__":
    unittest.main()
