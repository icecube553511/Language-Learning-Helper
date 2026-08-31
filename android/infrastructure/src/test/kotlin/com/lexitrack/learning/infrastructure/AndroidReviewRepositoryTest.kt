package com.lexitrack.learning.infrastructure

import android.content.Context
import androidx.test.core.app.ApplicationProvider
import com.lexitrack.learning.application.RateReviewWordUseCase
import com.lexitrack.learning.application.TimeProvider
import com.lexitrack.learning.domain.LearntWord
import com.lexitrack.learning.domain.PetVitals
import com.lexitrack.learning.domain.ReviewEvent
import com.lexitrack.learning.domain.ReviewRating
import com.lexitrack.learning.domain.ScheduleState
import java.time.LocalDate
import kotlinx.coroutines.CoroutineStart
import kotlinx.coroutines.launch
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner

@RunWith(RobolectricTestRunner::class)
class AndroidReviewRepositoryTest {
    private lateinit var context: Context

    @Before
    fun setUp() {
        context = ApplicationProvider.getApplicationContext()
        clearPreferences()
    }

    @After
    fun tearDown() {
        clearPreferences()
    }

    @Test
    fun savepointRestoresScheduleAndHistorySynchronously() = runBlocking {
        val repository = AndroidReviewRepository(context)
        val wordId = "focus"
        val baselineSchedule = ScheduleState(
            intervalDays = 1.0,
            repetitions = 1,
            dueAtUtc = 2_000.0,
            lastReviewedAtUtc = 1_000.0,
        )
        val baselineEvent = ReviewEvent(wordId, 1_000.0, ReviewRating.GOOD, 1.0)
        repository.saveReview(wordId, baselineSchedule, baselineEvent)

        val nextSchedule = baselineSchedule.copy(
            intervalDays = 6.0,
            repetitions = 2,
            dueAtUtc = 8_000.0,
            lastReviewedAtUtc = 2_000.0,
        )
        val nextEvent = ReviewEvent(wordId, 2_000.0, ReviewRating.EASY, 6.0)
        val savepoint = repository.saveReview(wordId, nextSchedule, nextEvent)

        val afterSave = AndroidReviewRepository(context)
        assertEquals(nextSchedule, afterSave.schedules.value.getValue(wordId))
        assertEquals(listOf(baselineEvent, nextEvent), afterSave.history.value)
        val preferences = context.getSharedPreferences(
            AndroidReviewRepository.PREFERENCES_NAME,
            Context.MODE_PRIVATE,
        )
        assertNotNull(preferences.getString(AndroidReviewRepository.KEY_SCHEDULES, null))
        assertNotNull(preferences.getString(AndroidReviewRepository.KEY_HISTORY, null))

        repository.rollbackReview(savepoint)

        val afterRollback = AndroidReviewRepository(context)
        assertEquals(baselineSchedule, afterRollback.schedules.value.getValue(wordId))
        assertEquals(listOf(baselineEvent), afterRollback.history.value)
    }

    @Test
    fun staleSavepointCannotOverwriteANewerRating() = runBlocking {
        val repository = AndroidReviewRepository(context)
        val first = ScheduleState(repetitions = 1, lastReviewedAtUtc = 1_000.0)
        val second = ScheduleState(repetitions = 2, lastReviewedAtUtc = 2_000.0)
        val stale = repository.saveReview(
            "focus",
            first,
            ReviewEvent("focus", 1_000.0, ReviewRating.GOOD, 1.0),
        )
        repository.saveReview(
            "focus",
            second,
            ReviewEvent("focus", 2_000.0, ReviewRating.EASY, 3.0),
        )

        val failure = runCatching { repository.rollbackReview(stale) }.exceptionOrNull()

        assertTrue(failure is IllegalStateException)
        val reloaded = AndroidReviewRepository(context)
        assertEquals(second, reloaded.schedules.value.getValue("focus"))
        assertEquals(2, reloaded.history.value.size)
    }

    @Test
    fun cancellationAfterCommitStillPublishesReviewState() = runBlocking {
        val ioDispatcher = ManualCoroutineDispatcher()
        val repository = AndroidReviewRepository(context, ioDispatcher)
        val schedule = ScheduleState(
            intervalDays = 6.0,
            repetitions = 2,
            dueAtUtc = 8_000.0,
            lastReviewedAtUtc = 2_000.0,
        )
        val event = ReviewEvent("focus", 2_000.0, ReviewRating.EASY, 6.0)
        val saveJob = launch(start = CoroutineStart.UNDISPATCHED) {
            repository.saveReview("focus", schedule, event)
        }

        ioDispatcher.runNextOnWorker()
        saveJob.cancel()
        saveJob.join()

        assertTrue(saveJob.isCancelled)
        assertEquals(schedule, repository.schedules.value.getValue("focus"))
        assertEquals(listOf(event), repository.history.value)
        val reloaded = AndroidReviewRepository(context)
        assertEquals(schedule, reloaded.schedules.value.getValue("focus"))
        assertEquals(listOf(event), reloaded.history.value)
    }

    @Test
    fun cancellationAfterReviewCommitCannotSplitTheRatingOutcome() = runBlocking {
        val learntWords = AndroidLearntWordsRepository(context)
        val original = LearntWord("focus", 0.8, 1_000.0, 1_000.0)
        learntWords.saveLearntWords(listOf(original))
        val reviewIo = ManualCoroutineDispatcher()
        val reviews = AndroidReviewRepository(context, reviewIo)
        val useCase = RateReviewWordUseCase(
            reviews = reviews,
            learntWords = learntWords,
            time = object : TimeProvider {
                override fun nowUtcSeconds(): Double = 2_000.0
                override fun localDate(epochSeconds: Double): LocalDate = LocalDate.ofEpochDay(0)
            },
        )
        val ratingJob = launch(start = CoroutineStart.UNDISPATCHED) {
            useCase("focus", ReviewRating.GOOD)
        }

        reviewIo.runNextOnWorker()
        ratingJob.cancel()
        ratingJob.join()

        val reloadedReviews = AndroidReviewRepository(context)
        val reloadedLearntWords = AndroidLearntWordsRepository(context)
        val reviewCommitted = "focus" in reloadedReviews.schedules.value
        val learningCommitted = reloadedLearntWords.learntWords.value
            .getValue("focus").reviewCount == 1
        assertEquals(reviewCommitted, learningCommitted)
        assertEquals(
            if (reviewCommitted) 50.2 else PetVitals.Default.satiety,
            reloadedLearntWords.petVitals.value.satiety,
            0.0,
        )
    }

    private fun clearPreferences() {
        context.getSharedPreferences(AndroidReviewRepository.PREFERENCES_NAME, Context.MODE_PRIVATE)
            .edit()
            .clear()
            .commit()
        context.getSharedPreferences(AndroidLearntWordsRepository.PREFERENCES_NAME, Context.MODE_PRIVATE)
            .edit()
            .clear()
            .commit()
    }
}
