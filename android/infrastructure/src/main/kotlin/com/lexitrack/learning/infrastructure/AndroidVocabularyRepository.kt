package com.lexitrack.learning.infrastructure

import android.content.Context
import com.lexitrack.learning.application.CatalogStatus
import com.lexitrack.learning.application.VocabularyRepository
import com.lexitrack.learning.domain.ImportReport
import com.lexitrack.learning.domain.VocabularyEntry
import java.io.FileNotFoundException
import java.io.InputStream
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext

class AndroidVocabularyRepository(
    context: Context,
    private val csvParser: CsvVocabularyParser = CsvVocabularyParser(),
) : VocabularyRepository {
    private val appContext = context.applicationContext
    private val preferences = appContext.getSharedPreferences(PREFERENCES_NAME, Context.MODE_PRIVATE)
    private val mutex = Mutex()
    private val importedEntries = mutableListOf<VocabularyEntry>()
    private val _words = MutableStateFlow<List<VocabularyEntry>>(emptyList())
    private val _status = MutableStateFlow(CatalogStatus())
    private var initialized = false

    override val words: StateFlow<List<VocabularyEntry>> = _words.asStateFlow()
    override val status: StateFlow<CatalogStatus> = _status.asStateFlow()

    init {
        val saved = preferences.getString(KEY_IMPORTED, null)
        if (!saved.isNullOrBlank()) {
            runCatching { VocabularyJsonCodec.decodeCatalog(saved, "csv").entries }
                .getOrDefault(emptyList())
                .let(importedEntries::addAll)
        }
    }

    override suspend fun initialize() = mutex.withLock {
        if (initialized) return@withLock
        initialized = true
        val decoded = withContext(Dispatchers.IO) {
            try {
                appContext.assets.open("catalog.json").bufferedReader(Charsets.UTF_8).use { reader ->
                    VocabularyJsonCodec.decodeCatalog(reader.readText())
                }
            } catch (_: FileNotFoundException) {
                CatalogDecodeResult(emptyList(), 0)
            } catch (_: Exception) {
                CatalogDecodeResult(emptyList(), 1)
            }
        }
        _words.value = merge(decoded.entries, importedEntries)
        _status.value = when {
            decoded.entries.isEmpty() && importedEntries.isEmpty() -> CatalogStatus(
                loading = false,
                message = "内置四六级词库尚未生成，可先从 CSV 导入词条。",
                acceptedEntries = 0,
                rejectedEntries = decoded.rejected,
            )
            decoded.rejected > 0 -> CatalogStatus(
                loading = false,
                message = "词库已加载；${decoded.rejected} 个不完整词条未进入学习队列。",
                acceptedEntries = _words.value.size,
                rejectedEntries = decoded.rejected,
            )
            else -> CatalogStatus(
                loading = false,
                message = "四六级词库已就绪。",
                acceptedEntries = _words.value.size,
                rejectedEntries = 0,
            )
        }
    }

    override suspend fun importCsv(input: InputStream): ImportReport = mutex.withLock {
        val batch = withContext(Dispatchers.IO) {
            csvParser.parse(input, _words.value.mapTo(mutableSetOf()) { it.id })
        }
        if (batch.entries.isNotEmpty()) {
            importedEntries += batch.entries
            preferences.edit()
                .putString(KEY_IMPORTED, VocabularyJsonCodec.encodeEntries(importedEntries))
                .apply()
            _words.value = merge(_words.value, batch.entries)
            _status.value = _status.value.copy(acceptedEntries = _words.value.size)
        }
        batch.report
    }

    private fun merge(
        first: List<VocabularyEntry>,
        second: List<VocabularyEntry>,
    ): List<VocabularyEntry> = (first + second)
        .distinctBy { it.id }
        .sortedBy { it.word.lowercase() }

    private companion object {
        const val PREFERENCES_NAME = "lexitrack_vocabulary"
        const val KEY_IMPORTED = "imported_entries"
    }
}
