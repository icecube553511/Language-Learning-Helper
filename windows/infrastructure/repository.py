from __future__ import annotations

from datetime import datetime
import json
import os
from pathlib import Path
import tempfile
import threading

from domain.models import (
    DEFAULT_STUDY_ORDER,
    DEFAULT_REMINDER_INTERVAL_MINUTES,
    DEFAULT_REVIEW_BATCH_SIZE,
    MAX_REMINDER_INTERVAL_MINUTES,
    MIN_REMINDER_INTERVAL_MINUTES,
    ReviewState,
    VocabularyEntry,
)
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
            "studyOrder": DEFAULT_STUDY_ORDER,
            "studyLevels": [],
            "reviewLevels": [],
            "reminderLevels": [],
            "reminderEnabled": False,
            "reminderIntervalMinutes": DEFAULT_REMINDER_INTERVAL_MINUTES,
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

    def get_study_order(self) -> str:
        with self._lock:
            value = str(self._settings.get("studyOrder", DEFAULT_STUDY_ORDER))
            return value if value in {"alphabetical", "random"} else DEFAULT_STUDY_ORDER

    def set_study_order(self, order: str) -> None:
        if order not in {"alphabetical", "random"}:
            raise ValueError("学习顺序必须为 alphabetical 或 random")
        with self._lock:
            self._settings["studyOrder"] = order
            self._save_locked()

    def _get_levels(self, key: str) -> set[str]:
        with self._lock:
            raw = self._settings.get(key, [])
            if isinstance(raw, str):
                raw = raw.replace(",", "|").split("|")
            if not isinstance(raw, list):
                return set()
            return {str(item).strip().upper() for item in raw if str(item).strip()}

    def _set_levels(self, key: str, levels: set[str]) -> None:
        with self._lock:
            self._settings[key] = sorted({str(item).strip().upper() for item in levels if str(item).strip()})
            self._save_locked()

    def get_study_levels(self) -> set[str]:
        return self._get_levels("studyLevels")

    def set_study_levels(self, levels: set[str]) -> None:
        self._set_levels("studyLevels", levels)

    def get_review_levels(self) -> set[str]:
        return self._get_levels("reviewLevels")

    def set_review_levels(self, levels: set[str]) -> None:
        self._set_levels("reviewLevels", levels)

    def get_reminder_levels(self) -> set[str]:
        return self._get_levels("reminderLevels")

    def set_reminder_levels(self, levels: set[str]) -> None:
        self._set_levels("reminderLevels", levels)

    def update_entry_labels(self, word_ids: set[str], level: str, tags: set[str]) -> int:
        normalized_ids = {str(item) for item in word_ids}
        normalized_level = level.strip() or "custom"
        normalized_tags = tuple(sorted({tag.strip() for tag in tags if tag.strip()}))
        updated = 0
        with self._lock:
            for word_id in normalized_ids:
                entry = self._user_entries.get(word_id)
                if entry is None:
                    continue
                self._user_entries[word_id] = VocabularyEntry(
                    word_id=entry.word_id,
                    word=entry.word,
                    meaning=entry.meaning,
                    examples=entry.examples,
                    phonetic=entry.phonetic,
                    level=normalized_level,
                    tags=normalized_tags,
                    mnemonic=entry.mnemonic,
                    source=entry.source,
                )
                updated += 1
            if updated:
                self._save_locked()
        return updated

    def get_reminder_enabled(self) -> bool:
        with self._lock:
            return self._settings.get("reminderEnabled", False) is True

    def set_reminder_enabled(self, enabled: bool) -> None:
        with self._lock:
            self._settings["reminderEnabled"] = bool(enabled)
            self._save_locked()

    def get_reminder_interval_minutes(self) -> float:
        with self._lock:
            try:
                return min(
                    MAX_REMINDER_INTERVAL_MINUTES,
                    max(
                        MIN_REMINDER_INTERVAL_MINUTES,
                        float(self._settings.get(
                            "reminderIntervalMinutes",
                            DEFAULT_REMINDER_INTERVAL_MINUTES,
                        )),
                    ),
                )
            except (TypeError, ValueError):
                return DEFAULT_REMINDER_INTERVAL_MINUTES

    def set_reminder_interval_minutes(self, minutes: float) -> None:
        with self._lock:
            self._settings["reminderIntervalMinutes"] = min(
                MAX_REMINDER_INTERVAL_MINUTES,
                max(MIN_REMINDER_INTERVAL_MINUTES, float(minutes)),
            )
            self._save_locked()
