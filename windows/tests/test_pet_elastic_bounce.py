from __future__ import annotations

import json
import math
from pathlib import Path
import sys
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from domain.pet_companion import (
    BOUNCE_COUNT, BOUNCE_DECAY, BOUNCE_TOP_RESTITUTION, FALL_GRAVITY,
    FALL_TIME_STEP_SECONDS, MAX_BOUNCE_SPEED, MIN_BOUNCE_SPEED,
    PetMode, PetPoint, PetRect, PetState, PetTarget, PetTargetKind, advance_pet,
)


class PetElasticBounceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = Path(__file__).resolve().parents[2] / "shared/contracts/pet-companion-golden-v1.json"
        golden = json.loads(path.read_text(encoding="utf-8"))
        cls.vectors = {item["name"]: item for item in golden["bounceStabilityVectors"]}

    def test_higher_impact_produces_higher_rebound_with_finite_cap(self):
        vector = self.vectors["rebound-speed-follows-impact-with-cap"]
        viewport = PetRect(0, 0, 500, 1000)
        rebound_speeds = []
        heights = []
        for impact in vector["impactSpeeds"]:
            state = advance_pet(
                PetState(PetPoint(200, 1000), PetMode.FALL, vertical_velocity=impact),
                [], viewport,
            )
            rebound_speeds.append(-state.vertical_velocity)
            minimum_y = state.position.y
            while state.vertical_velocity < 0:
                state = advance_pet(state, [], viewport)
                minimum_y = min(minimum_y, state.position.y)
            heights.append(1000 - minimum_y)
        self.assertEqual(rebound_speeds, vector["expectedReboundSpeeds"])
        self.assertLess(heights[0], heights[1])
        self.assertLess(heights[1], heights[2])

    def test_rebound_uses_contact_speed_and_consumes_remaining_tick(self):
        viewport = PetRect(0, 0, 500, 500)
        support = PetTarget("support", PetTargetKind.SURFACE, PetRect(0, 300, 500, 20))
        state = PetState(
            PetPoint(200, 299), PetMode.BOUNCE, target_id=support.id,
            vertical_velocity=200, bounces_remaining=4,
        )
        hit_speed = math.sqrt(200 ** 2 + 2 * FALL_GRAVITY)
        hit_time = (hit_speed - 200) / FALL_GRAVITY
        remaining = FALL_TIME_STEP_SECONDS - hit_time
        rebound = hit_speed * BOUNCE_DECAY
        advanced = advance_pet(state, [support], viewport)
        self.assertEqual(advanced.bounces_remaining, 3)
        self.assertAlmostEqual(advanced.position.y, 300 - rebound * remaining + 0.5 * FALL_GRAVITY * remaining ** 2)
        self.assertAlmostEqual(advanced.vertical_velocity, -rebound + FALL_GRAVITY * remaining)

    def test_low_energy_bounce_stops_before_maximum_count(self):
        viewport = PetRect(0, 0, 500, 500)
        support = PetTarget("support", PetTargetKind.SURFACE, PetRect(0, 300, 500, 20))
        state = PetState(
            PetPoint(200, 300), PetMode.BOUNCE, target_id=support.id,
            vertical_velocity=MIN_BOUNCE_SPEED, bounces_remaining=5,
        )
        advanced = advance_pet(state, [support], viewport)
        self.assertEqual(advanced.mode, PetMode.IDLE)
        self.assertEqual(advanced.bounces_remaining, 0)
        self.assertEqual(advanced.vertical_velocity, 0)

    def test_ceiling_contact_reflects_then_continues_same_tick(self):
        viewport = PetRect(0, 0, 500, 500)
        support = PetTarget("support", PetTargetKind.SURFACE, PetRect(0, 400, 500, 20))
        half = 56
        state = PetState(
            PetPoint(200, half + 1), PetMode.BOUNCE, target_id=support.id,
            vertical_velocity=-800, bounces_remaining=4,
        )
        hit_speed = math.sqrt(800 ** 2 - 2 * FALL_GRAVITY)
        hit_time = (800 - hit_speed) / FALL_GRAVITY
        remaining = FALL_TIME_STEP_SECONDS - hit_time
        downward_speed = hit_speed * BOUNCE_TOP_RESTITUTION
        advanced = advance_pet(state, [support], viewport, pet_size=half)
        self.assertEqual(advanced.mode, PetMode.BOUNCE)
        self.assertEqual(advanced.bounces_remaining, 4)
        self.assertAlmostEqual(advanced.position.y, half + downward_speed * remaining + 0.5 * FALL_GRAVITY * remaining ** 2)
        self.assertAlmostEqual(advanced.vertical_velocity, downward_speed + FALL_GRAVITY * remaining)
        self.assertGreater(advanced.position.y, half)

    def test_full_elastic_sequence_loses_energy_and_stays_with_original_edge(self):
        vector = self.vectors["bottom-bounce-retains-anchor-before-upper-content-return"]
        viewport = PetRect(0, 0, *vector["viewport"])
        half = vector["petHalfSize"]
        upper_data, bottom_data = vector["upperTarget"], vector["bottomTarget"]
        upper = PetTarget(upper_data["id"], PetTargetKind(upper_data["kind"]), PetRect(*upper_data["rect"]))
        bottom = PetTarget(bottom_data["id"], PetTargetKind(bottom_data["kind"]), PetRect(*bottom_data["rect"]))
        targets = [upper, bottom]
        state = PetState(PetPoint(*vector["position"]), PetMode.FALL)
        initial_x = state.position.x
        bounce_counts = []
        landed = False
        energy = None
        floor_y = vector["expectedBottomY"]
        for _ in range(vector["ticks"]):
            previous = state
            state = advance_pet(state, targets, viewport, pet_size=half)
            self.assertEqual(state.position.x, initial_x)
            if state.mode == PetMode.BOUNCE:
                landed = True
                self.assertEqual(state.target_id, bottom.id)
                self.assertGreaterEqual(state.position.y, half)
                self.assertLessEqual(state.position.y, floor_y)
                next_energy = 0.5 * state.vertical_velocity ** 2 + FALL_GRAVITY * (floor_y - state.position.y)
                if energy is not None:
                    self.assertLessEqual(next_energy, energy + 1e-6)
                energy = next_energy
                if not bounce_counts or bounce_counts[-1] != state.bounces_remaining:
                    bounce_counts.append(state.bounces_remaining)
                if previous.mode == PetMode.BOUNCE:
                    self.assertLessEqual(previous.position.y - state.position.y, vector["maxUpwardStep"])
            elif landed:
                self.assertEqual(state.mode, PetMode.IDLE)
                self.assertEqual(state.position, PetPoint(initial_x, floor_y))
                break
        self.assertTrue(landed)
        self.assertEqual(bounce_counts, list(range(vector["expectedRebounds"], 0, -1)))
        self.assertEqual(state.mode, PetMode.IDLE)
        returned = False
        for _ in range(220):
            previous = state.position
            state = advance_pet(state, targets, viewport, pet_size=half)
            self.assertLessEqual(math.hypot(state.position.x - previous.x, state.position.y - previous.y), 4.000001)
            if state.target_id == upper.id:
                returned = True
        self.assertTrue(returned)


if __name__ == "__main__":
    unittest.main()
