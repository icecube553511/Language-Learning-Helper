from __future__ import annotations

import csv
from pathlib import Path

from domain.models import ExampleSentence, ImportIssue, ImportReport, VocabularyEntry, normalize_word_id


REQUIRED_COLUMNS = (
    "word",
    "meaning",
    "example1_en",
    "example1_zh",
    "example2_en",
    "example2_zh",
    "example3_en",
    "example3_zh",
)
OPTIONAL_COLUMNS = ("phonetic", "level", "tags", "mnemonic")
KNOWN_COLUMNS = set(REQUIRED_COLUMNS) | set(OPTIONAL_COLUMNS)
VALID_LEVELS = {"CET4", "CET6", "custom"}


class CsvVocabularyImporter:
    def parse(self, path: Path, existing_ids: set[str]) -> tuple[list[VocabularyEntry], ImportReport]:
        report = ImportReport()
        try:
            handle = Path(path).open("r", encoding="utf-8-sig", newline="")
        except UnicodeDecodeError:
            report.failed = 1
            report.issues.append(ImportIssue(0, "", "invalid_encoding", "文件必须为 UTF-8 或 UTF-8 BOM"))
            return [], report
        except OSError as exc:
            report.failed = 1
            report.issues.append(ImportIssue(0, "", "malformed_csv", str(exc)))
            return [], report

        entries: list[VocabularyEntry] = []
        seen = set(existing_ids)
        try:
            with handle:
                reader = csv.DictReader(handle, strict=True)
                headers = [str(item).strip() for item in (reader.fieldnames or []) if item is not None]
                missing = [column for column in REQUIRED_COLUMNS if column not in headers]
                if missing:
                    report.failed = 1
                    for column in missing:
                        report.issues.append(
                            ImportIssue(1, column, "missing_column", f"缺少必填列：{column}")
                        )
                    return [], report
                unknown = [column for column in headers if column not in KNOWN_COLUMNS]
                if unknown:
                    report.warnings.append("已忽略未知列：" + ", ".join(unknown))

                for row_number, raw in enumerate(reader, start=2):
                    report.total_rows += 1
                    values = {str(key).strip(): str(value or "").strip() for key, value in raw.items() if key is not None}
                    issue = self._validate_row(row_number, values, seen)
                    if issue is not None:
                        report.issues.append(issue)
                        if issue.error_code == "duplicate_word":
                            report.skipped += 1
                        else:
                            report.failed += 1
                        continue
                    examples = [
                        ExampleSentence(values[f"example{index}_en"], values[f"example{index}_zh"])
                        for index in range(1, 4)
                    ]
                    entry = VocabularyEntry.create(
                        word=values["word"],
                        meaning=values["meaning"],
                        examples=examples,
                        phonetic=values.get("phonetic", ""),
                        level=values.get("level", "") or "custom",
                        tags=values.get("tags", "").split("|") if values.get("tags") else [],
                        mnemonic=values.get("mnemonic", ""),
                    )
                    entries.append(entry)
                    seen.add(entry.word_id)
        except UnicodeDecodeError:
            report.failed += 1
            report.issues.append(ImportIssue(0, "", "invalid_encoding", "文件必须为 UTF-8 或 UTF-8 BOM"))
            return [], report
        except csv.Error as exc:
            report.failed += 1
            report.issues.append(ImportIssue(report.total_rows + 2, "", "malformed_csv", str(exc)))
            return [], report
        return entries, report

    @staticmethod
    def _validate_row(row: int, values: dict[str, str], seen: set[str]) -> ImportIssue | None:
        for field, value in values.items():
            limit = 100 if field == "word" else 2000
            if len(value) > limit:
                return ImportIssue(row, field, "too_long", f"{field} 超过 {limit} 字符")
        for field in REQUIRED_COLUMNS:
            if not values.get(field, ""):
                return ImportIssue(row, field, "empty_required", f"{field} 不得为空")
        level = values.get("level", "") or "custom"
        if level not in VALID_LEVELS:
            return ImportIssue(row, "level", "invalid_level", "level 必须为 CET4、CET6 或 custom")
        english = [values[f"example{index}_en"] for index in range(1, 4)]
        if len({item.casefold() for item in english}) != 3:
            return ImportIssue(row, "examples", "duplicate_example", "三条英文例句必须互不相同")
        if normalize_word_id(values["word"]) in seen:
            return ImportIssue(row, "word", "duplicate_word", "词条已存在，未覆盖", status="skipped")
        return None

