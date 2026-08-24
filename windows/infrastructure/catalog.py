from __future__ import annotations

import json
from pathlib import Path

from domain.models import ExampleSentence, VocabularyEntry


def entry_from_payload(payload: dict, source: str = "catalog") -> VocabularyEntry | None:
    if not isinstance(payload, dict):
        return None
    raw_examples = payload.get("examples", [])
    examples: list[ExampleSentence] = []
    if isinstance(raw_examples, list):
        for item in raw_examples:
            if not isinstance(item, dict):
                continue
            english = str(item.get("en", item.get("english", ""))).strip()
            chinese = str(item.get("zh", item.get("chinese", ""))).strip()
            examples.append(ExampleSentence(english, chinese))

    raw_level = payload.get(
        "level",
        payload.get("memberships", payload.get("membership", "custom")),
    )
    if isinstance(raw_level, list):
        raw_level = "/".join(str(item) for item in raw_level)
    raw_tags = payload.get("tags", [])
    if isinstance(raw_tags, str):
        raw_tags = raw_tags.split("|")
    if not isinstance(raw_tags, list):
        raw_tags = []

    entry = VocabularyEntry.create(
        word=str(payload.get("word", "")),
        meaning=str(payload.get("meaning", payload.get("translation", ""))),
        examples=examples,
        phonetic=str(payload.get("phonetic", "")),
        level=str(raw_level or "custom"),
        tags=[str(tag) for tag in raw_tags],
        mnemonic=str(payload.get("mnemonic", "")),
        source=str(payload.get("source", source)),
    )
    return entry if entry.is_study_ready() else None


class CatalogLoader:
    def __init__(self, catalog_path: Path):
        self.catalog_path = catalog_path
        self.rejected_count = 0
        self.error = ""

    def load(self) -> list[VocabularyEntry]:
        self.rejected_count = 0
        self.error = ""
        if not self.catalog_path.is_file():
            return []
        try:
            payload = json.loads(self.catalog_path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            self.error = str(exc)
            return []
        raw_entries = payload.get("entries", payload.get("words", [])) if isinstance(payload, dict) else payload
        if not isinstance(raw_entries, list):
            self.error = "catalog root must be a list or contain entries/words"
            return []
        entries: list[VocabularyEntry] = []
        seen: set[str] = set()
        for item in raw_entries:
            entry = entry_from_payload(item)
            if entry is None or entry.word_id in seen:
                self.rejected_count += 1
                continue
            entries.append(entry)
            seen.add(entry.word_id)
        return entries
