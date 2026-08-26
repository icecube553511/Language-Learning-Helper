package com.lexitrack.learning.domain

import java.io.File
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.Json
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith

class DictationTest {
    private val golden by lazy { Json.parseToJsonElement(File(requireNotNull(System.getProperty("dictation.export.golden.path"))).readText()).jsonObject }

    @Test fun `blank vectors match shared golden`() {
        golden.getValue("blankVectors").jsonArray.forEach { item ->
            val vector = item.jsonObject
            val text = vector.getValue("text").jsonPrimitive.content
            val first = vector["showFirstLetter"]?.jsonPrimitive?.booleanOrNull ?: false
            val expectedCount = vector.getValue("blankCount").jsonPrimitive.int
            val actualCount = if (first) (text.trim().codePointCount(0, text.trim().length) - 1).let { kotlin.math.ceil(it * 1.8).toInt() } else blankCount(text)
            assertEquals(expectedCount, actualCount)
            assertEquals(vector.getValue("rendered").jsonPrimitive.content, wordPrompt(text, first))
        }
    }

    @Test fun `part of speech vectors match shared golden`() {
        golden.getValue("partOfSpeechVectors").jsonArray.forEach { item ->
            val vector = item.jsonObject
            val parsed = parseMeaning(vector.getValue("meaningInput").jsonPrimitive.content)
            assertEquals(vector.getValue("partOfSpeech").jsonPrimitive.content, parsed.partOfSpeech)
            assertEquals(vector.getValue("meaning").jsonPrimitive.content, parsed.chineseMeaning)
        }
    }

    @Test fun `example vectors match shared golden`() {
        golden.getValue("exampleBoundaryVectors").jsonArray.forEach { item ->
            val vector = item.jsonObject
            assertEquals(
                vector.getValue("englishOutput").jsonPrimitive.content,
                clozeExample(vector.getValue("englishInput").jsonPrimitive.content, vector.getValue("word").jsonPrimitive.content, vector["showFirstLetter"]?.jsonPrimitive?.booleanOrNull ?: false),
            )
        }
    }

    @Test fun `missing fields cannot be empty`() {
        assertFailsWith<IllegalArgumentException> { DictationDocumentOptions(missingFields = emptySet()) }
    }
}
