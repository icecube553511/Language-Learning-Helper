package com.lexitrack.learning.application

import com.lexitrack.learning.domain.DictationDocument
import com.lexitrack.learning.domain.DictationDocumentOptions
import com.lexitrack.learning.domain.DictationRow
import com.lexitrack.learning.domain.MarkMode
import com.lexitrack.learning.domain.DictationFormat
import com.lexitrack.learning.domain.VocabularyEntry
import com.lexitrack.learning.domain.fromEntry
import com.lexitrack.learning.domain.GROUP_ORDER
import com.lexitrack.learning.domain.classifyGroups
import com.lexitrack.learning.domain.normalizeGroupMembership
import com.lexitrack.learning.domain.DictationDraft
import com.lexitrack.learning.domain.DictationDraftSyncMetadata
import com.lexitrack.learning.domain.normalizeWordId
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
    fun random(
        count: Int,
        group: String = "all",
        includeEvaluated: Boolean = false,
        candidateIds: Collection<String>? = null,
    ): List<VocabularyEntry> {
        require(count >= 0) { "默写词数不能为负数" }
        val wanted = candidateIds?.map(::normalizeWordId)?.toSet()
        val pool = filtered(group, includeEvaluated)
            .filter { wanted == null || normalizeWordId(it.id) in wanted }
            .sortedBy { normalizeWordId(it.id) }
            .toMutableList()
        val selected = ArrayList<VocabularyEntry>(minOf(count, pool.size))
        repeat(minOf(count, pool.size)) {
            val index = (randomUnit().coerceIn(0.0, 0.9999999999999999) * pool.size).toInt()
            selected += pool.removeAt(index)
        }
        return selected
    }

    fun selected(ids: Collection<String>, includeEvaluated: Boolean = false, group: String = "all"): List<VocabularyEntry> {
        val requested = ids.map(::normalizeWordId).toSet()
        return filtered(group, includeEvaluated).filter { normalizeWordId(it.id) in requested }.sortedBy { normalizeWordId(it.id) }
    }

    fun groupPool(group: String = "all", includeEvaluated: Boolean = false): List<VocabularyEntry> =
        filtered(group, includeEvaluated)

    private fun filtered(group: String, includeEvaluated: Boolean): List<VocabularyEntry> {
        val base = vocabulary.words.value.filter { entry ->
            includeEvaluated || entry.tags.none { it.equals(TAG_EVALUATED, ignoreCase = true) }
        }.distinctBy { normalizeWordId(it.id) }
        return if (group == "all") base else entriesInGroup(base, group)
    }
}

class DictationDraftUseCase(private val repository: DictationDraftRepository?) {
    val available: Boolean get() = repository != null
    fun load(): DictationDraft? = repository?.get()
    fun save(draft: DictationDraft) { repository?.save(draft) }
    fun clear() { repository?.clear() }
    fun loadSyncMetadata(): DictationDraftSyncMetadata? = repository?.getSyncMetadata()
    fun saveSyncMetadata(metadata: DictationDraftSyncMetadata) { repository?.saveSyncMetadata(metadata) }
    fun saveLastSyncedEnvelope(envelope: DictationDraftSyncEnvelope) {
        repository?.saveLastSyncedEnvelope(envelope)
    }
    fun addConflictBackup(envelope: DictationDraftSyncEnvelope) {
        repository?.addConflictBackup(envelope)
    }
}

private fun entriesInGroup(entries: List<VocabularyEntry>, key: String): List<VocabularyEntry> = when {
    key == "all" -> entries
    key in GROUP_ORDER -> entries.filter { key in classifyGroups(it.levels, it.tags) }
    else -> {
        val code = normalizeGroupMembership(key)
        entries.filter { entry -> entry.levels.any { normalizeGroupMembership(it) == code } }
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
