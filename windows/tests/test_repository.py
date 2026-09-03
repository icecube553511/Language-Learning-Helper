from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest


WINDOWS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WINDOWS_DIR))

from domain.dictation import DictationDraft, DictationDraftSyncMetadata, MarkMode
from domain.dictation_sync import make_sync_envelope
from domain.models import ExampleSentence, LearntWord, ReviewState, VocabularyEntry
from infrastructure.catalog import CatalogLoader
from infrastructure.draft_cipher import DraftCipherError
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

    def test_dictation_draft_survives_restart(self):
        directory = Path(self.temp.name)
        repo = JsonLearningRepository(directory)
        draft = DictationDraft(
            mode="random", scope_group="cet4", count=3,
            selected_ids=("apple",),
            group_anchors={"cet4": "apple"},
            group_endpoints={"cet4": "banana"},
            group_scroll_positions={"cet4": 0.4},
        )
        repo.save_dictation_draft(draft)
        loaded = JsonLearningRepository(directory)
        self.assertEqual(loaded.get_dictation_draft(), draft)
        loaded.clear_dictation_draft()
        self.assertIsNone(JsonLearningRepository(directory).get_dictation_draft())

    def test_dictation_sync_metadata_survives_restart_after_draft_clear(self):
        directory = Path(self.temp.name)
        metadata = DictationDraftSyncMetadata("user-1", "opaque-9", 9)
        repo = JsonLearningRepository(directory, draft_cipher=None)
        repo.save_dictation_sync_metadata(metadata)
        repo.clear_dictation_draft()
        loaded = JsonLearningRepository(directory, draft_cipher=None)
        self.assertEqual(loaded.get_dictation_draft(), None)
        self.assertEqual(loaded.get_dictation_sync_metadata(), metadata)

    def test_synced_snapshot_and_three_conflict_backups_are_encrypted_and_bounded(self):
        class XorCipher:
            def encrypt(self, value):
                return bytes(byte ^ 0x3C for byte in value)

            def decrypt(self, value):
                return bytes(byte ^ 0x3C for byte in value)

        directory = Path(self.temp.name)
        repository = JsonLearningRepository(directory, draft_cipher=XorCipher())
        synced = make_sync_envelope(
            "user-1",
            DictationDraft(custom_example="last-synced-secret"),
            revision="synced-7",
            updated_at_utc=7,
        )
        repository.save_last_synced_dictation_envelope(synced)
        for revision in range(5):
            repository.add_dictation_conflict_backup(make_sync_envelope(
                "user-1",
                DictationDraft(custom_example=f"conflict-secret-{revision}"),
                revision=str(revision),
                updated_at_utc=revision,
            ))
        repository.add_dictation_conflict_backup(make_sync_envelope(
            "user-1",
            DictationDraft(custom_example="conflict-secret-4"),
            revision="4",
            updated_at_utc=4,
        ))

        restarted = JsonLearningRepository(directory, draft_cipher=XorCipher())
        self.assertEqual(
            restarted.get_last_synced_dictation_envelope().canonical_json(),
            synced.canonical_json(),
        )
        self.assertEqual(
            [item.revision for item in restarted.get_dictation_conflict_backups()],
            ["4", "3", "2"],
        )
        raw = (directory / "learning-state.json").read_text(encoding="utf-8")
        self.assertNotIn("last-synced-secret", raw)
        self.assertNotIn("conflict-secret", raw)

    def test_dictation_draft_uses_injected_cipher_and_never_writes_plaintext(self):
        class XorCipher:
            def encrypt(self, value):
                return bytes(byte ^ 0xA5 for byte in value)

            def decrypt(self, value):
                return bytes(byte ^ 0xA5 for byte in value)

        directory = Path(self.temp.name)
        draft = DictationDraft(custom_example="unique-draft-marker-7f3a")
        repo = JsonLearningRepository(directory, draft_cipher=XorCipher())
        repo.save_dictation_draft(draft)
        raw = (directory / "learning-state.json").read_text(encoding="utf-8")
        self.assertNotIn("unique-draft-marker-7f3a", raw)
        payload = json.loads(raw)
        stored = payload["settings"]["dictationDraft"]
        self.assertEqual(stored["format"], "dpapi-v1")
        self.assertIsInstance(stored["ciphertext"], str)
        restored = JsonLearningRepository(directory, draft_cipher=XorCipher())
        self.assertEqual(restored.get_dictation_draft(), draft)

    def test_legacy_plaintext_draft_is_migrated_on_load(self):
        class XorCipher:
            def encrypt(self, value):
                return bytes(byte ^ 0x5A for byte in value)

            def decrypt(self, value):
                return bytes(byte ^ 0x5A for byte in value)

        directory = Path(self.temp.name)
        draft = DictationDraft(custom_example="legacy-marker-92c1")
        path = directory / "learning-state.json"
        path.write_text(
            json.dumps({
                "schemaVersion": 1,
                "settings": {"dictationDraft": draft.to_dict()},
            }),
            encoding="utf-8",
        )
        repository = JsonLearningRepository(directory, draft_cipher=XorCipher())
        self.assertEqual(repository.get_dictation_draft(), draft)
        migrated = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(migrated["settings"]["dictationDraft"]["format"], "dpapi-v1")
        self.assertNotIn("legacy-marker-92c1", path.read_text(encoding="utf-8"))

    def test_plaintext_migration_preserves_other_loaded_state(self):
        class XorCipher:
            def encrypt(self, value):
                return bytes(byte ^ 0x5A for byte in value)

            def decrypt(self, value):
                return bytes(byte ^ 0x5A for byte in value)

        directory = Path(self.temp.name)
        draft = DictationDraft(custom_example="legacy-with-tags")
        path = directory / "learning-state.json"
        path.write_text(
            json.dumps({
                "schemaVersion": 1,
                "tagOverrides": {"serene": ["evaluated"]},
                "settings": {"dictationDraft": draft.to_dict()},
            }),
            encoding="utf-8",
        )
        built_in = sample_entry("serene")
        repository = JsonLearningRepository(directory, [built_in], draft_cipher=XorCipher())
        self.assertEqual(repository.get_dictation_draft(), draft)
        self.assertEqual(repository.all_entries()[0].tags, ("evaluated",))

    def test_corrupt_ciphertext_is_ignored_without_crashing(self):
        class RejectingCipher:
            def encrypt(self, value):
                raise DraftCipherError("test")

            def decrypt(self, value):
                raise DraftCipherError("test")

        directory = Path(self.temp.name)
        path = directory / "learning-state.json"
        path.write_text(
            json.dumps({
                "schemaVersion": 1,
                "settings": {
                    "dictationDraft": {
                        "format": "dpapi-v1",
                        "ciphertext": "%%%not-base64%%",
                    },
                },
            }),
            encoding="utf-8",
        )
        repository = JsonLearningRepository(directory, draft_cipher=RejectingCipher())
        self.assertIsNone(repository.get_dictation_draft())

    def test_generic_cipher_failure_is_fail_closed(self):
        class ExplodingCipher:
            def encrypt(self, value):
                raise RuntimeError("provider details must not escape")

            def decrypt(self, value):
                raise RuntimeError("provider details must not escape")

        directory = Path(self.temp.name)
        path = directory / "learning-state.json"
        path.write_text(
            json.dumps({
                "schemaVersion": 1,
                "settings": {
                    "dictationDraft": {
                        "format": "dpapi-v1",
                        "ciphertext": "AA==",
                    },
                },
            }),
            encoding="utf-8",
        )
        repository = JsonLearningRepository(directory, draft_cipher=ExplodingCipher())
        self.assertIsNone(repository.get_dictation_draft())

    def test_failed_legacy_migration_cannot_rewrite_plaintext_on_later_save(self):
        class UnavailableCipher:
            def encrypt(self, value):
                raise RuntimeError("DPAPI unavailable")

            def decrypt(self, value):
                raise RuntimeError("DPAPI unavailable")

        directory = Path(self.temp.name)
        draft = DictationDraft(
            selected_ids=("secret-word-id",),
            custom_example="legacy-only-marker",
        )
        path = directory / "learning-state.json"
        path.write_text(
            json.dumps({
                "schemaVersion": 1,
                "settings": {"dictationDraft": draft.to_dict()},
            }),
            encoding="utf-8",
        )
        repository = JsonLearningRepository(directory, draft_cipher=UnavailableCipher())
        self.assertEqual(repository.get_dictation_draft(), draft)
        repository.set_font_scale(1.1)
        rewritten = path.read_text(encoding="utf-8")
        self.assertNotIn("legacy-only-marker", rewritten)
        self.assertNotIn("secret-word-id", rewritten)
        self.assertIsNone(json.loads(rewritten)["settings"]["dictationDraft"])


if __name__ == "__main__":
    unittest.main()
