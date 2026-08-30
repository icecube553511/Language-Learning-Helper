package com.lexitrack.learning.domain

import kotlin.math.abs
import kotlin.math.max
import kotlin.math.hypot
import kotlin.math.min
import kotlin.math.pow

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
}

enum class PetFacing {
    LEFT,
    RIGHT,
}

const val PET_MOTION_ACCELERATION = 0.5f
const val PET_CRUISE_SPEED = 4f
const val PET_FALL_GRAVITY = 0.55f
const val PET_MAX_FALL_SPEED = 10f
const val PET_HARD_LANDING_SPEED = 7f
const val PET_BOUNCE_COUNT = 2
const val PET_FIRST_BOUNCE_SPEED = 5f
const val PET_BOUNCE_DECAY = 0.55f
const val PET_CENTER_BIAS_WEIGHT = 0.65f
const val PET_EDGE_PENALTY_RATIO = 0.15f
const val PET_IDLE_TICKS = 24

private const val PET_EPSILON = 1e-3f
private const val PET_PATH_SNAP_EPSILON = 1f

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
)

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
    return targets
        .asSequence()
        .filter { it.valid }
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

fun releaseDrag(state: PetState): PetState = state.copy(
    mode = PetMode.IDLE,
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
)

fun advancePet(
    state: PetState,
    targets: List<PetTarget>,
    viewport: PetRect,
    halfSize: Float,
    step: Float = PET_CRUISE_SPEED,
): PetState {
    val margin = max(0f, halfSize)
    if (state.mode == PetMode.DRAGGING) return state.copy(position = viewport.clamp(state.position, margin))
    if (state.idleTicksRemaining > 0) {
        return state.copy(
            idleTicksRemaining = state.idleTicksRemaining - 1,
            movementSpeed = (state.movementSpeed - PET_MOTION_ACCELERATION).coerceAtLeast(0f),
        )
    }
    if (targets.none(PetTarget::valid)) {
        return state.copy(
            position = viewport.clamp(state.position, margin),
            mode = PetMode.IDLE,
            targetId = null,
            movementSpeed = 0f,
            verticalVelocity = 0f,
            bouncesRemaining = 0,
        )
    }
    val target = state.targetId?.let { id -> targets.firstOrNull { it.id == id && it.valid } }
        ?: run {
            val valid = targets.filter(PetTarget::valid)
            val candidates = if (state.avoidTargetId != null) {
                valid.filter { it.id != state.avoidTargetId }.ifEmpty { valid }
            } else valid
            val below = if (state.mode == PetMode.FALL) {
                candidates.filter { target ->
                    fallSupportPoint(target, state.position, margin)?.y?.let { it > state.position.y + PET_EPSILON } == true
                }
            } else emptyList()
            nearestPetTarget(
                state.position,
                if (below.isNotEmpty()) below else candidates,
                margin,
                if (state.mode == PetMode.FALL) null else viewport,
            )
        }
        ?: return state.copy(position = viewport.clamp(state.position, margin), mode = PetMode.IDLE, targetId = null)

    if (state.mode == PetMode.BOUNCE) {
        return advanceBounce(state, target, viewport, margin)
    }
    if (state.mode == PetMode.FALL) {
        return advanceFall(state, target, viewport, margin, step)
    }

    if (target.kind == PetTargetKind.CHART && target.path.isNotEmpty()) {
        return advanceChart(state, target, viewport, margin, step)
    }

    return advanceSupport(state, target, viewport, margin, step)
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
                facing = facing,
            )
        }
        return state.copy(
            position = position,
            mode = PetMode.ROLL,
            targetId = target.id,
            rollCorners = state.rollCorners,
            movementSpeed = movement.speed,
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
            facing = facing,
        )
    }
}

private fun advanceFall(
    state: PetState,
    target: PetTarget,
    viewport: PetRect,
    halfSize: Float,
    maxSpeed: Float,
): PetState {
    val goal = viewport.clamp(
        fallSupportPoint(target, state.position, halfSize)
            ?: closestSupportPoint(target, state.position, halfSize),
        halfSize,
    )
    if (close(state.position.y, goal.y)) {
        if (close(state.position.x, goal.x)) {
            return landedState(state, target.id, viewport.clamp(goal, halfSize), state.verticalVelocity)
        }
        val movement = moveSmoothly(state.position, goal, state.movementSpeed, maxSpeed, verticalFirst = false)
        val position = viewport.clamp(movement.position, halfSize)
        val facing = facingAfter(state.facing, position.x - state.position.x)
        return if (movement.arrived) {
            landedState(state.copy(facing = facing), target.id, position, state.verticalVelocity)
        } else {
            state.copy(
                position = position,
                mode = PetMode.FALL,
                targetId = target.id,
                movementSpeed = movement.speed,
                verticalVelocity = 0f,
                facing = facing,
            )
        }
    }

    if (goal.y < state.position.y) {
        val movement = moveSmoothly(state.position, goal, state.movementSpeed, maxSpeed, verticalFirst = true)
        val position = viewport.clamp(movement.position, halfSize)
        return if (movement.arrived) {
            landedState(state, target.id, position, 0f)
        } else {
            state.copy(
                position = position,
                mode = PetMode.FALL,
                targetId = target.id,
                movementSpeed = movement.speed,
                verticalVelocity = 0f,
            )
        }
    }

    val velocity = (state.verticalVelocity.coerceAtLeast(0f) + PET_FALL_GRAVITY)
        .coerceAtMost(PET_MAX_FALL_SPEED)
    val nextY = (state.position.y + velocity).coerceAtMost(goal.y)
    val position = viewport.clamp(PetPoint(state.position.x, nextY), halfSize)
    if (close(nextY, goal.y) && close(state.position.x, goal.x)) {
        return landedState(state, target.id, position, velocity)
    }
    return state.copy(
        position = position,
        mode = PetMode.FALL,
        targetId = target.id,
        movementSpeed = 0f,
        verticalVelocity = if (close(nextY, goal.y)) 0f else velocity,
    )
}

private fun landedState(
    state: PetState,
    targetId: String,
    position: PetPoint,
    impactVelocity: Float,
): PetState = if (impactVelocity >= PET_HARD_LANDING_SPEED) {
    state.copy(
        position = position,
        mode = PetMode.BOUNCE,
        targetId = targetId,
        idleTicksRemaining = 0,
        movementSpeed = 0f,
        verticalVelocity = -PET_FIRST_BOUNCE_SPEED,
        bouncesRemaining = PET_BOUNCE_COUNT,
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
    )
}

private fun advanceBounce(
    state: PetState,
    target: PetTarget,
    viewport: PetRect,
    halfSize: Float,
): PetState {
    val landing = viewport.clamp(
        fallSupportPoint(target, state.position, halfSize)
            ?: closestSupportPoint(target, state.position, halfSize),
        halfSize,
    )
    val velocity = (state.verticalVelocity + PET_FALL_GRAVITY).coerceAtMost(PET_MAX_FALL_SPEED)
    val rawY = state.position.y + velocity
    if (velocity >= 0f && rawY >= landing.y) {
        val landedPosition = viewport.clamp(PetPoint(state.position.x, landing.y), halfSize)
        if (state.bouncesRemaining <= 1) {
            return state.copy(
                position = landedPosition,
                mode = PetMode.IDLE,
                targetId = target.id,
                idleTicksRemaining = PET_IDLE_TICKS,
                movementSpeed = 0f,
                verticalVelocity = 0f,
                bouncesRemaining = 0,
            )
        }
        val completedBounce = PET_BOUNCE_COUNT - state.bouncesRemaining + 1
        val reboundSpeed = PET_FIRST_BOUNCE_SPEED * PET_BOUNCE_DECAY.pow(completedBounce)
        return state.copy(
            position = landedPosition,
            mode = PetMode.BOUNCE,
            targetId = target.id,
            movementSpeed = 0f,
            verticalVelocity = -reboundSpeed,
            bouncesRemaining = state.bouncesRemaining - 1,
        )
    }
    return state.copy(
        position = viewport.clamp(PetPoint(state.position.x, rawY), halfSize),
        mode = PetMode.BOUNCE,
        targetId = target.id,
        movementSpeed = 0f,
        verticalVelocity = velocity,
    )
}

private fun advanceChart(
    state: PetState,
    target: PetTarget,
    viewport: PetRect,
    halfSize: Float,
    maxSpeed: Float,
): PetState {
    val path = target.path.map { viewport.clamp(PetPoint(it.x, it.y - halfSize), halfSize) }
    if (path.size == 1) {
        val movement = moveSmoothly(state.position, path.single(), state.movementSpeed, maxSpeed, verticalFirst = true)
        val position = viewport.clamp(movement.position, halfSize)
        return state.copy(
            position = position,
            mode = if (movement.arrived) PetMode.IDLE else PetMode.SLIDE,
            targetId = target.id,
            idleTicksRemaining = if (movement.arrived) PET_IDLE_TICKS else 0,
            movementSpeed = if (movement.arrived) 0f else movement.speed,
            facing = facingAfter(state.facing, position.x - state.position.x),
        )
    }

    var direction = if (state.targetId == target.id && state.pathDirection < 0) -1 else 1
    var waypoint = if (state.targetId == target.id) {
        state.pathIndex.coerceIn(0, path.lastIndex)
    } else {
        nearestPathIndex(state.position, path)
    }
    if (state.targetId != target.id && closePoint(state.position, path[waypoint])) {
        if (waypoint == path.lastIndex) {
            direction = -1
            waypoint -= 1
        } else {
            waypoint += 1
        }
    }

    val speed = (state.movementSpeed.coerceAtLeast(0f) + PET_MOTION_ACCELERATION)
        .coerceAtMost(max(PET_MOTION_ACCELERATION, maxSpeed))
    var budget = speed
    var position = state.position
    var completedCycle = false
    var iterations = 0
    while (budget > 0f && iterations < path.size * 2) {
        iterations += 1
        val goal = path[waypoint]
        val distance = hypot(goal.x - position.x, goal.y - position.y)
        if (distance <= budget + PET_PATH_SNAP_EPSILON) {
            position = goal
            budget = (budget - distance).coerceAtLeast(0f)
            if (waypoint == 0 && direction < 0) {
                completedCycle = true
                break
            }
            if (waypoint == path.lastIndex && direction > 0) {
                direction = -1
                waypoint = path.lastIndex - 1
            } else {
                waypoint += direction
            }
        } else {
            val ratio = budget / distance
            position = PetPoint(
                position.x + (goal.x - position.x) * ratio,
                position.y + (goal.y - position.y) * ratio,
            )
            budget = 0f
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
            avoidTargetId = target.id,
            movementSpeed = 0f,
            facing = facing,
        )
    } else {
        state.copy(
            position = position,
            mode = PetMode.SLIDE,
            targetId = target.id,
            pathIndex = waypoint,
            pathDirection = direction,
            movementSpeed = speed,
            verticalVelocity = 0f,
            facing = facing,
        )
    }
}

private fun moveSmoothly(
    position: PetPoint,
    goal: PetPoint,
    currentSpeed: Float,
    maxSpeed: Float,
    verticalFirst: Boolean,
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
    val speedLimit = max(PET_MOTION_ACCELERATION, maxSpeed)
    val safeCurrent = currentSpeed.coerceAtLeast(0f)
    val stoppingDistance = safeCurrent * safeCurrent / (2f * PET_MOTION_ACCELERATION)
    val speed = if (safeCurrent > 0f && remaining <= stoppingDistance) {
        (safeCurrent - PET_MOTION_ACCELERATION).coerceAtLeast(PET_MOTION_ACCELERATION)
    } else {
        (safeCurrent + PET_MOTION_ACCELERATION).coerceAtMost(speedLimit)
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
        return target.path
            .asSequence()
            .map { PetPoint(it.x, it.y - halfSize) }
            .minByOrNull { distanceSquared(position, it) }
            ?: position
    }
    val endpoints = supportEndpoints(target, halfSize)
    return closestPointOnSegment(position, endpoints.first, endpoints.second)
}

private fun fallSupportPoint(target: PetTarget, position: PetPoint, halfSize: Float): PetPoint? {
    if (target.kind == PetTargetKind.CHART && target.path.isNotEmpty()) {
        val shifted = target.path.map { PetPoint(it.x, it.y - halfSize) }
        return shifted.filter { it.y >= position.y - PET_EPSILON }
            .minByOrNull { distanceSquared(position, it) }
            ?: shifted.minByOrNull { distanceSquared(position, it) }
    }
    return closestSupportPoint(target, position, halfSize)
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
