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

    @Test
    fun `review reminder message clears when due count reaches zero`() {
        // A fresh due count announces the reminder and records the count.
        val announce = resolveReviewReminderMessage(dueNow = 5, lastRemindedDueCount = 0, currentMessage = null)
        assertEquals("有 5 个单词已按记忆曲线到期。" to 5, announce)

        // Same due count keeps the current message without re-announcing.
        val same = resolveReviewReminderMessage(dueNow = 5, lastRemindedDueCount = 5, currentMessage = announce.first)
        assertEquals(announce.first to 5, same)

        // After reviewing, dueNow == 0 clears the lingering reminder.
        val cleared = resolveReviewReminderMessage(dueNow = 0, lastRemindedDueCount = 5, currentMessage = announce.first)
        assertEquals(null to 0, cleared)
    }

    @Test
    fun `dictation group summaries respect the candidate pool`() {
        val base = entry(tags = emptySet())
        val pool = listOf(
            base.copy(id = "adapt", word = "adapt", levels = setOf("CET4"), tags = setOf("gk")),
            base.copy(id = "abandon", word = "abandon", levels = setOf("CET6"), tags = setOf("zk")),
            base.copy(id = "examined", word = "examined", levels = setOf("CET4"), tags = setOf("evaluated")),
            base.copy(id = "myword", word = "myword", levels = setOf("CUSTOM"), tags = emptySet()),
        )
        val groups = dictationGroupSummaries(pool)
        assertEquals(listOf("all", "cet4", "cet6", "zk", "gk", "custom"), groups.map { it.key })
        assertEquals(
            mapOf("all" to 4, "cet4" to 2, "cet6" to 1, "zk" to 1, "gk" to 1, "custom" to 1),
            groups.associate { it.key to it.count },
        )
    }

    @Test
    fun `dictation entries in a group filter by level or recognized tag`() {
        val base = entry(tags = emptySet())
        val pool = listOf(
            base.copy(id = "adapt", word = "adapt", levels = setOf("CET4"), tags = setOf("gk")),
            base.copy(id = "abandon", word = "abandon", levels = setOf("CET6"), tags = setOf("zk")),
            base.copy(id = "myword", word = "myword", levels = setOf("CUSTOM"), tags = emptySet()),
        )
        assertEquals(setOf("adapt"), dictationEntriesInGroup(pool, "cet4").map { it.id }.toSet())
        assertEquals(setOf("adapt"), dictationEntriesInGroup(pool, "gk").map { it.id }.toSet())
        assertEquals(setOf("myword"), dictationEntriesInGroup(pool, "custom").map { it.id }.toSet())
        assertEquals(3, dictationEntriesInGroup(pool, "all").size)
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
