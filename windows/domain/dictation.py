from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import math
import re
import json
from typing import Iterable, Mapping

from .models import VocabularyEntry, normalize_word_id


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


# Drafts are intentionally versioned at the domain boundary.  The Windows
# repository stores the resulting JSON, while the Android adapter can consume
# the same shape without leaking platform state into this module.
DICTATION_DRAFT_VERSION = 1
MAX_DICTATION_DRAFT_BYTES = 1_048_576


def _normalized_word_id(value: object) -> str:
    """Return the portable word-id form without ever serializing ``None``."""
    if value is None:
        return ""
    return normalize_word_id(str(value))


def _normalized_group_key(value: object) -> str:
    """Normalize a group key while preserving unknown membership groups."""
    if value is None:
        return "all"
    # Group keys are identifiers rather than display labels.  NFKC/casefold
    # matches the shared vocabulary-groups contract; punctuation in aliases
    # such as ``CET-4`` is removed by the same rule as membership codes.
    normalized = normalize_word_id(str(value))
    return "".join(ch for ch in normalized if ch not in " -_.") or "all"


def _bounded_scroll(value: object) -> float:
    try:
        scroll = float(value)
    except (TypeError, ValueError):
        return 0.0
    # JSON has no portable representation for NaN/Infinity.  Treat malformed
    # values as the beginning of the list instead of emitting non-standard
    # JSON or allowing an invalid persisted position to leak to presentation.
    if not math.isfinite(scroll):
        return 0.0
    return max(0.0, min(1.0, scroll))


def _coerce_bool(value: object, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().casefold()
        if normalized in {"true", "1", "yes"}:
            return True
        if normalized in {"false", "0", "no", ""}:
            return False
    return bool(value) if value is not None else default


@dataclass(frozen=True)
class DictationDraftSyncMetadata:
    """Revision metadata persisted with a draft and sent in its envelope."""

    account_id: str = ""
    revision: str = "0"
    updated_at_utc: float = 0.0
    deleted: bool = False

    def __post_init__(self) -> None:
        account = "" if self.account_id is None else str(self.account_id).strip()
        revision = "0" if self.revision is None else str(self.revision).strip() or "0"
        try:
            updated = float(self.updated_at_utc)
        except (TypeError, ValueError):
            updated = 0.0
        if not math.isfinite(updated) or updated < 0:
            updated = 0.0
        object.__setattr__(self, "account_id", account)
        object.__setattr__(self, "revision", revision)
        object.__setattr__(self, "updated_at_utc", updated)
        object.__setattr__(self, "deleted", _coerce_bool(self.deleted))

    def to_dict(self) -> dict:
        return {
            "accountId": self.account_id,
            "revision": self.revision,
            "updatedAtUtc": self.updated_at_utc,
            "deleted": self.deleted,
        }

    def canonical_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, separators=(",", ":"), sort_keys=True, allow_nan=False)

    def byte_size(self) -> int:
        return len(self.canonical_json().encode("utf-8"))

    @classmethod
    def from_dict(cls, payload: Mapping | None) -> "DictationDraftSyncMetadata":
        if not isinstance(payload, Mapping):
            return cls()
        return cls(
            account_id=payload.get("accountId", payload.get("account_id", "")),
            revision=payload.get("revision", "0"),
            updated_at_utc=payload.get("updatedAtUtc", payload.get("updated_at_utc", 0.0)),
            deleted=payload.get("deleted", False),
        )


@dataclass(frozen=True)
class DictationGroupDraft:
    selected_ids: tuple[str, ...] = ()
    anchor_id: str | None = None
    endpoint_id: str | None = None
    scroll_position: float = 0.0
    expanded: bool = False

    def to_dict(self) -> dict:
        selected_ids = tuple(
            _normalized_word_id(item)
            for item in self.selected_ids
            if _normalized_word_id(item)
        )
        return {
            "selectedIds": sorted(set(selected_ids)),
            "anchorId": (_normalized_word_id(self.anchor_id) or None),
            "endpointId": (_normalized_word_id(self.endpoint_id) or None),
            "scrollPosition": _bounded_scroll(self.scroll_position),
            "expanded": bool(self.expanded),
        }

    @classmethod
    def from_dict(cls, payload: Mapping | None) -> "DictationGroupDraft":
        if not isinstance(payload, Mapping):
            return cls()
        raw_ids = payload.get("selectedIds", ())
        ids = (
            tuple(sorted({
                _normalized_word_id(item)
                for item in raw_ids
                if _normalized_word_id(item)
            }))
            if isinstance(raw_ids, (list, tuple, set))
            else ()
        )
        return cls(
            selected_ids=ids,
            anchor_id=(_normalized_word_id(payload.get("anchorId")) or None),
            endpoint_id=(_normalized_word_id(payload.get("endpointId")) or None),
            scroll_position=_bounded_scroll(payload.get("scrollPosition", 0.0)),
            expanded=bool(payload.get("expanded", False)),
        )


@dataclass(frozen=True)
class DictationDraft:
    """Complete persisted state for the 默写纸 editor.

    Collections use JSON-friendly primitive values so infrastructure can
    encrypt/sync the payload later without understanding presentation types.
    ``group_selected_ids`` and ``group_scroll_positions`` are keyed by the
    canonical group key; all IDs are normalized word IDs.
    """

    mode: str = "random"
    scope_group: str = "all"
    open_group: str | None = None
    count: int = 10
    include_evaluated: bool = False
    formats: tuple[str, ...] = (DictationFormat.DOCX.value, DictationFormat.PDF.value)
    font_size_pt: int = 12
    missing_fields: tuple[str, ...] = (DictationField.WORD.value,)
    show_initial: bool = False
    include_examples: bool = False
    include_example_chinese: bool = False
    custom_example: str = ""
    selected_ids: tuple[str, ...] = ()
    group_selected_ids: Mapping[str, tuple[str, ...]] | None = None
    group_anchors: Mapping[str, str | None] | None = None
    group_endpoints: Mapping[str, str | None] | None = None
    group_scroll_positions: Mapping[str, float] | None = None
    expanded_groups: tuple[str, ...] = ()
    range_enabled: bool = True
    groups: Mapping[str, DictationGroupDraft] | None = field(default=None, compare=False)
    sync_metadata: DictationDraftSyncMetadata = field(default_factory=DictationDraftSyncMetadata)

    @property
    def version(self) -> int:
        return DICTATION_DRAFT_VERSION

    def canonical_json(self) -> str:
        """Canonical UTF-8 JSON used for the optional sync size gate."""
        return json.dumps(
            self.to_dict(),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
            allow_nan=False,
        )

    # Explicit aliases make the size/canonicalization contract convenient for
    # adapters without requiring them to know the internal method names.
    def canonical_payload(self) -> dict:
        return self.to_dict()

    def canonical_json_bytes(self) -> bytes:
        return self.canonical_json().encode("utf-8")

    def byte_size(self) -> int:
        return len(self.canonical_json_bytes())

    def to_dict(self) -> dict:
        # Merge aliases after normalization instead of allowing a later map
        # entry (for example ``CET-4``) to erase an earlier one (``cet4``).
        groups: dict[str, DictationGroupDraft] = {}
        for raw_key, raw_value in (self.groups or {}).items():
            key = _normalized_group_key(raw_key)
            value = (
                raw_value if isinstance(raw_value, DictationGroupDraft)
                else DictationGroupDraft.from_dict(raw_value)
            )
            previous = groups.get(key)
            if previous is None:
                groups[key] = value
            else:
                groups[key] = DictationGroupDraft(
                    selected_ids=tuple(sorted(set(previous.selected_ids) | set(value.selected_ids))),
                    anchor_id=value.anchor_id or previous.anchor_id,
                    endpoint_id=value.endpoint_id or previous.endpoint_id,
                    scroll_position=max(
                        _bounded_scroll(previous.scroll_position),
                        _bounded_scroll(value.scroll_position),
                    ),
                    expanded=bool(previous.expanded or value.expanded),
                )
        # Older drafts represented group state in parallel flattened maps.
        # Merge those maps even when a partially migrated nested ``groups``
        # object is present; otherwise a crash during migration could silently
        # drop selections or markers.
        def _legacy_map(value):
            result: dict[str, object] = {}
            for raw_key, item in (value or {}).items():
                key = _normalized_group_key(raw_key)
                previous = result.get(key)
                if isinstance(previous, (list, tuple, set)) and isinstance(item, (list, tuple, set)):
                    result[key] = tuple(previous) + tuple(item)
                elif key not in result or item not in (None, ""):
                    result[key] = item
            return result

        selected_map = _legacy_map(self.group_selected_ids)
        anchors_map = _legacy_map(self.group_anchors)
        endpoints_map = _legacy_map(self.group_endpoints)
        scroll_map = _legacy_map(self.group_scroll_positions)
        expanded_keys = {_normalized_group_key(item) for item in self.expanded_groups}
        legacy_keys = (
            set(selected_map) | set(anchors_map) | set(endpoints_map)
            | set(scroll_map) | expanded_keys
        )
        for key in legacy_keys:
            legacy_group = DictationGroupDraft(
                selected_ids=tuple(selected_map.get(key, ()))
                if isinstance(selected_map.get(key, ()), (list, tuple, set)) else (),
                anchor_id=anchors_map.get(key),
                endpoint_id=endpoints_map.get(key),
                scroll_position=scroll_map.get(key, 0.0),
                expanded=key in expanded_keys,
            )
            previous = groups.get(key)
            if previous is None:
                groups[key] = legacy_group
            else:
                groups[key] = DictationGroupDraft(
                    selected_ids=tuple(previous.selected_ids) + tuple(legacy_group.selected_ids),
                    anchor_id=previous.anchor_id or legacy_group.anchor_id,
                    endpoint_id=previous.endpoint_id or legacy_group.endpoint_id,
                    scroll_position=max(
                        _bounded_scroll(previous.scroll_position),
                        _bounded_scroll(legacy_group.scroll_position),
                    ),
                    expanded=bool(previous.expanded or legacy_group.expanded),
                )
        return {
            "version": DICTATION_DRAFT_VERSION,
            "mode": "manual" if self.mode == "manual" else "random",
            "scopeGroup": _normalized_group_key(self.scope_group),
            "openGroup": (_normalized_group_key(self.open_group) if self.open_group is not None else None),
            "count": max(1, int(self.count)),
            "includeEvaluated": bool(self.include_evaluated),
            "formats": sorted({str(item).upper() for item in self.formats}),
            "fontSizePt": max(8, min(24, int(self.font_size_pt))),
            "missingFields": sorted({str(item) for item in self.missing_fields}) or [DictationField.WORD.value],
            "showInitial": bool(self.show_initial),
            "includeExamples": bool(self.include_examples),
            "includeExampleChinese": bool(self.include_example_chinese),
            "customExample": self.custom_example or "",
            "selectedIds": sorted({_normalized_word_id(item) for item in self.selected_ids if _normalized_word_id(item)}),
            "groups": {
                key: groups[key].to_dict()
                for key in sorted(groups)
            },
            "rangeEnabled": bool(self.range_enabled),
            "syncMetadata": (
                self.sync_metadata.to_dict()
                if isinstance(self.sync_metadata, DictationDraftSyncMetadata)
                else DictationDraftSyncMetadata.from_dict(self.sync_metadata).to_dict()
            ),
        }

    @classmethod
    def from_dict(cls, payload: Mapping | None) -> "DictationDraft | None":
        if not isinstance(payload, Mapping):
            return None
        try:
            version = int(payload.get("version", 0))
        except (TypeError, ValueError):
            return None
        if version != DICTATION_DRAFT_VERSION:
            return None
        def tuple_of(value, cast=str):
            return tuple(cast(item) for item in value) if isinstance(value, (list, tuple)) else ()
        try:
            raw_groups = payload.get("groups")
            groups: dict[str, DictationGroupDraft] = {}
            if isinstance(raw_groups, Mapping):
                for raw_key, raw_value in raw_groups.items():
                    key = _normalized_group_key(raw_key)
                    value = DictationGroupDraft.from_dict(raw_value)
                    previous = groups.get(key)
                    if previous is None:
                        groups[key] = value
                    else:
                        groups[key] = DictationGroupDraft(
                            selected_ids=tuple(sorted(set(previous.selected_ids) | set(value.selected_ids))),
                            anchor_id=value.anchor_id or previous.anchor_id,
                            endpoint_id=value.endpoint_id or previous.endpoint_id,
                            scroll_position=max(previous.scroll_position, value.scroll_position),
                            expanded=bool(previous.expanded or value.expanded),
                        )
            # Accept the pre-contract map keys so drafts written during an
            # early build remain recoverable.
            raw_legacy_selected = payload.get("groupSelectedIds")
            raw_legacy_anchors = payload.get("groupAnchors")
            raw_legacy_endpoints = payload.get("groupEndpoints")
            raw_legacy_scroll = payload.get("groupScrollPositions")
            legacy_selected = {}
            if isinstance(raw_legacy_selected, Mapping):
                for key, value in raw_legacy_selected.items():
                    if isinstance(value, (list, tuple, set)):
                        legacy_selected[_normalized_group_key(key)] = tuple(
                            _normalized_word_id(item)
                            for item in value
                            if _normalized_word_id(item)
                        )
            legacy_anchors = {
                _normalized_group_key(key): (_normalized_word_id(value) or None)
                for key, value in (raw_legacy_anchors.items() if isinstance(raw_legacy_anchors, Mapping) else ())
            }
            legacy_endpoints = {
                _normalized_group_key(key): (_normalized_word_id(value) or None)
                for key, value in (raw_legacy_endpoints.items() if isinstance(raw_legacy_endpoints, Mapping) else ())
            }
            legacy_scroll = {
                _normalized_group_key(key): _bounded_scroll(value)
                for key, value in (raw_legacy_scroll.items() if isinstance(raw_legacy_scroll, Mapping) else ())
            }
            expanded = tuple(_normalized_group_key(item) for item in tuple_of(payload.get("expandedGroups")))
            # Merge legacy maps even when a partially migrated nested object
            # is present. This makes upgrades lossless and deterministic.
            legacy_keys = set(legacy_selected) | set(legacy_anchors) | set(legacy_endpoints) | set(legacy_scroll) | set(expanded)
            for key in legacy_keys:
                legacy_group = DictationGroupDraft(
                    selected_ids=legacy_selected.get(key, ()),
                    anchor_id=legacy_anchors.get(key),
                    endpoint_id=legacy_endpoints.get(key),
                    scroll_position=legacy_scroll.get(key, 0.0),
                    expanded=key in expanded,
                )
                current = groups.get(key)
                if current is None:
                    groups[key] = legacy_group
                else:
                    groups[key] = DictationGroupDraft(
                        selected_ids=tuple(sorted(set(current.selected_ids) | set(legacy_group.selected_ids))),
                        anchor_id=current.anchor_id or legacy_group.anchor_id,
                        endpoint_id=current.endpoint_id or legacy_group.endpoint_id,
                        scroll_position=max(current.scroll_position, legacy_group.scroll_position),
                        expanded=bool(current.expanded or legacy_group.expanded),
                    )
            return cls(
                mode="manual" if payload.get("mode") == "manual" else "random",
                scope_group=_normalized_group_key(payload.get("scopeGroup")),
                open_group=(_normalized_group_key(payload["openGroup"]) if payload.get("openGroup") is not None else None),
                count=max(1, int(payload.get("count", 10))),
                include_evaluated=bool(payload.get("includeEvaluated", False)),
                formats=tuple_of(payload.get("formats"), lambda item: str(item).upper()) or (DictationFormat.DOCX.value, DictationFormat.PDF.value),
                font_size_pt=int(payload.get("fontSizePt", 12)),
                missing_fields=tuple_of(payload.get("missingFields")) or (DictationField.WORD.value,),
                show_initial=bool(payload.get("showInitial", False)),
                include_examples=bool(payload.get("includeExamples", False)),
                include_example_chinese=bool(payload.get("includeExampleChinese", False)),
                custom_example=str(payload.get("customExample") or ""),
                selected_ids=tuple(sorted({_normalized_word_id(item) for item in tuple_of(payload.get("selectedIds")) if _normalized_word_id(item)})),
                group_selected_ids={key: group.selected_ids for key, group in groups.items() if group.selected_ids} or None,
                group_anchors={key: group.anchor_id for key, group in groups.items()} or None,
                group_endpoints={key: group.endpoint_id for key, group in groups.items()} or None,
                group_scroll_positions={key: group.scroll_position for key, group in groups.items()} or None,
                expanded_groups=tuple(key for key, group in groups.items() if group.expanded),
                range_enabled=bool(payload.get("rangeEnabled", True)),
                groups=groups or None,
                sync_metadata=DictationDraftSyncMetadata.from_dict(payload.get("syncMetadata")),
            )
        except (TypeError, ValueError):
            return None


def dictation_ordered_ids(entries: Iterable[VocabularyEntry]) -> tuple[str, ...]:
    """Return the stable order used by range selection and random pools."""
    return tuple(sorted({
        _normalized_word_id(entry.word_id)
        for entry in entries
        if _normalized_word_id(entry.word_id)
    }))


def dictation_range_ids(
    entries: Iterable[VocabularyEntry],
    anchor_id: str | None,
    endpoint_id: str | None,
) -> frozenset[str]:
    """Return the inclusive range between two IDs in canonical list order.

    Missing IDs are treated as an invalid range and return an empty set.  This
    lets callers safely restore drafts after a catalog update without selecting
    an unrelated word.
    """
    if not anchor_id or not endpoint_id:
        return frozenset()
    ordered = dictation_ordered_ids(entries)
    anchor_key = _normalized_word_id(anchor_id)
    endpoint_key = _normalized_word_id(endpoint_id)
    normalized = {value: value for value in ordered}
    try:
        start = ordered.index(normalized[anchor_key])
        end = ordered.index(normalized[endpoint_key])
    except (KeyError, ValueError):
        return frozenset()
    low, high = sorted((start, end))
    return frozenset(ordered[low : high + 1])


def nearest_dictation_id(
    entries: Iterable[VocabularyEntry],
    reference_id: str | None,
    selected_ids: Iterable[str],
) -> str | None:
    """Find the selected ID nearest to ``reference_id`` in list order.

    Ties intentionally prefer the earlier item, making cancellation behavior
    deterministic on both platforms.
    """
    if not reference_id:
        return None
    ordered = dictation_ordered_ids(entries)
    selected = {
        _normalized_word_id(value)
        for value in selected_ids
        if _normalized_word_id(value)
    }
    candidates = [(index, value) for index, value in enumerate(ordered) if value in selected]
    normalized = {value: value for value in ordered}
    try:
        reference_index = ordered.index(normalized[_normalized_word_id(reference_id)])
    except (KeyError, ValueError):
        return None
    if not candidates:
        return None
    return min(candidates, key=lambda item: (abs(item[0] - reference_index), item[0]))[1]


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
