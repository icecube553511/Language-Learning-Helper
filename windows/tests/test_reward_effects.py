from __future__ import annotations

import sys
import json
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


WINDOWS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WINDOWS_DIR))

from presentation.reward_effects import (
    BURST_DURATION_MS,
    BURST_PARTICLE_COUNT,
    DEFAULT_CONFIG,
    FlightPhase,
    HOMING_INITIAL_SPEED,
    HOMING_ACCELERATION,
    ORB_RADIUS,
    WINDOWS_EFFECT_SCALE,
    SIMULATION_STEP_MS,
    TRAIL_MAXIMUM_POINTS,
    REVIEW_REWARD_COLOR,
    RewardAnimationModel,
    RewardEffectsController,
    RewardEffectLayer,
    RewardPoint,
    RewardTarget,
    STUDY_REWARD_COLOR,
    collision_fraction,
    render_reward_frame,
    _orb_sprite,
)
from presentation.app import LexiTrackApp
from presentation.widgets import PetOverlay
from domain.models import ReviewRating, VocabularyEntry


GOLDEN = json.loads((WINDOWS_DIR.parent / "shared/contracts/pet-energy-ball-golden-v1.json").read_text(encoding="utf-8"))


class RewardEffectsModelTests(unittest.TestCase):
    def test_phase_colors_match_energy_ball_contract(self):
        self.assertEqual(STUDY_REWARD_COLOR, "#F5C451")
        self.assertEqual(REVIEW_REWARD_COLOR, "#39D9D0")

    def test_shared_motion_vectors_preserve_demo_acceleration_without_speed_or_age_limits(self):
        self.assertEqual(HOMING_INITIAL_SPEED, GOLDEN["motion"]["initialSpeedLogicalPxPerSecond"])
        self.assertEqual(HOMING_ACCELERATION, GOLDEN["motion"]["accelerationLogicalPxPerSecondSquared"])
        for vector in GOLDEN["motionVectors"]:
            with self.subTest(vector["name"]):
                model = RewardAnimationModel()
                flight = model.emit((0.0, 0.0), STUDY_REWARD_COLOR, now_ms=0.0)
                model.update(vector["seconds"] * 1000.0, (1_000_000.0, 0.0), pet_half_size=56.0)
                self.assertEqual(flight.phase, FlightPhase.HOMING)
                self.assertAlmostEqual(flight.position.x, vector["distance"], places=6)
                self.assertAlmostEqual(flight.speed, vector["speed"], places=6)

    def test_shared_relative_collision_vectors(self):
        for vector in GOLDEN["collisionVectors"]:
            with self.subTest(vector["name"]):
                result = collision_fraction(*(RewardPoint(*vector[key]) for key in
                                              ("orbStart", "orbEnd", "targetStart", "targetEnd")),
                                            vector["targetRadius"] + ORB_RADIUS)
                if vector["fraction"] is None:
                    self.assertIsNone(result)
                else:
                    self.assertAlmostEqual(result, vector["fraction"])

    def test_homing_retargets_direction_immediately_and_preserves_scalar_speed(self):
        model = RewardAnimationModel()
        flight = model.emit((0.0, 0.0), STUDY_REWARD_COLOR, now_ms=0.0)
        model.update(100.0, (10_000.0, 0.0), pet_half_size=56.0, target_key="main")
        model.update(100.0 + SIMULATION_STEP_MS, (flight.position.x, 10_000.0), pet_half_size=56.0, target_key="dialog")
        self.assertAlmostEqual(flight.velocity.x, 0.0)
        self.assertGreater(flight.velocity.y, 0.0)
        self.assertAlmostEqual(flight.speed, 65.0 + 230.0 * (0.1 + SIMULATION_STEP_MS / 1000.0))

    def test_trail_records_42_samples_at_120_hz_across_partial_frames(self):
        model = RewardAnimationModel()
        flight = model.emit((0, 0), STUDY_REWARD_COLOR, 0)
        for now_ms in range(16, 2001, 16):
            model.update(now_ms, (10_000, 0), 56)
        self.assertEqual(len(flight.trail), TRAIL_MAXIMUM_POINTS)
        for first, second in zip(flight.trail, flight.trail[1:]):
            self.assertAlmostEqual(second.at_ms - first.at_ms, SIMULATION_STEP_MS)
        distance = flight.trail[-1].position.x - flight.trail[0].position.x
        self.assertGreater(distance, 96.0)

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
        self.assertEqual(len({particle.direction for particle in flight.particles}), BURST_PARTICLE_COUNT)
        self.assertIsNotNone(flight.contact_point)
        self.assertAlmostEqual(flight.contact_point.distance_to(target), 56.0 + ORB_RADIUS * WINDOWS_EFFECT_SCALE)
        self.assertEqual(flight.position, target)
        model.update(flight.last_update_ms + BURST_DURATION_MS + SIMULATION_STEP_MS, target, pet_half_size=56.0)
        self.assertEqual(model.active_count, 0)

    def test_concurrent_flights_and_offscreen_positions_are_preserved(self):
        model = RewardAnimationModel()
        flights = [model.emit((-10_000.0 - index, 0.0), STUDY_REWARD_COLOR, 0) for index in range(12)]
        model.update(10_000, (1_000_000, 0), 56)
        self.assertEqual(model.flights, flights)
        self.assertEqual(model.active_count, 12)
        self.assertEqual(len({flight.flight_id for flight in flights}), 12)

    def test_missing_target_freezes_all_state_and_resumes_without_catchup(self):
        model = RewardAnimationModel()
        flight = model.emit((0, 0), STUDY_REWARD_COLOR, 0)
        model.update(100, (10_000, 0), 56)
        state = (flight.position, flight.speed, flight.elapsed_ms, tuple(flight.trail))
        model.update(5000, None, 56)
        model.update(10_000, None, 56)
        model.update(20_000, (-10_000, 0), 56)
        self.assertEqual((flight.position, flight.speed, flight.elapsed_ms, tuple(flight.trail)), state)
        model.update(20_016, (-10_000, 0), 56)
        self.assertEqual(flight.phase, FlightPhase.HOMING)
        self.assertLess(flight.position.x, state[0].x)
        self.assertAlmostEqual(flight.speed, state[1] + 230 * SIMULATION_STEP_MS / 1000.0)

    def test_missing_target_also_pauses_impact_age(self):
        model = RewardAnimationModel()
        flight = model.emit((0, 0), REVIEW_REWARD_COLOR, 0)
        model.update(16, (20, 0), 56)
        self.assertEqual(flight.phase, FlightPhase.BURST)
        age = flight.elapsed_ms
        model.update(5000, None, 56)
        model.update(10_000, (20, 0), 56)
        self.assertEqual(flight.elapsed_ms, age)
        model.update(10_430, (20, 0), 56)
        self.assertEqual(model.active_count, 0)

    def test_host_change_does_not_sweep_across_teleport_but_dragging_does(self):
        for key, expected in (("main", FlightPhase.BURST), ("dialog", FlightPhase.HOMING)):
            with self.subTest(key=key):
                model = RewardAnimationModel()
                flight = model.emit((0, 0), STUDY_REWARD_COLOR, 0)
                model.update(0, (100, 0), 56, "main")
                model.update(SIMULATION_STEP_MS, (-100, 0), 56, key)
                self.assertEqual(flight.phase, expected)

    def test_display_size_scales_motion_and_contact_together(self):
        positions = []
        for scale in (1.0, 2.0):
            model = RewardAnimationModel()
            flight = model.emit((0, 0), STUDY_REWARD_COLOR, 0)
            model.update(200, (200 * scale, 0), 56 * scale)
            positions.append(flight.position.x)
        self.assertAlmostEqual(positions[1], positions[0] * 2.0)

    def test_raster_has_white_core_soft_alpha_glow_and_transparent_background(self):
        model = RewardAnimationModel()
        model.emit((100, 100), STUDY_REWARD_COLOR, 0)
        frame, x, y = render_reward_frame(model, (0, 0, 200, 200))
        self.assertEqual(frame.getpixel((100 - x, 100 - y)), (255, 250, 228, 255))
        inner = frame.getpixel((124 - x, 100 - y))[3]
        outer = frame.getpixel((160 - x, 100 - y))[3]
        self.assertTrue(0 < outer < inner < 255)
        self.assertEqual(frame.getpixel((0, 0))[3], 0)

    def test_windows_enlargement_uses_shared_profile_for_pixels_and_contact(self):
        self.assertEqual(WINDOWS_EFFECT_SCALE, GOLDEN["platformEffectScale"]["windows"])
        model = RewardAnimationModel()
        flight = model.emit((100, 100), STUDY_REWARD_COLOR, 0)
        frame, x, y = render_reward_frame(model, (0, 0, 300, 300))
        self.assertGreaterEqual(frame.getpixel((112 - x, 100 - y))[3], 250)
        self.assertTrue(0 < frame.getpixel((175 - x, 100 - y))[3] < 255)
        model.update(SIMULATION_STEP_MS, (169, 100), 56)
        self.assertEqual(flight.phase, FlightPhase.BURST)

    def test_warm_frames_reuse_antialiased_orb_without_resampling_large_surface(self):
        model = RewardAnimationModel()
        for position in ((100, 100), (1800, 1000)):
            model.emit(position, STUDY_REWARD_COLOR, 0)
        render_reward_frame(model, (0, 0, 2560, 1600))
        with patch("PIL.Image.Image.resize", side_effect=AssertionError("resampled whole frame")):
            frame, _, _ = render_reward_frame(model, (0, 0, 2560, 1600))
        self.assertGreater(frame.width, 1700)
        self.assertGreater(_orb_sprite.cache_info().hits, 0)

    def test_source_is_button_center_even_when_pointer_position_is_available(self):
        app = object.__new__(LexiTrackApp)
        button = Mock()
        button.winfo_rootx.return_value, button.winfo_rooty.return_value = 100, 200
        button.winfo_width.return_value, button.winfo_height.return_value = 200, 40
        button._reward_pointer_down = (RewardPoint(101, 202), 0)
        self.assertEqual(app._rating_source_point(button), RewardPoint(200, 220))

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

    def test_page_navigation_preserves_flights_and_resets_only_target_history(self):
        app = object.__new__(LexiTrackApp)
        app.current_page = "study"
        app.pages = {"study": Mock(), "library": Mock()}
        app.nav_items = {"study": Mock(), "library": Mock()}
        app.word_bubbles = Mock()
        app.pet_companion = Mock()
        app._cancel_dictation_loading = Mock()
        app.refresh_library = Mock()
        app._schedule_pet_target_refresh = Mock()
        effects = object.__new__(RewardEffectsController)
        effects.model = RewardAnimationModel()
        flight = effects.model.emit((0, 0), STUDY_REWARD_COLOR, 0)
        effects.model.update(100, (10_000, 0), 56)
        app._reward_effects = effects
        position, speed = flight.position, flight.speed

        app.show_page("library")

        self.assertEqual(effects.model.flights, [flight])
        self.assertEqual((flight.position, flight.speed), (position, speed))
        self.assertIsNone(flight._previous_target)

    def test_inactive_ratings_never_emit_or_settle(self):
        app = object.__new__(LexiTrackApp)
        app.current_card = None
        app.review_queue = []
        app.answer_visible = app.review_answer_visible = False
        app._emit_rating_reward, app.service = Mock(), Mock()
        for rating in ReviewRating:
            app.rate_current(rating, RewardPoint(1, 1))
            app.rate_review_current(rating, RewardPoint(1, 1))
        app._emit_rating_reward.assert_not_called()
        app.service.rate_card.assert_not_called()
        app.service.rate_review_card.assert_not_called()


class RewardEffectsControllerTests(unittest.TestCase):
    def setUp(self):
        self.now = 0.0
        self.clock = patch("presentation.reward_effects._monotonic_ms", lambda: self.now)
        self.clock.start()
        self.addCleanup(self.clock.stop)
        self.layer_patch = patch("presentation.reward_effects.RewardEffectLayer")
        self.layer = self.layer_patch.start().return_value
        self.addCleanup(self.layer_patch.stop)
        self.host = Mock()
        self.host.wm_state.return_value = "normal"
        self.host.winfo_exists.return_value = self.host.winfo_viewable.return_value = True
        self.host.focus_displayof.return_value = object()
        self.target = RewardTarget(RewardPoint(10_000, 0), 56, "main")
        self.controller = RewardEffectsController(self.host, lambda: self.target, pet_half_size=56)

    def tick(self, now):
        self.now = now
        self.controller._tick()

    def test_foreground_and_missing_target_resume_with_fresh_clock(self):
        for suspension in ("iconic", "background", "missing-target"):
            with self.subTest(suspension=suspension):
                self.controller.clear()
                self.controller._ready_last_tick = False
                self.now += 100
                flight = self.controller.emit((0, 0), STUDY_REWARD_COLOR)
                self.tick(self.now + 16)
                initial = (flight.position, flight.speed, flight.elapsed_ms, tuple(flight.trail))
                if suspension == "iconic":
                    self.host.wm_state.return_value = "iconic"
                elif suspension == "background":
                    self.host.focus_displayof.return_value = None
                else:
                    self.target = None
                self.tick(self.now + 5000)
                self.layer.hide.assert_called()
                self.host.wm_state.return_value = "normal"
                self.host.focus_displayof.return_value = object()
                self.target = RewardTarget(RewardPoint(-10_000, 0), 56, "dialog")
                self.tick(self.now + 5000)
                self.assertEqual((flight.position, flight.speed, flight.elapsed_ms, tuple(flight.trail)), initial)
                self.tick(self.now + 16)
                self.assertAlmostEqual(flight.speed, initial[1] + 230 * 2 * SIMULATION_STEP_MS / 1000.0)
                self.assertEqual(flight.phase, FlightPhase.HOMING)

    def test_delayed_foreground_frame_is_bounded_to_demo_maximum_frame_time(self):
        flight = self.controller.emit((0, 0), STUDY_REWARD_COLOR)
        self.tick(5000)
        self.assertAlmostEqual(flight.elapsed_ms, 100.0)
        self.assertAlmostEqual(flight.speed, 88.0)

    def test_render_failure_retries_without_losing_orbs(self):
        self.layer.render.side_effect = RuntimeError("temporary native frame failure")
        flight = self.controller.emit((0, 0), STUDY_REWARD_COLOR)
        self.tick(16)
        self.assertEqual(self.controller.model.flights, [flight])
        self.assertIsNotNone(self.controller._after_id)
        self.layer.render.side_effect = None
        self.tick(32)
        self.assertIsNone(self.controller._render_error)

    def test_render_cost_is_subtracted_from_next_frame_delay(self):
        self.controller.emit((0, 0), STUDY_REWARD_COLOR)

        def render(*_args):
            self.now += 6

        self.layer.render.side_effect = render
        self.tick(16)
        self.host.after.assert_called_with(10, self.controller._tick)
        self.layer.render.side_effect = lambda *_args: setattr(self, "now", self.now + 30)
        self.tick(32)
        self.host.after.assert_called_with(1, self.controller._tick)

    def test_visible_layer_does_not_repeat_native_style_installation(self):
        layer = Mock()
        layer.state.return_value = "normal"
        RewardEffectLayer.show(layer)
        layer._enable_mouse_passthrough.assert_not_called()
        layer.lift.assert_not_called()

    def test_exit_cancels_timer_and_discards_transient_state(self):
        self.controller.emit((0, 0), STUDY_REWARD_COLOR)
        self.controller.destroy()
        self.assertEqual(self.controller.model.active_count, 0)
        self.host.after_cancel.assert_called()
        self.layer.destroy.assert_called_once()


@unittest.skipUnless(sys.platform == "win32", "Requires native Windows Toplevel restacking")
class RewardNativeWindowTests(unittest.TestCase):
    def test_effect_restack_preserves_pending_native_pet_geometry(self):
        root = tk.Tk()
        self.addCleanup(root.destroy)
        root.geometry("500x300+50+50")
        root.attributes("-alpha", 0.0)
        root.update()
        sprite = tk.PhotoImage(master=root, width=40, height=40)
        pet = PetOverlay(root, sprite, lambda _event: None, lambda _event: None,
                         lambda _event: None, display_size=40)
        pet.attributes("-alpha", 0.0)
        pet.place(x=20, y=50)
        root.update()
        layer = RewardEffectLayer(root)
        model = RewardAnimationModel()
        # Keep the test invisible while exercising the mapped layered HWND.
        model.emit((100_000, 100_000), STUDY_REWARD_COLOR, 0)
        layer.show()
        layer.render(model, 0)
        root.update()
        positions = []
        for index in range(5):
            x, y = 30 + index * 10, 60 + index * 5
            pet.place(x=x, y=y)
            pet.lift()
            layer.keep_above(pet)
            root.update()
            positions.append((pet.winfo_rootx(), pet.winfo_rooty()))
        self.assertGreaterEqual(len(set(positions)), 4)
        self.assertEqual(positions[-1], (root.winfo_rootx() + x, root.winfo_rooty() + y))
        for hwnd in layer._native_surfaces():
            self.assertEqual(layer.native_hit_test(hwnd, 100, 100), -1)


if __name__ == "__main__":
    unittest.main()
