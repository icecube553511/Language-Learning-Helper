package com.lexitrack.learning.application

import com.lexitrack.learning.domain.DictationDocument
import com.lexitrack.learning.domain.DictationDocumentOptions
import com.lexitrack.learning.domain.DictationRow
import com.lexitrack.learning.domain.MarkMode
import com.lexitrack.learning.domain.DictationFormat
import com.lexitrack.learning.domain.VocabularyEntry
import com.lexitrack.learning.domain.fromEntry
import kotlin.random.Random

const val TAG_CET4 = "cet4"
const val TAG_CET6 = "cet6"
const val TAG_GK = "gk"
const val TAG_ZK = "zk"
const val TAG_EVALUATED = "evaluated"
val PROGRAM_TAGS = setOf(TAG_CET4, TAG_CET6, TAG_GK, TAG_ZK, TAG_EVALUATED)

class SelectDictationCandidatesUseCase(
    private val vocabulary: VocabularyRepository,
    private val randomUnit: () -> Double = { Random.Default.nextDouble() },
) {
    fun random(count: Int, levels: Set<String> = emptySet(), includeEvaluated: Boolean = false): List<VocabularyEntry> {
        require(count >= 0) { "默写词数不能为负数" }
        val pool = filtered(levels, includeEvaluated).sortedBy { it.id }.toMutableList()
        val selected = ArrayList<VocabularyEntry>(minOf(count, pool.size))
        repeat(minOf(count, pool.size)) {
            val index = (randomUnit().coerceIn(0.0, 0.9999999999999999) * pool.size).toInt()
            selected += pool.removeAt(index)
        }
        return selected
    }

    fun selected(ids: Collection<String>, levels: Set<String> = emptySet(), includeEvaluated: Boolean = false): List<VocabularyEntry> {
        val requested = ids.toSet()
        return filtered(levels, includeEvaluated).filter { it.id in requested }.sortedBy { it.id }
    }

    private fun filtered(levels: Set<String>, includeEvaluated: Boolean): List<VocabularyEntry> {
        val normalizedLevels = levels.map(String::uppercase).toSet()
        return vocabulary.words.value.filter { entry ->
            (normalizedLevels.isEmpty() || entry.levels.any { it.uppercase() in normalizedLevels }) &&
                (includeEvaluated || entry.tags.none { it.equals(TAG_EVALUATED, ignoreCase = true) })
        }.distinctBy { it.id }
    }
}

class BuildDictationDocumentUseCase {
    operator fun invoke(entries: List<VocabularyEntry>, options: DictationDocumentOptions): DictationDocument =
        DictationDocument(entries.distinctBy { it.id }.map { DictationRow.fromEntry(it, options) }, options)
}

class ExportDictationDocumentUseCase(private val exporter: DictationExporter) {
    operator fun invoke(document: DictationDocument, format: DictationFormat): ExportedDictation = exporter.export(document, format)
    operator fun invoke(document: DictationDocument): List<ExportedDictation> =
        document.options.formats.sortedBy { it.name }.map { exporter.export(document, it) }
}

class UpdateProgramTagsUseCase(private val vocabulary: VocabularyRepository) {
    suspend operator fun invoke(wordIds: Set<String>, add: Set<String>, remove: Set<String>): Int {
        val normalizedAdd = add.map(String::lowercase).toSet()
        val normalizedRemove = remove.map(String::lowercase).toSet()
        require((normalizedAdd + normalizedRemove).all { it in PROGRAM_TAGS }) { "只允许修改程序标签" }
        require(normalizedAdd.intersect(normalizedRemove).isEmpty()) { "同一标签不能同时添加和移除" }
        return vocabulary.updateTags(wordIds, normalizedAdd, normalizedRemove)
    }
}

class UpdateMarkModeUseCase(private val settings: SettingsRepository) {
    suspend operator fun invoke(mode: MarkMode) = settings.setMarkMode(mode)
}
