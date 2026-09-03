from __future__ import annotations

import json
import math
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch


WINDOWS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WINDOWS_DIR))

from application.services import LearningService
from domain.models import (
    DEFAULT_FONT_SCALE,
    MAX_FONT_SCALE,
    MIN_FONT_SCALE,
    font_scale_from_percent,
    sanitize_font_scale,
)
from infrastructure.repository import JsonLearningRepository
from presentation.app import FontManager, LexiTrackApp


class _Panel:
    def winfo_width(self):
        return 480

    def winfo_manager(self):
        return ""

    def pack_forget(self):
        return None

    def pack(self, **_kwargs):
        return None


class FontScaleTests(unittest.TestCase):
    def test_domain_normalizer_rejects_non_finite_and_malformed_values(self):
        invalid_values = (
            None,
            "",
            "not-a-number",
            "nan",
            "inf",
            "-inf",
            float("nan"),
            float("inf"),
            float("-inf"),
        )
        for value in invalid_values:
            self.assertEqual(sanitize_font_scale(value), DEFAULT_FONT_SCALE)
        self.assertEqual(sanitize_font_scale(0), MIN_FONT_SCALE)
        self.assertEqual(sanitize_font_scale(2), MAX_FONT_SCALE)
        self.assertEqual(font_scale_from_percent("90"), MIN_FONT_SCALE)
        self.assertEqual(font_scale_from_percent("140"), MAX_FONT_SCALE)
        self.assertEqual(font_scale_from_percent("bad", fallback=1.25), 1.25)
        self.assertEqual(font_scale_from_percent("nan", fallback=1.25), 1.25)
        self.assertTrue(math.isfinite(font_scale_from_percent("1e309")))

    def test_repository_repairs_non_finite_json_and_writes_finite_values(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "learning-state.json"
            # Python's JSON decoder accepts these legacy non-standard tokens;
            # the repository must still normalize them before they reach Tk.
            path.write_text('{"settings": {"fontScale": NaN}}', encoding="utf-8")
            repository = JsonLearningRepository(Path(directory))
            self.assertEqual(repository.get_font_scale(), DEFAULT_FONT_SCALE)
            repository.set_font_scale("Infinity")
            payload = path.read_text(encoding="utf-8")
            self.assertNotIn("Infinity", payload)
            self.assertEqual(repository.get_font_scale(), DEFAULT_FONT_SCALE)

            # Even an accidental in-memory mutation cannot leak a non-finite
            # value through an unrelated settings save.
            repository._settings["fontScale"] = float("nan")
            repository.set_review_batch_size(3)
            saved_scale = json.loads(path.read_text(encoding="utf-8"))["settings"]["fontScale"]
            self.assertEqual(saved_scale, DEFAULT_FONT_SCALE)

    def test_service_normalizes_repository_values_and_inputs(self):
        repository = Mock()
        repository.get_font_scale.return_value = float("nan")
        service = LearningService(repository)
        self.assertEqual(service.font_scale(), DEFAULT_FONT_SCALE)
        self.assertEqual(service.set_font_scale("not-a-number"), DEFAULT_FONT_SCALE)
        repository.set_font_scale.assert_called_with(DEFAULT_FONT_SCALE)
        self.assertEqual(service.set_font_scale(float("inf")), DEFAULT_FONT_SCALE)

    def test_font_manager_apply_uses_safe_scale_for_non_finite_input(self):
        manager = object.__new__(FontManager)
        manager.fonts = {name: Mock() for name in FontManager.BASE_SIZES}
        manager.apply(float("nan"))
        manager.fonts["LexiBody"].configure.assert_called_once_with(size=13)
        manager.fonts["LexiExample"].configure.assert_called_once_with(size=12)

    def test_presentation_callback_recovers_from_malformed_slider_values(self):
        app = object.__new__(LexiTrackApp)
        service = Mock()
        service.font_scale.return_value = 1.25
        app.service = service
        app.font_manager = Mock()
        app.scale_var = Mock()
        app.scale_text = Mock()
        app.minsize = Mock()
        app.study_meaning = Mock()
        app.review_meaning = Mock()
        app._apply_answer_text = Mock()
        app.current_card = None
        app.example_texts = []
        app.example_labels = []
        app.answer_panel = _Panel()
        app.review_queue = []
        app.review_example_texts = []
        app.review_example_labels = []
        app.review_answer_panel = _Panel()
        app.answer_visible = False
        app.review_answer_visible = False
        app.current_page = "dashboard"

        with patch("presentation.app.ttk.Style") as style_factory:
            for raw_value in (None, "", "bad", "nan", "inf", "-inf", "1e309"):
                LexiTrackApp.change_font_scale(app, raw_value)

        # The current valid value is retained for every malformed callback.
        self.assertEqual(service.set_font_scale.call_count, 7)
        self.assertTrue(
            all(call.args == (1.25,) for call in service.set_font_scale.call_args_list)
        )
        self.assertEqual(app.scale_text.configure.call_args.args, ())
        self.assertEqual(app.scale_text.configure.call_args.kwargs["text"], "125%")
        self.assertFalse(app.__dict__.get("_font_scale_callback_active", False))


if __name__ == "__main__":
    unittest.main()
