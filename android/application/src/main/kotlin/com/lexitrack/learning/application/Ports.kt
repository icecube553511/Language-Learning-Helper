package com.lexitrack.learning.application

import com.lexitrack.learning.domain.ImportReport
import com.lexitrack.learning.domain.LearntWord
import com.lexitrack.learning.domain.ReviewEvent
import com.lexitrack.learning.domain.ScheduleState
import com.lexitrack.learning.domain.VocabularyEntry
import java.io.InputStream
import java.time.LocalDate
import kotlinx.coroutines.flow.StateFlow

data class CatalogStatus(
    val loading: Boolean = true,
    val message: String = "正在加载词库",
    val acceptedEntries: Int = 0,
    val rejectedEntries: Int = 0,
)

data class UserSettings(
    val fontScale: Float = 1.0f,
    val reviewBatchSize: Int = DEFAULT_REVIEW_BATCH_SIZE,
    val studyOrder: String = STUDY_ORDER_RANDOM,
    val studyLevels: Set<String> = emptySet(),
    val reviewLevels: Set<String> = emptySet(),
    val reminderEnabled: Boolean = false,
    val reminderIntervalMinutes: Float = DEFAULT_REMINDER_INTERVAL_MINUTES,
)

const val DEFAULT_REVIEW_BATCH_SIZE = 20
const val STUDY_ORDER_ALPHABETICAL = "alphabetical"
const val STUDY_ORDER_RANDOM = "random"
const val DEFAULT_REMINDER_INTERVAL_MINUTES = 30.0f
const val MIN_REMINDER_INTERVAL_MINUTES = 0.5f
const val MAX_REMINDER_INTERVAL_MINUTES = 120.0f

interface VocabularyRepository {
    val words: StateFlow<List<VocabularyEntry>>
    val status: StateFlow<CatalogStatus>

    suspend fun initialize()
    suspend fun importCsv(input: InputStream): ImportReport
    suspend fun updateLabels(wordIds: Set<String>, levels: Set<String>, tags: Set<String>): Int
}

interface ReviewRepository {
    val schedules: StateFlow<Map<String, ScheduleState>>
    val history: StateFlow<List<ReviewEvent>>

    suspend fun saveReview(wordId: String, state: ScheduleState, event: ReviewEvent)
}

interface LearntWordsRepository {
    val learntWords: StateFlow<Map<String, LearntWord>>

    suspend fun saveLearntWords(words: Collection<LearntWord>)
}

interface SettingsRepository {
    val settings: StateFlow<UserSettings>

    suspend fun setFontScale(scale: Float)
    suspend fun setReviewBatchSize(count: Int)
    suspend fun setStudyOrder(order: String)
    suspend fun setStudyLevels(levels: Set<String>)
    suspend fun setReviewLevels(levels: Set<String>)
    suspend fun setReminderEnabled(enabled: Boolean)
    suspend fun setReminderIntervalMinutes(minutes: Float)
}

interface TimeProvider {
    fun nowUtcSeconds(): Double
    fun localDate(epochSeconds: Double): LocalDate
}
