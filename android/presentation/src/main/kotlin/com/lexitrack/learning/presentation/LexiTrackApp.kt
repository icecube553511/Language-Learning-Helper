package com.lexitrack.learning.presentation
import android.os.SystemClock
import android.view.View

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.Image
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.gestures.detectDragGestures
import androidx.compose.foundation.gestures.awaitEachGesture
import androidx.compose.foundation.gestures.awaitFirstDown
import androidx.compose.foundation.gestures.awaitTouchSlopOrCancellation
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
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.selection.toggleable
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
import androidx.compose.material3.ProvideTextStyle
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Slider
import androidx.compose.material3.Surface
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateMapOf
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.runtime.setValue
import androidx.compose.runtime.key
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.composed
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Rect
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.Shape
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.draw.scale
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.semantics.Role
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
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.LocalView
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.layout.boundsInWindow
import androidx.compose.ui.layout.LayoutCoordinates
import androidx.compose.ui.layout.onGloballyPositioned
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.input.pointer.PointerEventPass
import androidx.compose.ui.input.pointer.changedToUp
import androidx.compose.ui.input.key.Key
import androidx.compose.ui.input.key.KeyEventType
import androidx.compose.ui.input.key.onPreviewKeyEvent
import androidx.compose.ui.input.key.isCtrlPressed
import androidx.compose.ui.input.key.isMetaPressed
import androidx.compose.ui.input.key.key
import androidx.compose.ui.input.key.type
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.zIndex
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.activity.compose.BackHandler
import com.lexitrack.learning.application.DashboardSnapshot
import com.lexitrack.learning.application.MAX_FONT_SCALE
import com.lexitrack.learning.application.MIN_FONT_SCALE
import com.lexitrack.learning.application.ExportedDictation
import com.lexitrack.learning.application.ForecastDay
import com.lexitrack.learning.application.LibraryGroup
import com.lexitrack.learning.application.sanitizeFontScale
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
import com.lexitrack.learning.domain.PetMode
import com.lexitrack.learning.domain.PetFacing
import com.lexitrack.learning.domain.PetPoint
import com.lexitrack.learning.domain.PetRect
import com.lexitrack.learning.domain.PetState
import com.lexitrack.learning.domain.PetTarget
import com.lexitrack.learning.domain.PetTargetKind
import com.lexitrack.learning.domain.PetMotionSample
import com.lexitrack.learning.domain.estimateReleaseVelocity
import com.lexitrack.learning.domain.beginDrag
import com.lexitrack.learning.domain.advancePet
import com.lexitrack.learning.domain.nearestPetTarget
import com.lexitrack.learning.domain.onNavigation
import com.lexitrack.learning.domain.releaseDrag
import com.lexitrack.learning.domain.PET_CRUISE_SPEED
import com.lexitrack.learning.domain.tokenizeEnglish
import com.lexitrack.learning.domain.normalizeWordId
import java.time.format.DateTimeFormatter
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.drop
import androidx.compose.runtime.snapshotFlow
import kotlin.math.abs
import kotlin.math.exp
import kotlin.math.max
import kotlin.math.roundToInt

internal data class WordBubbleState(val data: BubbleDefinition, val anchor: IntRect)

internal data class WordBubbleHostState(
    val stack: BubbleStack = BubbleStack(),
    val bubbles: List<WordBubbleState> = emptyList(),
)

internal fun openWordBubbleHost(
    state: WordBubbleHostState,
    definition: BubbleDefinition,
    depth: Int,
    anchor: IntRect,
): WordBubbleHostState {
    val nextStack = if (depth < 0) {
        BubbleStack().openRoot(definition)
    } else {
        state.stack.openChild(depth, definition)
    }
    if (nextStack == state.stack) return state
    val previousAnchors = state.bubbles.map(WordBubbleState::anchor)
    return WordBubbleHostState(
        stack = nextStack,
        bubbles = nextStack.frames.mapIndexed { index, frame ->
            WordBubbleState(
                frame.definition,
                if (index == nextStack.frames.lastIndex) anchor else previousAnchors.getOrElse(index) { anchor },
            )
        },
    )
}

internal fun closeWordBubbleHostAfter(state: WordBubbleHostState, depth: Int): WordBubbleHostState =
    state.copy(stack = state.stack.closeAfter(depth), bubbles = state.bubbles.take(depth + 1))

internal fun closeWordBubbleHostAt(state: WordBubbleHostState, depth: Int): WordBubbleHostState =
    state.copy(stack = state.stack.closeBubble(depth), bubbles = state.bubbles.take(depth))

const val DICTATION_DOCX_MIME_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
const val DICTATION_PDF_MIME_TYPE = "application/pdf"

data class DictationSaveSpec(val fileName: String, val mimeType: String)

fun dictationSaveSpec(output: ExportedDictation): DictationSaveSpec {
    val mimeType = output.mimeType.substringBefore(';').trim().lowercase()
    val extension = when (mimeType) {
        DICTATION_DOCX_MIME_TYPE -> "docx"
        DICTATION_PDF_MIME_TYPE -> "pdf"
        else -> error("不支持的默写文档格式：${output.mimeType}")
    }
    val stem = output.fileName.substringBeforeLast('.').ifBlank { "dictation" }
    return DictationSaveSpec("$stem.$extension", mimeType)
}

private val DictationWordColumnWidth = 116.dp
private val DictationMeaningColumnWidth = 210.dp
private val DictationTagsColumnWidth = 156.dp
private val DictationStatusColumnWidth = 84.dp
private val DictationSelectionColumnWidth = 72.dp
private val DictationTableWidth = DictationWordColumnWidth + DictationMeaningColumnWidth +
    DictationTagsColumnWidth + DictationStatusColumnWidth + DictationSelectionColumnWidth

private val LocalOpenWordBubble = staticCompositionLocalOf<(String, String, Int, IntRect) -> Unit> { { _, _, _, _ -> } }
private val LocalBubbleDepth = staticCompositionLocalOf { -1 }
private val LocalDismissWordBubbles = staticCompositionLocalOf<() -> Unit> { {} }
private val LocalRegisterPetTarget = staticCompositionLocalOf<(PetTarget) -> Unit> { {} }
private val LocalRegisterPetWindow = staticCompositionLocalOf<(Any, Boolean) -> Unit> { { _, _ -> } }
private val LocalPetWindowStack = staticCompositionLocalOf<List<Any>> { emptyList() }
private val LocalPetWindowCoordinator = staticCompositionLocalOf<PetWindowCoordinator> { PetWindowCoordinator() }
private val LocalTriggerReward = staticCompositionLocalOf<(RewardEffectMode, Offset) -> Unit> { { _, _ -> } }
// A single navigation revision is shared with dialog hosts so a page change
// always transitions the active pet, regardless of which host currently owns it.
private val LocalPetNavigationKey = staticCompositionLocalOf<Any> { Unit }

internal const val PET_DISPLAY_SIZE_DP = 112
internal const val PET_TICK_MS = 16L
internal const val WORD_BUBBLE_PET_SCOPE = "trigger-window-retained"

internal data class WordBubbleReachability(
    val placementViewport: PetRect,
    val petCorridor: PetRect,
)

internal fun wordBubbleReachability(
    viewport: PetRect,
    petDiameterPx: Float,
): WordBubbleReachability {
    if (!viewport.valid) {
        return WordBubbleReachability(viewport, PetRect(viewport.right, viewport.top, 0f, viewport.height))
    }
    val corridorWidth = petDiameterPx
        .coerceAtLeast(0f)
        .coerceAtMost((viewport.width - 1f).coerceAtLeast(0f))
    val placementWidth = viewport.width - corridorWidth
    return WordBubbleReachability(
        placementViewport = PetRect(viewport.left, viewport.top, placementWidth, viewport.height),
        petCorridor = PetRect(
            viewport.right - corridorWidth,
            viewport.top,
            corridorWidth,
            viewport.height,
        ),
    )
}

private fun Rect.toPetRect(): PetRect = PetRect(left, top, width, height)

internal fun LayoutCoordinates.boundsOnScreen(hostView: View): Rect {
    val windowBounds = boundsInWindow()
    val windowOrigin = IntArray(2)
    hostView.getLocationOnScreen(windowOrigin)
    return Rect(
        left = windowBounds.left + windowOrigin[0],
        top = windowBounds.top + windowOrigin[1],
        right = windowBounds.right + windowOrigin[0],
        bottom = windowBounds.bottom + windowOrigin[1],
    )
}

private fun Modifier.petTarget(
    register: (PetTarget) -> Unit,
    id: String,
    kind: PetTargetKind,
    path: (Rect) -> List<PetPoint> = { emptyList() },
): Modifier = composed {
    val hostView = LocalView.current
    DisposableEffect(register, id, kind) {
        onDispose {
            register(PetTarget(id, kind, PetRect(0f, 0f, 0f, 0f), visible = false))
        }
    }
    Modifier.onGloballyPositioned { coordinates ->
        val bounds = coordinates.boundsOnScreen(hostView)
        register(PetTarget(id, kind, bounds.toPetRect(), path(bounds)))
    }
}

internal fun updatePetTargetRegistry(
    registry: MutableMap<String, PetTarget>,
    prefix: String,
    target: PetTarget,
) {
    val key = "$prefix:${target.id}"
    if (!target.visible || !target.rect.valid) {
        registry.remove(key)
    } else {
        registry[key] = target.copy(id = key)
    }
}

internal fun <T> updatePetWindowStack(
    stack: MutableList<T>,
    key: T,
    active: Boolean,
) {
    stack.removeAll { it == key }
    if (active) stack.add(key)
}

internal fun isMainPetWindowVisible(stack: List<Any>): Boolean = stack.isEmpty()

internal fun isPetWindowVisible(stack: List<Any>, key: Any): Boolean = stack.lastOrNull() === key

internal fun localizePetTargets(
    targets: List<PetTarget>,
    origin: PetPoint,
    viewport: PetRect,
): List<PetTarget> {
    if (!viewport.valid) return emptyList()
    return targets.mapNotNull { target ->
        val localLeft = target.rect.left - origin.x
        val localTop = target.rect.top - origin.y
        val localRight = target.rect.right - origin.x
        val localBottom = target.rect.bottom - origin.y
        val left = localLeft.coerceAtLeast(viewport.left)
        val top = localTop.coerceAtLeast(viewport.top)
        val right = localRight.coerceAtMost(viewport.right)
        val bottom = localBottom.coerceAtMost(viewport.bottom)
        if (!target.visible || right <= left || bottom <= top) return@mapNotNull null
        target.copy(
            rect = PetRect(left, top, right - left, bottom - top),
            path = target.path.map { point ->
                PetPoint(
                    (point.x - origin.x).coerceIn(viewport.left, viewport.right),
                    (point.y - origin.y).coerceIn(viewport.top, viewport.bottom),
                )
            },
        )
    }
}

internal fun wordBubbleOffset(
    anchor: IntRect,
    hostOrigin: PetPoint,
    viewport: PetRect,
    bubbleSize: IntSize,
    gapPx: Int,
): IntOffset {
    val viewportLeft = viewport.left.roundToInt()
    val viewportTop = viewport.top.roundToInt()
    val viewportRight = viewport.right.roundToInt()
    val viewportBottom = viewport.bottom.roundToInt()
    val anchorLeft = anchor.left - hostOrigin.x.roundToInt()
    val anchorTop = anchor.top - hostOrigin.y.roundToInt()
    val anchorBottom = anchor.bottom - hostOrigin.y.roundToInt()
    val maxX = (viewportRight - bubbleSize.width).coerceAtLeast(viewportLeft)
    val centeredX = anchorLeft + (anchor.width - bubbleSize.width) / 2
    val x = centeredX.coerceIn(viewportLeft, maxX)
    val below = anchorBottom + gapPx
    val above = anchorTop - bubbleSize.height - gapPx
    val maxY = (viewportBottom - bubbleSize.height).coerceAtLeast(viewportTop)
    val y = if (below + bubbleSize.height <= viewportBottom) below else above
    return IntOffset(x, y.coerceIn(viewportTop, maxY))
}

@Composable
private fun PetOverlay(
    viewport: PetRect,
    windowId: String,
    windowOrigin: PetPoint,
    targets: List<PetTarget>,
    navigationKey: Any,
    onPointerActiveChange: (Boolean) -> Unit,
    preferredActive: Boolean = true,
) {
    val petSize = PET_DISPLAY_SIZE_DP.dp
    val density = LocalDensity.current
    val halfSize = with(density) { petSize.toPx() / 2f }
    val coordinator = LocalPetWindowCoordinator.current
    var state by remember {
        mutableStateOf(PetState(PetPoint(halfSize + 12f, halfSize + 96f)))
    }
    var dragSamples by remember { mutableStateOf<List<PetMotionSample>>(emptyList()) }
    var completedDrag by remember { mutableStateOf(0) }
    var dragCaptureActive by remember { mutableStateOf(false) }
    var wasPreferredActive by remember(windowId) { mutableStateOf(false) }
    var previousNavigationKey by remember(windowId) { mutableStateOf(navigationKey) }
    val edgeTargets = remember(viewport) {
        if (viewport.width <= 0f || viewport.height <= 0f) {
            emptyList()
        } else {
            listOf(
                PetTarget("edge:right", PetTargetKind.EDGE, PetRect(viewport.right - 1f, 0f, 1f, viewport.height)),
                PetTarget("edge:bottom", PetTargetKind.EDGE, PetRect(0f, viewport.bottom - 1f, viewport.width, 1f)),
                PetTarget("edge:left", PetTargetKind.EDGE, PetRect(0f, 0f, 1f, viewport.height)),
            )
        }
    }
    val activeTargets = targets + edgeTargets
    // Keep the fixed-step loop alive while Compose refreshes geometry. Reading
    // these wrappers inside the coroutine avoids restarting the ticker on each
    // newly allocated target list and keeps high-speed motion cadence stable.
    val latestViewport by rememberUpdatedState(viewport)
    val latestActiveTargets by rememberUpdatedState(activeTargets)
    val latestHalfSize by rememberUpdatedState(halfSize)
    val latestDensityScale by rememberUpdatedState(density.density)
    fun samplePosition(local: PetPoint): PetPoint =
        coordinator.worldPosition()?.takeIf { coordinator.activeWindowId != null }
            ?: PetPoint(windowOrigin.x + local.x, windowOrigin.y + local.y)
    val windowRect = PetRect(windowOrigin.x, windowOrigin.y, viewport.width, viewport.height)
    LaunchedEffect(windowId, windowRect, preferredActive, halfSize) {
        if (windowRect.valid) {
            coordinator.registerWindow(
                PetWindow(windowId, windowRect, order = 0, mapped = true, viewable = true),
                active = false,
            )
            if (preferredActive && (!wasPreferredActive || coordinator.activeWindowId == null)) {
                coordinator.activate(windowId, halfSize)
            }
            wasPreferredActive = preferredActive
            if (coordinator.activeWindowId == windowId) {
                if (!coordinator.hasState) {
                    coordinator.updateState(state)
                } else {
                    state = coordinator.state
                }
            }
        }
    }
    DisposableEffect(windowId) {
        onDispose { coordinator.unregisterWindow(windowId, halfSize) }
    }
    LaunchedEffect(windowId, activeTargets) {
        coordinator.updateTargets(windowId, activeTargets)
    }
    val ownership = petOverlayOwnership(coordinator.activeWindowId, windowId, dragCaptureActive)
    val visualState = if (ownership.renders) coordinator.state else state
    LaunchedEffect(windowId, coordinator.activeWindowId) {
        if (coordinator.activeWindowId == windowId) state = coordinator.state
    }
    val displayPosition = if (viewport.valid) {
        val clamped = viewport.clamp(visualState.position, halfSize)
        if (visualState.mode == PetMode.FALL || visualState.mode == PetMode.FLING) {
            PetPoint(clamped.x, visualState.position.y)
        } else clamped
    } else visualState.position
    // Animate between fixed simulation ticks. Dragging remains synchronous so
    // the pointer never lags behind the sprite while the user holds it.
    val animatedX by animateFloatAsState(
        targetValue = displayPosition.x,
        animationSpec = tween(PET_TICK_MS.toInt(), easing = LinearEasing),
        label = "bingzi-x",
    )
    val animatedY by animateFloatAsState(
        targetValue = displayPosition.y,
        animationSpec = tween(PET_TICK_MS.toInt(), easing = LinearEasing),
        label = "bingzi-y",
    )
    LaunchedEffect(navigationKey) {
        val navigationChanged = previousNavigationKey != navigationKey
        previousNavigationKey = navigationKey
        if (navigationChanged && coordinator.activeWindowId == windowId) {
            state = onNavigation(coordinator.state)
            coordinator.updateState(state)
        }
    }
    LaunchedEffect(completedDrag) {
        if (completedDrag > 0) {
            delay(100)
            onPointerActiveChange(false)
        }
    }
    LaunchedEffect(windowId) {
        while (true) {
            delay(PET_TICK_MS)
            val currentViewport = latestViewport
            val currentHalfSize = latestHalfSize
            val currentScale = latestDensityScale
            if (currentViewport.width > 0f && currentViewport.height > 0f) {
                if (coordinator.activeWindowId != windowId) continue
                // A rating card rebuild can briefly replace the target set and
                // recompute geometry.  A transient error on one frame must not
                // cancel the ticker, otherwise Bingzi freezes for the rest of
                // the session; only an actual coroutine cancellation stops it.
                try {
                    state = coordinator.state
                    // Hand a fast fling to an adjacent host before the domain
                    // reducer applies its local wall restitution.  Without this
                    // predictive check a 16 ms tick can reflect the pet before
                    // the portal sees the outward velocity.
                    if (coordinator.migrateIfNeeded(
                            windowId,
                            currentHalfSize,
                            lookaheadSeconds = PET_TICK_MS / 1_000f,
                            fallUnitScale = currentScale,
                        )
                    ) {
                        state = coordinator.state
                        continue
                    }
                    state = advancePet(
                        state = state,
                        targets = latestActiveTargets,
                        viewport = currentViewport,
                        halfSize = currentHalfSize,
                        step = PET_CRUISE_SPEED,
                        fallUnitScale = currentScale,
                    )
                    coordinator.updateState(state)
                } catch (cancellation: CancellationException) {
                    throw cancellation
                } catch (_: Exception) {
                    // Skip the failed frame and keep the loop alive.
                }
            }
        }
    }
    if ((!ownership.renders && !ownership.capturesGesture) || !viewport.valid) return
    val renderedPosition = if (visualState.mode == PetMode.DRAGGING) {
        displayPosition
    } else {
        PetPoint(animatedX, animatedY)
    }
    Image(
        painter = painterResource(
            if (visualState.facing == PetFacing.LEFT) R.drawable.bingzi_left else R.drawable.bingzi,
        ),
        contentDescription = if (ownership.renders) "冰子" else null,
        modifier = Modifier
            .zIndex(20f)
            .alpha(if (ownership.renders) 1f else 0f)
            .offset {
                IntOffset(
                    (if (visualState.mode == PetMode.DRAGGING) displayPosition.x - halfSize else animatedX - halfSize).roundToInt(),
                    (if (visualState.mode == PetMode.DRAGGING) displayPosition.y - halfSize else animatedY - halfSize).roundToInt(),
                )
            }
            .size(petSize)
            .scale(if (visualState.mode == PetMode.FALL) 0.96f else 1f)
            .pointerInput(viewport, halfSize) {
                detectDragGestures(
                    onDragStart = { localOffset ->
                        onPointerActiveChange(true)
                        dragCaptureActive = true
                        val dragged = beginDrag(
                            coordinator.state.copy(position = renderedPosition),
                            PetPoint(
                                renderedPosition.x - halfSize + localOffset.x,
                                renderedPosition.y - halfSize + localOffset.y,
                            ),
                        )
                        state = dragged
                        coordinator.updateState(dragged)
                        dragSamples = listOf(PetMotionSample(SystemClock.uptimeMillis(), samplePosition(dragged.position)))
                    },
                    onDrag = { change, dragAmount ->
                        change.consume()
                        coordinator.dragActiveBy(PetPoint(dragAmount.x, dragAmount.y), halfSize)
                        state = coordinator.state
                        if (state.mode == PetMode.DRAGGING) {
                            dragSamples = (dragSamples + PetMotionSample(SystemClock.uptimeMillis(), samplePosition(state.position)))
                                .takeLast(32)
                        }
                    },
                    onDragEnd = {
                        val releaseVelocity = estimateReleaseVelocity(dragSamples, nowMs = SystemClock.uptimeMillis())
                        state = releaseDrag(
                            coordinator.state,
                            coordinator.targetsFor(),
                            coordinator.viewportFor(),
                            halfSize,
                            releaseVelocity,
                        )
                        coordinator.updateState(state)
                        dragSamples = emptyList()
                        dragCaptureActive = false
                        completedDrag += 1
                    },
                    onDragCancel = {
                        val releaseVelocity = estimateReleaseVelocity(dragSamples, nowMs = SystemClock.uptimeMillis())
                        state = releaseDrag(
                            coordinator.state,
                            coordinator.targetsFor(),
                            coordinator.viewportFor(),
                            halfSize,
                            releaseVelocity,
                        )
                        coordinator.updateState(state)
                        dragSamples = emptyList()
                        dragCaptureActive = false
                        completedDrag += 1
                    },
                )
            },
    )
}

@Composable
private fun PetAlertDialog(
    petId: String,
    wordBubbleLookup: ((String, String) -> BubbleDefinition)? = null,
    onDismissRequest: () -> Unit,
    title: @Composable () -> Unit,
    text: @Composable () -> Unit,
    confirmButton: @Composable () -> Unit,
    dismissButton: (@Composable () -> Unit)? = null,
    icon: (@Composable () -> Unit)? = null,
    shape: Shape = RoundedCornerShape(8.dp),
) {
    val registerPetWindow = LocalRegisterPetWindow.current
    val petWindowStack = LocalPetWindowStack.current
    val inheritedOpenWordBubble = LocalOpenWordBubble.current
    val inheritedDismissWordBubbles = LocalDismissWordBubbles.current
    val petWindowKey = remember { Any() }
    val targets = remember { mutableStateMapOf<String, PetTarget>() }
    var viewport by remember { mutableStateOf(PetRect(0f, 0f, 0f, 0f)) }
    var viewportOrigin by remember { mutableStateOf(PetPoint(0f, 0f)) }
    var localBubbleHost by remember(petWindowKey) { mutableStateOf(WordBubbleHostState()) }
    val openWordBubble: (String, String, Int, IntRect) -> Unit = if (wordBubbleLookup == null) {
        inheritedOpenWordBubble
    } else {
        { token, contextExample, depth, anchor ->
            localBubbleHost = openWordBubbleHost(
                localBubbleHost,
                wordBubbleLookup(token, contextExample),
                depth,
                anchor,
            )
        }
    }
    val dismissWordBubbles: () -> Unit = if (wordBubbleLookup == null) {
        inheritedDismissWordBubbles
    } else {
        { localBubbleHost = WordBubbleHostState() }
    }
    val registerTarget: (PetTarget) -> Unit = remember(petId) {
        { target -> updatePetTargetRegistry(targets, petId, target) }
    }
    DisposableEffect(registerPetWindow, petWindowKey) {
        registerPetWindow(petWindowKey, true)
        onDispose { registerPetWindow(petWindowKey, false) }
    }
    Dialog(onDismissRequest = onDismissRequest) {
        val hostView = LocalView.current
        CompositionLocalProvider(
            LocalOpenWordBubble provides openWordBubble,
            LocalDismissWordBubbles provides dismissWordBubbles,
            LocalRegisterPetTarget provides registerTarget,
        ) {
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .widthIn(min = 280.dp, max = 560.dp)
                    .heightIn(min = PET_DISPLAY_SIZE_DP.dp)
                    .onGloballyPositioned { coordinates ->
                        val bounds = coordinates.boundsOnScreen(hostView)
                        viewportOrigin = PetPoint(bounds.left, bounds.top)
                        viewport = PetRect(
                            0f,
                            0f,
                            coordinates.size.width.toFloat(),
                            coordinates.size.height.toFloat(),
                        )
                    },
            ) {
                Surface(
                    modifier = Modifier
                        .fillMaxWidth()
                        .petTarget(registerTarget, "$petId-frame", PetTargetKind.SURFACE),
                    shape = shape,
                    color = MaterialTheme.colorScheme.surface,
                    tonalElevation = 6.dp,
                ) {
                    Column(
                        modifier = Modifier.padding(24.dp),
                        verticalArrangement = Arrangement.spacedBy(14.dp),
                    ) {
                        icon?.let { content ->
                            Box(modifier = Modifier.fillMaxWidth(), contentAlignment = Alignment.Center) { content() }
                        }
                        ProvideTextStyle(MaterialTheme.typography.headlineSmall) { title() }
                        Box(modifier = Modifier.fillMaxWidth().heightIn(max = 520.dp)) {
                            ProvideTextStyle(MaterialTheme.typography.bodyMedium) { text() }
                        }
                        Row(
                            modifier = Modifier.fillMaxWidth(),
                            horizontalArrangement = Arrangement.End,
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            dismissButton?.let { content ->
                                Box(
                                    modifier = Modifier.petTarget(
                                        registerTarget,
                                        "$petId-dismiss",
                                        PetTargetKind.CONTROL,
                                    ),
                                ) { content() }
                                Spacer(Modifier.width(8.dp))
                            }
                            Box(
                                modifier = Modifier.petTarget(
                                    registerTarget,
                                    "$petId-confirm",
                                    PetTargetKind.CONTROL,
                                ),
                            ) { confirmButton() }
                        }
                    }
                }
                if (wordBubbleLookup != null) {
                    WordBubbleOverlay(
                        bubbles = localBubbleHost.bubbles,
                        hostOrigin = viewportOrigin,
                        viewport = viewport,
                        onCloseAfter = { depth ->
                            localBubbleHost = closeWordBubbleHostAfter(localBubbleHost, depth)
                        },
                        onDismissCurrent = { depth ->
                            localBubbleHost = closeWordBubbleHostAt(localBubbleHost, depth)
                        },
                    )
                }
                PetOverlay(
                    viewport = viewport,
                    windowId = petId,
                    windowOrigin = viewportOrigin,
                    targets = localizePetTargets(targets.values.toList(), viewportOrigin, viewport),
                    navigationKey = LocalPetNavigationKey.current,
                    onPointerActiveChange = {},
                    preferredActive = isPetWindowVisible(petWindowStack, petWindowKey),
                )
            }
        }
    }
}

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
    var bubbleHost by remember { mutableStateOf(WordBubbleHostState()) }
    val petTargets = remember { mutableStateMapOf<String, PetTarget>() }
    val petWindows = remember { mutableStateListOf<Any>() }
    var petViewport by remember { mutableStateOf(PetRect(0f, 0f, 0f, 0f)) }
    var petViewportOrigin by remember { mutableStateOf(PetPoint(0f, 0f)) }
    var petPointerActive by remember { mutableStateOf(false) }
    var rewardRequests by remember { mutableStateOf<List<RewardEffectRequest>>(emptyList()) }
    var rewardSequence by remember { mutableStateOf(0L) }
    val hostView = LocalView.current
    val petWindowCoordinator = remember {
        PetWindowCoordinator()
    }
    val openBubble: (String, String, Int, IntRect) -> Unit = { token, contextExample, depth, anchor ->
        val definition = viewModel.lookupWordBubble(token, contextExample)
        bubbleHost = openWordBubbleHost(bubbleHost, definition, depth, anchor)
    }
    LaunchedEffect(state.section, state.currentCard?.id, state.reviewCard?.id, state.wordReminderCard?.id) {
        bubbleHost = WordBubbleHostState()
    }
    LaunchedEffect(state.section) {
        petTargets.clear()
        rewardRequests = emptyList()
    }
    val registerPetTarget: (PetTarget) -> Unit = remember(state.section) {
        val prefix = state.section.name.lowercase()
        val register: (PetTarget) -> Unit = { target ->
            updatePetTargetRegistry(petTargets, prefix, target)
        }
        register
    }
    val registerPetWindow: (Any, Boolean) -> Unit = remember {
        { key, active ->
            updatePetWindowStack(petWindows, key, active)
        }
    }
    LexiTrackTheme(state.fontScale) {
        CompositionLocalProvider(
            LocalOpenWordBubble provides openBubble,
            LocalDismissWordBubbles provides {
                bubbleHost = WordBubbleHostState()
            },
            LocalRegisterPetTarget provides registerPetTarget,
            LocalRegisterPetWindow provides registerPetWindow,
            LocalPetWindowStack provides petWindows,
            LocalPetWindowCoordinator provides petWindowCoordinator,
            LocalTriggerReward provides { mode, start ->
                (rewardTargetOrViewportCenter(
                    target = petWindowCoordinator.worldPosition(),
                    viewportOrigin = petViewportOrigin,
                    viewport = petViewport,
                ) ?: start).let { targetPoint ->
                    val request = RewardEffectRequest(
                        id = ++rewardSequence,
                        start = start,
                        target = targetPoint,
                        color = rewardColor(mode),
                    )
                    rewardRequests = (rewardRequests + request).takeLast(PET_ENERGY_BALL_MAX_CONCURRENT)
                }
            },
            LocalPetNavigationKey provides state.section,
        ) {
            Box(
                modifier = Modifier
                    .fillMaxSize()
                    .onGloballyPositioned { coordinates ->
                        val bounds = coordinates.boundsOnScreen(hostView)
                        petViewportOrigin = PetPoint(bounds.left, bounds.top)
                        petViewport = PetRect(0f, 0f, coordinates.size.width.toFloat(), coordinates.size.height.toFloat())
                    }
                    .pointerInput(Unit) {
                        awaitPointerEventScope {
                            while (true) {
                                val event = awaitPointerEvent(PointerEventPass.Final)
                                if (!petPointerActive && event.changes.any { it.changedToUp() && !it.isConsumed }) {
                                    bubbleHost = WordBubbleHostState()
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
                        onRate = { rating -> viewModel.rateCurrent(rating) },
                        rewardMode = RewardEffectMode.STUDY,
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
                        onRate = { rating -> viewModel.rateReviewCurrent(rating) },
                        onLevelsChange = viewModel::setReviewLevels,
                    )
                    MainSection.DICTATION -> {
                        BackHandler(enabled = true) {
                            if (state.dictationDirty) viewModel.requestDictationLeave()
                            else viewModel.selectSection(MainSection.DASHBOARD)
                        }
                        if (state.dictationLoading) {
                            DictationLoadingOverlay()
                        } else {
                            DictationScreen(
                                state = state,
                                onToggleSelection = viewModel::toggleDictationSelection,
                                onSetSelection = viewModel::setDictationSelection,
                                onSetGroup = viewModel::setDictationGroup,
                                onSetManualMode = viewModel::setDictationManualMode,
                                onSelectRangeToHere = viewModel::selectDictationRangeToHere,
                                onEndRange = viewModel::endDictationRange,
                                onSetScrollPosition = viewModel::setDictationScrollPosition,
                                onSaveDraft = viewModel::saveDictationDraft,
                                onClearDraft = viewModel::clearDictationSelection,
                                onConfigChange = viewModel::updateDictationConfig,
                                onBuild = { options, count, group, includeEvaluated, manual, customExample ->
                                    viewModel.buildDictation(options, count, group, includeEvaluated, manual, customExample)
                                    dictationPreviewOpen = true
                                },
                            )
                        }
                    }
                    MainSection.LIBRARY -> LibraryScreen(
                        state = state,
                        onQueryChange = viewModel::updateSearch,
                        onChooseCsv = onChooseCsv,
                        onToggleSelection = viewModel::toggleVocabularySelection,
                        onEditLabels = { labelEditorOpen = true },
                        onSelectGroup = viewModel::selectLibraryGroup,
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

        WordBubbleOverlay(
            bubbles = bubbleHost.bubbles,
            hostOrigin = petViewportOrigin,
            viewport = petViewport,
            onCloseAfter = { depth ->
                bubbleHost = closeWordBubbleHostAfter(bubbleHost, depth)
            },
            onDismissCurrent = { depth ->
                bubbleHost = closeWordBubbleHostAt(bubbleHost, depth)
            },
        )

        PetOverlay(
            viewport = petViewport,
            windowId = "main",
            windowOrigin = petViewportOrigin,
            targets = localizePetTargets(petTargets.values.toList(), petViewportOrigin, petViewport),
            navigationKey = state.section,
            onPointerActiveChange = { petPointerActive = it },
            preferredActive = isMainPetWindowVisible(petWindows),
        )

        rewardRequests.forEach { request ->
            RewardEffectsHost(
                request = request,
                hostOrigin = petViewportOrigin,
                targetProvider = {
                    petWindowCoordinator.worldPosition()?.let { Offset(it.x, it.y) }
                },
                onFinished = { id ->
                    rewardRequests = rewardRequests.filterNot { it.id == id }
                },
                modifier = Modifier.fillMaxSize(),
            )
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
        if (state.dictationLeaveRequested) {
            PetAlertDialog(
                petId = "dictation-leave",
                onDismissRequest = viewModel::dismissDictationLeavePrompt,
                title = { Text("保存默写选择") },
                text = { Text("默写纸有未保存的选择，是否保存？") },
                confirmButton = {
                    TextButton(onClick = { viewModel.confirmDictationLeave(save = true) }) { Text("保存") }
                },
                dismissButton = {
                    Row {
                        TextButton(onClick = { viewModel.confirmDictationLeave(save = false) }) { Text("不保存") }
                        TextButton(onClick = viewModel::dismissDictationLeavePrompt) { Text("继续编辑") }
                    }
                },
            )
        }
        state.dictationSyncConflict?.let { conflict ->
            PetAlertDialog(
                petId = "dictation-sync-conflict",
                onDismissRequest = viewModel::dismissDictationSyncConflict,
                title = { Text("默写选择同步冲突") },
                text = {
                    val localCount = conflict.local.draft?.selectedIds?.size ?: 0
                    val remoteCount = conflict.remote.draft?.selectedIds?.size ?: 0
                    Text("本机有 $localCount 个已选词，远端有 $remoteCount 个已选词。请选择要保留的版本。")
                },
                confirmButton = {
                    TextButton(onClick = { viewModel.resolveDictationSyncConflict(useRemote = true) }) {
                        Text("使用远端")
                    }
                },
                dismissButton = {
                    Row {
                        TextButton(onClick = { viewModel.resolveDictationSyncConflict(useRemote = false) }) {
                            Text("保留本机")
                        }
                        TextButton(onClick = viewModel::dismissDictationSyncConflict) {
                            Text("稍后处理")
                        }
                    }
                },
            )
        }
        state.transientMessage?.let { message ->
            MessageDialog(message, viewModel::dismissMessage)
        }
        state.reviewReminderMessage?.let { message ->
            PetAlertDialog(
                petId = "review-reminder",
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
            PetAlertDialog(
                petId = "word-reminder",
                wordBubbleLookup = { token, contextExample ->
                    viewModel.lookupWordBubble(token, contextExample)
                },
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
    val dismissBubbles = LocalDismissWordBubbles.current
    val hostView = LocalView.current
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
                val rect = coordinates.boundsOnScreen(hostView)
                bounds = IntRect(rect.left.toInt(), rect.top.toInt(), rect.right.toInt(), rect.bottom.toInt())
            }
            .pointerInput(annotated, bounds) {
                detectTapGestures(
                    onTap = tap@{ offset ->
                        val textLayout = layout ?: run {
                            dismissBubbles()
                            return@tap
                        }
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
                        } else {
                            dismissBubbles()
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
    bubbles: List<WordBubbleState>,
    hostOrigin: PetPoint,
    viewport: PetRect,
    onCloseAfter: (Int) -> Unit,
    onDismissCurrent: (Int) -> Unit,
) {
    if (!viewport.valid) return
    val density = LocalDensity.current
    val reachability = wordBubbleReachability(
        viewport = viewport,
        petDiameterPx = with(density) { PET_DISPLAY_SIZE_DP.dp.toPx() },
    )
    val bubbleViewport = reachability.placementViewport
    if (!bubbleViewport.valid) return
    val maxBubbleWidth = with(density) { bubbleViewport.width.toDp() }.coerceAtMost(440.dp)
    val minBubbleWidth = maxBubbleWidth.coerceAtMost(260.dp)
    val maxBubbleHeight = with(density) { bubbleViewport.height.toDp() }
    val registerPetTarget = LocalRegisterPetTarget.current
    Box(modifier = Modifier.fillMaxSize().zIndex(10f)) {
        bubbles.forEachIndexed { index, bubble ->
            var bubbleSize by remember(bubble.data.wordId, bubble.anchor) { mutableStateOf(IntSize.Zero) }
            val gapPx = with(density) { 6.dp.roundToPx() }
            // Root content uses -1; a bubble's depth is its zero-based stack index.
            CompositionLocalProvider(
                LocalBubbleDepth provides index,
                LocalDismissWordBubbles provides { onCloseAfter(index) },
            ) {
                Box(
                    modifier = Modifier
                        .offset {
                            wordBubbleOffset(
                                anchor = bubble.anchor,
                                hostOrigin = hostOrigin,
                                viewport = bubbleViewport,
                                bubbleSize = bubbleSize,
                                gapPx = gapPx,
                            )
                        }
                        .widthIn(min = minBubbleWidth, max = maxBubbleWidth)
                        .heightIn(max = maxBubbleHeight)
                        .onSizeChanged { bubbleSize = it },
                ) {
                    Surface(
                        modifier = Modifier
                            .fillMaxWidth()
                            .petTarget(
                                registerPetTarget,
                                "word-bubble-${bubble.data.wordId}-$index",
                                PetTargetKind.SURFACE,
                            )
                            .pointerInput(index) {
                                awaitPointerEventScope {
                                    while (true) {
                                        val event = awaitPointerEvent(PointerEventPass.Final)
                                        event.changes.firstOrNull { it.changedToUp() && !it.isConsumed }?.let { change ->
                                            onCloseAfter(index)
                                            change.consume()
                                        }
                                    }
                                }
                            },
                        color = MaterialTheme.colorScheme.surface,
                        shape = RoundedCornerShape(8.dp),
                        shadowElevation = 8.dp,
                        border = CardDefaults.outlinedCardBorder(),
                    ) {
                        Column(
                            modifier = Modifier
                                .padding(12.dp)
                                .verticalScroll(rememberScrollState()),
                            verticalArrangement = Arrangement.spacedBy(5.dp),
                        ) {
                            Row(
                                modifier = Modifier.fillMaxWidth(),
                                verticalAlignment = Alignment.CenterVertically,
                            ) {
                                Text(
                                    bubble.data.word,
                                    style = MaterialTheme.typography.titleLarge,
                                    color = Ink,
                                    modifier = Modifier.weight(1f),
                                )
                                TextButton(
                                    onClick = { onDismissCurrent(index) },
                                    contentPadding = PaddingValues(0.dp),
                                    modifier = Modifier
                                        .size(30.dp)
                                        .petTarget(
                                            registerPetTarget,
                                            "word-bubble-${bubble.data.wordId}-$index-close",
                                            PetTargetKind.CONTROL,
                                        ),
                                ) {
                                    Text("✕", color = MutedInk)
                                }
                            }
                            if (bubble.data.phonetic.isNotBlank()) {
                                Text(bubble.data.phonetic, style = MaterialTheme.typography.labelMedium, color = BrandTeal)
                            }
                            if (bubble.data.partOfSpeech.isNotBlank()) {
                                Text(bubble.data.partOfSpeech, style = MaterialTheme.typography.labelMedium, color = BusinessAmber)
                            }
                            Text(bubble.data.meaning, style = MaterialTheme.typography.bodyMedium, color = Ink)
                            val examplePairs = bubble.data.examplePairs.ifEmpty {
                                bubble.data.examples.map { it to "" }
                            }
                            examplePairs.forEach { (english, chinese) ->
                                InteractiveSentence(
                                    text = english,
                                    style = MaterialTheme.typography.labelMedium,
                                    color = MutedInk,
                                    modifier = Modifier.fillMaxWidth(),
                                )
                                if (chinese.isNotBlank()) {
                                    Text(
                                        text = chinese,
                                        style = MaterialTheme.typography.labelMedium,
                                        color = Ink,
                                        modifier = Modifier.fillMaxWidth(),
                                    )
                                }
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
    val registerPetTarget = LocalRegisterPetTarget.current
    Surface(
        modifier = Modifier
            .statusBarsPadding()
            .petTarget(registerPetTarget, "app-header", PetTargetKind.SURFACE),
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
                modifier = Modifier
                    .size(44.dp)
                    .petTarget(registerPetTarget, "app-logo", PetTargetKind.SURFACE),
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
    val registerPetTarget = LocalRegisterPetTarget.current
    val items = listOf(
        NavigationItem(MainSection.DASHBOARD, "总览", Icons.Outlined.Home),
        NavigationItem(MainSection.STUDY, "学习", Icons.Outlined.School),
        NavigationItem(MainSection.REVIEW, "复习", Icons.Outlined.Refresh),
        NavigationItem(MainSection.DICTATION, "默写纸", Icons.Outlined.Edit),
        NavigationItem(MainSection.LIBRARY, "词库", Icons.AutoMirrored.Outlined.List),
        NavigationItem(MainSection.INSIGHTS, "趋势", Icons.Outlined.BarChart),
        NavigationItem(MainSection.SETTINGS, "设置", Icons.Outlined.Settings),
    )
    NavigationBar(
        modifier = Modifier
            .navigationBarsPadding()
            .petTarget(registerPetTarget, "navigation", PetTargetKind.SURFACE),
        containerColor = MaterialTheme.colorScheme.surface,
        tonalElevation = 1.dp,
    ) {
        items.forEach { item ->
            NavigationBarItem(
                modifier = Modifier.petTarget(
                    registerPetTarget,
                    "nav-${item.section.name.lowercase()}",
                    PetTargetKind.CONTROL,
                ),
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
    val registerPetTarget = LocalRegisterPetTarget.current
    LazyColumn(
        modifier = Modifier.fillMaxSize(),
        contentPadding = PaddingValues(20.dp),
        verticalArrangement = Arrangement.spacedBy(18.dp),
    ) {
        item { PageHeader("今日总览", "掌握节奏，完成当前到期内容") }
        item { CatalogStatusStrip(state) }
        item { DashboardStats(state.dashboard) }
        item {
            SectionTitle("记忆保持率", "以 3 天稳定间隔展示")
            Spacer(Modifier.height(12.dp))
            MemoryCurve()
        }
        item {
            Button(
                onClick = if (state.dashboard.dueNow > 0) onReview else onStudy,
                modifier = Modifier
                    .fillMaxWidth()
                    .heightIn(min = 52.dp)
                    .petTarget(registerPetTarget, "dashboard-action", PetTargetKind.CONTROL),
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
    val registerPetTarget = LocalRegisterPetTarget.current
    Surface(
        modifier = Modifier
            .fillMaxWidth()
            .petTarget(registerPetTarget, "catalog-status", PetTargetKind.SURFACE),
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
    val registerPetTarget = LocalRegisterPetTarget.current
    Surface(
        modifier = modifier
            .heightIn(min = 108.dp)
            .petTarget(registerPetTarget, "stat-${label.hashCode()}", PetTargetKind.SURFACE),
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
    rewardMode: RewardEffectMode = RewardEffectMode.STUDY,
    title: String,
    emptyTitle: String,
    emptyMessage: String,
    filterTitle: String = "",
    selectedLevels: Set<String> = emptySet(),
    availableLevels: List<String> = emptyList(),
    onLevelsChange: (Set<String>) -> Unit = {},
) {
    val registerPetTarget = LocalRegisterPetTarget.current
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
            modifier = Modifier
                .fillMaxWidth()
                .weight(1f)
                .petTarget(registerPetTarget, "study-card", PetTargetKind.SURFACE),
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
                        modifier = Modifier
                            .fillMaxWidth()
                            .heightIn(min = 50.dp)
                            .petTarget(registerPetTarget, "study-reveal", PetTargetKind.CONTROL),
                    ) {
                        Icon(Icons.Outlined.Visibility, contentDescription = null)
                        Spacer(Modifier.width(8.dp))
                        Text("查看答案")
                    }
                } else {
                    RevealedCardContent(
                        card = card,
                        onRate = onRate,
                        rewardMode = rewardMode,
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
    val registerPetTarget = LocalRegisterPetTarget.current
    if (!state.reviewSessionStarted) {
        Column(
            modifier = Modifier.fillMaxSize().padding(20.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp),
        ) {
            PageHeader("复习", "按掌握权重抽取已学单词")
            LevelFilterRow("复习词汇组", state.reviewLevels, state.availableLevels, onLevelsChange)
            Surface(
                modifier = Modifier
                    .fillMaxWidth()
                    .petTarget(registerPetTarget, "review-summary", PetTargetKind.SURFACE),
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
                        modifier = Modifier
                            .fillMaxWidth()
                            .heightIn(min = 52.dp)
                            .petTarget(registerPetTarget, "review-start", PetTargetKind.CONTROL),
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
            Button(
                onClick = onStart,
                enabled = state.learntWordCount > 0,
                modifier = Modifier.petTarget(registerPetTarget, "review-restart", PetTargetKind.CONTROL),
            ) {
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
        rewardMode = RewardEffectMode.REVIEW,
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
    val registerPetTarget = LocalRegisterPetTarget.current
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
                    modifier = Modifier.petTarget(
                        registerPetTarget,
                        "level-${title.hashCode()}-${level.lowercase()}",
                        PetTargetKind.CONTROL,
                    ),
                )
            }
        }
    }
}

@Composable
private fun RevealedCardContent(
    card: VocabularyEntry,
    onRate: (ReviewRating) -> Unit,
    rewardMode: RewardEffectMode,
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
                    )
                    Text(
                        example.chinese,
                        modifier = Modifier.fillMaxWidth(),
                        style = MaterialTheme.typography.labelMedium,
                        color = MutedInk,
                        textAlign = TextAlign.Center,
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
            RatingButton("忘记", BusinessRed, Modifier.weight(1f), rewardMode) { onRate(ReviewRating.AGAIN) }
            RatingButton("模糊", BusinessAmber, Modifier.weight(1f), rewardMode) { onRate(ReviewRating.HARD) }
            RatingButton("认识", BrandTeal, Modifier.weight(1f), rewardMode) { onRate(ReviewRating.GOOD) }
            RatingButton("很熟", BrandNavy, Modifier.weight(1f), rewardMode) { onRate(ReviewRating.EASY) }
        }
    }
}

@Composable
private fun RatingButton(
    label: String,
    color: Color,
    modifier: Modifier,
    rewardMode: RewardEffectMode,
    onClick: () -> Unit,
) {
    val registerPetTarget = LocalRegisterPetTarget.current
    val triggerReward = LocalTriggerReward.current
    val hostView = LocalView.current
    var buttonBounds by remember { mutableStateOf(Rect.Zero) }
    Button(
        onClick = {
            onClick()
        },
        modifier = modifier
            .heightIn(min = 58.dp)
            .onGloballyPositioned { coordinates -> buttonBounds = coordinates.boundsOnScreen(hostView) }
            .pointerInput(rewardMode, triggerReward, buttonBounds) {
                awaitEachGesture {
                    val down = awaitFirstDown(
                        requireUnconsumed = false,
                        pass = PointerEventPass.Initial,
                    )
                    if (buttonBounds.width > 0f && buttonBounds.height > 0f) {
                        triggerReward(
                            rewardMode,
                            Offset(
                                buttonBounds.left + down.position.x,
                                buttonBounds.top + down.position.y,
                            ),
                        )
                    }
                }
            }
            .petTarget(registerPetTarget, "rating-${label.hashCode()}", PetTargetKind.CONTROL),
        colors = ButtonDefaults.buttonColors(containerColor = color, contentColor = Color.White),
        shape = RoundedCornerShape(8.dp),
        contentPadding = PaddingValues(horizontal = 5.dp, vertical = 10.dp),
    ) {
        Text(label, style = MaterialTheme.typography.labelLarge, maxLines = 1)
    }
}

@Composable
private fun DictationLoadingOverlay() {
    val registerPetTarget = LocalRegisterPetTarget.current
    Box(
        modifier = Modifier
            .fillMaxSize()
            .background(MaterialTheme.colorScheme.background),
        contentAlignment = Alignment.Center,
    ) {
        Surface(
            modifier = Modifier.petTarget(registerPetTarget, "dictation-loading", PetTargetKind.SURFACE),
            shape = RoundedCornerShape(8.dp),
            color = MaterialTheme.colorScheme.surface,
            border = CardDefaults.outlinedCardBorder(),
        ) {
            Column(
                modifier = Modifier.padding(horizontal = 48.dp, vertical = 36.dp),
                horizontalAlignment = Alignment.CenterHorizontally,
                verticalArrangement = Arrangement.spacedBy(18.dp),
            ) {
                BookTurningAnimation()
                Text(
                    "正在准备默写词条…",
                    color = MutedInk,
                    style = MaterialTheme.typography.titleMedium,
                )
                Text(
                    "正在生成可打印的 A4 默写页",
                    color = MutedInk,
                    style = MaterialTheme.typography.bodySmall,
                )
            }
        }
    }
}

@Composable
private fun BookTurningAnimation() {
    val transition = rememberInfiniteTransition(label = "dictationLoading")
    val progress by transition.animateFloat(
        initialValue = 0f,
        targetValue = 1f,
        animationSpec = infiniteRepeatable(
            animation = tween(durationMillis = DICTATION_BOOK_PAGE_TURN_MS, easing = LinearEasing),
            repeatMode = RepeatMode.Restart,
        ),
        label = "pageTurnProgress",
    )
    Box(
        modifier = Modifier.size(96.dp),
        contentAlignment = Alignment.Center,
    ) {
        Canvas(modifier = Modifier.fillMaxSize()) {
            val frame = dictationBookFrame(progress)
            val inset = size.minDimension * 0.06f
            val left = inset
            val right = size.width - inset
            val top = inset
            val bottom = size.height - inset
            val height = bottom - top
            val spine = (left + right) / 2f
            val half = (right - left) / 2f
            val edgeX = spine + half * frame.edgeOffset
            val lift = height * frame.liftFraction
            val pageColor = Color(0xFFFCFEFD)
            val pageBack = Color(0xFFEAF5F1)
            val edgeColor = Color(0xFF7FA69B)
            val inkColor = Color(0xFFB3CBC4)
            val shadowColor = Color(0x3345635B)
            val padding = size.minDimension * 0.12f

            drawRect(
                color = pageColor,
                topLeft = Offset(left, top),
                size = androidx.compose.ui.geometry.Size(spine - left, height),
            )
            drawRect(
                color = pageColor,
                topLeft = Offset(spine, top),
                size = androidx.compose.ui.geometry.Size(right - spine, height),
            )
            repeat(4) { i ->
                val y = top + height * (0.22f + i * 0.18f)
                drawLine(color = inkColor, start = Offset(left + padding, y), end = Offset(spine - padding, y), strokeWidth = 2f)
                drawLine(color = inkColor, start = Offset(spine + padding, y), end = Offset(right - padding, y), strokeWidth = 2f)
            }

            val path = Path().apply {
                moveTo(spine, top)
                lineTo(edgeX, top + lift)
                lineTo(edgeX, bottom - lift)
                lineTo(spine, bottom)
                close()
            }
            if (kotlin.math.abs(edgeX - spine) > 0.5f) {
                val shadowOffset = if (edgeX >= spine) 3f else -3f
                val shadow = Path().apply {
                    moveTo(spine, top + 2f)
                    lineTo(edgeX + shadowOffset, top + lift + 4f)
                    lineTo(edgeX + shadowOffset, bottom - lift + 4f)
                    lineTo(spine, bottom - 2f)
                    close()
                }
                drawPath(path = shadow, color = shadowColor)
            }
            drawPath(path = path, color = if (frame.edgeOffset >= 0f) pageColor else pageBack)
            drawPath(path = path, color = edgeColor, style = Stroke(width = 1.8f))

            val direction = if (edgeX >= spine) 1f else -1f
            val visibleWidth = kotlin.math.abs(edgeX - spine)
            if (visibleWidth > padding * 1.5f) {
                val lineStart = spine + direction * padding
                val lineEnd = edgeX - direction * padding
                repeat(3) { i ->
                    val ratio = 0.30f + i * 0.20f
                    val y = top + height * ratio
                    drawLine(
                        color = inkColor,
                        start = Offset(lineStart, y),
                        end = Offset(lineEnd, y + lift * (ratio - 0.5f)),
                        strokeWidth = 2f,
                    )
                }
            }
            drawLine(color = BrandTeal, start = Offset(spine, top), end = Offset(spine, bottom), strokeWidth = 2.4f)
        }
    }
}

@Composable
private fun DictationScreen(
    state: MainUiState,
    onToggleSelection: (String) -> Unit,
    onSetSelection: (Collection<String>, Boolean) -> Unit,
    onSetGroup: (String, Boolean) -> Unit,
    onSetManualMode: (Boolean) -> Unit,
    onSelectRangeToHere: (String, String) -> Unit,
    onEndRange: (String?) -> Unit,
    onSetScrollPosition: (String, Float) -> Unit,
    onSaveDraft: () -> Unit,
    onClearDraft: () -> Unit,
    onConfigChange: (Int, Boolean, Set<DictationFormat>, Int, Set<DictationMissingField>, Boolean, Boolean, Boolean, String) -> Unit,
    onBuild: (DictationDocumentOptions, Int, String, Boolean, Boolean, String) -> Unit,
) {
    val registerPetTarget = LocalRegisterPetTarget.current
    var formats by remember { mutableStateOf(setOf(DictationFormat.DOCX, DictationFormat.PDF)) }
    var fontSizeText by remember { mutableStateOf("12") }
    var missingFields by remember { mutableStateOf(setOf(DictationMissingField.WORD)) }
    var showInitial by remember { mutableStateOf(false) }
    var includeExamples by remember { mutableStateOf(false) }
    var includeExampleChinese by remember { mutableStateOf(false) }
    var customExample by remember { mutableStateOf("") }
    var includeEvaluated by remember { mutableStateOf(false) }
    var countText by remember { mutableStateOf("10") }
    var groupNavigation by remember(state.dictationManualMode, state.dictationScopeGroup, state.dictationOpenGroup) {
        mutableStateOf(
            DictationGroupNavigation(
                manual = state.dictationManualMode,
                scopeGroup = state.dictationScopeGroup,
                openGroup = state.dictationOpenGroup,
            ),
        )
    }
    var countError by remember { mutableStateOf(false) }
    var confirmationRequested by remember { mutableStateOf<Int?>(null) }
    var configSyncReady by remember { mutableStateOf(false) }
    var suppressConfigSync by remember { mutableStateOf(false) }

    // Hydrate local Compose controls exactly once after the ViewModel has
    // restored the persisted draft. Subsequent edits stay presentation-local
    // until the effect below mirrors them into the ViewModel state.
    LaunchedEffect(state.dictationDraftRestored, state.dictationDraftRestoreGeneration) {
        if (state.dictationDraftRestored) {
            suppressConfigSync = true
            formats = state.dictationFormats
            fontSizeText = state.dictationFontSizePt.toString()
            missingFields = state.dictationMissingFields
            showInitial = state.dictationShowInitial
            includeExamples = state.dictationIncludeExamples
            includeExampleChinese = state.dictationIncludeExampleChinese
            customExample = state.dictationCustomExample
            includeEvaluated = state.dictationIncludeEvaluated
            countText = state.dictationCount.toString()
            suppressConfigSync = false
        }
        configSyncReady = true
    }
    LaunchedEffect(formats, fontSizeText, missingFields, showInitial, includeExamples,
        includeExampleChinese, customExample, includeEvaluated, countText) {
        if (configSyncReady && !suppressConfigSync) {
            onConfigChange(
                countText.toIntOrNull() ?: 1,
                includeEvaluated,
                formats,
                fontSizeText.toIntOrNull() ?: 12,
                missingFields,
                showInitial,
                includeExamples,
                includeExampleChinese,
                customExample,
            )
        }
    }

    fun saveDraft() {
        onConfigChange(
            countText.toIntOrNull() ?: 1,
            includeEvaluated,
            formats,
            fontSizeText.toIntOrNull() ?: 12,
            missingFields,
            showInitial,
            includeExamples,
            includeExampleChinese,
            customExample,
        )
        onSaveDraft()
    }

    val manual = groupNavigation.manual
    val dictationScope = groupNavigation.scopeGroup
    val dictationGroup = groupNavigation.openGroup
    val candidateEntries = state.dictationEntries.filter { entry ->
        includeEvaluated || entry.tags.none { it.equals("evaluated", ignoreCase = true) }
    }
    val selectedCandidateIds = state.dictationSelectedIds.intersect(candidateEntries.mapTo(mutableSetOf()) { it.id })
    val selectedCount = selectedCandidateIds.size
    val scopeGroupLabel = dictationGroupSummaries(candidateEntries)
        .firstOrNull { it.key == dictationScope }?.label ?: dictationScope

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
        val buildGroup = if (manual) "all" else dictationScope
        onBuild(
            DictationDocumentOptions(
                formats = formats,
                fontSizePt = fontSizeText.toIntOrNull()?.coerceIn(8, 24) ?: 12,
                missingFields = missingFields,
                showInitial = showInitial,
                includeExamples = includeExamples,
                includeExampleChinese = includeExampleChinese,
            ),
            count,
            buildGroup,
            includeEvaluated,
            manual,
            customExample,
        )
    }

    LazyColumn(
        modifier = Modifier
            .fillMaxSize()
            .onPreviewKeyEvent { event ->
                if (event.type == KeyEventType.KeyDown &&
                    event.key == Key.S &&
                    (event.isCtrlPressed || event.isMetaPressed)
                ) {
                    saveDraft()
                    true
                } else false
            },
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
                includeExampleChinese = includeExampleChinese,
                onIncludeExampleChineseChange = { includeExampleChinese = it },
                customExample = customExample,
                onCustomExampleChange = { customExample = it },
                includeEvaluated = includeEvaluated,
                onIncludeEvaluatedChange = { includeEvaluated = it },
                countText = countText,
                onCountChange = { countText = it.filter(Char::isDigit); countError = false },
                countError = countError,
                manual = manual,
                onManualChange = {
                    groupNavigation = setDictationGroupMode(groupNavigation, it)
                    onSetManualMode(it)
                },
                preparing = state.dictationPreparing,
                onSubmit = ::submit,
            )
        }
        item {
            Surface(
                modifier = Modifier
                    .fillMaxWidth()
                    .petTarget(registerPetTarget, "dictation-selection", PetTargetKind.SURFACE),
                color = MaterialTheme.colorScheme.surface,
                shape = RoundedCornerShape(8.dp),
                border = CardDefaults.outlinedCardBorder(),
            ) {
                Column(modifier = Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text(
                            if (manual) "手选词条" else "随机词书范围",
                            modifier = Modifier.weight(1f),
                            style = MaterialTheme.typography.titleMedium,
                            color = Ink,
                        )
                        Text(
                            if (manual) "$selectedCount / ${countText.toIntOrNull() ?: 0}" else "随机范围：$scopeGroupLabel",
                            style = MaterialTheme.typography.labelLarge,
                            color = BrandTeal,
                        )
                    }
                    Text(
                        if (manual) {
                            "仅使用勾选的词条；数量不足时会再次确认。"
                        } else {
                            "点击词书分组打开内容并设置随机范围；取样时无重复。"
                        },
                        style = MaterialTheme.typography.bodySmall,
                        color = MutedInk,
                    )
                    val groups = remember(candidateEntries) { dictationGroupSummaries(candidateEntries) }
                    val activeGroup = dictationGroup
                    if (activeGroup != null) {
                        val activeLabel = remember(candidateEntries, activeGroup) {
                            dictationGroupSummaries(candidateEntries)
                                .firstOrNull { it.key == activeGroup }?.label ?: activeGroup
                        }
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            TextButton(
                                onClick = {
                                    groupNavigation = closeDictationGroup(groupNavigation)
                                    onSetGroup(activeGroup, false)
                                },
                            ) { Text("← 返回词书") }
                            Spacer(Modifier.width(8.dp))
                            Text(
                                activeLabel,
                                modifier = Modifier.weight(1f),
                                style = MaterialTheme.typography.labelLarge,
                                color = Ink,
                            )
                            if (!manual) {
                                Button(
                                    onClick = {
                                        groupNavigation = setDictationGroupMode(groupNavigation, manual = true)
                                        onSetManualMode(true)
                                    },
                                ) { Text("从该词书手选") }
                            }
                        }
                        if (!manual) {
                            Text(
                                "当前为随机候选范围；可跨分组勾选词条，取样时无重复。",
                                style = MaterialTheme.typography.bodySmall,
                                color = MutedInk,
                            )
                        }
                        Spacer(Modifier.height(4.dp))
                        key(activeGroup, manual) {
                            DictationSelectionTable(
                                entries = dictationEntriesInGroup(candidateEntries, activeGroup).sortedBy { it.id },
                                selectedIds = if (manual) selectedCandidateIds else (state.dictationRandomCandidateIds ?: emptySet())
                                    .map(::normalizeWordId)
                                    .toSet()
                                    .intersect(candidateEntries.mapTo(mutableSetOf()) { normalizeWordId(it.id) }),
                                selectionEnabled = true,
                                anchorId = state.dictationGroupDrafts[activeGroup]?.anchorId,
                                endpointId = state.dictationGroupDrafts[activeGroup]?.endpointId,
                                scrollPosition = state.dictationGroupDrafts[activeGroup]?.scrollPosition ?: 0f,
                                restoreScroll = state.dictationDraftRestored,
                                onToggleSelection = onToggleSelection,
                                onSetSelection = onSetSelection,
                                onSelectRangeToHere = { onSelectRangeToHere(activeGroup, it) },
                                onScrollPositionChange = { onSetScrollPosition(activeGroup, it) },
                            )
                        }
                    } else {
                        Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                            groups.forEach { group ->
                                VocabularyGroupCard(
                                    group = group,
                                    selected = !manual && group.key == dictationScope,
                                    onClick = {
                                        groupNavigation = openDictationGroup(groupNavigation, group.key)
                                        onSetGroup(group.key, true)
                                    },
                                    selectedCount = state.dictationGroupDrafts[group.key]?.selectedIds?.size ?: 0,
                                    unavailableCount = if (includeEvaluated) 0 else {
                                        val groupSelected = state.dictationGroupDrafts[group.key]?.selectedIds.orEmpty()
                                        val allGroupIds = dictationEntriesInGroup(state.dictationEntries, group.key).mapTo(mutableSetOf()) { it.id }
                                        val availableGroupIds = dictationEntriesInGroup(candidateEntries, group.key).mapTo(mutableSetOf()) { it.id }
                                        (groupSelected intersect allGroupIds subtract availableGroupIds).size
                                    },
                                )
                            }
                        }
                    }
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        TextButton(onClick = ::saveDraft) { Text("保存选择") }
                        TextButton(onClick = onClearDraft) { Text("清空本次选择") }
                        if (state.dictationGroupDrafts[dictationGroup ?: dictationScope]?.anchorId != null) {
                            TextButton(onClick = { onEndRange(dictationGroup ?: dictationScope) }) { Text("结束范围选择") }
                        }
                    }
                    state.dictationSyncMessage?.let { message ->
                        Text(
                            message,
                            style = MaterialTheme.typography.bodySmall,
                            color = if (state.dictationSyncStatus == com.lexitrack.learning.application.DictationDraftSyncStatus.CONFLICT) {
                                BusinessRed
                            } else {
                                MutedInk
                            },
                        )
                    }
                    if (candidateEntries.isEmpty()) {
                        Text("当前筛选没有可用词条。", style = MaterialTheme.typography.bodyMedium, color = BusinessAmber)
                    }
                }
            }
        }
    }

    confirmationRequested?.let { requestedCount ->
        PetAlertDialog(
            petId = "dictation-selection-confirmation",
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
                                includeExampleChinese = includeExampleChinese,
                            ),
                            count,
                            "all",
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
private fun DictationSelectionTable(
    entries: List<VocabularyEntry>,
    selectedIds: Set<String>,
    selectionEnabled: Boolean = true,
    anchorId: String? = null,
    endpointId: String? = null,
    scrollPosition: Float = 0f,
    restoreScroll: Boolean = false,
    onToggleSelection: (String) -> Unit,
    onSetSelection: (Collection<String>, Boolean) -> Unit,
    onSelectRangeToHere: (String) -> Unit = {},
    onScrollPositionChange: (Float) -> Unit = {},
) {
    val rows = remember(entries) { entries.map(VocabularyEntry::toDictationSelectionRow) }
    val tableScrollState = rememberScrollState()
    val listState = rememberLazyListState(
        initialFirstVisibleItemIndex = remember(entries, restoreScroll) {
            ((scrollPosition.coerceIn(0f, 1f)) * (rows.size - 1).coerceAtLeast(0)).roundToInt()
        },
    )
    LaunchedEffect(listState, rows.size) {
        snapshotFlow {
            val maxIndex = (rows.size - 1).coerceAtLeast(0)
            if (maxIndex == 0) 0f else {
                val index = listState.firstVisibleItemIndex.coerceIn(0, maxIndex)
                (index.toFloat() / maxIndex).coerceIn(0f, 1f)
            }
        }
            .distinctUntilChanged()
            // The initial emission reflects restored state, not a user edit.
            .drop(1)
            .collect(onScrollPositionChange)
    }
    val rowBounds = remember(entries) { mutableStateOf<Map<String, Rect>>(emptyMap()) }
    val containerTop = remember { mutableStateOf(0f) }
    Box(
        modifier = Modifier
            .fillMaxWidth()
            .onGloballyPositioned { containerTop.value = it.boundsInWindow().top }
            .pointerInput(rows, selectedIds, selectionEnabled) {
                if (!selectionEnabled) return@pointerInput
                awaitEachGesture {
                    val down = awaitFirstDown(requireUnconsumed = false)
                    // Do NOT consume the down so a simple tap still reaches the
                    // row's toggleable; only a drag past the slop takes over.
                    val drag = awaitTouchSlopOrCancellation(down.id) { change, _ ->
                        val windowY = containerTop.value + change.position.y
                        val anchor = rowBounds.value.entries
                            .firstOrNull { windowY in it.value.top..it.value.bottom }?.key
                        if (anchor != null) {
                            onSetSelection(listOf(anchor), anchor !in selectedIds)
                        }
                        change.consume()
                    }
                    if (drag == null) return@awaitEachGesture
                    var anchorId: String? = null
                    val windowY0 = containerTop.value + drag.position.y
                    anchorId = rowBounds.value.entries
                        .firstOrNull { windowY0 in it.value.top..it.value.bottom }?.key
                    if (anchorId != null) onSetSelection(listOf(anchorId), anchorId !in selectedIds)
                    while (true) {
                        val event = awaitPointerEvent()
                        val change = event.changes.firstOrNull { it.id == drag.id } ?: break
                        if (!change.pressed) break
                        val windowY = containerTop.value + change.position.y
                        val hits = rowBounds.value.entries
                            .filter { windowY in it.value.top..it.value.bottom }
                            .map { it.key }
                        if (hits.isNotEmpty()) onSetSelection(hits, anchorId?.let { it !in selectedIds } ?: true)
                        change.consume()
                    }
                }
            },
    ) {
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .horizontalScroll(tableScrollState),
        ) {
            Column(modifier = Modifier.width(DictationTableWidth)) {
                DictationSelectionTableHeader()
                HorizontalDivider()
                LazyColumn(
                    modifier = Modifier.fillMaxWidth().heightIn(max = 330.dp),
                    state = listState,
                ) {
                    items(rows, key = { it.id }) { row ->
                        DictationSelectionTableRow(
                            row = row,
                            selected = normalizeWordId(row.id) in selectedIds.map(::normalizeWordId).toSet(),
                            selectionEnabled = selectionEnabled,
                            onToggleSelection = { onToggleSelection(row.id) },
                            anchor = anchorId,
                            endpoint = endpointId,
                            onSelectRangeToHere = { onSelectRangeToHere(row.id) },
                            onBounds = { id, rect ->
                                rowBounds.value = if (rect == null) {
                                    rowBounds.value - id
                                } else {
                                    rowBounds.value + (id to rect)
                                }
                            },
                        )
                        HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
                    }
                }
            }
        }
    }
}

@Composable
private fun DictationSelectionTableHeader() {
    Row(
        modifier = Modifier
            .width(DictationTableWidth)
            .background(MaterialTheme.colorScheme.surfaceVariant)
            .padding(vertical = 10.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        DictationTableText("单词", DictationWordColumnWidth, FontWeight.SemiBold)
        DictationTableText("中文释义", DictationMeaningColumnWidth, FontWeight.SemiBold)
        DictationTableText("标签", DictationTagsColumnWidth, FontWeight.SemiBold)
        DictationTableText("考察状态", DictationStatusColumnWidth, FontWeight.SemiBold, TextAlign.Center)
        DictationTableText("选择", DictationSelectionColumnWidth, FontWeight.SemiBold, TextAlign.Center)
    }
}

@Composable
private fun DictationSelectionTableRow(
    row: DictationSelectionRow,
    selected: Boolean,
    selectionEnabled: Boolean,
    onToggleSelection: () -> Unit,
    onBounds: (String, Rect?) -> Unit,
    anchor: String? = null,
    endpoint: String? = null,
    onSelectRangeToHere: () -> Unit = {},
) {
    val registerPetTarget = LocalRegisterPetTarget.current
    DisposableEffect(row.id) {
        onDispose { onBounds(row.id, null) }
    }
    Column(modifier = Modifier.width(DictationTableWidth)) {
        if (anchor != null) {
            // The cyan guide is deliberately present only while a valid
            // anchor exists; it remains available for off-screen rows as the
            // full LazyColumn is the source of truth.
            Row(
                modifier = Modifier.fillMaxWidth().height(26.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                HorizontalDivider(
                    modifier = Modifier.weight(1f),
                    color = if (endpoint?.let(::normalizeWordId) == normalizeWordId(row.id)) BrandTeal else BrandTeal.copy(alpha = 0.35f),
                    thickness = 2.dp,
                )
                TextButton(
                    onClick = onSelectRangeToHere,
                    modifier = Modifier.height(28.dp),
                ) { Text("→ 选取到这里", color = BrandTeal, style = MaterialTheme.typography.labelSmall) }
            }
        }
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .toggleable(
                    value = selected,
                    enabled = selectionEnabled,
                    role = Role.Checkbox,
                    onValueChange = { onToggleSelection() },
                )
                .onGloballyPositioned { onBounds(row.id, it.boundsInWindow()) }
                .padding(vertical = 8.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            DictationTableText(row.word, DictationWordColumnWidth, FontWeight.Medium)
            DictationTableText(row.meaning, DictationMeaningColumnWidth)
            DictationTableText(row.tagsText, DictationTagsColumnWidth, color = BrandTeal)
            DictationTableText(
                row.evaluationStatus,
                DictationStatusColumnWidth,
                color = if (row.isEvaluated) Color.Black else BusinessRed,
                textAlign = TextAlign.Center,
            )
            Box(modifier = Modifier.width(DictationSelectionColumnWidth), contentAlignment = Alignment.Center) {
                Checkbox(
                    checked = selected,
                    onCheckedChange = null,
                    enabled = selectionEnabled,
                    modifier = Modifier
                        .size(48.dp)
                        .scale(1.25f)
                        .petTarget(registerPetTarget, "dictation-select-${row.id}", PetTargetKind.CONTROL),
                )
            }
        }
    }
}

@Composable
private fun DictationTableText(
    text: String,
    width: androidx.compose.ui.unit.Dp,
    fontWeight: FontWeight? = null,
    textAlign: TextAlign = TextAlign.Start,
    color: Color = Ink,
) {
    Text(
        text = text,
        modifier = Modifier.width(width).padding(horizontal = 8.dp),
        style = MaterialTheme.typography.bodySmall,
        color = color,
        fontWeight = fontWeight,
        textAlign = textAlign,
    )
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
    includeExampleChinese: Boolean,
    onIncludeExampleChineseChange: (Boolean) -> Unit,
    customExample: String,
    onCustomExampleChange: (String) -> Unit,
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
    val registerPetTarget = LocalRegisterPetTarget.current
    Surface(
        modifier = Modifier
            .fillMaxWidth()
            .petTarget(registerPetTarget, "dictation-options", PetTargetKind.SURFACE),
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
                    modifier = Modifier
                        .width(92.dp)
                        .petTarget(registerPetTarget, "dictation-font-size", PetTargetKind.CONTROL),
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
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text("默写数量", modifier = Modifier.weight(1f), style = MaterialTheme.typography.labelLarge, color = MutedInk)
                OutlinedTextField(
                    value = countText,
                    onValueChange = onCountChange,
                    modifier = Modifier
                        .width(120.dp)
                        .petTarget(registerPetTarget, "dictation-count", PetTargetKind.CONTROL),
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
                Switch(
                    checked = includeEvaluated,
                    onCheckedChange = onIncludeEvaluatedChange,
                    modifier = Modifier.petTarget(registerPetTarget, "dictation-evaluated", PetTargetKind.CONTROL),
                )
            }
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text("显示单词首字母", modifier = Modifier.weight(1f), style = MaterialTheme.typography.labelLarge, color = MutedInk)
                Switch(
                    checked = showInitial,
                    onCheckedChange = onShowInitialChange,
                    modifier = Modifier.petTarget(registerPetTarget, "dictation-initial", PetTargetKind.CONTROL),
                )
            }
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text("添加例句", modifier = Modifier.weight(1f), style = MaterialTheme.typography.labelLarge, color = MutedInk)
                Switch(
                    checked = includeExamples,
                    onCheckedChange = onIncludeExamplesChange,
                    modifier = Modifier.petTarget(registerPetTarget, "dictation-examples", PetTargetKind.CONTROL),
                )
            }
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text("例句含中文释义", modifier = Modifier.weight(1f), style = MaterialTheme.typography.labelLarge, color = MutedInk)
                Switch(
                    checked = includeExampleChinese,
                    onCheckedChange = onIncludeExampleChineseChange,
                    modifier = Modifier.petTarget(registerPetTarget, "dictation-example-chinese", PetTargetKind.CONTROL),
                )
            }
            if (includeExamples) {
                OutlinedTextField(
                    value = customExample,
                    onValueChange = onCustomExampleChange,
                    modifier = Modifier
                        .fillMaxWidth()
                        .petTarget(registerPetTarget, "dictation-custom-example", PetTargetKind.CONTROL),
                    label = { Text("自填例句（可选，应用于本次所有词条）") },
                    minLines = 2,
                )
            }
            Button(
                onClick = onSubmit,
                enabled = !preparing && formats.isNotEmpty() && missingFields.isNotEmpty() &&
                    fontSizeText.toIntOrNull()?.let { it in 8..24 } == true,
                modifier = Modifier
                    .fillMaxWidth()
                    .heightIn(min = 52.dp)
                    .petTarget(registerPetTarget, "dictation-generate", PetTargetKind.CONTROL),
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
    val registerPetTarget = LocalRegisterPetTarget.current
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
                modifier = Modifier
                    .padding(end = 6.dp)
                    .petTarget(
                        registerPetTarget,
                        "choice-${title.hashCode()}-${label.hashCode()}",
                        PetTargetKind.CONTROL,
                    ),
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
    val lines = remember(document) { dictationPreviewLines(document) }
    val linesPerPage = (842f / (document.options.fontSizePt * 1.9f)).toInt().coerceIn(12, 42)
    val pages = lines.chunked(linesPerPage).ifEmpty { listOf(emptyList()) }
    PetAlertDialog(
        petId = "dictation-preview",
        onDismissRequest = onDismiss,
        title = { Text("默写预览 · A4") },
        text = {
            val registerPetTarget = LocalRegisterPetTarget.current
            Column(
                modifier = Modifier.fillMaxWidth().heightIn(max = 600.dp).verticalScroll(rememberScrollState()),
                verticalArrangement = Arrangement.spacedBy(12.dp),
            ) {
                Text("${document.rows.size} 个词条 · ${document.options.fontSizePt} pt · ${pages.size} 页", color = MutedInk)
                pages.forEachIndexed { pageIndex, pageLines ->
                    Surface(
                        modifier = Modifier
                            .fillMaxWidth()
                            .aspectRatio(210f / 297f)
                            .petTarget(
                                registerPetTarget,
                                "dictation-preview-page-$pageIndex",
                                PetTargetKind.SURFACE,
                            ),
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
                Text(if (preparing) "正在准备文件" else "下载文档")
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
    PetAlertDialog(
        petId = "dictation-mark",
        onDismissRequest = onDismiss,
        title = { Text("标记默写词条") },
        text = {
            val registerPetTarget = LocalRegisterPetTarget.current
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text("是否将本次导出的词条标记为 evaluated？")
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Checkbox(
                        checked = dontAskAgain,
                        onCheckedChange = { dontAskAgain = it },
                        modifier = Modifier.petTarget(registerPetTarget, "dictation-mark-dont-ask", PetTargetKind.CONTROL),
                    )
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
    onSelectGroup: (String?) -> Unit,
) {
    val registerPetTarget = LocalRegisterPetTarget.current
    val browsingGroups = state.libraryGroup == null && state.searchQuery.isEmpty()
    val activeGroupLabel = state.libraryGroups.firstOrNull { it.key == state.libraryGroup }?.label
    Column(modifier = Modifier.fillMaxSize().padding(horizontal = 20.dp)) {
        Spacer(Modifier.height(20.dp))
        if (state.libraryGroup != null) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                TextButton(onClick = { onSelectGroup(null) }) { Text("← 返回词书") }
                Spacer(Modifier.width(8.dp))
                Text(
                    activeGroupLabel ?: "词库",
                    style = MaterialTheme.typography.headlineSmall,
                    color = Ink,
                )
            }
        } else {
            val total = state.libraryGroups.firstOrNull { it.key == "all" }?.count ?: 0
            PageHeader("词库", "$total 条词条 · 先选择词书分组")
        }
        Spacer(Modifier.height(14.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(10.dp), verticalAlignment = Alignment.CenterVertically) {
            OutlinedTextField(
                value = state.searchQuery,
                onValueChange = onQueryChange,
                modifier = Modifier
                    .weight(1f)
                    .petTarget(registerPetTarget, "library-search", PetTargetKind.CONTROL),
                singleLine = true,
                leadingIcon = { Icon(Icons.Outlined.Search, contentDescription = null) },
                placeholder = { Text("搜索单词、释义或标签") },
            )
            Button(
                onClick = onChooseCsv,
                enabled = !state.importInProgress,
                modifier = Modifier
                    .heightIn(min = 56.dp)
                    .petTarget(registerPetTarget, "library-import", PetTargetKind.CONTROL),
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
                modifier = Modifier
                    .heightIn(min = 56.dp)
                    .petTarget(registerPetTarget, "library-labels", PetTargetKind.CONTROL),
            ) { Text("标签 (${state.selectedVocabularyIds.size})") }
        }
        Text(
            "CSV 的 level 支持 CET4、CET6、custom（多个用 | 分隔），tags 也用 | 分隔；点击分组进入该组，可批量修改。",
            style = MaterialTheme.typography.labelMedium,
            color = MutedInk,
        )
        Spacer(Modifier.height(12.dp))
        if (browsingGroups) {
            LazyColumn(
                modifier = Modifier.fillMaxSize(),
                contentPadding = PaddingValues(bottom = 20.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                items(state.libraryGroups, key = { it.key }) { group ->
                    VocabularyGroupCard(group = group, onClick = { onSelectGroup(group.key) })
                }
            }
        } else if (state.searchResults.isEmpty()) {
            val emptyMessage = if (state.libraryGroup != null) "该分组暂无词条" else "可调整搜索条件或导入 CSV 词库"
            EmptyState(Icons.AutoMirrored.Outlined.List, "没有匹配词条", emptyMessage)
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
private fun VocabularyGroupCard(
    group: LibraryGroup,
    selected: Boolean = false,
    selectedCount: Int = 0,
    unavailableCount: Int = 0,
    onClick: () -> Unit,
) {
    Surface(
        modifier = Modifier.fillMaxWidth(),
        color = if (selected) MaterialTheme.colorScheme.primaryContainer else MaterialTheme.colorScheme.surface,
        shape = RoundedCornerShape(8.dp),
        border = if (selected) BorderStroke(2.dp, MaterialTheme.colorScheme.primary) else CardDefaults.outlinedCardBorder(),
        onClick = onClick,
    ) {
        Row(
            modifier = Modifier.padding(16.dp, 14.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(group.label, modifier = Modifier.weight(1f), style = MaterialTheme.typography.titleMedium, color = Ink)
            Text(
                "${group.count} 词" +
                    (if (selected) " · 已选" else "") +
                    (if (selectedCount > 0) " · 已选 $selectedCount" else "") +
                    (if (unavailableCount > 0) " · 暂不可用 $unavailableCount" else ""),
                style = MaterialTheme.typography.labelMedium,
                color = MutedInk,
            )
        }
    }
}

@Composable
private fun VocabularyRow(entry: VocabularyEntry, selected: Boolean, onToggleSelection: () -> Unit) {
    val registerPetTarget = LocalRegisterPetTarget.current
    Surface(
        modifier = Modifier
            .fillMaxWidth()
            .petTarget(registerPetTarget, "word-${entry.id}", PetTargetKind.SURFACE),
        color = MaterialTheme.colorScheme.surface,
        shape = RoundedCornerShape(8.dp),
        border = CardDefaults.outlinedCardBorder(),
    ) {
        Column(modifier = Modifier.padding(15.dp), verticalArrangement = Arrangement.spacedBy(5.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Checkbox(
                    checked = selected,
                    onCheckedChange = { onToggleSelection() },
                    modifier = Modifier.petTarget(registerPetTarget, "word-select-${entry.id}", PetTargetKind.CONTROL),
                )
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
    PetAlertDialog(
        petId = "vocabulary-labels",
        onDismissRequest = onDismiss,
        title = { Text("添加或删除标签") },
        text = {
            val registerPetTarget = LocalRegisterPetTarget.current
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
                            modifier = Modifier
                                .padding(end = 6.dp)
                                .petTarget(registerPetTarget, "labels-add-$tag", PetTargetKind.CONTROL),
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
                            modifier = Modifier
                                .padding(end = 6.dp)
                                .petTarget(registerPetTarget, "labels-remove-$tag", PetTargetKind.CONTROL),
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
    val registerPetTarget = LocalRegisterPetTarget.current
    val density = LocalDensity.current
    val curveLeftInset = with(density) { 12.dp.toPx() }
    val curveRightInset = with(density) { 8.dp.toPx() }
    val curveTopInset = with(density) { 10.dp.toPx() }
    val curveBottomInset = with(density) { 12.dp.toPx() }
    Surface(
        modifier = Modifier
            .fillMaxWidth()
            .petTarget(registerPetTarget, "memory-curve-frame", PetTargetKind.SURFACE),
        color = MaterialTheme.colorScheme.surface,
        shape = RoundedCornerShape(8.dp),
        border = CardDefaults.outlinedCardBorder(),
    ) {
        Column(modifier = Modifier.padding(16.dp)) {
            Canvas(
                modifier = Modifier
                    .fillMaxWidth()
                    .height(210.dp)
                    .petTarget(
                        registerPetTarget,
                        "memory-curve",
                        PetTargetKind.CHART,
                    ) { bounds ->
                        val left = bounds.left + curveLeftInset
                        val right = bounds.right - curveRightInset
                        val top = bounds.top + curveTopInset
                        val bottom = bounds.bottom - curveBottomInset
                        (0..70).map { step ->
                            val day = step / 10f
                            val retention = exp(-day / 3f)
                            PetPoint(
                                left + (right - left) * (day / 7f),
                                bottom - (bottom - top) * retention,
                            )
                        }
                    },
            ) {
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
    val registerPetTarget = LocalRegisterPetTarget.current
    val formatter = DateTimeFormatter.ofPattern("M/d")
    val maximum = max(1, forecast.maxOfOrNull { it.count } ?: 1)
    Surface(
        modifier = Modifier
            .fillMaxWidth()
            .petTarget(registerPetTarget, "forecast-bars", PetTargetKind.CHART),
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
    val safeFontScale = sanitizeFontScale(fontScale)
    var reminderEnabledDraft by remember(reminderEnabled) { mutableStateOf(reminderEnabled) }
    val registerPetTarget = LocalRegisterPetTarget.current
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
            modifier = Modifier
                .fillMaxWidth()
                .petTarget(registerPetTarget, "settings-font", PetTargetKind.SURFACE),
            color = MaterialTheme.colorScheme.surface,
            shape = RoundedCornerShape(8.dp),
            border = CardDefaults.outlinedCardBorder(),
        ) {
            Column(modifier = Modifier.padding(18.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                Row(modifier = Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                    Text("界面字号", modifier = Modifier.weight(1f), style = MaterialTheme.typography.titleMedium)
                    Text("${(safeFontScale * 100).toInt()}%", style = MaterialTheme.typography.titleMedium, color = BrandTeal)
                }
                Slider(
                    value = safeFontScale,
                    onValueChange = { onFontScaleChange(sanitizeFontScale(it)) },
                    valueRange = MIN_FONT_SCALE..MAX_FONT_SCALE,
                    steps = 4,
                    modifier = Modifier.petTarget(registerPetTarget, "settings-font-slider", PetTargetKind.CONTROL),
                )
                Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                    Text("90%", style = MaterialTheme.typography.labelMedium, color = MutedInk)
                    Text("140%", style = MaterialTheme.typography.labelMedium, color = MutedInk)
                }
            }
        }
        Surface(
            modifier = Modifier
                .fillMaxWidth()
                .petTarget(registerPetTarget, "settings-mark", PetTargetKind.SURFACE),
            color = MaterialTheme.colorScheme.surface,
            shape = RoundedCornerShape(8.dp),
            border = CardDefaults.outlinedCardBorder(),
        ) {
            Column(modifier = Modifier.padding(18.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                Text("默写后的标记", style = MaterialTheme.typography.titleMedium, color = Ink)
                Text("控制导出成功后是否给本次词条添加 evaluated 标签。", style = MaterialTheme.typography.bodyMedium, color = MutedInk)
                Row(modifier = Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    FilterChip(selected = markMode == MarkMode.ALWAYS, onClick = { onMarkModeChange(MarkMode.ALWAYS) }, label = { Text("默认标记") }, modifier = Modifier.petTarget(registerPetTarget, "settings-mark-always", PetTargetKind.CONTROL))
                    FilterChip(selected = markMode == MarkMode.NEVER, onClick = { onMarkModeChange(MarkMode.NEVER) }, label = { Text("默认不标记") }, modifier = Modifier.petTarget(registerPetTarget, "settings-mark-never", PetTargetKind.CONTROL))
                    FilterChip(selected = markMode == MarkMode.ASK, onClick = { onMarkModeChange(MarkMode.ASK) }, label = { Text("每次询问") }, modifier = Modifier.petTarget(registerPetTarget, "settings-mark-ask", PetTargetKind.CONTROL))
                }
            }
        }
        Surface(
            modifier = Modifier
                .fillMaxWidth()
                .petTarget(registerPetTarget, "settings-order", PetTargetKind.SURFACE),
            color = MaterialTheme.colorScheme.surface,
            shape = RoundedCornerShape(8.dp),
            border = CardDefaults.outlinedCardBorder(),
        ) {
            Column(modifier = Modifier.padding(18.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                Text("学习顺序", style = MaterialTheme.typography.titleMedium, color = Ink)
                Text("默认随机，也可按字母顺序学习。", style = MaterialTheme.typography.bodyMedium, color = MutedInk)
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    FilterChip(selected = studyOrder == "random", onClick = { onStudyOrderChange("random") }, label = { Text("随机顺序") }, modifier = Modifier.petTarget(registerPetTarget, "settings-order-random", PetTargetKind.CONTROL))
                    FilterChip(selected = studyOrder == "alphabetical", onClick = { onStudyOrderChange("alphabetical") }, label = { Text("按字母排序") }, modifier = Modifier.petTarget(registerPetTarget, "settings-order-alphabetical", PetTargetKind.CONTROL))
                }
            }
        }
        Surface(
            modifier = Modifier
                .fillMaxWidth()
                .petTarget(registerPetTarget, "settings-review-batch", PetTargetKind.SURFACE),
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
                    modifier = Modifier.petTarget(registerPetTarget, "settings-review-slider", PetTargetKind.CONTROL),
                )
            }
        }
        Surface(
            modifier = Modifier
                .fillMaxWidth()
                .petTarget(registerPetTarget, "settings-preview", PetTargetKind.SURFACE),
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
            modifier = Modifier
                .fillMaxWidth()
                .petTarget(registerPetTarget, "settings-reminder", PetTargetKind.SURFACE),
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
                        modifier = Modifier.petTarget(registerPetTarget, "settings-reminder-switch", PetTargetKind.CONTROL),
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
                    modifier = Modifier
                        .fillMaxWidth()
                        .petTarget(registerPetTarget, "settings-reminder-interval", PetTargetKind.CONTROL),
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
                        modifier = Modifier.petTarget(registerPetTarget, "settings-reminder-save", PetTargetKind.CONTROL),
                    ) { Text("保存设置") }
                    TextButton(
                        onClick = onPreviewReminder,
                        modifier = Modifier.petTarget(registerPetTarget, "settings-reminder-preview", PetTargetKind.CONTROL),
                    ) { Text("立即预览") }
                }
            }
        }
        Surface(
            modifier = Modifier
                .fillMaxWidth()
                .petTarget(registerPetTarget, "settings-local-data", PetTargetKind.SURFACE),
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
    PetAlertDialog(
        petId = "import-report",
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
    PetAlertDialog(
        petId = "message",
        onDismissRequest = onDismiss,
        icon = { Icon(Icons.Outlined.ErrorOutline, contentDescription = null, tint = BusinessRed) },
        title = { Text("无法完成操作") },
        text = { Text(message) },
        confirmButton = { TextButton(onClick = onDismiss) { Text("关闭") } },
        shape = RoundedCornerShape(8.dp),
    )
}
