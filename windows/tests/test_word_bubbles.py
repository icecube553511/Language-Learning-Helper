from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest

WINDOWS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WINDOWS_DIR))

from domain.models import ExampleSentence, VocabularyEntry
from domain.word_bubbles import BubbleStack, resolve_bubble_definition, tokenize_english
from presentation.widgets import _hit_test_lines, _text_block_origin, _wrapped_text_lines


def entry(word: str, meaning: str = "n. 词语") -> VocabularyEntry:
    return VocabularyEntry.create(word, meaning, [
        ExampleSentence(f"Use {word} here.", "在这里使用。"),
        ExampleSentence(f"Read {word} aloud.", "大声读出。"),
        ExampleSentence(f"Remember {word} today.", "今天记住。"),
    ])


class WordBubbleTests(unittest.TestCase):
    def test_tokenizer_preserves_apostrophes_and_ignores_digits(self):
        self.assertEqual(
            [token.text for token in tokenize_english("Don't stop, students'! word2 re-entry")],
            ["Don't", "stop", "students'", "word", "re", "entry"],
        )

    def test_tokenizer_and_depth_match_shared_golden(self):
        golden = json.loads((WINDOWS_DIR.parent / "shared/contracts/word-bubble-golden-v1.json").read_text(encoding="utf-8"))
        self.assertEqual(golden["maxDepth"], 9)
        for vector in golden["tokenVectors"]:
            with self.subTest(text=vector["text"]):
                self.assertEqual([token.text for token in tokenize_english(vector["text"])], vector["tokens"])

    def test_stack_transitions_match_shared_golden(self):
        golden = json.loads((WINDOWS_DIR.parent / "shared/contracts/word-bubble-golden-v1.json").read_text(encoding="utf-8"))
        definitions = [resolve_bubble_definition([entry(word)], word) for word in ("root", "child", "sibling")]
        with_child = BubbleStack().open_root(definitions[0]).open_child(0, definitions[1])
        with_sibling = with_child.open_child(0, definitions[2])
        actual = {
            "rootThenChildThenSibling": [frame.definition.word for frame in with_sibling.frames],
            "blankAtRoot": [frame.definition.word for frame in with_sibling.close_after(0).frames],
            "outside": [frame.definition.word for frame in with_sibling.close_all().frames],
        }
        self.assertEqual(actual, golden["stackVectors"])

    def test_lookup_extracts_pos_and_chinese(self):
        definition = resolve_bubble_definition([entry("Focus", "v. 集中 n. 焦点")], "focus")
        self.assertTrue(definition.known)
        self.assertEqual(definition.part_of_speech, "v / n")
        self.assertEqual(definition.meaning, "集中 焦点")

    def test_unknown_words_retain_source_example_for_recursive_presentation(self):
        definition = resolve_bubble_definition([], "unknown", "Unknown appears here.")
        self.assertFalse(definition.known)
        self.assertEqual(definition.meaning, "词库暂无中文释义")
        self.assertEqual(definition.examples, ("Unknown appears here.",))

    def test_stack_truncates_descendants_and_closes_at_depth(self):
        definitions = [resolve_bubble_definition([entry(word)], word) for word in ("root", "child", "sibling")]
        stack = BubbleStack().open_root(definitions[0]).open_child(0, definitions[1])
        sibling = stack.open_child(0, definitions[2])
        self.assertEqual([frame.definition.word for frame in sibling.frames], ["root", "sibling"])
        self.assertEqual([frame.definition.word for frame in sibling.close_after(0).frames], ["root"])
        self.assertEqual(len(sibling.close_all().frames), 0)

    def test_stack_never_exceeds_nine_known_layers(self):
        stack = BubbleStack()
        for index in range(12):
            word = f"word{index}"
            stack = stack.open_root(resolve_bubble_definition([entry(word)], word)) if not stack.frames else stack.open_child(len(stack.frames) - 1, resolve_bubble_definition([entry(word)], word))
        self.assertEqual(len(stack.frames), 9)

    def test_wrapped_hit_test_selects_only_the_clicked_word_and_line(self):
        text = "One two three\n中文"
        measure = lambda value: len(value) * 10
        lines = _wrapped_text_lines(text, 80, measure)
        tokens = tokenize_english("One two three")
        self.assertEqual(_hit_test_lines(tokens, lines, measure, text, 15, 5, 0, 0, 70, 20, "left").text, "One")
        self.assertEqual(_hit_test_lines(tokens, lines, measure, text, 25, 25, 0, 0, 70, 20, "left").text, "three")
        self.assertIsNone(_hit_test_lines(tokens, lines, measure, text, 35, 5, 0, 0, 70, 20, "left"))
        self.assertIsNone(_hit_test_lines(tokens, lines, measure, text, 15, 45, 0, 0, 70, 20, "left"))

    def test_text_block_origin_uses_exact_tk_anchor_values(self):
        dimensions = (600, 100, 4, 6, 200, 40)
        self.assertEqual(_text_block_origin("center", *dimensions), (200, 30))
        self.assertEqual(_text_block_origin("nw", *dimensions), (4, 6))
        self.assertEqual(_text_block_origin("se", *dimensions), (396, 54))
        self.assertEqual(_text_block_origin("w", *dimensions), (4, 30))
        self.assertEqual(_text_block_origin("n", *dimensions), (200, 6))


if __name__ == "__main__":
    unittest.main()
