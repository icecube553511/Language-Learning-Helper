from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from domain.pet_companion import (
    PetCompanion, PetFacing, PetMode, PetPoint, PetRect, PetState, PetTarget,
    PetTargetKind, advance_pet, estimate_release_velocity,
)
from presentation.app import LexiTrackApp, preserve_pet_motion_for_targets
from presentation.widgets import PetOverlay


class PetMotionStabilityTests(unittest.TestCase):
    viewport = PetRect(0, 0, 500, 500)

    @classmethod
    def setUpClass(cls):
        golden_path = Path(__file__).resolve().parents[2] / "shared/contracts/pet-companion-golden-v1.json"
        golden = json.loads(golden_path.read_text(encoding="utf-8"))
        cls.stability_vectors = {item["name"]: item for item in golden["motionStabilityVectors"]}

    def test_lost_or_moved_support_falls_before_idle_countdown(self):
        for mode in (PetMode.IDLE, PetMode.ROLL, PetMode.SLIDE):
            for targets in ([], [PetTarget(
                "support", PetTargetKind.SURFACE, PetRect(0, 200, 400, 20),
            )]):
                with self.subTest(mode=mode, missing=not targets):
                    state = PetState(
                        PetPoint(100, 100), mode, target_id="support",
                        idle_ticks_remaining=20, curve_velocity=2.0,
                        path_index=3, path_direction=-1,
                    )
                    advanced = advance_pet(state, targets, self.viewport)
                    self.assertEqual(advanced.mode, PetMode.FALL)
                    self.assertEqual(advanced.position.x, 100)
                    self.assertAlmostEqual(advanced.position.y, 100.44)
                    self.assertEqual(advanced.idle_ticks_remaining, 0)
                    self.assertEqual(advanced.path_index, 0)
                    self.assertIsNone(advanced.curve_velocity)

    def test_subpixel_support_motion_keeps_contact(self):
        support = PetTarget("support", PetTargetKind.SURFACE, PetRect(0, 100.4, 400, 20))
        state = PetState(PetPoint(100, 100), PetMode.IDLE, target_id="support", idle_ticks_remaining=20)
        advanced = advance_pet(state, [support], self.viewport)
        self.assertEqual(advanced.mode, PetMode.IDLE)
        self.assertEqual(advanced.position, state.position)
        self.assertEqual(advanced.idle_ticks_remaining, 19)

    def test_target_refresh_preserves_domain_contact_history(self):
        state = PetState(PetPoint(100, 100), PetMode.ROLL, target_id="removed")
        self.assertIs(preserve_pet_motion_for_targets(state, []), state)

    def test_missing_fling_target_keeps_projectile_momentum(self):
        state = PetState(
            PetPoint(100, 100), PetMode.FLING, target_id="removed",
            horizontal_velocity=200, vertical_velocity=-100,
        )
        advanced = advance_pet(state, [], self.viewport)
        self.assertEqual(advanced.mode, PetMode.FLING)
        self.assertAlmostEqual(advanced.position.x, 103.2)
        self.assertAlmostEqual(advanced.position.y, 98.84)
        self.assertAlmostEqual(advanced.horizontal_velocity, 200)
        self.assertAlmostEqual(advanced.vertical_velocity, -45)

    def test_orphan_bounce_keeps_signed_upward_arc(self):
        unrelated = PetTarget("upper", PetTargetKind.SURFACE, PetRect(0, 40, 400, 20))
        for target_id in (None, "removed"):
            with self.subTest(target_id=target_id):
                state = PetState(
                    PetPoint(100, 220), PetMode.BOUNCE, target_id=target_id,
                    vertical_velocity=-200, bounces_remaining=2,
                )
                advanced = advance_pet(state, [unrelated], self.viewport)
                self.assertEqual(advanced.mode, PetMode.FLING)
                self.assertAlmostEqual(advanced.position.y, 217.24)
                self.assertAlmostEqual(advanced.vertical_velocity, -145)

    def test_moved_bounce_support_cannot_teleport_at_apex(self):
        for rect in (PetRect(0, 40, 400, 20), PetRect(300, 300, 100, 20)):
            with self.subTest(rect=rect):
                support = PetTarget("support", PetTargetKind.SURFACE, rect)
                state = PetState(
                    PetPoint(100, 220), PetMode.BOUNCE, target_id="support",
                    vertical_velocity=-50, bounces_remaining=2,
                )
                advanced = advance_pet(state, [support], self.viewport)
                self.assertEqual(advanced.mode, PetMode.FLING)
                self.assertAlmostEqual(advanced.position.x, 100)
                self.assertAlmostEqual(advanced.position.y, 219.64)
                self.assertAlmostEqual(advanced.vertical_velocity, 5)

    def test_invalid_bounce_support_allows_same_tick_replacement_collision(self):
        replacement = PetTarget("replacement", PetTargetKind.SURFACE, PetRect(0, 220, 400, 20))
        for old_rect in (PetRect(0, 40, 400, 20), PetRect(300, 300, 100, 20)):
            with self.subTest(old_rect=old_rect):
                old_support = PetTarget("old", PetTargetKind.SURFACE, old_rect)
                state = PetState(
                    PetPoint(100, 219.9), PetMode.BOUNCE, target_id="old",
                    vertical_velocity=10, bounces_remaining=2,
                )
                advanced = advance_pet(state, [old_support, replacement], self.viewport)
                self.assertEqual(advanced.mode, PetMode.IDLE)
                self.assertEqual(advanced.target_id, "replacement")
                self.assertEqual(advanced.position, PetPoint(100, 220))
                self.assertEqual(advanced.vertical_velocity, 0)

    def test_bounce_retains_edge_anchor_when_nearby_content_exists(self):
        edge = PetTarget("edge", PetTargetKind.EDGE, PetRect(0, 240, 500, 3))
        content = PetTarget("content", PetTargetKind.SURFACE, PetRect(90, 230, 40, 10))
        state = PetState(
            PetPoint(100, 220), PetMode.BOUNCE, target_id="edge",
            vertical_velocity=10, bounces_remaining=2,
        )
        advanced = advance_pet(state, [edge, content], self.viewport)
        self.assertEqual(advanced.mode, PetMode.BOUNCE)
        self.assertEqual(advanced.target_id, "edge")
        self.assertAlmostEqual(advanced.position.y, 220.6)
        self.assertEqual(advanced.vertical_velocity, 65)

    def test_falling_onto_partly_outside_curve_keeps_x_and_original_geometry(self):
        target = PetTarget(
            "curve", PetTargetKind.CHART, self.viewport,
            (PetPoint(0, 100), PetPoint(100, 200)),
        )
        state = PetState(PetPoint(80, 123.9), PetMode.FALL, vertical_velocity=10)
        state = advance_pet(state, [target], self.viewport, pet_size=56)
        self.assertEqual(state.mode, PetMode.SLIDE)
        self.assertAlmostEqual(state.position.x, 80)
        self.assertAlmostEqual(state.position.y, 124)
        for _ in range(5):
            state = advance_pet(state, [target], self.viewport, pet_size=56)
            self.assertEqual(state.mode, PetMode.SLIDE)
            self.assertAlmostEqual(state.position.y - state.position.x, 44)

    def test_outside_curve_contact_is_not_clamped_to_viewport(self):
        target = PetTarget(
            "curve", PetTargetKind.CHART, self.viewport,
            (PetPoint(0, 40), PetPoint(200, 40)),
        )
        for mode in (PetMode.FALL, PetMode.FLING):
            with self.subTest(mode=mode):
                state = PetState(
                    PetPoint(80, -16.1), mode,
                    vertical_velocity=10,
                )
                advanced = advance_pet(state, [target], self.viewport, pet_size=56)
                self.assertEqual(advanced.mode, mode)
                self.assertIsNone(advanced.target_id)
                self.assertAlmostEqual(advanced.position.y, -15.5)

    def test_curve_viewport_boundary_stays_on_original_segment(self):
        target = PetTarget(
            "curve", PetTargetKind.CHART, self.viewport,
            (PetPoint(0, 100), PetPoint(200, 300)),
        )
        state = PetState(
            PetPoint(56.1, 100.1), PetMode.SLIDE, target_id="curve",
            curve_velocity=-8, path_index=0, path_direction=-1,
        )
        advanced = advance_pet(state, [target], self.viewport, pet_size=56)
        self.assertAlmostEqual(advanced.position.x, 56)
        self.assertAlmostEqual(advanced.position.y, 100)
        self.assertEqual(advanced.mode, PetMode.SLIDE)
        self.assertEqual(advanced.path_direction, 1)
        self.assertEqual(advanced.curve_velocity, 0)

    def test_curve_bounce_returns_to_physical_sliding(self):
        target = PetTarget(
            "curve", PetTargetKind.CHART, self.viewport,
            (PetPoint(20, 100), PetPoint(200, 200)),
        )
        state = PetState(
            PetPoint(110, 149.9), PetMode.BOUNCE, target_id="curve",
            vertical_velocity=10, bounces_remaining=1,
        )
        advanced = advance_pet(state, [target], self.viewport)
        self.assertEqual(advanced.mode, PetMode.SLIDE)
        self.assertAlmostEqual(advanced.position.x, 110)
        self.assertAlmostEqual(advanced.position.y, 150)
        self.assertEqual(advanced.curve_velocity, 0)
        self.assertEqual(advanced.idle_ticks_remaining, 0)

    def test_flat_curve_does_not_accelerate_and_slopes_scale_gravity(self):
        vector = self.stability_vectors["steeper-slopes-have-stronger-gravity"]
        velocities = []
        for tangent, expected in zip(vector["unitTangents"], vector["expectedNextCurveVelocities"]):
            target = PetTarget(
                "curve", PetTargetKind.CHART, self.viewport,
                (PetPoint(100, 100), PetPoint(100 + 200 * tangent[0], 100 + 200 * tangent[1])),
            )
            state = PetState(
                PetPoint(100 + 100 * tangent[0], 100 + 100 * tangent[1]), PetMode.SLIDE,
                target_id="curve", curve_velocity=vector["initialCurveVelocity"], path_index=1,
            )
            advanced = advance_pet(state, [target], self.viewport)
            velocities.append(advanced.curve_velocity)
            self.assertAlmostEqual(advanced.curve_velocity, expected)
            if tangent[1] == 0:
                self.assertEqual(advanced.position, state.position)
        self.assertEqual(velocities[0], 0.0)
        self.assertGreater(velocities[1], 0.0)
        self.assertGreater(velocities[2], velocities[1])

    def test_low_speed_valley_stays_at_rest_without_facing_flicker(self):
        vector = self.stability_vectors["low-energy-valley-remains-at-rest"]
        target = PetTarget(
            "valley", PetTargetKind.CHART, self.viewport,
            tuple(PetPoint(*point) for point in vector["path"]),
        )
        state = PetState(
            PetPoint(*vector["position"]), PetMode.SLIDE, target_id="valley",
            curve_velocity=vector["curveVelocity"], path_index=1, facing=PetFacing.LEFT,
        )
        changes = 0
        for _ in range(vector["ticks"]):
            previous_facing = state.facing
            state = advance_pet(state, [target], self.viewport)
            changes += state.facing != previous_facing
            self.assertEqual(state.position, PetPoint(*vector["expectedPosition"]))
            self.assertEqual(state.curve_velocity, vector["expectedCurveVelocity"])
        self.assertEqual(changes, vector["expectedFacingChanges"])

    def test_fast_valley_crossing_uses_outgoing_tangent_and_keeps_inertia(self):
        target = PetTarget(
            "valley", PetTargetKind.CHART, self.viewport,
            (PetPoint(20, 100), PetPoint(100, 180), PetPoint(180, 100)),
        )
        state = PetState(
            PetPoint(100, 180), PetMode.SLIDE, target_id="valley",
            curve_velocity=3.0, path_index=2, path_direction=1,
        )
        advanced = advance_pet(state, [target], self.viewport)
        self.assertGreater(advanced.position.x, 100)
        self.assertLess(advanced.position.y, 180)
        self.assertGreater(advanced.curve_velocity, 0)
        self.assertLess(advanced.curve_velocity, 3.0 * 0.875)

    def test_valley_approach_dissipates_inertia_and_settles(self):
        target = PetTarget(
            "valley", PetTargetKind.CHART, self.viewport,
            (PetPoint(20, 50), PetPoint(100, 130), PetPoint(180, 50)),
        )
        state = PetState(
            PetPoint(98, 128), PetMode.SLIDE, target_id="valley",
            curve_velocity=0.1, path_index=1,
        )
        for _ in range(180):
            state = advance_pet(state, [target], self.viewport)
        self.assertEqual(state.position, PetPoint(100, 130))
        self.assertEqual(state.curve_velocity, 0)
        resting_facing = state.facing
        for _ in range(60):
            state = advance_pet(state, [target], self.viewport)
            self.assertEqual(state.position, PetPoint(100, 130))
            self.assertEqual(state.facing, resting_facing)

    def test_pause_before_release_discards_stale_velocity(self):
        vector = self.stability_vectors["held-release-discards-old-motion"]
        self.assertEqual(
            estimate_release_velocity(vector["samples"], now_ms=vector["nowMs"]),
            PetPoint(*vector["expectedVelocity"]),
        )
        samples = [(0.0, PetPoint(0, 0)), (10.0, PetPoint(20, 0)), (500.0, PetPoint(20, 0))]
        self.assertEqual(estimate_release_velocity(samples), PetPoint(0, 0))
        self.assertEqual(estimate_release_velocity(samples[:2], now_ms=500), PetPoint(0, 0))

    def test_drag_press_uses_visible_position_as_anchor(self):
        app = LexiTrackApp.__new__(LexiTrackApp)
        app._cancel_main_pet_render = Mock()
        app._pet_pointer = Mock(return_value=PetPoint(80, 100))
        app._record_pet_sample = Mock()
        app._grab_pet_overlay = Mock()
        app._pet_overlay = Mock()
        app._pet_last_rendered_position = PetPoint(90, 110)
        app.pet_companion = PetCompanion(PetState(PetPoint(100, 120)))
        app._pet_press(object())
        self.assertEqual(app.pet_companion.state.position, PetPoint(90, 110))
        self.assertEqual(app._pet_drag_offset, PetPoint(10, 10))

    def test_late_render_uses_elapsed_clock_and_invalidated_frames_do_not_rewind(self):
        app = LexiTrackApp.__new__(LexiTrackApp)
        app._pet_overlay = Mock()
        app._pet_render_generation = 0
        app._pet_render_after_ids = []
        app._pet_last_rendered_position = PetPoint(10, 10)
        app._dialog_pet_stack = []
        app.after_cancel = Mock()
        app._place_pet_overlay = Mock()
        callbacks = []
        app.after = lambda delay, callback: callbacks.append(callback) or str(len(callbacks))
        now = [1000.0]
        app._pet_now_ms = lambda: now[0]
        state = PetState(PetPoint(100, 100), PetMode.FALL)
        app._schedule_main_pet_render(state, PetPoint(10, 10))
        now[0] += 32
        callbacks[0]()
        self.assertEqual(app._pet_last_rendered_position, state.position)
        app._cancel_main_pet_render()
        app._pet_last_rendered_position = PetPoint(200, 200)
        callbacks[-1]()
        self.assertEqual(app._pet_last_rendered_position, PetPoint(200, 200))

    def test_repeated_overlay_frame_does_not_restack_or_resize_window(self):
        overlay = PetOverlay.__new__(PetOverlay)
        overlay._display_size = 112
        overlay._last_geometry = None
        overlay.master = Mock()
        overlay.master.winfo_rootx.return_value = 20
        overlay.master.winfo_rooty.return_value = 30
        overlay.geometry = Mock()
        overlay.state = Mock(return_value="normal")
        overlay.lift = Mock()
        overlay.place(x=10, y=20)
        overlay.place(x=10, y=20)
        overlay.geometry.assert_called_once_with("112x112+30+50")
        overlay.lift.assert_not_called()


if __name__ == "__main__":
    unittest.main()
