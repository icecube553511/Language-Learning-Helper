package com.lexitrack.learning.domain

import java.text.Normalizer
import java.util.Locale

data class BilingualExample(
    val english: String,
    val chinese: String,
    val source: String = "",
) {
    init {
        require(english.isNotBlank()) { "English example cannot be blank" }
        require(chinese.isNotBlank()) { "Chinese translation cannot be blank" }
    }
}

data class VocabularyEntry(
    val id: String,
    val word: String,
    val meaning: String,
    val phonetic: String = "",
    val levels: Set<String> = setOf("custom"),
    val tags: Set<String> = emptySet(),
    val mnemonic: String = "",
    val examples: List<BilingualExample>,
    val source: String = "catalog",
) {
    init {
        require(id.isNotBlank()) { "Vocabulary id cannot be blank" }
        require(word.isNotBlank()) { "Word cannot be blank" }
        require(meaning.isNotBlank()) { "Meaning cannot be blank" }
        require(examples.size >= MINIMUM_EXAMPLES) {
            "Every learnable word must have at least $MINIMUM_EXAMPLES bilingual examples"
        }
    }

    companion object {
        const val MINIMUM_EXAMPLES = 3
    }
}

fun normalizeWordId(word: String): String = Normalizer
    .normalize(word.trim(), Normalizer.Form.NFKC)
    .lowercase(Locale.ROOT)
