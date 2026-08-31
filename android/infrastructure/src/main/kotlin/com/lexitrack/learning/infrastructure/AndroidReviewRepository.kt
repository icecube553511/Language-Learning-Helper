package com.lexitrack.learning.infrastructure

import android.content.Context
import com.lexitrack.learning.application.ReviewRepository
import com.lexitrack.learning.application.ReviewSavepoint
import com.lexitrack.learning.domain.CardPhase
import com.lexitrack.learning.domain.ReviewEvent
import com.lexitrack.learning.domain.ReviewRating
import com.lexitrack.learning.domain.ScheduleState
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
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.put

class AndroidReviewRepository(
    context: Context,
    private val ioDispatcher: CoroutineDispatcher = Dispatchers.IO,
) : ReviewRepository {
    private val preferences = context.applicationContext
        .getSharedPreferences(PREFERENCES_NAME, Context.MODE_PRIVATE)
    private val mutex = Mutex()
    private val savepointOwner = Any()
    private val _schedules = MutableStateFlow(loadSchedules())
    private val _history = MutableStateFlow(loadHistory())

    override val schedules: StateFlow<Map<String, ScheduleState>> = _schedules.asStateFlow()
    override val history: StateFlow<List<ReviewEvent>> = _history.asStateFlow()

    override suspend fun saveReview(
        wordId: String,
        state: ScheduleState,
        event: ReviewEvent,
    ): ReviewSavepoint = mutex.withLock {
        // SharedPreferences.commit() cannot be cancelled once it starts. Keep
        // the matching flow publication and savepoint creation in that boundary.
        withContext(NonCancellable) {
            val previousSchedules = _schedules.value
            val previousHistory = _history.value
            val nextSchedules = previousSchedules + (wordId to state)
            val nextHistory = (previousHistory + event).takeLast(MAX_HISTORY)
            persist(nextSchedules, nextHistory, "Unable to persist review")
            _schedules.value = nextSchedules
            _history.value = nextHistory
            AndroidReviewSavepoint(
                owner = savepointOwner,
                previousSchedules = previousSchedules,
                previousHistory = previousHistory,
                savedSchedules = nextSchedules,
                savedHistory = nextHistory,
            )
        }
    }

    override suspend fun rollbackReview(savepoint: ReviewSavepoint) {
        val owned = savepoint as? AndroidReviewSavepoint
            ?: throw IllegalArgumentException("Review savepoint belongs to another adapter")
        require(owned.owner === savepointOwner) {
            "Review savepoint belongs to another repository instance"
        }
        mutex.withLock {
            withContext(NonCancellable) {
                check(_schedules.value == owned.savedSchedules && _history.value == owned.savedHistory) {
                    "Review savepoint is stale and cannot replace a newer review"
                }
                persist(owned.previousSchedules, owned.previousHistory, "Unable to roll back review")
                _schedules.value = owned.previousSchedules
                _history.value = owned.previousHistory
            }
        }
    }

    private suspend fun persist(
        schedules: Map<String, ScheduleState>,
        history: List<ReviewEvent>,
        errorMessage: String,
    ) {
        check(
            withContext(ioDispatcher) {
                preferences.edit()
                    .putString(KEY_SCHEDULES, encodeSchedules(schedules))
                    .putString(KEY_HISTORY, encodeHistory(history))
                    .commit()
            },
        ) { errorMessage }
    }

    private fun loadSchedules(): Map<String, ScheduleState> = runCatching {
        val text = preferences.getString(KEY_SCHEDULES, null) ?: return@runCatching emptyMap()
        val root = Json.parseToJsonElement(text).jsonObject
        root.mapValues { (_, element) ->
            val value = element.jsonObject
            ScheduleState(
                phase = CardPhase.fromContractName(value.string("phase", "new")),
                intervalDays = value.double("intervalDays", 0.0),
                ease = value.double("ease", 2.5),
                repetitions = value.int("repetitions", 0),
                lapses = value.int("lapses", 0),
                dueAtUtc = value.double("dueAtUtc", 0.0),
                lastReviewedAtUtc = value["lastReviewedAtUtc"]?.jsonPrimitive?.doubleOrNull,
            )
        }
    }.getOrDefault(emptyMap())

    private fun loadHistory(): List<ReviewEvent> = runCatching {
        val text = preferences.getString(KEY_HISTORY, null) ?: return@runCatching emptyList()
        Json.parseToJsonElement(text).jsonArray.map { element ->
            val value = element.jsonObject
            ReviewEvent(
                wordId = value.string("wordId"),
                reviewedAtUtc = value.double("reviewedAtUtc", 0.0),
                rating = ReviewRating.fromContractName(value.string("rating", "good")),
                resultingIntervalDays = value.double("resultingIntervalDays", 0.0),
            )
        }
    }.getOrDefault(emptyList())

    private fun encodeSchedules(states: Map<String, ScheduleState>): String = buildJsonObject {
        states.forEach { (wordId, state) ->
            put(wordId, buildJsonObject {
                put("phase", state.phase.contractName)
                put("intervalDays", state.intervalDays)
                put("ease", state.ease)
                put("repetitions", state.repetitions)
                put("lapses", state.lapses)
                put("dueAtUtc", state.dueAtUtc)
                state.lastReviewedAtUtc?.let { put("lastReviewedAtUtc", it) }
            })
        }
    }.toString()

    private fun encodeHistory(events: List<ReviewEvent>): String = buildJsonArray {
        events.forEach { event ->
            add(buildJsonObject {
                put("wordId", event.wordId)
                put("reviewedAtUtc", event.reviewedAtUtc)
                put("rating", event.rating.contractName)
                put("resultingIntervalDays", event.resultingIntervalDays)
            })
        }
    }.toString()

    private fun JsonObject.string(key: String, fallback: String = ""): String =
        (this[key] as? JsonPrimitive)?.contentOrNull ?: fallback

    private fun JsonObject.double(key: String, fallback: Double): Double =
        (this[key] as? JsonPrimitive)?.doubleOrNull ?: fallback

    private fun JsonObject.int(key: String, fallback: Int): Int =
        (this[key] as? JsonPrimitive)?.intOrNull ?: fallback

    private data class AndroidReviewSavepoint(
        val owner: Any,
        val previousSchedules: Map<String, ScheduleState>,
        val previousHistory: List<ReviewEvent>,
        val savedSchedules: Map<String, ScheduleState>,
        val savedHistory: List<ReviewEvent>,
    ) : ReviewSavepoint

    companion object {
        internal const val PREFERENCES_NAME = "lexitrack_reviews"
        internal const val KEY_SCHEDULES = "schedules"
        internal const val KEY_HISTORY = "history"
        const val MAX_HISTORY = 2_000
    }
}
