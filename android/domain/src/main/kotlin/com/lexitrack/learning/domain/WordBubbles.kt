package com.lexitrack.learning.domain

import kotlin.math.min

const val MAX_BUBBLE_DEPTH = 20
const val FALLBACK_EXAMPLE_ZH = "（暂无中文释义）"

data class WordToken(val text: String, val start: Int, val end: Int) {
    val wordId: String get() = normalizeWordId(text)
}

private val englishTokenPattern = Regex("[A-Za-z]+(?:['\\u2019][A-Za-z]+|['\\u2019])?")

fun tokenizeEnglish(text: String): List<WordToken> = englishTokenPattern.findAll(text).map { match ->
    WordToken(match.value, match.range.first, match.range.last + 1)
}.toList()

data class BubbleDefinition(
    val wordId: String,
    val word: String,
    val phonetic: String = "",
    val partOfSpeech: String,
    val meaning: String,
    val examples: List<String>,
    val examplePairs: List<Pair<String, String>> = emptyList(),
    val known: Boolean = true,
)

fun resolveBubbleDefinition(
    entries: Iterable<VocabularyEntry>,
    token: String,
    contextExample: String = "",
): BubbleDefinition {
    val normalized = normalizeWordId(token)
    val entry = entries.firstOrNull { it.id == normalized }
    if (entry == null) {
        val context = contextExample.trim()
        return BubbleDefinition(
            wordId = normalized,
            word = token,
            partOfSpeech = "未收录",
            meaning = "词库暂无中文释义",
            examples = if (context.isEmpty()) emptyList() else listOf(context),
            examplePairs = if (context.isEmpty()) emptyList() else listOf(context to FALLBACK_EXAMPLE_ZH),
            known = false,
        )
    }
    val parsed = parseMeaning(entry.meaning)
    return BubbleDefinition(
        wordId = entry.id,
        word = entry.word,
        phonetic = entry.phonetic,
        partOfSpeech = parsed.partOfSpeech.ifBlank { "未标注" },
        meaning = parsed.chineseMeaning.ifBlank { entry.meaning },
        examples = entry.examples.take(3).map { it.english },
        examplePairs = entry.examples.take(3).map {
            it.english to it.chinese.ifBlank { FALLBACK_EXAMPLE_ZH }
        },
    )
}

data class BubbleFrame(val definition: BubbleDefinition, val parentDepth: Int)

data class BubbleStack(val frames: List<BubbleFrame> = emptyList()) {
    fun openRoot(definition: BubbleDefinition): BubbleStack =
        BubbleStack(listOf(BubbleFrame(definition, -1)))

    fun openChild(parentDepth: Int, definition: BubbleDefinition): BubbleStack {
        val prefix = when {
            parentDepth < 0 -> emptyList()
            parentDepth >= frames.size -> return this
            else -> frames.take(parentDepth + 1)
        }
        if (prefix.size >= MAX_BUBBLE_DEPTH) return this
        return BubbleStack(prefix + BubbleFrame(definition, parentDepth))
    }

    fun closeAfter(depth: Int): BubbleStack = when {
        depth < 0 -> BubbleStack()
        else -> BubbleStack(frames.take(min(depth + 1, frames.size)))
    }

    /** Remove the bubble at [depth] and all descendants, keeping ancestors.
     *
     * This is the explicit-dismiss transition: a non-root bubble returns to its
     * parent, while dismissing the root clears the whole stack.
     */
    fun closeBubble(depth: Int): BubbleStack = when {
        depth <= 0 -> BubbleStack()
        else -> BubbleStack(frames.take(depth))
    }

    fun closeAll(): BubbleStack = BubbleStack()
}
