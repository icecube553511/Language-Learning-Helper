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
    FALL_TIME_STEP_SECONDS,
    FIRST_BOUNCE_SPEED,
    HARD_LANDING_SPEED,
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
        self.assertEqual(motion["fallTimeStepSeconds"], FALL_TIME_STEP_SECONDS)
        self.assertEqual(motion["fallGravityLogicalUnitsPerSecondSquared"], FALL_GRAVITY)
        self.assertEqual(motion["maxFallSpeed"], MAX_FALL_SPEED)
        self.assertEqual(motion["hardLandingSpeed"], HARD_LANDING_SPEED)
        self.assertEqual(motion["fallVelocityUnits"], "logical-units-per-second")
        self.assertEqual(motion["fallIntegration"], "closed-form-constant-acceleration")
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
        support = PetTarget(
            "release-support",
            PetTargetKind.SURFACE,
            PetRect(0, drag["release"][1], drag["viewport"][0], 20),
        )
        released = release_drag(
            dragging,
            [support],
            PetRect(0, 0, *drag["viewport"]),
        )
        assert_point(self, released.position, drag["expectedPosition"])
        self.assertEqual(released.mode.value, drag["expectedMode"])
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
                "fall-without-below-target-uses-viewport-bottom",
                "fall-accelerates",
                "hard-landing-bounces-twice",
                "fall-skips-horizontally-offset-support",
                "fall-retargets-new-nearest-support-every-tick",
                "fall-already-touching-support-lands",
                "synthetic-bottom-hard-landing-bounces-twice",
                "suspended-drag-release-enters-fall",
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
        self.assertAlmostEqual(
            navigation_result.vertical_velocity,
            navigation["expectedVerticalVelocity"],
        )

        fallback = behaviors["fall-without-below-target-uses-viewport-bottom"]
        fallback_viewport = PetRect(0, 0, *fallback["viewport"])
        fallback_result = advance_pet(
            on_navigation(PetState(PetPoint(*fallback["position"]))),
            [self.target_from(item) for item in fallback["targets"]],
            fallback_viewport,
            pet_size=fallback["petHalfSize"],
        )
        self.assertEqual(fallback_result.target_id, fallback["expectedTarget"])
        self.assertEqual(fallback_result.mode.value, fallback["expectedMode"])
        self.assertGreaterEqual(fallback_result.position.y, fallback["position"][1])
        self.assertEqual(
            fallback_viewport.bottom - fallback["petHalfSize"],
            fallback["expectedSyntheticSupportY"],
        )

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
        self.assertEqual(hard_result.vertical_velocity, hard["expectedBounceVerticalVelocity"])
        self.assertEqual(hard_result.bounces_remaining, hard["expectedBouncesRemaining"])

        offset = behaviors["fall-skips-horizontally-offset-support"]
        offset_result = advance_pet(
            PetState(
                PetPoint(*offset["position"]),
                PetMode.FALL,
                vertical_velocity=offset["verticalVelocity"],
            ),
            [self.target_from(item) for item in offset["targets"]],
            PetRect(0, 0, *offset["viewport"]),
            pet_size=offset["petHalfSize"],
        )
        self.assertEqual(offset_result.target_id, offset["expectedTarget"])
        self.assertEqual(offset_result.mode.value, offset["expectedMode"])
        assert_point(self, offset_result.position, offset["expectedPositionAfterOneTick"])
        self.assertEqual(offset_result.vertical_velocity, offset["expectedVerticalVelocity"])

        retarget = behaviors["fall-retargets-new-nearest-support-every-tick"]
        retarget_result = advance_pet(
            PetState(
                PetPoint(*retarget["position"]),
                PetMode.FALL,
                target_id=retarget["previousTarget"],
                vertical_velocity=retarget["verticalVelocity"],
            ),
            [self.target_from(item) for item in retarget["targets"]],
            PetRect(0, 0, *retarget["viewport"]),
            pet_size=retarget["petHalfSize"],
        )
        self.assertEqual(retarget_result.target_id, retarget["expectedTarget"])
        self.assertEqual(retarget_result.mode.value, retarget["expectedMode"])
        assert_point(self, retarget_result.position, retarget["expectedPositionAfterOneTick"])
        self.assertEqual(
            retarget_result.vertical_velocity,
            retarget["expectedVerticalVelocity"],
        )

        touching = behaviors["fall-already-touching-support-lands"]
        touching_result = advance_pet(
            PetState(
                PetPoint(*touching["position"]),
                PetMode(touching["mode"]),
                vertical_velocity=touching["verticalVelocity"],
            ),
            [self.target_from(touching["target"])],
            PetRect(0, 0, *touching["viewport"]),
            pet_size=touching["petHalfSize"],
        )
        assert_point(self, touching_result.position, touching["expectedPosition"])
        self.assertEqual(touching_result.target_id, touching["expectedTarget"])
        self.assertEqual(touching_result.mode.value, touching["expectedMode"])
        self.assertEqual(
            touching_result.vertical_velocity,
            touching["expectedVerticalVelocity"],
        )

        synthetic = behaviors["synthetic-bottom-hard-landing-bounces-twice"]
        synthetic_result = advance_pet(
            PetState(
                PetPoint(*synthetic["position"]),
                PetMode.FALL,
                vertical_velocity=synthetic["verticalVelocity"],
            ),
            [],
            PetRect(0, 0, *synthetic["viewport"]),
            pet_size=synthetic["petHalfSize"],
        )
        assert_point(self, synthetic_result.position, synthetic["expectedPosition"])
        self.assertEqual(synthetic_result.mode.value, synthetic["expectedMode"])
        self.assertEqual(
            synthetic_result.vertical_velocity,
            synthetic["expectedBounceVerticalVelocity"],
        )
        self.assertEqual(
            synthetic_result.bounces_remaining,
            synthetic["expectedBouncesRemaining"],
        )

        suspended = behaviors["suspended-drag-release-enters-fall"]
        suspended_result = release_drag(
            PetState(PetPoint(*suspended["position"]), PetMode.DRAGGING),
            [self.target_from(item) for item in suspended["targets"]],
            PetRect(0, 0, *suspended["viewport"]),
            suspended["petHalfSize"],
        )
        self.assertEqual(suspended_result.mode.value, suspended["expectedMode"])
        self.assertEqual(suspended_result.target_id, suspended["expectedTarget"])
        self.assertEqual(
            suspended_result.vertical_velocity,
            suspended["expectedVerticalVelocity"],
        )

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

    def test_fall_has_no_speed_cap_and_hard_landing_completes_two_bounces_without_drift(self):
        target = PetTarget("landing", PetTargetKind.SURFACE, PetRect(20, 80, 60, 20))
        uncapped = advance_pet(
            PetState(PetPoint(50, 10), PetMode.FALL, vertical_velocity=1_000),
            [PetTarget("far", PetTargetKind.SURFACE, PetRect(20, 400, 60, 20))],
            PetRect(0, 0, 800, 700),
        )
        self.assertIsNone(MAX_FALL_SPEED)
        self.assertAlmostEqual(uncapped.vertical_velocity, 1_034.375)
        self.assertAlmostEqual(uncapped.position.y, 26.275)

        state = advance_pet(
            PetState(PetPoint(50, 75), PetMode.FALL, vertical_velocity=500),
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

    def test_fall_matches_shared_closed_form_samples(self):
        vector = self.golden["fallPhysicsVectors"][0]
        target = PetTarget("landing", PetTargetKind.SURFACE, PetRect(0, 500, 200, 20))
        state = PetState(
            PetPoint(50, vector["initialPositionY"]),
            PetMode.FALL,
            vertical_velocity=vector["initialVerticalVelocity"],
        )
        previous_y = state.position.y
        for sample in vector["samples"]:
            state = advance_pet(state, [target], PetRect(0, 0, 800, 700))
            self.assertAlmostEqual(state.position.y, sample["expectedY"])
            self.assertAlmostEqual(
                state.vertical_velocity,
                sample["expectedVerticalVelocity"],
            )
            self.assertAlmostEqual(
                state.position.y - previous_y,
                sample["expectedTickDisplacement"],
            )
            previous_y = state.position.y

    def test_landing_threshold_uses_velocity_at_contact_not_end_of_tick(self):
        target = PetTarget("nearby", PetTargetKind.SURFACE, PetRect(0, 100, 200, 20))
        state = advance_pet(
            PetState(PetPoint(50, 99.5), PetMode.FALL, vertical_velocity=430),
            [target],
            PetRect(0, 0, 200, 160),
        )

        self.assertEqual(state.position, PetPoint(50, 100))
        self.assertEqual(state.mode, PetMode.IDLE)
        self.assertEqual(state.bounces_remaining, 0)

    def test_synthetic_bottom_hard_landing_completes_two_bounces(self):
        viewport = PetRect(0, 0, 800, 700)
        state = advance_pet(
            PetState(PetPoint(100, 643), PetMode.FALL, vertical_velocity=500),
            [],
            viewport,
            pet_size=56,
        )
        bounce_counts = [state.bounces_remaining]
        for _ in range(100):
            state = advance_pet(state, [], viewport, pet_size=56)
            if state.bounces_remaining != bounce_counts[-1]:
                bounce_counts.append(state.bounces_remaining)
            if state.mode == PetMode.IDLE:
                break

        self.assertEqual(bounce_counts, [2, 1, 0])
        self.assertEqual(state.mode, PetMode.IDLE)
        self.assertIsNone(state.target_id)
        self.assertEqual(state.position, PetPoint(100, 644))

    def test_lost_support_and_no_below_target_keep_falling_downward(self):
        viewport = PetRect(0, 0, 800, 700)
        above = PetTarget("above", PetTargetKind.SURFACE, PetRect(20, 20, 120, 20))
        state = advance_pet(
            PetState(PetPoint(60, 100), PetMode.FALL),
            [above],
            viewport,
        )
        self.assertEqual(state.mode, PetMode.FALL)
        self.assertGreater(state.position.y, 100)
        self.assertIsNone(state.target_id)

        lost_target = advance_pet(
            PetState(
                PetPoint(60, 100),
                PetMode.IDLE,
                target_id="removed",
                idle_ticks_remaining=IDLE_TICKS,
            ),
            [],
            viewport,
        )
        self.assertEqual(lost_target.mode, PetMode.FALL)
        self.assertGreater(lost_target.position.y, 100)
        self.assertIsNone(lost_target.target_id)

    def test_fall_reselects_the_nearest_support_on_every_tick(self):
        viewport = PetRect(0, 0, 800, 700)
        far = PetTarget("far", PetTargetKind.SURFACE, PetRect(20, 500, 120, 20))
        near = PetTarget("near", PetTargetKind.SURFACE, PetRect(20, 220, 120, 20))
        state = PetState(
            PetPoint(60, 100),
            PetMode.FALL,
            target_id=far.id,
            vertical_velocity=125.0,
        )

        result = advance_pet(state, [far, near], viewport)

        self.assertEqual(result.target_id, near.id)
        self.assertEqual(result.mode, PetMode.FALL)
        self.assertEqual(result.position.x, state.position.x)
        self.assertGreater(result.position.y, state.position.y)

    def test_fall_lands_when_already_touching_the_nearest_support(self):
        support = PetTarget("touching", PetTargetKind.SURFACE, PetRect(20, 100, 120, 20))

        landed = advance_pet(
            PetState(PetPoint(60, 100), PetMode.FALL, vertical_velocity=120),
            [support],
            PetRect(0, 0, 800, 700),
        )

        self.assertEqual(landed.position, PetPoint(60, 100))
        self.assertEqual(landed.mode, PetMode.IDLE)
        self.assertEqual(landed.target_id, support.id)

        bounced = advance_pet(
            PetState(PetPoint(60, 100), PetMode.FALL, vertical_velocity=500),
            [support],
            PetRect(0, 0, 800, 700),
        )
        self.assertEqual(bounced.position, PetPoint(60, 100))
        self.assertEqual(bounced.mode, PetMode.BOUNCE)
        self.assertEqual(bounced.vertical_velocity, -FIRST_BOUNCE_SPEED)
        self.assertEqual(bounced.bounces_remaining, BOUNCE_COUNT)

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

    def test_drag_release_idles_on_support_and_falls_when_suspended(self):
        viewport = PetRect(0, 0, 200, 160)
        target = PetTarget("card", PetTargetKind.SURFACE, PetRect(20, 100, 120, 40))
        on_support = release_drag(
            PetState(PetPoint(60, 80), PetMode.DRAGGING),
            [target],
            viewport,
            20,
        )
        suspended = release_drag(
            PetState(PetPoint(60, 40), PetMode.DRAGGING),
            [target],
            viewport,
            20,
        )
        self.assertEqual(on_support.mode, PetMode.IDLE)
        self.assertEqual(on_support.target_id, target.id)
        self.assertEqual(suspended.mode, PetMode.FALL)
        self.assertIsNone(suspended.target_id)

    def test_reducer_wrapper_keeps_navigation_and_release_semantics(self):
        companion = PetCompanion(PetState(PetPoint(20, 20)), speed=4, pet_size=4)
        self.assertEqual(companion.navigate().mode, PetMode.FALL)
        companion.drag_start(PetPoint(40, 50))
        companion.drag_move(PetPoint(500, 600), PetRect(0, 0, 800, 700))
        released = companion.drag_release()
        self.assertEqual(released.position, PetPoint(500, 600))
        self.assertEqual(released.mode, PetMode.FALL)


if __name__ == "__main__":
    unittest.main()
