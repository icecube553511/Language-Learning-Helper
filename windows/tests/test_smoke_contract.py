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
    DictationGroupNavigation,
    LexiTrackApp,
    RED,
    close_dictation_group,
    dictation_candidate_display,
    dictation_preview_blocks,
    dictation_preview_scroll_units,
    dictation_render_range,
    distribute_dictation_columns,
    open_dictation_group,
    scroll_contract_ready,
    set_dictation_group_mode,
    visible_dictation_selection,
)
from presentation.widgets import popup_position_with_escape_corridor


class SmokeContractTests(unittest.TestCase):
    def test_random_dictation_group_opens_read_only_scope_then_switches_to_manual(self):
        state = open_dictation_group(DictationGroupNavigation(), "cet4")

        self.assertEqual(state.mode, "random")
        self.assertEqual(state.scope_group, "cet4")
        self.assertEqual(state.open_group, "cet4")

        state = set_dictation_group_mode(state, "manual")
        self.assertEqual(state.mode, "manual")
        self.assertEqual(state.scope_group, "cet4")
        self.assertEqual(state.open_group, "cet4")

        state = close_dictation_group(state)
        self.assertIsNone(state.open_group)
        self.assertEqual(state.scope_group, "cet4")

    def test_switching_an_open_manual_group_to_random_uses_that_group_as_scope(self):
        manual = DictationGroupNavigation(
            mode="manual",
            scope_group="all",
            open_group="custom",
        )

        random_state = set_dictation_group_mode(manual, "random")

        self.assertEqual(random_state.mode, "random")
        self.assertEqual(random_state.scope_group, "custom")
        self.assertEqual(random_state.open_group, "custom")

    def test_word_bubble_keeps_a_pet_escape_corridor_on_small_screens(self):
        position = popup_position_with_escape_corridor(
            default_x=192,
            default_y=56,
            popup_width=640,
            popup_height=708,
            screen_width=1024,
            screen_height=768,
            host_bounds=(172, 4, 680, 760),
            pet_half_size=56,
        )
        self.assertNotEqual(position, (192, 56))
        popup_x, popup_y = position
        host_corners = ((228, 60), (796, 60), (228, 708), (796, 708))
        self.assertTrue(any(
            x + 56 <= popup_x
            or x - 56 >= popup_x + 640
            or y + 56 <= popup_y
            or y - 56 >= popup_y + 708
            for x, y in host_corners
        ))

    def test_dictation_table_layout_constants_keep_columns_scrollable(self):
        self.assertEqual(DICTATION_MEANING_COLUMN_WIDTH, 260)
        self.assertEqual(DICTATION_SELECTION_COLUMN_WIDTH, 76)
        self.assertEqual(DICTATION_CHECKBOX_FONT[1], 16)
        self.assertGreater(DICTATION_CHECKBOX_PAD_Y, 0)

    def test_dictation_columns_grow_to_fill_the_viewport(self):
        # Narrow viewport keeps the content minimums (still horizontally
        # scrollable), while a wide viewport stretches the flexible columns.
        narrow = distribute_dictation_columns(170, 260, 200, 640)
        self.assertEqual(narrow, (170, 260, 200))

        wide = distribute_dictation_columns(170, 260, 200, 1400)
        self.assertGreater(sum(wide) + 120 + DICTATION_SELECTION_COLUMN_WIDTH, 1100)
        self.assertGreater(wide[1], DICTATION_MEANING_COLUMN_WIDTH)
        self.assertGreater(wide[0], 170)
        self.assertGreater(wide[2], 200)

    def test_dictation_render_range_only_covers_viewport_plus_buffer(self):
        # 2000 uniform rows of 56px; a small viewport must only need a band.
        row_heights = [56] * 2000
        row_tops = [index * 56 for index in range(2000)]
        start, end = dictation_render_range(row_tops, row_heights, 1000, 1180, buffer=20)
        # Visible rows ~ 18..21; with ±20 buffer it must stay far below 2000.
        self.assertGreaterEqual(start, 0)
        self.assertLessEqual(end, 1999)
        self.assertLess(end - start, 80)
        self.assertLess(start, 22)
        self.assertGreater(end, 38)

    def test_dictation_preview_scroll_units_scale_with_delta(self):
        # Windows wheel delta is typically ±120 per notch; a block/delta of
        # multiple notches scrolls farther so large wheels stay responsive.
        self.assertEqual(dictation_preview_scroll_units(0), (0, 0))
        self.assertEqual(dictation_preview_scroll_units(120), (-1, 1))
        self.assertEqual(dictation_preview_scroll_units(-120), (1, 1))
        self.assertEqual(dictation_preview_scroll_units(240), (-1, 2))
        self.assertEqual(dictation_preview_scroll_units(-360), (1, 3))

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

    def test_dictation_preview_includes_chinese_when_present(self):
        document = DictationDocument(
            rows=(
                DictationRow("conduct", "v", "指挥", ("They _______ it.",), ("他们指挥它。",)),
            ),
            options=DictationOptions(),
        )
        self.assertEqual(
            dictation_preview_blocks(document),
            ["1. conduct    v    指挥\n    e.g. They _______ it.（他们指挥它。）"],
        )


if __name__ == "__main__":
    unittest.main()
