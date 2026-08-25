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
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlin.random.Random

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
    val studyOrder: String = "random",
    val studyLevels: Set<String> = emptySet(),
    val reviewLevels: Set<String> = emptySet(),
    val availableLevels: List<String> = listOf("CET4", "CET6", "CUSTOM"),
    val searchQuery: String = "",
    val searchResults: List<VocabularyEntry> = emptyList(),
    val totalSearchResults: Int = 0,
    val selectedVocabularyIds: Set<String> = emptySet(),
    val fontScale: Float = 1.0f,
    val importInProgress: Boolean = false,
    val importReport: ImportReport? = null,
    val transientMessage: String? = null,
    val reviewReminderMessage: String? = null,
    val reminderEnabled: Boolean = false,
    val reminderIntervalMinutes: Float = 30.0f,
    val wordReminderCard: VocabularyEntry? = null,
)

class MainViewModel(
    private val useCases: AppUseCases,
) : ViewModel() {
    private var lastRemindedDueCount = 0
    private var studyRatingInProgress = false
    private var wordReminderJob: Job? = null
    private var wordReminderIsPreview = false
    private var previousReminderWordId = ""
    private var pendingReminderWordId: String? = null
    private var appInForeground = true
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
            combine(useCases.words, useCases.settings) { words, settings -> words to settings }
                .collect { (words, settings) ->
                    scheduleWordReminder(words, settings)
                }
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

    fun toggleVocabularySelection(wordId: String) {
        val selected = _uiState.value.selectedVocabularyIds
        _uiState.value = _uiState.value.copy(
            selectedVocabularyIds = if (wordId in selected) selected - wordId else selected + wordId,
        )
    }

    fun updateSelectedVocabularyLabels(levels: Set<String>, tags: Set<String>) {
        val selected = _uiState.value.selectedVocabularyIds
        if (selected.isEmpty()) return
        viewModelScope.launch {
            runCatching { useCases.updateVocabularyLabels(selected, levels, tags) }
                .onSuccess { count ->
                    _uiState.value = _uiState.value.copy(
                        selectedVocabularyIds = emptySet(),
                        transientMessage = "已更新 $count 个自定义词条。",
                    )
                    updateSearch(_uiState.value.searchQuery)
                }
                .onFailure { error ->
                    _uiState.value = _uiState.value.copy(transientMessage = error.message ?: "无法修改标签。")
                }
        }
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

    fun reportNotificationPermissionDenied() {
        _uiState.value = _uiState.value.copy(
            transientMessage = "通知权限未开启，Android 后台无法显示单词提醒。请在系统设置中允许通知。",
        )
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

    fun setStudyOrder(order: String) {
        _uiState.value = _uiState.value.copy(studyOrder = order, currentCard = null, answerRevealed = false)
        viewModelScope.launch {
            useCases.updateStudyOrder(order)
            refreshDerived(useCases.catalogStatus.value, useCases.settings.value)
        }
    }

    fun setStudyLevels(levels: Set<String>) {
        val normalized = levels.map(String::uppercase).toSet()
        _uiState.value = _uiState.value.copy(studyLevels = normalized, currentCard = null, answerRevealed = false)
        viewModelScope.launch {
            useCases.updateStudyLevels(normalized)
            refreshDerived(useCases.catalogStatus.value, useCases.settings.value)
        }
    }

    fun setReviewLevels(levels: Set<String>) {
        val normalized = levels.map(String::uppercase).toSet()
        _uiState.value = _uiState.value.copy(reviewLevels = normalized, reviewQueue = emptyList(), reviewCard = null, reviewSessionStarted = false)
        viewModelScope.launch { useCases.updateReviewLevels(normalized) }
    }

    fun setReminderSettings(enabled: Boolean, intervalMinutes: Float) {
        if (intervalMinutes !in 0.5f..120.0f) {
            _uiState.value = _uiState.value.copy(
                transientMessage = "提醒间隔需在 0.5 到 120 分钟之间",
            )
            return
        }
        _uiState.value = _uiState.value.copy(
            reminderEnabled = enabled,
            reminderIntervalMinutes = intervalMinutes,
            wordReminderCard = if (enabled) _uiState.value.wordReminderCard else null,
        )
        viewModelScope.launch { useCases.updateReminderSettings(enabled, intervalMinutes) }
    }

    fun previewWordReminder() {
        showWordReminder(useCases.words.value, preview = true)
    }

    fun showWordReminderById(wordId: String) {
        pendingReminderWordId = wordId
        useCases.words.value.firstOrNull { it.id == wordId }?.let { card ->
            pendingReminderWordId = null
            wordReminderIsPreview = false
            _uiState.value = _uiState.value.copy(wordReminderCard = card)
        }
    }

    fun onAppBackground() {
        appInForeground = false
        wordReminderJob?.cancel()
        wordReminderJob = null
    }

    fun onAppForeground() {
        appInForeground = true
        scheduleWordReminder(useCases.words.value, useCases.settings.value)
    }

    fun dismissWordReminder() {
        val wasPreview = wordReminderIsPreview
        wordReminderIsPreview = false
        _uiState.value = _uiState.value.copy(wordReminderCard = null)
        if (!wasPreview) scheduleWordReminder(useCases.words.value, useCases.settings.value)
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
            studyOrder = settings.studyOrder,
            studyLevels = settings.studyLevels,
            reviewLevels = settings.reviewLevels,
            availableLevels = useCases.words.value.flatMap { it.levels }.map(String::uppercase).toSet().ifEmpty { setOf("CET4", "CET6", "CUSTOM") }.sorted(),
            reminderEnabled = settings.reminderEnabled,
            reminderIntervalMinutes = settings.reminderIntervalMinutes,
            reviewReminderMessage = reminder,
        )
        pendingReminderWordId?.let { wordId ->
            useCases.words.value.firstOrNull { it.id == wordId }?.let { card ->
                pendingReminderWordId = null
                _uiState.value = _uiState.value.copy(wordReminderCard = card)
            }
        }
        if (_uiState.value.section == MainSection.STUDY && !studyRatingInProgress) ensureCurrentCard()
    }

    private fun ensureCurrentCard() {
        if (_uiState.value.currentCard != null) return
        _uiState.value = _uiState.value.copy(
            currentCard = useCases.nextCard(),
            answerRevealed = false,
        )
    }

    private fun scheduleWordReminder(
        words: List<VocabularyEntry>,
        settings: UserSettings,
        delayMinutes: Float = settings.reminderIntervalMinutes,
    ) {
        wordReminderJob?.cancel()
        if (!appInForeground || !settings.reminderEnabled || words.isEmpty()) return
        wordReminderJob = viewModelScope.launch {
            delay((delayMinutes * 60_000).toLong().coerceAtLeast(1L))
            showWordReminder(words, preview = false)
        }
    }

    private fun showWordReminder(words: List<VocabularyEntry>, preview: Boolean) {
        if (words.isEmpty()) {
            if (preview) {
                _uiState.value = _uiState.value.copy(transientMessage = "当前词库中没有可展示的单词。")
            }
            return
        }
        val now = System.currentTimeMillis() / 1000.0
        val dueIds = useCases.schedules.value
            .filterValues { it.lastReviewedAtUtc != null && it.dueAtUtc <= now }
            .keys
        val candidates = words.filter { it.id in dueIds }.ifEmpty { words }
        val freshCandidates = candidates.filter { it.id != previousReminderWordId }.ifEmpty { candidates }
        val card = freshCandidates[Random.nextInt(freshCandidates.size)]
        previousReminderWordId = card.id
        wordReminderIsPreview = preview
        _uiState.value = _uiState.value.copy(wordReminderCard = card)
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
