package com.lexitrack.learning.infrastructure

import android.content.Context
import com.lexitrack.learning.application.LearntWordsRepository
import com.lexitrack.learning.domain.LearntWord
import com.lexitrack.learning.domain.Mood
import com.lexitrack.learning.domain.PetVitals
import com.lexitrack.learning.domain.ReviewRecoveryTag
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.put

class AndroidLearntWordsRepository(
    context: Context,
    private val ioDispatcher: CoroutineDispatcher = Dispatchers.IO,
) : LearntWordsRepository {
    private val preferences = context.applicationContext
        .getSharedPreferences(PREFERENCES_NAME, Context.MODE_PRIVATE)
    private val mutex = Mutex()
    private val _learntWords = MutableStateFlow(loadLearntWords())
    private val _petVitals = MutableStateFlow(loadPetVitals())

    override val learntWords: StateFlow<Map<String, LearntWord>> = _learntWords.asStateFlow()
    override val petVitals: StateFlow<PetVitals> = _petVitals.asStateFlow()

    override suspend fun saveLearntWords(words: Collection<LearntWord>) {
        if (words.isEmpty()) return
        mutex.withLock {
            // Once commit starts, cancellation waits until the matching flow
            // state is published so memory and disk cannot diverge.
            withContext(NonCancellable) {
                val nextWords = _learntWords.value + words.associateBy { it.wordId }
                check(
                    withContext(ioDispatcher) {
                        preferences.edit()
                            .putString(KEY_WORDS, encodeLearntWords(nextWords))
                            .commit()
                    },
                ) { "Unable to persist learnt words" }
                _learntWords.value = nextWords
            }
        }
    }

    override suspend fun saveLearningOutcome(word: LearntWord, vitals: PetVitals) {
        mutex.withLock {
            withContext(NonCancellable) {
                val nextWords = _learntWords.value + (word.wordId to word)
                check(
                    withContext(ioDispatcher) {
                        preferences.edit()
                            .putString(KEY_WORDS, encodeLearntWords(nextWords))
                            .putString(KEY_PET_VITALS, encodePetVitals(vitals))
                            .commit()
                    },
                ) { "Unable to persist learning outcome" }
                _learntWords.value = nextWords
                _petVitals.value = vitals
            }
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
                    reviewRecoveryTag = value.reviewRecoveryTag(),
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
                word.reviewRecoveryTag?.let { put("reviewRecoveryTag", it.persistedValue) }
            })
        }
    }.toString()

    private fun loadPetVitals(): PetVitals = runCatching {
        val text = preferences.getString(KEY_PET_VITALS, null) ?: return@runCatching PetVitals.Default
        val value = Json.parseToJsonElement(text).jsonObject
        PetVitals.restore(
            satiety = value.optionalDouble("satiety"),
            foodReserve = value.optionalDouble("foodReserve"),
            mood = Mood.fromPersisted(value.string("mood", Mood.CALM.persistedValue)),
        )
    }.getOrDefault(PetVitals.Default)

    private fun encodePetVitals(vitals: PetVitals): String = buildJsonObject {
        put("satiety", vitals.satiety)
        // Keep the v1 wire shape scalar even though the domain composes FoodJar.
        put("foodReserve", vitals.foodJar.storedSatiety)
        put("mood", vitals.mood.persistedValue)
    }.toString()

    private fun JsonObject.string(key: String, fallback: String = ""): String =
        (this[key] as? JsonPrimitive)?.contentOrNull ?: fallback

    private fun JsonObject.double(key: String, fallback: Double? = null): Double =
        (this[key] as? JsonPrimitive)?.doubleOrNull ?: requireNotNull(fallback) {
            "Missing or invalid $key"
        }

    private fun JsonObject.int(key: String, fallback: Int): Int =
        (this[key] as? JsonPrimitive)?.intOrNull ?: fallback

    private fun JsonObject.optionalDouble(key: String): Double? =
        (this[key] as? JsonPrimitive)?.doubleOrNull

    private fun JsonObject.reviewRecoveryTag(): ReviewRecoveryTag? {
        val persistedValues = buildList {
            listOf("reviewRecoveryTag", "reviewRecoveryTags", "temporaryReviewTags").forEach { key ->
                this@reviewRecoveryTag[key]?.collectStrings(this)
            }
        }
        return ReviewRecoveryTag.decodePersisted(persistedValues)
    }

    private fun JsonElement.collectStrings(destination: MutableList<String>) {
        when (this) {
            is JsonPrimitive -> contentOrNull?.let(destination::add)
            is JsonArray -> forEach { it.collectStrings(destination) }
            is JsonObject -> forEach { (key, value) ->
                val isMarker = key == ReviewRecoveryTag.FORGOT.persistedValue ||
                    key == ReviewRecoveryTag.VAGUE.persistedValue
                if (isMarker && (value as? JsonPrimitive)?.booleanOrNull == true) {
                    destination += key
                } else {
                    value.collectStrings(destination)
                }
            }
        }
    }

    companion object {
        const val PREFERENCES_NAME = "Words_Learnt"
        internal const val KEY_WORDS = "words"
        internal const val KEY_PET_VITALS = "petVitals"
    }
}
