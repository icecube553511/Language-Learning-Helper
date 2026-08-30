from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest


WINDOWS_DIR = Path(__file__).resolve().parents[1]
ROOT_DIR = WINDOWS_DIR.parent
sys.path.insert(0, str(WINDOWS_DIR))

from domain.pet_companion import (
    PetCompanion,
    PetMode,
    PetPoint,
    PetRect,
    PetState,
    PetTarget,
    PetTargetKind,
    advance_pet,
    begin_drag,
    move_drag,
    nearest_pet_target,
    on_navigation,
    release_drag,
)
from presentation.app import LexiTrackApp


class PetCompanionTests(unittest.TestCase):
    def test_semantic_widget_id_survives_virtualized_widget_recreation(self):
        class VirtualWidget:
            pet_target_id = "dictation-selection:entry-42"

        first = VirtualWidget()
        second = VirtualWidget()

        self.assertEqual(
            LexiTrackApp._pet_widget_id(None, first, "dictation"),
            "dictation:dictation-selection:entry-42",
        )
        self.assertEqual(
            LexiTrackApp._pet_widget_id(None, second, "dictation"),
            LexiTrackApp._pet_widget_id(None, first, "dictation"),
        )

    def test_shared_golden_vectors(self):
        golden = json.loads(
            (ROOT_DIR / "shared" / "contracts" / "pet-companion-golden-v1.json").read_text(encoding="utf-8")
        )
        control = [
            PetTarget(
                item["id"],
                PetTargetKind(item["kind"]),
                PetRect(*item["rect"]),
            )
            for item in golden["vectors"][0]["targets"]
        ]
        self.assertEqual(
            nearest_pet_target(PetPoint(*golden["vectors"][0]["position"]), control).id,
            golden["vectors"][0]["expectedTarget"],
        )

        navigation = PetState(PetPoint(10, 20), PetMode.SLIDE, "chart")
        self.assertEqual(on_navigation(navigation).mode.value, "fall")

        drag = PetState(PetPoint(*golden["vectors"][2]["position"]))
        dragging = begin_drag(drag, PetPoint(*golden["vectors"][2]["release"]))
        released = release_drag(dragging)
        self.assertEqual(released.position, PetPoint(*golden["vectors"][2]["release"]))
        self.assertTrue(golden["drag"]["preserveGrabOffset"])
        behaviors = {vector["name"]: vector for vector in golden["behaviorVectors"]}
        self.assertEqual(
            set(behaviors),
            {
                "surface-inside-moves-to-border",
                "border-rolls-clockwise",
                "chart-path-reverses",
                "flight-is-vertical-first",
                "navigation-prefers-below",
            },
        )

        def target_from(item):
            return PetTarget(
                item["id"],
                PetTargetKind(item["kind"]),
                PetRect(*item["rect"]),
                tuple(PetPoint(*point) for point in item.get("path", [])),
            )

        viewport = PetRect(0, 0, 800, 700)
        surface = behaviors["surface-inside-moves-to-border"]
        surface_result = advance_pet(
            PetState(PetPoint(*surface["position"])),
            [target_from(surface["target"])],
            viewport,
            speed=surface["step"],
        )
        self.assertEqual(surface_result.position, PetPoint(*surface["expectedPosition"]))
        self.assertEqual(surface_result.mode.value, surface["expectedMode"])

        rolling = behaviors["border-rolls-clockwise"]
        rolling_target = target_from(rolling["target"])
        rolling_result = advance_pet(
            PetState(PetPoint(*rolling["position"]), target_id=rolling_target.id),
            [rolling_target],
            viewport,
            speed=rolling["step"],
        )
        self.assertEqual(rolling_result.mode.value, rolling["expectedMode"])

        chart = behaviors["chart-path-reverses"]
        chart_target = target_from(chart["target"])
        chart_state = PetState(PetPoint(*chart["position"]))
        chart_modes = []
        reversed_path = False
        for _ in range(chart["ticks"]):
            chart_state = advance_pet(chart_state, [chart_target], viewport, speed=chart["step"])
            chart_modes.append(chart_state.mode.value)
            reversed_path = reversed_path or chart_state.path_direction < 0
        self.assertIn(chart["expectedMode"], chart_modes)
        self.assertEqual(reversed_path, chart["mustReverse"])

        flight = behaviors["flight-is-vertical-first"]
        flight_result = advance_pet(
            PetState(PetPoint(*flight["position"]), PetMode(flight["mode"])),
            [target_from(flight["target"])],
            viewport,
            speed=flight["step"],
        )
        self.assertEqual(flight_result.position, PetPoint(*flight["expectedPosition"]))
        self.assertEqual(flight_result.mode.value, flight["expectedMode"])

        falling = behaviors["navigation-prefers-below"]
        falling_result = advance_pet(
            on_navigation(PetState(PetPoint(*falling["position"]))),
            [target_from(item) for item in falling["targets"]],
            viewport,
            speed=falling["step"],
        )
        self.assertEqual(falling_result.target_id, falling["expectedTarget"])
        self.assertEqual(falling_result.position, PetPoint(*falling["expectedPosition"]))

    def test_nearest_target_skips_invalid_and_preserves_registration_tie(self):
        position = PetPoint(50, 50)
        targets = [
            PetTarget("hidden", PetTargetKind.CONTROL, PetRect(50, 50, 10, 10), visible=False),
            PetTarget("first", PetTargetKind.SURFACE, PetRect(0, 0, 20, 20)),
            PetTarget("second", PetTargetKind.SURFACE, PetRect(80, 0, 20, 20)),
        ]
        self.assertEqual(nearest_pet_target(position, targets).id, "first")

    def test_position_inside_panel_still_targets_its_border(self):
        target = PetTarget("panel", PetTargetKind.SURFACE, PetRect(0, 0, 100, 80))
        self.assertEqual(target.distance_to(PetPoint(50, 40)), 40)
        moved = advance_pet(
            PetState(PetPoint(50, 40)),
            [target],
            PetRect(0, 0, 120, 100),
            speed=5,
        )
        self.assertEqual(moved.position, PetPoint(50, 35))
        self.assertEqual(moved.mode, PetMode.FLY)

    def test_drag_is_clamped_and_non_dragging_state_is_unchanged(self):
        viewport = PetRect(0, 0, 100, 80)
        state = begin_drag(PetState(PetPoint(10, 10)), PetPoint(10, 10))
        moved = move_drag(state, PetPoint(-20, 100), viewport, pet_size=10)
        self.assertEqual(moved.position, PetPoint(10, 70))
        self.assertEqual(move_drag(release_drag(moved), PetPoint(90, 90), viewport).position, moved.position)

    def test_chart_path_advances_in_slide_mode(self):
        target = PetTarget(
            "curve",
            PetTargetKind.CHART,
            PetRect(0, 0, 100, 100),
            path=(PetPoint(10, 20), PetPoint(20, 30), PetPoint(30, 40)),
        )
        state = advance_pet(
            PetState(PetPoint(10, 20)),
            [target],
            PetRect(0, 0, 100, 100),
            speed=4,
        )
        self.assertEqual(state.mode, PetMode.SLIDE)
        self.assertEqual(state.target_id, "curve")

    def test_chart_curve_and_border_targets_support_distinct_motion(self):
        curve = PetTarget(
            "memory-chart",
            PetTargetKind.CHART,
            PetRect(10, 10, 80, 60),
            path=(PetPoint(30, 30), PetPoint(50, 40), PetPoint(70, 30)),
        )
        border = PetTarget(
            "memory-chart:border",
            PetTargetKind.SURFACE,
            curve.rect,
        )
        sliding = advance_pet(
            PetState(PetPoint(30, 30)),
            [curve, border],
            PetRect(0, 0, 100, 80),
            speed=5,
        )
        rolling = advance_pet(
            PetState(PetPoint(40, 10), target_id=border.id),
            [curve, border],
            PetRect(0, 0, 100, 80),
            speed=5,
        )

        self.assertEqual((sliding.target_id, sliding.mode), (curve.id, PetMode.SLIDE))
        self.assertEqual((rolling.target_id, rolling.mode), (border.id, PetMode.ROLL))

    def test_chart_path_reverses_at_both_ends_instead_of_stopping(self):
        target = PetTarget(
            "curve",
            PetTargetKind.CHART,
            PetRect(0, 0, 40, 40),
            path=(PetPoint(10, 10), PetPoint(20, 20), PetPoint(30, 10)),
        )
        next_target = PetTarget("next", PetTargetKind.CONTROL, PetRect(35, 20, 4, 4))
        state = PetState(PetPoint(10, 10))
        directions = []
        completed_cycle = False
        for _ in range(12):
            state = advance_pet(state, [target, next_target], PetRect(0, 0, 40, 40), speed=30)
            directions.append(state.path_direction)
            if state.avoid_target_id == "curve":
                completed_cycle = True
                break
        self.assertIn(-1, directions)
        self.assertTrue(completed_cycle)
        for _ in range(12):
            state = advance_pet(state, [target, next_target], PetRect(0, 0, 40, 40), speed=30)
        self.assertEqual(state.target_id, "next")

    def test_pet_rolls_clockwise_on_horizontal_and_vertical_borders(self):
        target = PetTarget("control", PetTargetKind.CONTROL, PetRect(20, 20, 60, 30))
        horizontal = advance_pet(
            PetState(PetPoint(40, 20), PetMode.IDLE, "control"),
            [target],
            PetRect(0, 0, 120, 100),
            speed=5,
        )
        self.assertEqual(horizontal.mode, PetMode.ROLL)
        self.assertGreater(horizontal.position.x, 40)
        vertical = advance_pet(
            PetState(PetPoint(80, 30), PetMode.IDLE, "control"),
            [target],
            PetRect(0, 0, 120, 100),
            speed=5,
        )
        self.assertEqual(vertical.mode, PetMode.ROLL)
        self.assertGreater(vertical.position.y, 30)

    def test_arrival_idles_briefly_then_continues_rolling(self):
        target = PetTarget("panel", PetTargetKind.SURFACE, PetRect(20, 20, 60, 30))
        state = advance_pet(
            PetState(PetPoint(50, 10)),
            [target],
            PetRect(0, 0, 120, 100),
            speed=20,
        )
        self.assertEqual(state.mode, PetMode.IDLE)
        self.assertGreater(state.idle_ticks_remaining, 0)
        paused_at = state.position
        for _ in range(10):
            state = advance_pet(state, [target], PetRect(0, 0, 120, 100), speed=5)
        self.assertEqual(state.position, paused_at)
        state = advance_pet(state, [target], PetRect(0, 0, 120, 100), speed=5)
        self.assertEqual(state.mode, PetMode.ROLL)
        self.assertNotEqual(state.position, paused_at)

    def test_completed_border_lap_moves_to_the_nearest_other_target(self):
        first = PetTarget("first", PetTargetKind.SURFACE, PetRect(20, 20, 20, 20))
        second = PetTarget("second", PetTargetKind.CONTROL, PetRect(60, 20, 20, 20))
        state = PetState(PetPoint(30, 20), PetMode.ROLL, "first")
        for _ in range(4):
            state = advance_pet(state, [first, second], PetRect(0, 0, 100, 80), speed=100)
        self.assertEqual(state.avoid_target_id, "first")
        self.assertIsNone(state.target_id)
        for _ in range(12):
            state = advance_pet(state, [first, second], PetRect(0, 0, 100, 80), speed=100)
        self.assertEqual(state.target_id, "second")

    def test_flight_moves_vertically_before_horizontal_correction(self):
        target = PetTarget("button", PetTargetKind.CONTROL, PetRect(80, 70, 20, 20))
        moved = advance_pet(
            PetState(PetPoint(10, 10), PetMode.FALL),
            [target],
            PetRect(0, 0, 120, 120),
            speed=5,
        )
        self.assertEqual(moved.position.x, 10)
        self.assertGreater(moved.position.y, 10)
        self.assertEqual(moved.mode, PetMode.FALL)

    def test_navigation_fall_prefers_a_target_below(self):
        targets = [
            PetTarget("above", PetTargetKind.CONTROL, PetRect(40, 0, 20, 10)),
            PetTarget("below", PetTargetKind.CONTROL, PetRect(40, 80, 20, 10)),
        ]
        state = advance_pet(
            on_navigation(PetState(PetPoint(50, 50), PetMode.ROLL, "above")),
            targets,
            PetRect(0, 0, 100, 100),
            speed=5,
        )
        self.assertEqual(state.target_id, "below")
        self.assertEqual(state.position, PetPoint(50, 55))

    def test_reducer_wrapper_keeps_navigation_and_release_semantics(self):
        companion = PetCompanion(PetState(PetPoint(20, 20)), speed=4, pet_size=4)
        self.assertEqual(companion.navigate().mode, PetMode.FALL)
        companion.drag_start(PetPoint(40, 50))
        companion.drag_move(PetPoint(500, 600), PetRect(0, 0, 800, 700))
        self.assertEqual(companion.drag_release().position, PetPoint(500, 600))


if __name__ == "__main__":
    unittest.main()
