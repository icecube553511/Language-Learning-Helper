package com.lexitrack.learning.presentation

import com.lexitrack.learning.application.TAG_EVALUATED
import com.lexitrack.learning.application.LibraryGroup
import com.lexitrack.learning.domain.DictationDocument
import com.lexitrack.learning.domain.VocabularyEntry
import com.lexitrack.learning.domain.GROUP_ORDER
import com.lexitrack.learning.domain.canonicalMemberships
import com.lexitrack.learning.domain.classifyGroups
import com.lexitrack.learning.domain.groupLabel
import com.lexitrack.learning.domain.normalizeGroupMembership
import kotlin.random.Random

internal data class DictationSelectionRow(
    val id: String,
    val word: String,
    val meaning: String,
    val tagsText: String,
    val isEvaluated: Boolean,
) {
    val evaluationStatus: String
        get() = if (isEvaluated) "已考察" else "未考察"
}

internal fun VocabularyEntry.toDictationSelectionRow(): DictationSelectionRow {
    val isEvaluated = tags.any { it.equals(TAG_EVALUATED, ignoreCase = true) }
    val visibleTags = tags
        .map { it.trim().lowercase() }
        .filter { it.isNotEmpty() && it != TAG_EVALUATED }
        .distinct()
        .sorted()
        .joinToString(" / ")
        .ifEmpty { "-" }
    return DictationSelectionRow(id, word, meaning, visibleTags, isEvaluated)
}

/** Group summaries for a dictation candidate pool (canonical groups first, then extras). */
internal fun dictationGroupSummaries(entries: List<VocabularyEntry>): List<LibraryGroup> {
    val canonicalCounts = GROUP_ORDER.associateWith { 0 }.toMutableMap()
    val extraCounts = linkedMapOf<String, Int>()
    for (entry in entries) {
        val memberships = entry.levels.mapTo(mutableSetOf()) { normalizeGroupMembership(it) }
        for (key in classifyGroups(entry.levels, entry.tags)) {
            if (key in canonicalCounts) canonicalCounts[key] = canonicalCounts.getValue(key) + 1
        }
        for (code in memberships) {
            if (code !in canonicalMemberships()) extraCounts[code] = extraCounts.getOrDefault(code, 0) + 1
        }
    }
    val result = mutableListOf(LibraryGroup("all", groupLabel("all"), canonicalCounts.getValue("all")))
    for (key in GROUP_ORDER.drop(1)) result.add(LibraryGroup(key, groupLabel(key), canonicalCounts.getValue(key)))
    for ((code, count) in extraCounts.toSortedMap()) result.add(LibraryGroup(code, code, count))
    return result
}

/** Filter a dictation candidate pool to a single group. */
internal fun dictationEntriesInGroup(entries: List<VocabularyEntry>, key: String): List<VocabularyEntry> = when {
    key == "all" -> entries
    key in GROUP_ORDER -> entries.filter { key in classifyGroups(it.levels, it.tags) }
    else -> {
        val code = normalizeGroupMembership(key)
        entries.filter { entry -> entry.levels.any { normalizeGroupMembership(it) == code } }
    }
}

internal fun dictationPreviewLines(document: DictationDocument): List<String> =
    document.rows.flatMapIndexed { index, row ->
        buildList {
            add("${index + 1}. ${row.word}    ${row.partOfSpeech}    ${row.meaning}")
            row.examples.forEachIndexed { offset, example ->
                val chinese = row.exampleChinese.getOrNull(offset).orEmpty()
                add("    e.g. $example" + if (chinese.isNotEmpty()) "（$chinese）" else "")
            }
            add("")
        }
    }

/** Random 1-2 second delay in 100 ms steps for the dictation entry animation. */
internal fun dictationLoadingDelayMs(random: Random = Random.Default): Long =
    random.nextInt(10, 21) * 100L
