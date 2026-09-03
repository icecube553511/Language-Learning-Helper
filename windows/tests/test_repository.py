from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


WINDOWS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WINDOWS_DIR))

from domain.dictation import MarkMode
from domain.models import ExampleSentence, LearntWord, ReviewState, VocabularyEntry
from domain.pet_vitals import Mood, PetVitals, ReviewRecoveryTag
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

    def test_review_outcome_and_activity_share_one_replace_and_savepoint_restores(self):
        directory = Path(self.temp.name)
        repo = JsonLearningRepository(directory, [sample_entry()])
        state = ReviewState(
            "serene",
            state="review",
            interval_days=3,
            due_at_utc=10_000,
            last_reviewed_at_utc=1_000,
        )
        reviewed_at = 1704067200.0
        local_day = datetime.fromtimestamp(reviewed_at).strftime("%Y-%m-%d")
        real_replace = __import__("os").replace

        with mock.patch(
            "infrastructure.repository.os.replace",
            wraps=real_replace,
        ) as replace:
            savepoint = repo.save_review_outcome(state, reviewed_at)

        self.assertEqual(replace.call_count, 1)
        loaded = JsonLearningRepository(directory, [sample_entry()])
        self.assertEqual(loaded.review_state("serene"), state)
        self.assertEqual(loaded.reviewed_count_for_local_day(local_day), 1)

        repo.restore_review_savepoint(savepoint)
        restored = JsonLearningRepository(directory, [sample_entry()])
        self.assertEqual(restored.review_state("serene"), ReviewState("serene"))
        self.assertEqual(restored.reviewed_count_for_local_day(local_day), 0)

    def test_stale_review_savepoint_cannot_overwrite_a_newer_rating(self):
        directory = Path(self.temp.name)
        repo = JsonLearningRepository(directory, [sample_entry()])
        first = ReviewState("serene", state="review", repetitions=1)
        second = ReviewState("serene", state="review", repetitions=2)
        stale = repo.save_review_outcome(first, 1704067200.0)
        repo.save_review_outcome(second, 1704153600.0)

        with self.assertRaises(RuntimeError):
            repo.restore_review_savepoint(stale)

        reloaded = JsonLearningRepository(directory, [sample_entry()])
        self.assertEqual(reloaded.review_state("serene"), second)

    def test_reminder_interval_falls_back_and_is_bounded(self):
        directory = Path(self.temp.name)
        repo = JsonLearningRepository(directory)
        repo.set_reminder_interval_minutes(0.1)
        self.assertEqual(repo.get_reminder_interval_minutes(), 0.5)
        repo.set_reminder_interval_minutes(999)
        self.assertEqual(repo.get_reminder_interval_minutes(), 120.0)

    def test_font_scale_falls_back_for_corrupt_and_non_finite_values(self):
        directory = Path(self.temp.name) / "font-scale"
        directory.mkdir()
        (directory / "learning-state.json").write_text(
            json.dumps({"settings": {"fontScale": "not-a-number"}}),
            encoding="utf-8",
        )
        repo = JsonLearningRepository(directory)
        self.assertEqual(repo.get_font_scale(), 1.0)

        repo.set_font_scale(float("nan"))
        self.assertEqual(repo.get_font_scale(), 1.0)
        repo.set_font_scale(float("inf"))
        self.assertEqual(repo.get_font_scale(), 1.0)
        repo.set_font_scale(float("-inf"))
        self.assertEqual(repo.get_font_scale(), 1.0)

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
        self.assertEqual(payload["schemaVersion"], 2)
        self.assertIn("serene", payload["wordsLearnt"])
        self.assertEqual(payload["wordsLearnt"]["serene"]["reviewCount"], 0)
        self.assertIsNone(payload["wordsLearnt"]["serene"]["reviewMarker"])
        self.assertEqual(payload["petVitals"], {
            "satiety": 50.0,
            "foodReserve": 0.0,
            "mood": "calm",
        })
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

    def test_words_learnt_migrates_defaults_and_forgot_wins_marker_conflict(self):
        directory = Path(self.temp.name)
        path = directory / "Words_Learnt.json"
        path.write_text(json.dumps({
            "schemaVersion": 1,
            "wordsLearnt": {
                "serene": {
                    "wordId": "serene",
                    "weight": 0.8,
                    "learntAtUtc": 1000,
                    "lastReviewedAtUtc": 1000,
                    "reviewMarkers": [
                        ReviewRecoveryTag.VAGUE.value,
                        ReviewRecoveryTag.FORGOT.value,
                    ],
                },
            },
        }), encoding="utf-8")

        repository = JsonWordsLearntRepository(directory)

        self.assertEqual(repository.pet_vitals(), PetVitals())
        self.assertEqual(
            repository.learnt_word("serene").review_marker,
            ReviewRecoveryTag.FORGOT,
        )
        repository.save_learning_outcome(
            repository.learnt_word("serene"),
            PetVitals(82.5, 17.25, Mood.HAPPY),
        )
        persisted = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(
            persisted["wordsLearnt"]["serene"]["reviewMarker"],
            ReviewRecoveryTag.FORGOT.value,
        )
        self.assertNotIn("reviewMarkers", persisted["wordsLearnt"]["serene"])

    def test_learning_outcome_uses_one_replace_and_survives_restart(self):
        directory = Path(self.temp.name)
        repository = JsonWordsLearntRepository(directory)
        word = LearntWord(
            "serene",
            0.8,
            1000,
            1000,
            review_marker=ReviewRecoveryTag.VAGUE,
        )
        real_replace = __import__("os").replace
        with mock.patch(
            "infrastructure.words_learnt_repository.os.replace",
            wraps=real_replace,
        ) as replace:
            repository.save_learning_outcome(
                word,
                PetVitals(64.5, 12.75, Mood.EXCITED),
            )

        self.assertEqual(replace.call_count, 1)
        loaded = JsonWordsLearntRepository(directory)
        self.assertEqual(loaded.learnt_word("serene"), word)
        self.assertEqual(loaded.pet_vitals(), PetVitals(64.5, 12.75, Mood.EXCITED))

    def test_failed_learning_outcome_restores_in_memory_state(self):
        directory = Path(self.temp.name)
        repository = JsonWordsLearntRepository(directory)
        original = LearntWord("serene", 0.8, 1000, 1000)
        repository.save_learnt_word(original)

        with mock.patch(
            "infrastructure.words_learnt_repository.os.replace",
            side_effect=OSError("replace failed"),
        ):
            with self.assertRaises(OSError):
                repository.save_learning_outcome(
                    original.with_review_marker(ReviewRecoveryTag.FORGOT),
                    PetVitals(90.0, 10.0, Mood.HAPPY),
                )

        self.assertEqual(repository.learnt_word("serene"), original)
        self.assertEqual(repository.pet_vitals(), PetVitals())
        loaded = JsonWordsLearntRepository(directory)
        self.assertEqual(loaded.learnt_word("serene"), original)
        self.assertEqual(loaded.pet_vitals(), PetVitals())

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
