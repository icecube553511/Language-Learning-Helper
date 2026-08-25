package com.lexitrack.learning.presentation

import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import com.lexitrack.learning.application.AppUseCases
import com.lexitrack.learning.application.CatalogStatus
import com.lexitrack.learning.application.DashboardSnapshot
import com.lexitrack.learning.application.ForecastDay
import com.lexitrack.learning.application.UserSettings
import com.lexitrack.learning.domain.ImportReport
import com.lexitrack.learning.domain.ReviewRating
import com.lexitrack.learning.domain.VocabularyEntry
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch

enum class MainSection {
    DASHBOARD,
    STUDY,
    REVIEW,
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
    val reviewQueue: List<VocabularyEntry> = emptyList(),
    val reviewCard: VocabularyEntry? = null,
    val reviewAnswerRevealed: Boolean = false,
    val reviewSessionSize: Int = 0,
    val reviewSessionStarted: Boolean = false,
    val learntWordCount: Int = 0,
    val reviewBatchSize: Int = 20,
    val searchQuery: String = "",
    val searchResults: List<VocabularyEntry> = emptyList(),
    val totalSearchResults: Int = 0,
    val fontScale: Float = 1.0f,
    val importInProgress: Boolean = false,
    val importReport: ImportReport? = null,
    val transientMessage: String? = null,
    val reviewReminderMessage: String? = null,
)

class MainViewModel(
    private val useCases: AppUseCases,
) : ViewModel() {
    private var lastRemindedDueCount = 0
    private var studyRatingInProgress = false
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
            ) { _, status, _, _, settings -> status to settings }
                .combine(useCases.learntWords) { (status, settings), _ -> status to settings }
                .collect { (status, settings) -> refreshDerived(status, settings) }
        }
        viewModelScope.launch {
            useCases.initialize()
        }
        viewModelScope.launch {
            while (isActive) {
                delay(60_000)
                refreshDerived(useCases.catalogStatus.value, useCases.settings.value)
            }
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
        val state = _uiState.value
        val card = state.currentCard ?: return
        if (!state.answerRevealed || studyRatingInProgress) return
        studyRatingInProgress = true
        _uiState.value = state.copy(currentCard = null, answerRevealed = false)
        viewModelScope.launch {
            try {
                useCases.rateWord(card.id, rating)
            } finally {
                studyRatingInProgress = false
                _uiState.value = _uiState.value.copy(currentCard = null, answerRevealed = false)
                refreshDerived(useCases.catalogStatus.value, useCases.settings.value)
                ensureCurrentCard()
            }
        }
    }

    fun startReviewSession() {
        val queue = useCases.startReviewSession()
        _uiState.value = _uiState.value.copy(
            reviewQueue = queue,
            reviewCard = queue.firstOrNull(),
            reviewAnswerRevealed = false,
            reviewSessionSize = queue.size,
            reviewSessionStarted = true,
        )
    }

    fun revealReviewAnswer() {
        if (_uiState.value.reviewCard == null) return
        _uiState.value = _uiState.value.copy(reviewAnswerRevealed = true)
    }

    fun rateReviewCurrent(rating: ReviewRating) {
        val state = _uiState.value
        val card = state.reviewCard ?: return
        if (!state.reviewAnswerRevealed) return
        val remaining = state.reviewQueue.drop(1)
        _uiState.value = state.copy(
            reviewQueue = remaining,
            reviewCard = remaining.firstOrNull(),
            reviewAnswerRevealed = false,
        )
        viewModelScope.launch {
            useCases.rateReviewWord(card.id, rating)
            refreshDerived(useCases.catalogStatus.value, useCases.settings.value)
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

    fun dismissReviewReminder() {
        _uiState.value = _uiState.value.copy(reviewReminderMessage = null)
    }

    fun setFontScale(scale: Float) {
        _uiState.value = _uiState.value.copy(fontScale = scale.coerceIn(0.9f, 1.4f))
        viewModelScope.launch { useCases.updateFontScale(scale) }
    }

    fun setReviewBatchSize(count: Int) {
        val bounded = count.coerceIn(1, maxOf(1, _uiState.value.learntWordCount))
        _uiState.value = _uiState.value.copy(reviewBatchSize = bounded)
        viewModelScope.launch {
            useCases.updateReviewBatchSize(bounded)
            refreshDerived(useCases.catalogStatus.value, useCases.settings.value)
        }
    }

    private fun refreshDerived(status: CatalogStatus, settings: UserSettings) {
        val matches = useCases.search(_uiState.value.searchQuery)
        val learntCount = useCases.learntWords.value.size
        val current = _uiState.value.currentCard?.id?.let { id ->
            useCases.words.value.firstOrNull { it.id == id }
        }
        val dashboard = useCases.dashboard()
        val reminder = if (dashboard.dueNow > 0 && dashboard.dueNow != lastRemindedDueCount) {
            lastRemindedDueCount = dashboard.dueNow
            "有 ${dashboard.dueNow} 个单词已按记忆曲线到期。"
        } else {
            if (dashboard.dueNow == 0) lastRemindedDueCount = 0
            _uiState.value.reviewReminderMessage
        }
        _uiState.value = _uiState.value.copy(
            catalogStatus = status,
            dashboard = dashboard,
            forecast = useCases.forecast(),
            currentCard = current,
            searchResults = matches.take(MAX_VISIBLE_SEARCH_RESULTS),
            totalSearchResults = matches.size,
            fontScale = settings.fontScale,
            learntWordCount = learntCount,
            reviewBatchSize = settings.reviewBatchSize.coerceIn(1, maxOf(1, learntCount)),
            reviewReminderMessage = reminder,
        )
        if (_uiState.value.section == MainSection.STUDY && !studyRatingInProgress) ensureCurrentCard()
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
