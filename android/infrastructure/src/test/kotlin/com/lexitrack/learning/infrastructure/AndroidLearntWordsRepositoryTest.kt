package com.lexitrack.learning.infrastructure

import android.content.Context
import androidx.test.core.app.ApplicationProvider
import com.lexitrack.learning.domain.LearntWord
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertEquals
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

    private fun clearPreferences() {
        context.getSharedPreferences(AndroidLearntWordsRepository.PREFERENCES_NAME, Context.MODE_PRIVATE)
            .edit()
            .clear()
            .commit()
    }
}
