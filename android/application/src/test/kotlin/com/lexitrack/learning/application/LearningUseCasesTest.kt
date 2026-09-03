package com.lexitrack.learning.application

import com.lexitrack.learning.domain.BilingualExample
import com.lexitrack.learning.domain.FoodJar
import com.lexitrack.learning.domain.ImportReport
import com.lexitrack.learning.domain.LearntWord
import com.lexitrack.learning.domain.LexiSm2Scheduler
import com.lexitrack.learning.domain.ReviewEvent
import com.lexitrack.learning.domain.ReviewRating
import com.lexitrack.learning.domain.ScheduleState
import com.lexitrack.learning.domain.VocabularyEntry
import com.lexitrack.learning.domain.PetVitals
import com.lexitrack.learning.domain.ReviewRecoveryTag
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
import kotlin.test.assertFailsWith

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

        val card = GetNextCardUseCase(vocabulary, learntWords, FakeSettingsRepository(), randomUnit = { 0.0 })()

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
        assertEquals(ReviewRecoveryTag.VAGUE, saved.reviewRecoveryTag)
        assertEquals(PetVitals.Default, learntWords.petVitals.value)
    }

    @Test
    fun `study success rewards satiety while failure markers remain mutually exclusive`() = runTest {
        val useCase = RateWordUseCase(reviews, learntWords, time)

        useCase(words[0].id, ReviewRating.AGAIN)
        assertEquals(ReviewRecoveryTag.FORGOT, learntWords.learntWords.value.getValue(words[0].id).reviewRecoveryTag)

        useCase(words[1].id, ReviewRating.HARD)
        assertEquals(ReviewRecoveryTag.VAGUE, learntWords.learntWords.value.getValue(words[1].id).reviewRecoveryTag)

        useCase(words[2].id, ReviewRating.GOOD)
        assertEquals(52.0, learntWords.petVitals.value.satiety, 0.0)
        assertEquals(null, learntWords.learntWords.value.getValue(words[2].id).reviewRecoveryTag)
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
    fun `review reward uses prior marker then clears it and converts overflow`() = runTest {
        val wordId = words.first().id
        val useCase = RateReviewWordUseCase(reviews, learntWords, time)
        learntWords.wordsFlow.value = mapOf(
            wordId to learnt(wordId, 0.8).copy(reviewRecoveryTag = ReviewRecoveryTag.FORGOT),
        )
        learntWords.vitalsFlow.value = PetVitals.restore(
            satiety = 99.0,
            foodJar = FoodJar.restore(10.0),
        )

        useCase(wordId, ReviewRating.EASY)

        val saved = learntWords.learntWords.value.getValue(wordId)
        assertEquals(null, saved.reviewRecoveryTag)
        assertEquals(100.0, learntWords.petVitals.value.satiety, 0.0)
        assertEquals(11.6, learntWords.petVitals.value.foodReserve, 1e-9)
        assertEquals(11.6, learntWords.petVitals.value.foodJar.storedSatiety, 1e-9)
    }

    @Test
    fun `learning outcome failure rolls schedule and history back before retry`() = runTest {
        val wordId = words.first().id
        val localReviews = FakeReviewRepository()
        val localLearntWords = FakeLearntWordsRepository()
        val baselineSchedule = ScheduleState(
            intervalDays = 3.0,
            repetitions = 2,
            dueAtUtc = now - 1.0,
            lastReviewedAtUtc = now - 86_400.0,
        )
        val baselineHistory = listOf(
            ReviewEvent(wordId, now - 86_400.0, ReviewRating.GOOD, 3.0),
        )
        val baselineWord = learnt(wordId, 0.8)
        localReviews.scheduleFlow.value = mapOf(wordId to baselineSchedule)
        localReviews.history.value = baselineHistory
        localLearntWords.wordsFlow.value = mapOf(wordId to baselineWord)
        localLearntWords.failNextLearningOutcome = true
        val useCase = RateReviewWordUseCase(localReviews, localLearntWords, time)

        assertFailsWith<IllegalStateException> {
            useCase(wordId, ReviewRating.GOOD)
        }

        assertEquals(mapOf(wordId to baselineSchedule), localReviews.schedules.value)
        assertEquals(baselineHistory, localReviews.history.value)
        assertEquals(baselineWord, localLearntWords.learntWords.value.getValue(wordId))
        assertEquals(PetVitals.Default, localLearntWords.petVitals.value)

        val expected = LexiSm2Scheduler.review(baselineSchedule, ReviewRating.GOOD, now)
        assertEquals(expected, useCase(wordId, ReviewRating.GOOD))
        assertEquals(expected, localReviews.schedules.value.getValue(wordId))
        assertEquals(baselineHistory.size + 1, localReviews.history.value.size)
        assertEquals(1, localLearntWords.learntWords.value.getValue(wordId).reviewCount)
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
    fun `study defaults to random and supports alphabetical order and level filters`() = runTest {
        val zeta = word("zeta").copy(levels = setOf("CET4"))
        val alpha = word("alpha").copy(levels = setOf("CET6"))
        val localVocabulary = FakeVocabularyRepository(listOf(zeta, alpha))
        val settings = FakeSettingsRepository()

        val randomCard = GetNextCardUseCase(localVocabulary, learntWords, settings, randomUnit = { 0.99 })()
        assertEquals(alpha.id, randomCard?.id)

        settings.setStudyOrder(STUDY_ORDER_ALPHABETICAL)
        assertEquals(alpha.id, GetNextCardUseCase(localVocabulary, learntWords, settings)()?.id)

        settings.setStudyLevels(setOf("CET4"))
        assertEquals(zeta.id, GetNextCardUseCase(localVocabulary, learntWords, settings)()?.id)
    }

    @Test
    fun `study and review level filters are independent and support multiple levels`() = runTest {
        val cet4 = word("cet4").copy(levels = setOf("CET4"))
        val cet6 = word("cet6").copy(levels = setOf("CET6"))
        val localVocabulary = FakeVocabularyRepository(listOf(cet4, cet6))
        val settings = FakeSettingsRepository(UserSettings(studyLevels = setOf("CET6"), reviewLevels = setOf("CET4")))
        learntWords.wordsFlow.value = mapOf(cet4.id to learnt(cet4.id, 1.0))

        assertEquals(cet6.id, GetNextCardUseCase(localVocabulary, learntWords, settings)()?.id)
        val review = BuildReviewSessionUseCase(localVocabulary, learntWords, settings, randomUnit = { 0.0 })()
        assertEquals(listOf(cet4.id), review.map { it.id })

        learntWords.wordsFlow.value = learntWords.wordsFlow.value + (cet6.id to learnt(cet6.id, 1.0))
        settings.setReviewLevels(setOf("CET4", "CET6"))
        assertEquals(setOf(cet4.id, cet6.id), BuildReviewSessionUseCase(localVocabulary, learntWords, settings)().map { it.id }.toSet())
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
    fun `reminder settings accept fractional minutes and reject invalid bounds`() = runTest {
        val settings = FakeSettingsRepository()
        val useCase = UpdateReminderSettingsUseCase(settings)

        assertEquals(1.25f, useCase(true, 1.25f))
        assertEquals(true, settings.settings.value.reminderEnabled)
        assertEquals(1.25f, settings.settings.value.reminderIntervalMinutes)
        assertFailsWith<IllegalArgumentException> { useCase(true, 0.25f) }
        assertFailsWith<IllegalArgumentException> { useCase(true, 121.0f) }
    }

    @Test
    fun `reminder level filter is independent and applies before due-word preference`() = runTest {
        val cet4 = word("cet4-reminder").copy(levels = setOf("CET4"))
        val cet6 = word("cet6-reminder").copy(levels = setOf("CET6"))
        val custom = word("custom-reminder").copy(levels = setOf("CUSTOM"))
        val localVocabulary = FakeVocabularyRepository(listOf(cet4, cet6, custom))
        val settings = FakeSettingsRepository(
            UserSettings(
                studyLevels = setOf("CET4"),
                reviewLevels = setOf("CET6"),
                reminderLevels = setOf("CUSTOM"),
            ),
        )
        reviews.scheduleFlow.value = mapOf(
            cet4.id to ScheduleState(lastReviewedAtUtc = now - 100.0, dueAtUtc = now - 1.0),
            cet6.id to ScheduleState(lastReviewedAtUtc = now - 100.0, dueAtUtc = now - 1.0),
        )
        val useCase = GetReminderCardUseCase(
            localVocabulary,
            reviews,
            settings,
            time,
            randomUnit = { 0.0 },
        )

        assertEquals(custom.id, useCase()?.id)
        assertEquals(setOf("CET4"), settings.settings.value.studyLevels)
        assertEquals(setOf("CET6"), settings.settings.value.reviewLevels)

        UpdateReminderLevelsUseCase(settings)(setOf("cet4", "cet6"))
        assertEquals(setOf("CET4", "CET6"), settings.settings.value.reminderLevels)
        assertEquals(cet6.id, useCase(excludeId = cet4.id)?.id)
        assertFailsWith<IllegalArgumentException> {
            UpdateReminderLevelsUseCase(settings)(setOf("CET4", "other"))
        }
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

    @Test
    fun `library groups are canonical ordered with counts`() {
        val vocab = FakeVocabularyRepository(
            listOf(
                word("adapt").copy(levels = setOf("CET4"), tags = setOf("gk")),
                word("abandon").copy(levels = setOf("CET6"), tags = setOf("zk")),
                word("zephyr").copy(levels = setOf("CET4", "CET6")),
                word("myword").copy(levels = setOf("CUSTOM")),
            ),
        )
        val groups = LibraryGroupsUseCase(vocab)()
        assertEquals(listOf("all", "cet4", "cet6", "zk", "gk", "custom"), groups.map { it.key })
        assertEquals(
            mapOf("all" to 4, "cet4" to 2, "cet6" to 2, "zk" to 1, "gk" to 1, "custom" to 1),
            groups.associate { it.key to it.count },
        )
        assertEquals("CET-4（四级）", groups.first { it.key == "cet4" }.label)
    }

    @Test
    fun `words in group and within group search`() {
        val vocab = FakeVocabularyRepository(
            listOf(
                word("adapt").copy(levels = setOf("CET4"), tags = setOf("gk")),
                word("abandon").copy(levels = setOf("CET6"), tags = setOf("zk")),
                word("zephyr").copy(levels = setOf("CET4", "CET6")),
                word("myword").copy(levels = setOf("CUSTOM")),
            ),
        )
        val useCase = WordsInGroupUseCase(vocab)
        assertEquals(4, useCase("all").size)
        assertEquals(setOf("adapt", "zephyr"), useCase("cet4").map { it.id }.toSet())
        assertEquals(listOf("adapt"), useCase("gk").map { it.id })
        assertEquals(listOf("myword"), useCase("custom").map { it.id })
        assertEquals(listOf("abandon"), useCase("zk", "aband").map { it.id })
        assertEquals(listOf("zephyr"), useCase("all", "zeph").map { it.id })
        assertEquals(emptyList(), useCase("missing"))
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

    override suspend fun updateLabels(wordIds: Set<String>, levels: Set<String>, tags: Set<String>): Int {
        var count = 0
        words.value = words.value.map { entry ->
            if (entry.id !in wordIds) entry else entry.copy(levels = levels, tags = tags).also { count += 1 }
        }
        return count
    }
}

private class FakeReviewRepository : ReviewRepository {
    val scheduleFlow = MutableStateFlow<Map<String, ScheduleState>>(emptyMap())
    override val schedules: StateFlow<Map<String, ScheduleState>> = scheduleFlow
    override val history = MutableStateFlow<List<ReviewEvent>>(emptyList())
    override suspend fun saveReview(
        wordId: String,
        state: ScheduleState,
        event: ReviewEvent,
    ): ReviewSavepoint {
        val savepoint = FakeReviewSavepoint(scheduleFlow.value, history.value)
        scheduleFlow.value = scheduleFlow.value + (wordId to state)
        history.value = history.value + event
        return savepoint
    }

    override suspend fun rollbackReview(savepoint: ReviewSavepoint) {
        val state = savepoint as FakeReviewSavepoint
        scheduleFlow.value = state.schedules
        history.value = state.history
    }
}

private data class FakeReviewSavepoint(
    val schedules: Map<String, ScheduleState>,
    val history: List<ReviewEvent>,
) : ReviewSavepoint

private class FakeLearntWordsRepository : LearntWordsRepository {
    val wordsFlow = MutableStateFlow<Map<String, LearntWord>>(emptyMap())
    val vitalsFlow = MutableStateFlow(PetVitals.Default)
    override val learntWords: StateFlow<Map<String, LearntWord>> = wordsFlow
    override val petVitals: StateFlow<PetVitals> = vitalsFlow
    var failNextLearningOutcome = false

    override suspend fun saveLearntWords(words: Collection<LearntWord>) {
        wordsFlow.value = wordsFlow.value + words.associateBy { it.wordId }
    }

    override suspend fun saveLearningOutcome(word: LearntWord, vitals: PetVitals) {
        if (failNextLearningOutcome) {
            failNextLearningOutcome = false
            error("Injected learning outcome failure")
        }
        wordsFlow.value = wordsFlow.value + (word.wordId to word)
        vitalsFlow.value = vitals
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

    override suspend fun setStudyOrder(order: String) {
        settings.value = settings.value.copy(studyOrder = order)
    }

    override suspend fun setStudyLevels(levels: Set<String>) {
        settings.value = settings.value.copy(studyLevels = levels)
    }

    override suspend fun setReviewLevels(levels: Set<String>) {
        settings.value = settings.value.copy(reviewLevels = levels)
    }

    override suspend fun setReminderLevels(levels: Set<String>) {
        settings.value = settings.value.copy(reminderLevels = levels)
    }

    override suspend fun setReminderEnabled(enabled: Boolean) {
        settings.value = settings.value.copy(reminderEnabled = enabled)
    }

    override suspend fun setReminderIntervalMinutes(minutes: Float) {
        settings.value = settings.value.copy(reminderIntervalMinutes = minutes)
    }
}

private class FixedTimeProvider(private val now: Double) : TimeProvider {
    override fun nowUtcSeconds(): Double = now
    override fun localDate(epochSeconds: Double): LocalDate = Instant
        .ofEpochSecond(epochSeconds.toLong())
        .atZone(ZoneOffset.UTC)
        .toLocalDate()
}
