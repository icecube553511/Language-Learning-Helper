package com.lexitrack.learning.presentation

import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import com.lexitrack.learning.application.AppUseCases
import com.lexitrack.learning.application.CatalogStatus
import com.lexitrack.learning.application.DashboardSnapshot
import com.lexitrack.learning.application.ForecastDay
import com.lexitrack.learning.domain.ImportReport
import com.lexitrack.learning.domain.ReviewRating
import com.lexitrack.learning.domain.VocabularyEntry
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.launch

enum class MainSection {
    DASHBOARD,
    STUDY,
    LIBRARY,
    INSIGHTS,
    SETTINGS,
}

data class MainUiState(
    val section: MainSection = MainSection.DASHBOARD,
    val catalogStatus: CatalogStatus = CatalogStatus(),
    val dashboard: DashboardSnapshot = DashboardSnapshot(0, 0, 0, 0, 0),
    val forecast: List<ForecastDay> = emptyList(),
    val currentCard: VocabularyEntry? = null,
    val answerRevealed: Boolean = false,
    val searchQuery: String = "",
    val searchResults: List<VocabularyEntry> = emptyList(),
    val totalSearchResults: Int = 0,
    val fontScale: Float = 1.0f,
    val importInProgress: Boolean = false,
    val importReport: ImportReport? = null,
    val transientMessage: String? = null,
)

class MainViewModel(
    private val useCases: AppUseCases,
) : ViewModel() {
    private val _uiState = MutableStateFlow(MainUiState())
    val uiState: StateFlow<MainUiState> = _uiState.asStateFlow()

    init {
        viewModelScope.launch {
            combine(
                useCases.words,
                useCases.catalogStatus,
                useCases.schedules,
                useCases.history,
                useCases.settings,
            ) { _, status, _, _, settings -> status to settings }.collect { (status, settings) ->
                refreshDerived(status, settings.fontScale)
            }
        }
        viewModelScope.launch {
            useCases.initialize()
        }
    }

    fun selectSection(section: MainSection) {
        _uiState.value = _uiState.value.copy(section = section)
        if (section == MainSection.STUDY) ensureCurrentCard()
    }

    fun revealAnswer() {
        _uiState.value = _uiState.value.copy(answerRevealed = true)
    }

    fun rateCurrent(rating: ReviewRating) {
        val card = _uiState.value.currentCard ?: return
        viewModelScope.launch {
            useCases.rateWord(card.id, rating)
            _uiState.value = _uiState.value.copy(currentCard = null, answerRevealed = false)
            refreshDerived(useCases.catalogStatus.value, useCases.settings.value.fontScale)
            ensureCurrentCard()
        }
    }

    fun updateSearch(query: String) {
        val matches = useCases.search(query)
        _uiState.value = _uiState.value.copy(
            searchQuery = query,
            searchResults = matches.take(MAX_VISIBLE_SEARCH_RESULTS),
            totalSearchResults = matches.size,
        )
    }

    fun importCsv(bytes: ByteArray) {
        _uiState.value = _uiState.value.copy(importInProgress = true, transientMessage = null)
        viewModelScope.launch {
            runCatching { useCases.importVocabulary(bytes) }
                .onSuccess { report ->
                    _uiState.value = _uiState.value.copy(
                        importInProgress = false,
                        importReport = report,
                    )
                    updateSearch(_uiState.value.searchQuery)
                    ensureCurrentCard()
                }
                .onFailure { error ->
                    _uiState.value = _uiState.value.copy(
                        importInProgress = false,
                        transientMessage = error.message ?: "无法读取该 CSV 文件。",
                    )
                }
        }
    }

    fun reportImportReadFailure(message: String) {
        _uiState.value = _uiState.value.copy(transientMessage = message)
    }

    fun dismissImportReport() {
        _uiState.value = _uiState.value.copy(importReport = null)
    }

    fun dismissMessage() {
        _uiState.value = _uiState.value.copy(transientMessage = null)
    }

    fun setFontScale(scale: Float) {
        _uiState.value = _uiState.value.copy(fontScale = scale.coerceIn(0.9f, 1.4f))
        viewModelScope.launch { useCases.updateFontScale(scale) }
    }

    private fun refreshDerived(status: CatalogStatus, fontScale: Float) {
        val matches = useCases.search(_uiState.value.searchQuery)
        val current = _uiState.value.currentCard?.id?.let { id ->
            useCases.words.value.firstOrNull { it.id == id }
        }
        _uiState.value = _uiState.value.copy(
            catalogStatus = status,
            dashboard = useCases.dashboard(),
            forecast = useCases.forecast(),
            currentCard = current,
            searchResults = matches.take(MAX_VISIBLE_SEARCH_RESULTS),
            totalSearchResults = matches.size,
            fontScale = fontScale,
        )
        if (_uiState.value.section == MainSection.STUDY) ensureCurrentCard()
    }

    private fun ensureCurrentCard() {
        if (_uiState.value.currentCard != null) return
        _uiState.value = _uiState.value.copy(
            currentCard = useCases.nextCard(),
            answerRevealed = false,
        )
    }

    private companion object {
        const val MAX_VISIBLE_SEARCH_RESULTS = 200
    }
}

class MainViewModelFactory(
    private val useCases: AppUseCases,
) : ViewModelProvider.Factory {
    @Suppress("UNCHECKED_CAST")
    override fun <T : ViewModel> create(modelClass: Class<T>): T {
        require(modelClass.isAssignableFrom(MainViewModel::class.java))
        return MainViewModel(useCases) as T
    }
}
