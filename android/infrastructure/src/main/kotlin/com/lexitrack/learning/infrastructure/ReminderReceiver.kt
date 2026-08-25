package com.lexitrack.learning.infrastructure

import android.Manifest
import android.app.NotificationChannel
import android.app.NotificationManager
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import android.util.Log
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat
import com.lexitrack.learning.domain.VocabularyEntry
import com.lexitrack.learning.application.GetReminderCardUseCase
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch

class ReminderReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        val pendingResult = goAsync()
        val appContext = context.applicationContext
        CoroutineScope(Dispatchers.IO).launch {
            val scheduler = AndroidReminderScheduler(appContext)
            try {
                val settingsRepository = AndroidSettingsRepository(appContext)
                val settings = settingsRepository.settings.value
                if (intent.action == AndroidReminderScheduler.ACTION_BOOT || intent.action == Intent.ACTION_TIMEZONE_CHANGED) {
                    if (settings.reminderEnabled) scheduler.schedule(settings.reminderIntervalMinutes)
                    return@launch
                }
                if (!settings.reminderEnabled) return@launch
                if (!NotificationManagerCompat.from(appContext).areNotificationsEnabled()) {
                    settingsRepository.setReminderEnabled(false)
                    scheduler.cancel()
                    return@launch
                }
                val vocabulary = AndroidVocabularyRepository(appContext)
                val reviews = AndroidReviewRepository(appContext)
                vocabulary.initialize()
                val preferences = appContext.getSharedPreferences("lexitrack_settings", Context.MODE_PRIVATE)
                val previousId = preferences.getString(KEY_LAST_REMINDER_WORD, "").orEmpty()
                val entry = GetReminderCardUseCase(
                    vocabulary = vocabulary,
                    reviews = reviews,
                    settings = settingsRepository,
                    time = SystemTimeProvider(),
                )(previousId)
                if (entry != null) {
                    preferences.edit().putString(KEY_LAST_REMINDER_WORD, entry.id).apply()
                    notify(appContext, entry)
                }
                scheduler.schedule(settings.reminderIntervalMinutes)
            } catch (error: Throwable) {
                Log.e(TAG, "Unable to deliver learning reminder", error)
                if (error is SecurityException) {
                    runCatching { AndroidSettingsRepository(appContext).setReminderEnabled(false) }
                    scheduler.cancel()
                } else {
                    runCatching {
                        val settings = AndroidSettingsRepository(appContext).settings.value
                        if (settings.reminderEnabled) scheduler.schedule(settings.reminderIntervalMinutes)
                    }
                }
            } finally {
                pendingResult.finish()
            }
        }
    }

    private fun notify(context: Context, entry: VocabularyEntry) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU &&
            ContextCompat.checkSelfPermission(context, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED
        ) {
            throw SecurityException("POST_NOTIFICATIONS permission is not granted")
        }
        createChannel(context)
        val launchIntent = context.packageManager.getLaunchIntentForPackage(context.packageName)?.apply {
            putExtra(EXTRA_REMINDER_WORD_ID, entry.id)
            flags = Intent.FLAG_ACTIVITY_SINGLE_TOP or Intent.FLAG_ACTIVITY_CLEAR_TOP
        }
        val contentIntent = launchIntent?.let {
            android.app.PendingIntent.getActivity(
                context,
                entry.id.hashCode(),
                it,
                android.app.PendingIntent.FLAG_UPDATE_CURRENT or android.app.PendingIntent.FLAG_IMMUTABLE,
            )
        }
        val text = buildString {
            if (entry.phonetic.isNotBlank()) append(entry.phonetic).append("\n")
            append(entry.meaning)
            entry.examples.take(3).forEach { example ->
                append("\n").append(example.english).append("\n").append(example.chinese)
            }
            if (entry.mnemonic.isNotBlank()) append("\n助记: ").append(entry.mnemonic)
        }
        val notification = NotificationCompat.Builder(context, CHANNEL_ID)
            .setSmallIcon(android.R.drawable.ic_popup_reminder)
            .setContentTitle("学习提醒 · ${entry.word}")
            .setContentText(text)
            .setStyle(NotificationCompat.BigTextStyle().bigText(text))
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .setCategory(NotificationCompat.CATEGORY_REMINDER)
            .setAutoCancel(true)
            .apply { if (contentIntent != null) setContentIntent(contentIntent) }
            .build()
        try {
            NotificationManagerCompat.from(context).notify(NOTIFICATION_ID, notification)
        } catch (error: SecurityException) {
            Log.e(TAG, "Notification permission was revoked", error)
            throw error
        }
    }

    private fun createChannel(context: Context) {
        val channel = NotificationChannel(CHANNEL_ID, "学习单词提醒", NotificationManager.IMPORTANCE_HIGH).apply {
            description = "在设定间隔提醒学习单词"
            enableVibration(true)
        }
        context.getSystemService(NotificationManager::class.java).createNotificationChannel(channel)
    }

    companion object {
        const val EXTRA_REMINDER_WORD_ID = "reminder_word_id"
        private const val CHANNEL_ID = "learning_reminders"
        private const val NOTIFICATION_ID = 7401
        private const val KEY_LAST_REMINDER_WORD = "last_reminder_word"
        private const val TAG = "LexiTrackReminder"
    }
}
