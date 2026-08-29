from __future__ import annotations

import json
from pathlib import Path
import random
import sys
import tempfile
import unittest


WINDOWS_DIR = Path(__file__).resolve().parents[1]
ROOT_DIR = WINDOWS_DIR.parent
sys.path.insert(0, str(WINDOWS_DIR))

from application.services import LearningService
from domain.dictation import DictationField, DictationOptions, MarkMode
from domain.models import (
    ExampleSentence,
    LearntWord,
    ReviewState,
    VocabularyEntry,
    initial_review_weight,
    updated_review_weight,
)
from infrastructure.repository import JsonLearningRepository
from infrastructure.words_learnt_repository import JsonWordsLearntRepository


def sample_entry(word: str) -> VocabularyEntry:
    return VocabularyEntry.create(word, f"{word} 的释义", [
        ExampleSentence(f"Use {word} in the first example.", "例句一。"),
        ExampleSentence(f"Use {word} in the second example.", "例句二。"),
        ExampleSentence(f"Use {word} in the third example.", "例句三。"),
    ])


class LearningServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        entry = sample_entry("focus")
        self.repo = JsonLearningRepository(Path(self.temp.name), [entry])
        self.learnt_repo = JsonWordsLearntRepository(Path(self.temp.name))
        self.service = LearningService(
            self.repo,
            words_learnt_repository=self.learnt_repo,
        )

    def test_study_rate_and_dashboard(self):
        card = self.service.next_card(now_utc=1000)
        self.assertEqual(card.word, "focus")
        state = self.service.rate_card(card.word_id, "good", reviewed_at_utc=1000)
        self.assertEqual(state.interval_days, 3)
        snapshot = self.service.dashboard(now_utc=1001)
        self.assertEqual(snapshot.total_words, 1)
        self.assertEqual(snapshot.new_words, 0)
        self.assertIsNone(self.service.next_card(now_utc=1001))

    def test_word_bubble_lookup_stays_in_application_service(self):
        definition = self.service.word_bubble("focus", "Use focus here.")
        self.assertTrue(definition.known)
        self.assertEqual(definition.word_id, "focus")
        self.assertEqual(self.service.word_bubble("missing", "Missing here.").meaning, "词库暂无中文释义")

    def test_font_scale_is_bounded(self):
        self.assertEqual(self.service.set_font_scale(2), 1.4)
        self.assertEqual(self.service.set_font_scale(0), 0.9)

    def test_study_order_defaults_to_random_and_supports_alphabetical(self):
        entries = [sample_entry("zeta"), sample_entry("alpha")]
        repository = JsonLearningRepository(Path(self.temp.name), entries)
        service = LearningService(repository, words_learnt_repository=JsonWordsLearntRepository(Path(self.temp.name)))

        self.assertEqual(service.study_order(), "random")
        self.assertEqual(service.next_card(rng=random.Random(0)).word_id, "zeta")
        service.set_study_order("alphabetical")
        self.assertEqual(service.next_card().word_id, "alpha")

    def test_study_review_and_reminder_level_filters_are_independent(self):
        cet4 = VocabularyEntry.create("four", "四级", sample_entry("four").examples, level="CET4")
        cet6 = VocabularyEntry.create("six", "六级", sample_entry("six").examples, level="CET6")
        repository = JsonLearningRepository(Path(self.temp.name), [cet4, cet6])
        learnt_repository = JsonWordsLearntRepository(Path(self.temp.name))
        learnt_repository.save_learnt_words([
            LearntWord(cet4.word_id, 1.0, 100, 100),
            LearntWord(cet6.word_id, 1.0, 100, 100),
        ])
        service = LearningService(repository, words_learnt_repository=learnt_repository)
        service.set_study_levels({"CET6"})
        service.set_review_levels({"CET4"})
        service.set_reminder_levels({"CET6"})

        self.assertEqual(service.study_levels(), {"CET6"})
        self.assertEqual(service.reminder_levels(), {"CET6"})
        self.assertEqual(service.reminder_card(rng=random.Random(0)).word_id, "six")
        with self.assertRaises(ValueError):
            service.set_reminder_levels({"OTHER"})
        self.assertEqual([entry.word_id for entry in service.start_review_session(count=20, rng=random.Random(0))], ["four"])
        service.set_review_levels({"CET4", "CET6"})
        self.assertEqual({entry.word_id for entry in service.start_review_session(count=20, rng=random.Random(0))}, {"four", "six"})

    def test_study_ratings_create_initial_weights(self):
        entries = [sample_entry(word) for word in ("again", "hard", "good", "easy")]
        repository = JsonLearningRepository(Path(self.temp.name), entries)
        learnt_repository = JsonWordsLearntRepository(Path(self.temp.name))
        service = LearningService(repository, words_learnt_repository=learnt_repository)

        expected = {"again": 1.0, "hard": 0.8, "good": 0.2, "easy": 0.05}
        for entry in entries:
            service.rate_card(entry.word_id, entry.word_id, reviewed_at_utc=1000)

        actual = {word.word_id: word.weight for word in learnt_repository.all_learnt_words()}
        self.assertEqual(actual, expected)

    def test_review_ratings_only_reduce_weight_for_good_or_easy(self):
        self.service.rate_card("focus", "again", reviewed_at_utc=1000)

        self.service.rate_review_card("focus", "hard", reviewed_at_utc=2000)
        self.assertEqual(self.learnt_repo.learnt_word("focus").weight, 1.0)
        self.service.rate_review_card("focus", "good", reviewed_at_utc=3000)
        self.assertEqual(self.learnt_repo.learnt_word("focus").weight, 0.2)
        self.service.rate_review_card("focus", "again", reviewed_at_utc=4000)
        self.assertEqual(self.learnt_repo.learnt_word("focus").weight, 0.2)
        self.service.rate_review_card("focus", "easy", reviewed_at_utc=5000)
        self.assertEqual(self.learnt_repo.learnt_word("focus").weight, 0.05)
        self.assertEqual(self.learnt_repo.learnt_word("focus").review_count, 4)

    def test_weights_match_shared_golden_contract(self):
        golden = json.loads(
            (ROOT_DIR / "shared" / "contracts" / "weighted-review-golden-v1.json")
            .read_text(encoding="utf-8")
        )
        for vector in golden["ratings"]:
            with self.subTest(rating=vector["rating"]):
                self.assertEqual(
                    initial_review_weight(vector["rating"]),
                    vector["initialWeight"],
                )
                self.assertEqual(
                    updated_review_weight(vector["previousWeight"], vector["rating"]),
                    vector["reviewWeight"],
                )

    def test_review_session_is_weighted_and_without_replacement(self):
        entries = [sample_entry(word) for word in ("high", "low-a", "low-b", "low-c")]
        repository = JsonLearningRepository(Path(self.temp.name), entries)
        learnt_repository = JsonWordsLearntRepository(Path(self.temp.name))
        learnt_repository.save_learnt_words([
            LearntWord(entry.word_id, 1.0 if entry.word_id == "high" else 0.05, 1000, 1000)
            for entry in entries
        ])
        service = LearningService(repository, words_learnt_repository=learnt_repository)

        session = service.start_review_session(count=4, rng=random.Random(7))
        self.assertEqual(len(session), 4)
        self.assertEqual(len({entry.word_id for entry in session}), 4)

        randomizer = random.Random(11)
        selections = [
            service.start_review_session(count=1, rng=randomizer)[0].word_id
            for _ in range(400)
        ]
        self.assertGreater(selections.count("high"), 250)

    def test_review_batch_size_is_bounded_by_learnt_count(self):
        self.service.rate_card("focus", "good", reviewed_at_utc=1000)
        self.assertEqual(self.service.set_review_batch_size(0), 1)
        self.assertEqual(self.service.set_review_batch_size(99), 1)
        self.assertEqual(self.service.review_batch_size(), 1)

    def test_reminder_settings_accept_fractional_minutes_and_validate_bounds(self):
        self.assertEqual(self.service.set_reminder_settings(True, 1.25), 1.25)
        self.assertTrue(self.service.reminder_enabled())
        self.assertEqual(self.service.reminder_interval_minutes(), 1.25)
        with self.assertRaises(ValueError):
            self.service.set_reminder_settings(True, 0.25)
        with self.assertRaises(ValueError):
            self.service.set_reminder_settings(True, 121)

    def test_reminder_card_prefers_due_words_and_avoids_previous(self):
        entries = [sample_entry(word) for word in ("due-a", "due-b", "later")]
        repository = JsonLearningRepository(Path(self.temp.name), entries)
        service = LearningService(repository)
        repository.save_review_state(ReviewState("due-a", due_at_utc=900, last_reviewed_at_utc=100))
        repository.save_review_state(ReviewState("due-b", due_at_utc=900, last_reviewed_at_utc=100))
        repository.save_review_state(ReviewState("later", due_at_utc=1100, last_reviewed_at_utc=100))

        card = service.reminder_card(exclude_id="due-a", rng=random.Random(3), now_utc=1000)

        self.assertEqual(card.word_id, "due-b")

    def test_due_review_count_and_due_only_session_use_schedule(self):
        entries = [sample_entry("due"), sample_entry("later")]
        repository = JsonLearningRepository(Path(self.temp.name), entries)
        learnt_repository = JsonWordsLearntRepository(Path(self.temp.name))
        learnt_repository.save_learnt_words([
            LearntWord(entry.word_id, 0.2, 100, 100)
            for entry in entries
        ])
        repository.save_review_state(ReviewState(
            "due", due_at_utc=900, last_reviewed_at_utc=100
        ))
        repository.save_review_state(ReviewState(
            "later", due_at_utc=1100, last_reviewed_at_utc=100
        ))
        service = LearningService(repository, words_learnt_repository=learnt_repository)

        self.assertEqual(service.due_review_count(now_utc=1000), 1)
        session = service.start_review_session(
            count=20,
            rng=random.Random(3),
            due_only=True,
            now_utc=1000,
        )
        self.assertEqual([entry.word_id for entry in session], ["due"])

    def test_legacy_review_state_is_migrated(self):
        directory = Path(self.temp.name) / "legacy"
        repository = JsonLearningRepository(directory, [sample_entry("legacy")])
        repository.save_review_state(ReviewState(
            "legacy",
            state="relearning",
            lapses=1,
            due_at_utc=1600,
            last_reviewed_at_utc=1000,
        ))
        learnt_repository = JsonWordsLearntRepository(directory)

        LearningService(repository, words_learnt_repository=learnt_repository)

        migrated = learnt_repository.learnt_word("legacy")
        self.assertIsNotNone(migrated)
        self.assertEqual(migrated.weight, 0.2)
        self.assertEqual(migrated.learnt_at_utc, 1000)
        self.assertTrue((directory / "Words_Learnt.json").is_file())

    def test_dictation_candidates_filter_evaluated_and_sample_without_replacement(self):
        entries = [sample_entry(word) for word in ("alpha", "beta", "gamma")]
        entries[-1] = VocabularyEntry.create("gamma", "gamma", entries[-1].examples, level="CET6", tags=("evaluated",))
        repository = JsonLearningRepository(Path(self.temp.name), entries)
        service = LearningService(repository)
        result = service.dictation_candidates(5, rng=random.Random(1))
        self.assertEqual({item.word_id for item in result}, {"alpha", "beta"})
        self.assertEqual(len({item.word_id for item in result}), len(result))
        self.assertEqual(service.dictation_candidates(5, include_evaluated=True, rng=random.Random(1))[-1].word_id, "gamma")

    def test_selected_dictation_and_tags_and_mark_mode(self):
        repository = JsonLearningRepository(Path(self.temp.name), [sample_entry("built")])
        service = LearningService(repository)
        self.assertEqual(service.available_program_tags(), {"cet4", "cet6", "gk", "zk", "evaluated"})
        self.assertEqual(service.update_program_tags({"built"}, {"evaluated"}, set()), 1)
        self.assertEqual(service.selected_dictation_candidates({"built"}), [])
        self.assertEqual(service.selected_dictation_candidates({"built"}, include_evaluated=True)[0].word_id, "built")
        with self.assertRaises(ValueError):
            service.update_program_tags({"built"}, {"custom"}, set())
        self.assertEqual(service.set_mark_mode(MarkMode.ALWAYS), MarkMode.ALWAYS)
        self.assertEqual(service.mark_mode(), MarkMode.ALWAYS)
        document = service.build_dictation_document(DictationOptions(missing_fields={DictationField.MEANING}), word_ids={"built"}, include_evaluated=True)
        self.assertEqual(len(document.rows), 1)

    def test_library_groups_ordering_and_counts(self):
        examples = sample_entry("focus").examples
        entries = [
            VocabularyEntry.create("adapt", "适应", examples, level="CET4", tags=("gk",)),
            VocabularyEntry.create("abandon", "放弃", examples, level="CET6", tags=("zk",)),
            VocabularyEntry.create("zephyr", "和风", examples, level="CET4|CET6"),
            VocabularyEntry.create("myword", "自定义词", examples, level="custom"),
        ]
        service = LearningService(JsonLearningRepository(Path(self.temp.name), entries))
        groups = service.library_groups()
        self.assertEqual([group.key for group in groups], ["all", "cet4", "cet6", "zk", "gk", "custom"])
        counts = {group.key: group.count for group in groups}
        self.assertEqual(counts, {"all": 4, "cet4": 2, "cet6": 2, "zk": 1, "gk": 1, "custom": 1})
        labels = {group.key: group.label for group in groups}
        self.assertEqual(labels["cet4"], "CET-4（四级）")
        self.assertEqual(labels["custom"], "自定义")

    def test_words_in_group_and_search_within_group(self):
        examples = sample_entry("focus").examples
        entries = [
            VocabularyEntry.create("adapt", "适应", examples, level="CET4", tags=("gk",)),
            VocabularyEntry.create("abandon", "放弃", examples, level="CET6", tags=("zk",)),
            VocabularyEntry.create("zephyr", "和风", examples, level="CET4|CET6"),
            VocabularyEntry.create("myword", "自定义词", examples, level="custom"),
        ]
        service = LearningService(JsonLearningRepository(Path(self.temp.name), entries))

        self.assertEqual(len(service.words_in_group("all")), 4)
        self.assertEqual({entry.word for entry in service.words_in_group("cet4")}, {"adapt", "zephyr"})
        self.assertEqual([entry.word for entry in service.words_in_group("gk")], ["adapt"])
        self.assertEqual([entry.word for entry in service.words_in_group("custom")], ["myword"])
        self.assertEqual([entry.word for entry in service.words_in_group("zk", "aband")], ["abandon"])
        self.assertEqual([entry.word for entry in service.words_in_group("all", "zeph")], ["zephyr"])
        self.assertEqual(service.words_in_group("missing"), [])


if __name__ == "__main__":
    unittest.main()
