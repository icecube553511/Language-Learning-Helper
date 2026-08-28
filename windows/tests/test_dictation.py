from __future__ import annotations

import json
import math
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile

WINDOWS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WINDOWS_DIR))

from domain.dictation import (
    DictationField, DictationFormat, DictationOptions,
    blank_count, build_document, cloze_example, parse_meaning, word_prompt,
)
from domain.models import ExampleSentence, VocabularyEntry
from infrastructure.dictation_exporter import DictationDocumentExporter


def entry(word="conduct"):
    return VocabularyEntry.create(
        word, "n. 行为, conduct v. 指挥, 进行",
        [ExampleSentence("They conduct the test.", "他们进行测试。"),
         ExampleSentence("Her conduct was professional.", "她的行为很专业。"),
         ExampleSentence("The guide conducts tours.", "导游带领游览。")],
        level="CET4", tags=("gk",),
    )


class DictationDomainTests(unittest.TestCase):
    def test_blank_count_and_first_code_point(self):
        self.assertEqual(blank_count("abcd"), 8)
        self.assertEqual(word_prompt("😀ab"), "______")
        self.assertEqual(word_prompt("😀ab", True), "😀 ____")
        self.assertEqual(word_prompt("abcd", False), "________")

    def test_options_are_a4_and_bounded(self):
        self.assertEqual(DictationOptions().font_size_pt, 12)
        with self.assertRaises(ValueError):
            DictationOptions(font_size_pt=7)
        with self.assertRaises(ValueError):
            DictationOptions(paper_width_pt=600)

    def test_parse_pos_and_cloze_whole_words(self):
        self.assertEqual(parse_meaning("n. 行为, v. 进行 adj. 有关"), ("n / v / adj", "行为, 进行 有关"))
        self.assertEqual(cloze_example("Conduct conduct conducts re-conducted.", "conduct"),
                         "_____________ _____________ conducts re-conducted.")

    def test_custom_examples_override_and_fields_are_hidden(self):
        options = DictationOptions(
            missing_fields=frozenset({DictationField.WORD, DictationField.PART_OF_SPEECH}),
            include_examples=True,
            custom_examples={"conduct": "Conduct this review."},
        )
        document = build_document([entry()], options)
        row = document.rows[0]
        self.assertEqual(row.part_of_speech, "_________")
        self.assertEqual(row.word, "_____________")
        self.assertEqual(row.examples, ("_____________ this review.",))

    def test_shared_golden_vectors(self):
        root = json.loads((WINDOWS_DIR.parent / "shared/contracts/dictation-export-golden-v1.json").read_text(encoding="utf-8"))
        for vector in root["blankVectors"]:
            with self.subTest(vector=vector["name"]):
                if vector.get("showFirstLetter"):
                    self.assertEqual(word_prompt(vector["text"], True), vector["rendered"])
                else:
                    self.assertEqual(blank_count(vector["text"]), vector["blankCount"])
                self.assertEqual(word_prompt(vector["text"], vector.get("showFirstLetter", False)), vector["rendered"])
        for vector in root["partOfSpeechVectors"]:
            with self.subTest(vector=vector["name"]):
                self.assertEqual(parse_meaning(vector["meaningInput"]), (vector["partOfSpeech"], vector["meaning"]))
        for vector in root["exampleBoundaryVectors"]:
            with self.subTest(vector=vector["name"]):
                self.assertEqual(cloze_example(vector["englishInput"], vector["word"], vector.get("showFirstLetter", False)), vector["englishOutput"])

    def test_docx_and_pdf_are_openable_a4_and_contain_content(self):
        exporter = DictationDocumentExporter()
        options = DictationOptions(formats={DictationFormat.PDF})
        pdf = exporter.export(build_document([entry()], options), DictationFormat.PDF)
        self.assertEqual(pdf.mime_type, "application/pdf")
        self.assertTrue(pdf.bytes.startswith(b"%PDF"))
        self.assertIn(b"/MediaBox [ 0 0 595.2756 841.8898 ]", pdf.bytes)

        docx_options = DictationOptions(formats={DictationFormat.DOCX}, include_examples=True)
        docx = exporter.export(build_document([entry()], docx_options), DictationFormat.DOCX)
        self.assertEqual(docx.mime_type, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        with zipfile.ZipFile(__import__("io").BytesIO(docx.bytes)) as archive:
            xml = archive.read("word/document.xml")
            self.assertIn("conduct".encode(), xml)
            self.assertIn(b"e.g. They", xml)
            self.assertIn(b"11906", archive.read("word/document.xml"))

    def test_empty_document_is_rejected(self):
        exporter = DictationDocumentExporter()
        with self.assertRaises(ValueError):
            exporter.export(build_document([], DictationOptions()), DictationFormat.PDF)


if __name__ == "__main__":
    unittest.main()
