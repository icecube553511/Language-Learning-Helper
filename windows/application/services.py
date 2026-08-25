from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta
import random
import time

from domain.models import LearntWord, ImportReport, ReviewRating, ReviewState, VocabularyEntry
from domain.ports import LearningRepository, WordsLearntRepository
from domain.scheduler import SECONDS_PER_DAY, retention_at, schedule_review


@dataclass(frozen=True)
class DashboardSnapshot:
    total_words: int
    due_now: int
    new_words: int
    reviewed_today: int
    due_next_7_days: int
    due_next_30_days: int


class LearningService:
    def __init__(
        self,
        repository: LearningRepository,
        csv_importer=None,
        words_learnt_repository: WordsLearntRepository | None = None,
    ):
        self.repository = repository
        self.csv_importer = csv_importer
        self.words_learnt_repository = words_learnt_repository
        self._migrate_legacy_review_states()

    def _migrate_legacy_review_states(self) -> int:
        if self.words_learnt_repository is None:
            return 0
        known = {
            word.word_id
            for word in self.words_learnt_repository.all_learnt_words()
        }
        migrated = []
        for state in self.repository.all_review_states():
            if state.word_id in known or state.last_reviewed_at_utc is None:
                continue
            migrated.append(LearntWord(
                word_id=state.word_id,
                weight=0.2,
                learnt_at_utc=state.last_reviewed_at_utc,
                last_reviewed_at_utc=state.last_reviewed_at_utc,
            ))
        return self.words_learnt_repository.save_learnt_words(migrated)

    def _learnt_by_id(self) -> dict[str, LearntWord]:
        if self.words_learnt_repository is None:
            return {
                state.word_id: LearntWord(
                    word_id=state.word_id,
                    weight=0.2,
                    learnt_at_utc=state.last_reviewed_at_utc or 0.0,
                    last_reviewed_at_utc=state.last_reviewed_at_utc or 0.0,
                )
                for state in self.repository.all_review_states()
                if state.last_reviewed_at_utc is not None
            }
        return {
            word.word_id: word
            for word in self.words_learnt_repository.all_learnt_words()
        }

    def dashboard(self, now_utc: float | None = None) -> DashboardSnapshot:
        now = time.time() if now_utc is None else now_utc
        entries = self.repository.all_entries()
        states = self.repository.all_review_states()
        learnt_ids = set(self._learnt_by_id())
        entry_ids = {entry.word_id for entry in entries}
        reviewed = [
            state for state in states
            if state.word_id in learnt_ids
            and state.word_id in entry_ids
            and state.last_reviewed_at_utc is not None
        ]
        due_now = sum(state.due_at_utc <= now for state in reviewed)
        local_day = datetime.fromtimestamp(now).strftime("%Y-%m-%d")
        return DashboardSnapshot(
            total_words=len(entries),
            due_now=due_now,
            new_words=sum(entry.word_id not in learnt_ids for entry in entries),
            reviewed_today=self.repository.reviewed_count_for_local_day(local_day),
            due_next_7_days=sum(now < state.due_at_utc <= now + 7 * SECONDS_PER_DAY for state in reviewed),
            due_next_30_days=sum(now < state.due_at_utc <= now + 30 * SECONDS_PER_DAY for state in reviewed),
        )

    def next_card(self, now_utc: float | None = None, exclude_id: str = "") -> VocabularyEntry | None:
        entries = self.repository.all_entries()
        learnt_ids = set(self._learnt_by_id())
        fresh = [
            entry for entry in entries
            if entry.word_id not in learnt_ids and entry.word_id != exclude_id
        ]
        if fresh:
            return fresh[0]
        return None

    def rate_card(
        self,
        word_id: str,
        rating: ReviewRating | str,
        reviewed_at_utc: float | None = None,
    ) -> ReviewState:
        at_utc = time.time() if reviewed_at_utc is None else reviewed_at_utc
        updated = schedule_review(self.repository.review_state(word_id), rating, at_utc)
        self.repository.save_review_state(updated)
        self.repository.record_activity(word_id, at_utc)
        if (
            self.words_learnt_repository is not None
            and self.words_learnt_repository.learnt_word(word_id) is None
        ):
            self.words_learnt_repository.save_learnt_word(
                LearntWord.create(word_id, rating, at_utc)
            )
        return updated

    def start_review_session(
        self,
        count: int | None = None,
        rng: random.Random | None = None,
        *,
        due_only: bool = False,
        now_utc: float | None = None,
    ) -> list[VocabularyEntry]:
        entries = {entry.word_id: entry for entry in self.repository.all_entries()}
        learnt = [
            word for word in self._learnt_by_id().values()
            if word.word_id in entries
        ]
        if due_only:
            now = time.time() if now_utc is None else now_utc
            states = {state.word_id: state for state in self.repository.all_review_states()}
            learnt = [
                word for word in learnt
                if word.word_id in states and states[word.word_id].due_at_utc <= now
            ]
        if not learnt:
            return []

        requested = self.review_batch_size() if count is None else int(count)
        size = min(len(learnt), max(1, requested))
        randomizer = rng or random.SystemRandom()
        pool = sorted(learnt, key=lambda word: word.word_id)
        selected: list[VocabularyEntry] = []
        for _ in range(size):
            total_weight = sum(word.weight for word in pool)
            threshold = randomizer.random() * total_weight
            cumulative = 0.0
            selected_index = len(pool) - 1
            for index, word in enumerate(pool):
                cumulative += word.weight
                if threshold < cumulative:
                    selected_index = index
                    break
            word = pool.pop(selected_index)
            selected.append(entries[word.word_id])
        return selected

    def rate_review_card(
        self,
        word_id: str,
        rating: ReviewRating | str,
        reviewed_at_utc: float | None = None,
    ) -> ReviewState:
        if self.words_learnt_repository is None:
            raise RuntimeError("Words_Learnt repository is not configured")
        learnt = self.words_learnt_repository.learnt_word(word_id)
        if learnt is None:
            raise ValueError("Only learnt words can be reviewed")
        at_utc = time.time() if reviewed_at_utc is None else reviewed_at_utc
        updated = schedule_review(self.repository.review_state(word_id), rating, at_utc)
        self.repository.save_review_state(updated)
        self.repository.record_activity(word_id, at_utc)
        self.words_learnt_repository.save_learnt_word(learnt.reviewed(rating, at_utc))
        return updated

    def learnt_word_count(self) -> int:
        entry_ids = {entry.word_id for entry in self.repository.all_entries()}
        return sum(word_id in entry_ids for word_id in self._learnt_by_id())

    def review_batch_size(self) -> int:
        stored = self.repository.get_review_batch_size()
        total = self.learnt_word_count()
        return min(stored, total) if total else 1

    def set_review_batch_size(self, size: int) -> int:
        total = self.learnt_word_count()
        bounded = min(max(1, int(size)), max(1, total))
        self.repository.set_review_batch_size(bounded)
        return bounded

    def due_review_count(self, now_utc: float | None = None) -> int:
        now = time.time() if now_utc is None else now_utc
        learnt_ids = set(self._learnt_by_id())
        entry_ids = {entry.word_id for entry in self.repository.all_entries()}
        return sum(
            state.word_id in learnt_ids
            and state.word_id in entry_ids
            and state.last_reviewed_at_utc is not None
            and state.due_at_utc <= now
            for state in self.repository.all_review_states()
        )

    def search(self, query: str) -> list[VocabularyEntry]:
        key = query.strip().casefold()
        entries = self.repository.all_entries()
        if not key:
            return entries
        return [
            entry for entry in entries
            if key in entry.word.casefold()
            or key in entry.meaning.casefold()
            or any(key in tag.casefold() for tag in entry.tags)
        ]

    def import_csv(self, path) -> ImportReport:
        if self.csv_importer is None:
            raise RuntimeError("CSV importer is not configured")
        entries, report = self.csv_importer.parse(path, {item.word_id for item in self.repository.all_entries()})
        imported = self.repository.add_entries(entries)
        report.succeeded = imported
        if imported < len(entries):
            report.skipped += len(entries) - imported
        return report

    def forecast(self, days: int, now_utc: float | None = None) -> list[tuple[str, int]]:
        if days not in (7, 30):
            raise ValueError("Forecast supports 7 or 30 days")
        now = time.time() if now_utc is None else now_utc
        start = datetime.fromtimestamp(now).date()
        counts: Counter[str] = Counter()
        entry_ids = {entry.word_id for entry in self.repository.all_entries()}
        learnt_ids = set(self._learnt_by_id())
        for state in self.repository.all_review_states():
            if (
                state.last_reviewed_at_utc is None
                or state.word_id not in entry_ids
                or state.word_id not in learnt_ids
            ):
                continue
            due_date = datetime.fromtimestamp(state.due_at_utc).date()
            offset = (due_date - start).days
            if 0 <= offset < days:
                counts[due_date.isoformat()] += 1
        return [((start + timedelta(days=index)).isoformat(), counts[(start + timedelta(days=index)).isoformat()]) for index in range(days)]

    def retention_curve(self, days: int = 30, now_utc: float | None = None) -> list[float]:
        now = time.time() if now_utc is None else now_utc
        entry_ids = {entry.word_id for entry in self.repository.all_entries()}
        learnt_ids = set(self._learnt_by_id())
        states = [
            state for state in self.repository.all_review_states()
            if state.last_reviewed_at_utc is not None
            and state.word_id in entry_ids
            and state.word_id in learnt_ids
        ]
        if not states:
            return [0.0 for _ in range(days + 1)]
        return [
            sum(retention_at(state, now + day * SECONDS_PER_DAY) for state in states) / len(states)
            for day in range(days + 1)
        ]

    def font_scale(self) -> float:
        return self.repository.get_font_scale()

    def set_font_scale(self, scale: float) -> float:
        bounded = min(1.4, max(0.9, float(scale)))
        self.repository.set_font_scale(bounded)
        return bounded
