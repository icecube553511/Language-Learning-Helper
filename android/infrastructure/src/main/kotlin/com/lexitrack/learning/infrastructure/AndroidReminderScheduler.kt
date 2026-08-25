package com.lexitrack.learning.infrastructure

import android.app.AlarmManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.os.Build
import kotlin.math.roundToLong

/** Schedules one-shot reminders; the receiver schedules the next one after delivery. */
class AndroidReminderScheduler(context: Context) {
    private val appContext = context.applicationContext
    private val alarmManager = appContext.getSystemService(AlarmManager::class.java)

    fun schedule(intervalMinutes: Float) {
        val intent = Intent(appContext, ReminderReceiver::class.java).setAction(ACTION_REMINDER)
        val pending = pendingIntent(intent)
        val triggerAt = System.currentTimeMillis() + (intervalMinutes * 60_000f).roundToLong().coerceAtLeast(30_000L)
        alarmManager.cancel(pending)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S && alarmManager.canScheduleExactAlarms()) {
            alarmManager.setExactAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, triggerAt, pending)
        } else {
            alarmManager.setAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, triggerAt, pending)
        }
    }

    fun cancel() {
        val intent = Intent(appContext, ReminderReceiver::class.java).setAction(ACTION_REMINDER)
        alarmManager.cancel(pendingIntent(intent))
    }

    private fun pendingIntent(intent: Intent): PendingIntent = PendingIntent.getBroadcast(
        appContext,
        REQUEST_CODE,
        intent,
        PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
    )

    companion object {
        const val ACTION_REMINDER = "com.lexitrack.learning.action.LEARNING_REMINDER"
        const val ACTION_BOOT = "android.intent.action.BOOT_COMPLETED"
        private const val REQUEST_CODE = 5017
    }
}
