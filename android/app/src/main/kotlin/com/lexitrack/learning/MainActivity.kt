package com.lexitrack.learning

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.runtime.remember
import androidx.lifecycle.lifecycleScope
import androidx.lifecycle.viewmodel.compose.viewModel
import com.lexitrack.learning.presentation.LexiTrackApp
import com.lexitrack.learning.presentation.MainViewModel
import com.lexitrack.learning.presentation.MainViewModelFactory
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

class MainActivity : ComponentActivity() {
    private val container by lazy { AppContainer(applicationContext) }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            val factory = remember { MainViewModelFactory(container.useCases) }
            val viewModel: MainViewModel = viewModel(factory = factory)
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
                onChooseCsv = {
                    launcher.launch(arrayOf("text/csv", "text/comma-separated-values", "text/plain"))
                },
            )
        }
    }
}
