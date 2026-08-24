from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta
import time

from domain.models import ImportReport, ReviewRating, ReviewState, VocabularyEntry
from domain.ports import LearningRepository
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
    def __init__(self, repository: LearningRepository, csv_importer=None):
        self.repository = repository
        self.csv_importer = csv_importer

    def dashboard(self, now_utc: float | None = None) -> DashboardSnapshot:
        now = time.time() if now_utc is None else now_utc
        entries = self.repository.all_entries()
        states = self.repository.all_review_states()
        state_by_id = {state.word_id: state for state in states}
        reviewed = [state for state in states if state.last_reviewed_at_utc is not None]
        due_now = sum(state.due_at_utc <= now for state in reviewed)
        local_day = datetime.fromtimestamp(now).strftime("%Y-%m-%d")
        return DashboardSnapshot(
            total_words=len(entries),
            due_now=due_now,
            new_words=sum(entry.word_id not in state_by_id for entry in entries),
            reviewed_today=self.repository.reviewed_count_for_local_day(local_day),
            due_next_7_days=sum(now < state.due_at_utc <= now + 7 * SECONDS_PER_DAY for state in reviewed),
            due_next_30_days=sum(now < state.due_at_utc <= now + 30 * SECONDS_PER_DAY for state in reviewed),
        )

    def next_card(self, now_utc: float | None = None, exclude_id: str = "") -> VocabularyEntry | None:
        now = time.time() if now_utc is None else now_utc
        entries = self.repository.all_entries()
        by_id = {entry.word_id: entry for entry in entries}
        due = sorted(
            (
                state for state in self.repository.all_review_states()
                if state.last_reviewed_at_utc is not None
                and state.due_at_utc <= now
                and state.word_id in by_id
                and state.word_id != exclude_id
            ),
            key=lambda item: item.due_at_utc,
        )
        if due:
            return by_id[due[0].word_id]
        reviewed_ids = {state.word_id for state in self.repository.all_review_states()}
        fresh = [entry for entry in entries if entry.word_id not in reviewed_ids and entry.word_id != exclude_id]
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
        return updated

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
        for state in self.repository.all_review_states():
            if state.last_reviewed_at_utc is None:
                continue
            due_date = datetime.fromtimestamp(state.due_at_utc).date()
            offset = (due_date - start).days
            if 0 <= offset < days:
                counts[due_date.isoformat()] += 1
        return [((start + timedelta(days=index)).isoformat(), counts[(start + timedelta(days=index)).isoformat()]) for index in range(days)]

    def retention_curve(self, days: int = 30, now_utc: float | None = None) -> list[float]:
        now = time.time() if now_utc is None else now_utc
        states = [state for state in self.repository.all_review_states() if state.last_reviewed_at_utc is not None]
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
