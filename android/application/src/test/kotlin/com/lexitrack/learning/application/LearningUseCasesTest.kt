package com.lexitrack.learning.application

import com.lexitrack.learning.domain.BilingualExample
import com.lexitrack.learning.domain.ImportReport
import com.lexitrack.learning.domain.LearntWord
import com.lexitrack.learning.domain.ReviewEvent
import com.lexitrack.learning.domain.ReviewRating
import com.lexitrack.learning.domain.ScheduleState
import com.lexitrack.learning.domain.VocabularyEntry
import java.io.InputStream
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneOffset
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.test.runTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotEquals

class LearningUseCasesTest {
    private val now = 1_704_067_200.0
    private val words = (1..7_116).map { index -> word("word-$index") }
    private val vocabulary = FakeVocabularyRepository(words)
    private val reviews = FakeReviewRepository()
    private val learntWords = FakeLearntWordsRepository()
    private val time = FixedTimeProvider(now)

    @Test
    fun `dashboard separates new words from due reviews`() {
        val dashboard = BuildDashboardUseCase(vocabulary, reviews, learntWords, time)

        val initial = dashboard()
        assertEquals(7_116, initial.totalWords)
        assertEquals(0, initial.dueNow)
        assertEquals(7_116, initial.newWords)

        reviews.scheduleFlow.value = mapOf(
            words.first().id to ScheduleState(
                intervalDays = 3.0,
                repetitions = 1,
                dueAtUtc = now + 3 * 86_400.0,
            ),
        )
        learntWords.wordsFlow.value = mapOf(
            words.first().id to learnt(words.first().id, 0.2),
        )
        val afterGood = dashboard()
        assertEquals(0, afterGood.dueNow)
        assertEquals(7_115, afterGood.newWords)
    }

    @Test
    fun `study only returns words not in learnt words repository`() {
        learntWords.wordsFlow.value = mapOf(
            words.first().id to learnt(words.first().id, 1.0),
        )

        val card = GetNextCardUseCase(vocabulary, learntWords)()

        assertNotEquals(words.first().id, card?.id)
    }

    @Test
    fun `study rating creates learnt word with initial rating weight`() = runTest {
        val useCase = RateWordUseCase(reviews, learntWords, time)

        useCase(words.first().id, ReviewRating.HARD)

        val saved = learntWords.learntWords.value.getValue(words.first().id)
        assertEquals(0.8, saved.weight)
        assertEquals(now, saved.learntAtUtc)
        assertEquals(now, saved.lastReviewedAtUtc)
        assertEquals(0, saved.reviewCount)
    }

    @Test
    fun `review hard retains weight while good and easy replace it`() = runTest {
        val wordId = words.first().id
        val useCase = RateReviewWordUseCase(reviews, learntWords, time)
        learntWords.wordsFlow.value = mapOf(wordId to learnt(wordId, 0.8))

        useCase(wordId, ReviewRating.HARD)
        assertEquals(0.8, learntWords.learntWords.value.getValue(wordId).weight)
        assertEquals(1, learntWords.learntWords.value.getValue(wordId).reviewCount)

        useCase(wordId, ReviewRating.GOOD)
        assertEquals(0.2, learntWords.learntWords.value.getValue(wordId).weight)

        useCase(wordId, ReviewRating.EASY)
        assertEquals(0.05, learntWords.learntWords.value.getValue(wordId).weight)
        assertEquals(3, learntWords.learntWords.value.getValue(wordId).reviewCount)
    }

    @Test
    fun `review session uses configured count and weighted sampling without replacement`() {
        val first = words[0]
        val second = words[1]
        val third = words[2]
        val localVocabulary = FakeVocabularyRepository(listOf(first, second, third))
        learntWords.wordsFlow.value = mapOf(
            first.id to learnt(first.id, 1.0),
            second.id to learnt(second.id, 0.05),
            third.id to learnt(third.id, 0.05),
        )
        val settings = FakeSettingsRepository(UserSettings(reviewBatchSize = 2))
        val useCase = BuildReviewSessionUseCase(
            localVocabulary,
            learntWords,
            settings,
            randomUnit = { 0.5 },
        )

        val session = useCase()

        assertEquals(2, session.size)
        assertEquals(2, session.map { it.id }.distinct().size)
        assertEquals(first.id, session.first().id)
    }

    @Test
    fun `batch size is clamped to learnt word count and at least one`() = runTest {
        val settings = FakeSettingsRepository()
        val useCase = UpdateReviewBatchSizeUseCase(settings, learntWords)

        assertEquals(1, useCase(0))
        learntWords.wordsFlow.value = mapOf(
            words[0].id to learnt(words[0].id, 1.0),
            words[1].id to learnt(words[1].id, 0.8),
        )
        assertEquals(2, useCase(99))
        assertEquals(2, settings.settings.value.reviewBatchSize)
    }

    @Test
    fun `initialize migrates legacy review schedules with default weight`() = runTest {
        val wordId = words.first().id
        reviews.scheduleFlow.value = mapOf(
            wordId to ScheduleState(lastReviewedAtUtc = now, dueAtUtc = now + 100.0),
        )

        InitializeAppUseCase(vocabulary, reviews, learntWords)()

        val migrated = learntWords.learntWords.value.getValue(wordId)
        assertEquals(0.2, migrated.weight)
        assertEquals(now, migrated.learntAtUtc)
        assertEquals(0, migrated.reviewCount)
    }

    @Test
    fun `forecast ignores new words and places learned word on due day`() {
        val forecast = BuildForecastUseCase(vocabulary, reviews, time)
        assertEquals(List(7) { 0 }, forecast().map { it.count })

        reviews.scheduleFlow.value = mapOf(
            words.first().id to ScheduleState(
                intervalDays = 3.0,
                repetitions = 1,
                dueAtUtc = now + 3 * 86_400.0,
            ),
        )

        assertEquals(listOf(0, 0, 0, 1, 0, 0, 0), forecast().map { it.count })
    }

    private fun word(id: String) = VocabularyEntry(
        id = id,
        word = id,
        meaning = "测试",
        examples = listOf(
            BilingualExample("Example one for $id.", "例句一。"),
            BilingualExample("Example two for $id.", "例句二。"),
            BilingualExample("Example three for $id.", "例句三。"),
        ),
    )

    private fun learnt(id: String, weight: Double) = LearntWord(
        wordId = id,
        weight = weight,
        learntAtUtc = now,
        lastReviewedAtUtc = now,
    )
}

private class FakeVocabularyRepository(initial: List<VocabularyEntry>) : VocabularyRepository {
    override val words = MutableStateFlow(initial)
    override val status = MutableStateFlow(CatalogStatus(loading = false))
    override suspend fun initialize() = Unit
    override suspend fun importCsv(input: InputStream) = ImportReport.Empty
}

private class FakeReviewRepository : ReviewRepository {
    val scheduleFlow = MutableStateFlow<Map<String, ScheduleState>>(emptyMap())
    override val schedules: StateFlow<Map<String, ScheduleState>> = scheduleFlow
    override val history = MutableStateFlow<List<ReviewEvent>>(emptyList())
    override suspend fun saveReview(wordId: String, state: ScheduleState, event: ReviewEvent) {
        scheduleFlow.value = scheduleFlow.value + (wordId to state)
        history.value = history.value + event
    }
}

private class FakeLearntWordsRepository : LearntWordsRepository {
    val wordsFlow = MutableStateFlow<Map<String, LearntWord>>(emptyMap())
    override val learntWords: StateFlow<Map<String, LearntWord>> = wordsFlow

    override suspend fun saveLearntWords(words: Collection<LearntWord>) {
        wordsFlow.value = wordsFlow.value + words.associateBy { it.wordId }
    }
}

private class FakeSettingsRepository(
    initial: UserSettings = UserSettings(),
) : SettingsRepository {
    override val settings = MutableStateFlow(initial)

    override suspend fun setFontScale(scale: Float) {
        settings.value = settings.value.copy(fontScale = scale)
    }

    override suspend fun setReviewBatchSize(count: Int) {
        settings.value = settings.value.copy(reviewBatchSize = count)
    }
}

private class FixedTimeProvider(private val now: Double) : TimeProvider {
    override fun nowUtcSeconds(): Double = now
    override fun localDate(epochSeconds: Double): LocalDate = Instant
        .ofEpochSecond(epochSeconds.toLong())
        .atZone(ZoneOffset.UTC)
        .toLocalDate()
}
