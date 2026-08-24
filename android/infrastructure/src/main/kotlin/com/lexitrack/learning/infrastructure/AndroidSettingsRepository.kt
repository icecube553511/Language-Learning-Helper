package com.lexitrack.learning.infrastructure

import android.content.Context
import com.lexitrack.learning.application.SettingsRepository
import com.lexitrack.learning.application.UserSettings
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

class AndroidSettingsRepository(context: Context) : SettingsRepository {
    private val preferences = context.applicationContext
        .getSharedPreferences(PREFERENCES_NAME, Context.MODE_PRIVATE)
    private val _settings = MutableStateFlow(
        UserSettings(preferences.getFloat(KEY_FONT_SCALE, 1.0f).coerceIn(0.9f, 1.4f)),
    )

    override val settings: StateFlow<UserSettings> = _settings.asStateFlow()

    override suspend fun setFontScale(scale: Float) {
        val safeScale = scale.coerceIn(0.9f, 1.4f)
        preferences.edit().putFloat(KEY_FONT_SCALE, safeScale).apply()
        _settings.value = UserSettings(safeScale)
    }

    private companion object {
        const val PREFERENCES_NAME = "lexitrack_settings"
        const val KEY_FONT_SCALE = "font_scale"
    }
}
