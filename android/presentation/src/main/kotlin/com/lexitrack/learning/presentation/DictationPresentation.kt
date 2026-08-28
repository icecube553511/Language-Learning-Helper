package com.lexitrack.learning.presentation

import com.lexitrack.learning.application.TAG_EVALUATED
import com.lexitrack.learning.domain.DictationDocument
import com.lexitrack.learning.domain.VocabularyEntry

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

internal fun dictationPreviewLines(document: DictationDocument): List<String> =
    document.rows.flatMapIndexed { index, row ->
        buildList {
            add("${index + 1}. ${row.word}    ${row.partOfSpeech}    ${row.meaning}")
            row.examples.forEach { add("    e.g. $it") }
            add("")
        }
    }
