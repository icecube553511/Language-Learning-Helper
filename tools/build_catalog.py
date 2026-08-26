from __future__ import annotations

import argparse
import csv
import json
import re
import unicodedata
from collections import Counter
from datetime import date
from pathlib import Path

from opencc import OpenCC


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ECDICT = PROJECT_ROOT / ".cache" / "ecdict.csv"
DEFAULT_REFERENCE = PROJECT_ROOT.parent / "单词记忆1" / "data" / "cet4_words.json"
OUTPUT_DIR = PROJECT_ROOT / "shared" / "content"
OUTPUT_CATALOG = OUTPUT_DIR / "catalog.json"
OUTPUT_MANIFEST = OUTPUT_DIR / "catalog-manifest.json"
CONTENT_VERSION = "cet-2026.08-v2"
TO_SIMPLIFIED = OpenCC("t2s")


def clean_text(value: object) -> str:
    text = str(value or "")
    for marker in ("\\r\\n", "\\n", "\\r"):
        text = text.replace(marker, " ")
    return re.sub(r"\s+", " ", text).strip()


def canonical_id(word: str) -> str:
    return unicodedata.normalize("NFKC", clean_text(word)).casefold()


def fallback_examples(word: str) -> list[dict[str, str]]:
    return [
        {
            "en": f'The word "{word}" appeared in today\'s reading.',
            "zh": f'“{word}”这个词出现在今天的阅读中。',
            "source": "LexiTrack curriculum fallback",
        },
        {
            "en": f'Our teacher asked us to explain "{word}" in context.',
            "zh": f'老师让我们结合语境解释“{word}”。',
            "source": "LexiTrack curriculum fallback",
        },
        {
            "en": f'I wrote a sentence with "{word}" to remember its meaning.',
            "zh": f'我用“{word}”写了一个句子来记住它的含义。',
            "source": "LexiTrack curriculum fallback",
        },
    ]


def complete_examples(word: str, raw_examples: object) -> tuple[list[dict[str, str]], int]:
    result: list[dict[str, str]] = []
    seen: set[str] = set()
    if isinstance(raw_examples, list):
        for raw in raw_examples:
            if not isinstance(raw, dict):
                continue
            english = clean_text(raw.get("en"))
            chinese = TO_SIMPLIFIED.convert(clean_text(raw.get("zh"))).replace("\u200b", "")
            key = english.casefold()
            if not english or not chinese or key in seen:
                continue
            result.append(
                {
                    "en": english,
                    "zh": chinese,
                    "source": clean_text(raw.get("source")) or "Reference corpus",
                }
            )
            seen.add(key)
            if len(result) == 3:
                break

    fallback_count = 0
    for example in fallback_examples(word):
        if len(result) == 3:
            break
        key = example["en"].casefold()
        if key not in seen:
            result.append(example)
            seen.add(key)
            fallback_count += 1
    return result, fallback_count


def load_reference(path: Path) -> dict[str, dict]:
    items = json.loads(path.read_text(encoding="utf-8"))
    return {canonical_id(item.get("word", "")): item for item in items if canonical_id(item.get("word", ""))}


def build_catalog(ecdict_path: Path, reference_path: Path) -> tuple[list[dict], dict]:
    reference = load_reference(reference_path)
    rows: dict[str, dict] = {}
    membership_counts: Counter[str] = Counter()

    with ecdict_path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            tags = set(clean_text(row.get("tag")).lower().split())
            memberships: list[str] = []
            if tags.intersection({"zk", "gk", "cet4"}):
                memberships.append("CET4")
            if "cet6" in tags:
                memberships.append("CET6")
            if not memberships:
                continue

            word = clean_text(row.get("word"))
            meaning = clean_text(row.get("translation"))
            entry_id = canonical_id(word)
            if not entry_id or not meaning:
                continue

            existing = rows.get(entry_id)
            if existing:
                existing["memberships"] = sorted(set(existing["memberships"] + memberships))
                continue

            reference_item = reference.get(entry_id, {})
            examples, fallback_count = complete_examples(word, reference_item.get("examples", []))
            phonetic = clean_text(row.get("phonetic"))
            rows[entry_id] = {
                "id": entry_id,
                "word": word,
                "phonetic": f"/{phonetic.strip('/')}" + "/" if phonetic else clean_text(reference_item.get("phonetic")),
                "meaning": meaning,
                "memberships": sorted(set(memberships)),
                "tags": sorted(tags.intersection({"zk", "gk", "cet4", "cet6"})),
                "mnemonic": clean_text(reference_item.get("mnemonic")),
                "examples": examples,
                "provenance": {
                    "translation": "ECDICT",
                    "examples": sorted({example["source"] for example in examples}),
                    "fallbackExamples": fallback_count,
                },
                "contentVersion": CONTENT_VERSION,
            }

    catalog = sorted(rows.values(), key=lambda item: item["id"])
    for item in catalog:
        for membership in item["memberships"]:
            membership_counts[membership] += 1

    source_counts: Counter[str] = Counter()
    fallback_words = 0
    fallback_examples_total = 0
    for item in catalog:
        fallback = int(item["provenance"]["fallbackExamples"])
        fallback_examples_total += fallback
        fallback_words += int(fallback > 0)
        for source in item["provenance"]["examples"]:
            source_counts[source] += 1

    manifest = {
        "name": "LexiTrack CET-4/CET-6 catalog",
        "contentVersion": CONTENT_VERSION,
        "generatedOn": date.today().isoformat(),
        "wordCount": len(catalog),
        "membershipCounts": dict(sorted(membership_counts.items())),
        "fallbackWordCount": fallback_words,
        "fallbackExampleCount": fallback_examples_total,
        "exampleSourceWordCounts": dict(sorted(source_counts.items())),
        "sources": [
            {
                "name": "ECDICT",
                "url": "https://github.com/skywind3000/ECDICT",
                "license": "MIT",
                "usage": "words, phonetics, Chinese translations and exam tags",
            },
            {
                "name": "单词记忆1 reference catalog",
                "usage": "existing bilingual corpus examples retained only when both languages are non-empty",
            },
        ],
        "qualityRule": "Every entry has a Chinese meaning and at least three unique English examples with Simplified Chinese translations.",
    }
    return catalog, manifest


def validate_catalog(catalog: list[dict]) -> None:
    if not catalog:
        raise ValueError("Catalog is empty")
    ids: set[str] = set()
    for index, item in enumerate(catalog):
        entry_id = item.get("id", "")
        if not entry_id or entry_id in ids:
            raise ValueError(f"Duplicate or empty id at item {index}: {entry_id!r}")
        ids.add(entry_id)
        meaning = clean_text(item.get("meaning"))
        if not meaning or not re.search(r"[\u3400-\u9fff]", meaning):
            raise ValueError(f"Missing Chinese meaning: {entry_id}")
        memberships = set(item.get("memberships", []))
        if not memberships or not memberships.issubset({"CET4", "CET6"}):
            raise ValueError(f"Invalid memberships: {entry_id}")
        examples = item.get("examples", [])
        if len(examples) < 3:
            raise ValueError(f"Fewer than three examples: {entry_id}")
        english_seen: set[str] = set()
        for example in examples[:3]:
            english = clean_text(example.get("en"))
            chinese = clean_text(example.get("zh"))
            if not english or not chinese or not re.search(r"[\u3400-\u9fff]", chinese):
                raise ValueError(f"Incomplete example: {entry_id}")
            if english.casefold() in english_seen:
                raise ValueError(f"Duplicate example: {entry_id}")
            english_seen.add(english.casefold())


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the versioned CET-4/CET-6 catalog")
    parser.add_argument("--ecdict", type=Path, default=DEFAULT_ECDICT)
    parser.add_argument("--reference", type=Path, default=DEFAULT_REFERENCE)
    args = parser.parse_args()

    catalog, manifest = build_catalog(args.ecdict, args.reference)
    validate_catalog(catalog)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_CATALOG.write_text(
        json.dumps(catalog, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    OUTPUT_MANIFEST.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
