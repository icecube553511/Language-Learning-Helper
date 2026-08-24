from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest


WINDOWS_DIR = Path(__file__).resolve().parents[1]
ROOT_DIR = WINDOWS_DIR.parent
sys.path.insert(0, str(WINDOWS_DIR))

from domain.models import ReviewRating, ReviewState
from domain.scheduler import retention_at, schedule_review


class SchedulerContractTests(unittest.TestCase):
    def test_shared_golden_vectors(self):
        golden = json.loads(
            (ROOT_DIR / "shared" / "contracts" / "scheduler-golden-v1.json").read_text(encoding="utf-8")
        )
        for vector in golden["vectors"]:
            with self.subTest(vector=vector["name"]):
                initial = ReviewState(word_id="golden", **{
                    "state": golden["initial"]["state"],
                    "interval_days": golden["initial"]["intervalDays"],
                    "ease": golden["initial"]["ease"],
                    "repetitions": golden["initial"]["repetitions"],
                    "lapses": golden["initial"]["lapses"],
                })
                actual = schedule_review(initial, vector["rating"], vector["reviewedAtUtc"])
                expected = vector["expected"]
                self.assertEqual(actual.state, expected["state"])
                self.assertAlmostEqual(actual.interval_days, expected["intervalDays"])
                self.assertAlmostEqual(actual.ease, expected["ease"])
                self.assertEqual(actual.repetitions, expected["repetitions"])
                self.assertEqual(actual.lapses, expected["lapses"])
                self.assertAlmostEqual(actual.due_at_utc, expected["dueAtUtc"])

    def test_hard_review_uses_existing_interval(self):
        state = ReviewState("word", state="review", interval_days=5, ease=2.2, repetitions=3)
        actual = schedule_review(state, ReviewRating.HARD, 1000)
        self.assertAlmostEqual(actual.interval_days, 6)
        self.assertAlmostEqual(actual.ease, 2.05)
        self.assertEqual(actual.state, "review")

    def test_retention_matches_contract_formula(self):
        state = ReviewState("word", interval_days=3, last_reviewed_at_utc=1000)
        self.assertAlmostEqual(retention_at(state, 1000), 1.0)
        self.assertAlmostEqual(retention_at(state, 1000 + 3 * 86400), 0.36787944117)


if __name__ == "__main__":
    unittest.main()

