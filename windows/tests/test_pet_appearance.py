from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

WINDOWS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WINDOWS_DIR))

from domain.pet_appearance import (
    PET_AIRBORNE_THRESHOLD_SECONDS,
    PET_DOUBLE_TAP_WINDOW_MS,
    PET_HUNGRY_SATIETY,
    PET_LARGE_LANDING_SPEED,
    PET_STATIONARY_THRESHOLD_SECONDS,
    PetAppearance,
    PetAppearanceAssets,
    PetAppearanceContext,
    select_pet_appearance,
)


class PetAppearanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.assets = PetAppearanceAssets.from_file_names(
            ("pain.png", "scared.png", "sleep.png", "hungry.png"),
            ("happy10.png", "happy2.png", "happy1.png"),
        )

    def test_shared_golden_vectors(self) -> None:
        root = Path(__file__).resolve().parents[2]
        payload = json.loads(
            (root / "shared" / "contracts" / "pet-appearance-golden-v1.json").read_text(encoding="utf-8")
        )
        state_files = payload["assetSet"]["stateAssets"].values()
        assets = PetAppearanceAssets.from_file_names(state_files, payload["assetSet"]["happyAssets"])
        for vector in payload["vectors"]:
            context = vector["context"]
            vector_assets = PetAppearanceAssets() if vector.get("assetSet") == "empty" else assets
            decision = select_pet_appearance(
                PetAppearanceContext(
                    landing_impact_speed=context.get("landingImpactSpeed", 0.0),
                    airborne_seconds=context.get("airborneSeconds", 0.0),
                    stationary_seconds=context.get("stationarySeconds", 0.0),
                    moving=context.get("moving", False),
                    satiety=context.get("satiety"),
                    rapid_double_tap=context.get("rapidDoubleTap", False),
                    happy_asset_index=context.get("happyAssetIndex", 0),
                ),
                vector_assets,
            )
            expected = vector["expected"]
            with self.subTest(vector=vector["name"]):
                self.assertEqual(decision.appearance.value, expected["appearance"])
                self.assertEqual(decision.asset_name, expected["asset"])
                self.assertEqual(decision.reason, expected["reason"])

    def test_contract_thresholds_are_explicit(self) -> None:
        self.assertEqual(PET_LARGE_LANDING_SPEED, 437.5)
        self.assertEqual(PET_AIRBORNE_THRESHOLD_SECONDS, 3.0)
        self.assertEqual(PET_STATIONARY_THRESHOLD_SECONDS, 30.0)
        self.assertEqual(PET_DOUBLE_TAP_WINDOW_MS, 300)
        self.assertEqual(PET_HUNGRY_SATIETY, 0.0)

    def test_large_landing_selects_pain_at_boundary(self) -> None:
        decision = select_pet_appearance(
            PetAppearanceContext(landing_impact_speed=PET_LARGE_LANDING_SPEED),
            self.assets,
        )
        self.assertEqual((decision.appearance, decision.asset_name), (PetAppearance.PAIN, "pain.png"))

    def test_airborne_includes_exact_three_seconds(self) -> None:
        decision = select_pet_appearance(
            PetAppearanceContext(airborne_seconds=PET_AIRBORNE_THRESHOLD_SECONDS),
            self.assets,
        )
        self.assertEqual(decision.appearance, PetAppearance.SCARED)

    def test_zero_satiety_is_strictly_hungry_condition(self) -> None:
        hungry = select_pet_appearance(PetAppearanceContext(satiety=0.0), self.assets)
        almost_empty = select_pet_appearance(PetAppearanceContext(satiety=0.001), self.assets)
        self.assertEqual(hungry.appearance, PetAppearance.HUNGRY)
        self.assertEqual(almost_empty.appearance, PetAppearance.NORMAL)

    def test_stationary_and_double_tap_conditions(self) -> None:
        sleeping = select_pet_appearance(
            PetAppearanceContext(stationary_seconds=PET_STATIONARY_THRESHOLD_SECONDS),
            self.assets,
        )
        happy = select_pet_appearance(
            PetAppearanceContext(rapid_double_tap=True, happy_asset_index=1),
            self.assets,
        )
        self.assertEqual(sleeping.appearance, PetAppearance.SLEEP)
        self.assertEqual((happy.appearance, happy.asset_name), (PetAppearance.HAPPY, "happy2.png"))

    def test_priority_is_pain_then_scared_then_hungry_then_other_states(self) -> None:
        decision = select_pet_appearance(
            PetAppearanceContext(
                landing_impact_speed=PET_LARGE_LANDING_SPEED,
                airborne_seconds=PET_AIRBORNE_THRESHOLD_SECONDS,
                satiety=0.0,
                stationary_seconds=PET_STATIONARY_THRESHOLD_SECONDS,
                rapid_double_tap=True,
            ),
            self.assets,
        )
        self.assertEqual(decision.appearance, PetAppearance.PAIN)

        decision = select_pet_appearance(
            PetAppearanceContext(
                airborne_seconds=PET_AIRBORNE_THRESHOLD_SECONDS,
                satiety=0.0,
                stationary_seconds=PET_STATIONARY_THRESHOLD_SECONDS,
                rapid_double_tap=True,
            ),
            self.assets,
        )
        self.assertEqual(decision.appearance, PetAppearance.SCARED)

    def test_missing_assets_keep_existing_normal_appearance(self) -> None:
        decision = select_pet_appearance(
            PetAppearanceContext(
                landing_impact_speed=PET_LARGE_LANDING_SPEED,
                airborne_seconds=PET_AIRBORNE_THRESHOLD_SECONDS,
                satiety=0.0,
                stationary_seconds=PET_STATIONARY_THRESHOLD_SECONDS,
                rapid_double_tap=True,
            ),
        )
        self.assertEqual((decision.appearance, decision.asset_name), (PetAppearance.NORMAL, None))


if __name__ == "__main__":
    unittest.main()
