package com.lexitrack.learning.presentation

import androidx.compose.foundation.Canvas
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.runtime.withFrameNanos
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.unit.dp
import androidx.compose.ui.zIndex
import com.lexitrack.learning.domain.PetPoint
import kotlin.math.PI
import kotlin.math.cos
import kotlin.math.sin

/** The rating effect is presentation-only and is never persisted with learning data. */
internal enum class RewardEffectMode {
    STUDY,
    REVIEW,
}

/** Contract marker: pet-energy-ball-v1. */
internal const val PET_ENERGY_BALL_CONTRACT = "pet-energy-ball-v1"
internal const val PET_ENERGY_BALL_MAX_SPEED_PX_PER_SECOND = 1_800f
internal const val PET_ENERGY_BALL_HIT_RADIUS_PX = 36f
internal const val PET_ENERGY_BALL_MIN_TRAIL_PX = 12f
internal const val PET_ENERGY_BALL_MAX_TRAIL_PX = 96f
internal const val PET_ENERGY_BALL_PARTICLE_COUNT = 18
internal const val PET_ENERGY_BALL_BURST_DURATION_MS = 260f
internal const val PET_ENERGY_BALL_MAX_CONCURRENT = 3

internal val StudyRewardGold = Color(0xFFF5C451)
internal val ReviewRewardCyan = Color(0xFF39D9D0)

internal data class RewardEffectRequest(
    val id: Long,
    val start: Offset,
    val target: Offset,
    val color: Color,
    val durationMillis: Int = rewardDurationMillis((target - start).getDistance()),
)

internal fun rewardColor(mode: RewardEffectMode): Color = when (mode) {
    RewardEffectMode.STUDY -> StudyRewardGold
    RewardEffectMode.REVIEW -> ReviewRewardCyan
}

internal fun rewardDurationMillis(distancePx: Float): Int =
    (360f + distancePx.coerceIn(0f, 1_600f) * 0.18f).toInt().coerceIn(360, 650)

/** Quadratic ease-in gives the orb a visible acceleration toward Bingzi. */
internal fun rewardProgress(elapsedMillis: Float, durationMillis: Int): Float {
    if (durationMillis <= 0) return 1f
    return (elapsedMillis / durationMillis).coerceIn(0f, 1f).let { it * it }
}

internal fun rewardOrbPosition(request: RewardEffectRequest, progress: Float): Offset =
    request.start + (request.target - request.start) * progress.coerceIn(0f, 1f)

internal fun rewardSpeedPxPerSecond(
    distancePx: Float,
    elapsedMillis: Float,
    durationMillis: Int,
): Float {
    if (durationMillis <= 0) return 0f
    val normalizedTime = (elapsedMillis / durationMillis).coerceIn(0f, 1f)
    return (distancePx * 2f * normalizedTime / (durationMillis / 1_000f))
        .coerceAtMost(PET_ENERGY_BALL_MAX_SPEED_PX_PER_SECOND)
}

internal fun rewardTrailLength(speedPxPerSecond: Float): Float =
    (PET_ENERGY_BALL_MIN_TRAIL_PX + speedPxPerSecond * 0.047f)
        .coerceIn(PET_ENERGY_BALL_MIN_TRAIL_PX, PET_ENERGY_BALL_MAX_TRAIL_PX)

@Composable
internal fun RewardEffectsHost(
    request: RewardEffectRequest?,
    hostOrigin: PetPoint,
    onFinished: (Long) -> Unit,
    modifier: Modifier = Modifier,
    targetProvider: () -> Offset? = { null },
) {
    var orbProgress by remember { mutableStateOf(0f) }
    var burstProgress by remember { mutableStateOf(0f) }
    var flowPhase by remember { mutableStateOf(0f) }
    var burstStarted by remember { mutableStateOf(false) }
    var collisionTarget by remember { mutableStateOf<Offset?>(null) }
    var liveTarget by remember { mutableStateOf<Offset?>(null) }

    LaunchedEffect(request?.id) {
        val current = request ?: run {
            orbProgress = 0f
            burstProgress = 0f
            return@LaunchedEffect
        }
        val flightDuration = current.durationMillis.toFloat()
        val burstDuration = PET_ENERGY_BALL_BURST_DURATION_MS
        liveTarget = current.target
        burstStarted = false
        burstProgress = 0f
        collisionTarget = null
        val startedAt = withFrameNanos { it }
        var burstStartedAt: Float? = null
        while (true) {
            val elapsed = (withFrameNanos { it } - startedAt) / 1_000_000f
            targetProvider()?.let { liveTarget = it }
            val frameRequest = current.copy(target = liveTarget ?: current.target)
            val nextProgress = rewardProgress(elapsed, current.durationMillis)
            val framePosition = rewardOrbPosition(frameRequest, nextProgress)
            val targetDistance = (frameRequest.target - framePosition).getDistance()
            if (burstStartedAt == null && (targetDistance <= PET_ENERGY_BALL_HIT_RADIUS_PX || elapsed >= flightDuration)) {
                burstStartedAt = elapsed
                burstStarted = true
                collisionTarget = frameRequest.target
                orbProgress = 1f
            } else if (burstStartedAt == null) {
                orbProgress = nextProgress
            }
            flowPhase = (elapsed / 140f) % 1f
            burstProgress = burstStartedAt?.let { (elapsed - it) / burstDuration }?.coerceIn(0f, 1f) ?: 0f
            if (burstStartedAt != null && elapsed >= burstStartedAt + burstDuration) {
                orbProgress = 0f
                burstProgress = 0f
                burstStarted = false
                collisionTarget = null
                onFinished(current.id)
                break
            }
        }
    }

    val active = request ?: return
    val density = androidx.compose.ui.platform.LocalDensity.current
    val orbRadius = with(density) { 6.dp.toPx() }
    val localOrigin = Offset(hostOrigin.x, hostOrigin.y)
    val liveRequest = active.copy(target = liveTarget ?: active.target)
    val start = liveRequest.start - localOrigin
    val target = (collisionTarget ?: liveRequest.target) - localOrigin
    val position = rewardOrbPosition(liveRequest, orbProgress) - localOrigin
    val direction = (target - start).let { vector ->
        val length = vector.getDistance()
        if (length > 0.5f) vector / length else Offset(0f, -1f)
    }
    val distance = (target - start).getDistance()
    val elapsedForSpeed = active.durationMillis * kotlin.math.sqrt(orbProgress)
    val trail = rewardTrailLength(
        rewardSpeedPxPerSecond(distance, elapsedForSpeed, active.durationMillis),
    )

    Canvas(modifier = modifier.zIndex(30f)) {
        if (!burstStarted) {
            // Layered lines and circles produce a soft halo without a platform-specific blur.
            for (index in 0 until 6) {
                val fraction = index / 6f
                val tail = position - direction * (trail * fraction)
                drawLine(
                    color = active.color.copy(alpha = 0.05f + (1f - fraction) * 0.12f),
                    start = tail,
                    end = position,
                    strokeWidth = orbRadius * (2.2f - fraction),
                    cap = StrokeCap.Round,
                )
            }
            repeat(3) { index ->
                val fraction = (flowPhase + index * 0.31f) % 1f
                val flowPoint = position - direction * (trail * fraction)
                drawCircle(active.color.copy(alpha = (1f - fraction) * 0.36f), orbRadius * (0.3f + 0.14f * (1f - fraction)), flowPoint)
            }
            drawCircle(active.color.copy(alpha = 0.09f), orbRadius * 4.2f, position)
            drawCircle(active.color.copy(alpha = 0.18f), orbRadius * 2.4f, position)
            drawCircle(Color.White.copy(alpha = 0.92f), orbRadius * 0.72f, position)
            drawCircle(active.color, orbRadius, position, style = androidx.compose.ui.graphics.drawscope.Fill)
        }
        if (burstStarted) {
            val fade = 1f - burstProgress
            drawCircle(active.color.copy(alpha = 0.18f * fade), orbRadius * (2f + 8f * burstProgress), target)
            repeat(PET_ENERGY_BALL_PARTICLE_COUNT) { index ->
                val angle = (2.0 * PI * index / PET_ENERGY_BALL_PARTICLE_COUNT).toFloat()
                val rayDirection = Offset(cos(angle), sin(angle))
                val inner = target + rayDirection * (orbRadius * (0.5f + burstProgress * 2f))
                val outer = target + rayDirection * (orbRadius * (1.5f + burstProgress * 10f))
                drawLine(
                    color = active.color.copy(alpha = fade * 0.72f),
                    start = inner,
                    end = outer,
                    strokeWidth = orbRadius * fade.coerceAtLeast(0.18f) * 0.55f,
                    cap = StrokeCap.Round,
                )
                drawCircle(
                    color = Color.White.copy(alpha = fade * 0.8f),
                    radius = orbRadius * fade * 0.42f,
                    center = outer,
                )
            }
        }
    }
}
