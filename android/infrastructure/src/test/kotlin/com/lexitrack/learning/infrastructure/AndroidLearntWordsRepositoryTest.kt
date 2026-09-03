package com.lexitrack.learning.infrastructure

import android.content.Context
import androidx.test.core.app.ApplicationProvider
import com.lexitrack.learning.domain.LearntWord
import com.lexitrack.learning.domain.Mood
import com.lexitrack.learning.domain.PetVitals
import com.lexitrack.learning.domain.ReviewRecoveryTag
import kotlinx.coroutines.CoroutineStart
import kotlinx.coroutines.launch
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.double
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner

@RunWith(RobolectricTestRunner::class)
class AndroidLearntWordsRepositoryTest {
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
    fun persistsLearntWordsAcrossRepositoryInstances() = runBlocking {
        val repository = AndroidLearntWordsRepository(context)
        repository.saveLearntWords(
            listOf(LearntWord("focus", 0.8, 1_000.0, 1_000.0, reviewCount = 2)),
        )

        val loaded = AndroidLearntWordsRepository(context).learntWords.value.getValue("focus")

        assertEquals(0.8, loaded.weight, 0.0)
        assertEquals(1_000.0, loaded.learntAtUtc, 0.0)
        assertEquals(1_000.0, loaded.lastReviewedAtUtc, 0.0)
        assertEquals(2, loaded.reviewCount)
    }

    @Test
    fun legacyStoreUsesCanonicalPetVitalsDefaults() {
        val repository = AndroidLearntWordsRepository(context)

        assertEquals(50.0, repository.petVitals.value.satiety, 0.0)
        assertEquals(0.0, repository.petVitals.value.foodReserve, 0.0)
        assertEquals(Mood.CALM, repository.petVitals.value.mood)
    }

    @Test
    fun savesMarkerAndPetVitalsInOneLearningOutcome() = runBlocking {
        val repository = AndroidLearntWordsRepository(context)
        val word = LearntWord(
            "focus",
            0.8,
            1_000.0,
            1_000.0,
            reviewRecoveryTag = ReviewRecoveryTag.VAGUE,
        )
        val vitals = PetVitals.restore(satiety = 88.5, foodReserve = 14.25, mood = Mood.HAPPY)

        repository.saveLearningOutcome(word, vitals)

        val reloaded = AndroidLearntWordsRepository(context)
        assertEquals(ReviewRecoveryTag.VAGUE, reloaded.learntWords.value.getValue("focus").reviewRecoveryTag)
        assertEquals(88.5, reloaded.petVitals.value.satiety, 0.0)
        assertEquals(14.25, reloaded.petVitals.value.foodReserve, 0.0)
        assertEquals(14.25, reloaded.petVitals.value.foodJar.storedSatiety, 0.0)
        assertEquals(Mood.HAPPY, reloaded.petVitals.value.mood)

        val encodedVitals = context.getSharedPreferences(
            AndroidLearntWordsRepository.PREFERENCES_NAME,
            Context.MODE_PRIVATE,
        ).getString(AndroidLearntWordsRepository.KEY_PET_VITALS, null).orEmpty()
        val json = Json.parseToJsonElement(encodedVitals).jsonObject
        assertEquals(setOf("satiety", "foodReserve", "mood"), json.keys)
        assertEquals(14.25, json.getValue("foodReserve").jsonPrimitive.double, 0.0)
    }

    @Test
    fun malformedDualMarkerPrefersForgotAndNextSaveIsCanonical() = runBlocking {
        val malformed = """{
            "focus": {
                "wordId": "focus",
                "weight": 0.8,
                "learntAtUtc": 1000.0,
                "lastReviewedAtUtc": 1000.0,
                "reviewRecoveryTags": {
                    "ToBeReviewed_Vague": true,
                    "ToBeReviewed_Forgot": true
                }
            }
        }""".trimIndent()
        context.getSharedPreferences(AndroidLearntWordsRepository.PREFERENCES_NAME, Context.MODE_PRIVATE)
            .edit()
            .putString(AndroidLearntWordsRepository.KEY_WORDS, malformed)
            .commit()

        val repository = AndroidLearntWordsRepository(context)
        val word = repository.learntWords.value.getValue("focus")
        assertEquals(ReviewRecoveryTag.FORGOT, word.reviewRecoveryTag)

        repository.saveLearningOutcome(word, repository.petVitals.value)

        val encoded = context.getSharedPreferences(
            AndroidLearntWordsRepository.PREFERENCES_NAME,
            Context.MODE_PRIVATE,
        ).getString(AndroidLearntWordsRepository.KEY_WORDS, "").orEmpty()
        assertTrue(encoded.contains("ToBeReviewed_Forgot"))
        assertFalse(encoded.contains("ToBeReviewed_Vague"))
        assertFalse(encoded.contains("reviewRecoveryTags"))
    }

    @Test
    fun updatesExistingLearntWordWithoutDroppingOtherRows() = runBlocking {
        val repository = AndroidLearntWordsRepository(context)
        repository.saveLearntWords(
            listOf(
                LearntWord("focus", 0.8, 1_000.0, 1_000.0),
                LearntWord("serene", 1.0, 2_000.0, 2_000.0),
            ),
        )
        repository.saveLearntWords(
            listOf(LearntWord("focus", 0.2, 1_000.0, 3_000.0, reviewCount = 1)),
        )

        val loaded = AndroidLearntWordsRepository(context).learntWords.value

        assertEquals(setOf("focus", "serene"), loaded.keys)
        assertEquals(0.2, loaded.getValue("focus").weight, 0.0)
        assertEquals(3_000.0, loaded.getValue("focus").lastReviewedAtUtc, 0.0)
        assertEquals(1, loaded.getValue("focus").reviewCount)
    }

    @Test
    fun cancellationAfterCommitStillPublishesLearningOutcome() = runBlocking {
        val ioDispatcher = ManualCoroutineDispatcher()
        val repository = AndroidLearntWordsRepository(context, ioDispatcher)
        val word = LearntWord(
            "focus",
            0.2,
            1_000.0,
            2_000.0,
            reviewCount = 1,
            reviewRecoveryTag = ReviewRecoveryTag.FORGOT,
        )
        val vitals = PetVitals.restore(satiety = 73.5, foodReserve = 8.25, mood = Mood.WORRIED)
        val saveJob = launch(start = CoroutineStart.UNDISPATCHED) {
            repository.saveLearningOutcome(word, vitals)
        }

        ioDispatcher.runNextOnWorker()
        saveJob.cancel()
        saveJob.join()

        assertTrue(saveJob.isCancelled)
        assertEquals(word, repository.learntWords.value.getValue("focus"))
        assertEquals(vitals, repository.petVitals.value)
        val reloaded = AndroidLearntWordsRepository(context)
        assertEquals(word, reloaded.learntWords.value.getValue("focus"))
        assertEquals(vitals, reloaded.petVitals.value)
    }

    private fun clearPreferences() {
        context.getSharedPreferences(AndroidLearntWordsRepository.PREFERENCES_NAME, Context.MODE_PRIVATE)
            .edit()
            .clear()
            .commit()
    }
}
