package com.lexitrack.learning.application

import com.lexitrack.learning.domain.ImportReport
import com.lexitrack.learning.domain.LearntWord
import com.lexitrack.learning.domain.LearntWordWeights
import com.lexitrack.learning.domain.LexiSm2Scheduler
import com.lexitrack.learning.domain.ReviewEvent
import com.lexitrack.learning.domain.ReviewRating
import com.lexitrack.learning.domain.ScheduleState
import com.lexitrack.learning.domain.VocabularyEntry
import com.lexitrack.learning.domain.BubbleDefinition
import com.lexitrack.learning.domain.resolveBubbleDefinition
import com.lexitrack.learning.domain.initialWeightFor
import com.lexitrack.learning.domain.updatedWeightForReview
import java.io.ByteArrayInputStream
import java.time.LocalDate
import kotlinx.coroutines.flow.StateFlow
import kotlin.random.Random

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
    private val reviews: ReviewRepository,
    private val learntWords: LearntWordsRepository,
) {
    suspend operator fun invoke() {
        vocabulary.initialize()
        val known = learntWords.learntWords.value.keys
        val legacy = reviews.schedules.value.mapNotNull { (wordId, state) ->
            val reviewedAt = state.lastReviewedAtUtc ?: return@mapNotNull null
            if (wordId in known) return@mapNotNull null
            LearntWord(
                wordId = wordId,
                weight = LearntWordWeights.LEGACY_DEFAULT,
                learntAtUtc = reviewedAt,
                lastReviewedAtUtc = reviewedAt,
            )
        }
        if (legacy.isNotEmpty()) learntWords.saveLearntWords(legacy)
    }
}

class GetNextCardUseCase(
    private val vocabulary: VocabularyRepository,
    private val learntWords: LearntWordsRepository,
    private val settings: SettingsRepository,
    private val randomUnit: () -> Double = { Random.Default.nextDouble() },
) {
    operator fun invoke(): VocabularyEntry? {
        val learntIds = learntWords.learntWords.value.keys
        val candidates = vocabulary.words.value
            .asSequence()
            .filter { it.id !in learntIds }
            .filter { entry ->
                settings.settings.value.studyLevels.isEmpty() ||
                    entry.levels.any { it.uppercase() in settings.settings.value.studyLevels }
            }
            .toList()
        if (candidates.isEmpty()) return null
        if (settings.settings.value.studyOrder == STUDY_ORDER_ALPHABETICAL) {
            return candidates.minByOrNull { it.id }
        }
        val index = (randomUnit().coerceIn(0.0, 0.9999999999999999) * candidates.size).toInt()
        return candidates[index]
    }
}

class RateWordUseCase(
    private val reviews: ReviewRepository,
    private val learntWords: LearntWordsRepository,
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
        if (wordId !in learntWords.learntWords.value) {
            learntWords.saveLearntWords(
                listOf(
                    LearntWord(
                        wordId = wordId,
                        weight = initialWeightFor(rating),
                        learntAtUtc = reviewedAt,
                        lastReviewedAtUtc = reviewedAt,
                    ),
                ),
            )
        }
        return next
    }
}

class BuildReviewSessionUseCase(
    private val vocabulary: VocabularyRepository,
    private val learntWords: LearntWordsRepository,
    private val settings: SettingsRepository,
    private val randomUnit: () -> Double = { Random.Default.nextDouble() },
) {
    operator fun invoke(): List<VocabularyEntry> {
        val entriesById = vocabulary.words.value.associateBy { it.id }
        val candidates = learntWords.learntWords.value.values
            .asSequence()
            .mapNotNull { learnt -> entriesById[learnt.wordId]?.let { it to learnt.weight } }
            .filter { (entry, _) ->
                settings.settings.value.reviewLevels.isEmpty() ||
                    entry.levels.any { it.uppercase() in settings.settings.value.reviewLevels }
            }
            .sortedBy { (entry, _) -> entry.id }
            .toList()
        if (candidates.isEmpty()) return emptyList()
        val count = settings.settings.value.reviewBatchSize.coerceIn(1, candidates.size)
        return weightedSampleWithoutReplacement(candidates, count, randomUnit)
    }
}

internal fun weightedSampleWithoutReplacement(
    candidates: List<Pair<VocabularyEntry, Double>>,
    count: Int,
    randomUnit: () -> Double,
): List<VocabularyEntry> {
    if (count <= 0 || candidates.isEmpty()) return emptyList()
    val remaining = candidates.toMutableList()
    val selected = ArrayList<VocabularyEntry>(minOf(count, candidates.size))
    repeat(minOf(count, candidates.size)) {
        val totalWeight = remaining.sumOf { (_, weight) -> weight }
        val unit = randomUnit().coerceIn(0.0, 0.9999999999999999)
        val target = unit * totalWeight
        var cumulative = 0.0
        var selectedIndex = remaining.lastIndex
        for (index in remaining.indices) {
            cumulative += remaining[index].second
            if (target < cumulative) {
                selectedIndex = index
                break
            }
        }
        selected += remaining.removeAt(selectedIndex).first
    }
    return selected
}

class RateReviewWordUseCase(
    private val reviews: ReviewRepository,
    private val learntWords: LearntWordsRepository,
    private val time: TimeProvider,
) {
    suspend operator fun invoke(wordId: String, rating: ReviewRating): ScheduleState {
        val learnt = requireNotNull(learntWords.learntWords.value[wordId]) {
            "Cannot review a word that has not been learnt"
        }
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
        learntWords.saveLearntWords(
            listOf(
                learnt.copy(
                    weight = updatedWeightForReview(learnt.weight, rating),
                    lastReviewedAtUtc = reviewedAt,
                    reviewCount = learnt.reviewCount + 1,
                ),
            ),
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

class LookupVocabularyWordUseCase(
    private val vocabulary: VocabularyRepository,
) {
    operator fun invoke(token: String, contextExample: String = ""): BubbleDefinition =
        resolveBubbleDefinition(vocabulary.words.value, token, contextExample)
}

class GetReminderCardUseCase(
    private val vocabulary: VocabularyRepository,
    private val reviews: ReviewRepository,
    private val settings: SettingsRepository,
    private val time: TimeProvider,
    private val randomUnit: () -> Double = { Random.Default.nextDouble() },
) {
    operator fun invoke(excludeId: String = ""): VocabularyEntry? {
        val selectedLevels = settings.settings.value.reminderLevels
        val words = vocabulary.words.value.filter { entry ->
            selectedLevels.isEmpty() || entry.levels.any { it.uppercase() in selectedLevels }
        }
        if (words.isEmpty()) return null
        val now = time.nowUtcSeconds()
        val dueIds = reviews.schedules.value
            .filterValues { it.lastReviewedAtUtc != null && it.dueAtUtc <= now }
            .keys
        val candidates = words.filter { it.id in dueIds }.ifEmpty { words }
        val fresh = candidates.filter { it.id != excludeId }.ifEmpty { candidates }
        val index = (randomUnit().coerceIn(0.0, 0.9999999999999999) * fresh.size).toInt()
        return fresh[index]
    }
}

class ImportVocabularyUseCase(
    private val vocabulary: VocabularyRepository,
) {
    suspend operator fun invoke(bytes: ByteArray): ImportReport =
        vocabulary.importCsv(ByteArrayInputStream(bytes))
}

class UpdateVocabularyLabelsUseCase(private val vocabulary: VocabularyRepository) {
    suspend operator fun invoke(wordIds: Set<String>, levels: Set<String>, tags: Set<String>): Int {
        val normalizedLevels = levels.map(String::uppercase).toSet()
        require(normalizedLevels.isNotEmpty() && normalizedLevels.all { it in setOf("CET4", "CET6", "CUSTOM") }) {
            "词汇组只能包含 CET4、CET6 或 custom"
        }
        return vocabulary.updateLabels(
            wordIds,
            normalizedLevels,
            tags.map(String::trim).filter(String::isNotEmpty).toSet(),
        )
    }
}

class UpdateFontScaleUseCase(
    private val settings: SettingsRepository,
) {
    suspend operator fun invoke(scale: Float) {
        settings.setFontScale(scale.coerceIn(0.9f, 1.4f))
    }
}

class UpdateReviewBatchSizeUseCase(
    private val settings: SettingsRepository,
    private val learntWords: LearntWordsRepository,
) {
    suspend operator fun invoke(count: Int): Int {
        val maximum = maxOf(1, learntWords.learntWords.value.size)
        val bounded = count.coerceIn(1, maximum)
        settings.setReviewBatchSize(bounded)
        return bounded
    }
}

class UpdateStudyOrderUseCase(private val settings: SettingsRepository) {
    suspend operator fun invoke(order: String) {
        require(order == STUDY_ORDER_ALPHABETICAL || order == STUDY_ORDER_RANDOM) {
            "学习顺序必须为 alphabetical 或 random"
        }
        settings.setStudyOrder(order)
    }
}

class UpdateStudyLevelsUseCase(private val settings: SettingsRepository) {
    suspend operator fun invoke(levels: Set<String>) {
        settings.setStudyLevels(levels.map(String::uppercase).toSet())
    }
}

class UpdateReviewLevelsUseCase(private val settings: SettingsRepository) {
    suspend operator fun invoke(levels: Set<String>) {
        settings.setReviewLevels(levels.map(String::uppercase).toSet())
    }
}

class UpdateReminderLevelsUseCase(private val settings: SettingsRepository) {
    suspend operator fun invoke(levels: Set<String>) {
        val normalized = levels.map(String::uppercase).toSet()
        require(normalized.all { it in SUPPORTED_VOCABULARY_LEVELS }) {
            "提醒词汇组只能包含 CET4、CET6 或 custom"
        }
        settings.setReminderLevels(normalized)
    }
}

class UpdateReminderSettingsUseCase(
    private val settings: SettingsRepository,
) {
    suspend operator fun invoke(enabled: Boolean, intervalMinutes: Float): Float {
        require(intervalMinutes in MIN_REMINDER_INTERVAL_MINUTES..MAX_REMINDER_INTERVAL_MINUTES) {
            "提醒间隔需在 0.5 到 120 分钟之间"
        }
        settings.setReminderEnabled(enabled)
        settings.setReminderIntervalMinutes(intervalMinutes)
        return intervalMinutes
    }
}

class BuildDashboardUseCase(
    private val vocabulary: VocabularyRepository,
    private val reviews: ReviewRepository,
    private val learntWords: LearntWordsRepository,
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
            newWords = vocabulary.words.value.count { it.id !in learntWords.learntWords.value },
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
    val startReviewSession: BuildReviewSessionUseCase,
    val rateReviewWord: RateReviewWordUseCase,
    val search: SearchVocabularyUseCase,
    val lookupWord: LookupVocabularyWordUseCase,
    val importVocabulary: ImportVocabularyUseCase,
    val updateVocabularyLabels: UpdateVocabularyLabelsUseCase,
    val updateFontScale: UpdateFontScaleUseCase,
    val updateReviewBatchSize: UpdateReviewBatchSizeUseCase,
    val updateStudyOrder: UpdateStudyOrderUseCase,
    val updateStudyLevels: UpdateStudyLevelsUseCase,
    val updateReviewLevels: UpdateReviewLevelsUseCase,
    val updateReminderLevels: UpdateReminderLevelsUseCase,
    val updateReminderSettings: UpdateReminderSettingsUseCase,
    val selectDictationCandidates: SelectDictationCandidatesUseCase,
    val buildDictationDocument: BuildDictationDocumentUseCase,
    val exportDictationDocument: ExportDictationDocumentUseCase,
    val updateProgramTags: UpdateProgramTagsUseCase,
    val updateMarkMode: UpdateMarkModeUseCase,
    val reminderCard: GetReminderCardUseCase,
    val dashboard: BuildDashboardUseCase,
    val forecast: BuildForecastUseCase,
    val words: StateFlow<List<VocabularyEntry>>,
    val catalogStatus: StateFlow<CatalogStatus>,
    val schedules: StateFlow<Map<String, ScheduleState>>,
    val history: StateFlow<List<ReviewEvent>>,
    val learntWords: StateFlow<Map<String, LearntWord>>,
    val settings: StateFlow<UserSettings>,
)
