package com.lexitrack.learning.application

import com.lexitrack.learning.domain.BilingualExample
import com.lexitrack.learning.domain.MarkMode
import com.lexitrack.learning.domain.VocabularyEntry
import com.lexitrack.learning.domain.DictationDocumentOptions
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.runBlocking
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith

class DictationUseCasesTest {
    private val entries = listOf(
        entry("z", setOf("CET4"), setOf("gk")),
        entry("a", setOf("CET4"), setOf("evaluated")),
        entry("b", setOf("CET6"), emptySet()),
    )

    @Test fun `random selection is without replacement and filters evaluated`() {
        val result = SelectDictationCandidatesUseCase(FakeVocabulary(entries), randomUnit = { 0.0 })
            .random(10, "cet4")
        assertEquals(listOf("z"), result.map { it.id })
    }

    @Test fun `random selection respects the group scope`() {
        val vocab = FakeVocabulary(entries + entry("w", setOf("CUSTOM"), emptySet()))
        val cet4 = SelectDictationCandidatesUseCase(vocab, randomUnit = { 0.0 }).random(20, "cet4")
        assertEquals(setOf("z"), cet4.map { it.id }.toSet())
        val custom = SelectDictationCandidatesUseCase(vocab, randomUnit = { 0.0 }).random(20, "custom")
        assertEquals(setOf("w"), custom.map { it.id }.toSet())
    }

    @Test fun `selected ids are sorted and can include evaluated`() {
        val result = SelectDictationCandidatesUseCase(FakeVocabulary(entries))
            .selected(listOf("z", "a"), includeEvaluated = true)
        assertEquals(listOf("a", "z"), result.map { it.id })
    }

    @Test fun `program tags are allowlisted`() = runBlocking {
        val repository = FakeVocabulary(entries)
        UpdateProgramTagsUseCase(repository)(setOf("z"), setOf(TAG_EVALUATED), emptySet())
        assertEquals(setOf("gk", TAG_EVALUATED), repository.words.value.first { it.id == "z" }.tags)
        assertFailsWith<IllegalArgumentException> {
            runBlocking { UpdateProgramTagsUseCase(repository)(setOf("z"), setOf("custom"), emptySet()) }
        }
    }

    @Test fun `mark mode setting is updated`() = runBlocking {
        val settings = FakeSettings()
        UpdateMarkModeUseCase(settings)(MarkMode.ALWAYS)
        assertEquals(MarkMode.ALWAYS, settings.settings.value.markMode)
    }

    @Test fun `document uses one matching example and custom override`() {
        val entry = entries.first().copy(examples = listOf(
            com.lexitrack.learning.domain.BilingualExample("unrelated", "无关"),
            com.lexitrack.learning.domain.BilingualExample("A Z word", "匹配"),
            com.lexitrack.learning.domain.BilingualExample("last", "最后"),
        ))
        val options = DictationDocumentOptions(includeExamples = true, customExamples = mapOf(entry.id to "Custom z"))
        val row = BuildDictationDocumentUseCase()(listOf(entry), options).rows.single()
        assertEquals(listOf("Custom __"), row.examples)
        val fallback = BuildDictationDocumentUseCase()(listOf(entry), options.copy(customExamples = mapOf(entry.id to " "))).rows.single()
        assertEquals(listOf("A __ word"), fallback.examples)
    }

    private fun entry(id: String, levels: Set<String>, tags: Set<String>) = VocabularyEntry(
        id, id, "n. 中文", levels = levels, tags = tags,
        examples = listOf(BilingualExample("$id here", "这里"), BilingualExample("Other $id", "其他"), BilingualExample("$id again", "再一次")),
    )
}

private class FakeVocabulary(initial: List<VocabularyEntry>) : VocabularyRepository {
    override val words = MutableStateFlow(initial)
    override val status = MutableStateFlow(CatalogStatus(loading = false))
    override suspend fun initialize() = Unit
    override suspend fun importCsv(input: java.io.InputStream) = com.lexitrack.learning.domain.ImportReport.Empty
    override suspend fun updateLabels(wordIds: Set<String>, levels: Set<String>, tags: Set<String>) = 0
    override suspend fun updateTags(wordIds: Set<String>, add: Set<String>, remove: Set<String>): Int {
        words.value = words.value.map { if (it.id !in wordIds) it else it.copy(tags = (it.tags + add) - remove) }
        return wordIds.size
    }
}

private class FakeSettings : SettingsRepository {
    override val settings = MutableStateFlow(UserSettings())
    override suspend fun setFontScale(scale: Float) {}
    override suspend fun setReviewBatchSize(count: Int) {}
    override suspend fun setStudyOrder(order: String) {}
    override suspend fun setStudyLevels(levels: Set<String>) {}
    override suspend fun setReviewLevels(levels: Set<String>) {}
    override suspend fun setReminderLevels(levels: Set<String>) {}
    override suspend fun setReminderEnabled(enabled: Boolean) {}
    override suspend fun setReminderIntervalMinutes(minutes: Float) {}
    override suspend fun setMarkMode(mode: MarkMode) { settings.value = settings.value.copy(markMode = mode) }
}
