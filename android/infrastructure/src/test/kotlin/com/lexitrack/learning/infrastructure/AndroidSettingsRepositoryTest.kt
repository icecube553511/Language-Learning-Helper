package com.lexitrack.learning.infrastructure

import android.content.Context
import androidx.test.core.app.ApplicationProvider
import com.lexitrack.learning.application.DEFAULT_REVIEW_BATCH_SIZE
import com.lexitrack.learning.application.STUDY_ORDER_RANDOM
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner

@RunWith(RobolectricTestRunner::class)
class AndroidSettingsRepositoryTest {
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
    fun reviewBatchSizeDefaultsAndPersists() = runBlocking {
        val repository = AndroidSettingsRepository(context)
        assertEquals(DEFAULT_REVIEW_BATCH_SIZE, repository.settings.value.reviewBatchSize)

        repository.setReviewBatchSize(7)

        assertEquals(7, AndroidSettingsRepository(context).settings.value.reviewBatchSize)
    }

    @Test
    fun reviewBatchSizeNeverPersistsBelowOne() = runBlocking {
        val repository = AndroidSettingsRepository(context)

        repository.setReviewBatchSize(0)

        assertEquals(1, repository.settings.value.reviewBatchSize)
    }

    @Test
    fun reminderSettingsPersistFractionalMinutes() = runBlocking {
        val repository = AndroidSettingsRepository(context)

        repository.setReminderEnabled(true)
        repository.setReminderIntervalMinutes(2.75f)

        val loaded = AndroidSettingsRepository(context).settings.value
        assertTrue(loaded.reminderEnabled)
        assertEquals(2.75f, loaded.reminderIntervalMinutes)
    }

    @Test
    fun reminderIntervalIsBounded() = runBlocking {
        val repository = AndroidSettingsRepository(context)
        repository.setReminderIntervalMinutes(0.1f)
        assertEquals(0.5f, repository.settings.value.reminderIntervalMinutes)
        repository.setReminderIntervalMinutes(999f)
        assertEquals(120f, repository.settings.value.reminderIntervalMinutes)
    }

    @Test
    fun studyOrderAndIndependentLevelFiltersPersist() = runBlocking {
        val repository = AndroidSettingsRepository(context)
        assertEquals(STUDY_ORDER_RANDOM, repository.settings.value.studyOrder)

        repository.setStudyOrder("alphabetical")
        repository.setStudyLevels(setOf("cet4", "cet6"))
        repository.setReviewLevels(setOf("cet6"))
        repository.setReminderLevels(setOf("cet4", "custom"))

        val loaded = AndroidSettingsRepository(context).settings.value
        assertEquals("alphabetical", loaded.studyOrder)
        assertEquals(setOf("CET4", "CET6"), loaded.studyLevels)
        assertEquals(setOf("CET6"), loaded.reviewLevels)
        assertEquals(setOf("CET4", "CUSTOM"), loaded.reminderLevels)
    }

    private fun clearPreferences() {
        context.getSharedPreferences("lexitrack_settings", Context.MODE_PRIVATE)
            .edit()
            .clear()
            .commit()
    }
}
