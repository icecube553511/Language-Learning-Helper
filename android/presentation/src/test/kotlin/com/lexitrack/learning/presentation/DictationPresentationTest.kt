package com.lexitrack.learning.presentation

import com.lexitrack.learning.application.ExportedDictation
import com.lexitrack.learning.domain.BilingualExample
import com.lexitrack.learning.domain.DictationDocument
import com.lexitrack.learning.domain.DictationDocumentOptions
import com.lexitrack.learning.domain.DictationRow
import com.lexitrack.learning.domain.VocabularyEntry
import kotlin.random.Random
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class DictationPresentationTest {
    @Test
    fun `save spec keeps each export on its matching SAF format`() {
        val docx = dictationSaveSpec(
            ExportedDictation(
                bytes = byteArrayOf(1),
                fileName = "默写.PDF",
                mimeType = "$DICTATION_DOCX_MIME_TYPE; charset=binary",
            ),
        )
        val pdf = dictationSaveSpec(
            ExportedDictation(
                bytes = byteArrayOf(2),
                fileName = "默写.docx",
                mimeType = DICTATION_PDF_MIME_TYPE,
            ),
        )

        assertEquals(DICTATION_DOCX_MIME_TYPE, docx.mimeType)
        assertEquals("默写.docx", docx.fileName)
        assertEquals(DICTATION_PDF_MIME_TYPE, pdf.mimeType)
        assertEquals("默写.pdf", pdf.fileName)
    }

    @Test
    fun `manual selection row excludes evaluated from visible tags`() {
        val row = entry(tags = setOf("ZK", "Evaluated", "gk"))
            .copy(levels = setOf("CET4", "CET6"))
            .toDictationSelectionRow()

        assertEquals("gk / zk", row.tagsText)
        assertEquals("已考察", row.evaluationStatus)
        assertTrue(row.isEvaluated)
    }

    @Test
    fun `manual selection row marks entries without evaluated as unevaluated`() {
        val row = entry(tags = emptySet()).toDictationSelectionRow()

        assertEquals("-", row.tagsText)
        assertEquals("未考察", row.evaluationStatus)
        assertFalse(row.isEvaluated)
    }

    @Test
    fun `preview lines render every row from the supplied document`() {
        val document = DictationDocument(
            rows = listOf(
                DictationRow("a__", "n", "第一个词", listOf("A ___ example.")),
                DictationRow("ability", "n", "能力"),
            ),
            options = DictationDocumentOptions(),
        )

        assertEquals(
            listOf(
                "1. a__    n    第一个词",
                "    e.g. A ___ example.",
                "",
                "2. ability    n    能力",
                "",
            ),
            dictationPreviewLines(document),
        )
    }

    @Test
    fun `dictation loading delay is a random one to two seconds in 100 ms steps`() {
        val seen = mutableSetOf<Long>()
        val random = Random(20260828)
        repeat(500) {
            seen += dictationLoadingDelayMs(random)
        }

        assertTrue(seen.all { it in 1000L..2000L })
        assertTrue(seen.all { it % 100L == 0L })
        assertTrue(seen.size > 1)
    }

    private fun entry(tags: Set<String>) = VocabularyEntry(
        id = "ability",
        word = "ability",
        meaning = "n. 能力, 才能",
        tags = tags,
        examples = listOf(
            BilingualExample("Ability matters.", "能力很重要。"),
            BilingualExample("Show your ability.", "展示你的能力。"),
            BilingualExample("Her ability improved.", "她的能力提高了。"),
        ),
    )
}
