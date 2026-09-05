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
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
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
import kotlin.math.sin
import kotlin.math.sqrt

/** A small, deterministic feedback system for study and review ratings. */
internal object FeedbackTuning {
    /** Duration of the soft launch arc before the orb starts seeking Bingzi. */
    const val INTRO_MS = 150L
    /** Kept as an alias for callers that used the original tuning name. */
    const val ORBIT_MS = INTRO_MS
    const val INTRO_ARC = 15f
    const val SEEK_SPEED = 260f
    const val SEEK_ACCELERATION = 1_900f
    const val MAX_SPEED = 1_800f
    const val TRAIL_MS = 140L
    const val IMPACT_MS = 280L
    const val MAX_AGE_MS = 2_400L
    const val TARGET_GRACE_MS = 600L
    const val ORB_RADIUS = 7f
    const val VISUAL_ORB_RADIUS = 11f
    const val VISUAL_GLOW_RADIUS = 27f
    const val VISUAL_HIGHLIGHT_RADIUS = 2.5f
    const val IMPACT_RADIUS = 46f
    const val PARTICLES = 12
}

enum class FeedbackKind { STUDY, REVIEW }

data class FeedbackOrigin(val x: Float, val y: Float) {
    init { require(x.isFinite() && y.isFinite()) { "Feedback origin must be finite" } }
    internal fun point() = PetPoint(x, y)
}

data class FeedbackRequest(val kind: FeedbackKind, val origin: FeedbackOrigin)

internal const val RATING_POINTER_ORIGIN_FRESHNESS_MS = 1_500L
internal data class RatingPointerDown(val origin: FeedbackOrigin, val capturedAtUptimeMs: Long)

internal fun resolveRatingOrigin(pointerDown: RatingPointerDown?, buttonBounds: androidx.compose.ui.geometry.Rect, nowUptimeMs: Long): FeedbackOrigin {
    val age = pointerDown?.let { nowUptimeMs - it.capturedAtUptimeMs }
    return if (pointerDown != null && age in 0L..RATING_POINTER_ORIGIN_FRESHNESS_MS) pointerDown.origin
    else FeedbackOrigin((buttonBounds.left + buttonBounds.right) / 2f, (buttonBounds.top + buttonBounds.bottom) / 2f)
}

internal data class FeedbackTarget(val center: PetPoint, val halfSize: Float)
internal data class FeedbackOrb(val id: Long, val kind: FeedbackKind, val position: PetPoint, val velocity: PetPoint, val ageMs: Long, val trail: List<PetPoint>)
internal data class FeedbackImpact(val kind: FeedbackKind, val origin: PetPoint, val progress: Float)
internal data class FeedbackParticle(val kind: FeedbackKind, val position: PetPoint, val alpha: Float)
internal data class FeedbackSnapshot(val orbs: List<FeedbackOrb> = emptyList(), val impacts: List<FeedbackImpact> = emptyList(), val particles: List<FeedbackParticle> = emptyList()) { val active get() = orbs.isNotEmpty() || impacts.isNotEmpty() }

private data class OrbState(val id: Long, val kind: FeedbackKind, val origin: PetPoint, var position: PetPoint, var velocity: PetPoint = PetPoint(0f, 0f), var ageMs: Long = 0L, var noTargetMs: Long = 0L, val trail: ArrayDeque<PetPoint> = ArrayDeque())
private data class ImpactState(val kind: FeedbackKind, val origin: PetPoint, var ageMs: Long = 0L)

internal class FeedbackEngine {
    private val orbs = mutableListOf<OrbState>()
    private val impacts = mutableListOf<ImpactState>()
    private var nextId = 1L

    fun emit(request: FeedbackRequest): Long {
        val origin = request.origin.point()
        return nextId.also { nextId++ }.also { id ->
            orbs += OrbState(id, request.kind, origin, origin).also { it.trail.add(origin) }
        }
    }

    fun step(deltaMs: Long, target: FeedbackTarget?) {
        if (deltaMs <= 0) return
        impacts.forEach { it.ageMs += deltaMs }
        impacts.removeAll { it.ageMs >= FeedbackTuning.IMPACT_MS }
        val dt = deltaMs / 1_000f
        val it = orbs.iterator()
        while (it.hasNext()) {
            val orb = it.next(); orb.ageMs += deltaMs
            if (target == null) orb.noTargetMs += deltaMs else orb.noTargetMs = 0
            if (orb.ageMs >= FeedbackTuning.MAX_AGE_MS || orb.noTargetMs >= FeedbackTuning.TARGET_GRACE_MS) { it.remove(); continue }
            val previous = orb.position
            val enteredSeek = orb.ageMs >= FeedbackTuning.INTRO_MS && orb.ageMs - deltaMs < FeedbackTuning.INTRO_MS
            if (orb.ageMs < FeedbackTuning.INTRO_MS) {
                val p = (orb.ageMs.toFloat() / FeedbackTuning.INTRO_MS).coerceIn(0f, 1f)
                // A short, easing arc gives the glow a soft launch without delaying the seek.
                val eased = p * p * (3f - 2f * p)
                val angle = (2f * PI * (0.15f + 0.55f * eased)).toFloat()
                val radius = FeedbackTuning.INTRO_ARC * (1f - eased)
                orb.position = PetPoint(orb.origin.x + cos(angle) * radius, orb.origin.y + sin(angle) * radius)
            } else if (target != null) {
                val delta = target.center - orb.position
                val distance = delta.length()
                val direction = if (distance < 0.001f) PetPoint(0f, 0f) else delta / distance
                // Accelerate toward the current target every frame so a reflowing pet is tracked.
                if (enteredSeek) orb.velocity = direction * FeedbackTuning.SEEK_SPEED
                orb.velocity = (orb.velocity + direction * (FeedbackTuning.SEEK_ACCELERATION * dt)).let { velocity ->
                    val speed = velocity.length()
                    if (speed > FeedbackTuning.MAX_SPEED) velocity / speed * FeedbackTuning.MAX_SPEED else velocity
                }
                val next = orb.position + orb.velocity * dt
                val contact = target.halfSize.coerceAtLeast(0f) + FeedbackTuning.ORB_RADIUS
                if (distance <= contact || next.distanceTo(target.center) <= contact) {
                    orb.position = target.center; impacts += ImpactState(orb.kind, target.center); it.remove(); continue
                }
                orb.position = next
            }
            if (orb.position.distanceTo(previous) > 0.5f) orb.trail.addLast(orb.position)
            while (orb.trail.size > 14) orb.trail.removeFirst()
        }
    }

    fun snapshot(): FeedbackSnapshot = FeedbackSnapshot(
        orbs = orbs.map { FeedbackOrb(it.id, it.kind, it.position, it.velocity, it.ageMs, it.trail.toList()) },
        impacts = impacts.map { FeedbackImpact(it.kind, it.origin, (it.ageMs.toFloat() / FeedbackTuning.IMPACT_MS).coerceIn(0f, 1f)) },
        particles = impacts.flatMap { impact ->
            val p = (impact.ageMs.toFloat() / FeedbackTuning.IMPACT_MS).coerceIn(0f, 1f)
            List(FeedbackTuning.PARTICLES) { i ->
                val a = (2f * PI * i / FeedbackTuning.PARTICLES).toFloat()
                val r = 10f + 58f * p
                FeedbackParticle(impact.kind, PetPoint(impact.origin.x + cos(a) * r, impact.origin.y + sin(a) * r), (1f - p) * (1f - p))
            }
        },
    )
}

internal class FeedbackController(private val engine: FeedbackEngine = FeedbackEngine()) {
    var snapshot by mutableStateOf(engine.snapshot()); private set
    fun emit(request: FeedbackRequest) { engine.emit(request); snapshot = engine.snapshot() }
    fun step(deltaMs: Long, target: FeedbackTarget?) { engine.step(deltaMs, target); snapshot = engine.snapshot() }
}

internal val LocalFeedbackController = staticCompositionLocalOf { FeedbackController() }
internal val StudyRewardGold = Color(0xFFF4C542)

private fun Modifier.pointerTransparent() = this.then(PointerTransparentElement)
private object PointerTransparentElement : ModifierNodeElement<PointerTransparentNode>() { override fun create() = PointerTransparentNode(); override fun update(node: PointerTransparentNode) = Unit; override fun equals(other: Any?) = other === this; override fun hashCode() = javaClass.hashCode() }
private class PointerTransparentNode : Modifier.Node(), PointerInputModifierNode {
    override fun onPointerEvent(pointerEvent: PointerEvent, pass: PointerEventPass, bounds: IntSize) = Unit
    override fun onCancelPointerInput() = Unit
    override fun sharePointerInputWithSiblings() = true
}

@Composable
internal fun FeedbackAnimator(controller: FeedbackController, coordinator: PetWindowCoordinator, petHalfSizePx: Float) {
    val hostView = LocalView.current; val active = controller.snapshot.active
    LaunchedEffect(controller, coordinator, petHalfSizePx, active) {
        if (!active) return@LaunchedEffect
        var previous = withFrameNanos { it }
        while (isActive && controller.snapshot.active) {
            val frame = withFrameNanos { it }
            if (hostView.isShown && hostView.windowVisibility == View.VISIBLE) {
                val elapsed = ((frame - previous) / 1_000_000L).coerceIn(1L, 32L)
                val target = coordinator.worldPosition()?.let { FeedbackTarget(it, petHalfSizePx) }
                controller.step(elapsed, target)
            }
            previous = frame
        }
    }
}

@Composable
internal fun FeedbackCanvas(windowOrigin: PetPoint, modifier: Modifier = Modifier) {
    val snapshot = LocalFeedbackController.current.snapshot
    Canvas(modifier = modifier.pointerTransparent().zIndex(21f)) {
        snapshot.orbs.forEach { orb ->
            val color = feedbackColor(orb.kind); val center = orb.position.toOffset(windowOrigin)
            orb.trail.zipWithNext().forEachIndexed { i, (a, b) ->
                val alpha = (i + 1f) / orb.trail.size * 0.6f
                val speedRatio = (orb.velocity.length() / FeedbackTuning.MAX_SPEED).coerceIn(0f, 1f)
                val width = 2f + 4f * speedRatio
                drawLine(color.copy(alpha = alpha * 0.3f), a.toOffset(windowOrigin), b.toOffset(windowOrigin), width * 1.7f, StrokeCap.Round)
                drawLine(color.copy(alpha = alpha), a.toOffset(windowOrigin), b.toOffset(windowOrigin), width, StrokeCap.Round)
            }
            drawCircle(Brush.radialGradient(listOf(Color.White, color.copy(alpha = 0.8f), Color.Transparent), center, FeedbackTuning.VISUAL_GLOW_RADIUS), FeedbackTuning.VISUAL_GLOW_RADIUS, center)
            drawCircle(color, FeedbackTuning.VISUAL_ORB_RADIUS, center)
            drawCircle(Color.White.copy(alpha = 0.9f), FeedbackTuning.VISUAL_HIGHLIGHT_RADIUS, center - Offset(3f, 3f))
        }
        snapshot.impacts.forEach { impact ->
            val color = feedbackColor(impact.kind); val center = impact.origin.toOffset(windowOrigin); val p = impact.progress
            drawCircle(color.copy(alpha = (1f - p) * 0.7f), 8f + 42f * p, center, style = Stroke(2f))
        }
        snapshot.particles.forEach { particle -> drawCircle(feedbackColor(particle.kind).copy(alpha = particle.alpha), 3f, particle.position.toOffset(windowOrigin)) }
    }
}

private fun feedbackColor(kind: FeedbackKind) = if (kind == FeedbackKind.STUDY) StudyRewardGold else BrandTeal
private fun PetPoint.toOffset(origin: PetPoint) = Offset(x - origin.x, y - origin.y)
private fun PetPoint.length() = hypot(x, y)
private fun PetPoint.distanceTo(other: PetPoint) = (this - other).length()
private operator fun PetPoint.plus(other: PetPoint) = PetPoint(x + other.x, y + other.y)
private operator fun PetPoint.minus(other: PetPoint) = PetPoint(x - other.x, y - other.y)
private operator fun PetPoint.times(scale: Float) = PetPoint(x * scale, y * scale)
private operator fun PetPoint.div(scale: Float) = PetPoint(x / scale, y / scale)

