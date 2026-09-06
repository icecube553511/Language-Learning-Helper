from __future__ import annotations

import json
import math
from pathlib import Path
import sys
import tkinter as tk
import unittest
from unittest.mock import Mock


WINDOWS_DIR = Path(__file__).resolve().parents[1]
ROOT_DIR = WINDOWS_DIR.parent
sys.path.insert(0, str(WINDOWS_DIR))

from presentation.reward_effects import (
    BURST_PARTICLE_COUNT,
    DEFAULT_CONFIG,
    FlightPhase,
    RewardAnimationModel,
    RewardPoint,
    STUDY_REWARD_COLOR,
    BURST_PARTICLE_GLOW_RADIUS,
    BURST_PARTICLE_RADIUS,
    TRAIL_GLOW_WIDTH_MULTIPLIER,
    TRAIL_MAXIMUM_STROKE_WIDTH,
    TRAIL_MINIMUM_STROKE_WIDTH,
    TRAIL_STROKE_SPEED_FACTOR,
    VISUAL_ORB_GLOW_RADIUS,
    VISUAL_ORB_HIGHLIGHT_RADIUS,
    VISUAL_ORB_RADIUS,
    RewardEffectLayer,
    HTTRANSPARENT,
    WM_NCHITTEST,
    transparent_hit_test_result,
    TrailSample,
    clip_trail_to_length,
    trail_polyline_length,
    trail_length_for_speed,
    trail_stroke_width_for_speed,
)
from presentation.app import LexiTrackApp, preserve_pet_motion_for_targets
from domain.models import ReviewRating, VocabularyEntry
from domain.pet_companion import (
    advance_pet,
    PetMode,
    PetPoint,
    PetRect,
    PetState,
    PetTarget,
    PetTargetKind,
)


GOLDEN = json.loads(
    (ROOT_DIR / "shared" / "contracts" / "pet-vitals-golden-v1.json")
    .read_text(encoding="utf-8")
)


class RewardEffectsTests(unittest.TestCase):
    def test_card_refresh_rebinds_stale_target_without_clearing_pet_motion(self):
        state = PetState(
            position=PetPoint(48.0, 72.0),
            mode=PetMode.SLIDE,
            target_id="study:old-rating",
            idle_ticks_remaining=2,
            movement_speed=37.0,
            vertical_velocity=-12.0,
            horizontal_velocity=18.0,
            bounces_remaining=2,
        )
        targets = [
            PetTarget(
                "study:new-rating",
                PetTargetKind.CONTROL,
                PetRect(20.0, 100.0, 80.0, 24.0),
            ),
        ]

        rebound = preserve_pet_motion_for_targets(state, targets)

        self.assertIsNone(rebound.target_id)
        self.assertEqual(rebound.mode, state.mode)
        self.assertEqual(rebound.position, state.position)
        self.assertEqual(rebound.idle_ticks_remaining, state.idle_ticks_remaining)
        self.assertEqual(rebound.path_index, 0)
        self.assertEqual(rebound.path_direction, 1)
        self.assertEqual(rebound.roll_corners, 0)
        self.assertIsNone(rebound.avoid_target_id)
        self.assertIsNone(rebound.curve_velocity)
        self.assertEqual(rebound.movement_speed, state.movement_speed)
        self.assertEqual(rebound.vertical_velocity, state.vertical_velocity)
        self.assertEqual(rebound.horizontal_velocity, state.horizontal_velocity)
        self.assertEqual(rebound.bounces_remaining, state.bounces_remaining)

    def test_card_refresh_keeps_viewport_bottom_support_id(self):
        state = PetState(
            position=PetPoint(48.0, 72.0),
            mode=PetMode.BOUNCE,
            target_id="__viewport-bottom__",
            bounces_remaining=1,
            vertical_velocity=-120.0,
        )

        rebound = preserve_pet_motion_for_targets(state, [])

        self.assertEqual(rebound, state)

    def test_rating_reflow_keeps_pet_cruising(self):
        """When a rating click replaces the card, the pet must keep moving.

        The card reflow briefly drops the followed control.  The presentation
        rebinds a stale support without clearing the live physical state, and
        the reducer must keep advancing the companion toward the rebuilt card
        rather than parking it in an IDLE/no-target state.
        """
        viewport = PetRect(0.0, 0.0, 900.0, 700.0)
        pet_size = 24.0
        old_target = PetTarget("study:old-rating", PetTargetKind.CONTROL, PetRect(70.0, 300.0, 80.0, 24.0))
        new_controls = [
            PetTarget("study:new-inner", PetTargetKind.CONTROL, PetRect(60.0, 520.0, 90.0, 24.0)),
            PetTarget("nav:Home", PetTargetKind.CONTROL, PetRect(60.0, 20.0, 90.0, 24.0)),
            PetTarget("edge:right", PetTargetKind.EDGE, PetRect(897.0, 0.0, 3.0, 700.0)),
            PetTarget("edge:bottom", PetTargetKind.EDGE, PetRect(0.0, 697.0, 900.0, 3.0)),
            PetTarget("edge:left", PetTargetKind.EDGE, PetRect(0.0, 0.0, 3.0, 700.0)),
        ]
        state = PetState(
            position=PetPoint(180.0, 260.0),
            mode=PetMode.FLY,
            target_id=old_target.id,
            movement_speed=37.0,
            vertical_velocity=0.0,
            horizontal_velocity=0.0,
        )

        start_position = state.position
        sampled_positions: list[PetPoint] = [start_position]
        for _ in range(30):
            state = preserve_pet_motion_for_targets(state, new_controls)
            state = advance_pet(state, new_controls, viewport, pet_size=pet_size)
            if state.position not in sampled_positions:
                sampled_positions.append(state.position)

        # The companion must traverse at least a few distinct points so the
        # card reflow never parks it at a single frozen spot, and it must not
        # end stranded with a cleared target forever.
        self.assertGreater(len(sampled_positions), 3)
        self.assertTrue(
            state.position != start_position or state.target_id is not None,
            "pet was cleared to a target-less state without retaining motion",
        )

    def test_pet_tick_retries_transient_error_instead_of_freezing(self):
        """A TclError while a card is rebuilding must not permanently stop the pet."""
        app = object.__new__(LexiTrackApp)
        app._pet_overlay = object()
        app._dialog_pet_stack = []
        app._pet_targets = ()
        app._pet_tick_failures = 0
        app._pet_tick_after_id = None
        app._reward_effects = None
        app.pet_companion = Mock()
        app._pet_last_rendered_position = None

        scheduled: list[tuple] = []

        def fake_after(*args):
            scheduled.append(args)
            return f"after:{len(scheduled)}"

        app.after = fake_after

        def raise_tcl(*_args, **_kwargs):
            raise tk.TclError("widget unmounted mid-tick")

        app._collect_pet_targets = raise_tcl

        # A single transient error must retry rather than dropping the schedule.
        app._pet_tick()
        self.assertEqual(app._pet_tick_failures, 1)
        self.assertEqual(app._pet_tick_after_id, "after:1")
        self.assertEqual(len(scheduled), 1)

        # Repeated failures are bounded so a genuinely torn-down window stops
        # cleanly instead of hammering the event loop forever.
        for _ in range(4):
            app._pet_tick()
        self.assertEqual(app._pet_tick_failures, 5)
        self.assertIsNone(app._pet_tick_after_id)
        self.assertEqual(len(scheduled), 4)

    def test_effect_layer_hit_test_is_explicitly_transparent(self):
        self.assertEqual(transparent_hit_test_result(WM_NCHITTEST), HTTRANSPARENT)
        self.assertIsNone(transparent_hit_test_result(0x0201))
        self.assertIsNone(transparent_hit_test_result(None))

    def test_effect_layer_subclasses_every_native_surface(self):
        """The transparent surface must pass hits on both the top-level and canvas."""
        layer = object.__new__(RewardEffectLayer)
        layer._passthrough_handles = []
        layer._passthrough_callbacks = []
        layer._call_window_proc = None

        user32 = Mock()
        user32.GetWindowLongPtrW = Mock(return_value=0xDEAD_BEEF)
        user32.SetWindowLongPtrW = Mock(return_value=0)
        user32.CallWindowProcW = Mock(return_value=0)

        layer._install_hit_test_passthrough(user32, 0x1234)
        layer._install_hit_test_passthrough(user32, 0x5678)
        # Calling again for an existing surface must not double-subclass it.
        layer._install_hit_test_passthrough(user32, 0x1234)

        self.assertEqual(
            [handle for handle, _original in layer._passthrough_handles],
            [0x1234, 0x5678],
        )
        self.assertEqual(len(layer._passthrough_callbacks), 2)

    def test_tunable_configuration_matches_golden_contract(self):
        feedback = GOLDEN["rewardFlight"]
        self.assertEqual(STUDY_REWARD_COLOR, feedback["studyColor"])
        self.assertEqual(DEFAULT_CONFIG.spiral_duration_ms, feedback["spiralDurationMs"])
        self.assertEqual(DEFAULT_CONFIG.spiral_turns, feedback["spiralTurns"])
        self.assertEqual(DEFAULT_CONFIG.spiral_radius_start, feedback["spiralRadiusStart"])
        self.assertEqual(DEFAULT_CONFIG.spiral_radius_end, feedback["spiralRadiusEnd"])
        self.assertEqual(DEFAULT_CONFIG.homing_initial_speed, feedback["homingInitialSpeed"])
        self.assertEqual(DEFAULT_CONFIG.homing_acceleration, feedback["homingAcceleration"])
        self.assertEqual(DEFAULT_CONFIG.homing_maximum_speed, feedback["homingMaximumSpeed"])
        self.assertEqual(DEFAULT_CONFIG.orb_radius, feedback["orbRadius"])
        self.assertEqual(DEFAULT_CONFIG.trail_lifetime_ms, feedback["trailLifetimeMs"])
        self.assertEqual(DEFAULT_CONFIG.trail_maximum_points, feedback["trailMaximumPoints"])
        self.assertEqual(DEFAULT_CONFIG.burst_particle_count, feedback["burstParticleCount"])
        self.assertEqual(DEFAULT_CONFIG.burst_duration_ms, feedback["burstDurationMs"])
        self.assertEqual(DEFAULT_CONFIG.maximum_lifetime_ms, feedback["maximumLifetimeMs"])
        self.assertEqual(DEFAULT_CONFIG.missing_target_timeout_ms, feedback["missingTargetTimeoutMs"])
        visual = feedback["visual"]
        self.assertEqual(VISUAL_ORB_RADIUS, visual["orbRadius"])
        self.assertEqual(VISUAL_ORB_GLOW_RADIUS, visual["orbGlowRadius"])
        self.assertEqual(VISUAL_ORB_HIGHLIGHT_RADIUS, visual["orbHighlightRadius"])
        self.assertEqual(TRAIL_MINIMUM_STROKE_WIDTH, visual["trailMinimumStrokeWidth"])
        self.assertEqual(TRAIL_MAXIMUM_STROKE_WIDTH, visual["trailMaximumStrokeWidth"])
        self.assertEqual(TRAIL_STROKE_SPEED_FACTOR, visual["trailStrokeSpeedFactor"])
        self.assertEqual(TRAIL_GLOW_WIDTH_MULTIPLIER, visual["trailGlowWidthMultiplier"])
        self.assertEqual(BURST_PARTICLE_RADIUS, visual["burstParticleRadius"])
        self.assertEqual(BURST_PARTICLE_GLOW_RADIUS, visual["burstParticleGlowRadius"])

    def test_visual_trail_width_is_bounded_and_speed_responsive(self):
        self.assertEqual(trail_stroke_width_for_speed(0.0), TRAIL_MINIMUM_STROKE_WIDTH)
        self.assertGreater(trail_stroke_width_for_speed(1_000.0), trail_stroke_width_for_speed(100.0))
        self.assertEqual(trail_stroke_width_for_speed(10_000.0), TRAIL_MAXIMUM_STROKE_WIDTH)

    def test_minimum_verified_concurrency_is_independent(self):
        model = RewardAnimationModel()
        count = GOLDEN["rewardFlight"]["minimumVerifiedConcurrentFlights"] + 8
        flights = [
            model.emit((float(index), float(index * 2)), f"#{index:06x}", now_ms=0.0)
            for index in range(count)
        ]

        self.assertEqual(model.active_count, count)
        self.assertEqual(len({flight.flight_id for flight in flights}), count)
        self.assertEqual(len({id(flight.trail) for flight in flights}), count)
        model.update(90.0, RewardPoint(1000.0, 500.0), pet_half_size=56.0)
        self.assertEqual(model.active_count, count)
        self.assertEqual(
            [flight.color for flight in model.flights],
            [f"#{index:06x}" for index in range(count)],
        )

    def test_spiral_angular_motion_accelerates_then_enters_homing(self):
        model = RewardAnimationModel()
        flight = model.emit((0.0, 0.0), STUDY_REWARD_COLOR, now_ms=0.0)
        angles = []
        for now_ms in (45.0, 90.0, 135.0):
            model.update(now_ms, RewardPoint(1000.0, 0.0), pet_half_size=10.0)
            angle = math.atan2(flight.position.y, flight.position.x)
            if angle < 0.0:
                angle += math.tau
            angles.append(angle)
        self.assertGreater(angles[2] - angles[1], angles[1] - angles[0])

        endpoint = GOLDEN["rewardFlightVectors"]["spiralEndpoint"]
        model.update(
            endpoint["elapsedMs"],
            RewardPoint(1000.0, 0.0),
            pet_half_size=10.0,
        )
        self.assertEqual(flight.phase, FlightPhase.HOMING)
        self.assertAlmostEqual(flight.speed, DEFAULT_CONFIG.homing_initial_speed)

    def test_spiral_endpoint_matches_shared_vector_exactly(self):
        vector = GOLDEN["rewardFlightVectors"]["spiralEndpoint"]
        source = RewardPoint(123.0, 234.0)
        model = RewardAnimationModel()
        flight = model.emit(source, STUDY_REWARD_COLOR, now_ms=0.0)

        model.update(
            vector["elapsedMs"],
            RewardPoint(1000.0, 1000.0),
            pet_half_size=10.0,
        )

        self.assertEqual(
            flight.position - source,
            RewardPoint(vector["relativeX"], vector["relativeY"]),
        )

    def test_homing_accelerates_and_resamples_a_moving_target(self):
        model = RewardAnimationModel()
        flight = model.emit((0.0, 0.0), STUDY_REWARD_COLOR, now_ms=0.0)
        model.update(180.0, RewardPoint(1000.0, 0.0), pet_half_size=10.0)
        initial_speed = flight.speed
        model.update(196.0, RewardPoint(1000.0, 0.0), pet_half_size=10.0)
        accelerated_speed = flight.speed
        model.update(212.0, RewardPoint(1000.0, 1000.0), pet_half_size=10.0)

        self.assertGreater(accelerated_speed, initial_speed)
        self.assertGreater(flight.velocity.y, 0.0)
        self.assertGreaterEqual(len(flight.trail), 2)

    def test_speed_related_trail_length_is_monotonic_and_bounded(self):
        self.assertEqual(trail_length_for_speed(0.0), 18.0)
        self.assertGreater(trail_length_for_speed(1000.0), trail_length_for_speed(100.0))
        self.assertEqual(trail_length_for_speed(10_000.0), 96.0)

    def test_trail_clip_interpolates_exact_shared_polyline_boundary(self):
        vector = GOLDEN["rewardFlightVectors"]["trailClip"]
        samples = [
            TrailSample(float(index), RewardPoint(float(x), 0.0))
            for index, x in enumerate(vector["inputX"])
        ]

        clipped = clip_trail_to_length(
            samples,
            trail_length_for_speed(vector["speed"]),
        )

        self.assertEqual(clipped[0].position.x, vector["expectedStartX"])
        self.assertEqual(clipped[-1].position.x, vector["expectedEndX"])
        self.assertEqual(trail_polyline_length(clipped), vector["expectedLength"])

    def test_swept_contact_creates_exactly_eighteen_independent_particles(self):
        model = RewardAnimationModel()
        flight = model.emit((0.0, 0.0), STUDY_REWARD_COLOR, now_ms=0.0)
        target = RewardPoint(100.0, 0.0)
        model.update(180.0, target, pet_half_size=10.0)
        for now_ms in range(196, 1000, 16):
            model.update(float(now_ms), target, pet_half_size=10.0)
            if flight.phase is FlightPhase.BURST:
                break

        self.assertEqual(flight.phase, FlightPhase.BURST)
        self.assertEqual(len(flight.particles), BURST_PARTICLE_COUNT)
        self.assertEqual(len({particle.velocity for particle in flight.particles}), 18)
        self.assertIsNotNone(flight.contact_point)
        self.assertLessEqual(flight.contact_point.distance_to(target), 16.000001)

        model.update(
            flight.burst_started_at_ms + DEFAULT_CONFIG.burst_duration_ms,
            target,
            pet_half_size=10.0,
        )
        self.assertEqual(model.active_count, 0)

    def test_missing_target_cancels_only_after_timeout(self):
        model = RewardAnimationModel()
        flight = model.emit((0.0, 0.0), STUDY_REWARD_COLOR, now_ms=0.0)
        model.update(100.0, None, pet_half_size=10.0)
        self.assertTrue(flight.active)
        model.update(
            100.0 + DEFAULT_CONFIG.missing_target_timeout_ms - 1.0,
            None,
            pet_half_size=10.0,
        )
        self.assertTrue(flight.active)
        model.update(
            100.0 + DEFAULT_CONFIG.missing_target_timeout_ms,
            None,
            pet_half_size=10.0,
        )
        self.assertFalse(flight.active)
        self.assertEqual(model.active_count, 0)

    def test_pointer_source_uses_press_coordinates_and_keyboard_uses_center(self):
        class Button:
            _reward_pointer_down = None

            @staticmethod
            def update_idletasks():
                pass

            @staticmethod
            def winfo_rootx():
                return 100

            @staticmethod
            def winfo_rooty():
                return 200

            @staticmethod
            def winfo_width():
                return 80

            @staticmethod
            def winfo_height():
                return 40

        app = object.__new__(LexiTrackApp)
        button = Button()
        event = type("Event", (), {
            "widget": button,
            "x_root": 123,
            "y_root": 234,
        })()

        app._remember_rating_pointer(event)
        self.assertEqual(app._rating_source_point(button), RewardPoint(123.0, 234.0))
        self.assertEqual(app._rating_source_point(button), RewardPoint(140.0, 220.0))

    def test_review_queue_advances_only_after_service_success(self):
        card = VocabularyEntry.create("focus", "专注", [])
        app = object.__new__(LexiTrackApp)
        app.review_queue = [card]
        app.review_answer_visible = True
        app.service = Mock()
        app.service.rate_review_card.side_effect = OSError("save failed")
        app._show_next_review_card = Mock()
        app._reward_effects = Mock()

        with self.assertRaises(OSError):
            app.rate_review_current(
                ReviewRating.AGAIN,
                RewardPoint(10.0, 20.0),
            )

        self.assertEqual(app.review_queue, [card])
        app._show_next_review_card.assert_not_called()
        app._reward_effects.emit.assert_not_called()


if __name__ == "__main__":
    unittest.main()
