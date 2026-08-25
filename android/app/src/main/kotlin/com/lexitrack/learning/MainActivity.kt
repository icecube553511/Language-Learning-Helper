package com.lexitrack.learning

import android.Manifest
import android.content.pm.PackageManager
import android.os.Bundle
import android.os.Build
import androidx.activity.ComponentActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.runtime.remember
import androidx.compose.runtime.LaunchedEffect
import androidx.lifecycle.lifecycleScope
import androidx.core.content.ContextCompat
import androidx.lifecycle.viewmodel.compose.viewModel
import com.lexitrack.learning.presentation.LexiTrackApp
import com.lexitrack.learning.presentation.MainViewModel
import com.lexitrack.learning.presentation.MainViewModelFactory
import com.lexitrack.learning.infrastructure.AndroidReminderScheduler
import com.lexitrack.learning.infrastructure.ReminderReceiver
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

class MainActivity : ComponentActivity() {
    private val container by lazy { AppContainer(applicationContext) }
    private val reminderScheduler by lazy { AndroidReminderScheduler(applicationContext) }
    private var activeViewModel: MainViewModel? = null
    private var pendingReminderWordId: String? = null
    private var reminderEnabled = false
    private var reminderIntervalMinutes = 30.0f
    private val notificationPermissionLauncher = registerForActivityResult(
        ActivityResultContracts.RequestPermission(),
    ) { granted ->
        if (!granted) {
            reminderEnabled = false
            reminderScheduler.cancel()
            activeViewModel?.setReminderSettings(false, reminderIntervalMinutes)
            activeViewModel?.reportNotificationPermissionDenied()
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        container.useCases.settings.value.let { settings ->
            reminderEnabled = settings.reminderEnabled
            reminderIntervalMinutes = settings.reminderIntervalMinutes
        }
        pendingReminderWordId = intent.getStringExtra(ReminderReceiver.EXTRA_REMINDER_WORD_ID)
        setContent {
            val factory = remember { MainViewModelFactory(container.useCases) }
            val viewModel: MainViewModel = viewModel(factory = factory)
            activeViewModel = viewModel
            val notificationWordId = pendingReminderWordId
            LaunchedEffect(notificationWordId) {
                notificationWordId?.let(viewModel::showWordReminderById)
                pendingReminderWordId = null
            }
            LaunchedEffect(Unit) {
                if (reminderEnabled && Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU &&
                    ContextCompat.checkSelfPermission(this@MainActivity, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED
                ) {
                    notificationPermissionLauncher.launch(Manifest.permission.POST_NOTIFICATIONS)
                }
            }
            val launcher = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
                if (uri == null) return@rememberLauncherForActivityResult
                lifecycleScope.launch {
                    val bytes = runCatching {
                        withContext(Dispatchers.IO) {
                            contentResolver.openInputStream(uri)?.use { it.readBytes() }
                                ?: error("无法打开选择的文件。")
                        }
                    }
                    bytes.onSuccess(viewModel::importCsv)
                        .onFailure { error ->
                            viewModel.reportImportReadFailure(error.message ?: "无法读取选择的文件。")
                        }
                }
            }
            LexiTrackApp(
                viewModel = viewModel,
                onReminderSettingsRequested = { enabled, interval ->
                    reminderEnabled = enabled
                    reminderIntervalMinutes = interval
                    if (!enabled) reminderScheduler.cancel()
                    if (enabled && Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU &&
                        ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED
                    ) {
                        notificationPermissionLauncher.launch(Manifest.permission.POST_NOTIFICATIONS)
                    }
                },
                onChooseCsv = {
                    launcher.launch(arrayOf("text/csv", "text/comma-separated-values", "text/plain"))
                },
            )
        }
    }

    override fun onNewIntent(intent: android.content.Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        intent.getStringExtra(ReminderReceiver.EXTRA_REMINDER_WORD_ID)?.let { wordId ->
            activeViewModel?.showWordReminderById(wordId) ?: run { pendingReminderWordId = wordId }
        }
    }

    override fun onStart() {
        super.onStart()
        activeViewModel?.onAppForeground()
        reminderScheduler.cancel()
    }

    override fun onStop() {
        activeViewModel?.onAppBackground()
        if (reminderEnabled) reminderScheduler.schedule(reminderIntervalMinutes)
        super.onStop()
    }
}
