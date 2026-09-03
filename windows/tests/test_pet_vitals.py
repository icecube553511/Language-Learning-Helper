from __future__ import annotations

import json
import math
from dataclasses import FrozenInstanceError
from pathlib import Path
import sys
import unittest


WINDOWS_DIR = Path(__file__).resolve().parents[1]
ROOT_DIR = WINDOWS_DIR.parent
sys.path.insert(0, str(WINDOWS_DIR))

from domain.pet_vitals import (
    FoodJar,
    HungerState,
    Mood,
    PetVitals,
    ReviewRecoveryTag,
    apply_rating_reward,
    apply_vital_change,
)


GOLDEN = json.loads(
    (ROOT_DIR / "shared" / "contracts" / "pet-vitals-golden-v1.json")
    .read_text(encoding="utf-8")
)


class PetVitalsContractTests(unittest.TestCase):
    def test_defaults_and_mood_labels_match_golden(self):
        defaults = GOLDEN["defaults"]
        self.assertEqual(
            PetVitals(),
            PetVitals(
                defaults["satiety"],
                defaults["foodReserve"],
                Mood(defaults["mood"]),
            ),
        )
        self.assertEqual(
            [(mood.value, mood.label) for mood in Mood],
            [(item["name"], item["label"]) for item in GOLDEN["moods"]],
        )

    def test_food_jar_is_immutable_composed_and_owns_reserve_operations(self):
        bounds = GOLDEN["bounds"]
        jar = FoodJar(bounds["foodReserveMaximum"] - 1.0)
        self.assertEqual(jar.capacity, bounds["foodReserveMaximum"])
        self.assertEqual(jar.remaining_capacity, 1.0)
        self.assertEqual(jar.add_direct(5.0).stored_satiety, jar.capacity)
        self.assertEqual(jar.store_overflow(5.0).stored_satiety, jar.capacity)
        self.assertEqual(FoodJar().add_direct(5.0).stored_satiety, 5.0)
        self.assertEqual(FoodJar().store_overflow(5.0).stored_satiety, 1.0)

        remaining, transferred = FoodJar(12.0).withdraw(5.0)
        self.assertEqual((remaining.stored_satiety, transferred), (7.0, 5.0))
        empty, transferred = remaining.withdraw(20.0)
        self.assertEqual((empty.stored_satiety, transferred), (0.0, 7.0))
        self.assertEqual(jar.stored_satiety, bounds["foodReserveMaximum"] - 1.0)
        with self.assertRaises(FrozenInstanceError):
            jar.stored_satiety = 0.0
        for operation in (
            lambda: FoodJar().add_direct(-1.0),
            lambda: FoodJar().store_overflow(-1.0),
            lambda: FoodJar().withdraw(-1.0),
        ):
            with self.assertRaises(ValueError):
                operation()

        vitals = PetVitals(food_jar=FoodJar(9.5))
        self.assertIsInstance(vitals.food_jar, FoodJar)
        self.assertEqual(vitals.food_reserve, 9.5)
        self.assertEqual(vitals.to_dict()[GOLDEN["foodJar"]["persistedField"]], 9.5)

    def test_hunger_boundaries_match_every_golden_vector(self):
        for vector in GOLDEN["hungerStateVectors"]:
            with self.subTest(satiety=vector["satiety"]):
                self.assertEqual(
                    PetVitals(satiety=vector["satiety"]).hunger_state,
                    HungerState(vector["expected"]),
                )

    def test_complete_reward_matrix_matches_golden(self):
        for rule in GOLDEN["rewardRules"]:
            prior = ReviewRecoveryTag.from_persisted(rule["priorTag"])
            with self.subTest(
                phase=rule["phase"],
                prior=rule["priorTag"],
                rating=rule["rating"],
            ):
                outcome = apply_rating_reward(
                    PetVitals(),
                    rule["phase"],
                    rule["rating"],
                    prior,
                )
                self.assertAlmostEqual(outcome.satiety_gain, rule["satietyGain"])
                self.assertAlmostEqual(
                    outcome.food_reserve_gain,
                    rule["foodReserveGain"],
                )
                self.assertEqual(
                    outcome.next_marker,
                    ReviewRecoveryTag.from_persisted(rule["nextTag"]),
                )
                self.assertAlmostEqual(
                    outcome.vitals.satiety,
                    GOLDEN["defaults"]["satiety"] + rule["satietyGain"],
                )
                self.assertAlmostEqual(
                    outcome.vitals.food_reserve,
                    rule["foodReserveGain"],
                )
                self.assertEqual(outcome.vitals.mood, Mood.CALM)

    def test_vital_change_vectors_match_golden(self):
        for vector in GOLDEN["vitalChangeVectors"]:
            with self.subTest(name=vector["name"]):
                actual = apply_vital_change(
                    PetVitals(vector["satiety"], vector["foodReserve"]),
                    vector["satietyGain"],
                    vector["foodReserveGain"],
                )
                self.assertAlmostEqual(actual.satiety, vector["expectedSatiety"])
                self.assertAlmostEqual(
                    actual.food_reserve,
                    vector["expectedFoodReserve"],
                )

    def test_restore_clamps_bounds_refills_and_defaults_invalid_values(self):
        restored = PetVitals.from_dict({
            "satiety": -10.0,
            "foodReserve": 250.0,
            "mood": "happy",
        })
        self.assertEqual(restored, PetVitals(50.0, 150.0, Mood.HAPPY))
        self.assertEqual(
            PetVitals.from_dict({
                "satiety": float("nan"),
                "foodReserve": float("inf"),
                "mood": "unknown",
            }),
            PetVitals(),
        )

    def test_domain_values_are_finite_python_float64(self):
        self.assertIsInstance(PetVitals().satiety, float)
        self.assertEqual(math.nextafter(50.0, math.inf), 50.00000000000001)
        for value in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    PetVitals(satiety=value)
                with self.assertRaises(ValueError):
                    apply_vital_change(PetVitals(), satiety_gain=value)

    def test_review_marker_decoder_is_mutually_exclusive_and_forgot_first(self):
        self.assertEqual(
            ReviewRecoveryTag.from_persisted([
                ReviewRecoveryTag.VAGUE.value,
                ReviewRecoveryTag.FORGOT.value,
            ]),
            ReviewRecoveryTag.FORGOT,
        )
        self.assertIsNone(ReviewRecoveryTag.from_persisted(None))


if __name__ == "__main__":
    unittest.main()
