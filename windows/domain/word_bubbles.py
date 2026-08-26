from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable
import unicodedata

from .dictation import parse_meaning
from .models import VocabularyEntry, normalize_word_id


MAX_BUBBLE_DEPTH = 9
_TOKEN_PATTERN = re.compile(r"[A-Za-z]+(?:['\u2019][A-Za-z]+|['\u2019])?")


@dataclass(frozen=True)
class WordToken:
    text: str
    start: int
    end: int

    @property
    def word_id(self) -> str:
        return normalize_word_id(self.text)


def tokenize_english(text: str) -> tuple[WordToken, ...]:
    return tuple(WordToken(match.group(0), match.start(), match.end()) for match in _TOKEN_PATTERN.finditer(text))


@dataclass(frozen=True)
class BubbleDefinition:
    word_id: str
    word: str
    part_of_speech: str
    meaning: str
    examples: tuple[str, ...]
    known: bool = True


def resolve_bubble_definition(
    entries: Iterable[VocabularyEntry],
    token: str,
    context_example: str = "",
) -> BubbleDefinition:
    normalized = normalize_word_id(token)
    entry = next((item for item in entries if item.word_id == normalized), None)
    if entry is None:
        context = context_example.strip()
        return BubbleDefinition(
            word_id=normalized,
            word=token,
            part_of_speech="未收录",
            meaning="词库暂无中文释义",
            examples=(context,) if context else (),
            known=False,
        )
    part_of_speech, chinese_meaning = parse_meaning(entry.meaning)
    return BubbleDefinition(
        word_id=entry.word_id,
        word=entry.word,
        part_of_speech=part_of_speech or "未标注",
        meaning=chinese_meaning or entry.meaning,
        examples=tuple(example.english for example in entry.examples[:3]),
        known=True,
    )


@dataclass(frozen=True)
class BubbleFrame:
    definition: BubbleDefinition
    parent_depth: int


@dataclass(frozen=True)
class BubbleStack:
    frames: tuple[BubbleFrame, ...] = ()

    def open_root(self, definition: BubbleDefinition) -> "BubbleStack":
        return BubbleStack((BubbleFrame(definition, -1),))

    def open_child(self, parent_depth: int, definition: BubbleDefinition) -> "BubbleStack":
        if parent_depth < 0:
            prefix: tuple[BubbleFrame, ...] = ()
        elif parent_depth >= len(self.frames):
            return self
        else:
            prefix = self.frames[: parent_depth + 1]
        if len(prefix) >= MAX_BUBBLE_DEPTH:
            return self
        return BubbleStack(prefix + (BubbleFrame(definition, parent_depth),))

    def close_after(self, depth: int) -> "BubbleStack":
        if depth < 0:
            return BubbleStack()
        return BubbleStack(self.frames[: min(depth + 1, len(self.frames))])

    def close_all(self) -> "BubbleStack":
        return BubbleStack()


def normalize_token(token: str) -> str:
    return unicodedata.normalize("NFKC", token).strip().casefold()
