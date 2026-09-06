from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import math
import re
from typing import Mapping

from .models import VocabularyEntry


class DictationField(str, Enum):
    WORD = "word"
    PART_OF_SPEECH = "partOfSpeech"
    MEANING = "meaning"


class DictationFormat(str, Enum):
    DOCX = "DOCX"
    PDF = "PDF"


class MarkMode(str, Enum):
    ASK = "ASK"
    ALWAYS = "ALWAYS"
    NEVER = "NEVER"


@dataclass(frozen=True)
class DictationOptions:
    formats: frozenset[DictationFormat] = frozenset({DictationFormat.DOCX, DictationFormat.PDF})
    font_size_pt: int = 12
    missing_fields: frozenset[DictationField] = frozenset({DictationField.WORD})
    show_initial: bool = False
    include_examples: bool = False
    include_example_chinese: bool = False
    custom_examples: Mapping[str, str] | None = None
    paper_width_pt: int = 595
    paper_height_pt: int = 842

    def __post_init__(self) -> None:
        formats = frozenset(item if isinstance(item, DictationFormat) else DictationFormat(str(item).upper()) for item in self.formats)
        fields = frozenset(item if isinstance(item, DictationField) else DictationField(str(item)) for item in self.missing_fields)
        if not formats:
            raise ValueError("至少选择一种导出格式")
        if not fields:
            raise ValueError("至少选择一个缺失字段")
        if not 8 <= self.font_size_pt <= 24:
            raise ValueError("字号必须在 8 到 24 pt 之间")
        if (self.paper_width_pt, self.paper_height_pt) != (595, 842):
            raise ValueError("默写文档必须使用 A4 尺寸")
        object.__setattr__(self, "formats", formats)
        object.__setattr__(self, "missing_fields", fields)


@dataclass(frozen=True)
class DictationRow:
    word: str
    part_of_speech: str
    meaning: str
    examples: tuple[str, ...] = ()
    example_chinese: tuple[str, ...] = ()


@dataclass(frozen=True)
class DictationDocument:
    rows: tuple[DictationRow, ...]
    options: DictationOptions


_PARTS_OF_SPEECH = ("interj", "abbr", "prep", "pron", "conj", "adj", "adv", "aux", "num", "art", "vt", "vi", "n", "v", "a")
_POS_PATTERN = re.compile(r"(?i)(?<![A-Za-z0-9])(?:" + "|".join(_PARTS_OF_SPEECH) + r")\.?(?![A-Za-z0-9])")


def blank_count(text: str) -> int:
    return math.ceil(len(text.strip()) * 1.8)


def word_prompt(word: str, show_initial: bool = False) -> str:
    trimmed = word.strip()
    if not show_initial or not trimmed:
        return "_" * blank_count(trimmed)
    remaining = math.ceil(max(len(trimmed) - 1, 0) * 1.8)
    return trimmed[0] if remaining == 0 else f"{trimmed[0]} {'_' * remaining}"


def parse_meaning(meaning: str) -> tuple[str, str]:
    parts = tuple(dict.fromkeys(match.group(0).lower().removesuffix(".") for match in _POS_PATTERN.finditer(meaning)))
    chinese = re.sub(r"\s+", " ", _POS_PATTERN.sub(" ", meaning)).strip()
    return " / ".join(parts), chinese


def _word_boundary_pattern(target_word: str) -> re.Pattern[str]:
    return re.compile(r"(?i)(?<![A-Za-z0-9])" + re.escape(target_word.strip()) + r"(?![A-Za-z0-9])")


def cloze_example(sentence: str, target_word: str, show_initial: bool = False) -> str:
    target = target_word.strip()
    return sentence if not target else _word_boundary_pattern(target).sub("_" * blank_count(target), sentence)


def select_dictation_example(entry: VocabularyEntry, custom_example: str | None = None) -> str | None:
    if custom_example is not None and custom_example.strip():
        return custom_example.strip()
    non_empty = [item.english for item in entry.examples if item.english.strip()]
    pattern = _word_boundary_pattern(entry.word)
    return next((sentence for sentence in non_empty if pattern.search(sentence)), None) or (non_empty[0] if non_empty else None)


def select_dictation_example_chinese(entry: VocabularyEntry, custom_example: str | None = None) -> str | None:
    """Return the Chinese translation paired with the selected English example."""
    if custom_example is not None and custom_example.strip():
        # Custom examples have no paired translation unless provided in the entry.
        return None
    selected_english = select_dictation_example(entry, None)
    if selected_english is None:
        return None
    for item in entry.examples:
        if item.english.strip() == selected_english:
            return item.chinese.strip() or None
    return None


def row_from_entry(entry: VocabularyEntry, options: DictationOptions) -> DictationRow:
    part_of_speech, chinese_meaning = parse_meaning(entry.meaning)
    examples: tuple[str, ...] = ()
    example_chinese: tuple[str, ...] = ()
    if options.include_examples:
        source = select_dictation_example(entry, (options.custom_examples or {}).get(entry.word_id))
        if source is not None:
            examples = (cloze_example(source, entry.word, options.show_initial) if DictationField.WORD in options.missing_fields else source,)
            if options.include_example_chinese:
                chinese = select_dictation_example_chinese(entry, (options.custom_examples or {}).get(entry.word_id))
                example_chinese = (chinese,) if chinese else ()
    return DictationRow(
        word=word_prompt(entry.word, options.show_initial) if DictationField.WORD in options.missing_fields else entry.word.strip(),
        part_of_speech="_" * blank_count(part_of_speech) if DictationField.PART_OF_SPEECH in options.missing_fields else part_of_speech,
        meaning="_" * blank_count(chinese_meaning) if DictationField.MEANING in options.missing_fields else chinese_meaning,
        examples=examples,
        example_chinese=example_chinese,
    )


def build_document(entries: list[VocabularyEntry], options: DictationOptions) -> DictationDocument:
    unique = {entry.word_id: entry for entry in entries}
    return DictationDocument(tuple(row_from_entry(entry, options) for entry in unique.values()), options)
