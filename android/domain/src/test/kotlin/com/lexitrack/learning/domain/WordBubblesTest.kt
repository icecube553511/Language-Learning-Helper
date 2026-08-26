package com.lexitrack.learning.domain

import java.io.File
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.Json
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class WordBubblesTest {
    private val golden by lazy {
        Json.parseToJsonElement(File(requireNotNull(System.getProperty("word.bubble.golden.path"))).readText()).jsonObject
    }

    private fun entry(word: String, meaning: String = "n. 词语") = VocabularyEntry(
        id = normalizeWordId(word),
        word = word,
        meaning = meaning,
        examples = listOf(
            BilingualExample("Use $word here.", "在这里使用。"),
            BilingualExample("Read $word aloud.", "大声读出。"),
            BilingualExample("Remember $word today.", "今天记住。"),
        ),
    )

    @Test fun `tokenizer preserves apostrophes and ignores digits`() {
        assertEquals(
            listOf("Don't", "stop", "students'", "word", "re", "entry"),
            tokenizeEnglish("Don't stop, students'! word2 re-entry").map { it.text },
        )
    }

    @Test fun `lookup extracts pos and chinese`() {
        val definition = resolveBubbleDefinition(listOf(entry("Focus", "v. 集中 n. 焦点")), "focus")
        assertTrue(definition.known)
        assertEquals("v / n", definition.partOfSpeech)
        assertEquals("集中 焦点", definition.meaning)
    }

    @Test fun `unknown words have non recursive definition`() {
        val definition = resolveBubbleDefinition(emptyList(), "unknown", "Unknown appears here.")
        assertFalse(definition.known)
        assertEquals("词库暂无中文释义", definition.meaning)
        assertEquals(listOf("Unknown appears here."), definition.examples)
    }

    @Test fun `stack truncates descendants and closes at depth`() {
        val definitions = listOf("root", "child", "sibling").map { resolveBubbleDefinition(listOf(entry(it)), it) }
        val stack = BubbleStack().openRoot(definitions[0]).openChild(0, definitions[1])
        val sibling = stack.openChild(0, definitions[2])
        assertEquals(listOf("root", "sibling"), sibling.frames.map { it.definition.word })
        assertEquals(listOf("root"), sibling.closeAfter(0).frames.map { it.definition.word })
        assertTrue(sibling.closeAll().frames.isEmpty())
    }

    @Test fun `stack never exceeds nine known layers`() {
        var stack = BubbleStack()
        repeat(12) { index ->
            val word = "word$index"
            val definition = resolveBubbleDefinition(listOf(entry(word)), word)
            stack = if (stack.frames.isEmpty()) stack.openRoot(definition) else stack.openChild(stack.frames.lastIndex, definition)
        }
        assertEquals(9, stack.frames.size)
    }

    @Test fun `tokenizer and depth match shared golden`() {
        assertEquals(MAX_BUBBLE_DEPTH, golden.getValue("maxDepth").jsonPrimitive.int)
        golden.getValue("tokenVectors").jsonArray.forEach { item ->
            val vector = item.jsonObject
            assertEquals(
                vector.getValue("tokens").jsonArray.map { it.jsonPrimitive.content },
                tokenizeEnglish(vector.getValue("text").jsonPrimitive.content).map { it.text },
            )
        }
    }

    @Test fun `stack transitions match shared golden`() {
        val definitions = listOf("root", "child", "sibling").map { resolveBubbleDefinition(listOf(entry(it)), it) }
        val withChild = BubbleStack().openRoot(definitions[0]).openChild(0, definitions[1])
        val withSibling = withChild.openChild(0, definitions[2])
        val expected = golden.getValue("stackVectors").jsonObject
        assertEquals(
            expected.getValue("rootThenChildThenSibling").jsonArray.map { it.jsonPrimitive.content },
            withSibling.frames.map { it.definition.word },
        )
        assertEquals(
            expected.getValue("blankAtRoot").jsonArray.map { it.jsonPrimitive.content },
            withSibling.closeAfter(0).frames.map { it.definition.word },
        )
        assertEquals(
            expected.getValue("outside").jsonArray.map { it.jsonPrimitive.content },
            withSibling.closeAll().frames.map { it.definition.word },
        )
    }
}
