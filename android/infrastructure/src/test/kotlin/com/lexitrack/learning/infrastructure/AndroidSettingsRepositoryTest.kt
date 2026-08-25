package com.lexitrack.learning.infrastructure

import android.content.Context
import androidx.test.core.app.ApplicationProvider
import com.lexitrack.learning.application.DEFAULT_REVIEW_BATCH_SIZE
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertEquals
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

    private fun clearPreferences() {
        context.getSharedPreferences("lexitrack_settings", Context.MODE_PRIVATE)
            .edit()
            .clear()
            .commit()
    }
}
