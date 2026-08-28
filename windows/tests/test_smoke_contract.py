from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

WINDOWS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WINDOWS_DIR))

from domain.dictation import DictationDocument, DictationOptions, DictationRow
from domain.models import VocabularyEntry
from presentation.app import (
    DICTATION_CHECKBOX_FONT,
    DICTATION_CHECKBOX_PAD_Y,
    DICTATION_MEANING_COLUMN_WIDTH,
    DICTATION_SELECTION_COLUMN_WIDTH,
    LexiTrackApp,
    RED,
    dictation_candidate_display,
    dictation_preview_blocks,
    scroll_contract_ready,
    visible_dictation_selection,
)


class SmokeContractTests(unittest.TestCase):
    def test_dictation_table_layout_constants_keep_columns_scrollable(self):
        self.assertEqual(DICTATION_MEANING_COLUMN_WIDTH, 260)
        self.assertEqual(DICTATION_SELECTION_COLUMN_WIDTH, 76)
        self.assertEqual(DICTATION_CHECKBOX_FONT[1], 16)
        self.assertGreater(DICTATION_CHECKBOX_PAD_Y, 0)

    def test_dictation_download_uses_each_selected_path_and_marks_after_success(self):
        with tempfile.TemporaryDirectory() as directory:
            first_path = str(Path(directory) / "worksheet.docx")
            second_path = str(Path(directory) / "worksheet.pdf")
            output_a = type("Output", (), {"file_name": "worksheet.docx", "bytes": b"docx"})()
            output_b = type("Output", (), {"file_name": "worksheet.pdf", "bytes": b"pdf"})()
            service = Mock()
            service.export_dictation.return_value = [output_a, output_b]
            app = object.__new__(LexiTrackApp)
            app.dictation_document = object()
            app.service = service
            app._apply_dictation_mark = Mock()

            with patch("presentation.app.filedialog.asksaveasfilename", side_effect=[first_path, second_path]) as save_dialog, \
                 patch("presentation.app.messagebox.showinfo") as show_info:
                LexiTrackApp.download_dictation(app)

            self.assertEqual(Path(first_path).read_bytes(), b"docx")
            self.assertEqual(Path(second_path).read_bytes(), b"pdf")
            self.assertEqual(save_dialog.call_count, 2)
            app._apply_dictation_mark.assert_called_once_with()
            show_info.assert_called_once_with("下载完成", "已保存 2 个文件。", parent=app)

    def test_dictation_download_entry_uses_download_semantics(self):
        self.assertTrue(callable(getattr(LexiTrackApp, "download_dictation", None)))

    def test_overflow_requires_effective_wheel_scroll(self):
        self.assertTrue(scroll_contract_ready(True, True, [0.0, 0.5], [0.1, 0.6]))
        self.assertFalse(scroll_contract_ready(True, False, [0.0, 0.5], [0.0, 0.5]))

    def test_fully_visible_content_does_not_require_scroll(self):
        self.assertTrue(scroll_contract_ready(False, False, [0.0, 1.0], [0.0, 1.0]))
        self.assertFalse(scroll_contract_ready(False, False, [], []))

    def test_dictation_candidate_display_separates_tags_and_evaluation(self):
        evaluated = VocabularyEntry.create(
            "conduct",
            "n. 行为\nv. 指挥, 进行",
            [],
            tags=("ZK", "evaluated", "gk", "EVALUATED"),
        )
        display = dictation_candidate_display(evaluated)

        self.assertEqual(display.word, "conduct")
        self.assertEqual(display.meaning, "n. 行为 v. 指挥, 进行")
        self.assertEqual(display.tags, "gk / zk")
        self.assertEqual(display.evaluation_status, "已考察")
        self.assertEqual(display.evaluation_color, "#000000")

        unevaluated = dictation_candidate_display(
            VocabularyEntry.create("focus", "专注", [], tags=()),
        )
        self.assertEqual(unevaluated.tags, "-")
        self.assertEqual(unevaluated.evaluation_status, "未考察")
        self.assertEqual(unevaluated.evaluation_color, RED)

    def test_dictation_selection_refresh_only_removes_hidden_ids(self):
        visible = [
            VocabularyEntry.create("alpha", "甲", []),
            VocabularyEntry.create("gamma", "丙", []),
        ]

        self.assertEqual(
            visible_dictation_selection({"alpha", "beta", "gamma"}, visible),
            {"alpha", "gamma"},
        )

    def test_dictation_preview_text_comes_directly_from_document_rows(self):
        document = DictationDocument(
            rows=(
                DictationRow("conduct", "v", "指挥, 进行", ("They _______ the test.",)),
                DictationRow("focus", "n / v", "焦点; 专注", ()),
            ),
            options=DictationOptions(),
        )

        self.assertEqual(
            dictation_preview_blocks(document),
            [
                "1. conduct    v    指挥, 进行\n    e.g. They _______ the test.",
                "2. focus    n / v    焦点; 专注",
            ],
        )


if __name__ == "__main__":
    unittest.main()
