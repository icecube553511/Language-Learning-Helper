package com.lexitrack.learning.infrastructure

import android.app.AlarmManager
import android.content.Context
import androidx.test.core.app.ApplicationProvider
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.Shadows.shadowOf

@RunWith(RobolectricTestRunner::class)
class AndroidReminderSchedulerTest {
    @Test
    fun scheduleRegistersAndCancelRemovesAlarm() {
        val context = ApplicationProvider.getApplicationContext<Context>()
        val scheduler = AndroidReminderScheduler(context)
        val alarmManager = context.getSystemService(AlarmManager::class.java)
        val shadow = shadowOf(alarmManager)

        scheduler.schedule(0.5f)
        assertNotNull(shadow.scheduledAlarms.singleOrNull())

        scheduler.cancel()
        assertNull(shadow.scheduledAlarms.singleOrNull())
    }
}
