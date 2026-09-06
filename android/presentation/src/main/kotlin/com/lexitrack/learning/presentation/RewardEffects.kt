package com.lexitrack.learning.presentation

import android.view.View
import androidx.compose.foundation.Canvas
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.runtime.withFrameNanos
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Rect
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.input.pointer.PointerEvent
import androidx.compose.ui.input.pointer.PointerEventPass
import androidx.compose.ui.node.ModifierNodeElement
import androidx.compose.ui.node.PointerInputModifierNode
import androidx.compose.ui.platform.LocalView
import androidx.compose.ui.unit.IntSize
import androidx.compose.ui.zIndex
import com.lexitrack.learning.domain.PetPoint
import kotlinx.coroutines.isActive
import kotlin.math.PI
import kotlin.math.cos
import kotlin.math.hypot
import kotlin.math.max
import kotlin.math.sin
import kotlin.math.sqrt
import kotlin.math.roundToLong

/** Animation parameters are centralized because visual tuning will change later. */
internal object RewardFlightTuning {
    const val FRAME_MS = 16L
    const val SPIRAL_DURATION_MS = 180L
    const val SPIRAL_TURNS = 1.0f
    const val SPIRAL_RADIUS_START = 4.0f
    const val SPIRAL_RADIUS_END = 18.0f
    const val HOMING_INITIAL_SPEED = 180.0f
    const val HOMING_ACCELERATION = 2_400.0f
    const val HOMING_MAXIMUM_SPEED = 2_800.0f
    // Physical contact stays small; these values control the visible feedback
    // and are centralized because later releases will tune the presentation.
    const val ORB_RADIUS = 6.0f
    const val VISUAL_ORB_RADIUS = 16.0f
    const val VISUAL_ORB_GLOW_RADIUS = 34.0f
    const val VISUAL_ORB_HIGHLIGHT_RADIUS = 4.0f
    const val TRAIL_LIFETIME_MS = 180L
    const val TRAIL_MAXIMUM_POINTS = 20
    const val TRAIL_MINIMUM_STROKE_WIDTH = 5.0f
    const val TRAIL_MAXIMUM_STROKE_WIDTH = 12.0f
    const val TRAIL_STROKE_SPEED_FACTOR = 0.0025f
    const val TRAIL_GLOW_WIDTH_MULTIPLIER = 2.2f
    const val BURST_PARTICLE_COUNT = 18
    const val BURST_PARTICLE_RADIUS = 4.0f
    const val BURST_PARTICLE_GLOW_RADIUS = 10.0f
    const val BURST_DURATION_MS = 350L
    const val MAXIMUM_LIFETIME_MS = 2_500L
    const val MISSING_TARGET_TIMEOUT_MS = 500L
    const val MINIMUM_VERIFIED_CONCURRENT_FLIGHTS = 32
    const val BURST_MINIMUM_SPEED = 120.0f
    const val BURST_SPEED_STEP = 18.0f
}

enum class RewardEffectKind {
    STUDY,
    REVIEW,
}

data class RewardEffectOrigin(val x: Float, val y: Float) {
    init {
        require(x.isFinite() && y.isFinite()) { "Reward origin must be finite" }
    }

    internal fun toPetPoint() = PetPoint(x, y)
}

data class RewardEffectRequest(
    val kind: RewardEffectKind,
    val origin: RewardEffectOrigin,
)

internal const val RATING_POINTER_ORIGIN_FRESHNESS_MS = 1_500L

internal data class RatingPointerDown(
    val origin: RewardEffectOrigin,
    val capturedAtUptimeMs: Long,
)

internal fun resolveRatingOrigin(
    pointerDown: RatingPointerDown?,
    buttonBounds: Rect,
    nowUptimeMs: Long,
): RewardEffectOrigin {
    val pointerAge = pointerDown?.let { nowUptimeMs - it.capturedAtUptimeMs }
    if (pointerDown != null && pointerAge in 0L..RATING_POINTER_ORIGIN_FRESHNESS_MS) {
        return pointerDown.origin
    }
    return RewardEffectOrigin(
        x = (buttonBounds.left + buttonBounds.right) / 2f,
        y = (buttonBounds.top + buttonBounds.bottom) / 2f,
    )
}

internal enum class RewardFlightStage {
    SPIRAL,
    HOMING,
}

internal data class RewardTarget(
    val center: PetPoint,
    val halfSize: Float,
)

internal data class RewardTrailPoint(
    val position: PetPoint,
    val ageMs: Long,
)

internal data class RewardFlightSnapshot(
    val id: Long,
    val kind: RewardEffectKind,
    val position: PetPoint,
    val velocity: PetPoint,
    val stage: RewardFlightStage,
    val trail: List<RewardTrailPoint>,
)

internal data class RewardParticleSnapshot(
    val kind: RewardEffectKind,
    val position: PetPoint,
    val alpha: Float,
)

internal data class RewardEffectsSnapshot(
    val flights: List<RewardFlightSnapshot> = emptyList(),
    val particles: List<RewardParticleSnapshot> = emptyList(),
) {
    val active: Boolean get() = flights.isNotEmpty() || particles.isNotEmpty()
}

private data class MutableTrailPoint(
    val position: PetPoint,
    var ageMs: Long,
)

private data class MutableRewardFlight(
    val id: Long,
    val kind: RewardEffectKind,
    val origin: PetPoint,
    var position: PetPoint,
    var velocity: PetPoint = PetPoint(0f, 0f),
    var stage: RewardFlightStage = RewardFlightStage.SPIRAL,
    var spiralElapsedMs: Long = 0L,
    var lifetimeMs: Long = 0L,
    var missingTargetMs: Long = 0L,
    val trail: MutableList<MutableTrailPoint> = mutableListOf(MutableTrailPoint(origin, 0L)),
)

private data class MutableRewardBurst(
    val kind: RewardEffectKind,
    val origin: PetPoint,
    var ageMs: Long = 0L,
)

internal class RewardEffectsEngine {
    private val flights = mutableListOf<MutableRewardFlight>()
    private val bursts = mutableListOf<MutableRewardBurst>()
    private var nextId = 1L

    fun emit(request: RewardEffectRequest): Long {
        val id = nextId++
        val origin = request.origin.toPetPoint()
        flights += MutableRewardFlight(id = id, kind = request.kind, origin = origin, position = origin)
        return id
    }

    fun step(deltaMs: Long, target: RewardTarget?) {
        if (deltaMs <= 0L) return
        bursts.forEach { it.ageMs += deltaMs }
        bursts.removeAll { it.ageMs >= RewardFlightTuning.BURST_DURATION_MS }

        val iterator = flights.iterator()
        while (iterator.hasNext()) {
            val flight = iterator.next()
            flight.lifetimeMs += deltaMs
            flight.trail.forEach { it.ageMs += deltaMs }
            flight.trail.removeAll { it.ageMs > RewardFlightTuning.TRAIL_LIFETIME_MS }

            if (target == null) {
                flight.missingTargetMs += deltaMs
            } else {
                flight.missingTargetMs = 0L
            }
            if (
                flight.lifetimeMs >= RewardFlightTuning.MAXIMUM_LIFETIME_MS ||
                flight.missingTargetMs >= RewardFlightTuning.MISSING_TARGET_TIMEOUT_MS
            ) {
                iterator.remove()
                continue
            }

            var remainingMs = deltaMs
            if (flight.stage == RewardFlightStage.SPIRAL) {
                val spiralStep = minOf(
                    remainingMs,
                    RewardFlightTuning.SPIRAL_DURATION_MS - flight.spiralElapsedMs,
                )
                advanceSpiral(flight, spiralStep)
                remainingMs -= spiralStep
                if (flight.spiralElapsedMs >= RewardFlightTuning.SPIRAL_DURATION_MS) {
                    flight.stage = RewardFlightStage.HOMING
                    flight.velocity = target?.let {
                        direction(flight.position, it.center) * RewardFlightTuning.HOMING_INITIAL_SPEED
                    } ?: PetPoint(0f, 0f)
                }
            }

            if (flight.stage == RewardFlightStage.HOMING && remainingMs > 0L && target != null) {
                val contact = advanceHoming(flight, remainingMs, target)
                if (contact != null) {
                    bursts += MutableRewardBurst(flight.kind, contact)
                    iterator.remove()
                    continue
                }
            }
            addTrailPoint(flight)
        }
    }

    fun snapshot(): RewardEffectsSnapshot = RewardEffectsSnapshot(
        flights = flights.map { flight ->
            val speed = flight.velocity.length()
            RewardFlightSnapshot(
                id = flight.id,
                kind = flight.kind,
                position = flight.position,
                velocity = flight.velocity,
                stage = flight.stage,
                trail = visibleTrail(
                    flight.trail.map { RewardTrailPoint(it.position, it.ageMs) },
                    trailLengthForSpeed(speed),
                ),
            )
        },
        particles = bursts.flatMap(::burstParticles),
    )

    private fun advanceSpiral(flight: MutableRewardFlight, deltaMs: Long) {
        if (deltaMs <= 0L) return
        val previous = flight.position
        flight.spiralElapsedMs += deltaMs
        val progress = (
            flight.spiralElapsedMs.toFloat() / RewardFlightTuning.SPIRAL_DURATION_MS.toFloat()
            ).coerceIn(0f, 1f)
        val acceleratedProgress = progress * progress
        val angle = (2.0 * PI * RewardFlightTuning.SPIRAL_TURNS * acceleratedProgress).toFloat()
        val radius = lerp(
            RewardFlightTuning.SPIRAL_RADIUS_START,
            RewardFlightTuning.SPIRAL_RADIUS_END,
            progress,
        )
        flight.position = PetPoint(
            flight.origin.x + cos(angle) * radius,
            flight.origin.y + sin(angle) * radius,
        )
        val seconds = deltaMs / 1_000f
        flight.velocity = if (seconds > 0f) (flight.position - previous) / seconds else flight.velocity
    }

    private fun advanceHoming(
        flight: MutableRewardFlight,
        deltaMs: Long,
        target: RewardTarget,
    ): PetPoint? {
        val seconds = deltaMs / 1_000f
        val previous = flight.position
        val targetDirection = direction(previous, target.center)
        if (flight.velocity.length() <= 1e-4f) {
            flight.velocity = targetDirection * RewardFlightTuning.HOMING_INITIAL_SPEED
        }
        val accelerated = flight.velocity + targetDirection * (RewardFlightTuning.HOMING_ACCELERATION * seconds)
        flight.velocity = accelerated.capped(RewardFlightTuning.HOMING_MAXIMUM_SPEED)
        val next = previous + flight.velocity * seconds
        val contactRadius = target.halfSize.coerceAtLeast(0f) + RewardFlightTuning.ORB_RADIUS
        val contact = segmentCircleContact(previous, next, target.center, contactRadius)
        flight.position = contact ?: next
        return contact
    }

    private fun addTrailPoint(flight: MutableRewardFlight) {
        val last = flight.trail.lastOrNull()?.position
        if (last == flight.position) return
        flight.trail += MutableTrailPoint(flight.position, 0L)
        while (flight.trail.size > RewardFlightTuning.TRAIL_MAXIMUM_POINTS) {
            flight.trail.removeAt(0)
        }
    }
}

internal class RewardEffectsController(
    private val engine: RewardEffectsEngine = RewardEffectsEngine(),
) {
    var snapshot by mutableStateOf(engine.snapshot())
        private set

    fun emit(request: RewardEffectRequest) {
        engine.emit(request)
        snapshot = engine.snapshot()
    }

    fun step(deltaMs: Long, target: RewardTarget?) {
        engine.step(deltaMs, target)
        snapshot = engine.snapshot()
    }
}

internal val LocalRewardEffectsController = staticCompositionLocalOf { RewardEffectsController() }
internal val StudyRewardGold = Color(0xFFF4C542)

/**
 * Keep the visual layer in the pointer hit-test path without taking ownership
 * of the gesture.  A full-size sibling with a pointer-input modifier would
 * otherwise become the only hit target on Compose versions that stop at the
 * highest z-index sibling.  Sharing the hit-test result lets the underlying
 * rating buttons and navigation controls continue to receive their events.
 */
private fun Modifier.pointerTransparent(): Modifier = this.then(PointerTransparentElement)

private object PointerTransparentElement : ModifierNodeElement<PointerTransparentNode>() {
    override fun create(): PointerTransparentNode = PointerTransparentNode()

    override fun update(node: PointerTransparentNode) = Unit

    override fun equals(other: Any?): Boolean = other === this

    override fun hashCode(): Int = javaClass.hashCode()
}

private class PointerTransparentNode : Modifier.Node(), PointerInputModifierNode {
    override fun onPointerEvent(
        pointerEvent: PointerEvent,
        pass: PointerEventPass,
        bounds: IntSize,
    ) = Unit

    override fun onCancelPointerInput() = Unit

    override fun sharePointerInputWithSiblings(): Boolean = true
}

@Composable
internal fun RewardEffectsAnimator(
    controller: RewardEffectsController,
    coordinator: PetWindowCoordinator,
    petHalfSizePx: Float,
) {
    val hostView = LocalView.current
    val active = controller.snapshot.active
    LaunchedEffect(controller, coordinator, petHalfSizePx, active) {
        if (!active) return@LaunchedEffect
        var previousFrame = withFrameNanos { it }
        while (isActive && controller.snapshot.active) {
            val frame = withFrameNanos { it }
            if (hostView.isShown && hostView.windowVisibility == View.VISIBLE) {
                val elapsedMs = ((frame - previousFrame) / 1_000_000L)
                    .coerceIn(1L, RewardFlightTuning.FRAME_MS * 2)
                val target = coordinator.worldPosition()
                    ?.takeIf { coordinator.activeWindowId != null }
                    ?.let { RewardTarget(it, petHalfSizePx) }
                controller.step(elapsedMs, target)
            }
            previousFrame = frame
        }
    }
}

@Composable
internal fun RewardEffectsCanvas(
    windowOrigin: PetPoint,
    modifier: Modifier = Modifier,
) {
    val controller = LocalRewardEffectsController.current
    val snapshot = controller.snapshot
    Canvas(
        // This canvas is deliberately visual-only.  Explicitly sharing the
        // pointer hit-test keeps it from turning the whole page into a modal
        // animation while the reward flight is being rendered.
        modifier = modifier
            .pointerTransparent()
            .zIndex(21f),
    ) {
        snapshot.flights.forEach { flight ->
            val color = rewardColor(flight.kind)
            val trail = flight.trail
            val baseStrokeWidth = trailStrokeWidthForSpeed(flight.velocity.length())
            trail.zipWithNext().forEachIndexed { index, (from, to) ->
                val ageAlpha = 1f - to.ageMs.toFloat() / RewardFlightTuning.TRAIL_LIFETIME_MS.toFloat()
                val sequenceAlpha = (index + 1f) / max(1, trail.lastIndex).toFloat()
                val segmentAlpha = (ageAlpha * sequenceAlpha).coerceIn(0f, 1f)
                val taperedWidth = baseStrokeWidth * (0.55f + sequenceAlpha * 0.45f)
                drawLine(
                    color = color.copy(alpha = segmentAlpha * 0.24f),
                    start = from.position.toOffset(windowOrigin),
                    end = to.position.toOffset(windowOrigin),
                    strokeWidth = baseStrokeWidth * RewardFlightTuning.TRAIL_GLOW_WIDTH_MULTIPLIER,
                    cap = StrokeCap.Round,
                )
                drawLine(
                    color = color.copy(alpha = segmentAlpha * 0.88f),
                    start = from.position.toOffset(windowOrigin),
                    end = to.position.toOffset(windowOrigin),
                    strokeWidth = taperedWidth,
                    cap = StrokeCap.Round,
                )
            }
            val center = flight.position.toOffset(windowOrigin)
            val glowRadius = RewardFlightTuning.VISUAL_ORB_GLOW_RADIUS
            drawCircle(
                brush = Brush.radialGradient(
                    colors = listOf(
                        color.copy(alpha = 0.34f),
                        color.copy(alpha = 0.18f),
                        color.copy(alpha = 0.04f),
                        Color.Transparent,
                    ),
                    center = center,
                    radius = glowRadius,
                ),
                radius = glowRadius,
                center = center,
            )
            val auraRadius = RewardFlightTuning.VISUAL_ORB_RADIUS * 1.35f
            drawCircle(
                brush = Brush.radialGradient(
                    colors = listOf(
                        Color.White.copy(alpha = 0.32f),
                        color.copy(alpha = 0.42f),
                        color.copy(alpha = 0.1f),
                        Color.Transparent,
                    ),
                    center = center,
                    radius = auraRadius,
                ),
                radius = auraRadius,
                center = center,
            )
            val coreRadius = RewardFlightTuning.VISUAL_ORB_RADIUS
            drawCircle(
                brush = Brush.radialGradient(
                    colors = listOf(
                        Color.White.copy(alpha = 0.98f),
                        color.copy(alpha = 0.98f),
                        color.copy(alpha = 0.74f),
                    ),
                    center = Offset(
                        center.x - coreRadius * 0.32f,
                        center.y - coreRadius * 0.38f,
                    ),
                    radius = coreRadius * 1.55f,
                ),
                radius = coreRadius,
                center = center,
            )
            drawCircle(
                color = Color.White.copy(alpha = 0.9f),
                radius = RewardFlightTuning.VISUAL_ORB_HIGHLIGHT_RADIUS,
                center = Offset(
                    center.x - coreRadius * 0.35f,
                    center.y - coreRadius * 0.42f,
                ),
            )
        }
        snapshot.particles.forEach { particle ->
            val particleCenter = particle.position.toOffset(windowOrigin)
            drawCircle(
                brush = Brush.radialGradient(
                    colors = listOf(
                        rewardColor(particle.kind).copy(alpha = particle.alpha * 0.42f),
                        rewardColor(particle.kind).copy(alpha = particle.alpha * 0.12f),
                        Color.Transparent,
                    ),
                    center = particleCenter,
                    radius = RewardFlightTuning.BURST_PARTICLE_GLOW_RADIUS,
                ),
                radius = RewardFlightTuning.BURST_PARTICLE_GLOW_RADIUS,
                center = particleCenter,
            )
            drawCircle(
                color = rewardColor(particle.kind).copy(alpha = particle.alpha),
                radius = RewardFlightTuning.BURST_PARTICLE_RADIUS,
                center = particleCenter,
            )
            drawCircle(
                color = Color.White.copy(alpha = particle.alpha * 0.78f),
                radius = 1.4f,
                center = particleCenter,
            )
        }
    }
}

internal fun trailLengthForSpeed(speed: Float): Float = (speed * 0.04f).coerceIn(18f, 96f)

internal fun trailStrokeWidthForSpeed(speed: Float): Float {
    val boundedSpeed = if (speed.isFinite()) speed.coerceAtLeast(0f) else 0f
    return (
        RewardFlightTuning.TRAIL_MINIMUM_STROKE_WIDTH +
            boundedSpeed * RewardFlightTuning.TRAIL_STROKE_SPEED_FACTOR
        ).coerceIn(
            RewardFlightTuning.TRAIL_MINIMUM_STROKE_WIDTH,
            RewardFlightTuning.TRAIL_MAXIMUM_STROKE_WIDTH,
        )
}

internal fun visibleTrail(points: List<RewardTrailPoint>, maximumLength: Float): List<RewardTrailPoint> {
    require(maximumLength.isFinite() && maximumLength >= 0f) {
        "Visible trail length must be finite and non-negative"
    }
    if (points.size < 2) return points
    val kept = ArrayDeque<RewardTrailPoint>()
    kept.addFirst(points.last())
    var remaining = maximumLength
    for (index in points.lastIndex downTo 1) {
        val current = points[index]
        val previous = points[index - 1]
        val segmentLength = current.position.distanceTo(previous.position)
        if (segmentLength <= remaining) {
            kept.addFirst(previous)
            remaining -= segmentLength
            continue
        }
        if (segmentLength > 0f && remaining > 0f) {
            val fraction = remaining / segmentLength
            kept.addFirst(
                RewardTrailPoint(
                    position = current.position + (previous.position - current.position) * fraction,
                    ageMs = (
                        current.ageMs + (previous.ageMs - current.ageMs) * fraction
                        ).roundToLong(),
                ),
            )
        }
        break
    }
    return kept.toList()
}

private fun burstParticles(burst: MutableRewardBurst): List<RewardParticleSnapshot> {
    val progress = (burst.ageMs.toFloat() / RewardFlightTuning.BURST_DURATION_MS.toFloat()).coerceIn(0f, 1f)
    val seconds = burst.ageMs / 1_000f
    return List(RewardFlightTuning.BURST_PARTICLE_COUNT) { index ->
        val angle = (2.0 * PI * index / RewardFlightTuning.BURST_PARTICLE_COUNT).toFloat()
        val speed = RewardFlightTuning.BURST_MINIMUM_SPEED +
            (index % 5) * RewardFlightTuning.BURST_SPEED_STEP
        val drag = 1f - progress * 0.45f
        RewardParticleSnapshot(
            kind = burst.kind,
            position = PetPoint(
                burst.origin.x + cos(angle) * speed * seconds * drag,
                burst.origin.y + sin(angle) * speed * seconds * drag,
            ),
            alpha = (1f - progress) * (1f - progress),
        )
    }
}

private fun segmentCircleContact(
    start: PetPoint,
    end: PetPoint,
    center: PetPoint,
    radius: Float,
): PetPoint? {
    if (start.distanceTo(center) <= radius) return start
    val delta = end - start
    val offset = start - center
    val a = delta dot delta
    if (a <= 1e-8f) return null
    val b = 2f * (offset dot delta)
    val c = (offset dot offset) - radius * radius
    val discriminant = b * b - 4f * a * c
    if (discriminant < 0f) return null
    val root = sqrt(discriminant)
    val first = (-b - root) / (2f * a)
    val second = (-b + root) / (2f * a)
    val time = listOf(first, second).filter { it in 0f..1f }.minOrNull() ?: return null
    return start + delta * time
}

private fun direction(from: PetPoint, to: PetPoint): PetPoint {
    val delta = to - from
    val length = delta.length()
    return if (length <= 1e-6f) PetPoint(0f, 0f) else delta / length
}

private fun PetPoint.capped(maximum: Float): PetPoint {
    val speed = length()
    return if (speed <= maximum || speed <= 1e-6f) this else this * (maximum / speed)
}

private fun PetPoint.toOffset(origin: PetPoint) = Offset(x - origin.x, y - origin.y)
private fun PetPoint.length(): Float = hypot(x, y)
private fun PetPoint.distanceTo(other: PetPoint): Float = (this - other).length()
private infix fun PetPoint.dot(other: PetPoint): Float = x * other.x + y * other.y
private operator fun PetPoint.plus(other: PetPoint) = PetPoint(x + other.x, y + other.y)
private operator fun PetPoint.minus(other: PetPoint) = PetPoint(x - other.x, y - other.y)
private operator fun PetPoint.times(scale: Float) = PetPoint(x * scale, y * scale)
private operator fun PetPoint.div(scale: Float) = PetPoint(x / scale, y / scale)
private fun lerp(start: Float, end: Float, progress: Float) = start + (end - start) * progress

private fun rewardColor(kind: RewardEffectKind): Color = when (kind) {
    RewardEffectKind.STUDY -> StudyRewardGold
    RewardEffectKind.REVIEW -> BrandTeal
}
