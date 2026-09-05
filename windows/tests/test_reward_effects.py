from __future__ import annotations

import sys
import unittest
from pathlib import Path


WINDOWS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WINDOWS_DIR))

from presentation.reward_effects import (
    BURST_DURATION_MS,
    BURST_PARTICLE_COUNT,
    DEFAULT_CONFIG,
    FlightPhase,
    MAX_CONCURRENT_BALLS,
    REVIEW_REWARD_COLOR,
    RewardAnimationModel,
    RewardPoint,
    STUDY_REWARD_COLOR,
    trail_length_for_speed,
)
from presentation.app import LexiTrackApp
from domain.models import ReviewRating, VocabularyEntry


class RewardEffectsModelTests(unittest.TestCase):
    def test_phase_colors_match_energy_ball_contract(self):
        self.assertEqual(STUDY_REWARD_COLOR, "#F5C451")
        self.assertEqual(REVIEW_REWARD_COLOR, "#39D9D0")

    def test_homing_accelerates_toward_live_pet_and_is_capped(self):
        model = RewardAnimationModel()
        flight = model.emit((0.0, 0.0), STUDY_REWARD_COLOR, now_ms=0.0)
        model.update(180.0, RewardPoint(10_000.0, 0.0), pet_half_size=56.0)
        initial_speed = flight.speed
        model.update(196.0, RewardPoint(10_000.0, 0.0), pet_half_size=56.0)
        self.assertGreater(flight.speed, initial_speed)
        model.update(212.0, RewardPoint(10_000.0, 1_000.0), pet_half_size=56.0)
        self.assertGreater(flight.velocity.y, 0.0)
        model.update(2_000.0, RewardPoint(10_000.0, 0.0), pet_half_size=56.0)
        self.assertLessEqual(flight.speed, DEFAULT_CONFIG.homing_maximum_speed + 1e-6)

    def test_trail_length_grows_with_speed_and_stays_bounded(self):
        self.assertEqual(trail_length_for_speed(0.0), 12.0)
        self.assertGreater(trail_length_for_speed(1_000.0), trail_length_for_speed(100.0))
        self.assertEqual(trail_length_for_speed(10_000.0), 96.0)

    def test_contact_enters_firework_burst_and_expires(self):
        model = RewardAnimationModel()
        flight = model.emit((0.0, 0.0), REVIEW_REWARD_COLOR, now_ms=0.0)
        target = RewardPoint(100.0, 0.0)
        for now_ms in range(180, 1_000, 16):
            model.update(float(now_ms), target, pet_half_size=56.0)
            if flight.phase is FlightPhase.BURST:
                break
        self.assertEqual(flight.phase, FlightPhase.BURST)
        self.assertEqual(len(flight.particles), BURST_PARTICLE_COUNT)
        self.assertEqual(len({particle.velocity for particle in flight.particles}), BURST_PARTICLE_COUNT)
        self.assertIsNotNone(flight.contact_point)
        self.assertLessEqual(flight.contact_point.distance_to(target), DEFAULT_CONFIG.hit_radius + 1e-6)
        model.update(float(flight.burst_started_at_ms + BURST_DURATION_MS), target, pet_half_size=56.0)
        self.assertEqual(model.active_count, 0)

    def test_concurrent_flights_are_bounded_to_three(self):
        model = RewardAnimationModel()
        for index in range(MAX_CONCURRENT_BALLS + 2):
            model.emit((float(index), float(index)), STUDY_REWARD_COLOR, now_ms=0.0)
        self.assertEqual(len(model.flights), MAX_CONCURRENT_BALLS)
        self.assertEqual(model.active_count, MAX_CONCURRENT_BALLS)

    def test_rating_starts_feedback_before_persistence_for_study_and_review(self):
        card = VocabularyEntry.create("focus", "专注", [])
        source = RewardPoint(123.0, 456.0)

        study = object.__new__(LexiTrackApp)
        study.current_card = card
        study.answer_visible = True
        study.service = type("Service", (), {})()
        calls: list[tuple] = []
        study.service.rate_card = lambda *args: calls.append(("service", args))
        study._emit_rating_reward = lambda *args: calls.append(("effect", args))
        study._sync_review_batch_control = lambda: None
        study.load_study_card = lambda **kwargs: calls.append(("next", kwargs))
        study.rate_current(ReviewRating.GOOD, source)

        self.assertEqual(calls[0], ("effect", (source, STUDY_REWARD_COLOR)))
        self.assertEqual(calls[1][0], "service")

        review = object.__new__(LexiTrackApp)
        review.review_queue = [card]
        review.review_answer_visible = True
        review.service = type("Service", (), {})()
        review_calls: list[tuple] = []
        review.service.rate_review_card = lambda *args: review_calls.append(("service", args))
        review._emit_rating_reward = lambda *args: review_calls.append(("effect", args))
        review._show_next_review_card = lambda: review_calls.append(("next", ()))
        review.rate_review_current(ReviewRating.EASY, source)

        self.assertEqual(review_calls[0], ("effect", (source, REVIEW_REWARD_COLOR)))
        self.assertEqual(review_calls[1][0], "service")


if __name__ == "__main__":
    unittest.main()
