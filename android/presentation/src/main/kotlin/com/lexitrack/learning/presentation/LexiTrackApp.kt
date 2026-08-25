package com.lexitrack.learning.presentation

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
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
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.outlined.List
import androidx.compose.material.icons.outlined.BarChart
import androidx.compose.material.icons.outlined.CheckCircle
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
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.NavigationBarItemDefaults
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Slider
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.lexitrack.learning.application.DashboardSnapshot
import com.lexitrack.learning.application.ForecastDay
import com.lexitrack.learning.domain.ImportReport
import com.lexitrack.learning.domain.ImportRowStatus
import com.lexitrack.learning.domain.ReviewRating
import com.lexitrack.learning.domain.VocabularyEntry
import java.time.format.DateTimeFormatter
import kotlin.math.exp
import kotlin.math.max

@Composable
fun LexiTrackApp(
    viewModel: MainViewModel,
    onChooseCsv: () -> Unit,
) {
    val state by viewModel.uiState.collectAsStateWithLifecycle()
    LexiTrackTheme(state.fontScale) {
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
                    )
                    MainSection.REVIEW -> ReviewScreen(
                        state = state,
                        onStart = viewModel::startReviewSession,
                        onReveal = viewModel::revealReviewAnswer,
                        onRate = viewModel::rateReviewCurrent,
                    )
                    MainSection.LIBRARY -> LibraryScreen(
                        state = state,
                        onQueryChange = viewModel::updateSearch,
                        onChooseCsv = onChooseCsv,
                    )
                    MainSection.INSIGHTS -> InsightsScreen(state.forecast)
                    MainSection.SETTINGS -> SettingsScreen(
                        fontScale = state.fontScale,
                        onFontScaleChange = viewModel::setFontScale,
                        learntWordCount = state.learntWordCount,
                        reviewBatchSize = state.reviewBatchSize,
                        onReviewBatchSizeChange = viewModel::setReviewBatchSize,
                    )
                }
            }
        }

        state.importReport?.let { report ->
            ImportReportDialog(report, viewModel::dismissImportReport)
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
) {
    if (card == null) {
        EmptyState(Icons.Outlined.CheckCircle, emptyTitle, emptyMessage)
        return
    }
    Column(
        modifier = Modifier.fillMaxSize().padding(20.dp),
    ) {
        PageHeader(title, card.levels.sorted().joinToString(" / "))
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
) {
    if (!state.reviewSessionStarted) {
        Column(
            modifier = Modifier.fillMaxSize().padding(20.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp),
        ) {
            PageHeader("复习", "按掌握权重抽取已学单词")
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
    )
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
            maxLines = 2,
            overflow = TextOverflow.Ellipsis,
        )
        if (card.mnemonic.isNotBlank()) {
            Spacer(Modifier.height(4.dp))
            Text(
                card.mnemonic,
                style = MaterialTheme.typography.labelMedium,
                color = MutedInk,
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
                Column(modifier = Modifier.fillMaxWidth()) {
                    Text(
                        "${index + 1}. ${example.english}",
                        style = MaterialTheme.typography.labelMedium,
                        color = Ink,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                    )
                    Text(
                        example.chinese,
                        style = MaterialTheme.typography.labelMedium,
                        color = MutedInk,
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
private fun LibraryScreen(
    state: MainUiState,
    onQueryChange: (String) -> Unit,
    onChooseCsv: () -> Unit,
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
        }
        Spacer(Modifier.height(12.dp))
        if (state.searchResults.isEmpty()) {
            EmptyState(Icons.AutoMirrored.Outlined.List, "没有匹配词条", "可调整搜索条件或导入 CSV 词库")
        } else {
            LazyColumn(
                modifier = Modifier.fillMaxSize(),
                contentPadding = PaddingValues(bottom = 20.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                items(state.searchResults, key = { it.id }) { entry -> VocabularyRow(entry) }
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
private fun VocabularyRow(entry: VocabularyEntry) {
    Surface(
        modifier = Modifier.fillMaxWidth(),
        color = MaterialTheme.colorScheme.surface,
        shape = RoundedCornerShape(8.dp),
        border = CardDefaults.outlinedCardBorder(),
    ) {
        Column(modifier = Modifier.padding(15.dp), verticalArrangement = Arrangement.spacedBy(5.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
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
) {
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
