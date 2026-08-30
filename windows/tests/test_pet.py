from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest


WINDOWS_DIR = Path(__file__).resolve().parents[1]
ROOT_DIR = WINDOWS_DIR.parent
sys.path.insert(0, str(WINDOWS_DIR))

from domain.pet_companion import (
    BOUNCE_DECAY,
    BOUNCE_COUNT,
    CRUISE_SPEED,
    FALL_GRAVITY,
    IDLE_TICKS,
    MAX_FALL_SPEED,
    MOTION_ACCELERATION,
    PET_DISPLAY_SIZE,
    PET_TICK_MS,
    PetCompanion,
    PetFacing,
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


def assert_point(test: unittest.TestCase, actual: PetPoint, expected: list[float]) -> None:
    test.assertAlmostEqual(actual.x, expected[0])
    test.assertAlmostEqual(actual.y, expected[1])


class PetCompanionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.golden = json.loads(
            (ROOT_DIR / "shared" / "contracts" / "pet-companion-golden-v1.json").read_text(
                encoding="utf-8"
            )
        )

    @staticmethod
    def target_from(item) -> PetTarget:
        return PetTarget(
            item["id"],
            PetTargetKind(item["kind"]),
            PetRect(*item["rect"]),
            tuple(PetPoint(*point) for point in item.get("path", [])),
        )

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

    def test_shared_identity_and_motion_constants(self):
        golden = self.golden
        motion = golden["motion"]
        self.assertEqual(golden["tickMs"], PET_TICK_MS)
        self.assertEqual(golden["displaySize"], PET_DISPLAY_SIZE)
        self.assertEqual(golden["modes"], [mode.value for mode in PetMode])
        self.assertEqual(golden["facings"], [facing.value for facing in PetFacing])
        self.assertEqual(motion["acceleration"], MOTION_ACCELERATION)
        self.assertEqual(motion["cruiseSpeed"], CRUISE_SPEED)
        self.assertEqual(motion["fallGravity"], FALL_GRAVITY)
        self.assertEqual(motion["maxFallSpeed"], MAX_FALL_SPEED)
        self.assertEqual(motion["bounceCount"], BOUNCE_COUNT)
        self.assertEqual(motion["bounceDecay"], BOUNCE_DECAY)
        self.assertEqual(motion["idleTicks"], IDLE_TICKS)
        self.assertEqual(motion["supportSide"], "upper")
        self.assertTrue(motion["horizontalFlip"])

    def test_shared_basic_vectors(self):
        golden = self.golden
        nearest = golden["vectors"][0]
        targets = [self.target_from(item) for item in nearest["targets"]]
        self.assertEqual(
            nearest_pet_target(PetPoint(*nearest["position"]), targets).id,
            nearest["expectedTarget"],
        )
        navigation = PetState(PetPoint(10, 20), PetMode.SLIDE, "chart")
        self.assertEqual(on_navigation(navigation).mode.value, golden["vectors"][1]["expectedMode"])
        drag = golden["vectors"][2]
        dragging = begin_drag(PetState(PetPoint(*drag["position"])), PetPoint(*drag["release"]))
        released = release_drag(dragging)
        assert_point(self, released.position, drag["expectedPosition"])
        self.assertTrue(golden["drag"]["preserveGrabOffset"])

    def test_shared_behavior_vectors(self):
        behaviors = {vector["name"]: vector for vector in self.golden["behaviorVectors"]}
        self.assertEqual(
            set(behaviors),
            {
                "surface-inside-moves-to-upper-support",
                "upper-support-reverses",
                "vertical-screen-edge-remains-traversable",
                "horizontal-edge-moves-to-upper-support",
                "chart-path-reverses",
                "flight-is-vertical-first",
                "navigation-prefers-below",
                "navigation-fallback-ignores-center-bias",
                "fall-accelerates",
                "hard-landing-bounces-twice",
                "center-bias-prefers-interior",
                "center-bias-measures-nearest-support",
            },
        )
        viewport = PetRect(0, 0, 800, 700)

        surface = behaviors["surface-inside-moves-to-upper-support"]
        surface_result = advance_pet(
            PetState(PetPoint(*surface["position"])),
            [self.target_from(surface["target"])],
            viewport,
            speed=surface["step"],
        )
        assert_point(self, surface_result.position, surface["expectedPosition"])
        self.assertEqual(surface_result.mode.value, surface["expectedMode"])

        upper = behaviors["upper-support-reverses"]
        upper_target = self.target_from(upper["target"])
        upper_result = advance_pet(
            PetState(
                PetPoint(*upper["position"]),
                target_id=upper_target.id,
                movement_speed=upper["movementSpeed"],
            ),
            [upper_target],
            viewport,
            speed=upper["step"],
        )
        assert_point(self, upper_result.position, upper["expectedPosition"])
        self.assertEqual(upper_result.mode.value, upper["expectedMode"])
        self.assertEqual(upper_result.facing.value, upper["expectedFacing"])

        vertical_edge = behaviors["vertical-screen-edge-remains-traversable"]
        edge_target = self.target_from(vertical_edge["target"])
        edge_result = advance_pet(
            PetState(
                PetPoint(*vertical_edge["position"]),
                target_id=edge_target.id,
                movement_speed=vertical_edge["movementSpeed"],
            ),
            [edge_target],
            viewport,
            speed=vertical_edge["step"],
        )
        assert_point(self, edge_result.position, vertical_edge["expectedPosition"])
        self.assertEqual(edge_result.mode.value, vertical_edge["expectedMode"])

        horizontal_edge = behaviors["horizontal-edge-moves-to-upper-support"]
        horizontal_result = advance_pet(
            PetState(PetPoint(*horizontal_edge["position"])),
            [self.target_from(horizontal_edge["target"])],
            viewport,
            speed=horizontal_edge["step"],
        )
        assert_point(self, horizontal_result.position, horizontal_edge["expectedPosition"])
        self.assertEqual(horizontal_result.mode.value, horizontal_edge["expectedMode"])

        chart = behaviors["chart-path-reverses"]
        chart_target = self.target_from(chart["target"])
        chart_state = PetState(PetPoint(*chart["position"]))
        reversed_path = False
        for _ in range(chart["ticks"]):
            chart_state = advance_pet(chart_state, [chart_target], viewport, speed=chart["step"])
            reversed_path = reversed_path or chart_state.path_direction < 0
        self.assertEqual(chart_state.mode.value, chart["expectedMode"])
        self.assertEqual(reversed_path, chart["mustReverse"])

        flight = behaviors["flight-is-vertical-first"]
        flight_result = advance_pet(
            PetState(
                PetPoint(*flight["position"]),
                PetMode(flight["mode"]),
                movement_speed=flight["movementSpeed"],
            ),
            [self.target_from(flight["target"])],
            viewport,
            speed=flight["step"],
        )
        assert_point(self, flight_result.position, flight["expectedPosition"])
        self.assertEqual(flight_result.mode.value, flight["expectedMode"])

        navigation = behaviors["navigation-prefers-below"]
        navigation_result = advance_pet(
            on_navigation(PetState(PetPoint(*navigation["position"]))),
            [self.target_from(item) for item in navigation["targets"]],
            viewport,
            speed=navigation["step"],
        )
        self.assertEqual(navigation_result.target_id, navigation["expectedTarget"])
        assert_point(self, navigation_result.position, navigation["expectedPosition"])

        fallback = behaviors["navigation-fallback-ignores-center-bias"]
        fallback_viewport = PetRect(0, 0, *fallback["viewport"])
        fallback_result = advance_pet(
            on_navigation(PetState(PetPoint(*fallback["position"]))),
            [self.target_from(item) for item in fallback["targets"]],
            fallback_viewport,
        )
        self.assertEqual(fallback_result.target_id, fallback["expectedTarget"])

        falling = behaviors["fall-accelerates"]
        falling_target = self.target_from(falling["target"])
        falling_result = advance_pet(
            PetState(
                PetPoint(*falling["position"]),
                PetMode(falling["mode"]),
                vertical_velocity=falling["verticalVelocity"],
            ),
            [falling_target],
            viewport,
            speed=falling["step"],
        )
        assert_point(self, falling_result.position, falling["expectedPosition"])
        self.assertAlmostEqual(falling_result.vertical_velocity, falling["expectedVerticalVelocity"])
        self.assertEqual(falling_result.mode.value, falling["expectedMode"])

        hard = behaviors["hard-landing-bounces-twice"]
        hard_target = self.target_from(hard["target"])
        hard_result = advance_pet(
            PetState(
                PetPoint(*hard["position"]),
                PetMode(hard["mode"]),
                vertical_velocity=hard["verticalVelocity"],
            ),
            [hard_target],
            viewport,
            speed=hard["step"],
        )
        assert_point(self, hard_result.position, hard["expectedPosition"])
        self.assertEqual(hard_result.mode.value, hard["expectedMode"])
        self.assertEqual(hard_result.bounces_remaining, hard["expectedBouncesRemaining"])

        centre = behaviors["center-bias-prefers-interior"]
        centre_viewport = PetRect(0, 0, *centre["viewport"])
        selected = nearest_pet_target(
            PetPoint(*centre["position"]),
            [self.target_from(item) for item in centre["targets"]],
            viewport=centre_viewport,
        )
        self.assertEqual(selected.id, centre["expectedTarget"])

        nearest_support = behaviors["center-bias-measures-nearest-support"]
        support_viewport = PetRect(0, 0, *nearest_support["viewport"])
        selected = nearest_pet_target(
            PetPoint(*nearest_support["position"]),
            [self.target_from(item) for item in nearest_support["targets"]],
            viewport=support_viewport,
        )
        self.assertEqual(selected.id, nearest_support["expectedTarget"])

    def test_nearest_target_skips_invalid_and_preserves_registration_tie(self):
        position = PetPoint(50, 50)
        targets = [
            PetTarget("hidden", PetTargetKind.CONTROL, PetRect(50, 50, 10, 10), visible=False),
            PetTarget("first", PetTargetKind.SURFACE, PetRect(0, 0, 20, 20)),
            PetTarget("second", PetTargetKind.SURFACE, PetRect(80, 0, 20, 20)),
        ]
        self.assertEqual(nearest_pet_target(position, targets).id, "first")

    def test_ordinary_rectangles_expose_only_the_expanded_upper_support(self):
        target = PetTarget("panel", PetTargetKind.SURFACE, PetRect(20, 30, 60, 40))
        start, end = target.support_segment(PetPoint(50, 70), pet_size=10)
        self.assertEqual((start, end), (PetPoint(10, 20), PetPoint(90, 20)))
        self.assertEqual(target.support_point(PetPoint(50, 70), 10), PetPoint(50, 20))

    def test_chart_path_is_shifted_up_by_half_the_pet_size(self):
        target = PetTarget(
            "curve",
            PetTargetKind.CHART,
            PetRect(0, 0, 100, 100),
            path=(PetPoint(20, 50), PetPoint(80, 60)),
        )
        self.assertEqual(target.shifted_path(12), (PetPoint(20, 38), PetPoint(80, 48)))
        state = advance_pet(
            PetState(PetPoint(20, 38)),
            [target],
            PetRect(0, 0, 120, 100),
            speed=5,
            pet_size=12,
        )
        self.assertEqual(state.mode, PetMode.SLIDE)
        self.assertLess(state.position.y, 50)

    def test_support_above_the_viewport_is_clamped_instead_of_stalling(self):
        target = PetTarget("header", PetTargetKind.CONTROL, PetRect(20, 20, 80, 30))
        state = advance_pet(
            PetState(PetPoint(60, 80)),
            [target],
            PetRect(0, 0, 200, 160),
            pet_size=56,
        )
        for _ in range(40):
            state = advance_pet(state, [target], PetRect(0, 0, 200, 160), pet_size=56)
            if state.mode == PetMode.IDLE:
                break
        self.assertEqual(state.position.y, 56)
        self.assertEqual(state.mode, PetMode.IDLE)

    def test_fall_speed_is_capped_and_hard_landing_completes_two_bounces_without_drift(self):
        target = PetTarget("landing", PetTargetKind.SURFACE, PetRect(20, 80, 60, 20))
        capped = advance_pet(
            PetState(PetPoint(50, 10), PetMode.FALL, vertical_velocity=9.8),
            [target],
            PetRect(0, 0, 120, 120),
        )
        self.assertEqual(capped.vertical_velocity, MAX_FALL_SPEED)
        self.assertEqual(capped.position, PetPoint(50, 20))

        state = advance_pet(
            PetState(PetPoint(50, 75), PetMode.FALL, vertical_velocity=8),
            [target],
            PetRect(0, 0, 120, 120),
        )
        bounce_counts = [state.bounces_remaining]
        for _ in range(80):
            self.assertEqual(state.position.x, 50)
            state = advance_pet(state, [target], PetRect(0, 0, 120, 120))
            if state.bounces_remaining != bounce_counts[-1]:
                bounce_counts.append(state.bounces_remaining)
            if state.mode == PetMode.IDLE:
                break
        self.assertEqual(bounce_counts, [2, 1, 0])
        self.assertEqual(state.mode, PetMode.IDLE)

    def test_navigation_uses_strict_landing_distance_without_center_bias(self):
        near_edge = PetTarget("near-edge", PetTargetKind.CONTROL, PetRect(0, 50, 20, 10))
        central_but_far = PetTarget("central", PetTargetKind.CONTROL, PetRect(45, 90, 20, 10))
        state = advance_pet(
            on_navigation(PetState(PetPoint(10, 10))),
            [near_edge, central_but_far],
            PetRect(0, 0, 100, 120),
        )
        self.assertEqual(state.target_id, "near-edge")

    def test_ordinary_motion_accelerates_caps_and_decelerates(self):
        target = PetTarget("panel", PetTargetKind.SURFACE, PetRect(20, 10, 60, 30))
        state = PetState(PetPoint(50, 70))
        speeds = []
        for _ in range(80):
            state = advance_pet(state, [target], PetRect(0, 0, 120, 100))
            speeds.append(state.movement_speed)
            if state.mode == PetMode.IDLE:
                break
        self.assertEqual(speeds[0], MOTION_ACCELERATION)
        self.assertLessEqual(max(speeds), CRUISE_SPEED)
        self.assertTrue(any(0 < later < earlier for earlier, later in zip(speeds, speeds[1:])))

    def test_horizontal_motion_updates_facing_and_vertical_motion_preserves_it(self):
        target = PetTarget("control", PetTargetKind.CONTROL, PetRect(20, 20, 60, 30))
        left = advance_pet(
            PetState(
                PetPoint(60, 20),
                target_id=target.id,
                path_direction=-1,
                movement_speed=5,
            ),
            [target],
            PetRect(0, 0, 120, 100),
            speed=5,
        )
        self.assertEqual(left.facing, PetFacing.LEFT)
        flight = advance_pet(
            PetState(PetPoint(10, 10), PetMode.FLY, facing=PetFacing.LEFT, movement_speed=5),
            [PetTarget("next", PetTargetKind.CONTROL, PetRect(80, 70, 20, 20))],
            PetRect(0, 0, 120, 120),
            speed=5,
        )
        self.assertEqual(flight.facing, PetFacing.LEFT)

    def test_drag_is_clamped_and_non_dragging_state_is_unchanged(self):
        viewport = PetRect(0, 0, 100, 80)
        state = begin_drag(PetState(PetPoint(10, 10)), PetPoint(10, 10))
        moved = move_drag(state, PetPoint(-20, 100), viewport, pet_size=10)
        self.assertEqual(moved.position, PetPoint(10, 70))
        self.assertEqual(move_drag(release_drag(moved), PetPoint(90, 90), viewport).position, moved.position)

    def test_reducer_wrapper_keeps_navigation_and_release_semantics(self):
        companion = PetCompanion(PetState(PetPoint(20, 20)), speed=4, pet_size=4)
        self.assertEqual(companion.navigate().mode, PetMode.FALL)
        companion.drag_start(PetPoint(40, 50))
        companion.drag_move(PetPoint(500, 600), PetRect(0, 0, 800, 700))
        self.assertEqual(companion.drag_release().position, PetPoint(500, 600))


if __name__ == "__main__":
    unittest.main()
