from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest


WINDOWS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WINDOWS_DIR))

from domain.models import ExampleSentence, ReviewState, VocabularyEntry
from infrastructure.catalog import CatalogLoader
from infrastructure.repository import JsonLearningRepository


def sample_entry(word="serene"):
    return VocabularyEntry.create(
        word,
        "宁静的",
        [
            ExampleSentence("A serene lake reflected the sky.", "宁静的湖面映照着天空。"),
            ExampleSentence("She remained serene under pressure.", "她在压力下依然从容。"),
            ExampleSentence("The office felt serene after hours.", "下班后的办公室十分安静。"),
        ],
        level="CET4",
    )


class RepositoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

    def test_round_trip_review_activity_and_setting(self):
        directory = Path(self.temp.name)
        repo = JsonLearningRepository(directory, [sample_entry()])
        state = ReviewState("serene", state="review", interval_days=3, due_at_utc=1000, last_reviewed_at_utc=10)
        repo.save_review_state(state)
        repo.record_activity("serene", 1704067200)
        repo.set_font_scale(1.25)
        loaded = JsonLearningRepository(directory, [sample_entry()])
        self.assertEqual(loaded.review_state("serene").state, "review")
        self.assertEqual(loaded.get_font_scale(), 1.25)
        self.assertEqual(sum(len(v) for v in loaded._activity.values()), 1)

    def test_catalog_gracefully_handles_missing_file(self):
        loader = CatalogLoader(Path(self.temp.name) / "missing.json")
        self.assertEqual(loader.load(), [])
        self.assertEqual(loader.error, "")

    def test_catalog_rejects_entries_without_three_translations(self):
        path = Path(self.temp.name) / "catalog.json"
        path.write_text(json.dumps({"entries": [{
            "word": "thin", "meaning": "薄的",
            "examples": [{"en": "A thin line.", "zh": "一条细线。"}],
        }]}), encoding="utf-8")
        loader = CatalogLoader(path)
        self.assertEqual(loader.load(), [])
        self.assertEqual(loader.rejected_count, 1)

    def test_user_entry_persists(self):
        directory = Path(self.temp.name)
        repo = JsonLearningRepository(directory)
        self.assertEqual(repo.add_entries([sample_entry()]), 1)
        loaded = JsonLearningRepository(directory)
        self.assertEqual([item.word for item in loaded.all_entries()], ["serene"])


if __name__ == "__main__":
    unittest.main()

