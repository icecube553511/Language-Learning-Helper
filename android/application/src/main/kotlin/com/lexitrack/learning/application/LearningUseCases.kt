package com.lexitrack.learning.application

import com.lexitrack.learning.domain.ImportReport
import com.lexitrack.learning.domain.LexiSm2Scheduler
import com.lexitrack.learning.domain.ReviewEvent
import com.lexitrack.learning.domain.ReviewRating
import com.lexitrack.learning.domain.ScheduleState
import com.lexitrack.learning.domain.VocabularyEntry
import java.io.ByteArrayInputStream
import java.time.LocalDate
import kotlinx.coroutines.flow.StateFlow

data class DashboardSnapshot(
    val totalWords: Int,
    val dueNow: Int,
    val newWords: Int,
    val mastered: Int,
    val reviewedToday: Int,
)

data class ForecastDay(
    val date: LocalDate,
    val count: Int,
)

class InitializeAppUseCase(
    private val vocabulary: VocabularyRepository,
) {
    suspend operator fun invoke() = vocabulary.initialize()
}

class GetNextCardUseCase(
    private val vocabulary: VocabularyRepository,
    private val reviews: ReviewRepository,
    private val time: TimeProvider,
) {
    operator fun invoke(): VocabularyEntry? {
        val now = time.nowUtcSeconds()
        return vocabulary.words.value
            .asSequence()
            .filter { entry -> (reviews.schedules.value[entry.id]?.dueAtUtc ?: 0.0) <= now }
            .sortedWith(
                compareBy<VocabularyEntry> { entry ->
                    reviews.schedules.value[entry.id]?.let { 0 } ?: 1
                }.thenBy { entry -> reviews.schedules.value[entry.id]?.dueAtUtc ?: 0.0 }
                    .thenBy { entry -> entry.word.lowercase() },
            )
            .firstOrNull()
    }
}

class RateWordUseCase(
    private val reviews: ReviewRepository,
    private val time: TimeProvider,
) {
    suspend operator fun invoke(wordId: String, rating: ReviewRating): ScheduleState {
        val reviewedAt = time.nowUtcSeconds()
        val next = LexiSm2Scheduler.review(
            current = reviews.schedules.value[wordId] ?: ScheduleState.Initial,
            rating = rating,
            reviewedAtUtc = reviewedAt,
        )
        reviews.saveReview(
            wordId = wordId,
            state = next,
            event = ReviewEvent(wordId, reviewedAt, rating, next.intervalDays),
        )
        return next
    }
}

class SearchVocabularyUseCase(
    private val vocabulary: VocabularyRepository,
) {
    operator fun invoke(query: String): List<VocabularyEntry> {
        val needle = query.trim().lowercase()
        if (needle.isEmpty()) return vocabulary.words.value
        return vocabulary.words.value.filter { entry ->
            entry.word.lowercase().contains(needle) ||
                entry.meaning.lowercase().contains(needle) ||
                entry.tags.any { it.lowercase().contains(needle) }
        }
    }
}

class ImportVocabularyUseCase(
    private val vocabulary: VocabularyRepository,
) {
    suspend operator fun invoke(bytes: ByteArray): ImportReport =
        vocabulary.importCsv(ByteArrayInputStream(bytes))
}

class UpdateFontScaleUseCase(
    private val settings: SettingsRepository,
) {
    suspend operator fun invoke(scale: Float) {
        settings.setFontScale(scale.coerceIn(0.9f, 1.4f))
    }
}

class BuildDashboardUseCase(
    private val vocabulary: VocabularyRepository,
    private val reviews: ReviewRepository,
    private val time: TimeProvider,
) {
    operator fun invoke(): DashboardSnapshot {
        val now = time.nowUtcSeconds()
        val today = time.localDate(now)
        val schedules = reviews.schedules.value
        return DashboardSnapshot(
            totalWords = vocabulary.words.value.size,
            dueNow = vocabulary.words.value.count { entry ->
                schedules[entry.id]?.dueAtUtc?.let { it <= now } == true
            },
            newWords = vocabulary.words.value.count { it.id !in schedules },
            mastered = schedules.values.count { it.repetitions >= 5 },
            reviewedToday = reviews.history.value
                .asSequence()
                .filter { time.localDate(it.reviewedAtUtc) == today }
                .map { it.wordId }
                .distinct()
                .count(),
        )
    }
}

class BuildForecastUseCase(
    private val vocabulary: VocabularyRepository,
    private val reviews: ReviewRepository,
    private val time: TimeProvider,
) {
    operator fun invoke(days: Int = 7): List<ForecastDay> {
        val now = time.nowUtcSeconds()
        val today = time.localDate(now)
        val counts = IntArray(days)
        vocabulary.words.value.forEach { entry ->
            val schedule = reviews.schedules.value[entry.id] ?: return@forEach
            val dueDate = time.localDate(schedule.dueAtUtc)
            val offset = (dueDate.toEpochDay() - today.toEpochDay()).coerceAtLeast(0).toInt()
            if (offset in counts.indices) counts[offset] += 1
        }
        return counts.mapIndexed { index, count -> ForecastDay(today.plusDays(index.toLong()), count) }
    }
}

data class AppUseCases(
    val initialize: InitializeAppUseCase,
    val nextCard: GetNextCardUseCase,
    val rateWord: RateWordUseCase,
    val search: SearchVocabularyUseCase,
    val importVocabulary: ImportVocabularyUseCase,
    val updateFontScale: UpdateFontScaleUseCase,
    val dashboard: BuildDashboardUseCase,
    val forecast: BuildForecastUseCase,
    val words: StateFlow<List<VocabularyEntry>>,
    val catalogStatus: StateFlow<CatalogStatus>,
    val schedules: StateFlow<Map<String, ScheduleState>>,
    val history: StateFlow<List<ReviewEvent>>,
    val settings: StateFlow<UserSettings>,
)
