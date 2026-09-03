from __future__ import annotations

import json
import math
from pathlib import Path
import random
import sys
import tempfile
import unittest
import zipfile

WINDOWS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WINDOWS_DIR))

from domain.dictation import (
    DictationField, DictationFormat, DictationOptions,
    DictationDraft, dictation_range_ids, nearest_dictation_id,
    blank_count, build_document, cloze_example, parse_meaning, word_prompt,
)
from domain.models import ExampleSentence, VocabularyEntry
from infrastructure.dictation_exporter import DictationDocumentExporter


def entry(word="conduct"):
    return VocabularyEntry.create(
        word, "n. 行为, conduct v. 指挥, 进行",
        [ExampleSentence("They conduct the test.", "他们进行测试。"),
         ExampleSentence("Her conduct was professional.", "她的行为很专业。"),
         ExampleSentence("The guide conducts tours.", "导游带领游览。")],
        level="CET4", tags=("gk",),
    )


class DictationDomainTests(unittest.TestCase):
    def test_range_selection_is_inclusive_and_stable(self):
        entries = [entry("Canada"), entry("apple"), entry("banana"), entry("dear")]
        self.assertEqual(
            dictation_range_ids(entries, "banana", "apple"),
            frozenset({"apple", "banana"}),
        )
        self.assertEqual(dictation_range_ids(entries, "missing", "apple"), frozenset())

    def test_nearest_selected_id_prefers_earlier_tie(self):
        entries = [entry("a"), entry("b"), entry("c"), entry("d")]
        self.assertEqual(nearest_dictation_id(entries, "c", {"b", "d"}), "b")

    def test_draft_round_trip_is_versioned(self):
        draft = DictationDraft(
            mode="random", scope_group="cet4", count=3,
            selected_ids=("apple", "banana"),
            group_selected_ids={"cet4": ("apple", "banana")},
            group_anchors={"cet4": "apple"},
            group_endpoints={"cet4": "banana"},
            group_scroll_positions={"cet4": 0.25},
            expanded_groups=("cet4",),
        )
        restored = DictationDraft.from_dict(draft.to_dict())
        self.assertEqual(restored, draft)
        self.assertIsNone(DictationDraft.from_dict({"version": 999}))
    def test_blank_count_and_first_code_point(self):
        self.assertEqual(blank_count("abcd"), 8)
        self.assertEqual(word_prompt("😀ab"), "______")
        self.assertEqual(word_prompt("😀ab", True), "😀 ____")
        self.assertEqual(word_prompt("abcd", False), "________")

    def test_options_are_a4_and_bounded(self):
        self.assertEqual(DictationOptions().font_size_pt, 12)
        with self.assertRaises(ValueError):
            DictationOptions(font_size_pt=7)
        with self.assertRaises(ValueError):
            DictationOptions(paper_width_pt=600)

    def test_parse_pos_and_cloze_whole_words(self):
        self.assertEqual(parse_meaning("n. 行为, v. 进行 adj. 有关"), ("n / v / adj", "行为, 进行 有关"))
        self.assertEqual(cloze_example("Conduct conduct conducts re-conducted.", "conduct"),
                         "_____________ _____________ conducts re-conducted.")

    def test_custom_examples_override_and_fields_are_hidden(self):
        options = DictationOptions(
            missing_fields=frozenset({DictationField.WORD, DictationField.PART_OF_SPEECH}),
            include_examples=True,
            custom_examples={"conduct": "Conduct this review."},
        )
        document = build_document([entry()], options)
        row = document.rows[0]
        self.assertEqual(row.part_of_speech, "_________")
        self.assertEqual(row.word, "_____________")
        self.assertEqual(row.examples, ("_____________ this review.",))

    def test_include_example_chinese_appends_translation(self):
        options = DictationOptions(
            missing_fields=frozenset({DictationField.WORD}),
            include_examples=True,
            include_example_chinese=True,
        )
        document = build_document([entry()], options)
        row = document.rows[0]
        self.assertEqual(row.examples, ("They _____________ the test.",))
        self.assertEqual(row.example_chinese, ("他们进行测试。",))

    def test_include_example_chinese_off_is_empty(self):
        options = DictationOptions(
            missing_fields=frozenset({DictationField.WORD}),
            include_examples=True,
            include_example_chinese=False,
        )
        document = build_document([entry()], options)
        row = document.rows[0]
        self.assertEqual(row.examples, ("They _____________ the test.",))
        self.assertEqual(row.example_chinese, ())

    def test_shared_golden_vectors(self):
        root = json.loads((WINDOWS_DIR.parent / "shared/contracts/dictation-export-golden-v1.json").read_text(encoding="utf-8"))
        for vector in root["blankVectors"]:
            with self.subTest(vector=vector["name"]):
                if vector.get("showFirstLetter"):
                    self.assertEqual(word_prompt(vector["text"], True), vector["rendered"])
                else:
                    self.assertEqual(blank_count(vector["text"]), vector["blankCount"])
                self.assertEqual(word_prompt(vector["text"], vector.get("showFirstLetter", False)), vector["rendered"])
        for vector in root["partOfSpeechVectors"]:
            with self.subTest(vector=vector["name"]):
                self.assertEqual(parse_meaning(vector["meaningInput"]), (vector["partOfSpeech"], vector["meaning"]))
        for vector in root["exampleBoundaryVectors"]:
            with self.subTest(vector=vector["name"]):
                self.assertEqual(cloze_example(vector["englishInput"], vector["word"], vector.get("showFirstLetter", False)), vector["englishOutput"])
        example_chinese = root.get("exampleChineseVector", {})
        if example_chinese:
            self.assertEqual(
                example_chinese["renderedExampleLine"],
                "e.g. We _________ quickly.（我们很快适应。）",
            )

    def test_docx_and_pdf_are_openable_a4_and_contain_content(self):
        exporter = DictationDocumentExporter()
        options = DictationOptions(formats={DictationFormat.PDF})
        pdf = exporter.export(build_document([entry()], options), DictationFormat.PDF)
        self.assertEqual(pdf.mime_type, "application/pdf")
        self.assertTrue(pdf.bytes.startswith(b"%PDF"))
        self.assertIn(b"/MediaBox [ 0 0 595.2756 841.8898 ]", pdf.bytes)

        docx_options = DictationOptions(formats={DictationFormat.DOCX}, include_examples=True)
        docx = exporter.export(build_document([entry()], docx_options), DictationFormat.DOCX)
        self.assertEqual(docx.mime_type, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        with zipfile.ZipFile(__import__("io").BytesIO(docx.bytes)) as archive:
            xml = archive.read("word/document.xml")
            self.assertIn("conduct".encode(), xml)
            self.assertIn(b"e.g. They", xml)
            self.assertIn(b"11906", archive.read("word/document.xml"))

    def test_empty_document_is_rejected(self):
        exporter = DictationDocumentExporter()
        with self.assertRaises(ValueError):
            exporter.export(build_document([], DictationOptions()), DictationFormat.PDF)


class DictationLoadingTests(unittest.TestCase):
    def test_delay_is_random_one_to_two_seconds_in_100ms_steps(self):
        from presentation.app import dictation_loading_delay_ms

        rng = random.Random(20260828)
        seen = {dictation_loading_delay_ms(rng) for _ in range(500)}
        for value in seen:
            self.assertGreaterEqual(value, 1000)
            self.assertLessEqual(value, 2000)
            self.assertEqual(value % 100, 0)
        self.assertGreater(len(seen), 1)

    def test_book_turning_frame_sweeps_from_right_page_to_left_page(self):
        from presentation.widgets import (
            BOOK_TURNING_FRAMES_PER_PAGE,
            BOOK_TURNING_TICK_MS,
            book_turning_frame,
            book_turning_progress,
        )

        right = book_turning_frame(0.0, 56)
        edge_on = book_turning_frame(0.5, 56)
        left = book_turning_frame(1.0, 56)

        self.assertGreater(right.edge_x, right.spine_x)
        self.assertAlmostEqual(edge_on.edge_x, edge_on.spine_x)
        self.assertGreater(edge_on.lift, right.lift)
        self.assertLess(left.edge_x, left.spine_x)
        self.assertAlmostEqual(right.edge_x - right.spine_x, left.spine_x - left.edge_x)
        page_progress = [
            book_turning_progress(frame_index)
            for frame_index in range(BOOK_TURNING_FRAMES_PER_PAGE)
        ]
        self.assertEqual(page_progress[0], 0.0)
        self.assertEqual(page_progress[-1], 1.0)
        self.assertTrue(all(left < right for left, right in zip(page_progress, page_progress[1:])))
        self.assertEqual(book_turning_progress(BOOK_TURNING_FRAMES_PER_PAGE), 0.0)
        self.assertLessEqual(BOOK_TURNING_FRAMES_PER_PAGE * BOOK_TURNING_TICK_MS, 1000)

    def test_book_turning_frame_clamps_progress_and_stays_inside_canvas(self):
        from presentation.widgets import book_turning_frame

        before = book_turning_frame(-5.0, 56)
        after = book_turning_frame(5.0, 56)

        self.assertEqual(before.progress, 0.0)
        self.assertEqual(after.progress, 1.0)
        for frame in (before, after):
            self.assertLessEqual(frame.left, frame.edge_x)
            self.assertLessEqual(frame.edge_x, frame.right)
            self.assertLess(frame.top, frame.bottom)

    def test_loading_overlay_draws_a_moving_page_without_tk_display(self):
        from presentation.widgets import BOOK_TURNING_FRAMES_PER_PAGE, DictationLoadingOverlay

        class RecordingCanvas:
            def __init__(self):
                self.polygons = []

            def delete(self, *_args, **_kwargs):
                self.polygons.clear()

            def create_rectangle(self, *_args, **_kwargs):
                return None

            def create_line(self, *_args, **_kwargs):
                return None

            def create_polygon(self, *coords, **_kwargs):
                self.polygons.append(coords)

        overlay = object.__new__(DictationLoadingOverlay)
        overlay._spinner = RecordingCanvas()
        overlay._size = 56
        overlay._surface = "#FFFFFF"
        overlay._border = "#DDE3E8"
        overlay._accent = "#16866F"

        overlay._draw(BOOK_TURNING_FRAMES_PER_PAGE - 1)
        finishing_page = overlay._spinner.polygons[-1]
        overlay._draw(BOOK_TURNING_FRAMES_PER_PAGE)
        next_page = overlay._spinner.polygons[-1]

        self.assertNotEqual(finishing_page, next_page)
        self.assertLess(finishing_page[2], finishing_page[0])
        self.assertGreater(next_page[2], next_page[0])
        self.assertGreaterEqual(len(overlay._spinner.polygons), 1)


if __name__ == "__main__":
    unittest.main()
