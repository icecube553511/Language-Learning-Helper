"""Vocabulary-group classification (pure, platform-independent).

This mirrors ``shared/contracts/vocabulary-groups-v1.md`` and
``shared/contracts/vocabulary-groups-golden-v1.json``. It must stay free of any
UI, filesystem or platform dependency so Windows and Android classify words the
same way.
"""

from __future__ import annotations

import unicodedata


GROUP_ORDER = ("all", "cet4", "cet6", "zk", "gk", "custom")

GROUP_LABELS = {
    "all": "全部",
    "cet4": "CET-4（四级）",
    "cet6": "CET-6（六级）",
    "zk": "中考（zk）",
    "gk": "高考（gk）",
    "custom": "自定义",
}

_GROUP_RULES = (
    ("cet4", {"CET4"}, {"cet4"}),
    ("cet6", {"CET6"}, {"cet6"}),
    ("zk", {"ZK"}, {"zk"}),
    ("gk", {"GK"}, {"gk"}),
)

_CANONICAL_MEMBERSHIPS = {"CET4", "CET6", "ZK", "GK", "CUSTOM"}


def normalize_group_membership(code: str) -> str:
    normalized = unicodedata.normalize("NFKC", code.strip()).upper()
    return "".join(ch for ch in normalized if ch not in " -_.")


def normalize_group_tag(tag: str) -> str:
    return unicodedata.normalize("NFKC", tag.strip()).casefold()


def classify_groups(memberships, tags) -> frozenset[str]:
    """Return the canonical group keys a word belongs to."""
    levels = {normalize_group_membership(value) for value in memberships}
    normalized_tags = {normalize_group_tag(value) for value in tags}
    result = {"all"}
    for key, level_codes, tag_codes in _GROUP_RULES:
        if (levels & level_codes) or (normalized_tags & tag_codes):
            result.add(key)
    if "CUSTOM" in levels:
        result.add("custom")
    return frozenset(result)


def group_label(key: str) -> str:
    return GROUP_LABELS.get(key, key)


def canonical_memberships() -> frozenset[str]:
    return frozenset(_CANONICAL_MEMBERSHIPS)
