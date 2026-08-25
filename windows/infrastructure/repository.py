from __future__ import annotations

from datetime import datetime
import json
import os
from pathlib import Path
import tempfile
import threading

from domain.models import DEFAULT_REVIEW_BATCH_SIZE, ReviewState, VocabularyEntry
from infrastructure.catalog import entry_from_payload


SCHEMA_VERSION = 1


class JsonLearningRepository:
    def __init__(self, data_dir: Path, catalog_entries: list[VocabularyEntry] | None = None):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.state_path = self.data_dir / "learning-state.json"
        self._lock = threading.RLock()
        self._catalog = {item.word_id: item for item in (catalog_entries or [])}
        self._user_entries: dict[str, VocabularyEntry] = {}
        self._reviews: dict[str, ReviewState] = {}
        self._activity: dict[str, list[str]] = {}
        self._settings: dict[str, object] = {
            "fontScale": 1.0,
            "reviewBatchSize": DEFAULT_REVIEW_BATCH_SIZE,
        }
        self._load()

    def _load(self) -> None:
        if not self.state_path.is_file():
            return
        try:
            payload = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return
        if not isinstance(payload, dict):
            return
        for raw in payload.get("userEntries", []):
            entry = entry_from_payload(raw, source="user")
            if entry is not None and entry.word_id not in self._catalog:
                self._user_entries[entry.word_id] = entry
        reviews = payload.get("reviews", {})
        if isinstance(reviews, dict):
            for word_id, raw in reviews.items():
                if isinstance(raw, dict):
                    self._reviews[str(word_id)] = ReviewState.from_dict(str(word_id), raw)
        activity = payload.get("activity", {})
        if isinstance(activity, dict):
            self._activity = {
                str(day): list(dict.fromkeys(str(word_id) for word_id in word_ids))
                for day, word_ids in activity.items()
                if isinstance(word_ids, list)
            }
        settings = payload.get("settings", {})
        if isinstance(settings, dict):
            self._settings.update(settings)

    def _payload(self) -> dict:
        return {
            "schemaVersion": SCHEMA_VERSION,
            "userEntries": [entry.to_dict() for entry in self._user_entries.values()],
            "reviews": {word_id: state.to_dict() for word_id, state in self._reviews.items()},
            "activity": self._activity,
            "settings": self._settings,
        }

    def _save_locked(self) -> None:
        text = json.dumps(self._payload(), ensure_ascii=False, indent=2)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix="learning-state-", suffix=".tmp", dir=self.data_dir
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_name, self.state_path)
        finally:
            if os.path.exists(temporary_name):
                os.unlink(temporary_name)

    def all_entries(self) -> list[VocabularyEntry]:
        with self._lock:
            merged = dict(self._catalog)
            merged.update(self._user_entries)
            return sorted(merged.values(), key=lambda item: item.word_id)

    def add_entries(self, entries: list[VocabularyEntry]) -> int:
        added = 0
        with self._lock:
            known = set(self._catalog) | set(self._user_entries)
            for entry in entries:
                if entry.word_id in known or not entry.is_study_ready():
                    continue
                self._user_entries[entry.word_id] = entry
                known.add(entry.word_id)
                added += 1
            if added:
                self._save_locked()
        return added

    def review_state(self, word_id: str) -> ReviewState:
        with self._lock:
            return self._reviews.get(word_id, ReviewState(word_id=word_id))

    def all_review_states(self) -> list[ReviewState]:
        with self._lock:
            return list(self._reviews.values())

    def save_review_state(self, state: ReviewState) -> None:
        with self._lock:
            self._reviews[state.word_id] = state
            self._save_locked()

    def record_activity(self, word_id: str, reviewed_at_utc: float) -> None:
        local_day = datetime.fromtimestamp(reviewed_at_utc).strftime("%Y-%m-%d")
        with self._lock:
            words = self._activity.setdefault(local_day, [])
            if word_id not in words:
                words.append(word_id)
            for old_day in sorted(self._activity)[:-120]:
                del self._activity[old_day]
            self._save_locked()

    def reviewed_count_for_local_day(self, local_day: str) -> int:
        with self._lock:
            return len(self._activity.get(local_day, []))

    def get_font_scale(self) -> float:
        with self._lock:
            try:
                return min(1.4, max(0.9, float(self._settings.get("fontScale", 1.0))))
            except (TypeError, ValueError):
                return 1.0

    def set_font_scale(self, scale: float) -> None:
        with self._lock:
            self._settings["fontScale"] = min(1.4, max(0.9, float(scale)))
            self._save_locked()

    def get_review_batch_size(self) -> int:
        with self._lock:
            try:
                return max(1, int(self._settings.get("reviewBatchSize", DEFAULT_REVIEW_BATCH_SIZE)))
            except (TypeError, ValueError):
                return DEFAULT_REVIEW_BATCH_SIZE

    def set_review_batch_size(self, size: int) -> None:
        with self._lock:
            self._settings["reviewBatchSize"] = max(1, int(size))
            self._save_locked()
