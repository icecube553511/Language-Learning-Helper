from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import threading

from domain.models import LearntWord


SCHEMA_VERSION = 1


class JsonWordsLearntRepository:
    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.state_path = self.data_dir / "Words_Learnt.json"
        self._lock = threading.RLock()
        self._words: dict[str, LearntWord] = {}
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
        raw_words = payload.get("wordsLearnt", {})
        if isinstance(raw_words, list):
            raw_words = {
                str(item.get("wordId", "")): item
                for item in raw_words
                if isinstance(item, dict) and item.get("wordId")
            }
        if not isinstance(raw_words, dict):
            return
        for word_id, raw in raw_words.items():
            if not word_id or not isinstance(raw, dict):
                continue
            try:
                self._words[str(word_id)] = LearntWord.from_dict(str(word_id), raw)
            except (TypeError, ValueError):
                continue

    def _payload(self) -> dict:
        return {
            "schemaVersion": SCHEMA_VERSION,
            "wordsLearnt": {
                word_id: word.to_dict()
                for word_id, word in sorted(self._words.items())
            },
        }

    def _save_locked(self) -> None:
        text = json.dumps(self._payload(), ensure_ascii=False, indent=2)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix="Words_Learnt-", suffix=".tmp", dir=self.data_dir
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

    def all_learnt_words(self) -> list[LearntWord]:
        with self._lock:
            return [self._words[word_id] for word_id in sorted(self._words)]

    def learnt_word(self, word_id: str) -> LearntWord | None:
        with self._lock:
            return self._words.get(word_id)

    def save_learnt_word(self, word: LearntWord) -> None:
        with self._lock:
            self._words[word.word_id] = word
            self._save_locked()

    def save_learnt_words(self, words: list[LearntWord]) -> int:
        added = 0
        with self._lock:
            for word in words:
                if word.word_id in self._words:
                    continue
                self._words[word.word_id] = word
                added += 1
            if added:
                self._save_locked()
        return added
