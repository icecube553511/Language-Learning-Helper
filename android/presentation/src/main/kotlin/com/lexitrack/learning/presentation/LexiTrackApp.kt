package com.lexitrack.learning.presentation

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.outlined.List
import androidx.compose.material.icons.outlined.BarChart
import androidx.compose.material.icons.outlined.CheckCircle
import androidx.compose.material.icons.outlined.Edit
import androidx.compose.material.icons.outlined.ErrorOutline
import androidx.compose.material.icons.outlined.Home
import androidx.compose.material.icons.outlined.Info
import androidx.compose.material.icons.outlined.Refresh
import androidx.compose.material.icons.outlined.School
import androidx.compose.material.icons.outlined.Search
import androidx.compose.material.icons.outlined.Settings
import androidx.compose.material.icons.outlined.UploadFile
import androidx.compose.material.icons.outlined.Visibility
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Badge
import androidx.compose.material3.BadgedBox
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Checkbox
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.NavigationBarItemDefaults
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Slider
import androidx.compose.material3.Surface
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.TextLayoutResult
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.unit.IntRect
import androidx.compose.ui.unit.IntSize
import androidx.compose.ui.unit.LayoutDirection
import androidx.compose.ui.window.Popup
import androidx.compose.ui.window.PopupPositionProvider
import androidx.compose.ui.window.PopupProperties
import androidx.compose.ui.layout.boundsInWindow
import androidx.compose.ui.layout.onGloballyPositioned
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.input.pointer.PointerEventPass
import androidx.compose.ui.input.pointer.changedToUp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.lexitrack.learning.application.DashboardSnapshot
import com.lexitrack.learning.application.ExportedDictation
import com.lexitrack.learning.application.ForecastDay
import com.lexitrack.learning.domain.DictationDocument
import com.lexitrack.learning.domain.DictationDocumentOptions
import com.lexitrack.learning.domain.DictationFormat
import com.lexitrack.learning.domain.DictationMissingField
import com.lexitrack.learning.domain.ImportReport
import com.lexitrack.learning.domain.ImportRowStatus
import com.lexitrack.learning.domain.MarkMode
import com.lexitrack.learning.domain.ReviewRating
import com.lexitrack.learning.domain.VocabularyEntry
import com.lexitrack.learning.domain.BubbleDefinition
import com.lexitrack.learning.domain.BubbleStack
import com.lexitrack.learning.domain.tokenizeEnglish
import java.time.format.DateTimeFormatter
import kotlin.math.exp
import kotlin.math.max

private data class WordBubbleState(val data: BubbleDefinition, val anchor: IntRect)

private val LocalOpenWordBubble = staticCompositionLocalOf<(String, String, Int, IntRect) -> Unit> { { _, _, _, _ -> } }
private val LocalBubbleDepth = staticCompositionLocalOf { -1 }

@Composable
fun LexiTrackApp(
    viewModel: MainViewModel,
    onChooseCsv: () -> Unit,
    onReminderSettingsRequested: (Boolean, Float) -> Unit = { _, _ -> },
    onSaveDictation: (List<ExportedDictation>, (Int) -> Unit) -> Unit = { _, _ -> },
) {
    val state by viewModel.uiState.collectAsStateWithLifecycle()
    var labelEditorOpen by remember { mutableStateOf(false) }
    var dictationPreviewOpen by remember { mutableStateOf(false) }
    var dictationMarkOpen by remember { mutableStateOf(false) }
    val bubbles = remember { mutableStateListOf<WordBubbleState>() }
    var bubbleStack by remember { mutableStateOf(BubbleStack()) }
    val openBubble: (String, String, Int, IntRect) -> Unit = { token, contextExample, depth, anchor ->
        val definition = viewModel.lookupWordBubble(token, contextExample)
        val next = if (depth < 0) {
            BubbleStack().openRoot(definition)
        } else {
            bubbleStack.openChild(depth, definition)
        }
        if (next != bubbleStack) {
            bubbleStack = next
            val previousAnchors = bubbles.map { it.anchor }
            bubbles.clear()
            next.frames.forEachIndexed { index, frame ->
                bubbles += WordBubbleState(
                    frame.definition,
                    if (index == next.frames.lastIndex) anchor else previousAnchors.getOrElse(index) { anchor },
                )
            }
        }
    }
    LaunchedEffect(state.section, state.currentCard?.id, state.reviewCard?.id, state.wordReminderCard?.id) {
        bubbleStack = BubbleStack()
        bubbles.clear()
    }
    LexiTrackTheme(state.fontScale) {
        CompositionLocalProvider(LocalOpenWordBubble provides openBubble) {
            Box(
                modifier = Modifier
                    .fillMaxSize()
                    .pointerInput(bubbles) {
                        awaitPointerEventScope {
                            while (true) {
                                val event = awaitPointerEvent(PointerEventPass.Initial)
                                if (event.changes.any { it.changedToUp() }) {
                                    bubbles.clear()
                                    bubbleStack = BubbleStack()
                                }
                            }
                        }
                    },
            ) {
        Scaffold(
            containerColor = MaterialTheme.colorScheme.background,
            topBar = { AppHeader() },
            bottomBar = {
                AppNavigation(
                    selected = state.section,
                    dueCount = state.dashboard.dueNow,
                    onSelected = viewModel::selectSection,
                )
            },
        ) { contentPadding ->
            Box(
                modifier = Modifier
                    .fillMaxSize()
                    .padding(contentPadding),
            ) {
                when (state.section) {
                    MainSection.DASHBOARD -> DashboardScreen(
                        state = state,
                        onStudy = { viewModel.selectSection(MainSection.STUDY) },
                        onReview = { viewModel.selectSection(MainSection.REVIEW) },
                    )
                    MainSection.STUDY -> StudyScreen(
                        card = state.currentCard,
                        revealed = state.answerRevealed,
                        onReveal = viewModel::revealAnswer,
                        onRate = viewModel::rateCurrent,
                        title = "学习卡",
                        emptyTitle = "新词学习已完成",
                        emptyMessage = "导入更多词条或前往复习巩固已学内容",
                        filterTitle = "学习词汇组",
                        selectedLevels = state.studyLevels,
                        availableLevels = state.availableLevels,
                        onLevelsChange = viewModel::setStudyLevels,
                    )
                    MainSection.REVIEW -> ReviewScreen(
                        state = state,
                        onStart = viewModel::startReviewSession,
                        onReveal = viewModel::revealReviewAnswer,
                        onRate = viewModel::rateReviewCurrent,
                        onLevelsChange = viewModel::setReviewLevels,
                    )
                    MainSection.DICTATION -> DictationScreen(
                        state = state,
                        onToggleSelection = viewModel::toggleDictationSelection,
                        onBuild = { options, count, levels, includeEvaluated, manual, customExample ->
                            viewModel.buildDictation(options, count, levels, includeEvaluated, manual, customExample)
                            dictationPreviewOpen = true
                        },
                    )
                    MainSection.LIBRARY -> LibraryScreen(
                        state = state,
                        onQueryChange = viewModel::updateSearch,
                        onChooseCsv = onChooseCsv,
                        onToggleSelection = viewModel::toggleVocabularySelection,
                        onEditLabels = { labelEditorOpen = true },
                    )
                    MainSection.INSIGHTS -> InsightsScreen(state.forecast)
                    MainSection.SETTINGS -> SettingsScreen(
                        fontScale = state.fontScale,
                        onFontScaleChange = viewModel::setFontScale,
                        learntWordCount = state.learntWordCount,
                        reviewBatchSize = state.reviewBatchSize,
                        onReviewBatchSizeChange = viewModel::setReviewBatchSize,
                        reminderEnabled = state.reminderEnabled,
                        reminderIntervalMinutes = state.reminderIntervalMinutes,
                        reminderLevels = state.reminderLevels,
                        availableLevels = state.availableLevels,
                        studyOrder = state.studyOrder,
                        onStudyOrderChange = viewModel::setStudyOrder,
                        onReminderSettingsChange = { enabled, interval ->
                            onReminderSettingsRequested(enabled, interval)
                            viewModel.setReminderSettings(enabled, interval)
                        },
                        onReminderLevelsChange = viewModel::setReminderLevels,
                        onPreviewReminder = viewModel::previewWordReminder,
                        markMode = state.dictationMarkMode,
                        onMarkModeChange = viewModel::setMarkMode,
                    )
                }
            }
        }

        state.importReport?.let { report ->
            ImportReportDialog(report, viewModel::dismissImportReport)
        }
        if (labelEditorOpen) {
            VocabularyLabelDialog(
                selectionCount = state.selectedVocabularyIds.size,
                onDismiss = { labelEditorOpen = false },
                onSave = { add, remove ->
                    viewModel.updateSelectedVocabularyTags(add, remove)
                    labelEditorOpen = false
                },
            )
        }
        val dictationDocument = state.dictationDocument
        if (dictationPreviewOpen && dictationDocument != null) {
            DictationPreviewDialog(
                document = dictationDocument,
                preparing = state.dictationPreparing,
                exports = state.dictationExports,
                onDismiss = { dictationPreviewOpen = false },
                onExport = {
                    onSaveDictation(state.dictationExports) { savedCount ->
                        if (savedCount > 0) {
                            dictationPreviewOpen = false
                            when (state.dictationMarkMode) {
                                MarkMode.ALWAYS -> viewModel.finishDictationMark(mark = true, dontAskAgain = false)
                                MarkMode.NEVER -> Unit
                                MarkMode.ASK -> dictationMarkOpen = true
                            }
                        }
                    }
                },
            )
        }
        if (dictationMarkOpen) {
            DictationMarkDialog(
                onDismiss = {
                    dictationMarkOpen = false
                    viewModel.finishDictationMark(mark = false, dontAskAgain = false)
                },
                onFinish = { mark, dontAskAgain ->
                    dictationMarkOpen = false
                    viewModel.finishDictationMark(mark, dontAskAgain)
                },
            )
        }
        state.transientMessage?.let { message ->
            MessageDialog(message, viewModel::dismissMessage)
        }
        state.reviewReminderMessage?.let { message ->
            AlertDialog(
                onDismissRequest = viewModel::dismissReviewReminder,
                icon = { Icon(Icons.Outlined.Refresh, contentDescription = null) },
                title = { Text("复习提醒") },
                text = { Text(message) },
                confirmButton = {
                    TextButton(
                        onClick = {
                            viewModel.dismissReviewReminder()
                            viewModel.selectSection(MainSection.REVIEW)
                        },
                    ) { Text("去复习") }
                },
                dismissButton = {
                    TextButton(onClick = viewModel::dismissReviewReminder) { Text("稍后") }
                },
            )
        } ?: state.wordReminderCard?.let { card ->
            AlertDialog(
                onDismissRequest = viewModel::dismissWordReminder,
                icon = { Icon(Icons.Outlined.School, contentDescription = null) },
                title = { Text("单词学习提醒") },
                text = {
                    Column(
                        modifier = Modifier.verticalScroll(rememberScrollState()),
                        verticalArrangement = Arrangement.spacedBy(8.dp),
                    ) {
                        Text(card.word, style = MaterialTheme.typography.headlineMedium, color = Ink)
                        Text(card.phonetic.ifBlank { "音标待补充" }, style = MaterialTheme.typography.bodyMedium, color = MutedInk)
                        Text(card.meaning, style = MaterialTheme.typography.titleMedium, color = Ink)
                        HorizontalDivider()
                        card.examples.take(3).forEachIndexed { index, example ->
                            Column(verticalArrangement = Arrangement.spacedBy(2.dp)) {
                                InteractiveSentence(
                                    "${index + 1}. ${example.english}",
                                    style = MaterialTheme.typography.bodyMedium,
                                    color = Ink,
                                )
                                Text(example.chinese, style = MaterialTheme.typography.bodyMedium, color = Ink)
                            }
                        }
                        if (card.mnemonic.isNotBlank()) {
                            Text("助记  ${card.mnemonic}", style = MaterialTheme.typography.bodyMedium, color = BusinessAmber)
                        }
                    }
                },
                confirmButton = {
                    TextButton(onClick = viewModel::dismissWordReminder) { Text("知道了") }
                },
                dismissButton = null,
            )
        }
        WordBubbleOverlay(
            bubbles = bubbles,
            onDismissAll = {
                bubbles.clear()
                bubbleStack = BubbleStack()
            },
            onCloseAfter = { depth ->
                bubbleStack = bubbleStack.closeAfter(depth)
                while (bubbles.size > depth + 1) bubbles.removeAt(bubbles.lastIndex)
            },
        )
            }
        }
    }
}

@Composable
private fun InteractiveSentence(
    text: String,
    modifier: Modifier = Modifier,
    style: androidx.compose.ui.text.TextStyle = MaterialTheme.typography.labelMedium,
    color: Color = Ink,
    textAlign: TextAlign? = null,
    maxLines: Int = Int.MAX_VALUE,
    overflow: TextOverflow = TextOverflow.Clip,
) {
    val openBubble = LocalOpenWordBubble.current
    val depth = LocalBubbleDepth.current
    var layout by remember { mutableStateOf<TextLayoutResult?>(null) }
    var bounds by remember { mutableStateOf(IntRect.Zero) }
    val annotated = remember(text, color) {
        buildAnnotatedString {
            var cursor = 0
            tokenizeEnglish(text).forEach { token ->
                append(text.substring(cursor, token.start))
                pushStringAnnotation("word", token.text)
                withStyle(SpanStyle(color = color)) { append(token.text) }
                pop()
                cursor = token.end
            }
            append(text.substring(cursor))
        }
    }
    Text(
        text = annotated,
        modifier = modifier
            .onGloballyPositioned { coordinates ->
                val rect = coordinates.boundsInWindow()
                bounds = IntRect(rect.left.toInt(), rect.top.toInt(), rect.right.toInt(), rect.bottom.toInt())
            }
            .pointerInput(annotated, bounds) {
                detectTapGestures(
                    onTap = tap@{ offset ->
                        val textLayout = layout ?: return@tap
                        val characterOffset = textLayout.getOffsetForPosition(offset)
                        val hit = annotated.getStringAnnotations("word", characterOffset, characterOffset + 1).firstOrNull()
                        if (hit != null && characterOffset < annotated.length && textLayout.getBoundingBox(characterOffset).contains(offset)) {
                            val tokenBoxes = (hit.start until hit.end).map(textLayout::getBoundingBox)
                            val tokenBounds = IntRect(
                                left = bounds.left + tokenBoxes.minOf { it.left }.toInt(),
                                top = bounds.top + tokenBoxes.minOf { it.top }.toInt(),
                                right = bounds.left + tokenBoxes.maxOf { it.right }.toInt(),
                                bottom = bounds.top + tokenBoxes.maxOf { it.bottom }.toInt(),
                            )
                            openBubble(hit.item, text, depth, tokenBounds)
                        }
                    },
                )
            },
        style = style,
        color = color,
        textAlign = textAlign,
        maxLines = maxLines,
        overflow = overflow,
        onTextLayout = { layout = it },
    )
}

@Composable
private fun WordBubbleOverlay(
    bubbles: MutableList<WordBubbleState>,
    onDismissAll: () -> Unit,
    onCloseAfter: (Int) -> Unit,
) {
    bubbles.toList().forEachIndexed { index, bubble ->
        val positionProvider: PopupPositionProvider = remember(bubble.anchor) {
            object : PopupPositionProvider {
                override fun calculatePosition(
                    anchorBounds: IntRect,
                    windowSize: IntSize,
                    layoutDirection: LayoutDirection,
                    popupContentSize: IntSize,
                ): IntOffset {
                    val centeredX = bubble.anchor.left + (bubble.anchor.width - popupContentSize.width) / 2
                    val x = centeredX.coerceIn(0, (windowSize.width - popupContentSize.width).coerceAtLeast(0))
                    val below = bubble.anchor.bottom + 6
                    val above = bubble.anchor.top - popupContentSize.height - 6
                    val y = if (below + popupContentSize.height <= windowSize.height) below else above.coerceAtLeast(0)
                    return IntOffset(x, y)
                }
            }
        }
        Popup(
            popupPositionProvider = positionProvider,
            onDismissRequest = onDismissAll,
            properties = PopupProperties(focusable = false, dismissOnBackPress = true, dismissOnClickOutside = false),
        ) {
            // Root content uses -1; a bubble's depth is its zero-based stack index.
            CompositionLocalProvider(LocalBubbleDepth provides index) {
                Surface(
                    modifier = Modifier
                        .widthIn(min = 220.dp, max = 360.dp)
                        .pointerInput(index) {
                            awaitPointerEventScope {
                                while (true) {
                                    val event = awaitPointerEvent(PointerEventPass.Initial)
                                    if (event.changes.any { it.changedToUp() }) onCloseAfter(index)
                                }
                            }
                        },
                    color = MaterialTheme.colorScheme.surface,
                    shape = RoundedCornerShape(8.dp),
                    shadowElevation = 8.dp,
                    border = CardDefaults.outlinedCardBorder(),
                ) {
                    Column(
                        modifier = Modifier.padding(12.dp),
                        verticalArrangement = Arrangement.spacedBy(5.dp),
                    ) {
                        Text(bubble.data.word, style = MaterialTheme.typography.titleLarge, color = Ink)
                        if (bubble.data.phonetic.isNotBlank()) {
                            Text(bubble.data.phonetic, style = MaterialTheme.typography.labelMedium, color = BrandTeal)
                        }
                        if (bubble.data.partOfSpeech.isNotBlank()) {
                            Text(bubble.data.partOfSpeech, style = MaterialTheme.typography.labelMedium, color = BusinessAmber)
                        }
                        Text(bubble.data.meaning, style = MaterialTheme.typography.bodyMedium, color = Ink)
                        bubble.data.examples.forEach { sentence ->
                            if (bubble.data.known) {
                                InteractiveSentence(
                                    text = sentence,
                                    style = MaterialTheme.typography.labelMedium,
                                    color = MutedInk,
                                    modifier = Modifier.fillMaxWidth(),
                                )
                            } else {
                                Text(sentence, style = MaterialTheme.typography.labelMedium, color = MutedInk)
                            }
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun AppHeader() {
    Surface(
        modifier = Modifier.statusBarsPadding(),
        color = MaterialTheme.colorScheme.surface,
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .heightIn(min = 68.dp)
                .padding(horizontal = 20.dp, vertical = 10.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Surface(
                modifier = Modifier.size(44.dp),
                color = BrandNavy,
                shape = RoundedCornerShape(8.dp),
            ) {
                Box(contentAlignment = Alignment.Center) {
                    Text("词", color = Color.White, style = MaterialTheme.typography.titleLarge)
                }
            }
            Spacer(Modifier.width(12.dp))
            Column {
                Text("词程", style = MaterialTheme.typography.titleLarge, color = Ink)
                Text("LEXITRACK", style = MaterialTheme.typography.labelSmall, color = MutedInk)
            }
        }
    }
}

@Composable
private fun AppNavigation(selected: MainSection, dueCount: Int, onSelected: (MainSection) -> Unit) {
    val items = listOf(
        NavigationItem(MainSection.DASHBOARD, "总览", Icons.Outlined.Home),
        NavigationItem(MainSection.STUDY, "学习", Icons.Outlined.School),
        NavigationItem(MainSection.REVIEW, "复习", Icons.Outlined.Refresh),
        NavigationItem(MainSection.DICTATION, "默写", Icons.Outlined.Edit),
        NavigationItem(MainSection.LIBRARY, "词库", Icons.AutoMirrored.Outlined.List),
        NavigationItem(MainSection.INSIGHTS, "趋势", Icons.Outlined.BarChart),
        NavigationItem(MainSection.SETTINGS, "设置", Icons.Outlined.Settings),
    )
    NavigationBar(
        modifier = Modifier.navigationBarsPadding(),
        containerColor = MaterialTheme.colorScheme.surface,
        tonalElevation = 1.dp,
    ) {
        items.forEach { item ->
            NavigationBarItem(
                selected = selected == item.section,
                onClick = { onSelected(item.section) },
                icon = {
                    BadgedBox(
                        badge = {
                            if (item.section == MainSection.REVIEW && dueCount > 0) {
                                Badge { Text(if (dueCount > 99) "99+" else dueCount.toString()) }
                            }
                        },
                    ) {
                        Icon(item.icon, contentDescription = item.label)
                    }
                },
                label = { Text(item.label, maxLines = 1) },
                colors = NavigationBarItemDefaults.colors(
                    selectedIconColor = BrandTeal,
                    selectedTextColor = BrandTeal,
                    indicatorColor = MaterialTheme.colorScheme.primaryContainer,
                ),
            )
        }
    }
}

private data class NavigationItem(
    val section: MainSection,
    val label: String,
    val icon: ImageVector,
)

@Composable
private fun DashboardScreen(state: MainUiState, onStudy: () -> Unit, onReview: () -> Unit) {
    LazyColumn(
        modifier = Modifier.fillMaxSize(),
        contentPadding = PaddingValues(20.dp),
        verticalArrangement = Arrangement.spacedBy(18.dp),
    ) {
        item { PageHeader("今日总览", "掌握节奏，完成当前到期内容") }
        item { CatalogStatusStrip(state) }
        item { DashboardStats(state.dashboard) }
        item {
            Button(
                onClick = if (state.dashboard.dueNow > 0) onReview else onStudy,
                modifier = Modifier.fillMaxWidth().heightIn(min = 52.dp),
            ) {
                Icon(Icons.Outlined.School, contentDescription = null)
                Spacer(Modifier.width(8.dp))
                Text(
                    when {
                        state.dashboard.dueNow > 0 -> "开始复习 ${state.dashboard.dueNow} 词"
                        state.dashboard.newWords > 0 -> "开始学习 ${state.dashboard.newWords} 词"
                        else -> "进入学习"
                    },
                )
            }
        }
        item {
            SectionTitle("未来 7 天负载", "按当前到期时间统计")
            Spacer(Modifier.height(12.dp))
            ForecastBars(state.forecast)
        }
    }
}

@Composable
private fun CatalogStatusStrip(state: MainUiState) {
    Surface(
        modifier = Modifier.fillMaxWidth(),
        color = if (state.catalogStatus.acceptedEntries > 0) {
            MaterialTheme.colorScheme.primaryContainer
        } else {
            MaterialTheme.colorScheme.secondaryContainer
        },
        shape = RoundedCornerShape(8.dp),
    ) {
        Row(
            modifier = Modifier.padding(16.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            if (state.catalogStatus.loading) {
                CircularProgressIndicator(modifier = Modifier.size(24.dp), strokeWidth = 2.dp)
            } else {
                Icon(
                    Icons.Outlined.Info,
                    contentDescription = null,
                    tint = MaterialTheme.colorScheme.onPrimaryContainer,
                )
            }
            Spacer(Modifier.width(12.dp))
            Text(
                state.catalogStatus.message,
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onPrimaryContainer,
            )
        }
    }
}

@Composable
private fun DashboardStats(snapshot: DashboardSnapshot) {
    Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            StatTile("总词数", snapshot.totalWords.toString(), BrandNavy, Modifier.weight(1f))
            StatTile("未学习", snapshot.newWords.toString(), BrandTeal, Modifier.weight(1f))
        }
        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            StatTile("待复习", snapshot.dueNow.toString(), BusinessAmber, Modifier.weight(1f))
            StatTile("今日完成", snapshot.reviewedToday.toString(), BusinessGreen, Modifier.weight(1f))
        }
    }
}

@Composable
private fun StatTile(label: String, value: String, accent: Color, modifier: Modifier = Modifier) {
    Surface(
        modifier = modifier.heightIn(min = 108.dp),
        shape = RoundedCornerShape(8.dp),
        color = MaterialTheme.colorScheme.surface,
        border = CardDefaults.outlinedCardBorder(),
    ) {
        Column(
            modifier = Modifier.padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(4.dp),
        ) {
            Box(Modifier.size(6.dp).background(accent, RoundedCornerShape(2.dp)))
            Text(value, style = MaterialTheme.typography.headlineLarge, color = Ink)
            Text(label, style = MaterialTheme.typography.bodyMedium, color = MutedInk)
        }
    }
}

@Composable
private fun StudyScreen(
    card: VocabularyEntry?,
    revealed: Boolean,
    onReveal: () -> Unit,
    onRate: (ReviewRating) -> Unit,
    title: String,
    emptyTitle: String,
    emptyMessage: String,
    filterTitle: String = "",
    selectedLevels: Set<String> = emptySet(),
    availableLevels: List<String> = emptyList(),
    onLevelsChange: (Set<String>) -> Unit = {},
) {
    if (card == null) {
        Column(modifier = Modifier.fillMaxSize().padding(20.dp)) {
            if (filterTitle.isNotBlank()) {
                LevelFilterRow(filterTitle, selectedLevels, availableLevels, onLevelsChange)
            }
            Box(modifier = Modifier.weight(1f)) {
                EmptyState(Icons.Outlined.CheckCircle, emptyTitle, emptyMessage)
            }
        }
        return
    }
    Column(
        modifier = Modifier.fillMaxSize().padding(20.dp),
    ) {
        PageHeader(title, card.levels.sorted().joinToString(" / "))
        if (filterTitle.isNotBlank()) {
            LevelFilterRow(filterTitle, selectedLevels, availableLevels, onLevelsChange)
        }
        Spacer(Modifier.height(12.dp))
        Surface(
            modifier = Modifier.fillMaxWidth().weight(1f),
            color = MaterialTheme.colorScheme.surface,
            shape = RoundedCornerShape(8.dp),
            border = CardDefaults.outlinedCardBorder(),
        ) {
            Column(
                modifier = Modifier.fillMaxSize().padding(horizontal = 14.dp, vertical = 14.dp),
                horizontalAlignment = Alignment.CenterHorizontally,
            ) {
                Text(card.word, style = MaterialTheme.typography.displayLarge, color = Ink)
                if (card.phonetic.isNotBlank()) {
                    Text(card.phonetic, style = MaterialTheme.typography.titleMedium, color = BrandTeal)
                }
                Spacer(Modifier.height(8.dp))
                if (!revealed) {
                    Button(
                        onClick = onReveal,
                        modifier = Modifier.fillMaxWidth().heightIn(min = 50.dp),
                    ) {
                        Icon(Icons.Outlined.Visibility, contentDescription = null)
                        Spacer(Modifier.width(8.dp))
                        Text("查看答案")
                    }
                } else {
                    RevealedCardContent(
                        card = card,
                        onRate = onRate,
                        modifier = Modifier.fillMaxWidth().weight(1f),
                    )
                }
            }
        }
    }
}

@Composable
private fun ReviewScreen(
    state: MainUiState,
    onStart: () -> Unit,
    onReveal: () -> Unit,
    onRate: (ReviewRating) -> Unit,
    onLevelsChange: (Set<String>) -> Unit,
) {
    if (!state.reviewSessionStarted) {
        Column(
            modifier = Modifier.fillMaxSize().padding(20.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp),
        ) {
            PageHeader("复习", "按掌握权重抽取已学单词")
            LevelFilterRow("复习词汇组", state.reviewLevels, state.availableLevels, onLevelsChange)
            Surface(
                modifier = Modifier.fillMaxWidth(),
                color = MaterialTheme.colorScheme.surface,
                shape = RoundedCornerShape(8.dp),
                border = CardDefaults.outlinedCardBorder(),
            ) {
                Column(
                    modifier = Modifier.padding(20.dp),
                    verticalArrangement = Arrangement.spacedBy(12.dp),
                ) {
                    Text("已学 ${state.learntWordCount} 词", style = MaterialTheme.typography.titleMedium, color = Ink)
                    Text(
                        "本轮 ${minOf(state.reviewBatchSize, state.learntWordCount)} 词 · 到期 ${state.dashboard.dueNow} 词",
                        style = MaterialTheme.typography.bodyMedium,
                        color = MutedInk,
                    )
                    Button(
                        onClick = onStart,
                        enabled = state.learntWordCount > 0,
                        modifier = Modifier.fillMaxWidth().heightIn(min = 52.dp),
                    ) {
                        Icon(Icons.Outlined.Refresh, contentDescription = null)
                        Spacer(Modifier.width(8.dp))
                        Text("开始复习")
                    }
                }
            }
            if (state.learntWordCount == 0) {
                EmptyState(Icons.Outlined.School, "暂无已学词", "先在学习中完成至少一个单词的评分")
            }
        }
        return
    }
    if (state.reviewCard == null) {
        Column(
            modifier = Modifier.fillMaxSize().padding(20.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.Center,
        ) {
            Icon(Icons.Outlined.CheckCircle, contentDescription = null, tint = BusinessGreen, modifier = Modifier.size(52.dp))
            Spacer(Modifier.height(12.dp))
            Text("本轮复习完成", style = MaterialTheme.typography.headlineMedium, color = Ink)
            Text(
                "已完成 ${state.reviewSessionSize} 个单词",
                style = MaterialTheme.typography.bodyMedium,
                color = MutedInk,
            )
            Spacer(Modifier.height(18.dp))
            Button(onClick = onStart, enabled = state.learntWordCount > 0) {
                Icon(Icons.Outlined.Refresh, contentDescription = null)
                Spacer(Modifier.width(8.dp))
                Text("再复习一轮")
            }
        }
        return
    }
    val completed = state.reviewSessionSize - state.reviewQueue.size
    StudyScreen(
        card = state.reviewCard,
        revealed = state.reviewAnswerRevealed,
        onReveal = onReveal,
        onRate = onRate,
        title = "复习卡 ${completed + 1} / ${state.reviewSessionSize}",
        emptyTitle = "本轮复习完成",
        emptyMessage = "可再次主动开始复习",
        filterTitle = "复习词汇组",
        selectedLevels = state.reviewLevels,
        availableLevels = state.availableLevels,
        onLevelsChange = onLevelsChange,
    )
}

@Composable
private fun LevelFilterRow(
    title: String,
    selected: Set<String>,
    available: List<String>,
    onChange: (Set<String>) -> Unit,
) {
    val effectiveSelection = if (selected.isEmpty()) available.toSet() else selected
    Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
        Text(title, style = MaterialTheme.typography.labelLarge, color = MutedInk)
        Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            available.forEach { level ->
                val label = when (level) { "CET4" -> "四级"; "CET6" -> "六级"; "CUSTOM" -> "自定义"; else -> level }
                FilterChip(
                    selected = level in effectiveSelection,
                    onClick = { onChange(if (level in effectiveSelection) effectiveSelection - level else effectiveSelection + level) },
                    label = { Text(label) },
                )
            }
        }
    }
}

@Composable
private fun RevealedCardContent(
    card: VocabularyEntry,
    onRate: (ReviewRating) -> Unit,
    modifier: Modifier = Modifier,
) {
    Column(modifier = modifier) {
        Text(
            card.meaning,
            modifier = Modifier.fillMaxWidth(),
            style = MaterialTheme.typography.titleMedium,
            color = Ink,
            textAlign = TextAlign.Center,
            maxLines = 2,
            overflow = TextOverflow.Ellipsis,
        )
        if (card.mnemonic.isNotBlank()) {
            Spacer(Modifier.height(4.dp))
            Text(
                card.mnemonic,
                style = MaterialTheme.typography.labelMedium,
                color = MutedInk,
                textAlign = TextAlign.Center,
                modifier = Modifier.fillMaxWidth(),
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
        }
        Spacer(Modifier.height(6.dp))
        HorizontalDivider(color = DividerColor)
        Column(
            modifier = Modifier.fillMaxWidth().padding(vertical = 6.dp),
            verticalArrangement = Arrangement.spacedBy(5.dp),
        ) {
            card.examples.take(3).forEachIndexed { index, example ->
                Column(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalAlignment = Alignment.CenterHorizontally,
                ) {
                    InteractiveSentence(
                        "${index + 1}. ${example.english}",
                        modifier = Modifier.fillMaxWidth(),
                        style = MaterialTheme.typography.labelMedium,
                        color = Ink,
                        textAlign = TextAlign.Center,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                    )
                    Text(
                        example.chinese,
                        modifier = Modifier.fillMaxWidth(),
                        style = MaterialTheme.typography.labelMedium,
                        color = MutedInk,
                        textAlign = TextAlign.Center,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                    )
                }
            }
        }
        Spacer(Modifier.weight(1f))
        HorizontalDivider(color = DividerColor)
        Spacer(Modifier.height(8.dp))
        Text(
            "本次掌握程度",
            modifier = Modifier.fillMaxWidth(),
            style = MaterialTheme.typography.labelMedium,
            color = Ink,
        )
        Spacer(Modifier.height(6.dp))
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(4.dp),
        ) {
            RatingButton("忘记", BusinessRed, Modifier.weight(1f)) { onRate(ReviewRating.AGAIN) }
            RatingButton("模糊", BusinessAmber, Modifier.weight(1f)) { onRate(ReviewRating.HARD) }
            RatingButton("认识", BrandTeal, Modifier.weight(1f)) { onRate(ReviewRating.GOOD) }
            RatingButton("很熟", BrandNavy, Modifier.weight(1f)) { onRate(ReviewRating.EASY) }
        }
    }
}

@Composable
private fun RatingButton(label: String, color: Color, modifier: Modifier, onClick: () -> Unit) {
    Button(
        onClick = onClick,
        modifier = modifier.heightIn(min = 58.dp),
        colors = ButtonDefaults.buttonColors(containerColor = color, contentColor = Color.White),
        shape = RoundedCornerShape(8.dp),
        contentPadding = PaddingValues(horizontal = 5.dp, vertical = 10.dp),
    ) {
        Text(label, style = MaterialTheme.typography.labelLarge, maxLines = 1)
    }
}

@Composable
private fun DictationScreen(
    state: MainUiState,
    onToggleSelection: (String) -> Unit,
    onBuild: (DictationDocumentOptions, Int, Set<String>, Boolean, Boolean, String) -> Unit,
) {
    var formats by remember { mutableStateOf(setOf(DictationFormat.DOCX, DictationFormat.PDF)) }
    var fontSizeText by remember { mutableStateOf("12") }
    var missingFields by remember { mutableStateOf(setOf(DictationMissingField.WORD)) }
    var showInitial by remember { mutableStateOf(false) }
    var includeExamples by remember { mutableStateOf(false) }
    var customExample by remember { mutableStateOf("") }
    var selectedLevels by remember { mutableStateOf(setOf("CET4", "CET6", "CUSTOM")) }
    var includeEvaluated by remember { mutableStateOf(false) }
    var countText by remember { mutableStateOf("10") }
    var manual by remember { mutableStateOf(false) }
    var countError by remember { mutableStateOf(false) }
    var confirmationRequested by remember { mutableStateOf<Int?>(null) }

    val effectiveLevels = if (selectedLevels.isEmpty()) state.availableLevels.toSet() else selectedLevels
    val candidateEntries = state.dictationEntries.filter { entry ->
        (effectiveLevels.isEmpty() || entry.levels.any { it.uppercase() in effectiveLevels }) &&
            (includeEvaluated || entry.tags.none { it.equals("evaluated", ignoreCase = true) })
    }
    val selectedCandidateIds = state.dictationSelectedIds.intersect(candidateEntries.mapTo(mutableSetOf()) { it.id })
    val selectedCount = selectedCandidateIds.size

    fun submit() {
        val count = countText.toIntOrNull()
        if (count == null || count < 1) {
            countError = true
            return
        }
        countError = false
        if (manual && selectedCount in 1 until count) {
            confirmationRequested = count
            return
        }
        onBuild(
            DictationDocumentOptions(
                formats = formats,
                fontSizePt = fontSizeText.toIntOrNull()?.coerceIn(8, 24) ?: 12,
                missingFields = missingFields,
                showInitial = showInitial,
                includeExamples = includeExamples,
            ),
            count,
            effectiveLevels,
            includeEvaluated,
            manual,
            customExample,
        )
    }

    LazyColumn(
        modifier = Modifier.fillMaxSize(),
        contentPadding = PaddingValues(20.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        item { PageHeader("默写", "生成可预览、可打印的 A4 默写页") }
        item {
            DictationOptionsPanel(
                formats = formats,
                onFormatsChange = { formats = it },
                fontSizeText = fontSizeText,
                onFontSizeChange = { fontSizeText = it.filter(Char::isDigit) },
                missingFields = missingFields,
                onMissingFieldsChange = { missingFields = it },
                showInitial = showInitial,
                onShowInitialChange = { showInitial = it },
                includeExamples = includeExamples,
                onIncludeExamplesChange = { includeExamples = it },
                customExample = customExample,
                onCustomExampleChange = { customExample = it },
                selectedLevels = selectedLevels,
                availableLevels = state.availableLevels,
                onLevelsChange = { selectedLevels = it },
                includeEvaluated = includeEvaluated,
                onIncludeEvaluatedChange = { includeEvaluated = it },
                countText = countText,
                onCountChange = { countText = it.filter(Char::isDigit); countError = false },
                countError = countError,
                manual = manual,
                onManualChange = { manual = it },
                preparing = state.dictationPreparing,
                onSubmit = ::submit,
            )
        }
        item {
            Surface(
                modifier = Modifier.fillMaxWidth(),
                color = MaterialTheme.colorScheme.surface,
                shape = RoundedCornerShape(8.dp),
                border = CardDefaults.outlinedCardBorder(),
            ) {
                Column(modifier = Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text("手选词条", modifier = Modifier.weight(1f), style = MaterialTheme.typography.titleMedium, color = Ink)
                        Text(
                            if (manual) "$selectedCount / ${countText.toIntOrNull() ?: 0}" else "随机模式",
                            style = MaterialTheme.typography.labelLarge,
                            color = BrandTeal,
                        )
                    }
                    Text(
                        if (manual) "仅使用勾选的词条；数量不足时会再次确认。" else "随机模式会在筛选结果中无重复取样。",
                        style = MaterialTheme.typography.bodySmall,
                        color = MutedInk,
                    )
                    if (manual) {
                        LazyColumn(
                            modifier = Modifier.fillMaxWidth().heightIn(max = 330.dp),
                            verticalArrangement = Arrangement.spacedBy(2.dp),
                        ) {
                            items(candidateEntries, key = { it.id }) { entry ->
                                Row(
                                    modifier = Modifier.fillMaxWidth(),
                                    verticalAlignment = Alignment.CenterVertically,
                                ) {
                                    Checkbox(
                                        checked = entry.id in state.dictationSelectedIds,
                                        onCheckedChange = { onToggleSelection(entry.id) },
                                    )
                                    Column(modifier = Modifier.weight(1f)) {
                                        Text(entry.word, style = MaterialTheme.typography.bodyLarge, color = Ink)
                                        Text(
                                            entry.meaning,
                                            style = MaterialTheme.typography.bodySmall,
                                            color = MutedInk,
                                            maxLines = 1,
                                            overflow = TextOverflow.Ellipsis,
                                        )
                                    }
                                    Text(
                                        entry.levels.sorted().joinToString(" / "),
                                        style = MaterialTheme.typography.labelSmall,
                                        color = BrandTeal,
                                    )
                                }
                            }
                        }
                    }
                    if (candidateEntries.isEmpty()) {
                        Text("当前筛选没有可用词条。", style = MaterialTheme.typography.bodyMedium, color = BusinessAmber)
                    }
                }
            }
        }
    }

    confirmationRequested?.let { requestedCount ->
        AlertDialog(
            onDismissRequest = { confirmationRequested = null },
            title = { Text("确认选择") },
            text = { Text("当前仅选择了$selectedCount/$requestedCount，是否确定选择") },
            confirmButton = {
                TextButton(
                    onClick = {
                        confirmationRequested = null
                        val count = requestedCount
                        onBuild(
                            DictationDocumentOptions(
                                formats = formats,
                                fontSizePt = fontSizeText.toIntOrNull()?.coerceIn(8, 24) ?: 12,
                                missingFields = missingFields,
                                showInitial = showInitial,
                                includeExamples = includeExamples,
                            ),
                            count,
                            effectiveLevels,
                            includeEvaluated,
                            true,
                            customExample,
                        )
                    },
                ) { Text("确定选择") }
            },
            dismissButton = { TextButton(onClick = { confirmationRequested = null }) { Text("返回选择") } },
            shape = RoundedCornerShape(8.dp),
        )
    }
}

@Composable
private fun DictationOptionsPanel(
    formats: Set<DictationFormat>,
    onFormatsChange: (Set<DictationFormat>) -> Unit,
    fontSizeText: String,
    onFontSizeChange: (String) -> Unit,
    missingFields: Set<DictationMissingField>,
    onMissingFieldsChange: (Set<DictationMissingField>) -> Unit,
    showInitial: Boolean,
    onShowInitialChange: (Boolean) -> Unit,
    includeExamples: Boolean,
    onIncludeExamplesChange: (Boolean) -> Unit,
    customExample: String,
    onCustomExampleChange: (String) -> Unit,
    selectedLevels: Set<String>,
    availableLevels: List<String>,
    onLevelsChange: (Set<String>) -> Unit,
    includeEvaluated: Boolean,
    onIncludeEvaluatedChange: (Boolean) -> Unit,
    countText: String,
    onCountChange: (String) -> Unit,
    countError: Boolean,
    manual: Boolean,
    onManualChange: (Boolean) -> Unit,
    preparing: Boolean,
    onSubmit: () -> Unit,
) {
    Surface(
        modifier = Modifier.fillMaxWidth(),
        color = MaterialTheme.colorScheme.surface,
        shape = RoundedCornerShape(8.dp),
        border = CardDefaults.outlinedCardBorder(),
    ) {
        Column(modifier = Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Text("默写设置", style = MaterialTheme.typography.titleMedium, color = Ink)
            ChoiceRow(
                title = "输出格式",
                choices = listOf(DictationFormat.DOCX to "Word", DictationFormat.PDF to "PDF"),
                selected = formats,
                onChange = { format -> onFormatsChange(if (format in formats && formats.size > 1) formats - format else formats + format) },
            )
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text("字号", modifier = Modifier.weight(1f), style = MaterialTheme.typography.labelLarge, color = MutedInk)
                OutlinedTextField(
                    value = fontSizeText,
                    onValueChange = onFontSizeChange,
                    modifier = Modifier.width(92.dp),
                    singleLine = true,
                    suffix = { Text("pt") },
                    isError = fontSizeText.toIntOrNull()?.let { it !in 8..24 } ?: true,
                )
            }
            Text("可填写 8 到 24 pt，默认小四 12 pt。", style = MaterialTheme.typography.bodySmall, color = MutedInk)
            ChoiceRow(
                title = "缺失项",
                choices = listOf(
                    DictationMissingField.WORD to "单词",
                    DictationMissingField.PART_OF_SPEECH to "词性",
                    DictationMissingField.MEANING to "中文",
                ),
                selected = missingFields,
                onChange = { field ->
                    onMissingFieldsChange(if (field in missingFields && missingFields.size > 1) missingFields - field else missingFields + field)
                },
            )
            Row(modifier = Modifier.horizontalScroll(rememberScrollState()), verticalAlignment = Alignment.CenterVertically) {
                Text("词库", modifier = Modifier.width(64.dp), style = MaterialTheme.typography.labelLarge, color = MutedInk)
                LevelFilterRow("", selectedLevels, availableLevels) { onLevelsChange(it) }
            }
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text("默写数量", modifier = Modifier.weight(1f), style = MaterialTheme.typography.labelLarge, color = MutedInk)
                OutlinedTextField(
                    value = countText,
                    onValueChange = onCountChange,
                    modifier = Modifier.width(120.dp),
                    singleLine = true,
                    isError = countError,
                    supportingText = if (countError) ({ Text("请输入大于 0 的数量") }) else null,
                )
            }
            ChoiceRow(
                title = "选择方式",
                choices = listOf(false to "随机填写", true to "从词库选择"),
                selected = setOf(manual),
                onChange = onManualChange,
            )
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text("包含已考察词", modifier = Modifier.weight(1f), style = MaterialTheme.typography.labelLarge, color = MutedInk)
                Switch(checked = includeEvaluated, onCheckedChange = onIncludeEvaluatedChange)
            }
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text("显示单词首字母", modifier = Modifier.weight(1f), style = MaterialTheme.typography.labelLarge, color = MutedInk)
                Switch(checked = showInitial, onCheckedChange = onShowInitialChange)
            }
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text("添加例句", modifier = Modifier.weight(1f), style = MaterialTheme.typography.labelLarge, color = MutedInk)
                Switch(checked = includeExamples, onCheckedChange = onIncludeExamplesChange)
            }
            if (includeExamples) {
                OutlinedTextField(
                    value = customExample,
                    onValueChange = onCustomExampleChange,
                    modifier = Modifier.fillMaxWidth(),
                    label = { Text("自填例句（可选，应用于本次所有词条）") },
                    minLines = 2,
                )
            }
            Button(
                onClick = onSubmit,
                enabled = !preparing && formats.isNotEmpty() && missingFields.isNotEmpty() &&
                    fontSizeText.toIntOrNull()?.let { it in 8..24 } == true,
                modifier = Modifier.fillMaxWidth().heightIn(min = 52.dp),
            ) {
                if (preparing) CircularProgressIndicator(modifier = Modifier.size(20.dp), color = Color.White, strokeWidth = 2.dp)
                else Icon(Icons.Outlined.Visibility, contentDescription = null)
                Spacer(Modifier.width(8.dp))
                Text(if (preparing) "正在生成" else "生成并预览 A4 页面")
            }
        }
    }
}

@Composable
private fun <T> ChoiceRow(
    title: String,
    choices: List<Pair<T, String>>,
    selected: Set<T>,
    onChange: (T) -> Unit,
) {
    Row(
        modifier = Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        if (title.isNotEmpty()) Text(title, modifier = Modifier.width(64.dp), style = MaterialTheme.typography.labelLarge, color = MutedInk)
        choices.forEach { (value, label) ->
            FilterChip(
                selected = value in selected,
                onClick = { onChange(value) },
                label = { Text(label) },
                modifier = Modifier.padding(end = 6.dp),
            )
        }
    }
}

@Composable
private fun DictationPreviewDialog(
    document: DictationDocument,
    preparing: Boolean,
    exports: List<ExportedDictation>,
    onDismiss: () -> Unit,
    onExport: () -> Unit,
) {
    val lines = document.rows.flatMapIndexed { index, row ->
        buildList {
            add("${index + 1}. ${row.word}    ${row.partOfSpeech}    ${row.meaning}")
            row.examples.forEach { add("    e.g. $it") }
            add("")
        }
    }
    val linesPerPage = (842f / (document.options.fontSizePt * 1.9f)).toInt().coerceIn(12, 42)
    val pages = lines.chunked(linesPerPage).ifEmpty { listOf(emptyList()) }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("默写预览 · A4") },
        text = {
            Column(
                modifier = Modifier.fillMaxWidth().heightIn(max = 600.dp).verticalScroll(rememberScrollState()),
                verticalArrangement = Arrangement.spacedBy(12.dp),
            ) {
                Text("${document.rows.size} 个词条 · ${document.options.fontSizePt} pt · ${pages.size} 页", color = MutedInk)
                pages.forEachIndexed { pageIndex, pageLines ->
                    Surface(
                        modifier = Modifier.fillMaxWidth().aspectRatio(210f / 297f),
                        color = Color.White,
                        border = CardDefaults.outlinedCardBorder(),
                    ) {
                        Column(
                            modifier = Modifier.padding(12.dp),
                            verticalArrangement = Arrangement.spacedBy(3.dp),
                        ) {
                            pageLines.forEach { line ->
                                Text(
                                    line,
                                    color = Color(0xFF18252F),
                                    fontSize = (document.options.fontSizePt * 0.75f).sp,
                                    maxLines = 2,
                                    overflow = TextOverflow.Ellipsis,
                                )
                            }
                            Spacer(Modifier.weight(1f))
                            Text("${pageIndex + 1} / ${pages.size}", modifier = Modifier.fillMaxWidth(), textAlign = TextAlign.End, color = MutedInk, fontSize = 8.sp)
                        }
                    }
                }
            }
        },
        confirmButton = {
            TextButton(onClick = onExport, enabled = !preparing && exports.isNotEmpty()) {
                Text(if (preparing) "正在准备文件" else "导出 ${exports.size} 个文件")
            }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("返回修改") } },
        shape = RoundedCornerShape(8.dp),
    )
}

@Composable
private fun DictationMarkDialog(
    onDismiss: () -> Unit,
    onFinish: (Boolean, Boolean) -> Unit,
) {
    var dontAskAgain by remember { mutableStateOf(false) }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("标记默写词条") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text("是否将本次导出的词条标记为 evaluated？")
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Checkbox(checked = dontAskAgain, onCheckedChange = { dontAskAgain = it })
                    Text("不再提示")
                }
            }
        },
        confirmButton = { TextButton(onClick = { onFinish(true, dontAskAgain) }) { Text("标记") } },
        dismissButton = { TextButton(onClick = { onFinish(false, dontAskAgain) }) { Text("不标记") } },
        shape = RoundedCornerShape(8.dp),
    )
}

@Composable
private fun LibraryScreen(
    state: MainUiState,
    onQueryChange: (String) -> Unit,
    onChooseCsv: () -> Unit,
    onToggleSelection: (String) -> Unit,
    onEditLabels: () -> Unit,
) {
    Column(modifier = Modifier.fillMaxSize().padding(horizontal = 20.dp)) {
        Spacer(Modifier.height(20.dp))
        PageHeader("词库", "${state.totalSearchResults} 个匹配词条")
        Spacer(Modifier.height(14.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(10.dp), verticalAlignment = Alignment.CenterVertically) {
            OutlinedTextField(
                value = state.searchQuery,
                onValueChange = onQueryChange,
                modifier = Modifier.weight(1f),
                singleLine = true,
                leadingIcon = { Icon(Icons.Outlined.Search, contentDescription = null) },
                placeholder = { Text("搜索单词、释义或标签") },
            )
            Button(
                onClick = onChooseCsv,
                enabled = !state.importInProgress,
                modifier = Modifier.heightIn(min = 56.dp),
                contentPadding = PaddingValues(horizontal = 14.dp),
            ) {
                if (state.importInProgress) {
                    CircularProgressIndicator(
                        modifier = Modifier.size(22.dp),
                        color = Color.White,
                        strokeWidth = 2.dp,
                    )
                } else {
                    Icon(Icons.Outlined.UploadFile, contentDescription = "导入 CSV")
                }
            }
            Button(
                onClick = onEditLabels,
                enabled = state.selectedVocabularyIds.isNotEmpty(),
                modifier = Modifier.heightIn(min = 56.dp),
            ) { Text("标签 (${state.selectedVocabularyIds.size})") }
        }
        Text(
            "CSV 的 level 支持 CET4、CET6、custom（多个用 | 分隔），tags 也用 | 分隔；勾选导入词条可批量修改。",
            style = MaterialTheme.typography.labelMedium,
            color = MutedInk,
        )
        Spacer(Modifier.height(12.dp))
        if (state.searchResults.isEmpty()) {
            EmptyState(Icons.AutoMirrored.Outlined.List, "没有匹配词条", "可调整搜索条件或导入 CSV 词库")
        } else {
            LazyColumn(
                modifier = Modifier.fillMaxSize(),
                contentPadding = PaddingValues(bottom = 20.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                items(state.searchResults, key = { it.id }) { entry ->
                    VocabularyRow(
                        entry = entry,
                        selected = entry.id in state.selectedVocabularyIds,
                        onToggleSelection = { onToggleSelection(entry.id) },
                    )
                }
                if (state.totalSearchResults > state.searchResults.size) {
                    item {
                        Text(
                            "当前显示前 ${state.searchResults.size} 项",
                            modifier = Modifier.fillMaxWidth().padding(16.dp),
                            style = MaterialTheme.typography.bodyMedium,
                            color = MutedInk,
                        )
                    }
                }
            }
        }
    }
}

@Composable
private fun VocabularyRow(entry: VocabularyEntry, selected: Boolean, onToggleSelection: () -> Unit) {
    Surface(
        modifier = Modifier.fillMaxWidth(),
        color = MaterialTheme.colorScheme.surface,
        shape = RoundedCornerShape(8.dp),
        border = CardDefaults.outlinedCardBorder(),
    ) {
        Column(modifier = Modifier.padding(15.dp), verticalArrangement = Arrangement.spacedBy(5.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Checkbox(checked = selected, onCheckedChange = { onToggleSelection() })
                Text(
                    entry.word,
                    modifier = Modifier.weight(1f),
                    style = MaterialTheme.typography.titleLarge,
                    color = Ink,
                )
                Text(
                    entry.levels.sorted().joinToString(" / "),
                    style = MaterialTheme.typography.labelMedium,
                    color = BrandTeal,
                )
            }
            if (entry.phonetic.isNotBlank()) {
                Text(entry.phonetic, style = MaterialTheme.typography.bodyMedium, color = BrandTeal)
            }
            Text(
                entry.meaning,
                style = MaterialTheme.typography.bodyMedium,
                color = MutedInk,
                maxLines = 2,
                overflow = TextOverflow.Ellipsis,
            )
        }
    }
}

@Composable
private fun VocabularyLabelDialog(
    selectionCount: Int,
    onDismiss: () -> Unit,
    onSave: (Set<String>, Set<String>) -> Unit,
) {
    val availableTags = listOf("cet4", "cet6", "gk", "zk", "evaluated")
    var addTags by remember { mutableStateOf(emptySet<String>()) }
    var removeTags by remember { mutableStateOf(emptySet<String>()) }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("添加或删除标签") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                Text("已选择 $selectionCount 个词条；只能操作程序内置标签。")
                Text("添加标签", style = MaterialTheme.typography.labelLarge, color = MutedInk)
                Row(modifier = Modifier.horizontalScroll(rememberScrollState())) {
                    availableTags.forEach { tag ->
                        FilterChip(
                            selected = tag in addTags,
                            onClick = {
                                addTags = if (tag in addTags) addTags - tag else addTags + tag
                                removeTags = removeTags - tag
                            },
                            label = { Text(tag) },
                            modifier = Modifier.padding(end = 6.dp),
                        )
                    }
                }
                Text("删除标签", style = MaterialTheme.typography.labelLarge, color = MutedInk)
                Row(modifier = Modifier.horizontalScroll(rememberScrollState())) {
                    availableTags.forEach { tag ->
                        FilterChip(
                            selected = tag in removeTags,
                            onClick = {
                                removeTags = if (tag in removeTags) removeTags - tag else removeTags + tag
                                addTags = addTags - tag
                            },
                            label = { Text(tag) },
                            modifier = Modifier.padding(end = 6.dp),
                        )
                    }
                }
            }
        },
        confirmButton = {
            TextButton(
                onClick = { onSave(addTags, removeTags) },
                enabled = addTags.isNotEmpty() || removeTags.isNotEmpty(),
            ) { Text("保存标签") }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("取消") } },
    )
}

@Composable
private fun InsightsScreen(forecast: List<ForecastDay>) {
    LazyColumn(
        modifier = Modifier.fillMaxSize(),
        contentPadding = PaddingValues(20.dp),
        verticalArrangement = Arrangement.spacedBy(24.dp),
    ) {
        item { PageHeader("记忆趋势", "lexi-sm2-v1") }
        item {
            SectionTitle("预计记忆保持率", "以 3 天稳定间隔展示")
            Spacer(Modifier.height(12.dp))
            MemoryCurve()
        }
        item {
            SectionTitle("未来 7 天负载", "到期词条")
            Spacer(Modifier.height(12.dp))
            ForecastBars(forecast)
        }
    }
}

@Composable
private fun MemoryCurve() {
    Surface(
        modifier = Modifier.fillMaxWidth(),
        color = MaterialTheme.colorScheme.surface,
        shape = RoundedCornerShape(8.dp),
        border = CardDefaults.outlinedCardBorder(),
    ) {
        Column(modifier = Modifier.padding(16.dp)) {
            Canvas(modifier = Modifier.fillMaxWidth().height(210.dp)) {
                val left = 12.dp.toPx()
                val right = size.width - 8.dp.toPx()
                val top = 10.dp.toPx()
                val bottom = size.height - 12.dp.toPx()
                drawLine(DividerColor, Offset(left, top), Offset(left, bottom), strokeWidth = 1.dp.toPx())
                drawLine(DividerColor, Offset(left, bottom), Offset(right, bottom), strokeWidth = 1.dp.toPx())
                val path = Path()
                for (step in 0..70) {
                    val day = step / 10f
                    val retention = exp(-day / 3f)
                    val x = left + (right - left) * (day / 7f)
                    val y = bottom - (bottom - top) * retention
                    if (step == 0) path.moveTo(x, y) else path.lineTo(x, y)
                }
                drawPath(path, BrandTeal, style = Stroke(width = 3.dp.toPx(), cap = StrokeCap.Round))
                drawLine(
                    BusinessAmber,
                    Offset(left, bottom - (bottom - top) * 0.8f),
                    Offset(right, bottom - (bottom - top) * 0.8f),
                    strokeWidth = 1.dp.toPx(),
                )
            }
            Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                Text("今天 100%", style = MaterialTheme.typography.labelMedium, color = MutedInk)
                Text("第 3 天 37%", style = MaterialTheme.typography.labelMedium, color = MutedInk)
                Text("第 7 天 10%", style = MaterialTheme.typography.labelMedium, color = MutedInk)
            }
        }
    }
}

@Composable
private fun ForecastBars(forecast: List<ForecastDay>) {
    val formatter = DateTimeFormatter.ofPattern("M/d")
    val maximum = max(1, forecast.maxOfOrNull { it.count } ?: 1)
    Surface(
        modifier = Modifier.fillMaxWidth(),
        color = MaterialTheme.colorScheme.surface,
        shape = RoundedCornerShape(8.dp),
        border = CardDefaults.outlinedCardBorder(),
    ) {
        Row(
            modifier = Modifier.fillMaxWidth().heightIn(min = 178.dp).padding(14.dp),
            horizontalArrangement = Arrangement.spacedBy(7.dp),
            verticalAlignment = Alignment.Bottom,
        ) {
            forecast.forEachIndexed { index, day ->
                val barHeight = 24.dp + 80.dp * (day.count.toFloat() / maximum)
                Column(
                    modifier = Modifier.weight(1f),
                    horizontalAlignment = Alignment.CenterHorizontally,
                    verticalArrangement = Arrangement.Bottom,
                ) {
                    Text(day.count.toString(), style = MaterialTheme.typography.labelSmall, color = Ink)
                    Spacer(Modifier.height(4.dp))
                    Box(
                        modifier = Modifier
                            .fillMaxWidth()
                            .height(barHeight)
                            .background(
                                if (index == 0) BusinessAmber else BrandNavy,
                                RoundedCornerShape(topStart = 4.dp, topEnd = 4.dp),
                            ),
                    )
                    Spacer(Modifier.height(6.dp))
                    Text(day.date.format(formatter), style = MaterialTheme.typography.labelSmall, color = MutedInk)
                }
            }
        }
    }
}

@Composable
private fun SettingsScreen(
    fontScale: Float,
    onFontScaleChange: (Float) -> Unit,
    learntWordCount: Int,
    reviewBatchSize: Int,
    onReviewBatchSizeChange: (Int) -> Unit,
    reminderEnabled: Boolean,
    reminderIntervalMinutes: Float,
    reminderLevels: Set<String>,
    availableLevels: List<String>,
    onReminderSettingsChange: (Boolean, Float) -> Unit,
    onReminderLevelsChange: (Set<String>) -> Unit,
    onPreviewReminder: () -> Unit,
    studyOrder: String,
    onStudyOrderChange: (String) -> Unit,
    markMode: MarkMode,
    onMarkModeChange: (MarkMode) -> Unit,
) {
    var reminderEnabledDraft by remember(reminderEnabled) { mutableStateOf(reminderEnabled) }
    var reminderIntervalDraft by remember(reminderIntervalMinutes) {
        mutableStateOf(reminderIntervalMinutes.toString().removeSuffix(".0"))
    }
    var reminderIntervalError by remember { mutableStateOf(false) }
    Column(
        modifier = Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(20.dp),
        verticalArrangement = Arrangement.spacedBy(20.dp),
    ) {
        PageHeader("设置", "阅读与数据")
        Surface(
            modifier = Modifier.fillMaxWidth(),
            color = MaterialTheme.colorScheme.surface,
            shape = RoundedCornerShape(8.dp),
            border = CardDefaults.outlinedCardBorder(),
        ) {
            Column(modifier = Modifier.padding(18.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                Row(modifier = Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                    Text("界面字号", modifier = Modifier.weight(1f), style = MaterialTheme.typography.titleMedium)
                    Text("${(fontScale * 100).toInt()}%", style = MaterialTheme.typography.titleMedium, color = BrandTeal)
                }
                Slider(
                    value = fontScale,
                    onValueChange = onFontScaleChange,
                    valueRange = 0.9f..1.4f,
                    steps = 4,
                )
                Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                    Text("90%", style = MaterialTheme.typography.labelMedium, color = MutedInk)
                    Text("140%", style = MaterialTheme.typography.labelMedium, color = MutedInk)
                }
            }
        }
        Surface(
            modifier = Modifier.fillMaxWidth(),
            color = MaterialTheme.colorScheme.surface,
            shape = RoundedCornerShape(8.dp),
            border = CardDefaults.outlinedCardBorder(),
        ) {
            Column(modifier = Modifier.padding(18.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                Text("默写后的标记", style = MaterialTheme.typography.titleMedium, color = Ink)
                Text("控制导出成功后是否给本次词条添加 evaluated 标签。", style = MaterialTheme.typography.bodyMedium, color = MutedInk)
                Row(modifier = Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    FilterChip(selected = markMode == MarkMode.ALWAYS, onClick = { onMarkModeChange(MarkMode.ALWAYS) }, label = { Text("默认标记") })
                    FilterChip(selected = markMode == MarkMode.NEVER, onClick = { onMarkModeChange(MarkMode.NEVER) }, label = { Text("默认不标记") })
                    FilterChip(selected = markMode == MarkMode.ASK, onClick = { onMarkModeChange(MarkMode.ASK) }, label = { Text("每次询问") })
                }
            }
        }
        Surface(
            modifier = Modifier.fillMaxWidth(),
            color = MaterialTheme.colorScheme.surface,
            shape = RoundedCornerShape(8.dp),
            border = CardDefaults.outlinedCardBorder(),
        ) {
            Column(modifier = Modifier.padding(18.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                Text("学习顺序", style = MaterialTheme.typography.titleMedium, color = Ink)
                Text("默认随机，也可按字母顺序学习。", style = MaterialTheme.typography.bodyMedium, color = MutedInk)
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    FilterChip(selected = studyOrder == "random", onClick = { onStudyOrderChange("random") }, label = { Text("随机顺序") })
                    FilterChip(selected = studyOrder == "alphabetical", onClick = { onStudyOrderChange("alphabetical") }, label = { Text("按字母排序") })
                }
            }
        }
        Surface(
            modifier = Modifier.fillMaxWidth(),
            color = MaterialTheme.colorScheme.surface,
            shape = RoundedCornerShape(8.dp),
            border = CardDefaults.outlinedCardBorder(),
        ) {
            Column(modifier = Modifier.padding(18.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                Row(modifier = Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                    Text("每轮复习数量", modifier = Modifier.weight(1f), style = MaterialTheme.typography.titleMedium)
                    Text(
                        if (learntWordCount == 0) "暂无已学词" else "$reviewBatchSize / $learntWordCount",
                        style = MaterialTheme.typography.titleMedium,
                        color = BrandTeal,
                    )
                }
                Slider(
                    value = reviewBatchSize.coerceAtMost(maxOf(1, learntWordCount)).toFloat(),
                    onValueChange = { onReviewBatchSizeChange(it.toInt()) },
                    enabled = learntWordCount > 0,
                    valueRange = 1f..maxOf(1, learntWordCount).toFloat(),
                    steps = maxOf(0, learntWordCount - 2),
                )
            }
        }
        Surface(
            modifier = Modifier.fillMaxWidth(),
            color = MaterialTheme.colorScheme.secondaryContainer,
            shape = RoundedCornerShape(8.dp),
        ) {
            Column(modifier = Modifier.padding(18.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text("Preview", style = MaterialTheme.typography.labelMedium, color = BrandNavy)
                Text("Vocabulary", style = MaterialTheme.typography.headlineMedium, color = Ink)
                Text("词汇；词汇量", style = MaterialTheme.typography.bodyLarge, color = MutedInk)
            }
        }
        Surface(
            modifier = Modifier.fillMaxWidth(),
            color = MaterialTheme.colorScheme.surface,
            shape = RoundedCornerShape(8.dp),
            border = CardDefaults.outlinedCardBorder(),
        ) {
            Column(modifier = Modifier.padding(18.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                Row(modifier = Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                    Column(modifier = Modifier.weight(1f)) {
                        Text("弹窗单词卡片", style = MaterialTheme.typography.titleMedium, color = Ink)
                        Text("前台卡片与后台系统通知", style = MaterialTheme.typography.labelMedium, color = MutedInk)
                    }
                    Switch(
                        checked = reminderEnabledDraft,
                        onCheckedChange = { reminderEnabledDraft = it },
                    )
                }
                LevelFilterRow(
                    title = "提醒词汇组",
                    selected = reminderLevels,
                    available = availableLevels,
                    onChange = onReminderLevelsChange,
                )
                OutlinedTextField(
                    value = reminderIntervalDraft,
                    onValueChange = {
                        reminderIntervalDraft = it
                        reminderIntervalError = false
                    },
                    modifier = Modifier.fillMaxWidth(),
                    label = { Text("弹窗间隔") },
                    suffix = { Text("min") },
                    singleLine = true,
                    isError = reminderIntervalError,
                    supportingText = if (reminderIntervalError) {
                        { Text("请输入 0.5 到 120 之间的数字") }
                    } else {
                        null
                    },
                )
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Button(
                        onClick = {
                            val interval = reminderIntervalDraft.replace(',', '.').toFloatOrNull()
                            if (interval == null || interval !in 0.5f..120.0f) {
                                reminderIntervalError = true
                            } else {
                                onReminderSettingsChange(reminderEnabledDraft, interval)
                            }
                        },
                    ) { Text("保存设置") }
                    TextButton(onClick = onPreviewReminder) { Text("立即预览") }
                }
            }
        }
        Surface(
            modifier = Modifier.fillMaxWidth(),
            color = MaterialTheme.colorScheme.surface,
            shape = RoundedCornerShape(8.dp),
            border = CardDefaults.outlinedCardBorder(),
        ) {
            Column(modifier = Modifier.padding(18.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text("本地数据", style = MaterialTheme.typography.titleMedium, color = Ink)
                Text("词库、复习记录与偏好保存在此设备。", style = MaterialTheme.typography.bodyMedium, color = MutedInk)
            }
        }
    }
}

@Composable
private fun PageHeader(title: String, subtitle: String) {
    Column(verticalArrangement = Arrangement.spacedBy(3.dp)) {
        Text(title, style = MaterialTheme.typography.headlineMedium, color = Ink)
        Text(subtitle, style = MaterialTheme.typography.bodyMedium, color = MutedInk)
    }
}

@Composable
private fun SectionTitle(title: String, subtitle: String) {
    Row(modifier = Modifier.fillMaxWidth(), verticalAlignment = Alignment.Bottom) {
        Text(title, modifier = Modifier.weight(1f), style = MaterialTheme.typography.titleLarge, color = Ink)
        Text(subtitle, style = MaterialTheme.typography.labelMedium, color = MutedInk)
    }
}

@Composable
private fun EmptyState(icon: ImageVector, title: String, detail: String) {
    Column(
        modifier = Modifier.fillMaxSize().padding(32.dp),
        verticalArrangement = Arrangement.Center,
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Icon(icon, contentDescription = null, modifier = Modifier.size(52.dp), tint = BrandTeal)
        Spacer(Modifier.height(14.dp))
        Text(title, style = MaterialTheme.typography.titleLarge, color = Ink)
        Spacer(Modifier.height(6.dp))
        Text(detail, style = MaterialTheme.typography.bodyMedium, color = MutedInk)
    }
}

@Composable
private fun ImportReportDialog(report: ImportReport, onDismiss: () -> Unit) {
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("CSV 导入结果") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
                Text(
                    "总行数 ${report.totalRows} · 成功 ${report.imported} · 跳过 ${report.skipped} · 失败 ${report.failed}",
                    style = MaterialTheme.typography.bodyLarge,
                )
                report.warnings.forEach { warning ->
                    Text(warning, style = MaterialTheme.typography.bodyMedium, color = BusinessAmber)
                }
                if (report.rows.isNotEmpty()) {
                    LazyColumn(
                        modifier = Modifier.fillMaxWidth().heightIn(max = 340.dp),
                        verticalArrangement = Arrangement.spacedBy(6.dp),
                    ) {
                        items(report.rows.take(80)) { row ->
                            Row(verticalAlignment = Alignment.Top) {
                                val icon = when (row.status) {
                                    ImportRowStatus.IMPORTED -> Icons.Outlined.CheckCircle
                                    ImportRowStatus.SKIPPED -> Icons.Outlined.Info
                                    ImportRowStatus.FAILED -> Icons.Outlined.ErrorOutline
                                }
                                val tint = when (row.status) {
                                    ImportRowStatus.IMPORTED -> BusinessGreen
                                    ImportRowStatus.SKIPPED -> BusinessAmber
                                    ImportRowStatus.FAILED -> BusinessRed
                                }
                                Icon(icon, contentDescription = null, modifier = Modifier.size(20.dp), tint = tint)
                                Spacer(Modifier.width(8.dp))
                                Text(
                                    "第 ${row.row} 行${row.word?.let { " · $it" }.orEmpty()}：${row.message}",
                                    style = MaterialTheme.typography.bodyMedium,
                                )
                            }
                        }
                    }
                }
            }
        },
        confirmButton = { TextButton(onClick = onDismiss) { Text("完成") } },
        shape = RoundedCornerShape(8.dp),
    )
}

@Composable
private fun MessageDialog(message: String, onDismiss: () -> Unit) {
    AlertDialog(
        onDismissRequest = onDismiss,
        icon = { Icon(Icons.Outlined.ErrorOutline, contentDescription = null, tint = BusinessRed) },
        title = { Text("无法完成操作") },
        text = { Text(message) },
        confirmButton = { TextButton(onClick = onDismiss) { Text("关闭") } },
        shape = RoundedCornerShape(8.dp),
    )
}
