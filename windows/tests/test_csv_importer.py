from __future__ import annotations

import csv
from pathlib import Path
import sys
import tempfile
import unittest


WINDOWS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WINDOWS_DIR))

from infrastructure.csv_importer import CsvVocabularyImporter


HEADERS = [
    "word", "meaning", "phonetic", "level", "tags", "mnemonic",
    "example1_en", "example1_zh", "example2_en", "example2_zh", "example3_en", "example3_zh",
]


def valid_row(word="negotiate"):
    return [
        word, "v. 谈判,协商", "/nɪˈɡəʊʃieɪt/", "CET6", "business|meeting", "",
        "They negotiated a better contract.", "他们谈成了一份更好的合同。",
        "We need to negotiate with the supplier.", "我们需要与供应商协商。",
        '"Negotiate clearly," the manager said.', '经理说："要清楚地协商。"',
    ]


class CsvImporterTests(unittest.TestCase):
    def write_rows(self, rows, encoding="utf-8-sig") -> Path:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "words.csv"
        with path.open("w", encoding=encoding, newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(HEADERS)
            writer.writerows(rows)
        return path

    def test_imports_bom_quotes_commas_and_tags(self):
        entries, report = CsvVocabularyImporter().parse(self.write_rows([valid_row()]), set())
        self.assertEqual((report.total_rows, len(entries), report.failed), (1, 1, 0))
        self.assertEqual(entries[0].level, "CET6")
        self.assertEqual(entries[0].tags, ("business", "meeting"))
        self.assertIn("谈判,协商", entries[0].meaning)

    def test_duplicates_are_skipped_without_overwrite(self):
        path = self.write_rows([valid_row("Alpha"), valid_row("Ａlpha")])
        entries, report = CsvVocabularyImporter().parse(path, set())
        self.assertEqual(len(entries), 1)
        self.assertEqual(report.skipped, 1)
        self.assertEqual(report.issues[0].error_code, "duplicate_word")

    def test_rejects_duplicate_examples(self):
        row = valid_row()
        row[8] = row[6]
        entries, report = CsvVocabularyImporter().parse(self.write_rows([row]), set())
        self.assertEqual(entries, [])
        self.assertEqual(report.failed, 1)
        self.assertEqual(report.issues[0].error_code, "duplicate_example")

    def test_reports_missing_column(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "bad.csv"
        path.write_text("word,meaning\nhello,你好\n", encoding="utf-8")
        entries, report = CsvVocabularyImporter().parse(path, set())
        self.assertEqual(entries, [])
        self.assertTrue(any(item.error_code == "missing_column" for item in report.issues))


if __name__ == "__main__":
    unittest.main()

