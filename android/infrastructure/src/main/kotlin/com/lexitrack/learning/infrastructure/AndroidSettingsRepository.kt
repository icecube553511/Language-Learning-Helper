package com.lexitrack.learning.infrastructure

import android.content.Context
import com.lexitrack.learning.application.SettingsRepository
import com.lexitrack.learning.application.DEFAULT_REVIEW_BATCH_SIZE
import com.lexitrack.learning.application.DEFAULT_REMINDER_INTERVAL_MINUTES
import com.lexitrack.learning.application.MAX_REMINDER_INTERVAL_MINUTES
import com.lexitrack.learning.application.MIN_REMINDER_INTERVAL_MINUTES
import com.lexitrack.learning.application.STUDY_ORDER_RANDOM
import com.lexitrack.learning.application.SUPPORTED_VOCABULARY_LEVELS
import com.lexitrack.learning.application.UserSettings
import com.lexitrack.learning.domain.MarkMode
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

    override suspend fun setStudyOrder(order: String) {
        val safeOrder = if (order == "alphabetical") "alphabetical" else STUDY_ORDER_RANDOM
        preferences.edit().putString(KEY_STUDY_ORDER, safeOrder).apply()
        _settings.value = _settings.value.copy(studyOrder = safeOrder)
    }

    override suspend fun setStudyLevels(levels: Set<String>) {
        val safeLevels = levels.map(String::uppercase).toSet()
        preferences.edit().putStringSet(KEY_STUDY_LEVELS, safeLevels).apply()
        _settings.value = _settings.value.copy(studyLevels = safeLevels)
    }

    override suspend fun setReviewLevels(levels: Set<String>) {
        val safeLevels = levels.map(String::uppercase).toSet()
        preferences.edit().putStringSet(KEY_REVIEW_LEVELS, safeLevels).apply()
        _settings.value = _settings.value.copy(reviewLevels = safeLevels)
    }

    override suspend fun setReminderLevels(levels: Set<String>) {
        val safeLevels = levels.map(String::uppercase).filter { it in SUPPORTED_VOCABULARY_LEVELS }.toSet()
        preferences.edit().putStringSet(KEY_REMINDER_LEVELS, safeLevels).apply()
        _settings.value = _settings.value.copy(reminderLevels = safeLevels)
    }

    override suspend fun setReminderEnabled(enabled: Boolean) {
        preferences.edit().putBoolean(KEY_REMINDER_ENABLED, enabled).apply()
        _settings.value = _settings.value.copy(reminderEnabled = enabled)
    }

    override suspend fun setReminderIntervalMinutes(minutes: Float) {
        val safeMinutes = minutes.coerceIn(
            MIN_REMINDER_INTERVAL_MINUTES,
            MAX_REMINDER_INTERVAL_MINUTES,
        )
        preferences.edit().putFloat(KEY_REMINDER_INTERVAL_MINUTES, safeMinutes).apply()
        _settings.value = _settings.value.copy(reminderIntervalMinutes = safeMinutes)
    }

    override suspend fun setMarkMode(mode: MarkMode) {
        preferences.edit().putString(KEY_MARK_MODE, mode.name).apply()
        _settings.value = _settings.value.copy(markMode = mode)
    }

    private fun loadSettings() = UserSettings(
        fontScale = preferences.getFloat(KEY_FONT_SCALE, 1.0f).coerceIn(0.9f, 1.4f),
        reviewBatchSize = preferences
            .getInt(KEY_REVIEW_BATCH_SIZE, DEFAULT_REVIEW_BATCH_SIZE)
            .coerceAtLeast(1),
        studyOrder = preferences.getString(KEY_STUDY_ORDER, STUDY_ORDER_RANDOM)
            .let { if (it == "alphabetical") "alphabetical" else STUDY_ORDER_RANDOM },
        studyLevels = preferences.getStringSet(KEY_STUDY_LEVELS, emptySet()).orEmpty()
            .map(String::uppercase).toSet(),
        reviewLevels = preferences.getStringSet(KEY_REVIEW_LEVELS, emptySet()).orEmpty()
            .map(String::uppercase).toSet(),
        reminderLevels = preferences.getStringSet(KEY_REMINDER_LEVELS, emptySet()).orEmpty()
            .map(String::uppercase).filter { it in SUPPORTED_VOCABULARY_LEVELS }.toSet(),
        reminderEnabled = preferences.getBoolean(KEY_REMINDER_ENABLED, false),
        reminderIntervalMinutes = preferences
            .getFloat(KEY_REMINDER_INTERVAL_MINUTES, DEFAULT_REMINDER_INTERVAL_MINUTES)
            .coerceIn(MIN_REMINDER_INTERVAL_MINUTES, MAX_REMINDER_INTERVAL_MINUTES),
        markMode = runCatching { MarkMode.valueOf(preferences.getString(KEY_MARK_MODE, MarkMode.ASK.name) ?: MarkMode.ASK.name) }
            .getOrDefault(MarkMode.ASK),
    )

    private companion object {
        const val PREFERENCES_NAME = "lexitrack_settings"
        const val KEY_FONT_SCALE = "font_scale"
        const val KEY_REVIEW_BATCH_SIZE = "review_batch_size"
        const val KEY_STUDY_ORDER = "study_order"
        const val KEY_STUDY_LEVELS = "study_levels"
        const val KEY_REVIEW_LEVELS = "review_levels"
        const val KEY_REMINDER_LEVELS = "reminder_levels"
        const val KEY_REMINDER_ENABLED = "reminder_enabled"
        const val KEY_REMINDER_INTERVAL_MINUTES = "reminder_interval_minutes"
        const val KEY_MARK_MODE = "dictation_mark_mode"
    }
}
