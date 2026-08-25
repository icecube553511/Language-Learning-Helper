package com.lexitrack.learning.infrastructure

import android.content.Context
import com.lexitrack.learning.application.LearntWordsRepository
import com.lexitrack.learning.domain.LearntWord
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.put

class AndroidLearntWordsRepository(context: Context) : LearntWordsRepository {
    private val preferences = context.applicationContext
        .getSharedPreferences(PREFERENCES_NAME, Context.MODE_PRIVATE)
    private val mutex = Mutex()
    private val _learntWords = MutableStateFlow(loadLearntWords())

    override val learntWords: StateFlow<Map<String, LearntWord>> = _learntWords.asStateFlow()

    override suspend fun saveLearntWords(words: Collection<LearntWord>) {
        if (words.isEmpty()) return
        mutex.withLock {
            _learntWords.value = _learntWords.value + words.associateBy { it.wordId }
            preferences.edit()
                .putString(KEY_WORDS, encodeLearntWords(_learntWords.value))
                .apply()
        }
    }

    private fun loadLearntWords(): Map<String, LearntWord> = runCatching {
        val text = preferences.getString(KEY_WORDS, null) ?: return@runCatching emptyMap()
        Json.parseToJsonElement(text).jsonObject.mapNotNull { (wordId, element) ->
            runCatching {
                val value = element.jsonObject
                val learntAtUtc = value.double("learntAtUtc")
                wordId to LearntWord(
                    wordId = value.string("wordId", wordId),
                    weight = value.double("weight"),
                    learntAtUtc = learntAtUtc,
                    lastReviewedAtUtc = value.double("lastReviewedAtUtc", learntAtUtc),
                    reviewCount = value.int("reviewCount", 0),
                )
            }.getOrNull()
        }.toMap()
    }.getOrDefault(emptyMap())

    private fun encodeLearntWords(words: Map<String, LearntWord>): String = buildJsonObject {
        words.toSortedMap().forEach { (wordId, word) ->
            put(wordId, buildJsonObject {
                put("wordId", word.wordId)
                put("weight", word.weight)
                put("learntAtUtc", word.learntAtUtc)
                put("lastReviewedAtUtc", word.lastReviewedAtUtc)
                put("reviewCount", word.reviewCount)
            })
        }
    }.toString()

    private fun JsonObject.string(key: String, fallback: String = ""): String =
        (this[key] as? JsonPrimitive)?.contentOrNull ?: fallback

    private fun JsonObject.double(key: String, fallback: Double? = null): Double =
        (this[key] as? JsonPrimitive)?.doubleOrNull ?: requireNotNull(fallback) {
            "Missing or invalid $key"
        }

    private fun JsonObject.int(key: String, fallback: Int): Int =
        (this[key] as? JsonPrimitive)?.intOrNull ?: fallback

    companion object {
        const val PREFERENCES_NAME = "Words_Learnt"
        internal const val KEY_WORDS = "words"
    }
}
