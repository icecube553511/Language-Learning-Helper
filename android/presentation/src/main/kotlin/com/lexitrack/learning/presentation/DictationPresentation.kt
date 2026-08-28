package com.lexitrack.learning.presentation

import com.lexitrack.learning.application.TAG_EVALUATED
import com.lexitrack.learning.domain.DictationDocument
import com.lexitrack.learning.domain.VocabularyEntry
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
