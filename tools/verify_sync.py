from __future__ import annotations

import json
import math
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
CONTRACTS = ROOT / "shared" / "contracts"
CONTENT = ROOT / "shared" / "content"


def fail(message: str) -> None:
    raise AssertionError(message)


def verify_scheduler() -> None:
    payload = json.loads((CONTRACTS / "scheduler-golden-v1.json").read_text(encoding="utf-8"))
    if payload["algorithmVersion"] != "lexi-sm2-v1":
        fail("Unexpected scheduler version")
    initial = payload["initial"]
    for vector in payload["vectors"]:
        ease = float(initial["ease"])
        interval = float(initial["intervalDays"])
        repetitions = int(initial["repetitions"])
        lapses = int(initial["lapses"])
        rating = vector["rating"]
        if rating == "again":
            interval, ease, repetitions, lapses, state = 10 / 1440, max(1.3, ease - 0.2), 0, lapses + 1, "relearning"
        elif rating == "hard":
            interval, ease, repetitions, state = (1 if interval < 1 else max(1, interval * 1.2)), max(1.3, ease - 0.15), repetitions + 1, "learning" if repetitions == 0 else "review"
        elif rating == "good":
            interval, repetitions, state = (3 if interval < 1 else interval * ease), repetitions + 1, "review"
        elif rating == "easy":
            interval, ease, repetitions, state = (7 if interval < 1 else interval * ease * 1.3), min(3.0, ease + 0.15), repetitions + 1, "review"
        else:
            fail(f"Unknown rating: {rating}")
        actual = {
            "state": state,
            "intervalDays": interval,
            "ease": ease,
            "repetitions": repetitions,
            "lapses": lapses,
            "dueAtUtc": vector["reviewedAtUtc"] + interval * 86400,
        }
        for key, expected in vector["expected"].items():
            observed = actual[key]
            if isinstance(expected, float):
                if not math.isclose(observed, expected, rel_tol=1e-12, abs_tol=1e-9):
                    fail(f"Scheduler vector {vector['name']} differs at {key}: {observed} != {expected}")
            elif observed != expected:
                fail(f"Scheduler vector {vector['name']} differs at {key}: {observed} != {expected}")


def verify_catalog() -> None:
    catalog_path = CONTENT / "catalog.json"
    manifest_path = CONTENT / "catalog-manifest.json"
    if not catalog_path.exists() or not manifest_path.exists():
        fail("Catalog and manifest must both exist")
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    parity = json.loads((CONTRACTS / "parity.json").read_text(encoding="utf-8"))
    if manifest["contentVersion"] != parity["contentVersion"]:
        fail("Content version differs from parity manifest")
    if manifest["wordCount"] != len(catalog):
        fail("Manifest word count is stale")
    ids: set[str] = set()
    membership_counts = {"CET4": 0, "CET6": 0}
    for item in catalog:
        entry_id = item.get("id", "")
        if not entry_id or entry_id in ids:
            fail(f"Duplicate or empty word id: {entry_id!r}")
        ids.add(entry_id)
        meaning = str(item.get("meaning", "")).strip()
        if not meaning or not re.search(r"[\u3400-\u9fff]", meaning):
            fail(f"Missing meaning: {entry_id}")
        memberships = item.get("memberships", [])
        if not memberships:
            fail(f"Missing membership: {entry_id}")
        for membership in memberships:
            if membership not in membership_counts:
                fail(f"Invalid membership {membership}: {entry_id}")
            membership_counts[membership] += 1
        examples = item.get("examples", [])
        if len(examples) < 3:
            fail(f"Fewer than three examples: {entry_id}")
        seen_examples: set[str] = set()
        for example in examples[:3]:
            english = str(example.get("en", "")).strip()
            chinese = str(example.get("zh", "")).strip()
            if not english or not chinese or not re.search(r"[\u3400-\u9fff]", chinese):
                fail(f"Incomplete bilingual example: {entry_id}")
            if english.casefold() in seen_examples:
                fail(f"Duplicate English example: {entry_id}")
            seen_examples.add(english.casefold())
    if membership_counts != manifest["membershipCounts"]:
        fail(f"Membership counts are stale: {membership_counts}")


def verify_platform_markers() -> None:
    parity = json.loads((CONTRACTS / "parity.json").read_text(encoding="utf-8"))
    for platform in parity["platforms"]:
        marker_path = ROOT / platform / "platform-contract.json"
        if not marker_path.exists():
            fail(f"Missing platform marker: {marker_path.relative_to(ROOT)}")
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
        for key in ("releaseVersion", "schemaVersion", "algorithmVersion", "contentVersion"):
            if marker.get(key) != parity.get(key):
                fail(f"{platform} {key} differs from shared parity manifest")
        if marker.get("capabilities") != parity.get("capabilities"):
            fail(f"{platform} capabilities differ from shared parity manifest")


def main() -> int:
    verify_scheduler()
    verify_catalog()
    verify_platform_markers()
    print("Synchronization contract verified for Windows, Android and shared content.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"sync verification failed: {exc}", file=sys.stderr)
        raise
