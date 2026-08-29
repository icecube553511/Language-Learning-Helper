from __future__ import annotations

import json
import math
import re
import sys
from pathlib import Path

from opencc import OpenCC


ROOT = Path(__file__).resolve().parent.parent
CONTRACTS = ROOT / "shared" / "contracts"
CONTENT = ROOT / "shared" / "content"
TO_SIMPLIFIED = OpenCC("t2s")


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


def verify_weighted_review() -> None:
    payload = json.loads((CONTRACTS / "weighted-review-golden-v1.json").read_text(encoding="utf-8"))
    if payload.get("contractVersion") != "weighted-review-v1":
        fail("Unexpected weighted review contract version")
    expected_initial = {"again": 1.0, "hard": 0.8, "good": 0.2, "easy": 0.05}
    for vector in payload.get("ratings", []):
        rating = vector.get("rating")
        if rating not in expected_initial:
            fail(f"Unknown weighted review rating: {rating}")
        if not math.isclose(float(vector.get("initialWeight", -1)), expected_initial[rating]):
            fail(f"Initial review weight differs for {rating}")
        expected_review = (
            float(vector["previousWeight"])
            if rating in {"again", "hard"}
            else expected_initial[rating]
        )
        if not math.isclose(float(vector.get("reviewWeight", -1)), expected_review):
            fail(f"Updated review weight differs for {rating}")
    if int(payload.get("defaultBatchSize", 0)) != 20:
        fail("Unexpected default review batch size")


def verify_dictation_contract() -> None:
    contract_path = CONTRACTS / "dictation-export-v1.md"
    golden_path = CONTRACTS / "dictation-export-golden-v1.json"
    if not contract_path.is_file() or not contract_path.read_text(encoding="utf-8").strip():
        fail("Dictation export contract is missing or empty")
    if not golden_path.is_file():
        fail("Dictation export golden file is missing")
    payload = json.loads(golden_path.read_text(encoding="utf-8"))
    if payload.get("contractVersion") != "dictation-export-v1":
        fail("Unexpected dictation export contract version")
    page = payload.get("page", {})
    if page.get("size") != "A4" or page.get("orientation") != "portrait":
        fail("Dictation export must use A4 portrait")
    font_size = payload.get("fontSizePt", {})
    if (font_size.get("default"), font_size.get("minimum"), font_size.get("maximum")) != (12, 8, 24):
        fail("Unexpected dictation export font-size bounds")
    if payload.get("formats") != ["DOCX", "PDF"]:
        fail("Dictation export formats differ from the shared contract")
    if payload.get("allowedTags") != ["cet4", "cet6", "gk", "zk", "evaluated"]:
        fail("Dictation program tag allowlist differs from the shared contract")
    confirmation = payload.get("confirmation", {})
    if confirmation.get("rendered") != "当前仅选择了3/10，是否确定选择":
        fail("Dictation manual-selection confirmation text differs from the shared contract")
    evaluated = payload.get("evaluated", {})
    if evaluated.get("defaultPreference") != "ASK" or evaluated.get("preferences") != ["ASK", "ALWAYS", "NEVER"]:
        fail("Dictation evaluated preferences differ from the shared contract")
    selection_ui = payload.get("manualSelectionUi", {})
    if selection_ui.get("columns") != ["word", "meaning", "tags", "evaluationStatus", "selected"]:
        fail("Dictation manual-selection columns differ from the shared contract")
    if selection_ui.get("headings") != ["单词", "中文释义", "标签", "考察状态", "选择"]:
        fail("Dictation manual-selection headings differ from the shared contract")
    if (
        selection_ui.get("evaluatedTag") != "evaluated"
        or selection_ui.get("evaluatedText") != "已考察"
        or selection_ui.get("evaluatedColor") != "black"
        or selection_ui.get("unevaluatedText") != "未考察"
        or selection_ui.get("unevaluatedColor") != "red"
        or selection_ui.get("emptyTagsText") != "-"
        or selection_ui.get("selectionControl") != "checkbox"
        or selection_ui.get("horizontalOverflow") != "scroll"
        or selection_ui.get("rowClickSelection") is not True
        or selection_ui.get("dragMultiSelect") is not True
        or selection_ui.get("downloadAction") != "下载文档"
        or selection_ui.get("downloadPathSelection") != "user-selected"
    ):
        fail("Dictation manual-selection behavior differs from the shared contract")
    example_chinese = payload.get("exampleChineseVector", {})
    if (
        example_chinese.get("includeExample") is not True
        or example_chinese.get("includeExampleChinese") is not True
        or example_chinese.get("renderedExampleLine") != "e.g. We _________ quickly.（我们很快适应。）"
    ):
        fail("Dictation example-with-Chinese semantics differ from the shared contract")


def verify_word_bubble_contract() -> None:
    contract_path = CONTRACTS / "word-bubble-v1.md"
    golden_path = CONTRACTS / "word-bubble-golden-v1.json"
    if not contract_path.is_file() or "word-bubble-v1" not in contract_path.read_text(encoding="utf-8"):
        fail("Word bubble contract is missing or has the wrong version")
    if not golden_path.is_file():
        fail("Word bubble golden file is missing")
    payload = json.loads(golden_path.read_text(encoding="utf-8"))
    if payload.get("contractVersion") != "word-bubble-v1" or payload.get("maxDepth") != 9:
        fail("Word bubble contract version or max depth differs")
    stack_vectors = payload.get("stackVectors", {})
    if stack_vectors.get("dismissChild") != ["root"] or stack_vectors.get("dismissRoot") != []:
        fail("Word bubble dismiss semantics differ from the shared golden")
    if "bilingual example" not in contract_path.read_text(encoding="utf-8"):
        fail("Word bubble contract must require bilingual example rendering")
    parity = json.loads((CONTRACTS / "parity.json").read_text(encoding="utf-8"))
    if parity.get("wordBubbleVersion") != "word-bubble-v1":
        fail("Parity manifest does not declare word-bubble-v1")


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
            if TO_SIMPLIFIED.convert(chinese) != chinese:
                fail(f"Example translation is not Simplified Chinese: {entry_id}")
            if "\u200b" in chinese:
                fail(f"Example translation contains a zero-width space: {entry_id}")
            if english.casefold() in seen_examples:
                fail(f"Duplicate English example: {entry_id}")
            seen_examples.add(english.casefold())
    if membership_counts != manifest["membershipCounts"]:
        fail(f"Membership counts are stale: {membership_counts}")


def verify_branding() -> None:
    parity = json.loads((CONTRACTS / "parity.json").read_text(encoding="utf-8"))
    relative_path = parity.get("branding", {}).get("appImage")
    if not relative_path:
        fail("Shared app image is not declared")
    image_path = ROOT / relative_path
    if not image_path.is_file():
        fail(f"Shared app image is missing: {relative_path}")
    with image_path.open("rb") as image_file:
        signature = image_file.read(8)
    if signature != b"\x89PNG\r\n\x1a\n":
        fail(f"Shared app image is not a PNG: {relative_path}")


def verify_platform_markers() -> None:
    parity = json.loads((CONTRACTS / "parity.json").read_text(encoding="utf-8"))
    for platform in parity["platforms"]:
        marker_path = ROOT / platform / "platform-contract.json"
        if not marker_path.exists():
            fail(f"Missing platform marker: {marker_path.relative_to(ROOT)}")
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
        for key in ("releaseVersion", "schemaVersion", "algorithmVersion", "wordBubbleVersion", "contentVersion"):
            if marker.get(key) != parity.get(key):
                fail(f"{platform} {key} differs from shared parity manifest")
        for key in ("branding", "fontScale", "learningReminder", "studyOrder", "vocabularyFilters"):
            if marker.get(key) != parity.get(key):
                fail(f"{platform} {key} differs from shared parity manifest")
        if marker.get("capabilities") != parity.get("capabilities"):
            fail(f"{platform} capabilities differ from shared parity manifest")


def main() -> int:
    verify_scheduler()
    verify_weighted_review()
    verify_dictation_contract()
    verify_word_bubble_contract()
    verify_catalog()
    verify_branding()
    verify_platform_markers()
    print("Synchronization contract verified for Windows, Android and shared resources.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"sync verification failed: {exc}", file=sys.stderr)
        raise
