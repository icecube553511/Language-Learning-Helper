package com.lexitrack.learning.presentation

import kotlin.math.floor
import kotlin.math.sqrt

internal enum class RewardEffectMode { STUDY, REVIEW }

internal const val PET_ENERGY_BALL_CONTRACT = "pet-energy-ball-v1"
internal const val PET_ENERGY_BALL_BEHAVIOR_REVISION = 2
internal const val PET_ENERGY_BALL_INITIAL_SPEED_PX_PER_SECOND = 65.0
internal const val PET_ENERGY_BALL_ACCELERATION_PX_PER_SECOND_SQUARED = 230.0
internal const val PET_ENERGY_BALL_FIXED_STEP_SECONDS = 1.0 / 120.0
internal const val PET_ENERGY_BALL_MAXIMUM_FRAME_SECONDS = 0.1
internal const val PET_ENERGY_BALL_ORB_RADIUS_PX = 7.0
internal const val PET_ENERGY_BALL_CORE_RADIUS_PX = 4.0
internal const val PET_ENERGY_BALL_GLOW_RADIUS_PX = 46.0
internal const val PET_ENERGY_BALL_GLOW_PEAK_ALPHA = 105
internal const val PET_ENERGY_BALL_TRAIL_SAMPLES = 42
internal const val PET_ENERGY_BALL_TRAIL_SAMPLE_STRIDE = 3
internal const val PET_ENERGY_BALL_TRAIL_WIDTH_PX = 7.0
internal const val PET_ENERGY_BALL_TRAIL_HEAD_OPACITY = 0.55f
internal const val PET_ENERGY_BALL_PARTICLE_COUNT = 8
internal const val PET_ENERGY_BALL_BURST_DURATION_SECONDS = 0.42

/** Logical screen coordinates. No Android clock, density, lifecycle or storage APIs. */
internal data class RewardPoint(val x: Double, val y: Double) {
    operator fun plus(other: RewardPoint) = RewardPoint(x + other.x, y + other.y)
    operator fun minus(other: RewardPoint) = RewardPoint(x - other.x, y - other.y)
    operator fun times(factor: Double) = RewardPoint(x * factor, y * factor)
    fun dot(other: RewardPoint) = x * other.x + y * other.y
    fun length() = sqrt(dot(this))
}

internal data class RewardTarget(val center: RewardPoint, val radius: Double, val hostId: String)
internal data class RewardOrb(
    val id: Long,
    val position: RewardPoint,
    val mode: RewardEffectMode,
    val speed: Double = PET_ENERGY_BALL_INITIAL_SPEED_PX_PER_SECOND,
    val trail: List<RewardPoint> = listOf(position),
)
internal data class RewardImpact(
    val id: Long,
    val position: RewardPoint,
    val mode: RewardEffectMode,
    val ageSeconds: Double = 0.0,
)
internal data class RewardSnapshot(
    val orbs: List<RewardOrb> = emptyList(),
    val impacts: List<RewardImpact> = emptyList(),
)

/** Relative segment versus expanded circle, matching the prototype's swept query. */
internal fun rewardCollisionFraction(
    orbStart: RewardPoint,
    orbEnd: RewardPoint,
    targetStart: RewardPoint,
    targetEnd: RewardPoint,
    targetRadius: Double,
): Double? {
    val relativeStart = orbStart - targetStart
    val relativeTravel = (orbEnd - targetEnd) - relativeStart
    val radius = targetRadius + PET_ENERGY_BALL_ORB_RADIUS_PX
    val c = relativeStart.dot(relativeStart) - radius * radius
    if (c <= 0.0) return 0.0
    val a = relativeTravel.dot(relativeTravel)
    if (a <= 1e-20) return null
    val b = 2.0 * relativeStart.dot(relativeTravel)
    val discriminant = b * b - 4.0 * a * c
    if (discriminant < 0.0) return null
    val fraction = (-b - sqrt(discriminant)) / (2.0 * a)
    return fraction.takeIf { it in 0.0..1.0 }
}

internal class RewardPursuit {
    private var sequence = 0L
    private var orbs = emptyList<RewardOrb>()
    private var impacts = emptyList<RewardImpact>()
    private var previousTimeNanos: Long? = null
    private var previousFrameTarget: RewardTarget? = null
    private var previousStepCenter: RewardPoint? = null
    private var accumulatorSeconds = 0.0

    fun snapshot() = RewardSnapshot(orbs, impacts)

    fun spawn(position: RewardPoint, mode: RewardEffectMode): Long {
        val id = ++sequence
        orbs = orbs + RewardOrb(id, position, mode)
        return id
    }

    fun pause() {
        previousTimeNanos = null
        previousFrameTarget = null
        previousStepCenter = null
    }

    fun clear() {
        orbs = emptyList()
        impacts = emptyList()
        accumulatorSeconds = 0.0
        pause()
    }

    fun frame(timeNanos: Long, target: RewardTarget?, active: Boolean = true) {
        if (!active || target == null) {
            pause()
            return
        }
        val previousTime = previousTimeNanos
        previousTimeNanos = timeNanos
        if (previousTime == null) {
            previousFrameTarget = target
            previousStepCenter = target.center
            return
        }
        advance((timeNanos - previousTime).coerceAtLeast(0L) / 1_000_000_000.0, target)
    }

    fun advance(elapsedSeconds: Double, target: RewardTarget) {
        val acceptedSeconds = elapsedSeconds.coerceIn(0.0, PET_ENERGY_BALL_MAXIMUM_FRAME_SECONDS)
        val previous = previousFrameTarget?.takeIf { it.hostId == target.hostId } ?: target.also {
            previousStepCenter = it.center
        }
        val oldRemainder = accumulatorSeconds
        accumulatorSeconds += acceptedSeconds
        val count = floor((accumulatorSeconds + 1e-12) / PET_ENERGY_BALL_FIXED_STEP_SECONDS).toInt()
        for (index in 0 until count) {
            val fraction = if (acceptedSeconds > 0.0) {
                (((index + 1) * PET_ENERGY_BALL_FIXED_STEP_SECONDS - oldRemainder) / acceptedSeconds).coerceIn(0.0, 1.0)
            } else 1.0
            val nextCenter = previous.center + (target.center - previous.center) * fraction
            step(previousStepCenter ?: previous.center, nextCenter, target.radius)
            previousStepCenter = nextCenter
        }
        accumulatorSeconds = (accumulatorSeconds - count * PET_ENERGY_BALL_FIXED_STEP_SECONDS).coerceAtLeast(0.0)
        previousFrameTarget = target
    }

    private fun step(targetStart: RewardPoint, targetEnd: RewardPoint, targetRadius: Double) {
        val dt = PET_ENERGY_BALL_FIXED_STEP_SECONDS
        impacts = impacts.map { it.copy(ageSeconds = it.ageSeconds + dt) }
            .filter { it.ageSeconds + 1e-12 < PET_ENERGY_BALL_BURST_DURATION_SECONDS }
        orbs = orbs.mapNotNull { orb ->
            val offset = targetStart - orb.position
            val length = offset.length()
            val distance = orb.speed * dt + 0.5 * PET_ENERGY_BALL_ACCELERATION_PX_PER_SECOND_SQUARED * dt * dt
            val end = if (length > 0.0) orb.position + offset * (distance / length) else orb.position
            val collision = rewardCollisionFraction(orb.position, end, targetStart, targetEnd, targetRadius)
            if (collision != null) {
                impacts = impacts + RewardImpact(orb.id, targetStart + (targetEnd - targetStart) * collision, orb.mode)
                null
            } else {
                orb.copy(
                    position = end,
                    speed = orb.speed + PET_ENERGY_BALL_ACCELERATION_PX_PER_SECOND_SQUARED * dt,
                    trail = (orb.trail + end).takeLast(PET_ENERGY_BALL_TRAIL_SAMPLES),
                )
            }
        }
    }
}
