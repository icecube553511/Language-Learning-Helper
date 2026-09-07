package com.lexitrack.learning.presentation

import androidx.compose.foundation.Canvas
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.setValue
import androidx.compose.runtime.withFrameNanos
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Rect
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.zIndex
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import com.lexitrack.learning.domain.PetPoint
import kotlin.math.PI
import kotlin.math.cos
import kotlin.math.sin

internal fun rewardColor(mode: RewardEffectMode): Color = when (mode) {
    RewardEffectMode.STUDY -> StudyRewardGold
    RewardEffectMode.REVIEW -> ReviewRewardCyan
}

internal val StudyRewardGold = Color(0xFFF5C451)
internal val ReviewRewardCyan = Color(0xFF39D9D0)

internal fun rewardPointFromScreen(point: Offset, density: Float): RewardPoint =
    RewardPoint(point.x / density.toDouble(), point.y / density.toDouble())

internal fun rewardPointOnHost(point: RewardPoint, origin: PetPoint, density: Float): Offset =
    Offset((point.x * density - origin.x).toFloat(), (point.y * density - origin.y).toFloat())

/** All input methods use Button.onClick; a rejected rating emits nothing. */
internal fun activateRewardRating(
    bounds: Rect,
    mode: RewardEffectMode,
    onRate: () -> Boolean,
    emit: (RewardEffectMode, Offset) -> Unit,
) {
    val center = bounds.takeIf { it.width > 0f && it.height > 0f }?.center
    if (onRate() && center != null) emit(mode, center)
}

/** One app-level model/clock; each native host draws the same immutable frame. */
internal class RewardEffectsController {
    val pursuit = RewardPursuit()
    var snapshot by mutableStateOf(RewardSnapshot())
        private set
    private val targets = mutableMapOf<String, RewardTarget>()

    fun emit(mode: RewardEffectMode, screenPoint: Offset, density: Float) {
        pursuit.spawn(rewardPointFromScreen(screenPoint, density), mode)
        snapshot = pursuit.snapshot()
    }

    fun updateTarget(target: RewardTarget) {
        targets[target.hostId] = target
    }

    fun removeTarget(hostId: String) {
        targets.remove(hostId)
    }

    fun targetFor(hostId: String?): RewardTarget? = hostId?.let(targets::get)

    fun frame(timeNanos: Long, hostId: String?, foreground: Boolean) {
        pursuit.frame(timeNanos, targetFor(hostId), foreground)
        snapshot = pursuit.snapshot()
    }

    fun pause() = pursuit.pause()

    fun clear() {
        targets.clear()
        pursuit.clear()
        snapshot = RewardSnapshot()
    }
}

@Composable
internal fun rememberRewardEffectsController(activeHost: () -> String?): RewardEffectsController {
    val controller = remember { RewardEffectsController() }
    val lifecycle = LocalLifecycleOwner.current.lifecycle
    val latestActiveHost by rememberUpdatedState(activeHost)
    var foreground by remember(lifecycle) { mutableStateOf(lifecycle.currentState.isAtLeast(Lifecycle.State.RESUMED)) }
    DisposableEffect(lifecycle, controller) {
        val observer = LifecycleEventObserver { _, _ ->
            foreground = lifecycle.currentState.isAtLeast(Lifecycle.State.RESUMED)
            // withFrameNanos may itself stop in the background, so reset here.
            if (!foreground) controller.pause()
        }
        lifecycle.addObserver(observer)
        onDispose {
            lifecycle.removeObserver(observer)
            controller.clear()
        }
    }
    LaunchedEffect(controller) {
        while (true) {
            withFrameNanos { time -> controller.frame(time, latestActiveHost(), foreground) }
        }
    }
    return controller
}

@Composable
internal fun RewardEffectsHost(
    controller: RewardEffectsController,
    hostOrigin: PetPoint,
    modifier: Modifier = Modifier,
) {
    val snapshot = controller.snapshot
    val density = LocalDensity.current.density
    Canvas(modifier = modifier.zIndex(30f)) {
        snapshot.orbs.forEach { orb ->
            val color = rewardColor(orb.mode)
            val points = orb.trail.filterIndexed { index, _ -> index % PET_ENERGY_BALL_TRAIL_SAMPLE_STRIDE == 0 }
            for (index in 1 until points.size) {
                val strength = index.toFloat() / points.size
                drawLine(
                    color = color.copy(alpha = PET_ENERGY_BALL_TRAIL_HEAD_OPACITY * strength),
                    start = rewardPointOnHost(points[index - 1], hostOrigin, density),
                    end = rewardPointOnHost(points[index], hostOrigin, density),
                    strokeWidth = (PET_ENERGY_BALL_TRAIL_WIDTH_PX.toFloat() * strength).coerceAtLeast(1f) * density,
                    cap = StrokeCap.Round,
                )
            }
            val position = rewardPointOnHost(orb.position, hostOrigin, density)
            // Annuli preserve the prototype's alpha profile without additive stacking.
            for (radius in PET_ENERGY_BALL_GLOW_RADIUS_PX.toInt() downTo 1) {
                val strength = 1f - radius / PET_ENERGY_BALL_GLOW_RADIUS_PX.toFloat()
                drawCircle(
                    color.copy(alpha = PET_ENERGY_BALL_GLOW_PEAK_ALPHA / 255f * strength * strength),
                    (radius - 0.5f) * density,
                    position,
                    style = Stroke(density),
                )
            }
            drawCircle(color, PET_ENERGY_BALL_ORB_RADIUS_PX.toFloat() * density, position)
            drawCircle(Color(0xFFFFFAE4), PET_ENERGY_BALL_CORE_RADIUS_PX.toFloat() * density, position)
        }
        snapshot.impacts.forEach { impact ->
            val progress = (impact.ageSeconds / PET_ENERGY_BALL_BURST_DURATION_SECONDS).toFloat()
            val color = rewardColor(impact.mode).copy(alpha = (1f - progress).coerceIn(0f, 1f))
            val position = rewardPointOnHost(impact.position, hostOrigin, density)
            drawCircle(color, (20f + 38f * progress) * density, position, style = Stroke(2f * density))
            repeat(PET_ENERGY_BALL_PARTICLE_COUNT) { index ->
                val angle = (2 * PI * index / PET_ENERGY_BALL_PARTICLE_COUNT).toFloat()
                drawCircle(
                    color,
                    2f * density,
                    position + Offset(cos(angle), sin(angle)) * ((22f + 44f * progress) * density),
                )
            }
        }
    }
}
