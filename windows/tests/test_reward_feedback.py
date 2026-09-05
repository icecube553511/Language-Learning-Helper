from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from presentation.reward_feedback import (
    DEFAULT_CONFIG,
    BURST_PARTICLE_COUNT,
    FlightPhase,
    RewardFeedbackModel,
    RewardFeedbackController,
    RewardPoint,
    REVIEW_REWARD_COLOR,
    STUDY_REWARD_COLOR,
    transparent_hit_test_result,
    WM_NCHITTEST,
    HTTRANSPARENT,
    trail_length_for_speed,
    clip_trail_to_length,
)


class RewardFeedbackV2Tests(unittest.TestCase):
    def test_new_flight_has_intro_and_unique_identity(self):
        model = RewardFeedbackModel()
        first = model.emit((10, 20), STUDY_REWARD_COLOR, now_ms=0)
        second = model.emit((20, 30), "#22b8b5", now_ms=0)
        self.assertEqual(first.phase, FlightPhase.INTRO)
        self.assertNotEqual(first.flight_id, second.flight_id)
        self.assertEqual(model.active_count, 2)

    def test_intro_transitions_to_seek_with_acceleration(self):
        model = RewardFeedbackModel()
        flight = model.emit((0, 0), STUDY_REWARD_COLOR, now_ms=0)
        model.update(DEFAULT_CONFIG.intro_ms, (800, 0), pet_half_size=10)
        self.assertEqual(flight.phase, FlightPhase.SEEK)
        speed_before = flight.speed
        model.update(DEFAULT_CONFIG.intro_ms + 80, (800, 0), pet_half_size=10)
        self.assertGreater(flight.speed, speed_before)
        self.assertGreater(len(flight.trail), 1)

    def test_contact_generates_compact_burst(self):
        model = RewardFeedbackModel()
        flight = model.emit((0, 0), STUDY_REWARD_COLOR, now_ms=0)
        model.update(DEFAULT_CONFIG.intro_ms, (30, 0), pet_half_size=10)
        model.update(DEFAULT_CONFIG.intro_ms + 100, (30, 0), pet_half_size=10)
        self.assertEqual(flight.phase, FlightPhase.BURST)
        self.assertEqual(len(flight.particles), BURST_PARTICLE_COUNT)
        self.assertIsNotNone(flight.contact_point)
        model.update(flight.burst_started_at_ms + DEFAULT_CONFIG.burst_ms, (30, 0), 10)
        self.assertEqual(model.active_count, 0)

    def test_missing_target_timeout_cancels_flight(self):
        model = RewardFeedbackModel()
        flight = model.emit((0, 0), STUDY_REWARD_COLOR, now_ms=0)
        model.update(100, None, 10)
        self.assertTrue(flight.active)
        model.update(100 + DEFAULT_CONFIG.missing_target_ms, None, 10)
        self.assertFalse(flight.active)

    def test_pointer_source_uses_press_coordinates(self):
        # pointer_source_uses_press_coordinates is intentionally retained as a
        # behavior contract while implementation lives in presentation.app.
        from presentation.app import LexiTrackApp
        class Button:
            _reward_pointer_down = None
            def update_idletasks(self): pass
            def winfo_rootx(self): return 100
            def winfo_rooty(self): return 200
            def winfo_width(self): return 80
            def winfo_height(self): return 40
        app = object.__new__(LexiTrackApp)
        button = Button()
        app._pet_now_ms = lambda: 50.0
        event = type("Event", (), {"widget": button, "x_root": 123, "y_root": 234})()
        app._remember_rating_pointer(event)
        self.assertEqual(app._rating_source_point(button), RewardPoint(123, 234))

    def test_hit_test_contract_is_explicit(self):
        self.assertEqual(transparent_hit_test_result(WM_NCHITTEST), HTTRANSPARENT)
        self.assertIsNone(transparent_hit_test_result(0x0201))

    def test_trail_helpers_are_bounded(self):
        self.assertGreater(trail_length_for_speed(500), trail_length_for_speed(0))
        samples = [RewardPoint(float(i), 0) for i in range(20)]
        clipped = clip_trail_to_length(samples, 6)
        self.assertLessEqual(sum(clipped[i].distance_to(clipped[i-1]) for i in range(1, len(clipped))), 6.001)

    def test_controller_keeps_multiple_flights_independent(self):
        host = Mock()
        host.after.side_effect = lambda _delay, callback: "after"
        host.wm_state.return_value = "normal"
        host.winfo_exists.return_value = True
        host.winfo_viewable.return_value = True
        controller = object.__new__(RewardFeedbackController)
        controller.host = host
        controller.target_provider = lambda: RewardPoint(100, 100)
        controller.pet_half_size = 10
        controller.model = RewardFeedbackModel()
        controller.layer = Mock()
        controller._after_id = None
        controller._destroyed = False
        controller._now = 0
        a = controller.model.emit((0, 0), "#abc", 0)
        b = controller.model.emit((10, 0), "#def", 0)
        self.assertEqual(controller.model.active_count, 2)
        self.assertIsNot(a.trail, b.trail)

    def test_rating_colours_are_platform_specific(self):
        self.assertEqual(STUDY_REWARD_COLOR, "#F4C542")
        self.assertEqual(REVIEW_REWARD_COLOR, "#16866F")

    def test_study_rating_emits_gold_feedback(self):
        from presentation.app import LexiTrackApp
        from domain.models import ReviewRating

        app = object.__new__(LexiTrackApp)
        app.current_card = type("Card", (), {"word_id": "word-1"})()
        app.answer_visible = True
        app.service = Mock()
        app._rating_button_center = Mock(return_value=RewardPoint(10, 20))
        app._emit_rating_reward = Mock()
        app._sync_review_batch_control = Mock()
        app.load_study_card = Mock()
        app.rating_buttons = []

        app.rate_current(ReviewRating.GOOD, RewardPoint(10, 20))

        app._emit_rating_reward.assert_called_once_with(RewardPoint(10, 20), STUDY_REWARD_COLOR)

    def test_review_rating_emits_teal_feedback(self):
        from presentation.app import LexiTrackApp
        from domain.models import ReviewRating

        app = object.__new__(LexiTrackApp)
        app.review_queue = [type("Card", (), {"word_id": "word-1"})()]
        app.review_answer_visible = True
        app.service = Mock()
        app._rating_button_center = Mock(return_value=RewardPoint(30, 40))
        app._emit_rating_reward = Mock()
        app.review_rating_buttons = []
        app._show_next_review_card = Mock()

        app.rate_review_current(ReviewRating.GOOD, RewardPoint(30, 40))

        app._emit_rating_reward.assert_called_once_with(RewardPoint(30, 40), REVIEW_REWARD_COLOR)


if __name__ == "__main__":
    unittest.main()



