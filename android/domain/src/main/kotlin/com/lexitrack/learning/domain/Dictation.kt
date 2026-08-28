package com.lexitrack.learning.domain

import kotlin.math.ceil

enum class DictationFormat { DOCX, PDF }

enum class DictationMissingField { WORD, PART_OF_SPEECH, MEANING }

enum class MarkMode { ASK, ALWAYS, NEVER }

data class DictationDocumentOptions(
    val formats: Set<DictationFormat> = setOf(DictationFormat.DOCX, DictationFormat.PDF),
    val fontSizePt: Int = 12,
    val paperWidthPt: Int = 595,
    val paperHeightPt: Int = 842,
    val missingFields: Set<DictationMissingField> = setOf(DictationMissingField.WORD),
    val showInitial: Boolean = false,
    val includeExamples: Boolean = false,
    val customExamples: Map<String, String> = emptyMap(),
) {
    init {
        require(formats.isNotEmpty()) { "至少选择一种导出格式" }
        require(missingFields.isNotEmpty()) { "至少选择一个缺失字段" }
        require(fontSizePt in 8..24) { "字号必须在 8 到 24 pt 之间" }
        require(paperWidthPt == 595 && paperHeightPt == 842) { "默写文档必须使用 A4 尺寸" }
    }
}

data class DictationRow(
    val word: String,
    val partOfSpeech: String,
    val meaning: String,
    val examples: List<String> = emptyList(),
) {
    companion object
}

data class DictationDocument(val rows: List<DictationRow>, val options: DictationDocumentOptions)

fun blankCount(word: String): Int {
    val trimmed = word.trim()
    return ceil(trimmed.codePointCount(0, trimmed.length) * 1.8).toInt()
}

fun wordPrompt(word: String, showInitial: Boolean): String {
    val trimmed = word.trim()
    val length = trimmed.codePointCount(0, trimmed.length)
    if (!showInitial || length == 0) return "_".repeat(blankCount(trimmed))
    val firstEnd = trimmed.offsetByCodePoints(0, 1)
    val remainingBlankCount = ceil((length - 1) * 1.8).toInt()
    return trimmed.substring(0, firstEnd) + if (remainingBlankCount == 0) "" else " " + "_".repeat(remainingBlankCount)
}

private val partOfSpeechPattern = Regex(
    "(?i)(?<![A-Za-z0-9])(?:interj|abbr|prep|pron|conj|adj|adv|aux|num|art|vt|vi|n|v|a)\\.?(?![A-Za-z0-9])",
)

data class ParsedMeaning(val partOfSpeech: String, val chineseMeaning: String)

fun parseMeaning(meaning: String): ParsedMeaning {
    val matches = partOfSpeechPattern.findAll(meaning)
        .map { it.value.lowercase().removeSuffix(".") }
        .distinct()
        .toList()
    val chinese = meaning.replace(partOfSpeechPattern, " ")
        .replace(Regex("\\s+"), " ")
        .trim()
    return ParsedMeaning(matches.joinToString(" / "), chinese)
}

fun clozeExample(sentence: String, targetWord: String, showInitial: Boolean = false): String {
    val target = targetWord.trim()
    if (target.isBlank()) return sentence
    val escaped = Regex.escape(target)
    return sentence.replace(
        Regex("(?i)(?<![A-Za-z0-9])$escaped(?![A-Za-z0-9])"),
        "_".repeat(blankCount(target)),
    )
}

fun selectDictationExample(entry: VocabularyEntry, customExample: String? = null): String? {
    customExample?.trim()?.takeIf(String::isNotEmpty)?.let { return it }
    val boundary = Regex("(?i)(?<![A-Za-z0-9])${Regex.escape(entry.word.trim())}(?![A-Za-z0-9])")
    return entry.examples.asSequence().map { it.english.trim() }.filter(String::isNotEmpty).firstOrNull { boundary.containsMatchIn(it) }
        ?: entry.examples.asSequence().map { it.english.trim() }.firstOrNull(String::isNotEmpty)
}

fun DictationRow.Companion.fromEntry(
    entry: VocabularyEntry,
    options: DictationDocumentOptions,
): DictationRow {
    val parsed = parseMeaning(entry.meaning)
    val examples = if (!options.includeExamples) emptyList() else {
        selectDictationExample(entry, options.customExamples[entry.id])?.let(::listOf) ?: emptyList()
    }.map { example ->
        if (DictationMissingField.WORD in options.missingFields) {
            clozeExample(example, entry.word, options.showInitial)
        } else {
            example
        }
    }
    return DictationRow(
        word = if (DictationMissingField.WORD in options.missingFields) wordPrompt(entry.word, options.showInitial) else entry.word,
        partOfSpeech = if (DictationMissingField.PART_OF_SPEECH in options.missingFields) {
            "_".repeat(blankCount(parsed.partOfSpeech))
        } else parsed.partOfSpeech,
        meaning = if (DictationMissingField.MEANING in options.missingFields) {
            "_".repeat(blankCount(parsed.chineseMeaning))
        } else parsed.chineseMeaning,
        examples = examples,
    )
}
