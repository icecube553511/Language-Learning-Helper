from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest


WINDOWS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WINDOWS_DIR))

from domain.dictation import MarkMode
from domain.models import ExampleSentence, LearntWord, ReviewState, VocabularyEntry
from infrastructure.catalog import CatalogLoader
from infrastructure.repository import JsonLearningRepository
from infrastructure.words_learnt_repository import JsonWordsLearntRepository


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
        repo.set_review_batch_size(14)
        repo.set_study_order("alphabetical")
        repo.set_study_levels({"CET4", "CET6"})
        repo.set_review_levels({"CET6"})
        repo.set_reminder_levels({"CET4"})
        repo.set_reminder_enabled(True)
        repo.set_reminder_interval_minutes(2.75)
        loaded = JsonLearningRepository(directory, [sample_entry()])
        self.assertEqual(loaded.review_state("serene").state, "review")
        self.assertEqual(loaded.get_font_scale(), 1.25)
        self.assertEqual(loaded.get_review_batch_size(), 14)
        self.assertEqual(loaded.get_study_order(), "alphabetical")
        self.assertEqual(loaded.get_study_levels(), {"CET4", "CET6"})
        self.assertEqual(loaded.get_review_levels(), {"CET6"})
        self.assertEqual(loaded.get_reminder_levels(), {"CET4"})
        self.assertTrue(loaded.get_reminder_enabled())
        self.assertEqual(loaded.get_reminder_interval_minutes(), 2.75)
        self.assertEqual(sum(len(v) for v in loaded._activity.values()), 1)

    def test_reminder_interval_falls_back_and_is_bounded(self):
        directory = Path(self.temp.name)
        repo = JsonLearningRepository(directory)
        repo.set_reminder_interval_minutes(0.1)
        self.assertEqual(repo.get_reminder_interval_minutes(), 0.5)
        repo.set_reminder_interval_minutes(999)
        self.assertEqual(repo.get_reminder_interval_minutes(), 120.0)

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

    def test_batch_labels_only_update_user_entries(self):
        directory = Path(self.temp.name)
        built_in = sample_entry("built-in")
        user = sample_entry("user")
        repo = JsonLearningRepository(directory, [built_in])
        repo.add_entries([user])

        self.assertEqual(repo.update_entry_labels({built_in.word_id, user.word_id}, "CET6", {"exam", "batch"}), 1)
        entries = {entry.word_id: entry for entry in repo.all_entries()}
        self.assertEqual(entries[built_in.word_id].level, "CET4")
        self.assertEqual(entries[user.word_id].level, "CET6")
        self.assertEqual(entries[user.word_id].tags, ("batch", "exam"))

    def test_words_learnt_uses_independent_json_file(self):
        directory = Path(self.temp.name)
        JsonLearningRepository(directory).set_review_batch_size(20)
        repository = JsonWordsLearntRepository(directory)
        repository.save_learnt_word(LearntWord("serene", 0.8, 1000, 1000))

        loaded = JsonWordsLearntRepository(directory)
        self.assertEqual(loaded.learnt_word("serene"), LearntWord("serene", 0.8, 1000, 1000))
        payload = json.loads((directory / "Words_Learnt.json").read_text(encoding="utf-8"))
        self.assertEqual(payload["schemaVersion"], 1)
        self.assertIn("serene", payload["wordsLearnt"])
        self.assertEqual(payload["wordsLearnt"]["serene"]["reviewCount"], 0)
        learning_payload = json.loads((directory / "learning-state.json").read_text(encoding="utf-8"))
        self.assertNotIn("wordsLearnt", learning_payload)

    def test_words_learnt_invalid_weight_falls_back_to_neutral(self):
        directory = Path(self.temp.name)
        path = directory / "Words_Learnt.json"
        path.write_text(json.dumps({
            "schemaVersion": 1,
            "wordsLearnt": {
                "serene": {
                    "wordId": "serene",
                    "weight": 0.33,
                    "learntAtUtc": 1000,
                    "lastReviewedAtUtc": 1000,
                    "reviewCount": 0,
                },
            },
        }), encoding="utf-8")

        self.assertEqual(JsonWordsLearntRepository(directory).learnt_word("serene").weight, 0.2)

    def test_tag_override_and_mark_mode_survive_restart_without_changing_catalog_entry(self):
        directory = Path(self.temp.name)
        built_in = sample_entry("serene")
        repo = JsonLearningRepository(directory, [built_in])
        self.assertEqual(repo.update_tags({"serene"}, {"evaluated", "zk"}, {"cet4"}), 1)
        repo.set_mark_mode(MarkMode.NEVER)
        loaded = JsonLearningRepository(directory, [built_in])
        loaded_entry = loaded.all_entries()[0]
        self.assertEqual(set(loaded_entry.tags), {"evaluated", "zk"})
        self.assertEqual(set(built_in.tags), set())
        self.assertEqual(loaded.get_mark_mode(), MarkMode.NEVER)
        payload = json.loads((directory / "learning-state.json").read_text(encoding="utf-8"))
        self.assertEqual(payload["tagOverrides"]["serene"], ["evaluated", "zk"])


if __name__ == "__main__":
    unittest.main()
