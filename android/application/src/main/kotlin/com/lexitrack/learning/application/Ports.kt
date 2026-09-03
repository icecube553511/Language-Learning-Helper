package com.lexitrack.learning.application

import com.lexitrack.learning.domain.ImportReport
import com.lexitrack.learning.domain.LearntWord
import com.lexitrack.learning.domain.ReviewEvent
import com.lexitrack.learning.domain.ScheduleState
import com.lexitrack.learning.domain.VocabularyEntry
import com.lexitrack.learning.domain.DictationDocument
import com.lexitrack.learning.domain.MarkMode
import com.lexitrack.learning.domain.DictationFormat
import com.lexitrack.learning.domain.PetVitals
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
    val fontScale: Float = DEFAULT_FONT_SCALE,
    val reviewBatchSize: Int = DEFAULT_REVIEW_BATCH_SIZE,
    val studyOrder: String = STUDY_ORDER_RANDOM,
    val studyLevels: Set<String> = emptySet(),
    val reviewLevels: Set<String> = emptySet(),
    val reminderLevels: Set<String> = emptySet(),
    val reminderEnabled: Boolean = false,
    val reminderIntervalMinutes: Float = DEFAULT_REMINDER_INTERVAL_MINUTES,
    val markMode: MarkMode = MarkMode.ASK,
)

const val DEFAULT_REVIEW_BATCH_SIZE = 20
const val DEFAULT_FONT_SCALE = 1.0f
const val MIN_FONT_SCALE = 0.9f
const val MAX_FONT_SCALE = 1.4f
const val STUDY_ORDER_ALPHABETICAL = "alphabetical"
const val STUDY_ORDER_RANDOM = "random"
val SUPPORTED_VOCABULARY_LEVELS = setOf("CET4", "CET6", "CUSTOM")
const val DEFAULT_REMINDER_INTERVAL_MINUTES = 30.0f
const val MIN_REMINDER_INTERVAL_MINUTES = 0.5f
const val MAX_REMINDER_INTERVAL_MINUTES = 120.0f

/**
 * Keep persisted and transient font settings safe for Compose text layout.
 * Float.coerceIn leaves NaN unchanged, which would produce an invalid TextUnit.
 */
fun sanitizeFontScale(scale: Float): Float =
    if (scale.isFinite()) scale.coerceIn(MIN_FONT_SCALE, MAX_FONT_SCALE) else DEFAULT_FONT_SCALE

interface VocabularyRepository {
    val words: StateFlow<List<VocabularyEntry>>
    val status: StateFlow<CatalogStatus>

    suspend fun initialize()
    suspend fun importCsv(input: InputStream): ImportReport
    suspend fun updateLabels(wordIds: Set<String>, levels: Set<String>, tags: Set<String>): Int

    suspend fun updateTags(wordIds: Set<String>, add: Set<String>, remove: Set<String>): Int = 0
}

/** Opaque token owned and interpreted only by a ReviewRepository adapter. */
interface ReviewSavepoint

interface ReviewRepository {
    val schedules: StateFlow<Map<String, ScheduleState>>
    val history: StateFlow<List<ReviewEvent>>

    suspend fun saveReview(wordId: String, state: ScheduleState, event: ReviewEvent): ReviewSavepoint
    suspend fun rollbackReview(savepoint: ReviewSavepoint)
}

interface LearntWordsRepository {
    val learntWords: StateFlow<Map<String, LearntWord>>
    val petVitals: StateFlow<PetVitals>

    suspend fun saveLearntWords(words: Collection<LearntWord>)
    suspend fun saveLearningOutcome(word: LearntWord, vitals: PetVitals)
}

interface SettingsRepository {
    val settings: StateFlow<UserSettings>

    suspend fun setFontScale(scale: Float)
    suspend fun setReviewBatchSize(count: Int)
    suspend fun setStudyOrder(order: String)
    suspend fun setStudyLevels(levels: Set<String>)
    suspend fun setReviewLevels(levels: Set<String>)
    suspend fun setReminderLevels(levels: Set<String>)
    suspend fun setReminderEnabled(enabled: Boolean)
    suspend fun setReminderIntervalMinutes(minutes: Float)
    suspend fun setMarkMode(mode: MarkMode) = Unit
}

interface DictationExporter {
    fun export(document: DictationDocument, format: DictationFormat): ExportedDictation
}

data class ExportedDictation(val bytes: ByteArray, val fileName: String, val mimeType: String)

interface TimeProvider {
    fun nowUtcSeconds(): Double
    fun localDate(epochSeconds: Double): LocalDate
}
