from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest


WINDOWS_DIR = Path(__file__).resolve().parents[1]
ROOT_DIR = WINDOWS_DIR.parent
sys.path.insert(0, str(WINDOWS_DIR))

from domain.groups import (
    GROUP_ORDER,
    classify_groups,
    normalize_group_membership,
    normalize_group_tag,
)


GOLDEN = ROOT_DIR / "shared" / "contracts" / "vocabulary-groups-golden-v1.json"


class VocabularyGroupsTests(unittest.TestCase):
    def setUp(self):
        if not GOLDEN.is_file():
            self.fail("vocabulary-groups-golden-v1.json is missing")
        self.payload = json.loads(GOLDEN.read_text(encoding="utf-8"))

    def test_group_order_and_labels(self):
        self.assertEqual(list(self.payload["groupOrder"]), list(GROUP_ORDER))
        self.assertEqual(self.payload["groupOrder"][0], "all")
        self.assertEqual(self.payload["groupLabels"]["all"], "全部")

    def test_normalization_matches_golden(self):
        for raw, expected in self.payload.get("normalize", {}).items():
            with self.subTest(raw=raw):
                self.assertEqual(normalize_group_membership(raw), expected)

    def test_classifier_matches_golden_fixtures(self):
        counts = dict.fromkeys(self.payload["groupOrder"], 0)
        for fixture in self.payload["fixtures"]:
            memberships = fixture.get("memberships", [])
            tags = fixture.get("tags", [])
            expected = sorted(fixture.get("expectedGroups", []))
            actual = sorted(classify_groups(memberships, tags))
            with self.subTest(fixture=fixture.get("id")):
                self.assertEqual(actual, expected)
            for key in actual:
                counts[key] += 1
        self.assertEqual(counts, self.payload["expected"]["groupCounts"])

    def test_special_tags_do_not_create_groups(self):
        # A business tag is not a recognized group tag and must not spawn a group.
        groups = classify_groups(["GK"], ["business"])
        self.assertEqual(sorted(groups), ["all", "gk"])
        normalize_group_tag("Business")


if __name__ == "__main__":
    unittest.main()
