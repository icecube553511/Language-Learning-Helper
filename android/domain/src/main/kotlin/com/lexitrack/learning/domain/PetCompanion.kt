package com.lexitrack.learning.domain

import kotlin.math.abs
import kotlin.math.max
import kotlin.math.hypot
import kotlin.math.min
import kotlin.math.pow
import kotlin.math.sqrt

/**
 * Presentation-only state for the Bingzi companion.  The domain owns only
 * deterministic geometry and state transitions; callers must not persist this
 * state as part of learning data.
 */
enum class PetMode {
    IDLE,
    SLIDE,
    ROLL,
    FLY,
    FALL,
    BOUNCE,
    DRAGGING,
    FLING,
}

enum class PetFacing {
    LEFT,
    RIGHT,
}

const val PET_MOTION_ACCELERATION = 0.5f
const val PET_CRUISE_SPEED = 4f
/** Chart motion intentionally accelerates more gently than ordinary movement. */
const val PET_CURVE_ACCELERATION = 0.25f
const val PET_CURVE_MOTION_ACCELERATION = PET_CURVE_ACCELERATION
const val PET_CURVE_LANDING_SPEED_LIMIT = 8f
const val PET_CURVE_DOWNHILL_TERMINAL_SPEED = 7.04f
const val PET_CURVE_DOWNHILL_RESPONSE_PER_TICK = 0.125f
const val PET_CURVE_DIRECTION_EPSILON = 0.000001f
const val PET_SUPPORT_CONTACT_TOLERANCE = 0.5f
const val PET_CURVE_VALLEY_REST_SPEED = 0.25f
const val PET_CURVE_CORNER_SUBSTEPS = 4
const val PET_CURVE_CORNER_RADIUS = 8f
const val PET_FALL_TIME_STEP_SECONDS = 0.016f
const val PET_FALL_GRAVITY = 3437.5f
const val PET_FLING_GRAVITY = PET_FALL_GRAVITY
const val PET_FLING_HORIZONTAL_RESTITUTION = 0.72f
const val PET_MAX_SUBSTEP_SECONDS = 0.004f
const val PET_MAX_SUBSTEPS_PER_TICK = 8
const val PET_RELEASE_VELOCITY_SAMPLE_WINDOW_MS = 120L
const val PET_MINIMUM_FLING_SPEED = 90f
const val PET_MAX_FLING_SPEED = 1800f
const val PET_HARD_LANDING_SPEED = 437.5f
const val PET_BOUNCE_COUNT = 2
const val PET_FIRST_BOUNCE_SPEED = 312.5f
const val PET_BOUNCE_DECAY = 0.55f
const val PET_CENTER_BIAS_WEIGHT = 0.65f
const val PET_EDGE_PENALTY_RATIO = 0.15f
const val PET_IDLE_TICKS = 24

private const val PET_EPSILON = 1e-3f
private const val PET_VIEWPORT_BOTTOM_TARGET_ID = "__viewport-bottom__"

enum class PetTargetKind {
    CONTROL,
    SURFACE,
    CHART,
    EDGE,
}

data class PetPoint(val x: Float, val y: Float)

data class PetRect(
    val x: Float,
    val y: Float,
    val width: Float,
    val height: Float,
) {
    init {
        require(x.isFinite() && y.isFinite() && width.isFinite() && height.isFinite()) {
            "Pet target bounds must be finite"
        }
        require(width >= 0f && height >= 0f) {
            "Pet target bounds must be ordered"
        }
    }

    val left: Float get() = x
    val top: Float get() = y
    val right: Float get() = x + width
    val bottom: Float get() = y + height
    val valid: Boolean get() = width > 0f && height > 0f

    fun contains(point: PetPoint): Boolean =
        point.x in left..right && point.y in top..bottom

    /** Squared distance from a point to the nearest point on this rectangle. */
    fun distanceSquared(point: PetPoint): Float {
        val dx = when {
            point.x < left -> left - point.x
            point.x > right -> point.x - right
            else -> 0f
        }
        val dy = when {
            point.y < top -> top - point.y
            point.y > bottom -> point.y - bottom
            else -> 0f
        }
        return dx * dx + dy * dy
    }

    fun closestPoint(point: PetPoint, margin: Float = 0f): PetPoint {
        val inset = max(0f, margin)
        return PetPoint(
            point.x.coerceIn(left - inset, right + inset),
            point.y.coerceIn(top - inset, bottom + inset),
        )
    }

    fun boundaryPoint(point: PetPoint, margin: Float = 0f): PetPoint {
        val inset = max(0f, margin)
        val expanded = PetRect(left - inset, top - inset, width + inset * 2f, height + inset * 2f)
        if (!expanded.contains(point)) return expanded.closestPoint(point)
        val candidates = listOf(
            PetPoint(point.x, expanded.top),
            PetPoint(expanded.right, point.y),
            PetPoint(point.x, expanded.bottom),
            PetPoint(expanded.left, point.y),
        )
        return candidates.minByOrNull { hypot(it.x - point.x, it.y - point.y) } ?: point
    }

    fun nextBoundaryCorner(point: PetPoint, margin: Float = 0f): PetPoint {
        val inset = max(0f, margin)
        val left = this.left - inset
        val right = this.right + inset
        val top = this.top - inset
        val bottom = this.bottom + inset
        val epsilon = 1e-3f
        if (abs(point.x - right) <= epsilon && abs(point.y - top) <= epsilon) return PetPoint(right, bottom)
        if (abs(point.x - right) <= epsilon && abs(point.y - bottom) <= epsilon) return PetPoint(left, bottom)
        if (abs(point.x - left) <= epsilon && abs(point.y - bottom) <= epsilon) return PetPoint(left, top)
        if (abs(point.x - left) <= epsilon && abs(point.y - top) <= epsilon) return PetPoint(right, top)
        val candidates = listOf(
            abs(point.y - top) to PetPoint(right, top),
            abs(point.x - right) to PetPoint(right, bottom),
            abs(point.y - bottom) to PetPoint(left, bottom),
            abs(point.x - left) to PetPoint(left, top),
        )
        return candidates.minByOrNull { it.first }?.second ?: PetPoint(right, top)
    }

    fun clamp(point: PetPoint, inset: Float = 0f): PetPoint {
        val horizontal = max(0f, right - left - inset * 2f)
        val vertical = max(0f, bottom - top - inset * 2f)
        return PetPoint(
            x = (point.x - left - inset).coerceIn(0f, horizontal) + left + inset,
            y = (point.y - top - inset).coerceIn(0f, vertical) + top + inset,
        )
    }
}

data class PetTarget(
    val id: String,
    val kind: PetTargetKind,
    val rect: PetRect,
    /** Optional chart polyline in the same screen coordinate space. */
    val path: List<PetPoint> = emptyList(),
    val visible: Boolean = true,
) {
    init {
        require(id.isNotBlank()) { "Pet target id cannot be blank" }
    }

    val bounds: PetRect get() = rect
    val valid: Boolean get() = visible && rect.valid

    fun distanceTo(point: PetPoint, margin: Float = 0f): Float {
        val support = closestSupportPoint(this, point, max(0f, margin))
        return hypot(point.x - support.x, point.y - support.y)
    }
}

data class PetState(
    val position: PetPoint,
    val mode: PetMode = PetMode.IDLE,
    val targetId: String? = null,
    val idleTicksRemaining: Int = 0,
    val pathIndex: Int = 0,
    val pathDirection: Int = 1,
    val rollCorners: Int = 0,
    val avoidTargetId: String? = null,
    val movementSpeed: Float = 0f,
    val verticalVelocity: Float = 0f,
    val bouncesRemaining: Int = 0,
    val facing: PetFacing = PetFacing.RIGHT,
    val dragOffset: PetPoint? = null,
    /** Non-zero only while a user fling is being simulated. */
    val horizontalVelocity: Float = 0f,
    /** Signed arc speed in canonical chart-path order, or null for autonomous motion. */
    val curveVelocity: Float? = null,
) {
    /** Aliases used by platform adapters and cross-platform tests. */
    val velocityX: Float get() = horizontalVelocity
    val velocityY: Float get() = verticalVelocity
    val velocity: PetPoint get() = PetPoint(horizontalVelocity, verticalVelocity)
}

/** A constrained pet-centre sample captured while the user drags. */
data class PetMotionSample(
    val timestampMs: Long,
    val position: PetPoint,
)

typealias PetDragSample = PetMotionSample
typealias PetVelocitySample = PetMotionSample

/** Proportionally limit a fling vector while preserving its tangent. */
fun limitFlingVelocity(
    velocity: PetPoint,
    maximum: Float = PET_MAX_FLING_SPEED,
): PetPoint {
    if (!velocity.x.isFinite() || !velocity.y.isFinite()) return PetPoint(0f, 0f)
    val limit = when {
        maximum.isNaN() -> PET_MAX_FLING_SPEED
        maximum == Float.POSITIVE_INFINITY -> PET_MAX_FLING_SPEED
        maximum == Float.NEGATIVE_INFINITY -> 0f
        else -> maximum.coerceAtLeast(0f)
    }
    val magnitude = hypot(velocity.x, velocity.y)
    if (!magnitude.isFinite()) return PetPoint(0f, 0f)
    if (magnitude <= limit || magnitude <= PET_EPSILON) return velocity
    val scale = limit / magnitude
    return PetPoint(velocity.x * scale, velocity.y * scale)
}

/** Snake-case alias for parity with the Windows domain adapter. */
fun limit_fling_velocity(velocity: PetPoint, maximum: Float = PET_MAX_FLING_SPEED): PetPoint =
    limitFlingVelocity(velocity, maximum)

private fun parseMotionSample(value: Any?): PetMotionSample? {
    when (value) {
        is PetMotionSample -> return value
        is Map<*, *> -> {
            val timestamp = sequenceOf("timeMs", "timestampMs", "time", "timestamp")
                .mapNotNull { key -> value[key] as? Number }
                .firstOrNull()
            val rawPosition = value["position"] ?: value["point"]
            val position = when (rawPosition) {
                is PetPoint -> rawPosition
                is Pair<*, *> -> {
                    val x = rawPosition.first as? Number
                    val y = rawPosition.second as? Number
                    if (x != null && y != null) PetPoint(x.toFloat(), y.toFloat()) else null
                }
                is List<*> -> {
                    val x = rawPosition.getOrNull(0) as? Number
                    val y = rawPosition.getOrNull(1) as? Number
                    if (x != null && y != null) PetPoint(x.toFloat(), y.toFloat()) else null
                }
                else -> null
            }
            if (timestamp != null && position != null) {
                return PetMotionSample(timestamp.toLong(), position)
            }
        }
        is Pair<*, *> -> {
            val first = value.first
            val second = value.second
            if (first is Number && second is PetPoint) {
                return PetMotionSample(first.toLong(), second)
            }
            if (first is PetPoint && second is Number) {
                return PetMotionSample(second.toLong(), first)
            }
            if (first is Number && second is Pair<*, *>) {
                val x = second.first as? Number
                val y = second.second as? Number
                if (x != null && y != null) {
                    return PetMotionSample(first.toLong(), PetPoint(x.toFloat(), y.toFloat()))
                }
            }
        }
        is Triple<*, *, *> -> {
            val timestamp = value.first as? Number
            val x = value.second as? Number
            val y = value.third as? Number
            if (timestamp != null && x != null && y != null) {
                return PetMotionSample(timestamp.toLong(), PetPoint(x.toFloat(), y.toFloat()))
            }
        }
    }
    return null
}

/**
 * Estimate the terminal drag tangent using a recency-weighted linear
 * regression. Samples must be the *constrained* pet centres and timestamps
 * are monotonic milliseconds. The result is expressed in logical units/sec.
 */
fun estimateReleaseVelocity(
    samples: Iterable<*>,
    nowMs: Long? = null,
    windowMs: Long = PET_RELEASE_VELOCITY_SAMPLE_WINDOW_MS,
): PetPoint {
    val parsed = samples.mapNotNull(::parseMotionSample).sortedBy(PetMotionSample::timestampMs)
    if (parsed.size < 2) return PetPoint(0f, 0f)
    val end = nowMs ?: parsed.last().timestampMs
    val cutoff = end - windowMs.coerceAtLeast(0L)
    val recent = parsed.filter { it.timestampMs >= cutoff && it.timestampMs <= end }
    if (recent.size < 2) return PetPoint(0f, 0f)
    val origin = recent.first().timestampMs
    val times = recent.map { (it.timestampMs - origin) / 1000f }
    val span = times.last().coerceAtLeast(1e-6f)
    if (span <= 1e-6f) return PetPoint(0f, 0f)
    val weights = times.map { 0.25f + 0.75f * (it / span) }
    val weightSum = weights.sum().coerceAtLeast(1e-6f)
    val meanT = times.zip(weights).sumOf { (time, weight) -> (time * weight).toDouble() }.toFloat() / weightSum
    val meanX = recent.zip(weights).sumOf { (sample, weight) -> (sample.position.x * weight).toDouble() }.toFloat() / weightSum
    val meanY = recent.zip(weights).sumOf { (sample, weight) -> (sample.position.y * weight).toDouble() }.toFloat() / weightSum
    val denominator = times.zip(weights).sumOf { (time, weight) -> (weight * (time - meanT) * (time - meanT)).toDouble() }.toFloat()
    if (denominator <= 1e-9f) return PetPoint(0f, 0f)
    val slopeX = recent.indices.sumOf { index ->
        (weights[index] * (times[index] - meanT) * (recent[index].position.x - meanX)).toDouble()
    }.toFloat() / denominator
    val slopeY = recent.indices.sumOf { index ->
        (weights[index] * (times[index] - meanT) * (recent[index].position.y - meanY)).toDouble()
    }.toFloat() / denominator
    return PetPoint(slopeX, slopeY)
}

fun estimateDragVelocity(
    samples: Iterable<*>,
    nowMs: Long? = null,
    windowMs: Long = PET_RELEASE_VELOCITY_SAMPLE_WINDOW_MS,
): PetPoint = estimateReleaseVelocity(samples, nowMs, windowMs)

fun estimate_release_velocity(
    samples: Iterable<*>,
    nowMs: Long? = null,
    windowMs: Long = PET_RELEASE_VELOCITY_SAMPLE_WINDOW_MS,
): PetPoint = estimateReleaseVelocity(samples, nowMs, windowMs)

fun estimateDragReleaseVelocity(
    samples: Iterable<*>,
    nowMs: Long? = null,
    windowMs: Long = PET_RELEASE_VELOCITY_SAMPLE_WINDOW_MS,
): PetPoint = estimateReleaseVelocity(samples, nowMs, windowMs)

/**
 * Select the nearest visible target.  Invalid/zero-sized targets are ignored,
 * and ties retain registration order via the stable list iteration.
 */
fun nearestPetTarget(
    position: PetPoint,
    targets: List<PetTarget>,
    halfSize: Float = 0f,
    viewport: PetRect? = null,
): PetTarget? {
    val margin = max(0f, halfSize)
    val viewportCenter = viewport?.let { PetPoint(it.left + it.width / 2f, it.top + it.height / 2f) }
    val edgePenalty = viewport?.let { hypot(it.width, it.height) * PET_EDGE_PENALTY_RATIO } ?: 0f
    val valid = targets.filter { it.valid }
    // Edge targets are presentation hints used to roam a window boundary or
    // reach a portal.  When real content (control/surface/chart) is available,
    // prefer it so a card rebuild can never strand the companion on a thin
    // screen edge rolling in place.
    val content = valid.filter { it.kind != PetTargetKind.EDGE }
    val candidates = if (content.isNotEmpty()) content else valid
    return candidates
        .minWithOrNull(compareBy { target ->
            if (viewport == null || viewportCenter == null) {
                target.distanceTo(position, margin)
            } else {
                val positionSupport = viewport.clamp(closestSupportPoint(target, position, margin), margin)
                val centerSupport = viewport.clamp(closestSupportPoint(target, viewportCenter, margin), margin)
                hypot(position.x - positionSupport.x, position.y - positionSupport.y) +
                    hypot(viewportCenter.x - centerSupport.x, viewportCenter.y - centerSupport.y) * PET_CENTER_BIAS_WEIGHT +
                    if (target.kind == PetTargetKind.EDGE) edgePenalty else 0f
            }
        })
}

fun onNavigation(state: PetState): PetState = state.copy(
    mode = PetMode.FALL,
    targetId = null,
    idleTicksRemaining = 0,
    pathIndex = 0,
    pathDirection = 1,
    rollCorners = 0,
    avoidTargetId = null,
    movementSpeed = 0f,
    verticalVelocity = 0f,
    bouncesRemaining = 0,
    dragOffset = null,
    horizontalVelocity = 0f,
    curveVelocity = null,
)

fun beginDrag(state: PetState, pointer: PetPoint): PetState =
    state.copy(
        mode = PetMode.DRAGGING,
        targetId = null,
        idleTicksRemaining = 0,
        pathIndex = 0,
        pathDirection = 1,
        rollCorners = 0,
        avoidTargetId = null,
        movementSpeed = 0f,
        verticalVelocity = 0f,
        bouncesRemaining = 0,
        dragOffset = PetPoint(pointer.x - state.position.x, pointer.y - state.position.y),
        horizontalVelocity = 0f,
        curveVelocity = null,
    )

fun moveDrag(
    state: PetState,
    pointer: PetPoint,
    viewport: PetRect,
    halfSize: Float,
): PetState = if (state.mode != PetMode.DRAGGING) state else state.copy(
    position = viewport.clamp(
        PetPoint(
            pointer.x - (state.dragOffset?.x ?: 0f),
            pointer.y - (state.dragOffset?.y ?: 0f),
        ),
        max(0f, halfSize),
    ),
    mode = PetMode.DRAGGING,
    targetId = null,
)

fun releaseDrag(
    state: PetState,
    targets: List<PetTarget> = emptyList(),
    viewport: PetRect? = null,
    halfSize: Float = 0f,
    releaseVelocity: PetPoint? = null,
): PetState {
    val flingVelocity = limitFlingVelocity(releaseVelocity ?: PetPoint(0f, 0f))
    if (hypot(flingVelocity.x, flingVelocity.y) >= PET_MINIMUM_FLING_SPEED) {
        // A non-zero release vector takes precedence over support snapping so
        // a throw remains a projectile even when released over a control.
        return state.copy(
            mode = PetMode.FLING,
            targetId = null,
            idleTicksRemaining = 0,
            pathIndex = 0,
            pathDirection = 1,
            rollCorners = 0,
            avoidTargetId = null,
            movementSpeed = 0f,
            verticalVelocity = flingVelocity.y,
            bouncesRemaining = 0,
            dragOffset = null,
            horizontalVelocity = flingVelocity.x,
            curveVelocity = null,
        )
    }
    val support = targets.firstOrNull { target ->
        target.valid && isOnSupport(target, state.position, max(0f, halfSize), viewport)
    }
    if (
        support?.kind == PetTargetKind.CHART &&
        support.path.isNotEmpty() &&
        viewport != null
    ) {
        return chartLandingState(
            state = state,
            target = support,
            contact = state.position,
            incomingVelocity = PetPoint(0f, 0f),
            viewport = viewport,
            halfSize = max(0f, halfSize),
            unitScale = 1f,
        )
    }
    return state.copy(
        mode = if (support == null) PetMode.FALL else PetMode.IDLE,
        targetId = support?.id,
        idleTicksRemaining = if (support == null) 0 else PET_IDLE_TICKS,
        pathIndex = 0,
        pathDirection = 1,
        rollCorners = 0,
        avoidTargetId = null,
        movementSpeed = 0f,
        verticalVelocity = 0f,
        bouncesRemaining = 0,
        dragOffset = null,
        horizontalVelocity = 0f,
        curveVelocity = null,
    )
}

fun advancePet(
    state: PetState,
    targets: List<PetTarget>,
    viewport: PetRect,
    halfSize: Float,
    step: Float = PET_CRUISE_SPEED,
    fallUnitScale: Float = 1f,
): PetState {
    val margin = max(0f, halfSize)
    val unitScale = fallUnitScale.coerceAtLeast(PET_EPSILON)
    if (state.mode == PetMode.DRAGGING) {
        return state.copy(
            position = viewport.clamp(state.position, margin),
            curveVelocity = null,
        )
    }
    val validTargets = targets.filter(PetTarget::valid)
    val retainedTarget = state.targetId?.let { id -> validTargets.firstOrNull { it.id == id } }
    val supportLost = (state.mode == PetMode.BOUNCE && state.targetId == null) || (
        state.targetId != null &&
        state.targetId != PET_VIEWPORT_BOTTOM_TARGET_ID &&
        (retainedTarget == null ||
            (state.mode == PetMode.BOUNCE && fallSupportPoint(retainedTarget, state.position, margin, viewport) == null) ||
            (state.mode in setOf(PetMode.IDLE, PetMode.ROLL, PetMode.SLIDE) &&
                !isOnSupport(retainedTarget, state.position, margin, viewport, PET_SUPPORT_CONTACT_TOLERANCE * unitScale)))
        )
    val currentState = if (supportLost) {
        val airborne = state.mode == PetMode.FALL || state.mode == PetMode.FLING || state.mode == PetMode.BOUNCE
        state.copy(
            mode = when (state.mode) {
                PetMode.BOUNCE -> PetMode.FLING
                PetMode.FLING -> PetMode.FLING
                else -> PetMode.FALL
            },
            targetId = null,
            idleTicksRemaining = 0,
            pathIndex = 0,
            pathDirection = 1,
            rollCorners = 0,
            avoidTargetId = null,
            movementSpeed = 0f,
            verticalVelocity = if (airborne) state.verticalVelocity else 0f,
            horizontalVelocity = if (airborne) state.horizontalVelocity else 0f,
            bouncesRemaining = 0,
            curveVelocity = null,
        )
    } else {
        state
    }
    if (currentState.mode != PetMode.FALL && currentState.idleTicksRemaining > 0) {
        return currentState.copy(
            idleTicksRemaining = currentState.idleTicksRemaining - 1,
            movementSpeed = (currentState.movementSpeed - PET_MOTION_ACCELERATION).coerceAtLeast(0f),
            horizontalVelocity = 0f,
            curveVelocity = null,
        )
    }
    // Fling is a self-contained projectile state. It must be advanced before
    // selecting an idle support so upward throws are not snapped to a nearby
    // surface while they are still on the rising arc.
    if (currentState.mode == PetMode.FLING) {
        return advanceFling(currentState, validTargets, viewport, margin, unitScale)
    }
    if (currentState.mode == PetMode.BOUNCE && currentState.targetId == PET_VIEWPORT_BOTTOM_TARGET_ID) {
        return advanceViewportBottomBounce(currentState, viewport, margin, unitScale)
    }
    if (validTargets.isEmpty()) {
        return if (currentState.mode == PetMode.FALL) {
            advanceFreeFall(currentState, viewport, margin, unitScale)
        } else currentState.copy(
            position = viewport.clamp(currentState.position, margin),
            mode = PetMode.IDLE,
            targetId = null,
            movementSpeed = 0f,
            verticalVelocity = 0f,
            horizontalVelocity = 0f,
            bouncesRemaining = 0,
            curveVelocity = null,
        )
    }
    val candidates = if (currentState.avoidTargetId != null) {
        validTargets.filter { it.id != currentState.avoidTargetId }.ifEmpty { validTargets }
    } else validTargets
    val target = if (currentState.mode == PetMode.FALL) {
        nearestFallTarget(currentState.position, candidates, margin, viewport)
    } else {
        val retained = currentState.targetId?.let { id -> validTargets.firstOrNull { it.id == id } }
        val contentExists = validTargets.any { it.kind != PetTargetKind.EDGE }
        // A thin edge must never be retained as a long-term support while real
        // content exists: a pet that once landed on a boundary would keep
        // creeping along it forever (visually motionless) and never return to
        // the page content.
        if (retained != null && (currentState.mode == PetMode.BOUNCE || retained.kind != PetTargetKind.EDGE || !contentExists)) {
            retained
        } else {
            nearestPetTarget(
                currentState.position,
                candidates,
                margin,
                viewport,
            )
        }
    }
        ?: return if (currentState.mode == PetMode.FALL) {
            advanceFreeFall(currentState.copy(targetId = null), viewport, margin, unitScale)
        } else {
            currentState.copy(
                position = viewport.clamp(currentState.position, margin),
                mode = PetMode.IDLE,
                targetId = null,
                horizontalVelocity = 0f,
                verticalVelocity = 0f,
                curveVelocity = null,
            )
        }

    if (currentState.mode == PetMode.BOUNCE) {
        return advanceBounce(currentState, target, viewport, margin, unitScale)
    }
    if (currentState.mode == PetMode.FALL) {
        return advanceFall(currentState, target, viewport, margin, unitScale)
    }

    if (target.kind == PetTargetKind.CHART && target.path.isNotEmpty()) {
        return advanceChart(currentState, target, viewport, margin, step, unitScale)
    }

    return advanceSupport(currentState, target, viewport, margin, step)
}

private data class PetMovement(
    val position: PetPoint,
    val arrived: Boolean,
    val speed: Float,
)

private fun advanceSupport(
    state: PetState,
    target: PetTarget,
    viewport: PetRect,
    halfSize: Float,
    maxSpeed: Float,
): PetState {
    val rawEndpoints = supportEndpoints(target, halfSize)
    val endpoints = viewport.clamp(rawEndpoints.first, halfSize) to
        viewport.clamp(rawEndpoints.second, halfSize)
    val currentSupport = closestPointOnSegment(state.position, endpoints.first, endpoints.second)
    val rolling = state.targetId == target.id &&
        distanceSquared(state.position, currentSupport) <= PET_EPSILON * PET_EPSILON
    if (rolling) {
        val direction = if (state.pathDirection < 0) -1 else 1
        val goal = if (direction > 0) endpoints.second else endpoints.first
        val movement = moveSmoothly(state.position, goal, state.movementSpeed, maxSpeed, verticalFirst = false)
        val position = viewport.clamp(movement.position, halfSize)
        val facing = facingAfter(state.facing, position.x - state.position.x)
        if (movement.arrived) {
            val completedEnds = state.rollCorners + 1
            if (completedEnds >= 2) {
                return state.copy(
                    position = position,
                    mode = PetMode.IDLE,
                    targetId = null,
                    idleTicksRemaining = PET_IDLE_TICKS,
                    pathDirection = -direction,
                    rollCorners = 0,
                    avoidTargetId = target.id,
                    movementSpeed = 0f,
                    horizontalVelocity = 0f,
                    verticalVelocity = 0f,
                    curveVelocity = null,
                    facing = facing,
                )
            }
            return state.copy(
                position = position,
                mode = PetMode.ROLL,
                targetId = target.id,
                pathDirection = -direction,
                rollCorners = completedEnds,
                movementSpeed = 0f,
                horizontalVelocity = 0f,
                verticalVelocity = 0f,
                curveVelocity = null,
                facing = facing,
            )
        }
        return state.copy(
            position = position,
            mode = PetMode.ROLL,
            targetId = target.id,
            rollCorners = state.rollCorners,
            movementSpeed = movement.speed,
            horizontalVelocity = 0f,
            verticalVelocity = 0f,
            curveVelocity = null,
            facing = facing,
        )
    }

    val goal = currentSupport
    val movement = moveSmoothly(state.position, goal, state.movementSpeed, maxSpeed, verticalFirst = true)
    val position = viewport.clamp(movement.position, halfSize)
    val facing = facingAfter(state.facing, position.x - state.position.x)
    return if (movement.arrived) {
        state.copy(
            position = position,
            mode = PetMode.IDLE,
            targetId = target.id,
            idleTicksRemaining = PET_IDLE_TICKS,
            pathDirection = 1,
            rollCorners = 0,
            movementSpeed = 0f,
            verticalVelocity = 0f,
            horizontalVelocity = 0f,
            curveVelocity = null,
            facing = facing,
        )
    } else {
        state.copy(
            position = position,
            mode = PetMode.FLY,
            targetId = target.id,
            rollCorners = 0,
            movementSpeed = movement.speed,
            verticalVelocity = 0f,
            horizontalVelocity = 0f,
            curveVelocity = null,
            facing = facing,
        )
    }
}

private data class FlingSubstep(
    val position: PetPoint,
    val horizontalVelocity: Float,
    val verticalVelocity: Float,
)

private fun flingTangentSupportExitTime(
    position: PetPoint,
    horizontalVelocity: Float,
    verticalVelocity: Float,
    target: PetTarget,
    halfSize: Float,
): Float? {
    if (
        !target.valid ||
        target.kind == PetTargetKind.CHART ||
        abs(verticalVelocity) > PET_EPSILON ||
        abs(horizontalVelocity) <= PET_EPSILON
    ) {
        return null
    }
    val endpoints = supportEndpoints(target, halfSize)
    if (!close(endpoints.first.y, endpoints.second.y) || !close(position.y, endpoints.first.y)) {
        return null
    }
    val minX = min(endpoints.first.x, endpoints.second.x)
    val maxX = max(endpoints.first.x, endpoints.second.x)
    if (position.x !in (minX - PET_EPSILON)..(maxX + PET_EPSILON)) return null
    return if (horizontalVelocity > 0f) {
        ((maxX - position.x) / horizontalVelocity).coerceAtLeast(0f)
    } else {
        ((minX - position.x) / horizontalVelocity).coerceAtLeast(0f)
    }
}

/**
 * Advance a fling using deterministic closed-form substeps. Keeping the
 * simulation split into four 4 ms slices avoids visible tunnelling at high
 * release speeds while preserving the same 16 ms constant-acceleration result.
 */
private fun advanceFling(
    state: PetState,
    targets: List<PetTarget>,
    viewport: PetRect,
    halfSize: Float,
    fallUnitScale: Float,
): PetState {
    val requested = kotlin.math.ceil(PET_FALL_TIME_STEP_SECONDS / PET_MAX_SUBSTEP_SECONDS)
        .toInt()
        .coerceAtLeast(1)
    val substeps = requested.coerceAtMost(PET_MAX_SUBSTEPS_PER_TICK)
    val dt = PET_FALL_TIME_STEP_SECONDS / substeps
    var current = state
    repeat(substeps) {
        if (current.mode == PetMode.FLING) {
            current = advanceFlingSubstep(current, targets, viewport, halfSize, fallUnitScale, dt)
        }
    }
    return current
}

private fun advanceFlingSubstep(
    state: PetState,
    targets: List<PetTarget>,
    viewport: PetRect,
    halfSize: Float,
    fallUnitScale: Float,
    dt: Float,
): PetState {
    val gravity = PET_FLING_GRAVITY * fallUnitScale
    var position = state.position
    var vx = state.horizontalVelocity
    var vy = state.verticalVelocity
    var remaining = dt.coerceAtLeast(0f)
    val minX = viewport.left + halfSize
    val maxX = (viewport.right - halfSize).coerceAtLeast(minX)
    val minY = viewport.top + halfSize
    val maxY = (viewport.bottom - halfSize).coerceAtLeast(minY)

    // Integrate piecewise. Every candidate is evaluated from the current
    // contact point and remaining duration, so a wall reflection changes the
    // subsequent support ray instead of retroactively changing the whole tick.
    repeat(8) {
        if (remaining <= PET_EPSILON) return@repeat
        // Starting exactly on a horizontal support with no normal velocity is
        // a constrained tangent contact, not a landing at t=0. Keep y fixed
        // until the pet reaches the support edge (or a wall), then integrate
        // the unused portion of this substep as a projectile.
        val tangentExitTimes = targets.mapNotNull { target ->
            flingTangentSupportExitTime(position, vx, vy, target, halfSize)
        }
        if (tangentExitTimes.isNotEmpty()) {
            val supportExitTime = tangentExitTimes.maxOrNull() ?: 0f
            val wallKind = when {
                vx > PET_EPSILON -> FlingContactKind.RIGHT
                vx < -PET_EPSILON -> FlingContactKind.LEFT
                else -> null
            }
            val wallTime = when (wallKind) {
                FlingContactKind.RIGHT -> ((maxX - position.x) / vx).coerceAtLeast(0f)
                FlingContactKind.LEFT -> ((minX - position.x) / vx).coerceAtLeast(0f)
                else -> Float.POSITIVE_INFINITY
            }
            val travelTime = minOf(remaining, supportExitTime, wallTime)
            position = PetPoint(position.x + vx * travelTime, position.y)
            remaining = (remaining - travelTime).coerceAtLeast(0f)
            if (
                wallKind != null &&
                wallTime <= supportExitTime + PET_EPSILON &&
                wallTime <= travelTime + PET_EPSILON
            ) {
                position = PetPoint(if (wallKind == FlingContactKind.LEFT) minX else maxX, position.y)
                vx = -vx * PET_FLING_HORIZONTAL_RESTITUTION
                position = PetPoint(position.x + vx.signSafe() * PET_EPSILON, position.y)
                return@repeat
            }
            if (supportExitTime <= travelTime + PET_EPSILON) {
                position = PetPoint(position.x + vx.signSafe() * PET_EPSILON * 2f, position.y)
                return@repeat
            }
            return@repeat
        }
        val candidates = mutableListOf<FlingContact>()
        if (vx > PET_EPSILON) {
            val wallTime = (maxX - position.x) / vx
            if (wallTime >= -PET_EPSILON && wallTime <= remaining + PET_EPSILON) {
                candidates += FlingContact(wallTime.coerceAtLeast(0f), FlingContactKind.RIGHT)
            }
        } else if (vx < -PET_EPSILON) {
            val wallTime = (minX - position.x) / vx
            if (wallTime >= -PET_EPSILON && wallTime <= remaining + PET_EPSILON) {
                candidates += FlingContact(wallTime.coerceAtLeast(0f), FlingContactKind.LEFT)
            }
        }
        // Always solve the contact equation, even when the projectile starts
        // with a small upward velocity and turns downward within this slice.
        // The helper filters roots whose impact velocity is still upward.
        earliestFlingSupportHit(
            position.y,
            vy,
            gravity,
            position.x,
            vx,
            remaining,
            targets,
            halfSize,
            viewport,
        )?.let { hit -> candidates += FlingContact(hit.time, FlingContactKind.TARGET, hit) }
        positiveQuadraticRoots(0.5f * gravity, vy, position.y - maxY, remaining)
            .filter { time -> !(time <= PET_EPSILON && vy <= PET_EPSILON) }
            .firstOrNull { time -> vy + gravity * time >= -PET_EPSILON }
            ?.let { time -> candidates += FlingContact(time, FlingContactKind.BOTTOM) }
        if (vy < -PET_EPSILON) {
            positiveQuadraticRoots(0.5f * gravity, vy, position.y - minY, remaining)
                .filter { time -> vy + gravity * time <= PET_EPSILON }
                .firstOrNull()
                ?.let { time -> candidates += FlingContact(time, FlingContactKind.TOP) }
        }

        val contact = candidates.minWithOrNull(compareBy<FlingContact>({ it.time }, { it.kind.priority }))
        if (contact == null) {
            position = PetPoint(
                position.x + vx * remaining,
                position.y + vy * remaining + 0.5f * gravity * remaining * remaining,
            )
            vy += gravity * remaining
            remaining = 0f
            return@repeat
        }

        val elapsed = contact.time.coerceIn(0f, remaining)
        position = PetPoint(
            position.x + vx * elapsed,
            position.y + vy * elapsed + 0.5f * gravity * elapsed * elapsed,
        )
        vy += gravity * elapsed
        remaining = (remaining - elapsed).coerceAtLeast(0f)
        when (contact.kind) {
            FlingContactKind.LEFT, FlingContactKind.RIGHT -> {
                position = PetPoint(if (contact.kind == FlingContactKind.LEFT) minX else maxX, position.y)
                vx = -vx * PET_FLING_HORIZONTAL_RESTITUTION
                if (elapsed <= PET_EPSILON) {
                    // Keep the next wall candidate strictly in the interior.
                    position = PetPoint(position.x + vx.signSafe() * PET_EPSILON, position.y)
                }
            }
            FlingContactKind.TARGET -> {
                val hit = contact.hit ?: return@repeat
                val target = targets.firstOrNull { it.id == hit.targetId } ?: return@repeat
                val landed = landOnTarget(
                    state = state.copy(
                        position = PetPoint(hit.x, hit.y),
                        horizontalVelocity = vx,
                        verticalVelocity = hit.verticalVelocity,
                    ),
                    target = target,
                    position = PetPoint(hit.x, hit.y),
                    incomingVelocity = PetPoint(vx, hit.verticalVelocity),
                    viewport = viewport,
                    halfSize = halfSize,
                    fallUnitScale = fallUnitScale,
                )
                position = landed.position
                return landed
            }
            FlingContactKind.BOTTOM -> {
                val impact = vy.coerceAtLeast(0f)
                val landed = landAtViewportBottom(
                    state.copy(position = PetPoint(position.x, maxY), horizontalVelocity = vx),
                    PetPoint(position.x, maxY),
                    impact,
                    fallUnitScale,
                )
                return landed
            }
            FlingContactKind.TOP -> {
                position = PetPoint(position.x, minY)
                vy = (-vy * 0.5f).coerceAtLeast(0f)
            }
        }
    }
    position = position.copy(x = position.x.coerceIn(minX, maxX))
    if (position.y < minY) {
        position = PetPoint(position.x, minY)
        vy = (-vy).coerceAtLeast(0f) * 0.5f
    }
    return state.copy(
        position = position,
        mode = PetMode.FLING,
        targetId = null,
        movementSpeed = 0f,
        horizontalVelocity = vx,
        verticalVelocity = vy,
        bouncesRemaining = 0,
        curveVelocity = null,
        // Use the post-collision horizontal velocity when available.  A
        // high-speed fling can hit a wall and reverse within one tick, making
        // the net displacement point in the opposite direction of its
        // continuing motion.
        facing = facingAfter(
            state.facing,
            if (abs(vx) > PET_EPSILON) vx else position.x - state.position.x,
        ),
    )
}

private enum class FlingContactKind(val priority: Int) {
    TARGET(0),
    BOTTOM(1),
    TOP(2),
    LEFT(3),
    RIGHT(3),
}

private data class FlingContact(
    val time: Float,
    val kind: FlingContactKind,
    val hit: FlingSupportHit? = null,
)

private data class FlingSupportHit(
    val targetId: String,
    val x: Float,
    val y: Float,
    val verticalVelocity: Float,
    val time: Float,
)

private fun earliestFlingSupportHit(
    y0: Float,
    vy0: Float,
    gravity: Float,
    x0: Float,
    vx: Float,
    dt: Float,
    targets: List<PetTarget>,
    halfSize: Float,
    viewport: PetRect,
): FlingSupportHit? {
    var earliest: FlingSupportHit? = null
    targets.forEach { target ->
        if (!target.valid) return@forEach
        val candidate = when {
            target.kind == PetTargetKind.CHART && target.path.isNotEmpty() -> {
                flingChartHit(target, y0, vy0, gravity, x0, vx, dt, halfSize, viewport)
            }
            else -> {
                val endpoints = supportEndpoints(target, halfSize)
                if (!close(endpoints.first.y, endpoints.second.y)) null
                else flingHorizontalSupportHit(
                    target,
                    endpoints.first.y,
                    min(endpoints.first.x, endpoints.second.x),
                    max(endpoints.first.x, endpoints.second.x),
                    y0,
                    vy0,
                    gravity,
                    x0,
                    vx,
                    dt,
                )
            }
        }
        if (candidate != null && (earliest == null || candidate.time < earliest!!.time)) earliest = candidate
    }
    return earliest
}

private fun flingHorizontalSupportHit(
    target: PetTarget,
    supportY: Float,
    minX: Float,
    maxX: Float,
    y0: Float,
    vy0: Float,
    gravity: Float,
    x0: Float,
    vx: Float,
    dt: Float,
): FlingSupportHit? {
    val roots = positiveQuadraticRoots(0.5f * gravity, vy0, y0 - supportY, dt)
    return roots.asSequence()
        .filter { time -> !(time <= PET_EPSILON && vy0 <= PET_EPSILON) }
        .filter { time -> vy0 + gravity * time >= -PET_EPSILON }
        .map { time -> x0 + vx * time to time }
        .filter { (x, _) -> x in (minX - PET_EPSILON)..(maxX + PET_EPSILON) }
        .map { (x, time) -> FlingSupportHit(target.id, x, supportY, vy0 + gravity * time, time) }
        .minByOrNull(FlingSupportHit::time)
}

private fun flingChartHit(
    target: PetTarget,
    y0: Float,
    vy0: Float,
    gravity: Float,
    x0: Float,
    vx: Float,
    dt: Float,
    halfSize: Float,
    viewport: PetRect,
): FlingSupportHit? {
    val path = target.path.map { PetPoint(it.x, it.y - halfSize) }
    if (path.size == 1) {
        if (!close(x0, path.single().x) || !isInsidePetViewport(path.single(), viewport, halfSize)) return null
        return positiveQuadraticRoots(0.5f * gravity, vy0, y0 - path.single().y, dt)
            .filter { time -> !(time <= PET_EPSILON && vy0 <= PET_EPSILON) }
            .filter { time -> vy0 + gravity * time >= -PET_EPSILON }
            .minOrNull()
            ?.let { time -> FlingSupportHit(target.id, x0, path.single().y, vy0 + gravity * time, time) }
    }
    return path.zipWithNext().mapNotNull { (start, end) ->
        val dx = end.x - start.x
        val minX = min(start.x, end.x) - PET_EPSILON
        val maxX = max(start.x, end.x) + PET_EPSILON
        if (abs(dx) <= PET_EPSILON) return@mapNotNull null
        // x(t) is linear. A linear chart segment turns the collision equation
        // into a quadratic with one additional term from the segment slope.
        val slope = (end.y - start.y) / dx
        val intercept = start.y - slope * start.x
        val a = 0.5f * gravity
        val b = vy0 - slope * vx
        val c = y0 - (slope * x0 + intercept)
        positiveQuadraticRoots(a, b, c, dt)
            .filter { time -> !(time <= PET_EPSILON && b <= PET_EPSILON) }
            // Contact direction is the derivative of the relative curve
            // equation, not world-space vertical velocity. A projectile can
            // move upward while still crossing a steep descending segment.
            .filter { time -> b + 2f * a * time >= -PET_EPSILON }
            .mapNotNull { time ->
                val x = x0 + vx * time
                if (x !in minX..maxX || !isInsidePetViewport(PetPoint(x, slope * x + intercept), viewport, halfSize)) {
                    null
                } else {
                    FlingSupportHit(
                        targetId = target.id,
                        x = x,
                        y = slope * x + intercept,
                        verticalVelocity = vy0 + gravity * time,
                        time = time,
                    )
                }
            }
            .minByOrNull(FlingSupportHit::time)
    }.minByOrNull(FlingSupportHit::time)
}

private fun positiveQuadraticRoots(a: Float, b: Float, c: Float, maxTime: Float): List<Float> {
    if (abs(a) <= PET_EPSILON) {
        if (abs(b) <= PET_EPSILON) return emptyList()
        val root = -c / b
        return listOf(root).filter { it >= -PET_EPSILON && it <= maxTime + PET_EPSILON }
    }
    val discriminant = b * b - 4f * a * c
    if (discriminant < -PET_EPSILON) return emptyList()
    val root = sqrt(discriminant.coerceAtLeast(0f))
    val first = (-b - root) / (2f * a)
    val second = (-b + root) / (2f * a)
    return listOf(first, second)
        .filter { it >= -PET_EPSILON && it <= maxTime + PET_EPSILON }
        .map { it.coerceIn(0f, maxTime) }
        .distinct()
        .sorted()
}

private fun Float.signSafe(): Float = when {
    this < 0f -> -1f
    this > 0f -> 1f
    else -> 0f
}

private data class PetPathSegmentContact(
    val index: Int,
    val projection: PetPoint,
    val unitTangent: PetPoint,
)

private fun closestPathSegment(
    position: PetPoint,
    path: List<PetPoint>,
    preferredIndex: Int? = null,
): PetPathSegmentContact {
    var closest: PetPathSegmentContact? = null
    var closestDistance = Float.POSITIVE_INFINITY
    path.zipWithNext().forEachIndexed { index, (start, end) ->
        val dx = end.x - start.x
        val dy = end.y - start.y
        val length = hypot(dx, dy)
        if (length <= PET_EPSILON) return@forEachIndexed
        val projection = closestPointOnSegment(position, start, end)
        val distance = hypot(position.x - projection.x, position.y - projection.y)
        if (distance < closestDistance - PET_CURVE_DIRECTION_EPSILON ||
            (abs(distance - closestDistance) <= PET_CURVE_DIRECTION_EPSILON && index == preferredIndex)
        ) {
            closestDistance = distance
            closest = PetPathSegmentContact(
                index = index,
                projection = projection,
                unitTangent = PetPoint(dx / length, dy / length),
            )
        }
    }
    return closest ?: PetPathSegmentContact(
        index = 0,
        projection = path.firstOrNull() ?: position,
        unitTangent = PetPoint(1f, 0f),
    )
}

private fun curveDownhillDirection(unitTangent: PetPoint): Int = when {
    unitTangent.y > PET_CURVE_DIRECTION_EPSILON -> 1
    unitTangent.y < -PET_CURVE_DIRECTION_EPSILON -> -1
    else -> 1
}

private fun curveEndpointIsDownhill(
    path: List<PetPoint>,
    endpoint: Int,
    direction: Int,
): Boolean {
    val segment = (if (direction > 0) endpoint - 1 else endpoint).coerceIn(0, path.lastIndex - 1)
    val start = path[segment]
    val end = path[segment + 1]
    val dx = end.x - start.x
    val dy = end.y - start.y
    val length = hypot(dx, dy)
    val unitTangent = if (length > PET_CURVE_DIRECTION_EPSILON) {
        PetPoint(dx / length, dy / length)
    } else {
        PetPoint(1f, 0f)
    }
    val canonicalDirection = if (direction < 0) -1 else 1
    return canonicalDirection == curveDownhillDirection(unitTangent)
}

private fun chartLandingState(
    state: PetState,
    target: PetTarget,
    contact: PetPoint,
    incomingVelocity: PetPoint,
    viewport: PetRect,
    halfSize: Float,
    unitScale: Float,
): PetState {
    val path = target.path.map { PetPoint(it.x, it.y - halfSize) }
    if (path.size < 2) {
        return state.copy(
            position = viewport.clamp(contact, halfSize),
            mode = PetMode.IDLE,
            targetId = target.id,
            idleTicksRemaining = PET_IDLE_TICKS,
            movementSpeed = 0f,
            verticalVelocity = 0f,
            horizontalVelocity = 0f,
            curveVelocity = null,
        )
    }

    val segment = closestPathSegment(contact, path)
    val rawProjectedVelocity = (
        incomingVelocity.x * segment.unitTangent.x +
            incomingVelocity.y * segment.unitTangent.y
        ) * PET_FALL_TIME_STEP_SECONDS / unitScale
    val projectedVelocity = rawProjectedVelocity.takeIf(Float::isFinite) ?: 0f
    val clampedCurveVelocity = projectedVelocity.coerceIn(
        -PET_CURVE_LANDING_SPEED_LIMIT,
        PET_CURVE_LANDING_SPEED_LIMIT,
    )
    val curveVelocity = clampedCurveVelocity.takeUnless {
        abs(it) <= PET_CURVE_DIRECTION_EPSILON
    } ?: 0f
    val direction = when {
        curveVelocity > PET_CURVE_DIRECTION_EPSILON -> 1
        curveVelocity < -PET_CURVE_DIRECTION_EPSILON -> -1
        else -> curveDownhillDirection(segment.unitTangent)
    }
    return state.copy(
        position = viewport.clamp(segment.projection, halfSize),
        mode = PetMode.SLIDE,
        targetId = target.id,
        idleTicksRemaining = 0,
        pathIndex = if (direction > 0) segment.index + 1 else segment.index,
        pathDirection = direction,
        rollCorners = 0,
        avoidTargetId = null,
        movementSpeed = abs(curveVelocity) * unitScale,
        verticalVelocity = 0f,
        bouncesRemaining = 0,
        horizontalVelocity = 0f,
        curveVelocity = curveVelocity,
        dragOffset = null,
    )
}

private data class PetPathMotion(
    val position: PetPoint,
    val index: Int,
    val reachedEndpoint: Boolean,
    val remainingBudget: Float,
)

private fun moveAlongPath(
    start: PetPoint,
    path: List<PetPoint>,
    index: Int,
    direction: Int,
    distance: Float,
    viewport: PetRect,
    halfSize: Float,
): PetPathMotion {
    val canonicalDirection = if (direction < 0) -1 else 1
    val endpoint = if (canonicalDirection > 0) path.lastIndex else 0
    var cursor = index.coerceIn(0, path.lastIndex)
    var position = start
    var remaining = distance.coerceAtLeast(0f)
    while (true) {
        val goal = path[cursor]
        val segmentDistance = hypot(goal.x - position.x, goal.y - position.y)
        val proposed = if (segmentDistance > remaining + PET_EPSILON) {
            val ratio = remaining / segmentDistance
            PetPoint(position.x + (goal.x - position.x) * ratio, position.y + (goal.y - position.y) * ratio)
        } else goal
        if (!isInsidePetViewport(proposed, viewport, halfSize)) {
            // Intersect the travelled segment with the viewport; clamping its
            // two coordinates separately would move the pet off the curve.
            val minimum = viewport.clamp(PetPoint(viewport.left, viewport.top), halfSize)
            val maximum = viewport.clamp(PetPoint(viewport.right, viewport.bottom), halfSize)
            var fraction = 1f
            val dx = proposed.x - position.x
            val dy = proposed.y - position.y
            if (dx > PET_CURVE_DIRECTION_EPSILON) fraction = min(fraction, (maximum.x - position.x) / dx)
            else if (dx < -PET_CURVE_DIRECTION_EPSILON) fraction = min(fraction, (minimum.x - position.x) / dx)
            if (dy > PET_CURVE_DIRECTION_EPSILON) fraction = min(fraction, (maximum.y - position.y) / dy)
            else if (dy < -PET_CURVE_DIRECTION_EPSILON) fraction = min(fraction, (minimum.y - position.y) / dy)
            fraction = fraction.coerceAtLeast(0f)
            return PetPathMotion(
                PetPoint(position.x + dx * fraction, position.y + dy * fraction), cursor, true, 0f,
            )
        }
        if (segmentDistance > remaining + PET_EPSILON) {
            return PetPathMotion(
                position = proposed,
                index = cursor,
                reachedEndpoint = false,
                remainingBudget = 0f,
            )
        }
        position = goal
        remaining = (remaining - segmentDistance).coerceAtLeast(0f)
        if (cursor == endpoint) {
            return PetPathMotion(position, cursor, true, remaining)
        }
        cursor += canonicalDirection
        if (remaining <= PET_EPSILON) {
            return PetPathMotion(position, cursor, false, 0f)
        }
    }
}

private fun advanceLandedChart(
    state: PetState,
    target: PetTarget,
    path: List<PetPoint>,
    viewport: PetRect,
    halfSize: Float,
    unitScale: Float,
): PetState {
    val nearCorner = (1 until path.lastIndex).any { index ->
        distanceSquared(state.position, path[index]) <= (PET_CURVE_CORNER_RADIUS * unitScale).pow(2)
    }
    val substeps = if (nearCorner) PET_CURVE_CORNER_SUBSTEPS else 1
    var current = state
    repeat(substeps) {
        if (current.mode != PetMode.SLIDE || current.curveVelocity == null || current.targetId != target.id) return current
        current = advanceLandedChartSubstep(current, target, path, viewport, halfSize, unitScale, 1f / substeps)
    }
    return current
}

private fun advanceLandedChartSubstep(
    state: PetState,
    target: PetTarget,
    path: List<PetPoint>,
    viewport: PetRect,
    halfSize: Float,
    unitScale: Float,
    tickFraction: Float,
): PetState {
    val currentVelocity = ((state.curveVelocity ?: 0f).takeIf(Float::isFinite) ?: 0f).coerceIn(
        -PET_CURVE_LANDING_SPEED_LIMIT,
        PET_CURVE_LANDING_SPEED_LIMIT,
    )
    // A shallow numerical crossing at the bottom of a valley must settle
    // instead of alternating between opposing segment tangents each tick.
    val restPoint = if (abs(currentVelocity) <= PET_CURVE_VALLEY_REST_SPEED) {
        (1 until path.lastIndex).firstOrNull { index ->
            val point = path[index]
            val incomingLength = hypot(point.x - path[index - 1].x, point.y - path[index - 1].y)
            val outgoingLength = hypot(point.x - path[index + 1].x, point.y - path[index + 1].y)
            incomingLength > PET_CURVE_DIRECTION_EPSILON && outgoingLength > PET_CURVE_DIRECTION_EPSILON &&
                (point.y - path[index - 1].y) / incomingLength > PET_CURVE_DIRECTION_EPSILON &&
                (point.y - path[index + 1].y) / outgoingLength > PET_CURVE_DIRECTION_EPSILON &&
                distanceSquared(state.position, point) <=
                (PET_SUPPORT_CONTACT_TOLERANCE * unitScale).pow(2)
        }
    } else null
    if (restPoint != null) {
        return state.copy(
            position = path[restPoint],
            mode = PetMode.SLIDE,
            targetId = target.id,
            idleTicksRemaining = 0,
            movementSpeed = 0f,
            verticalVelocity = 0f,
            horizontalVelocity = 0f,
            curveVelocity = 0f,
        )
    }
    val preferredIndex = if (state.pathDirection < 0) state.pathIndex else state.pathIndex - 1
    val segment = closestPathSegment(state.position, path, preferredIndex)
    val downhill = curveDownhillDirection(segment.unitTangent)
    val terminalVelocity = if (abs(segment.unitTangent.y) <= PET_CURVE_DIRECTION_EPSILON) 0f
    else segment.unitTangent.y * PET_CURVE_DOWNHILL_TERMINAL_SPEED
    val response = 1f - (1f - PET_CURVE_DOWNHILL_RESPONSE_PER_TICK).pow(tickFraction)
    val acceleratedVelocity = currentVelocity + (terminalVelocity - currentVelocity) * response
    val curveVelocity = if (abs(terminalVelocity - acceleratedVelocity) <= PET_CURVE_DIRECTION_EPSILON) {
        terminalVelocity
    } else acceleratedVelocity
    val direction = when {
        curveVelocity > PET_CURVE_DIRECTION_EPSILON -> 1
        curveVelocity < -PET_CURVE_DIRECTION_EPSILON -> -1
        else -> downhill
    }
    val waypoint = if (direction > 0) segment.index + 1 else segment.index
    val start = if (distanceSquared(state.position, segment.projection) <= PET_EPSILON * PET_EPSILON) {
        segment.projection
    } else {
        state.position
    }
    val motion = moveAlongPath(
        start,
        path,
        waypoint,
        direction,
        abs(curveVelocity) * unitScale * tickFraction,
        viewport,
        halfSize,
    )
    val position = viewport.clamp(motion.position, halfSize)
    val facing = facingAfter(state.facing, position.x - state.position.x)
    if (motion.reachedEndpoint) {
        val endpoint = motion.index
        if (curveEndpointIsDownhill(path, endpoint, direction)) {
            return state.copy(
                position = position,
                mode = PetMode.IDLE,
                targetId = null,
                idleTicksRemaining = PET_IDLE_TICKS,
                pathIndex = 0,
                pathDirection = 1,
                rollCorners = 0,
                avoidTargetId = target.id,
                movementSpeed = 0f,
                verticalVelocity = 0f,
                horizontalVelocity = 0f,
                curveVelocity = null,
                facing = facing,
            )
        }
        val reverse = -direction
        return state.copy(
            position = position,
            mode = PetMode.SLIDE,
            targetId = target.id,
            idleTicksRemaining = 0,
            pathIndex = endpoint + reverse,
            pathDirection = reverse,
            rollCorners = 0,
            movementSpeed = 0f,
            verticalVelocity = 0f,
            horizontalVelocity = 0f,
            curveVelocity = 0f,
            facing = facing,
        )
    }
    return state.copy(
        position = position,
        mode = PetMode.SLIDE,
        targetId = target.id,
        idleTicksRemaining = 0,
        pathIndex = motion.index,
        pathDirection = direction,
        movementSpeed = abs(curveVelocity) * unitScale,
        verticalVelocity = 0f,
        horizontalVelocity = 0f,
        curveVelocity = curveVelocity,
        facing = facing,
    )
}

private fun advanceFall(
    state: PetState,
    target: PetTarget,
    viewport: PetRect,
    halfSize: Float,
    fallUnitScale: Float,
): PetState {
    val rawGoal = fallSupportPoint(target, state.position, halfSize, viewport)
        ?: return advanceFreeFall(state.copy(targetId = null), viewport, halfSize, fallUnitScale)
    val goal = viewport.clamp(rawGoal, halfSize)
    if (goal.y < state.position.y - PET_EPSILON) {
        return advanceFreeFall(state.copy(targetId = null), viewport, halfSize, fallUnitScale)
    }
    if (close(state.position.y, goal.y)) {
        if (close(state.position.x, goal.x)) {
            val impactVelocity = abs(state.verticalVelocity)
            return landOnTarget(
                state = state,
                target = target,
                position = viewport.clamp(goal, halfSize),
                incomingVelocity = PetPoint(0f, impactVelocity),
                viewport = viewport,
                halfSize = halfSize,
                fallUnitScale = fallUnitScale,
            )
        }
        return advanceFreeFall(state.copy(targetId = null), viewport, halfSize, fallUnitScale)
    }

    // A top-portal entry may carry an upward velocity while its centre is
    // still outside the viewport. Preserve that arc only in this outside
    // state; ordinary in-viewport FALL remains strictly downward.
    val fall = nextFallStep(
        state.verticalVelocity,
        fallUnitScale,
        allowUpward = state.position.y < viewport.top - PET_EPSILON,
    )
    val nextY = (state.position.y + fall.distance).coerceAtMost(goal.y)
    val position = fallPosition(state.position.x, nextY, viewport, halfSize)
    if (close(nextY, goal.y) && close(state.position.x, goal.x)) {
        val impactVelocity = fallImpactVelocity(
            state.verticalVelocity,
            goal.y - state.position.y,
            fallUnitScale,
        )
        return landOnTarget(
            state = state,
            target = target,
            position = position,
            incomingVelocity = PetPoint(0f, impactVelocity),
            viewport = viewport,
            halfSize = halfSize,
            fallUnitScale = fallUnitScale,
        )
    }
    return state.copy(
        position = position,
        mode = PetMode.FALL,
        targetId = target.id,
        movementSpeed = 0f,
        verticalVelocity = fall.velocity,
        curveVelocity = null,
    )
}

private data class PetFallStep(val distance: Float, val velocity: Float)

private fun nextFallStep(
    verticalVelocity: Float,
    fallUnitScale: Float,
    allowUpward: Boolean = false,
): PetFallStep {
    val initialVelocity = if (allowUpward) verticalVelocity else verticalVelocity.coerceAtLeast(0f)
    val scaledGravity = PET_FALL_GRAVITY * fallUnitScale
    val finalVelocity = initialVelocity + scaledGravity * PET_FALL_TIME_STEP_SECONDS
    return PetFallStep(
        distance = initialVelocity * PET_FALL_TIME_STEP_SECONDS +
            0.5f * scaledGravity * PET_FALL_TIME_STEP_SECONDS * PET_FALL_TIME_STEP_SECONDS,
        velocity = finalVelocity,
    )
}

private fun fallImpactVelocity(
    verticalVelocity: Float,
    distance: Float,
    fallUnitScale: Float,
): Float {
    // Energy at contact is based on the signed incoming velocity. Squaring
    // preserves the correct impact speed after an upward portal arc.
    val initialVelocity = verticalVelocity
    val scaledGravity = PET_FALL_GRAVITY * fallUnitScale
    return sqrt(
        (initialVelocity * initialVelocity + 2f * scaledGravity * distance.coerceAtLeast(0f))
            .coerceAtLeast(0f),
    )
}

private fun advanceFreeFall(
    state: PetState,
    viewport: PetRect,
    halfSize: Float,
    fallUnitScale: Float,
): PetState {
    val bottom = viewport.clamp(PetPoint(state.position.x, viewport.bottom), halfSize)
    if (state.position.y >= bottom.y - PET_EPSILON) {
        return landAtViewportBottom(state, bottom, state.verticalVelocity, fallUnitScale)
    }
    val fall = nextFallStep(
        state.verticalVelocity,
        fallUnitScale,
        allowUpward = state.position.y < viewport.top - PET_EPSILON,
    )
    val nextY = (state.position.y + fall.distance).coerceAtMost(bottom.y)
    if (close(nextY, bottom.y)) {
        val impactVelocity = fallImpactVelocity(
            state.verticalVelocity,
            bottom.y - state.position.y,
            fallUnitScale,
        )
        return landAtViewportBottom(state, bottom, impactVelocity, fallUnitScale)
    }
    return state.copy(
        position = fallPosition(bottom.x, nextY, viewport, halfSize),
        mode = PetMode.FALL,
        targetId = null,
        movementSpeed = 0f,
        verticalVelocity = fall.velocity,
        bouncesRemaining = 0,
        curveVelocity = null,
    )
}

/**
 * Keep a portal-entering centre above the top edge until it actually crosses
 * the viewport.  `PetRect.clamp` is intentionally not used for y in that
 * interval because it would teleport a top-entry sprite to `top + halfSize`
 * on its first tick.  Once inside, normal viewport clamping resumes.
 */
private fun fallPosition(
    x: Float,
    y: Float,
    viewport: PetRect,
    halfSize: Float,
): PetPoint {
    val clampedX = viewport.clamp(PetPoint(x, viewport.top + halfSize), halfSize).x
    val firstVisibleY = viewport.top + halfSize
    val clampedY = if (y < firstVisibleY - PET_EPSILON) {
        y
    } else {
        viewport.clamp(PetPoint(clampedX, y), halfSize).y
    }
    return PetPoint(clampedX, clampedY)
}

private fun landAtViewportBottom(
    state: PetState,
    position: PetPoint,
    impactVelocity: Float,
    fallUnitScale: Float,
): PetState = if (impactVelocity >= PET_HARD_LANDING_SPEED * fallUnitScale) {
    state.copy(
        position = position,
        mode = PetMode.BOUNCE,
        targetId = PET_VIEWPORT_BOTTOM_TARGET_ID,
        idleTicksRemaining = 0,
        movementSpeed = 0f,
        verticalVelocity = -PET_FIRST_BOUNCE_SPEED * fallUnitScale,
        bouncesRemaining = PET_BOUNCE_COUNT,
        horizontalVelocity = 0f,
        curveVelocity = null,
    )
} else {
    state.copy(
        position = position,
        mode = PetMode.IDLE,
        targetId = null,
        idleTicksRemaining = PET_IDLE_TICKS,
        movementSpeed = 0f,
        verticalVelocity = 0f,
        bouncesRemaining = 0,
        horizontalVelocity = 0f,
        curveVelocity = null,
    )
}

private fun landOnTarget(
    state: PetState,
    target: PetTarget,
    position: PetPoint,
    incomingVelocity: PetPoint,
    viewport: PetRect,
    halfSize: Float,
    fallUnitScale: Float,
): PetState {
    val impactVelocity = abs(incomingVelocity.y)
    if (impactVelocity >= PET_HARD_LANDING_SPEED * fallUnitScale) {
        return landedState(state, target.id, position, impactVelocity, fallUnitScale)
    }
    if (target.kind == PetTargetKind.CHART && target.path.isNotEmpty()) {
        return chartLandingState(
            state = state,
            target = target,
            contact = position,
            incomingVelocity = incomingVelocity,
            viewport = viewport,
            halfSize = halfSize,
            unitScale = fallUnitScale,
        )
    }
    return landedState(state, target.id, position, impactVelocity, fallUnitScale)
}

private fun landedState(
    state: PetState,
    targetId: String,
    position: PetPoint,
    impactVelocity: Float,
    fallUnitScale: Float,
): PetState = if (impactVelocity >= PET_HARD_LANDING_SPEED * fallUnitScale) {
    state.copy(
        position = position,
        mode = PetMode.BOUNCE,
        targetId = targetId,
        idleTicksRemaining = 0,
        movementSpeed = 0f,
        verticalVelocity = -PET_FIRST_BOUNCE_SPEED * fallUnitScale,
        bouncesRemaining = PET_BOUNCE_COUNT,
        horizontalVelocity = 0f,
        curveVelocity = null,
    )
} else {
    state.copy(
        position = position,
        mode = PetMode.IDLE,
        targetId = targetId,
        idleTicksRemaining = PET_IDLE_TICKS,
        movementSpeed = 0f,
        verticalVelocity = 0f,
        bouncesRemaining = 0,
        horizontalVelocity = 0f,
        curveVelocity = null,
    )
}

private fun advanceBounce(
    state: PetState,
    target: PetTarget,
    viewport: PetRect,
    halfSize: Float,
    fallUnitScale: Float,
): PetState {
    val rawLanding = fallSupportPoint(target, state.position, halfSize, viewport)
        ?: return advanceFling(
            state.copy(mode = PetMode.FLING, targetId = null, bouncesRemaining = 0),
            listOf(target), viewport, halfSize, fallUnitScale,
        )
    val landing = viewport.clamp(rawLanding, halfSize)
    val bounced = advanceBounceAt(
        state = state,
        landing = landing,
        bounceTargetId = target.id,
        restingTargetId = target.id,
        viewport = viewport,
        halfSize = halfSize,
        fallUnitScale = fallUnitScale,
    )
    return if (bounced.mode == PetMode.IDLE && target.kind == PetTargetKind.CHART && target.path.isNotEmpty()) {
        chartLandingState(bounced, target, bounced.position, PetPoint(0f, 0f), viewport, halfSize, fallUnitScale)
    } else bounced
}

private fun advanceViewportBottomBounce(
    state: PetState,
    viewport: PetRect,
    halfSize: Float,
    fallUnitScale: Float,
): PetState = advanceBounceAt(
    state = state,
    landing = viewport.clamp(PetPoint(state.position.x, viewport.bottom), halfSize),
    bounceTargetId = PET_VIEWPORT_BOTTOM_TARGET_ID,
    restingTargetId = null,
    viewport = viewport,
    halfSize = halfSize,
    fallUnitScale = fallUnitScale,
)

private fun advanceBounceAt(
    state: PetState,
    landing: PetPoint,
    bounceTargetId: String,
    restingTargetId: String?,
    viewport: PetRect,
    halfSize: Float,
    fallUnitScale: Float,
): PetState {
    val initialVelocity = state.verticalVelocity
    val scaledGravity = PET_FALL_GRAVITY * fallUnitScale
    val velocity = initialVelocity + scaledGravity * PET_FALL_TIME_STEP_SECONDS
    val rawY = state.position.y + initialVelocity * PET_FALL_TIME_STEP_SECONDS +
        0.5f * scaledGravity * PET_FALL_TIME_STEP_SECONDS * PET_FALL_TIME_STEP_SECONDS
    if (velocity >= 0f && rawY >= landing.y) {
        val landedPosition = viewport.clamp(PetPoint(state.position.x, landing.y), halfSize)
        if (state.bouncesRemaining <= 1) {
            return state.copy(
                position = landedPosition,
                mode = PetMode.IDLE,
                targetId = restingTargetId,
                idleTicksRemaining = PET_IDLE_TICKS,
                movementSpeed = 0f,
                verticalVelocity = 0f,
                bouncesRemaining = 0,
                horizontalVelocity = 0f,
                curveVelocity = null,
            )
        }
        val completedBounce = PET_BOUNCE_COUNT - state.bouncesRemaining + 1
        val reboundSpeed = PET_FIRST_BOUNCE_SPEED * fallUnitScale * PET_BOUNCE_DECAY.pow(completedBounce)
        return state.copy(
            position = landedPosition,
            mode = PetMode.BOUNCE,
            targetId = bounceTargetId,
            movementSpeed = 0f,
            verticalVelocity = -reboundSpeed,
            bouncesRemaining = state.bouncesRemaining - 1,
            horizontalVelocity = 0f,
            curveVelocity = null,
        )
    }
    return state.copy(
        position = viewport.clamp(PetPoint(state.position.x, rawY), halfSize),
        mode = PetMode.BOUNCE,
        targetId = bounceTargetId,
        movementSpeed = 0f,
        verticalVelocity = velocity,
        horizontalVelocity = 0f,
        curveVelocity = null,
    )
}

private fun advanceChart(
    state: PetState,
    target: PetTarget,
    viewport: PetRect,
    halfSize: Float,
    maxSpeed: Float,
    unitScale: Float,
): PetState {
    val curveAcceleration = PET_CURVE_ACCELERATION
    val path = target.path.map { PetPoint(it.x, it.y - halfSize) }
    if (state.curveVelocity != null && path.size > 1) {
        return advanceLandedChart(state, target, path, viewport, halfSize, unitScale)
    }
    if (path.size == 1) {
        val movement = moveSmoothly(
            state.position,
            path.single(),
            state.movementSpeed,
            maxSpeed,
            verticalFirst = true,
            acceleration = curveAcceleration,
        )
        val position = viewport.clamp(movement.position, halfSize)
        return state.copy(
            position = position,
            mode = if (movement.arrived) PetMode.IDLE else PetMode.FLY,
            targetId = target.id,
            idleTicksRemaining = if (movement.arrived) PET_IDLE_TICKS else 0,
            movementSpeed = if (movement.arrived) 0f else movement.speed,
            horizontalVelocity = 0f,
            verticalVelocity = 0f,
            curveVelocity = null,
            facing = facingAfter(state.facing, position.x - state.position.x),
        )
    }

    val sameTarget = state.targetId == target.id && state.mode == PetMode.SLIDE
    var direction = if (sameTarget && state.pathDirection < 0) -1 else 1
    var waypoint = if (sameTarget) {
        state.pathIndex.coerceIn(0, path.lastIndex)
    } else {
        val segment = closestPathSegment(state.position, path)
        if (distanceSquared(state.position, segment.projection) <= PET_EPSILON * PET_EPSILON) {
            direction = curveDownhillDirection(segment.unitTangent)
            if (direction > 0) segment.index + 1 else segment.index
        } else {
            nearestPathIndex(state.position, path)
        }
    }
    if (!sameTarget && closePoint(state.position, path[waypoint])) {
        if (waypoint == path.lastIndex) {
            direction = -1
            waypoint -= 1
        } else if (waypoint == 0) {
            direction = 1
            waypoint += 1
        }
    }

    val currentSpeed = state.movementSpeed.coerceAtLeast(0f)
    val remainingToEndpoint = pathDistanceToEndpoint(state.position, path, waypoint, direction)
    val stoppingDistance = currentSpeed * currentSpeed / (2f * curveAcceleration)
    val speed = if (currentSpeed > 0f && remainingToEndpoint <= stoppingDistance) {
        (currentSpeed - curveAcceleration).coerceAtLeast(curveAcceleration)
    } else {
        (currentSpeed + curveAcceleration).coerceAtMost(max(curveAcceleration, maxSpeed))
    }
    var motion = moveAlongPath(state.position, path, waypoint, direction, speed, viewport, halfSize)
    var position = motion.position
    waypoint = motion.index
    var completedCycle = false
    var completedEnds = if (sameTarget) state.rollCorners else 0
    if (motion.reachedEndpoint) {
        completedEnds += 1
        completedCycle = completedEnds >= 2
        if (!completedCycle) {
            direction *= -1
            waypoint = (waypoint + direction).coerceIn(0, path.lastIndex)
            if (motion.remainingBudget > PET_EPSILON) {
                motion = moveAlongPath(position, path, waypoint, direction, motion.remainingBudget, viewport, halfSize)
                position = motion.position
                waypoint = motion.index
                if (motion.reachedEndpoint) {
                    direction *= -1
                    waypoint = (waypoint + direction).coerceIn(0, path.lastIndex)
                }
            }
        }
    }
    position = viewport.clamp(position, halfSize)
    val facing = facingAfter(state.facing, position.x - state.position.x)
    return if (completedCycle) {
        state.copy(
            position = position,
            mode = PetMode.IDLE,
            targetId = null,
            idleTicksRemaining = PET_IDLE_TICKS,
            pathIndex = 0,
            pathDirection = 1,
            rollCorners = 0,
            avoidTargetId = target.id,
            movementSpeed = 0f,
            horizontalVelocity = 0f,
            verticalVelocity = 0f,
            curveVelocity = null,
            facing = facing,
        )
    } else {
        state.copy(
            position = position,
            mode = if (isOnSupport(target, position, halfSize, viewport, PET_SUPPORT_CONTACT_TOLERANCE * unitScale)) PetMode.SLIDE else PetMode.FLY,
            targetId = target.id,
            pathIndex = waypoint,
            pathDirection = direction,
            rollCorners = completedEnds,
            movementSpeed = speed,
            verticalVelocity = 0f,
            horizontalVelocity = 0f,
            curveVelocity = null,
            facing = facing,
        )
    }
}

private fun pathDistanceToEndpoint(
    position: PetPoint,
    path: List<PetPoint>,
    waypoint: Int,
    direction: Int,
): Float {
    if (path.isEmpty()) return 0f
    var cursor = waypoint.coerceIn(0, path.lastIndex)
    var distance = hypot(path[cursor].x - position.x, path[cursor].y - position.y)
    val endpoint = if (direction < 0) 0 else path.lastIndex
    while (cursor != endpoint) {
        val next = cursor + if (direction < 0) -1 else 1
        distance += hypot(path[next].x - path[cursor].x, path[next].y - path[cursor].y)
        cursor = next
    }
    return distance
}

private fun moveSmoothly(
    position: PetPoint,
    goal: PetPoint,
    currentSpeed: Float,
    maxSpeed: Float,
    verticalFirst: Boolean,
    acceleration: Float = PET_MOTION_ACCELERATION,
): PetMovement {
    val verticalPending = verticalFirst && !close(position.y, goal.y)
    val dx = if (verticalPending) 0f else goal.x - position.x
    val dy = if (verticalPending) goal.y - position.y else if (verticalFirst) 0f else goal.y - position.y
    val remaining = hypot(dx, dy)
    if (remaining <= PET_EPSILON) {
        return PetMovement(
            PetPoint(if (verticalPending) position.x else goal.x, if (verticalPending) goal.y else position.y),
            close(position.x, goal.x) && close(position.y, goal.y),
            0f,
        )
    }
    val accelerationStep = acceleration.coerceAtLeast(PET_EPSILON)
    val speedLimit = max(accelerationStep, maxSpeed)
    val safeCurrent = currentSpeed.coerceAtLeast(0f)
    val stoppingDistance = safeCurrent * safeCurrent / (2f * accelerationStep)
    val speed = if (safeCurrent > 0f && remaining <= stoppingDistance) {
        (safeCurrent - accelerationStep).coerceAtLeast(accelerationStep)
    } else {
        (safeCurrent + accelerationStep).coerceAtMost(speedLimit)
    }
    if (remaining <= speed) {
        val next = PetPoint(
            if (verticalPending) position.x else goal.x,
            if (verticalPending) goal.y else goal.y,
        )
        return PetMovement(next, close(next.x, goal.x) && close(next.y, goal.y), speed)
    }
    val ratio = speed / remaining
    val next = PetPoint(position.x + dx * ratio, position.y + dy * ratio)
    return PetMovement(next, false, speed)
}

private fun closestSupportPoint(target: PetTarget, position: PetPoint, halfSize: Float): PetPoint {
    if (target.kind == PetTargetKind.CHART && target.path.isNotEmpty()) {
        val path = target.path.map { PetPoint(it.x, it.y - halfSize) }
        if (path.size == 1) return path.first()
        return path
            .zipWithNext()
            .asSequence()
            .map { (start, end) -> closestPointOnSegment(position, start, end) }
            .minByOrNull { distanceSquared(position, it) }
            ?: position
    }
    val endpoints = supportEndpoints(target, halfSize)
    return closestPointOnSegment(position, endpoints.first, endpoints.second)
}

private fun isInsidePetViewport(position: PetPoint, viewport: PetRect, halfSize: Float): Boolean =
    distanceSquared(position, viewport.clamp(position, halfSize)) <= PET_EPSILON * PET_EPSILON

private fun fallSupportPoint(target: PetTarget, position: PetPoint, halfSize: Float, viewport: PetRect): PetPoint? {
    if (target.kind == PetTargetKind.CHART && target.path.isNotEmpty()) {
        val shifted = target.path.map { PetPoint(it.x, it.y - halfSize) }
        val intersections = if (shifted.size == 1) {
            shifted.filter { close(it.x, position.x) }
        } else {
            shifted.zipWithNext().mapNotNull { (start, end) ->
                val minX = minOf(start.x, end.x) - PET_EPSILON
                val maxX = maxOf(start.x, end.x) + PET_EPSILON
                if (position.x !in minX..maxX) return@mapNotNull null
                val dx = end.x - start.x
                if (abs(dx) <= PET_EPSILON) {
                    if (!close(position.x, start.x)) null else {
                        val y = position.y.coerceIn(minOf(start.y, end.y), maxOf(start.y, end.y))
                        PetPoint(position.x, y)
                    }
                } else {
                    val ratio = (position.x - start.x) / dx
                    PetPoint(position.x, start.y + (end.y - start.y) * ratio)
                }
            }
        }
        return intersections
            .filter { it.y >= position.y - PET_EPSILON }
            .filter { isInsidePetViewport(it, viewport, halfSize) }
            .minByOrNull { it.y - position.y }
    }
    val endpoints = supportEndpoints(target, halfSize)
    if (!close(endpoints.first.y, endpoints.second.y)) return null
    val minX = minOf(endpoints.first.x, endpoints.second.x) - PET_EPSILON
    val maxX = maxOf(endpoints.first.x, endpoints.second.x) + PET_EPSILON
    if (position.x !in minX..maxX) return null
    return PetPoint(position.x, endpoints.first.y).takeIf { it.y >= position.y - PET_EPSILON }
}

private fun nearestFallTarget(
    position: PetPoint,
    targets: List<PetTarget>,
    halfSize: Float,
    viewport: PetRect,
): PetTarget? = targets
    .asSequence()
    .mapNotNull { target ->
        fallSupportPoint(target, position, halfSize, viewport)?.let { support -> target to support }
    }
    .minByOrNull { (_, support) -> support.y - position.y }
    ?.first

private fun isOnSupport(
    target: PetTarget,
    position: PetPoint,
    halfSize: Float,
    viewport: PetRect?,
    tolerance: Float = PET_EPSILON,
): Boolean {
    if (target.kind == PetTargetKind.CHART && target.path.isNotEmpty()) {
        val path = target.path
            .map { PetPoint(it.x, it.y - halfSize) }
        if (path.size == 1) {
            return distanceSquared(position, path.first()) <= tolerance * tolerance
        }
        return path.zipWithNext().any { (start, end) ->
            distanceSquared(position, closestPointOnSegment(position, start, end)) <= tolerance * tolerance
        }
    }
    val endpoints = supportEndpoints(target, halfSize)
    val start = viewport?.clamp(endpoints.first, halfSize) ?: endpoints.first
    val end = viewport?.clamp(endpoints.second, halfSize) ?: endpoints.second
    val closest = closestPointOnSegment(position, start, end)
    return distanceSquared(position, closest) <= tolerance * tolerance
}

private fun supportEndpoints(target: PetTarget, halfSize: Float): Pair<PetPoint, PetPoint> {
    if (target.kind != PetTargetKind.EDGE) {
        val y = target.rect.top - halfSize
        return PetPoint(target.rect.left - halfSize, y) to PetPoint(target.rect.right + halfSize, y)
    }
    return if (target.rect.height > target.rect.width) {
        val x = if (target.rect.left <= halfSize) target.rect.right + halfSize else target.rect.left - halfSize
        PetPoint(x, target.rect.top) to PetPoint(x, target.rect.bottom)
    } else {
        val y = target.rect.top - halfSize
        PetPoint(target.rect.left, y) to PetPoint(target.rect.right, y)
    }
}

private fun closestPointOnSegment(point: PetPoint, start: PetPoint, end: PetPoint): PetPoint {
    val dx = end.x - start.x
    val dy = end.y - start.y
    val lengthSquared = dx * dx + dy * dy
    if (lengthSquared <= PET_EPSILON) return start
    val ratio = ((point.x - start.x) * dx + (point.y - start.y) * dy) / lengthSquared
    val clamped = ratio.coerceIn(0f, 1f)
    return PetPoint(start.x + dx * clamped, start.y + dy * clamped)
}

private fun facingAfter(current: PetFacing, horizontalDelta: Float): PetFacing = when {
    horizontalDelta < -PET_EPSILON -> PetFacing.LEFT
    horizontalDelta > PET_EPSILON -> PetFacing.RIGHT
    else -> current
}

private fun nearestPathIndex(position: PetPoint, path: List<PetPoint>): Int =
    path.indices.minByOrNull { distanceSquared(position, path[it]) } ?: 0

private fun close(first: Float, second: Float): Boolean = abs(first - second) <= PET_EPSILON

private fun closePoint(first: PetPoint, second: PetPoint): Boolean =
    close(first.x, second.x) && close(first.y, second.y)

private fun distanceSquared(first: PetPoint, second: PetPoint): Float {
    val dx = first.x - second.x
    val dy = first.y - second.y
    return dx * dx + dy * dy
}
