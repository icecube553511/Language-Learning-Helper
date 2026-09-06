from __future__ import annotations

import json
import math
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
    CURVE_ACCELERATION,
    estimate_release_velocity,
    FLING_GRAVITY,
    FLING_HORIZONTAL_RESTITUTION,
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
    limit_fling_velocity,
)
from presentation.app import DialogPetRuntime, LexiTrackApp
from presentation.pet_windows import (
    PetWindow,
    PetWindowCoordinator,
    interpolate_pet_position,
    map_pet_entry,
    predicted_exit_times,
    ray_rect_entry_time,
    select_adjacent_window,
)
from presentation.widgets import PetOverlay


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

    def test_presentation_interpolates_linearly_between_simulated_ticks(self):
        start = PetPoint(10.0, 30.0)
        end = PetPoint(50.0, 70.0)

        self.assertEqual(interpolate_pet_position(start, end, -4, 16), start)
        self.assertEqual(
            interpolate_pet_position(start, end, 8, 16),
            PetPoint(30.0, 50.0),
        )
        self.assertEqual(interpolate_pet_position(start, end, 20, 16), end)
        self.assertEqual(interpolate_pet_position(start, end, 8, 0), end)

    def test_layout_invalidation_anchors_rendering_to_live_state(self):
        """Queued frames from a replaced card must not restore stale coords."""
        app = LexiTrackApp.__new__(LexiTrackApp)
        app._pet_render_generation = 3
        app._pet_render_after_ids = []
        app._pet_last_rendered_position = PetPoint(5.0, 5.0)
        app.pet_companion = PetCompanion(PetState(PetPoint(48.0, 72.0)))

        app._invalidate_main_pet_render()

        self.assertEqual(app._pet_render_generation, 4)
        self.assertEqual(app._pet_last_rendered_position, PetPoint(48.0, 72.0))

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
        navigation = PetState(
            PetPoint(10, 20),
            PetMode.SLIDE,
            "chart",
            curve_velocity=2.0,
        )
        navigated = on_navigation(navigation)
        self.assertEqual(navigated.mode.value, golden["vectors"][1]["expectedMode"])
        self.assertIsNone(navigated.curve_velocity)
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

    def test_nearest_target_prefers_content_over_screen_edge(self):
        """Content wins over an edge so a card rebuild cannot strand the pet."""
        position = PetPoint(40.0, 220.0)
        edge = PetTarget("edge:bottom", PetTargetKind.EDGE, PetRect(0.0, 240.0, 100.0, 3.0))
        control = PetTarget("study:new-card", PetTargetKind.CONTROL, PetRect(10.0, 60.0, 80.0, 24.0))
        viewport = PetRect(0.0, 0.0, 100.0, 250.0)

        selected = nearest_pet_target(position, [edge, control], viewport=viewport)
        self.assertEqual(selected.id, "study:new-card")

        # With no content available, an edge remains a valid fallback target.
        only_edge = nearest_pet_target(position, [edge], viewport=viewport)
        self.assertEqual(only_edge.id, "edge:bottom")

    def test_retained_edge_target_yields_to_content(self):
        """A pet already following an edge must re-select content next tick.

        Once the companion lands on a thin boundary the retained target would
        otherwise keep it creeping along the edge forever (visually motionless)
        even though real content targets exist.
        """
        state = PetState(
            position=PetPoint(59.0, 120.0),
            mode=PetMode.ROLL,
            target_id="edge:left",
            path_direction=1,
            movement_speed=1.2,
        )
        targets = [
            PetTarget("edge:left", PetTargetKind.EDGE, PetRect(0.0, 0.0, 3.0, 700.0)),
            PetTarget("study:card", PetTargetKind.SURFACE, PetRect(240.0, 80.0, 600.0, 500.0)),
        ]
        viewport = PetRect(0.0, 0.0, 960.0, 700.0)

        advanced = advance_pet(state, targets, viewport, pet_size=56.0)

        self.assertNotEqual(advanced.target_id, "edge:left")
        self.assertEqual(advanced.target_id, "study:card")

    def test_edge_retained_when_no_content_exists(self):
        """With no content available the edge remains a legal retained support."""
        state = PetState(
            position=PetPoint(59.0, 120.0),
            mode=PetMode.ROLL,
            target_id="edge:left",
            path_direction=1,
            movement_speed=1.2,
        )
        targets = [PetTarget("edge:left", PetTargetKind.EDGE, PetRect(0.0, 0.0, 3.0, 700.0))]
        viewport = PetRect(0.0, 0.0, 960.0, 700.0)

        advanced = advance_pet(state, targets, viewport, pet_size=56.0)

        self.assertEqual(advanced.target_id, "edge:left")

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

    def test_chart_segment_midpoint_is_a_legal_release_support(self):
        vector = next(
            item
            for item in self.golden["curveLandingVectors"]
            if item["name"] == "zero-speed-mid-segment-starts-downhill-without-vertex-snap"
        )
        target = PetTarget(
            "curve",
            PetTargetKind.CHART,
            PetRect(0, 0, 200, 160),
            path=tuple(PetPoint(*point) for point in vector["segment"]),
        )
        released = release_drag(
            PetState(PetPoint(*vector["contactPoint"]), PetMode.DRAGGING),
            [target],
            PetRect(0, 0, 200, 200),
        )
        self.assertEqual(released.mode.value, vector["expectedMode"])
        self.assertEqual(released.target_id, "curve")
        assert_point(self, released.position, vector["contactPoint"])
        self.assertAlmostEqual(
            released.curve_velocity,
            vector["expectedInitialCurveVelocity"],
        )
        self.assertEqual(released.path_direction, vector["expectedPathDirection"])

        advanced = advance_pet(released, [target], PetRect(0, 0, 200, 200))

        self.assertAlmostEqual(
            advanced.curve_velocity,
            vector["expectedNextCurveVelocity"],
        )
        assert_point(self, advanced.position, vector["expectedNextPosition"])
        self.assertGreater(advanced.position.x, released.position.x)
        self.assertGreater(advanced.position.y, released.position.y)

    def test_flat_curve_release_ignores_stale_direction(self):
        vector = next(
            item
            for item in self.golden["curveLandingVectors"]
            if item["name"] == "flat-segment-rest-uses-registration-direction"
        )
        viewport = PetRect(0, 0, 200, 200)
        target = PetTarget(
            "curve",
            PetTargetKind.CHART,
            PetRect(0, 0, 200, 160),
            tuple(PetPoint(*point) for point in vector["segment"]),
        )
        contact = PetPoint(*vector["contactPoint"])
        landed = release_drag(
            PetState(
                contact,
                PetMode.DRAGGING,
                path_direction=vector["initialPathDirection"],
            ),
            [target],
            viewport,
        )

        self.assertEqual(landed.mode.value, vector["expectedMode"])
        self.assertAlmostEqual(
            landed.curve_velocity,
            vector["expectedInitialCurveVelocity"],
        )
        self.assertEqual(landed.path_direction, vector["expectedPathDirection"])

        advanced = advance_pet(landed, [target], viewport)

        self.assertAlmostEqual(
            advanced.curve_velocity,
            vector["expectedNextCurveVelocity"],
        )
        assert_point(self, advanced.position, vector["expectedNextPosition"])

    def test_curve_uphill_endpoint_stops_and_reverses_downhill(self):
        for vector in self.golden["curveEndpointVectors"]:
            with self.subTest(name=vector["name"]):
                width = max(point[0] for point in vector["segment"]) + 100.0
                viewport = PetRect(0, 0, width, 200)
                target = PetTarget(
                    "curve",
                    PetTargetKind.CHART,
                    viewport,
                    tuple(PetPoint(*point) for point in vector["segment"]),
                )
                state = PetState(
                    PetPoint(*vector["initialPosition"]),
                    PetMode.SLIDE,
                    target_id=target.id,
                    path_index=0,
                    path_direction=vector["initialPathDirection"],
                    curve_velocity=vector["initialCurveVelocity"],
                )

                for _ in range(vector["expectedEndpointTick"]):
                    state = advance_pet(state, [target], viewport)

                self.assertEqual(state.mode.value, vector["expectedEndpointMode"])
                assert_point(self, state.position, vector["expectedEndpointPosition"])
                self.assertAlmostEqual(
                    state.curve_velocity,
                    vector["expectedEndpointCurveVelocity"],
                )
                self.assertEqual(
                    state.path_direction,
                    vector["expectedEndpointPathDirection"],
                )

                state = advance_pet(state, [target], viewport)

                self.assertEqual(state.mode.value, vector["expectedNextMode"])
                self.assertAlmostEqual(
                    state.curve_velocity,
                    vector["expectedNextCurveVelocity"],
                )
                assert_point(self, state.position, vector["expectedNextPosition"])

    def test_curve_coordinate_scale_vector_preserves_logical_motion(self):
        vector = self.golden["curveScaleVectors"][0]
        viewport = PetRect(0, 0, 200, 200)
        target = PetTarget(
            "curve",
            PetTargetKind.CHART,
            PetRect(0, 0, 200, 160),
            tuple(PetPoint(*point) for point in vector["logicalSegment"]),
        )
        incoming = vector["logicalIncomingVelocity"]
        landed = advance_pet(
            PetState(
                PetPoint(*vector["logicalContactPoint"]),
                PetMode.FALL,
                vertical_velocity=incoming[1],
            ),
            [target],
            viewport,
        )
        self.assertAlmostEqual(
            landed.curve_velocity,
            vector["expectedInitialLogicalCurveVelocity"],
        )

        advanced = advance_pet(landed, [target], viewport)
        expected_physical = vector["expectedNextPhysicalPosition"]
        scale = vector["unitScale"]

        self.assertAlmostEqual(
            advanced.curve_velocity,
            vector["expectedNextLogicalCurveVelocity"],
        )
        assert_point(
            self,
            advanced.position,
            [coordinate / scale for coordinate in expected_physical],
        )

    def test_curve_landing_projection_clamps_uphill_speed(self):
        vector = next(
            item
            for item in self.golden["curveLandingVectors"]
            if item["name"] == "fling-projection-clamps-uphill-speed"
        )
        viewport = PetRect(0, 0, 200, 200)
        target = PetTarget(
            "curve",
            PetTargetKind.CHART,
            PetRect(0, 0, 200, 160),
            tuple(PetPoint(*point) for point in vector["segment"]),
        )
        contact = PetPoint(*vector["contactPoint"])
        landed = advance_pet(
            PetState(
                contact,
                PetMode.FLING,
                horizontal_velocity=vector["incomingVelocity"][0],
                vertical_velocity=vector["incomingVelocity"][1],
            ),
            [target],
            viewport,
        )

        self.assertEqual(landed.mode.value, vector["expectedMode"])
        self.assertAlmostEqual(
            landed.curve_velocity,
            vector["expectedInitialCurveVelocity"],
        )
        self.assertEqual(landed.path_direction, vector["expectedPathDirection"])

        advanced = advance_pet(landed, [target], viewport)

        self.assertAlmostEqual(
            advanced.curve_velocity,
            vector["expectedNextCurveVelocity"],
        )
        assert_point(self, advanced.position, vector["expectedNextPosition"])

    def test_vertical_curve_landing_projects_velocity_without_sliding_uphill(self):
        vectors = {
            item["name"]: item for item in self.golden["curveLandingVectors"]
        }
        viewport = PetRect(0, 0, 200, 200)
        for name in (
            "vertical-fall-projects-onto-descending-tangent",
            "vertical-fall-uses-reverse-order-downhill-on-ascending-segment",
        ):
            with self.subTest(name=name):
                vector = vectors[name]
                target = PetTarget(
                    name,
                    PetTargetKind.CHART,
                    PetRect(0, 0, 200, 160),
                    tuple(PetPoint(*point) for point in vector["segment"]),
                )
                contact = PetPoint(*vector["contactPoint"])
                landed = advance_pet(
                    PetState(
                        contact,
                        PetMode.FALL,
                        vertical_velocity=vector["incomingVelocity"][1],
                    ),
                    [target],
                    viewport,
                )

                self.assertEqual(landed.mode.value, vector["expectedMode"])
                self.assertEqual(landed.target_id, target.id)
                assert_point(self, landed.position, vector["contactPoint"])
                self.assertAlmostEqual(
                    landed.curve_velocity,
                    vector["expectedInitialCurveVelocity"],
                )
                self.assertEqual(
                    landed.path_direction,
                    vector["expectedPathDirection"],
                )

                advanced = advance_pet(landed, [target], viewport)

                self.assertAlmostEqual(
                    advanced.curve_velocity,
                    vector["expectedNextCurveVelocity"],
                )
                self.assertGreater(advanced.position.y, landed.position.y)
                if "expectedNextPosition" in vector:
                    assert_point(self, advanced.position, vector["expectedNextPosition"])

    def test_uphill_fling_slows_then_reverses_downhill(self):
        vector = next(
            item
            for item in self.golden["curveLandingVectors"]
            if item["name"] == "uphill-fling-slows-before-reversing-downhill"
        )
        viewport = PetRect(0, 0, 200, 200)
        target = PetTarget(
            "curve",
            PetTargetKind.CHART,
            PetRect(0, 0, 200, 160),
            tuple(PetPoint(*point) for point in vector["segment"]),
        )
        landed = advance_pet(
            PetState(
                PetPoint(*vector["contactPoint"]),
                PetMode.FLING,
                horizontal_velocity=vector["incomingVelocity"][0],
                vertical_velocity=vector["incomingVelocity"][1],
            ),
            [target],
            viewport,
        )

        self.assertEqual(landed.mode.value, vector["expectedMode"])
        self.assertAlmostEqual(
            landed.curve_velocity,
            vector["expectedInitialCurveVelocity"],
        )
        self.assertEqual(landed.path_direction, vector["expectedPathDirection"])

        first_slide = advance_pet(landed, [target], viewport)
        self.assertAlmostEqual(
            first_slide.curve_velocity,
            vector["expectedNextCurveVelocity"],
        )
        assert_point(self, first_slide.position, vector["expectedNextPosition"])
        self.assertLess(first_slide.position.y, landed.position.y)

        state = first_slide
        downhill_tick = None
        for tick in range(2, vector["expectedDownhillByTick"] + 1):
            state = advance_pet(state, [target], viewport)
            if state.curve_velocity > 0.0:
                downhill_tick = tick
                break

        self.assertIsNotNone(downhill_tick)
        self.assertEqual(downhill_tick, vector["expectedDownhillByTick"])
        downhill_position = advance_pet(state, [target], viewport)
        self.assertGreater(downhill_position.position.y, state.position.y)

    def test_landed_curve_acceleration_decreases_toward_terminal_speed(self):
        vector = next(
            item
            for item in self.golden["curveLandingVectors"]
            if item["name"] == "zero-speed-mid-segment-starts-downhill-without-vertex-snap"
        )
        viewport = PetRect(0, 0, 200, 200)
        target = PetTarget(
            "curve",
            PetTargetKind.CHART,
            PetRect(0, 0, 200, 160),
            tuple(PetPoint(*point) for point in vector["segment"]),
        )
        state = release_drag(
            PetState(PetPoint(*vector["contactPoint"]), PetMode.DRAGGING),
            [target],
            viewport,
        )
        velocities = [state.curve_velocity]
        positions = [state.position]
        for _ in range(8):
            state = advance_pet(state, [target], viewport)
            velocities.append(state.curve_velocity)
            positions.append(state.position)

        increments = [
            later - earlier for earlier, later in zip(velocities, velocities[1:])
        ]
        self.assertAlmostEqual(increments[0], vector["expectedNextCurveVelocity"])
        self.assertTrue(all(increment > 0.0 for increment in increments))
        self.assertTrue(
            all(later < earlier for earlier, later in zip(increments, increments[1:]))
        )
        self.assertTrue(
            all(later.y > earlier.y for earlier, later in zip(positions, positions[1:]))
        )

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

    def test_drag_velocity_uses_monotonic_constrained_samples_and_preserves_tangent(self):
        samples = [
            (1000.0, PetPoint(20.0, 30.0)),
            (1040.0, PetPoint(32.0, 18.0)),
            (1080.0, PetPoint(44.0, 6.0)),
        ]
        velocity = estimate_release_velocity(samples)
        self.assertAlmostEqual(velocity.x, 300.0, places=5)
        self.assertAlmostEqual(velocity.y, -300.0, places=5)
        # Out-of-order timestamps are normalized rather than producing a
        # backwards impulse; duplicate timestamps alone carry no velocity.
        self.assertEqual(
            estimate_release_velocity([(5.0, PetPoint(2, 2)), (5.0, PetPoint(4, 4))]),
            PetPoint(0.0, 0.0),
        )
        golden_samples = [
            {"timeMs": 0, "position": [100.0, 200.0]},
            {"timeMs": 40, "position": [120.0, 180.0]},
            {"timeMs": 80, "position": [140.0, 160.0]},
            {"timeMs": 120, "position": [160.0, 140.0]},
        ]
        self.assertAlmostEqual(
            estimate_release_velocity(golden_samples, nowMs=120, windowMs=120).x,
            500.0,
        )

    def test_release_enters_fling_and_closed_form_substeps_match_golden(self):
        viewport = PetRect(0, 0, 1000, 1000)
        state = release_drag(
            PetState(PetPoint(320, 420), PetMode.DRAGGING),
            [],
            viewport,
            release_velocity=PetPoint(420, -680),
        )
        self.assertEqual(state.mode, PetMode.FLING)
        self.assertEqual(state.velocity, PetPoint(420, -680))
        next_state = advance_pet(state, [], viewport)
        self.assertAlmostEqual(next_state.position.x, 326.72, places=6)
        self.assertAlmostEqual(next_state.position.y, 409.395, places=6)
        self.assertAlmostEqual(next_state.vertical_velocity, -645.625, places=6)

    def test_non_finite_fling_velocity_is_rejected(self):
        self.assertEqual(
            limit_fling_velocity(PetPoint(float("nan"), 10.0)),
            PetPoint(0.0, 0.0),
        )
        self.assertEqual(
            limit_fling_velocity(PetPoint(float("inf"), -10.0)),
            PetPoint(0.0, 0.0),
        )

    def test_non_finite_curve_velocity_recovers_downhill(self):
        target = PetTarget(
            "curve",
            PetTargetKind.CHART,
            PetRect(0, 0, 200, 160),
            path=(PetPoint(0, 100), PetPoint(100, 120)),
        )
        advanced = advance_pet(
            PetState(
                PetPoint(50, 110),
                PetMode.SLIDE,
                target_id=target.id,
                path_index=1,
                curve_velocity=float("nan"),
            ),
            [target],
            PetRect(0, 0, 200, 200),
        )

        self.assertAlmostEqual(advanced.curve_velocity, 0.25)
        self.assertTrue(math.isfinite(advanced.curve_velocity))
        self.assertGreater(advanced.position.y, 110)

    def test_shared_drag_velocity_vectors_and_curve_acceleration(self):
        vectors = {item["name"]: item for item in self.golden.get("dragVelocityVectors", [])}
        terminal = vectors["terminal-tangent-estimate-uses-constrained-centres"]
        estimated = estimate_release_velocity(
            terminal["samples"],
            now_ms=terminal["nowMs"],
            window_ms=terminal["sampleWindowMs"],
        )
        assert_point(self, estimated, terminal["expectedVelocity"])
        insufficient = vectors["insufficient-drag-samples-do-not-fling"]
        self.assertEqual(
            estimate_release_velocity(
                insufficient["samples"],
                now_ms=insufficient["nowMs"],
                window_ms=insufficient["sampleWindowMs"],
            ),
            PetPoint(0.0, 0.0),
        )
        curve = self.golden["curveMotionVectors"][0]
        target = PetTarget(
            "curve",
            PetTargetKind.CHART,
            PetRect(0, 0, 120, 100),
            (PetPoint(10, 50), PetPoint(110, 50)),
        )
        state = PetState(
            PetPoint(10, 50),
            PetMode.SLIDE,
            target_id=target.id,
            path_index=1,
            movement_speed=curve["initialMovementSpeed"],
        )
        observed = []
        for _ in curve["tickSpeeds"]:
            state = advance_pet(
                state,
                [target],
                PetRect(0, 0, 120, 100),
                speed=curve["cruiseSpeed"],
            )
            observed.append(state.movement_speed)
        self.assertEqual(observed, curve["tickSpeeds"])

        curve_vectors = {
            item["name"]: item for item in self.golden["curveMotionVectors"]
        }
        corner = curve_vectors["curve-slide-retains-budget-across-corner"]
        corner_target = PetTarget(
            "corner",
            PetTargetKind.CHART,
            PetRect(0, 0, 120, 100),
            (
                PetPoint(10, 50),
                PetPoint(10 + corner["remainingToCorner"], 50),
                PetPoint(110, 50),
            ),
        )
        corner_state = advance_pet(
            PetState(
                PetPoint(10, 50),
                PetMode.SLIDE,
                target_id=corner_target.id,
                path_index=1,
                movement_speed=corner["initialMovementSpeed"],
            ),
            [corner_target],
            PetRect(0, 0, 120, 100),
            speed=corner["cruiseSpeed"],
        )
        self.assertAlmostEqual(corner_state.movement_speed, corner["expectedSpeedAfterCorner"])
        self.assertAlmostEqual(
            corner_state.position.x,
            10 + corner["remainingToCorner"] + corner["expectedBudgetAfterCorner"],
        )
        self.assertEqual(corner_state.path_index, 2)

        override = curve_vectors[
            "curve-slide-step-override-keeps-contract-acceleration-and-corner-budget"
        ]
        override_state = advance_pet(
            PetState(
                PetPoint(10, 50),
                PetMode.SLIDE,
                target_id=corner_target.id,
                path_index=1,
                movement_speed=override["initialMovementSpeed"],
            ),
            [corner_target],
            PetRect(0, 0, 120, 100),
            speed=override["requestedStep"],
        )
        self.assertAlmostEqual(
            override_state.movement_speed,
            override["expectedSpeedAfterCorner"],
        )
        self.assertAlmostEqual(
            override_state.position.x,
            10
            + override["remainingToCorner"]
            + override["expectedBudgetAfterCorner"],
        )
        self.assertEqual(override_state.path_index, 2)

    def test_curve_brakes_before_reversing_at_endpoint(self):
        target = PetTarget(
            "curve",
            PetTargetKind.CHART,
            PetRect(0, 0, 100, 100),
            (PetPoint(10, 50), PetPoint(50, 50)),
        )
        state = PetState(
            PetPoint(10, 50),
            PetMode.SLIDE,
            target_id=target.id,
            path_index=1,
        )
        speeds = []
        for _ in range(80):
            state = advance_pet(state, [target], PetRect(0, 0, 100, 100))
            speeds.append(state.movement_speed)
            if state.path_direction < 0:
                break
        self.assertEqual(state.path_direction, -1)
        self.assertEqual(speeds[-1], 0.0)
        self.assertTrue(any(0.0 < later < earlier for earlier, later in zip(speeds, speeds[1:-1])))

    def test_pet_overlay_grab_is_owned_by_the_bound_sprite(self):
        class RecordingSprite:
            def __init__(self):
                self.calls = []

            def grab_set(self):
                self.calls.append("set")

            def grab_release(self):
                self.calls.append("release")

        overlay = object.__new__(PetOverlay)
        sprite = RecordingSprite()
        overlay._sprite = sprite

        overlay.grab_pointer()
        overlay.release_pointer()

        self.assertEqual(sprite.calls, ["set", "release"])

    def test_release_event_migration_releases_the_new_active_host(self):
        class Host:
            pass

        class Overlay:
            def __init__(self):
                self.grabbed = True

        def dragging_companion() -> PetCompanion:
            return PetCompanion(
                PetState(PetPoint(100.0, 100.0), PetMode.DRAGGING),
                pet_size=PET_DISPLAY_SIZE / 2.0,
            )

        def samples() -> list[tuple[float, PetPoint]]:
            return [
                (0.0, PetPoint(100.0, 100.0)),
                (16.0, PetPoint(120.0, 100.0)),
            ]

        class FakeApp:
            def __init__(self):
                self._dialog_pet_runtimes = {}
                self._pet_drag_host_dialog = None
                self._pet_dragging = True
                self._pet_drag_samples = samples()
                self._pet_drag_offset = PetPoint(0.0, 0.0)
                self._pet_overlay = Overlay()
                self.pet_companion = dragging_companion()

            @staticmethod
            def _pet_viewport_for(_host):
                return PetRect(0.0, 0.0, 400.0, 300.0)

            @staticmethod
            def _pet_viewport():
                return PetRect(0.0, 0.0, 400.0, 300.0)

            @staticmethod
            def _collect_dialog_pet_targets(_host, _key):
                return ()

            @staticmethod
            def _collect_pet_targets():
                return ()

            @staticmethod
            def _release_pet_overlay(overlay):
                overlay.grabbed = False

        event = object()

        with self.subTest("dialog-to-dialog"):
            app = FakeApp()
            source, target = Host(), Host()
            source_runtime = DialogPetRuntime(
                "source",
                dragging_companion(),
                Overlay(),
                drag_samples=samples(),
            )
            target_runtime = DialogPetRuntime(
                "target",
                dragging_companion(),
                Overlay(),
                drag_samples=samples(),
            )
            app._dialog_pet_runtimes[target] = target_runtime
            app._pet_drag_host_dialog = source

            def move_to_target(_event):
                source_runtime.overlay.grabbed = False
                target_runtime.overlay.grabbed = True
                app._pet_drag_host_dialog = target

            LexiTrackApp._release_dialog_pet(
                app,
                event,
                source,
                source_runtime,
                source_runtime.key,
                move_to_target,
            )
            self.assertNotEqual(target_runtime.companion.state.mode, PetMode.DRAGGING)
            self.assertFalse(target_runtime.overlay.grabbed)
            self.assertIsNone(app._pet_drag_host_dialog)
            self.assertFalse(app._pet_dragging)

        with self.subTest("dialog-to-main"):
            app = FakeApp()
            source = Host()
            source_runtime = DialogPetRuntime(
                "source",
                dragging_companion(),
                Overlay(),
                drag_samples=samples(),
            )
            app._pet_drag_host_dialog = source

            def move_to_main(_event):
                source_runtime.overlay.grabbed = False
                app._pet_overlay.grabbed = True
                app._pet_drag_host_dialog = app

            LexiTrackApp._release_dialog_pet(
                app,
                event,
                source,
                source_runtime,
                source_runtime.key,
                move_to_main,
            )
            self.assertNotEqual(app.pet_companion.state.mode, PetMode.DRAGGING)
            self.assertFalse(app._pet_overlay.grabbed)
            self.assertIsNone(app._pet_drag_host_dialog)
            self.assertFalse(app._pet_dragging)

        with self.subTest("main-to-dialog"):
            app = FakeApp()
            target = Host()
            target_runtime = DialogPetRuntime(
                "target",
                dragging_companion(),
                Overlay(),
                drag_samples=samples(),
            )
            app._dialog_pet_runtimes[target] = target_runtime

            def move_to_target(_event):
                app._pet_overlay.grabbed = False
                target_runtime.overlay.grabbed = True
                app._pet_drag_host_dialog = target

            app._pet_move = move_to_target
            LexiTrackApp._pet_release(app, event)
            self.assertNotEqual(target_runtime.companion.state.mode, PetMode.DRAGGING)
            self.assertFalse(target_runtime.overlay.grabbed)
            self.assertIsNone(app._pet_drag_host_dialog)
            self.assertFalse(app._pet_dragging)

    def test_horizontal_fling_moves_along_support_before_falling(self):
        viewport = PetRect(0, 0, 400, 300)
        support = PetTarget("card", PetTargetKind.SURFACE, PetRect(50, 120, 200, 30))
        state = release_drag(
            PetState(PetPoint(100, 100), PetMode.DRAGGING),
            [support],
            viewport,
            20,
            release_velocity=PetPoint(600, 0),
        )

        state = advance_pet(state, [support], viewport, pet_size=20)

        self.assertEqual(state.mode, PetMode.FLING)
        self.assertGreater(state.position.x, 100)
        self.assertEqual(state.position.y, 100)
        self.assertEqual(state.horizontal_velocity, 600)

        for _ in range(30):
            state = advance_pet(state, [support], viewport, pet_size=20)
            if state.position.y > 100:
                break
        self.assertGreater(state.position.y, 100)

    def test_fling_hard_landing_clears_horizontal_velocity_through_bounce(self):
        viewport = PetRect(0, 0, 400, 300)
        support = PetTarget("floor", PetTargetKind.SURFACE, PetRect(0, 220, 400, 20))
        state = PetState(
            PetPoint(100, 195),
            PetMode.FLING,
            horizontal_velocity=240,
            vertical_velocity=500,
        )

        state = advance_pet(state, [support], viewport, pet_size=20)

        self.assertEqual(state.mode, PetMode.BOUNCE)
        self.assertEqual(state.horizontal_velocity, 0.0)
        landing_x = state.position.x
        for _ in range(80):
            state = advance_pet(state, [support], viewport, pet_size=20)
            self.assertEqual(state.position.x, landing_x)
            self.assertEqual(state.horizontal_velocity, 0.0)
            if state.mode == PetMode.IDLE:
                break
        self.assertEqual(state.mode, PetMode.IDLE)

    def test_fling_reflects_horizontal_wall_and_lands_on_support(self):
        viewport = PetRect(0, 0, 400, 300)
        state = PetState(
            PetPoint(375, 120),
            PetMode.FLING,
            horizontal_velocity=900,
            vertical_velocity=0,
        )
        bounced = advance_pet(state, [], viewport, pet_size=20)
        self.assertLessEqual(bounced.position.x, 380)
        self.assertLess(bounced.horizontal_velocity, 0)
        self.assertAlmostEqual(
            abs(bounced.horizontal_velocity),
            900 * FLING_HORIZONTAL_RESTITUTION,
            delta=5,
        )
        support = PetTarget("floor", PetTargetKind.SURFACE, PetRect(0, 220, 400, 20))
        falling = PetState(
            PetPoint(100, 100),
            PetMode.FLING,
            horizontal_velocity=0,
            vertical_velocity=500,
        )
        landed = advance_pet(falling, [support], viewport, pet_size=20)
        for _ in range(30):
            if landed.mode != PetMode.FLING:
                break
            landed = advance_pet(landed, [support], viewport, pet_size=20)
        self.assertIn(landed.mode, {PetMode.IDLE, PetMode.BOUNCE})
        self.assertAlmostEqual(landed.position.y, 200.0, delta=1e-5)

    def test_fling_can_land_on_descending_root_after_entering_below_support(self):
        """Do not discard the later root when an upward fling starts below a surface."""
        viewport = PetRect(0, 0, 400, 300)
        support = PetTarget("support", PetTargetKind.SURFACE, PetRect(0, 100, 400, 10))
        state = PetState(
            PetPoint(200, 100.01),
            PetMode.FLING,
            vertical_velocity=-16,
        )
        landed = advance_pet(state, [support], viewport)
        self.assertEqual(landed.mode, PetMode.IDLE)
        self.assertEqual(landed.target_id, "support")
        self.assertAlmostEqual(landed.position.y, 100.0, places=5)

    def test_fling_hits_diagonal_chart_using_relative_normal_velocity(self):
        vector = next(
            item
            for item in self.golden["flingPhysicsVectors"]
            if item["name"] == "sloped-chart-contact-uses-relative-descending-derivative"
        )
        chart = PetTarget(
            "diagonal",
            PetTargetKind.CHART,
            PetRect(0, 0, 200, 200),
            tuple(PetPoint(*point) for point in vector["chartSegment"]),
        )

        landed = advance_pet(
            PetState(
                PetPoint(*vector["initialPosition"]),
                PetMode.FLING,
                horizontal_velocity=vector["releaseVelocity"][0],
                vertical_velocity=vector["releaseVelocity"][1],
            ),
            [chart],
            PetRect(0, 0, 400, 400),
        )

        self.assertEqual(landed.mode.value, vector["expectedMode"])
        self.assertEqual(landed.target_id, chart.id)
        assert_point(self, landed.position, vector["expectedContactPoint"])
        self.assertEqual(landed.horizontal_velocity, 0.0)

    def test_window_portal_maps_full_sprite_and_selects_only_adjacent_viewable(self):
        source = PetWindow("main", PetRect(0, 0, 400, 300), order=0)
        right = PetWindow("study", PetRect(400, 0, 400, 300), order=1)
        hidden = PetWindow("hidden", PetRect(400, 0, 400, 300), order=2, viewable=False)
        selected = select_adjacent_window(source, [hidden, right], "right", PetPoint(399, 150))
        self.assertEqual(selected, right)
        entry = map_pet_entry(
            source.rect,
            right.rect,
            PetPoint(399, 150),
            "left",
            56,
            mode=PetMode.FLING,
            velocity=PetPoint(420, 0),
        )
        self.assertEqual(entry.position, PetPoint(56, 150))
        self.assertEqual(entry.velocity, PetPoint(420, 0))
        self.assertEqual(entry.mode, PetMode.FLING)
        top = map_pet_entry(
            source.rect,
            PetRect(0, 300, 400, 300),
            PetPoint(200, 299),
            "top",
            56,
            mode=PetMode.FALL,
            velocity=PetPoint(0, 125),
        )
        self.assertEqual(top.position, PetPoint(200, -56))
        self.assertEqual(top.mode, PetMode.FALL)
        bottom = map_pet_entry(
            PetRect(0, 300, 400, 300),
            source.rect,
            PetPoint(200, 1),
            "bottom",
            56,
            mode=PetMode.FLING,
            velocity=PetPoint(0, -320),
        )
        self.assertEqual(bottom.position, PetPoint(200, 356))
        self.assertEqual(bottom.mode, PetMode.FLING)

    def test_window_coordinator_migrates_active_state_at_portal(self):
        coordinator = PetWindowCoordinator(
            PetState(
                PetPoint(344, 150),
                PetMode.FLING,
                horizontal_velocity=420,
            )
        )
        main = PetWindow("main", PetRect(0, 0, 400, 300), order=0)
        study = PetWindow("study", PetRect(400, 0, 400, 300), order=1)
        coordinator.register_window(main, active=True, pet_half_size=56)
        coordinator.register_window(study)

        self.assertTrue(coordinator.migrate_if_needed("main", 56))
        self.assertEqual(coordinator.active_window_id, "study")
        self.assertEqual(coordinator.state.position, PetPoint(56, 150))
        self.assertEqual(coordinator.state.velocity, PetPoint(420, 0))

    def test_window_coordinator_predicts_high_speed_exit_before_local_reflection(self):
        """A fast fling crossing the edge in one tick enters its neighbour."""
        coordinator = PetWindowCoordinator(
            PetState(
                PetPoint(330, 150),
                PetMode.FLING,
                horizontal_velocity=1800,
            )
        )
        main = PetWindow("main", PetRect(0, 0, 400, 300), order=0)
        study = PetWindow("study", PetRect(400, 0, 400, 300), order=1)
        coordinator.register_window(main, active=True, pet_half_size=56)
        coordinator.register_window(study)

        self.assertTrue(coordinator.migrate_if_needed("main", 56))
        self.assertEqual(coordinator.active_window_id, "study")
        crossing_time = 14 / 1800
        self.assertAlmostEqual(coordinator.state.position.x, 56)
        self.assertAlmostEqual(
            coordinator.state.position.y,
            150 + 0.5 * FLING_GRAVITY * crossing_time * crossing_time,
        )
        self.assertAlmostEqual(coordinator.state.horizontal_velocity, 1800)
        self.assertAlmostEqual(coordinator.state.vertical_velocity, FLING_GRAVITY * crossing_time)

    def test_window_coordinator_predicts_downward_exit_into_window_below(self):
        coordinator = PetWindowCoordinator(
            PetState(
                PetPoint(200, 320),
                PetMode.FLING,
                vertical_velocity=1800,
            )
        )
        coordinator.register_window(
            PetWindow("main", PetRect(0, 0, 400, 400)),
            active=True,
            pet_half_size=56,
        )
        coordinator.register_window(PetWindow("reminder", PetRect(0, 400, 400, 400)))

        self.assertTrue(
            coordinator.migrate_if_needed("main", 56, lookahead_seconds=0.016)
        )
        self.assertEqual(coordinator.active_window_id, "reminder")
        self.assertEqual(coordinator.state.position, PetPoint(200, -56))
        self.assertEqual(coordinator.state.mode, PetMode.FALL)
        gravity = FLING_GRAVITY
        crossing_time = (-1800 + math.sqrt(1800 ** 2 + 2 * gravity * 24)) / gravity
        self.assertAlmostEqual(coordinator.state.vertical_velocity, 1800 + gravity * crossing_time)

    def test_predicted_portal_crossings_are_continuous_and_earliest_first(self):
        crossings = predicted_exit_times(
            PetState(
                PetPoint(330, 230),
                PetMode.FLING,
                horizontal_velocity=1800,
                vertical_velocity=1000,
            ),
            PetRect(0, 0, 400, 300),
            56,
        )
        self.assertEqual([direction for _, direction in crossings], ["right", "bottom"])
        self.assertAlmostEqual(crossings[0][0], 14 / 1800, places=9)
        self.assertLess(crossings[0][0], crossings[1][0])

    def test_predicted_portal_crossings_honor_nonzero_viewport_origin(self):
        crossings = predicted_exit_times(
            PetState(PetPoint(430, 180), PetMode.FLING, horizontal_velocity=500),
            PetRect(100, 50, 400, 300),
            20,
            duration=0.2,
        )
        self.assertEqual(crossings[0][1], "right")
        self.assertAlmostEqual(crossings[0][0], 50 / 500, places=9)

    def test_window_coordinator_preserves_world_position_for_nonadjacent_close(self):
        coordinator = PetWindowCoordinator(
            PetState(
                PetPoint(120, 80),
                PetMode.FLING,
                target_id="dialog-local",
                idle_ticks_remaining=4,
                avoid_target_id="old-target",
                horizontal_velocity=180,
                curve_velocity=1.5,
            )
        )
        coordinator.register_window(PetWindow("main", PetRect(0, 0, 400, 300)), active=True, pet_half_size=56)
        coordinator.register_window(PetWindow("dialog", PetRect(900, 700, 400, 300)), active=True, pet_half_size=56)
        coordinator.unregister_window("dialog", pet_half_size=56)

        self.assertEqual(coordinator.active_window_id, "main")
        self.assertEqual(coordinator.state.position, PetPoint(344, 244))
        self.assertIsNone(coordinator.state.target_id)
        self.assertEqual(coordinator.state.idle_ticks_remaining, 0)
        self.assertIsNone(coordinator.state.avoid_target_id)
        self.assertIsNone(coordinator.state.curve_velocity)

    def test_window_coordinator_keeps_falling_pet_outside_nonadjacent_fallback(self):
        coordinator = PetWindowCoordinator(
            PetState(
                PetPoint(120, 100),
                PetMode.FALL,
                vertical_velocity=125,
            )
        )
        coordinator.register_window(
            PetWindow("dialog", PetRect(900, -200, 400, 300)),
            active=True,
            pet_half_size=56,
        )
        coordinator.register_window(
            PetWindow("main", PetRect(0, 0, 400, 300)),
            active=False,
            pet_half_size=56,
        )

        coordinator.unregister_window("dialog", pet_half_size=56)

        self.assertEqual(coordinator.active_window_id, "main")
        self.assertEqual(coordinator.state.mode, PetMode.FALL)
        self.assertEqual(coordinator.state.position, PetPoint(344, -100))
        self.assertEqual(coordinator.state.vertical_velocity, 125)

    def test_window_coordinator_keeps_falling_pet_outside_nonadjacent_activation(self):
        coordinator = PetWindowCoordinator(
            PetState(
                PetPoint(120, 100),
                PetMode.FALL,
                vertical_velocity=125,
            )
        )
        coordinator.register_window(
            PetWindow("main", PetRect(0, 0, 400, 300)),
            active=True,
            pet_half_size=56,
        )
        coordinator.register_window(PetWindow("dialog", PetRect(900, 500, 400, 300)))

        self.assertTrue(coordinator.activate("dialog", pet_half_size=56))
        self.assertEqual(coordinator.active_window_id, "dialog")
        self.assertEqual(coordinator.state.mode, PetMode.FALL)
        self.assertEqual(coordinator.state.position, PetPoint(56, -400))
        self.assertEqual(coordinator.state.vertical_velocity, 125)

    def test_window_coordinator_migrates_fling_through_top_edge(self):
        coordinator = PetWindowCoordinator(
            PetState(
                PetPoint(200, 56),
                PetMode.FLING,
                vertical_velocity=-320,
            )
        )
        coordinator.register_window(PetWindow("main", PetRect(0, 300, 400, 300)), active=True, pet_half_size=56)
        coordinator.register_window(PetWindow("above", PetRect(0, 0, 400, 300)))

        self.assertTrue(coordinator.migrate_if_needed("main", 56))
        self.assertEqual(coordinator.active_window_id, "above")
        self.assertEqual(coordinator.state.position, PetPoint(200, 356))
        self.assertEqual(coordinator.state.mode, PetMode.FLING)
        self.assertEqual(coordinator.state.vertical_velocity, -320)

    def test_window_coordinator_clears_source_bookkeeping_but_keeps_drag_offset(self):
        coordinator = PetWindowCoordinator(
            PetState(
                PetPoint(344, 150),
                PetMode.DRAGGING,
                target_id="source-target",
                idle_ticks_remaining=8,
                avoid_target_id="source-avoid",
                drag_offset=PetPoint(-12, 7),
                curve_velocity=-1.25,
            )
        )
        coordinator.register_window(
            PetWindow("main", PetRect(0, 0, 400, 300)),
            active=True,
            pet_half_size=56,
        )
        coordinator.register_window(PetWindow("dialog", PetRect(400, 0, 400, 300)))

        self.assertTrue(coordinator.migrate_if_needed("main", 56))
        self.assertEqual(coordinator.state.mode, PetMode.DRAGGING)
        self.assertIsNone(coordinator.state.target_id)
        self.assertEqual(coordinator.state.idle_ticks_remaining, 0)
        self.assertIsNone(coordinator.state.avoid_target_id)
        self.assertEqual(coordinator.state.drag_offset, PetPoint(-12, 7))
        self.assertIsNone(coordinator.state.curve_velocity)

    def test_window_coordinator_allows_dialog_to_main_return(self):
        dialog = PetWindow("study-dialog", PetRect(400, 0, 400, 300), order=1)
        main = PetWindow("main", PetRect(0, 0, 400, 300), order=0)
        coordinator = PetWindowCoordinator(
            PetState(
                PetPoint(56, 150),
                PetMode.FLING,
                horizontal_velocity=-420,
            )
        )
        coordinator.register_window(dialog, active=True, pet_half_size=56)
        coordinator.register_window(main)

        self.assertTrue(coordinator.migrate_if_needed("study-dialog", 56))
        self.assertEqual(coordinator.active_window_id, "main")
        self.assertEqual(coordinator.state.position, PetPoint(344, 150))
        self.assertEqual(coordinator.state.velocity, PetPoint(-420, 0))

    def test_bottom_portal_maps_to_destination_top_without_clipping(self):
        entry = map_pet_entry(
            PetRect(0, 0, 400, 300),
            PetRect(0, 300, 400, 300),
            PetPoint(200, 244),
            "top",
            56,
            mode=PetMode.FLING,
            velocity=PetPoint(0, 320),
        )
        self.assertEqual(entry.position, PetPoint(200, -56))
        self.assertEqual(entry.mode, PetMode.FALL)
        self.assertEqual(entry.velocity, PetPoint(0, 320))

    def test_top_portal_keeps_fling_outside_destination_bottom_edge(self):
        entry = map_pet_entry(
            PetRect(0, 300, 400, 300),
            PetRect(0, 0, 400, 300),
            PetPoint(200, 56),
            "bottom",
            56,
            mode=PetMode.FLING,
            velocity=PetPoint(0, -320),
        )
        self.assertEqual(entry.position, PetPoint(200, 356))
        self.assertEqual(entry.mode, PetMode.FLING)
        self.assertEqual(entry.velocity, PetPoint(0, -320))

    def test_window_coordinator_unregisters_active_host_to_adjacent_fallback(self):
        coordinator = PetWindowCoordinator(
            PetState(
                PetPoint(344, 150),
                PetMode.FLING,
                horizontal_velocity=420,
            )
        )
        coordinator.register_window(PetWindow("main", PetRect(0, 0, 400, 300)), active=True, pet_half_size=56)
        coordinator.register_window(PetWindow("study", PetRect(400, 0, 400, 300), order=1))

        coordinator.unregister_window("main", pet_half_size=56)
        self.assertEqual(coordinator.active_window_id, "study")
        self.assertEqual(coordinator.state.position, PetPoint(56, 150))
        self.assertEqual(coordinator.state.velocity, PetPoint(420, 0))

    def test_window_portal_direction_is_case_insensitive(self):
        source = PetRect(0, 0, 400, 300)
        target = PetRect(400, 0, 400, 300)
        entry = map_pet_entry(source, target, PetPoint(390, 150), "LEFT", 56)
        self.assertEqual(entry.position, PetPoint(56, 150))
        selected = select_adjacent_window(
            PetWindow("main", source),
            [PetWindow("study", target)],
            "RIGHT",
            PetPoint(390, 150),
        )
        self.assertIsNotNone(selected)
        self.assertEqual(selected.id, "study")

    def test_window_selection_rejects_overlap_for_autonomy_but_allows_drag(self):
        source = PetWindow("main", PetRect(100, 100, 400, 300), order=0)
        overlapping = PetWindow("dialog", PetRect(200, 100, 400, 300), order=1)
        position = PetPoint(399, 150)

        self.assertIsNone(
            select_adjacent_window(source, [overlapping], "right", position)
        )
        self.assertEqual(
            select_adjacent_window(
                source,
                [overlapping],
                "right",
                position,
                allow_overlap=True,
            ),
            overlapping,
        )

    def test_window_selection_rejects_candidate_missed_by_motion_ray(self):
        source = PetWindow("main", PetRect(0, 0, 400, 300))
        off_axis = PetWindow("dialog", PetRect(400, 200, 400, 100))
        aligned = PetWindow("aligned", PetRect(400, 0, 400, 100), order=1)
        position = PetPoint(344, 60)

        self.assertIsNone(select_adjacent_window(source, [off_axis], "right", position))
        self.assertEqual(
            select_adjacent_window(source, [off_axis, aligned], "right", position),
            aligned,
        )

    def test_window_selection_uses_first_diagonal_ray_intersection_across_gap(self):
        vector = next(
            item
            for item in self.golden["windowRayVectors"]
            if item["name"]
            == "gapped-diagonal-ray-rejects-near-miss-and-selects-first-hit"
        )
        source_data = vector["sourceWindow"]
        source = PetWindow(source_data["id"], PetRect(*source_data["rect"]))
        candidates = [
            PetWindow(
                candidate["id"],
                PetRect(*candidate["rect"]),
                order=candidate["order"],
            )
            for candidate in vector["candidates"]
        ]
        origin_world = PetPoint(*vector["rayOriginWorld"])
        position = PetPoint(
            origin_world.x - source.rect.left,
            origin_world.y - source.rect.top,
        )
        motion = PetPoint(*vector["velocity"])
        lookahead = vector["lookaheadSeconds"]
        rejected = {
            candidate.id: candidate
            for candidate in candidates
            if candidate.id in vector["expectedRejected"]
        }

        for candidate in rejected.values():
            self.assertIsNone(
                select_adjacent_window(
                    source,
                    [candidate],
                    "right",
                    position,
                    motion=motion,
                    max_time=lookahead,
                )
            )
        selected = select_adjacent_window(
            source,
            candidates,
            "right",
            position,
            motion=motion,
            max_time=lookahead,
        )
        self.assertIsNotNone(selected)
        self.assertEqual(selected.id, vector["expectedHost"])

        entry_time = ray_rect_entry_time(
            origin_world,
            motion,
            selected.rect,
            max_time=lookahead,
        )
        self.assertIsNotNone(entry_time)
        self.assertAlmostEqual(entry_time, vector["expectedIntersectionTimeSeconds"])
        intersection = PetPoint(
            origin_world.x + motion.x * entry_time,
            origin_world.y + motion.y * entry_time,
        )
        assert_point(self, intersection, vector["expectedIntersectionPoint"])

        beyond_tick = PetWindow("beyond-tick", PetRect(500, 60, 400, 200), order=3)
        self.assertIsNone(
            select_adjacent_window(
                source,
                [beyond_tick],
                "right",
                position,
                motion=motion,
                max_time=lookahead,
            )
        )
        self.assertEqual(
            select_adjacent_window(
                source,
                [beyond_tick],
                "right",
                position,
                motion=motion,
            ),
            beyond_tick,
        )

    def test_window_coordinator_maps_from_diagonal_ray_intersection(self):
        vector = next(
            item
            for item in self.golden["windowRayVectors"]
            if item["name"]
            == "gapped-diagonal-ray-rejects-near-miss-and-selects-first-hit"
        )
        source_data = vector["sourceWindow"]
        source = PetWindow(source_data["id"], PetRect(*source_data["rect"]))
        candidates = [
            PetWindow(
                candidate["id"],
                PetRect(*candidate["rect"]),
                order=candidate["order"],
            )
            for candidate in vector["candidates"]
        ]
        origin_world = PetPoint(*vector["rayOriginWorld"])
        velocity = PetPoint(*vector["velocity"])
        coordinator = PetWindowCoordinator(
            PetState(
                position=PetPoint(
                    origin_world.x - source.rect.left,
                    origin_world.y - source.rect.top,
                ),
                mode=PetMode.FLING,
                vertical_velocity=velocity.y,
                horizontal_velocity=velocity.x,
            )
        )
        coordinator.register_window(source, active=True)
        for candidate in candidates:
            coordinator.register_window(candidate)

        self.assertTrue(
            coordinator.migrate_if_needed(
                source.id,
                pet_half_size=0.0,
                lookahead_seconds=vector["lookaheadSeconds"],
            )
        )
        self.assertEqual(coordinator.active_window_id, vector["expectedHost"])
        assert_point(self, coordinator.world_position(), vector["expectedIntersectionPoint"])

    def test_fall_entry_from_top_preserves_outside_y_until_crossing_viewport(self):
        viewport = PetRect(0, 0, 400, 300)
        support = PetTarget("landing", PetTargetKind.SURFACE, PetRect(0, 100, 400, 20))
        entry = map_pet_entry(
            PetRect(0, -300, 400, 300),
            viewport,
            PetPoint(200, 300),
            "top",
            56,
            mode=PetMode.FALL,
            velocity=PetPoint(0, 125),
        )
        state = PetState(
            entry.position,
            entry.mode,
            vertical_velocity=entry.velocity.y,
        )
        next_state = advance_pet(state, [support], viewport, pet_size=56)
        self.assertEqual(next_state.mode, PetMode.FALL)
        self.assertGreater(next_state.position.y, entry.position.y)
        self.assertLess(next_state.position.y, viewport.top + 56)
        self.assertEqual(next_state.position.x, entry.position.x)


if __name__ == "__main__":
    unittest.main()
