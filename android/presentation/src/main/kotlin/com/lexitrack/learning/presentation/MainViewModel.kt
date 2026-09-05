package com.lexitrack.learning.presentation

import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import com.lexitrack.learning.application.AppUseCases
import com.lexitrack.learning.application.CatalogStatus
import com.lexitrack.learning.application.DashboardSnapshot
import com.lexitrack.learning.application.DEFAULT_FONT_SCALE
import com.lexitrack.learning.application.ForecastDay
import com.lexitrack.learning.application.UserSettings
import com.lexitrack.learning.application.LibraryGroup
import com.lexitrack.learning.application.ExportedDictation
import com.lexitrack.learning.application.sanitizeFontScale
import com.lexitrack.learning.application.DictationDraftSyncConflict
import com.lexitrack.learning.application.DictationDraftSyncResult
import com.lexitrack.learning.application.DictationDraftSyncStatus
import com.lexitrack.learning.application.makeDictationDraftSyncEnvelope
import com.lexitrack.learning.application.reconcileDictationDraftSyncEnvelopes
import com.lexitrack.learning.domain.ImportReport
import com.lexitrack.learning.domain.DictationDocument
import com.lexitrack.learning.domain.DictationDocumentOptions
import com.lexitrack.learning.domain.DictationFormat
import com.lexitrack.learning.domain.DictationMissingField
import com.lexitrack.learning.domain.MarkMode
import com.lexitrack.learning.domain.ReviewRating
import com.lexitrack.learning.domain.VocabularyEntry
import com.lexitrack.learning.domain.DictationDraft
import com.lexitrack.learning.domain.DictationGroupDraft
import com.lexitrack.learning.domain.DictationDraftSyncMetadata
import com.lexitrack.learning.domain.dictationRangeIds
import com.lexitrack.learning.domain.nearestDictationId
import com.lexitrack.learning.domain.sanitizeDictationDraft
import com.lexitrack.learning.domain.normalizeWordId
import com.lexitrack.learning.domain.normalizeDictationGroupKey
import com.lexitrack.learning.domain.BubbleDefinition
import kotlinx.coroutines.delay
import kotlinx.coroutines.Job
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch

enum class MainSection {
    DASHBOARD,
    STUDY,
    REVIEW,
    DICTATION,
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
    val dictationEntries: List<VocabularyEntry> = emptyList(),
    val dictationSelectedIds: Set<String> = emptySet(),
    /** Explicit random candidate subset; null means use the complete scope. */
    val dictationRandomCandidateIds: Set<String>? = null,
    val dictationGeneratedIds: Set<String> = emptySet(),
    /** Shared selection and browsing state for both generation modes. */
    val dictationGroupDrafts: Map<String, DictationGroupDraft> = emptyMap(),
    val dictationScopeGroup: String = "all",
    val dictationOpenGroup: String? = null,
    val dictationManualMode: Boolean = false,
    val dictationRangeEnabled: Boolean = true,
    val dictationDirty: Boolean = false,
    val dictationDraftRestored: Boolean = false,
    /** Monotonic key so Compose controls rehydrate after a remote pull too. */
    val dictationDraftRestoreGeneration: Long = 0L,
    val dictationLeaveRequested: Boolean = false,
    val dictationPendingSection: MainSection? = null,
    val dictationCount: Int = 10,
    val dictationIncludeEvaluated: Boolean = false,
    val dictationFormats: Set<DictationFormat> = setOf(DictationFormat.DOCX, DictationFormat.PDF),
    val dictationFontSizePt: Int = 12,
    val dictationMissingFields: Set<DictationMissingField> = setOf(DictationMissingField.WORD),
    val dictationShowInitial: Boolean = false,
    val dictationIncludeExamples: Boolean = false,
    val dictationIncludeExampleChinese: Boolean = false,
    val dictationCustomExample: String = "",
    val dictationSyncMetadata: DictationDraftSyncMetadata = DictationDraftSyncMetadata(),
    val dictationSyncStatus: DictationDraftSyncStatus = DictationDraftSyncStatus.DISABLED,
    val dictationSyncMessage: String? = null,
    val dictationSyncConflict: DictationDraftSyncConflict? = null,
    val dictationSyncInProgress: Boolean = false,
    val dictationDocument: DictationDocument? = null,
    val dictationExports: List<ExportedDictation> = emptyList(),
    val dictationPreparing: Boolean = false,
    val dictationLoading: Boolean = false,
    val dictationMarkMode: MarkMode = MarkMode.ASK,
    val reviewSessionSize: Int = 0,
    val reviewSessionStarted: Boolean = false,
    val learntWordCount: Int = 0,
    val reviewBatchSize: Int = 20,
    val studyOrder: String = "random",
    val studyLevels: Set<String> = emptySet(),
    val reviewLevels: Set<String> = emptySet(),
    val reminderLevels: Set<String> = emptySet(),
    val availableLevels: List<String> = listOf("CET4", "CET6", "CUSTOM"),
    val searchQuery: String = "",
    val searchResults: List<VocabularyEntry> = emptyList(),
    val totalSearchResults: Int = 0,
    val selectedVocabularyIds: Set<String> = emptySet(),
    val libraryGroup: String? = null,
    val libraryGroups: List<LibraryGroup> = emptyList(),
    val fontScale: Float = DEFAULT_FONT_SCALE,
    val importInProgress: Boolean = false,
    val importReport: ImportReport? = null,
    val transientMessage: String? = null,
    val reviewReminderMessage: String? = null,
    val reminderEnabled: Boolean = false,
    val reminderIntervalMinutes: Float = 30.0f,
    val wordReminderCard: VocabularyEntry? = null,
)


internal fun resolveReviewReminderMessage(
    dueNow: Int,
    lastRemindedDueCount: Int,
    currentMessage: String?,
): Pair<String?, Int> {
    return when {
        dueNow > 0 && dueNow != lastRemindedDueCount ->
            "有 $dueNow 个单词已按记忆曲线到期。" to dueNow
        dueNow == 0 -> null to 0
        else -> currentMessage to lastRemindedDueCount
    }
}

internal fun activeDictationSelectionAfterModeSwitch(
    manual: Boolean,
    manualIds: Set<String>,
    randomIds: Set<String>?,
): Set<String> = if (manual) randomIds.orEmpty() else manualIds


class MainViewModel(
    private val useCases: AppUseCases,
) : ViewModel() {
    private var lastRemindedDueCount = 0
    private var studyRatingInProgress = false
    private var reviewRatingInProgress = false
    private var wordReminderJob: Job? = null
    private var wordReminderIsPreview = false
    private var previousReminderWordId = ""
    private var pendingReminderWordId: String? = null
    private var appInForeground = true
    private var dictationLoadingJob: Job? = null
    private var dictationSyncPullJob: Job? = null
    private var dictationSyncPushJob: Job? = null
    private var dictationSyncPushGeneration: Long = 0
    private val _uiState = MutableStateFlow(MainUiState())
    val uiState: StateFlow<MainUiState> = _uiState.asStateFlow()
    private val _feedbackEvents = MutableSharedFlow<FeedbackRequest>(extraBufferCapacity = 64)
    val feedbackEvents: SharedFlow<FeedbackRequest> = _feedbackEvents.asSharedFlow()

    /** Keep the flattened selection as a compatibility view over group state. */
    private fun mergeDictationSelection(
        state: MainUiState,
        group: String,
        updatedGroup: DictationGroupDraft,
    ): Set<String> {
        val represented = state.dictationGroupDrafts.values
            .flatMap { it.selectedIds }
            .map(::normalizeWordId)
            .toSet()
        val activeSelection = if (state.dictationManualMode) {
            state.dictationSelectedIds
        } else {
            state.dictationRandomCandidateIds.orEmpty()
        }
        val orphaned = activeSelection
            .map(::normalizeWordId)
            .filter { it !in represented }
            .toSet()
        return orphaned + state.dictationGroupDrafts
            .filterKeys { it != group }
            .values
            .flatMap { it.selectedIds }
            .map(::normalizeWordId)
            .toSet() + updatedGroup.selectedIds.map(::normalizeWordId)
    }

    fun lookupWordBubble(token: String, contextExample: String = ""): BubbleDefinition =
        useCases.lookupWord(token, contextExample)

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
            // Draft loading is intentionally sequenced after catalog loading;
            // otherwise valid IDs could be mistaken for stale IDs at startup.
            val draftStore = useCases.dictationDraft
            val saved = draftStore.load()
            if (saved != null) restoreDictationDraft(saved)
            else _uiState.value = _uiState.value.copy(
                dictationDraftRestored = true,
                dictationSyncMetadata = draftStore.loadSyncMetadata() ?: DictationDraftSyncMetadata(),
            )
            // Pull only after the catalog and local snapshot are ready.  The
            // default composition root supplies a disabled adapter, which is
            // an explicit no-network no-op.
            pullDictationDraft()
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
        val currentState = _uiState.value
        if (section != MainSection.DICTATION &&
            currentState.section == MainSection.DICTATION &&
            currentState.dictationDirty
        ) {
            _uiState.value = currentState.copy(
                dictationPendingSection = section,
                dictationLeaveRequested = true,
            )
            return
        }
        if (section != MainSection.DICTATION) stopDictationLoading()
        _uiState.value = _uiState.value.copy(section = section)
        if (section == MainSection.STUDY) ensureCurrentCard()
        if (section == MainSection.DICTATION) {
            startDictationLoading()
            pullDictationDraft()
        }
    }

    private fun startDictationLoading() {
        dictationLoadingJob?.cancel()
        _uiState.value = _uiState.value.copy(dictationLoading = true)
        dictationLoadingJob = viewModelScope.launch {
            delay(dictationLoadingDelayMs())
            _uiState.value = _uiState.value.copy(dictationLoading = false)
            dictationLoadingJob = null
        }
    }

    private fun stopDictationLoading() {
        dictationLoadingJob?.cancel()
        dictationLoadingJob = null
        if (_uiState.value.dictationLoading) {
            _uiState.value = _uiState.value.copy(dictationLoading = false)
        }
    }

    fun revealAnswer() {
        _uiState.value = _uiState.value.copy(answerRevealed = true)
    }

    fun rateCurrent(rating: ReviewRating, origin: FeedbackOrigin? = null): Boolean {
        val state = _uiState.value
        val card = state.currentCard ?: return false
        if (!state.answerRevealed || studyRatingInProgress) return false
        studyRatingInProgress = true
        viewModelScope.launch {
            var succeeded = false
            try {
                useCases.rateWord(card.id, rating)
                origin?.let {
                    _feedbackEvents.emit(FeedbackRequest(FeedbackKind.STUDY, it))
                }
                succeeded = true
                _uiState.value = _uiState.value.copy(currentCard = null, answerRevealed = false)
            } catch (cancelled: CancellationException) {
                throw cancelled
            } catch (error: Exception) {
                _uiState.value = _uiState.value.copy(
                    currentCard = card,
                    answerRevealed = true,
                    transientMessage = error.message ?: "无法保存学习结果。",
                )
            } finally {
                studyRatingInProgress = false
                refreshDerived(useCases.catalogStatus.value, useCases.settings.value)
                if (succeeded && _uiState.value.section == MainSection.STUDY) ensureCurrentCard()
            }
        }
        return true
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

    fun toggleDictationSelection(wordId: String) {
        val state = _uiState.value
        val canonicalId = normalizeWordId(wordId)
        if (canonicalId.isBlank()) return
        val selected = if (state.dictationManualMode) {
            state.dictationSelectedIds
        } else {
            state.dictationRandomCandidateIds.orEmpty()
        }
        val adding = canonicalId !in selected
        val next = if (adding) selected + canonicalId else selected - canonicalId
        val group = state.dictationOpenGroup ?: state.dictationScopeGroup
        val groupEntries = dictationEntriesInGroup(state.dictationEntries, group)
        val previousGroup = state.dictationGroupDrafts[group] ?: DictationGroupDraft()
        val canonicalGroupIds = groupEntries.mapTo(mutableSetOf()) { normalizeWordId(it.id) }
        val nextAnchor = if (adding) canonicalId else {
            val remainingInGroup = previousGroup.selectedIds.map(::normalizeWordId).toSet() - canonicalId
            val reference = previousGroup.endpointId ?: canonicalId
            nearestDictationId(groupEntries, reference, remainingInGroup)
        }
        val nextGroup = previousGroup.copy(
            selectedIds = previousGroup.selectedIds
                .map(::normalizeWordId)
                .let { if (adding) it + canonicalId else it - canonicalId }
                .intersect(canonicalGroupIds),
            anchorId = nextAnchor,
            endpointId = if (adding) null else previousGroup.endpointId
                ?.let(::normalizeWordId)
                ?.takeIf { it in next },
        )
        val merged = mergeDictationSelection(state, group, nextGroup)
        _uiState.value = state.copy(
            dictationSelectedIds = if (state.dictationManualMode) merged else state.dictationSelectedIds,
            dictationRandomCandidateIds = if (!state.dictationManualMode) merged else state.dictationRandomCandidateIds,
            dictationGroupDrafts = state.dictationGroupDrafts + (group to nextGroup),
            dictationRangeEnabled = if (adding) true else state.dictationRangeEnabled,
            dictationDirty = true,
        )
    }

    fun setDictationSelection(wordIds: Collection<String>, selected: Boolean) {
        val state = _uiState.value
        val canonicalIds = wordIds.map(::normalizeWordId).filter(String::isNotBlank).toSet()
        if (canonicalIds.isEmpty()) return
        val current = (if (state.dictationManualMode) {
            state.dictationSelectedIds
        } else {
            state.dictationRandomCandidateIds.orEmpty()
        }).toMutableSet()
        if (selected) current.addAll(canonicalIds) else current.removeAll(canonicalIds)
        val group = state.dictationOpenGroup ?: state.dictationScopeGroup
        val entries = dictationEntriesInGroup(state.dictationEntries, group)
        val previousGroup = state.dictationGroupDrafts[group] ?: DictationGroupDraft()
        val anchor = if (selected) canonicalIds.lastOrNull() else {
            val reference = previousGroup.endpointId ?: canonicalIds.lastOrNull()
            nearestDictationId(entries, reference, previousGroup.selectedIds.map(::normalizeWordId).toSet() - canonicalIds)
        }
        val canonicalGroupIds = entries.mapTo(mutableSetOf()) { normalizeWordId(it.id) }
        val groupDraft = (state.dictationGroupDrafts[group] ?: DictationGroupDraft()).copy(
            selectedIds = previousGroup.selectedIds
                .map(::normalizeWordId)
                .let { if (selected) it + canonicalIds else it - canonicalIds }
                .intersect(canonicalGroupIds),
            anchorId = anchor,
            endpointId = if (selected) null else previousGroup.endpointId
                ?.let(::normalizeWordId)
                ?.takeIf { it in current },
        )
        val merged = mergeDictationSelection(state, group, groupDraft)
        _uiState.value = state.copy(
            dictationSelectedIds = if (state.dictationManualMode) merged else state.dictationSelectedIds,
            dictationRandomCandidateIds = if (!state.dictationManualMode) merged else state.dictationRandomCandidateIds,
            dictationGroupDrafts = state.dictationGroupDrafts + (group to groupDraft),
            dictationRangeEnabled = if (selected) true else state.dictationRangeEnabled,
            dictationDirty = true,
        )
    }

    /** Add the inclusive anchor-to-endpoint range for one group. */
    fun selectDictationRangeToHere(group: String, endpointId: String) {
        val state = _uiState.value
        val cleanGroup = normalizeDictationGroupKey(group)
        val draft = state.dictationGroupDrafts[cleanGroup] ?: return
        val anchor = draft.anchorId ?: return
        if (!state.dictationRangeEnabled) return
        val entries = dictationEntriesInGroup(state.dictationEntries, cleanGroup)
        val canonicalEndpoint = normalizeWordId(endpointId)
        if (canonicalEndpoint.isBlank()) return
        val range = dictationRangeIds(entries, anchor, canonicalEndpoint)
        if (range.isEmpty()) return
        val updatedGroup = draft.copy(
            selectedIds = draft.selectedIds.map(::normalizeWordId).toSet() + range,
            anchorId = canonicalEndpoint,
            endpointId = canonicalEndpoint,
        )
        val merged = mergeDictationSelection(state, cleanGroup, updatedGroup)
        _uiState.value = state.copy(
            dictationSelectedIds = if (state.dictationManualMode) merged else state.dictationSelectedIds,
            dictationRandomCandidateIds = if (!state.dictationManualMode) merged else state.dictationRandomCandidateIds,
            dictationGroupDrafts = state.dictationGroupDrafts + (cleanGroup to updatedGroup),
            dictationRangeEnabled = true,
            dictationDirty = true,
        )
    }

    fun endDictationRange(group: String? = null) {
        val state = _uiState.value
        val key = normalizeDictationGroupKey(group ?: state.dictationOpenGroup ?: state.dictationScopeGroup)
        val draft = state.dictationGroupDrafts[key] ?: return
        _uiState.value = state.copy(
            dictationGroupDrafts = state.dictationGroupDrafts + (key to draft.copy(anchorId = null, endpointId = null)),
            dictationRangeEnabled = false,
            dictationDirty = true,
        )
    }

    fun setDictationGroup(group: String, open: Boolean = true) {
        val state = _uiState.value
        val cleanGroup = normalizeDictationGroupKey(group)
        val updatedGroups = state.dictationGroupDrafts.toMutableMap()
        val currentGroup = updatedGroups[cleanGroup] ?: DictationGroupDraft()
        updatedGroups[cleanGroup] = currentGroup.copy(expanded = open)
        _uiState.value = state.copy(
            dictationScopeGroup = if (state.dictationManualMode) state.dictationScopeGroup else cleanGroup,
            dictationOpenGroup = if (open) cleanGroup else null,
            dictationGroupDrafts = updatedGroups,
            dictationDirty = true,
        )
    }

    fun setDictationManualMode(manual: Boolean) {
        val state = _uiState.value
        if (state.dictationManualMode == manual) return
        val activeSelection = activeDictationSelectionAfterModeSwitch(
            manual = manual,
            manualIds = state.dictationSelectedIds,
            randomIds = state.dictationRandomCandidateIds,
        )
        _uiState.value = state.copy(
            dictationManualMode = manual,
            dictationSelectedIds = activeSelection,
            dictationRandomCandidateIds = activeSelection.takeIf { it.isNotEmpty() },
            dictationDirty = true,
        )
    }

    private fun dictationAccountId(state: MainUiState = _uiState.value): String =
        useCases.dictationDraftSyncAccountId.trim()
            .ifBlank { useCases.dictationDraftSync?.configuredAccountId?.trim().orEmpty() }
            .ifBlank { state.dictationSyncMetadata.accountId.trim() }

    private fun dictationNowUtc(state: MainUiState = _uiState.value): Double =
        useCases.timeProvider?.nowUtcSeconds()
            ?.takeIf { it.isFinite() && it >= 0.0 }
            ?: state.dictationSyncMetadata.updatedAtUtc

    private fun draftFromState(
        state: MainUiState = _uiState.value,
        metadata: DictationDraftSyncMetadata = state.dictationSyncMetadata,
    ): DictationDraft = DictationDraft(
        mode = if (state.dictationManualMode) "manual" else "random",
        scopeGroup = state.dictationScopeGroup,
        openGroup = state.dictationOpenGroup,
        selectedIds = if (state.dictationManualMode) {
            state.dictationSelectedIds
        } else {
            state.dictationRandomCandidateIds.orEmpty()
        },
        groups = state.dictationGroupDrafts,
        count = state.dictationCount,
        includeEvaluated = state.dictationIncludeEvaluated,
        formats = state.dictationFormats.map { it.name }.toSet(),
        fontSizePt = state.dictationFontSizePt,
        missingFields = state.dictationMissingFields.map {
            when (it) {
                DictationMissingField.WORD -> "word"
                DictationMissingField.PART_OF_SPEECH -> "partOfSpeech"
                DictationMissingField.MEANING -> "meaning"
            }
        }.toSet(),
        showInitial = state.dictationShowInitial,
        includeExamples = state.dictationIncludeExamples,
        includeExampleChinese = state.dictationIncludeExampleChinese,
        customExample = state.dictationCustomExample,
        rangeEnabled = state.dictationRangeEnabled,
        syncMetadata = metadata,
    )

    private fun dictationEditorFingerprint(state: MainUiState = _uiState.value): String =
        draftFromState(state).canonicalJson()

    private fun syncFailure(error: Throwable, fallback: String): DictationDraftSyncResult {
        if (error is CancellationException) throw error
        return DictationDraftSyncResult(
            status = DictationDraftSyncStatus.LOCAL_ONLY,
            // Transport exceptions may contain request details.  Keep the UI
            // message stable so bearer credentials cannot leak through an
            // implementation-specific exception string.
            message = fallback,
        )
    }

    /** Save locally first, then push asynchronously when online sync is
     * configured.  The UI remains responsive even when the network is slow. */
    fun saveDictationDraft() {
        val state = _uiState.value
        val repository = useCases.dictationDraft
        if (!repository.available) return
        dictationSyncPullJob?.cancel()
        dictationSyncPushJob?.cancel()
        dictationSyncPushGeneration++
        val metadata = state.dictationSyncMetadata.copy(
            accountId = dictationAccountId(state),
            updatedAtUtc = dictationNowUtc(state),
            deleted = false,
        ).normalized()
        val draft = draftFromState(state, metadata)
        val saved = runCatching { repository.save(draft) }
        if (saved.isFailure) {
            _uiState.value = state.copy(
                dictationSyncMessage = saved.exceptionOrNull()?.message ?: "无法保存默写选择",
                transientMessage = saved.exceptionOrNull()?.message ?: "无法保存默写选择",
            )
            return
        }
        val adapter = useCases.dictationDraftSync
        val initialStatus = if (adapter == null || metadata.accountId.isBlank()) {
            DictationDraftSyncStatus.DISABLED
        } else {
            DictationDraftSyncStatus.LOCAL_ONLY
        }
        _uiState.value = state.copy(
            dictationSyncMetadata = metadata,
            dictationDirty = false,
            dictationSyncStatus = initialStatus,
            dictationSyncInProgress = false,
            dictationSyncMessage = if (initialStatus == DictationDraftSyncStatus.DISABLED) {
                "默写选择已保存（仅本地）"
            } else {
                "默写选择已保存，正在同步"
            },
            transientMessage = null,
        )
        scheduleDictationPush(draft, metadata.accountId)
    }

    private fun scheduleDictationPush(draft: DictationDraft, accountId: String) {
        val adapter = useCases.dictationDraftSync ?: return
        if (accountId.isBlank()) return
        dictationSyncPushJob?.cancel()
        val generation = ++dictationSyncPushGeneration
        dictationSyncPushJob = viewModelScope.launch {
            _uiState.value = _uiState.value.copy(dictationSyncInProgress = true)
            val revision = draft.syncMetadata.revision.takeIf { it.isNotBlank() && it != "0" }
            val envelope = makeDictationDraftSyncEnvelope(
                accountId = accountId,
                draft = draft,
                revision = draft.syncMetadata.revision,
                updatedAtUtc = draft.syncMetadata.updatedAtUtc,
            )
            val result = try {
                adapter.push(accountId, envelope, revision)
            } catch (error: Throwable) {
                syncFailure(error, "同步失败，已保留本地选择")
            }
            if (generation == dictationSyncPushGeneration) {
                applyPushResult(result, draft)
            }
        }
    }

    private fun applyPushResult(result: DictationDraftSyncResult, outbound: DictationDraft) {
        val state = _uiState.value
        val conflict = result.conflict ?: result.envelope?.let { remote ->
            val local = makeDictationDraftSyncEnvelope(
                dictationAccountId(state),
                outbound,
                revision = outbound.syncMetadata.revision,
                updatedAtUtc = outbound.syncMetadata.updatedAtUtc,
            )
            DictationDraftSyncConflict(local, remote)
        }
        if (result.status == DictationDraftSyncStatus.CONFLICT && conflict != null) {
            _uiState.value = state.copy(
                dictationSyncInProgress = false,
                dictationSyncStatus = DictationDraftSyncStatus.CONFLICT,
                dictationSyncConflict = conflict,
                dictationSyncMessage = result.message.ifBlank { "远端默写选择与本地不同" },
            )
            return
        }
        val returned = result.envelope
        if (result.isSuccess && returned != null) {
            val repository = useCases.dictationDraft
            val acknowledgedMetadata = DictationDraftSyncMetadata(
                accountId = returned.accountId,
                revision = returned.revision,
                updatedAtUtc = returned.updatedAtUtc,
                deleted = returned.deleted,
            ).normalized()
            runCatching {
                repository.saveLastSyncedEnvelope(returned)
                repository.saveSyncMetadata(acknowledgedMetadata)
            }
            // Do not overwrite a newer in-editor edit with a late response.
            if (!state.dictationDirty) {
                returned.draft?.let { repository.save(it) }
            }
            _uiState.value = _uiState.value.copy(dictationSyncMetadata = acknowledgedMetadata)
        }
        _uiState.value = _uiState.value.copy(
            dictationSyncInProgress = false,
            dictationSyncStatus = result.status,
            dictationSyncMessage = result.message.takeIf(String::isNotBlank),
        )
    }

    /** Clear only the current selection; preserve browsing/scroll context. */
    fun clearDictationSelection() {
        // Clearing is an in-editor operation. Keep the last saved snapshot
        // until the user explicitly saves this empty state or discards on
        // leaving, so a cancelled leave cannot destroy recoverable work.
        val state = _uiState.value
        _uiState.value = _uiState.value.copy(
            dictationSelectedIds = emptySet(),
            dictationRandomCandidateIds = null,
            dictationGroupDrafts = state.dictationGroupDrafts.mapValues { (_, group) ->
                group.copy(selectedIds = emptySet(), anchorId = null, endpointId = null)
            },
            dictationRangeEnabled = true,
            dictationDirty = true,
            transientMessage = "已清空本次选择",
        )
    }

    /** Backwards-compatible UI callback name for the in-editor clear action. */
    fun clearDictationDraft() = clearDictationSelection()

    fun requestDictationLeave() {
        if (_uiState.value.dictationDirty) {
            _uiState.value = _uiState.value.copy(
                dictationLeaveRequested = true,
                // System back has no destination callback, so treat it as a
                // request to return to the dashboard after the decision.
                dictationPendingSection = _uiState.value.dictationPendingSection ?: MainSection.DASHBOARD,
            )
        }
    }

    fun dismissDictationLeavePrompt() {
        _uiState.value = _uiState.value.copy(dictationLeaveRequested = false)
    }

    fun confirmDictationLeave(save: Boolean) {
        val pending = _uiState.value.dictationPendingSection
        if (save) {
            saveDictationDraft()
        } else {
            // Discard means the next visit starts empty, including removing
            // the previously saved snapshot, per the product decision.
            discardDictationDraft()
            _uiState.value = _uiState.value.copy(
                dictationSelectedIds = emptySet(),
                dictationRandomCandidateIds = null,
                dictationGroupDrafts = emptyMap(),
                dictationScopeGroup = "all",
                dictationOpenGroup = null,
                dictationManualMode = false,
                dictationRangeEnabled = true,
                dictationCount = 10,
                dictationIncludeEvaluated = false,
                dictationFormats = setOf(DictationFormat.DOCX, DictationFormat.PDF),
                dictationFontSizePt = 12,
                dictationMissingFields = setOf(DictationMissingField.WORD),
                dictationShowInitial = false,
                dictationIncludeExamples = false,
                dictationIncludeExampleChinese = false,
                dictationCustomExample = "",
                dictationSyncConflict = null,
                dictationDirty = false,
                transientMessage = "已放弃本次选择",
            )
        }
        _uiState.value = _uiState.value.copy(
            dictationLeaveRequested = false,
            dictationPendingSection = null,
        )
        pending?.let(::selectSection)
    }

    fun discardDictationDraft() {
        val state = _uiState.value
        val repository = useCases.dictationDraft
        if (!repository.available) return
        dictationSyncPullJob?.cancel()
        dictationSyncPushJob?.cancel()
        dictationSyncPushGeneration++
        val metadata = state.dictationSyncMetadata.copy(
            accountId = dictationAccountId(state),
            updatedAtUtc = dictationNowUtc(state),
            deleted = true,
        ).normalized()
        runCatching {
            repository.clear()
            repository.saveSyncMetadata(metadata)
        }
            .onFailure { error ->
                _uiState.value = state.copy(transientMessage = error.message ?: "无法清除默写选择")
                return
            }
        _uiState.value = state.copy(
            dictationSyncMetadata = metadata,
            dictationSyncInProgress = false,
        )
        scheduleDictationTombstone(metadata)
    }

    private fun scheduleDictationTombstone(metadata: DictationDraftSyncMetadata) {
        val adapter = useCases.dictationDraftSync ?: return
        if (metadata.accountId.isBlank()) return
        dictationSyncPushJob?.cancel()
        val generation = ++dictationSyncPushGeneration
        dictationSyncPushJob = viewModelScope.launch {
            _uiState.value = _uiState.value.copy(dictationSyncInProgress = true)
            val envelope = makeDictationDraftSyncEnvelope(
                accountId = metadata.accountId,
                draft = null,
                revision = metadata.revision,
                updatedAtUtc = metadata.updatedAtUtc,
            )
            val revision = metadata.revision.takeIf { it.isNotBlank() && it != "0" }
            val result = try {
                adapter.push(metadata.accountId, envelope, revision)
            } catch (error: Throwable) {
                syncFailure(error, "删除同步失败，已清除本地选择")
            }
            if (generation == dictationSyncPushGeneration) {
                val acknowledged = result.envelope?.let {
                    DictationDraftSyncMetadata(
                        accountId = it.accountId,
                        revision = it.revision,
                        updatedAtUtc = it.updatedAtUtc,
                        deleted = true,
                    ).normalized()
                } ?: metadata
                if (result.isSuccess) {
                    runCatching {
                        result.envelope?.let { useCases.dictationDraft.saveLastSyncedEnvelope(it) }
                        useCases.dictationDraft.saveSyncMetadata(acknowledged)
                    }
                }
                _uiState.value = _uiState.value.copy(
                    dictationSyncMetadata = if (result.isSuccess) acknowledged else _uiState.value.dictationSyncMetadata,
                    dictationSyncInProgress = false,
                    dictationSyncStatus = result.status,
                    dictationSyncMessage = result.message.takeIf(String::isNotBlank),
                    dictationSyncConflict = result.conflict,
                )
            }
        }
    }

    /** Resolve a visible remote conflict without silently choosing a side. */
    fun resolveDictationSyncConflict(useRemote: Boolean) {
        val conflict = _uiState.value.dictationSyncConflict ?: return
        val rejected = if (useRemote) conflict.local else conflict.remote
        try {
            useCases.dictationDraft.addConflictBackup(rejected)
        } catch (error: Throwable) {
            _uiState.value = _uiState.value.copy(
                dictationSyncMessage = error.message ?: "无法保存未选的冲突版本",
            )
            return
        }
        if (useRemote) {
            val remote = conflict.remote
            runCatching { useCases.dictationDraft.saveLastSyncedEnvelope(remote) }
            if (remote.deleted) {
                val metadata = DictationDraftSyncMetadata(
                    accountId = remote.accountId,
                    revision = remote.revision,
                    updatedAtUtc = remote.updatedAtUtc,
                    deleted = true,
                ).normalized()
                useCases.dictationDraft.saveSyncMetadata(metadata)
                useCases.dictationDraft.clear()
                resetDictationEditorState(metadata)
            } else {
                remote.draft?.let { draft ->
                    useCases.dictationDraft.save(draft)
                    restoreDictationDraft(draft)
                }
            }
            _uiState.value = _uiState.value.copy(
                dictationSyncConflict = null,
                dictationSyncStatus = if (remote.deleted) DictationDraftSyncStatus.TOMBSTONE else DictationDraftSyncStatus.SYNCED,
                dictationSyncMessage = "已采用远端默写选择",
                dictationDirty = false,
            )
            return
        }
        // Keep local content but use the remote revision as the next
        // If-Match token, making the user's explicit choice a guarded update.
        val localDraft = conflict.local.draft
        if (localDraft == null) {
            // The local choice is a deletion.  Keep the editor empty and
            // retry the tombstone against the remote token rather than
            // silently restoring the remote draft.
            val tombstone = DictationDraftSyncMetadata(
                accountId = conflict.remote.accountId,
                revision = conflict.remote.revision,
                updatedAtUtc = dictationNowUtc(),
                deleted = true,
            ).normalized()
            useCases.dictationDraft.clear()
            useCases.dictationDraft.saveSyncMetadata(tombstone)
            resetDictationEditorState(tombstone)
            _uiState.value = _uiState.value.copy(
                dictationSyncConflict = null,
                dictationSyncStatus = DictationDraftSyncStatus.LOCAL_ONLY,
                dictationSyncMessage = "已保留本地删除，正在同步",
            )
            scheduleDictationTombstone(tombstone)
            return
        }
        val metadata = localDraft.syncMetadata.copy(
            accountId = conflict.remote.accountId,
            revision = conflict.remote.revision,
            updatedAtUtc = dictationNowUtc(),
            deleted = false,
        ).normalized()
        val draft = localDraft.copy(syncMetadata = metadata)
        useCases.dictationDraft.save(draft)
        _uiState.value = _uiState.value.copy(
            dictationSyncMetadata = metadata,
            dictationSyncConflict = null,
            dictationSyncStatus = DictationDraftSyncStatus.LOCAL_ONLY,
            dictationSyncMessage = "已保留本地选择，正在同步",
            dictationDirty = false,
        )
        scheduleDictationPush(draft, metadata.accountId)
    }

    fun dismissDictationSyncConflict() {
        _uiState.value = _uiState.value.copy(dictationSyncConflict = null)
    }

    /** Pull a remote snapshot when the editor is clean.  A dirty editor is
     * intentionally left untouched until the user saves or discards it. */
    private fun pullDictationDraft() {
        val adapter = useCases.dictationDraftSync ?: return
        val account = dictationAccountId()
        if (account.isBlank() || _uiState.value.dictationDirty) return
        if (dictationSyncPushJob?.isActive == true) return
        if (dictationSyncPullJob?.isActive == true) return
        val expectedFingerprint = dictationEditorFingerprint()
        dictationSyncPullJob = viewModelScope.launch {
            _uiState.value = _uiState.value.copy(dictationSyncInProgress = true)
            val result = try {
                adapter.pull(account)
            } catch (error: Throwable) {
                syncFailure(error, "同步读取失败，已保留本地选择")
            }
            handlePulledDictationDraft(account, result, expectedFingerprint)
        }
    }

    /** Explicit retry hook for lifecycle/UI integrations. */
    fun syncDictationDraft() {
        pullDictationDraft()
    }

    private fun handlePulledDictationDraft(
        account: String,
        result: DictationDraftSyncResult,
        expectedFingerprint: String,
    ) {
        val state = _uiState.value
        // A pull may finish after the user edits the worksheet.  Never apply
        // a stale remote response over those edits; the next explicit save
        // will push them with the proper revision guard.
        if (state.dictationDirty || dictationEditorFingerprint(state) != expectedFingerprint) {
            _uiState.value = state.copy(
                dictationSyncInProgress = false,
                dictationSyncStatus = result.status,
                dictationSyncMessage = "本机有未保存的默写选择，已跳过远端覆盖",
            )
            return
        }
        val repository = useCases.dictationDraft
        val localDraft = repository.load()
        val localEnvelope = if (localDraft != null) {
            val localAccount = localDraft.syncMetadata.accountId.trim().ifBlank { account }
            makeDictationDraftSyncEnvelope(
                accountId = localAccount,
                draft = localDraft,
                revision = localDraft.syncMetadata.revision,
                updatedAtUtc = localDraft.syncMetadata.updatedAtUtc,
            )
        } else {
            state.dictationSyncMetadata.takeIf { it.deleted }?.let {
                makeDictationDraftSyncEnvelope(
                    accountId = it.accountId.ifBlank { account },
                    draft = null,
                    revision = it.revision,
                    updatedAtUtc = it.updatedAtUtc,
                )
            }
        }
        val remote = result.envelope
        if (result.status == DictationDraftSyncStatus.CONFLICT) {
            val conflict = result.conflict ?: remote?.let { remoteEnvelope ->
                localEnvelope?.let { local -> DictationDraftSyncConflict(local, remoteEnvelope) }
            }
            if (conflict != null) {
                _uiState.value = state.copy(
                    dictationSyncInProgress = false,
                    dictationSyncStatus = DictationDraftSyncStatus.CONFLICT,
                    dictationSyncConflict = conflict,
                    dictationSyncMessage = result.message.ifBlank { "远端默写选择与本地不同" },
                )
            } else {
                _uiState.value = state.copy(
                    dictationSyncInProgress = false,
                    dictationSyncStatus = result.status,
                    dictationSyncMessage = result.message.takeIf(String::isNotBlank),
                )
            }
            return
        }
        if (remote != null && localEnvelope != null) {
            val reconciled = reconcileDictationDraftSyncEnvelopes(localEnvelope, remote)
            if (reconciled.status == DictationDraftSyncStatus.CONFLICT) {
                _uiState.value = state.copy(
                    dictationSyncInProgress = false,
                    dictationSyncStatus = DictationDraftSyncStatus.CONFLICT,
                    dictationSyncConflict = reconciled.conflict,
                    dictationSyncMessage = reconciled.message,
                )
                return
            }
        }
        if (remote?.deleted == true || result.status == DictationDraftSyncStatus.TOMBSTONE) {
            val metadata = remote?.let {
                DictationDraftSyncMetadata(
                    accountId = it.accountId,
                    revision = it.revision,
                    updatedAtUtc = it.updatedAtUtc,
                    deleted = true,
                ).normalized()
            } ?: state.dictationSyncMetadata.copy(deleted = true).normalized()
            repository.saveSyncMetadata(metadata)
            remote?.let { repository.saveLastSyncedEnvelope(it) }
            repository.clear()
            resetDictationEditorState(metadata)
        } else if (result.status == DictationDraftSyncStatus.SYNCED) {
            val remoteDraft = remote?.draft
            if (remoteDraft != null) {
                repository.saveLastSyncedEnvelope(remote)
                repository.save(remoteDraft)
                restoreDictationDraft(remoteDraft)
            }
        }
        _uiState.value = _uiState.value.copy(
            dictationSyncInProgress = false,
            dictationSyncStatus = result.status,
            dictationSyncMessage = result.message.takeIf(String::isNotBlank),
            dictationSyncConflict = null,
        )
    }

    private fun resetDictationEditorState(
        metadata: DictationDraftSyncMetadata = DictationDraftSyncMetadata(),
    ) {
        _uiState.value = _uiState.value.copy(
            dictationSelectedIds = emptySet(),
            dictationRandomCandidateIds = null,
            dictationGroupDrafts = emptyMap(),
            dictationScopeGroup = "all",
            dictationOpenGroup = null,
            dictationManualMode = false,
            dictationRangeEnabled = true,
            dictationCount = 10,
            dictationIncludeEvaluated = false,
            dictationFormats = setOf(DictationFormat.DOCX, DictationFormat.PDF),
            dictationFontSizePt = 12,
            dictationMissingFields = setOf(DictationMissingField.WORD),
            dictationShowInitial = false,
            dictationIncludeExamples = false,
            dictationIncludeExampleChinese = false,
            dictationCustomExample = "",
            dictationSyncMetadata = metadata.normalized(),
            dictationDirty = false,
            dictationDraftRestored = true,
            dictationDraftRestoreGeneration = _uiState.value.dictationDraftRestoreGeneration + 1,
        )
    }

    /** Persist the current scroll as a normalized fraction for one group. */
    fun setDictationScrollPosition(group: String, position: Float) {
        val state = _uiState.value
        val cleanGroup = normalizeDictationGroupKey(group)
        val normalized = position.coerceIn(0f, 1f)
        val current = state.dictationGroupDrafts[cleanGroup] ?: DictationGroupDraft()
        if (kotlin.math.abs(current.scrollPosition - normalized) < 0.005f) return
        _uiState.value = state.copy(
            dictationGroupDrafts = state.dictationGroupDrafts + (cleanGroup to current.copy(scrollPosition = normalized)),
            dictationDirty = true,
        )
    }

    fun updateDictationConfig(
        count: Int,
        includeEvaluated: Boolean,
        formats: Set<DictationFormat>,
        fontSizePt: Int,
        missingFields: Set<DictationMissingField>,
        showInitial: Boolean,
        includeExamples: Boolean,
        includeExampleChinese: Boolean,
        customExample: String,
    ) {
        val current = _uiState.value
        val nextCount = count.coerceAtLeast(1)
        val nextFont = fontSizePt.coerceIn(8, 24)
        val changed = current.dictationCount != nextCount ||
            current.dictationIncludeEvaluated != includeEvaluated ||
            current.dictationFormats != formats ||
            current.dictationFontSizePt != nextFont ||
            current.dictationMissingFields != missingFields ||
            current.dictationShowInitial != showInitial ||
            current.dictationIncludeExamples != includeExamples ||
            current.dictationIncludeExampleChinese != includeExampleChinese ||
            current.dictationCustomExample != customExample
        _uiState.value = current.copy(
            dictationCount = nextCount,
            dictationIncludeEvaluated = includeEvaluated,
            dictationFormats = formats,
            dictationFontSizePt = nextFont,
            dictationMissingFields = missingFields,
            dictationShowInitial = showInitial,
            dictationIncludeExamples = includeExamples,
            dictationIncludeExampleChinese = includeExampleChinese,
            dictationCustomExample = customExample,
            dictationDirty = current.dictationDirty || changed,
        )
    }

    private fun restoreDictationDraft(draft: DictationDraft) {
        if (draft.syncMetadata.deleted) {
            resetDictationEditorState(draft.syncMetadata)
            _uiState.value = _uiState.value.copy(
                transientMessage = null,
                dictationDraftRestored = true,
            )
            return
        }
        val clean = sanitizeDictationDraft(draft, useCases.words.value)
        val selected = clean.selectedIds
        val groups = clean.groups
        _uiState.value = _uiState.value.copy(
            dictationSelectedIds = if (clean.mode == "manual") selected else emptySet(),
            dictationRandomCandidateIds = if (clean.mode == "random" && selected.isNotEmpty()) selected else null,
            dictationGroupDrafts = groups,
            dictationScopeGroup = clean.scopeGroup,
            dictationOpenGroup = clean.openGroup,
            dictationManualMode = clean.mode == "manual",
            dictationRangeEnabled = clean.rangeEnabled,
            dictationCount = clean.count,
            dictationIncludeEvaluated = clean.includeEvaluated,
            dictationFormats = clean.formats.mapNotNull { value -> runCatching { DictationFormat.valueOf(value.uppercase()) }.getOrNull() }.toSet().ifEmpty { setOf(DictationFormat.DOCX, DictationFormat.PDF) },
            dictationFontSizePt = clean.fontSizePt,
            dictationMissingFields = clean.missingFields.mapNotNull { value ->
                when (value) {
                    "word" -> DictationMissingField.WORD
                    "partOfSpeech", "part_of_speech" -> DictationMissingField.PART_OF_SPEECH
                    "meaning" -> DictationMissingField.MEANING
                    else -> null
                }
            }.toSet().ifEmpty { setOf(DictationMissingField.WORD) },
            dictationShowInitial = clean.showInitial,
            dictationIncludeExamples = clean.includeExamples,
            dictationIncludeExampleChinese = clean.includeExampleChinese,
            dictationCustomExample = clean.customExample,
            dictationSyncMetadata = clean.syncMetadata,
            dictationDirty = false,
            dictationDraftRestored = true,
            dictationDraftRestoreGeneration = _uiState.value.dictationDraftRestoreGeneration + 1,
            transientMessage = "已恢复上次选择",
        )
    }

    fun updateDictationDraftConfig(draft: DictationDraft) {
        val state = _uiState.value
        _uiState.value = state.copy(
            dictationCount = draft.count,
            dictationIncludeEvaluated = draft.includeEvaluated,
            dictationFormats = draft.formats.mapNotNull { runCatching { DictationFormat.valueOf(it.uppercase()) }.getOrNull() }.toSet(),
            dictationFontSizePt = draft.fontSizePt,
            dictationMissingFields = draft.missingFields.mapNotNull {
                when (it) {
                    "word" -> DictationMissingField.WORD
                    "partOfSpeech", "part_of_speech" -> DictationMissingField.PART_OF_SPEECH
                    "meaning" -> DictationMissingField.MEANING
                    else -> null
                }
            }.toSet(),
            dictationShowInitial = draft.showInitial,
            dictationIncludeExamples = draft.includeExamples,
            dictationIncludeExampleChinese = draft.includeExampleChinese,
            dictationCustomExample = draft.customExample,
            dictationDirty = true,
        )
    }

    fun buildDictation(
        options: DictationDocumentOptions,
        count: Int,
        group: String,
        includeEvaluated: Boolean,
        manual: Boolean,
        customExample: String,
    ) {
        _uiState.value = _uiState.value.copy(
            dictationDocument = null,
            dictationExports = emptyList(),
            dictationPreparing = false,
            transientMessage = null,
            dictationCount = count,
            dictationIncludeEvaluated = includeEvaluated,
            dictationFormats = options.formats,
            dictationFontSizePt = options.fontSizePt,
            dictationMissingFields = options.missingFields,
            dictationShowInitial = options.showInitial,
            dictationIncludeExamples = options.includeExamples,
            dictationIncludeExampleChinese = options.includeExampleChinese,
            dictationCustomExample = customExample,
            dictationGeneratedIds = emptySet(),
        )
        if (count < 1) {
            _uiState.value = _uiState.value.copy(transientMessage = "默写数量必须大于 0")
            return
        }
        val entries = if (manual) {
            useCases.selectDictationCandidates.selected(
                _uiState.value.dictationSelectedIds,
                includeEvaluated,
            )
        } else {
            useCases.selectDictationCandidates.random(
                count,
                // Once an explicit subset exists it is global across books;
                // the active group remains a browser scope only.
                if (_uiState.value.dictationRandomCandidateIds?.isNotEmpty() == true) "all" else group,
                includeEvaluated,
                candidateIds = _uiState.value.dictationRandomCandidateIds?.takeIf { it.isNotEmpty() },
            )
        }
        if (entries.isEmpty()) {
            _uiState.value = _uiState.value.copy(transientMessage = "没有符合当前条件的词条")
            return
        }
        val effectiveOptions = if (customExample.isBlank()) options else options.copy(
            customExamples = entries.associate { it.id to customExample.trim() },
        )
        val document = useCases.buildDictationDocument(entries, effectiveOptions)
        _uiState.value = _uiState.value.copy(
            dictationDocument = document,
            dictationExports = emptyList(),
            dictationPreparing = true,
            dictationSelectedIds = if (manual) entries.mapTo(mutableSetOf()) { it.id } else _uiState.value.dictationSelectedIds,
            dictationGeneratedIds = entries.mapTo(mutableSetOf()) { it.id },
            transientMessage = null,
        )
        viewModelScope.launch {
            runCatching { useCases.exportDictationDocument(document) }
                .onSuccess { outputs ->
                    _uiState.value = _uiState.value.copy(dictationExports = outputs, dictationPreparing = false)
                }
                .onFailure { error ->
                    _uiState.value = _uiState.value.copy(
                        dictationPreparing = false,
                        transientMessage = error.message ?: "无法生成默写文件。",
                    )
                }
        }
    }

    fun finishDictationMark(mark: Boolean, dontAskAgain: Boolean) {
        val ids = _uiState.value.dictationGeneratedIds.ifEmpty { _uiState.value.dictationSelectedIds }
        viewModelScope.launch {
            if (dontAskAgain) useCases.updateMarkMode(if (mark) MarkMode.ALWAYS else MarkMode.NEVER)
            if (mark && ids.isNotEmpty()) useCases.updateProgramTags(ids, setOf("evaluated"), emptySet())
            _uiState.value = _uiState.value.copy(transientMessage = if (mark) "已标记本次默写词条。" else null)
        }
    }

    fun revealReviewAnswer() {
        if (_uiState.value.reviewCard == null) return
        _uiState.value = _uiState.value.copy(reviewAnswerRevealed = true)
    }

    fun rateReviewCurrent(rating: ReviewRating, origin: FeedbackOrigin? = null): Boolean {
        val state = _uiState.value
        val card = state.reviewCard ?: return false
        if (!state.reviewAnswerRevealed || reviewRatingInProgress) return false
        reviewRatingInProgress = true
        viewModelScope.launch {
            try {
                useCases.rateReviewWord(card.id, rating)
                origin?.let {
                    _feedbackEvents.emit(FeedbackRequest(FeedbackKind.REVIEW, it))
                }
                val current = _uiState.value
                val remaining = if (current.reviewQueue.firstOrNull()?.id == card.id) {
                    current.reviewQueue.drop(1)
                } else {
                    current.reviewQueue
                }
                _uiState.value = current.copy(
                    reviewQueue = remaining,
                    reviewCard = remaining.firstOrNull(),
                    reviewAnswerRevealed = false,
                )
                refreshDerived(useCases.catalogStatus.value, useCases.settings.value)
            } catch (cancelled: CancellationException) {
                throw cancelled
            } catch (error: Exception) {
                _uiState.value = _uiState.value.copy(
                    reviewCard = card,
                    reviewAnswerRevealed = true,
                    transientMessage = error.message ?: "无法保存复习结果。",
                )
            } finally {
                reviewRatingInProgress = false
            }
        }
        return true
    }

    private fun resolveLibraryMatches(query: String): List<VocabularyEntry> {
        val group = _uiState.value.libraryGroup
        return if (group != null) useCases.wordsInGroup(group, query) else useCases.search(query)
    }

    fun updateSearch(query: String) {
        val matches = resolveLibraryMatches(query)
        _uiState.value = _uiState.value.copy(
            searchQuery = query,
            searchResults = matches.take(MAX_VISIBLE_SEARCH_RESULTS),
            totalSearchResults = matches.size,
        )
    }

    fun selectLibraryGroup(groupKey: String?) {
        _uiState.value = _uiState.value.copy(libraryGroup = groupKey, searchQuery = "")
        updateSearch("")
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

    fun updateSelectedVocabularyTags(add: Set<String>, remove: Set<String>) {
        val selected = _uiState.value.selectedVocabularyIds
        if (selected.isEmpty()) return
        viewModelScope.launch {
            runCatching { useCases.updateProgramTags(selected, add, remove) }
                .onSuccess { count ->
                    _uiState.value = _uiState.value.copy(
                        selectedVocabularyIds = emptySet(),
                        transientMessage = "已更新 $count 个词条的标签。",
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
        val safeScale = sanitizeFontScale(scale)
        _uiState.value = _uiState.value.copy(fontScale = safeScale)
        viewModelScope.launch { useCases.updateFontScale(safeScale) }
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

    fun setReminderLevels(levels: Set<String>) {
        val normalized = levels.map(String::uppercase).toSet()
        _uiState.value = _uiState.value.copy(reminderLevels = normalized)
        viewModelScope.launch { useCases.updateReminderLevels(normalized) }
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

    fun setMarkMode(mode: MarkMode) {
        _uiState.value = _uiState.value.copy(dictationMarkMode = mode)
        viewModelScope.launch { useCases.updateMarkMode(mode) }
    }

    fun previewWordReminder() {
        showWordReminder(preview = true)
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
        pullDictationDraft()
    }

    fun dismissWordReminder() {
        val wasPreview = wordReminderIsPreview
        wordReminderIsPreview = false
        _uiState.value = _uiState.value.copy(wordReminderCard = null)
        if (!wasPreview) scheduleWordReminder(useCases.words.value, useCases.settings.value)
    }

    private fun refreshDerived(status: CatalogStatus, settings: UserSettings) {
        val matches = resolveLibraryMatches(_uiState.value.searchQuery)
        val learntCount = useCases.learntWords.value.size
        val current = _uiState.value.currentCard?.id?.let { id ->
            useCases.words.value.firstOrNull { it.id == id }
        }
        val dashboard = useCases.dashboard()
        val (reminder, updatedLastReminded) = resolveReviewReminderMessage(
            dueNow = dashboard.dueNow,
            lastRemindedDueCount = lastRemindedDueCount,
            currentMessage = _uiState.value.reviewReminderMessage,
        )
        lastRemindedDueCount = updatedLastReminded
        _uiState.value = _uiState.value.copy(
            catalogStatus = status,
            dashboard = dashboard,
            forecast = useCases.forecast(),
            currentCard = current,
            libraryGroups = useCases.libraryGroups(),
            searchResults = matches.take(MAX_VISIBLE_SEARCH_RESULTS),
            totalSearchResults = matches.size,
            fontScale = sanitizeFontScale(settings.fontScale),
            learntWordCount = learntCount,
            reviewBatchSize = settings.reviewBatchSize.coerceIn(1, maxOf(1, learntCount)),
            studyOrder = settings.studyOrder,
            studyLevels = settings.studyLevels,
            reviewLevels = settings.reviewLevels,
            reminderLevels = settings.reminderLevels,
            availableLevels = (
                setOf("CET4", "CET6", "CUSTOM") +
                    useCases.words.value.flatMap { it.levels }.map(String::uppercase)
                ).sorted(),
            reminderEnabled = settings.reminderEnabled,
            reminderIntervalMinutes = settings.reminderIntervalMinutes,
            reviewReminderMessage = reminder,
            dictationEntries = useCases.words.value,
            dictationMarkMode = settings.markMode,
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
            showWordReminder(preview = false)
            if (appInForeground && useCases.settings.value.reminderEnabled) {
                scheduleWordReminder(useCases.words.value, useCases.settings.value)
            }
        }
    }

    private fun showWordReminder(preview: Boolean) {
        val card = useCases.reminderCard(previousReminderWordId)
        if (card == null) {
            if (preview) {
                _uiState.value = _uiState.value.copy(transientMessage = "所选提醒词汇组中没有可展示的单词。")
            }
            return
        }
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
