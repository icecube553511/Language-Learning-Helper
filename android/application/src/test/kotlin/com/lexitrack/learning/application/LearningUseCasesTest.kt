package com.lexitrack.learning.application

import com.lexitrack.learning.domain.BilingualExample
import com.lexitrack.learning.domain.ImportReport
import com.lexitrack.learning.domain.ReviewEvent
import com.lexitrack.learning.domain.ScheduleState
import com.lexitrack.learning.domain.VocabularyEntry
import java.io.InputStream
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneOffset
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlin.test.Test
import kotlin.test.assertEquals

class LearningUseCasesTest {
    private val now = 1_704_067_200.0
    private val words = (1..7_116).map { index -> word("word-$index") }
    private val vocabulary = FakeVocabularyRepository(words)
    private val reviews = FakeReviewRepository()
    private val time = FixedTimeProvider(now)

    @Test
    fun `dashboard separates new words from due reviews`() {
        val dashboard = BuildDashboardUseCase(vocabulary, reviews, time)

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
        val afterGood = dashboard()
        assertEquals(0, afterGood.dueNow)
        assertEquals(7_115, afterGood.newWords)
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

private class FixedTimeProvider(private val now: Double) : TimeProvider {
    override fun nowUtcSeconds(): Double = now
    override fun localDate(epochSeconds: Double): LocalDate = Instant
        .ofEpochSecond(epochSeconds.toLong())
        .atZone(ZoneOffset.UTC)
        .toLocalDate()
}
