package com.lexitrack.learning.infrastructure

import android.content.Context
import com.lexitrack.learning.application.SettingsRepository
import com.lexitrack.learning.application.DEFAULT_REVIEW_BATCH_SIZE
import com.lexitrack.learning.application.UserSettings
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

class AndroidSettingsRepository(context: Context) : SettingsRepository {
    private val preferences = context.applicationContext
        .getSharedPreferences(PREFERENCES_NAME, Context.MODE_PRIVATE)
    private val _settings = MutableStateFlow(
        loadSettings(),
    )

    override val settings: StateFlow<UserSettings> = _settings.asStateFlow()

    override suspend fun setFontScale(scale: Float) {
        val safeScale = scale.coerceIn(0.9f, 1.4f)
        preferences.edit().putFloat(KEY_FONT_SCALE, safeScale).apply()
        _settings.value = _settings.value.copy(fontScale = safeScale)
    }

    override suspend fun setReviewBatchSize(count: Int) {
        val safeCount = count.coerceAtLeast(1)
        preferences.edit().putInt(KEY_REVIEW_BATCH_SIZE, safeCount).apply()
        _settings.value = _settings.value.copy(reviewBatchSize = safeCount)
    }

    private fun loadSettings() = UserSettings(
        fontScale = preferences.getFloat(KEY_FONT_SCALE, 1.0f).coerceIn(0.9f, 1.4f),
        reviewBatchSize = preferences
            .getInt(KEY_REVIEW_BATCH_SIZE, DEFAULT_REVIEW_BATCH_SIZE)
            .coerceAtLeast(1),
    )

    private companion object {
        const val PREFERENCES_NAME = "lexitrack_settings"
        const val KEY_FONT_SCALE = "font_scale"
        const val KEY_REVIEW_BATCH_SIZE = "review_batch_size"
    }
}
