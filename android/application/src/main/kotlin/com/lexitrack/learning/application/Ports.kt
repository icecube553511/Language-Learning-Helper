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
)

const val DEFAULT_REVIEW_BATCH_SIZE = 20

interface VocabularyRepository {
    val words: StateFlow<List<VocabularyEntry>>
    val status: StateFlow<CatalogStatus>

    suspend fun initialize()
    suspend fun importCsv(input: InputStream): ImportReport
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
}

interface TimeProvider {
    fun nowUtcSeconds(): Double
    fun localDate(epochSeconds: Double): LocalDate
}
