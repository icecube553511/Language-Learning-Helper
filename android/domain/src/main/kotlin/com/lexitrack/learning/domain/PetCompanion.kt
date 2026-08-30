package com.lexitrack.learning.domain

import kotlin.math.abs
import kotlin.math.max
import kotlin.math.hypot
import kotlin.math.min

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
    DRAGGING,
}

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

    fun distanceTo(point: PetPoint, margin: Float = 0f): Float = if (kind == PetTargetKind.CHART && path.isNotEmpty()) {
        path.minOf { hypot(point.x - it.x, point.y - it.y) }
    } else {
        val boundary = rect.boundaryPoint(point, margin)
        hypot(point.x - boundary.x, point.y - boundary.y)
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
)

/**
 * Select the nearest visible target.  Invalid/zero-sized targets are ignored,
 * and ties retain registration order via the stable list iteration.
 */
fun nearestPetTarget(
    position: PetPoint,
    targets: List<PetTarget>,
    halfSize: Float = 0f,
): PetTarget? {
    return targets
        .asSequence()
        .filter { it.valid }
        .minWithOrNull(compareBy { target ->
            target.distanceTo(position, max(0f, halfSize))
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
)

fun beginDrag(state: PetState, pointer: PetPoint): PetState =
    state.copy(
        position = pointer,
        mode = PetMode.DRAGGING,
        targetId = null,
        idleTicksRemaining = 0,
        pathIndex = 0,
        pathDirection = 1,
        rollCorners = 0,
        avoidTargetId = null,
    )

fun moveDrag(
    state: PetState,
    pointer: PetPoint,
    viewport: PetRect,
    halfSize: Float,
): PetState = if (state.mode != PetMode.DRAGGING) state else state.copy(
    position = viewport.clamp(pointer, max(0f, halfSize)),
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
)

fun advancePet(
    state: PetState,
    targets: List<PetTarget>,
    viewport: PetRect,
    halfSize: Float,
    step: Float = 8f,
): PetState {
    if (state.mode == PetMode.DRAGGING) return state.copy(position = viewport.clamp(state.position, halfSize))
    if (state.idleTicksRemaining > 0) return state.copy(idleTicksRemaining = state.idleTicksRemaining - 1)
    if (targets.isEmpty()) return state.copy(position = viewport.clamp(state.position, halfSize), mode = PetMode.IDLE, targetId = null)
    val target = state.targetId?.let { id -> targets.firstOrNull { it.id == id && it.valid } }
        ?: run {
            val valid = targets.filter(PetTarget::valid)
            val candidates = if (state.avoidTargetId != null) {
                valid.filter { it.id != state.avoidTargetId }.ifEmpty { valid }
            } else valid
            val below = if (state.mode == PetMode.FALL) {
                candidates.filter { it.rect.bottom + max(0f, halfSize) >= state.position.y }
            } else emptyList()
            nearestPetTarget(state.position, if (below.isNotEmpty()) below else candidates, halfSize)
        }
        ?: return state.copy(position = viewport.clamp(state.position, halfSize), mode = PetMode.IDLE, targetId = null)

    if (target.kind == PetTargetKind.CHART && target.path.isNotEmpty()) {
        var index = if (state.targetId == target.id) state.pathIndex.coerceIn(0, target.path.lastIndex)
            else nearestPathIndex(state.position, target.path)
        var direction = if (state.targetId == target.id && state.pathDirection < 0) -1 else 1
        val (nextPosition, arrived) = stepTowards(state.position, target.path[index], step)
        if (arrived) {
            val completedCycle = state.targetId == target.id && state.pathDirection < 0 && index == 0
            if (completedCycle) {
                return PetState(
                    position = viewport.clamp(nextPosition, halfSize),
                    mode = PetMode.IDLE,
                    targetId = null,
                    idleTicksRemaining = 10,
                    avoidTargetId = target.id,
                )
            }
            val next = nextPathIndex(index, direction, target.path.size)
            index = next.first
            direction = next.second
        }
        return PetState(viewport.clamp(nextPosition, halfSize), PetMode.SLIDE, target.id, 0, index, direction)
    }

    val boundary = target.rect.boundaryPoint(state.position, halfSize)
    val onBoundary = distanceSquared(boundary, state.position) <= 1e-6f
    val rolling = state.targetId == target.id && onBoundary
    val goal = when {
        rolling -> target.rect.nextBoundaryCorner(state.position, halfSize)
        state.mode == PetMode.FALL -> fallGoal(state.position, target.rect, halfSize)
        else -> boundary
    }
    val verticalFlight = !rolling && (state.mode == PetMode.FALL || state.mode == PetMode.FLY || state.targetId != target.id)
    val (nextPosition, arrived) = if (verticalFlight) stepVerticalFirst(state.position, goal, step)
        else stepTowards(state.position, goal, step)
    val position = viewport.clamp(nextPosition, halfSize)
    if (!arrived) {
        return PetState(
            position = position,
            mode = if (state.mode == PetMode.FALL) PetMode.FALL else if (rolling) PetMode.ROLL else PetMode.FLY,
            targetId = target.id,
            rollCorners = if (rolling) state.rollCorners else 0,
        )
    }
    if (rolling) {
        val completedCorners = state.rollCorners + 1
        if (completedCorners >= 4) {
            return PetState(
                position = position,
                mode = PetMode.IDLE,
                targetId = null,
                idleTicksRemaining = 10,
                avoidTargetId = target.id,
            )
        }
        return PetState(position, PetMode.ROLL, target.id, rollCorners = completedCorners)
    }
    return PetState(position, PetMode.IDLE, target.id, idleTicksRemaining = 10)
}

private fun stepTowards(position: PetPoint, goal: PetPoint, distance: Float): Pair<PetPoint, Boolean> {
    val dx = goal.x - position.x
    val dy = goal.y - position.y
    val remaining = hypot(dx, dy)
    if (remaining <= max(0f, distance) || remaining == 0f) return goal to true
    val ratio = distance / remaining
    return PetPoint(position.x + dx * ratio, position.y + dy * ratio) to false
}

private fun stepVerticalFirst(position: PetPoint, goal: PetPoint, distance: Float): Pair<PetPoint, Boolean> {
    if (!close(position.y, goal.y)) {
        val delta = goal.y - position.y
        if (abs(delta) <= distance) return PetPoint(position.x, goal.y) to close(position.x, goal.x)
        return PetPoint(position.x, position.y + kotlin.math.sign(delta) * distance) to false
    }
    return stepTowards(position, goal, distance)
}

private fun nearestPathIndex(position: PetPoint, path: List<PetPoint>): Int =
    path.indices.minByOrNull { distanceSquared(position, path[it]) } ?: 0

private fun nextPathIndex(index: Int, direction: Int, size: Int): Pair<Int, Int> {
    if (size <= 1) return 0 to 1
    val next = index + if (direction >= 0) 1 else -1
    if (next >= size) return (size - 2) to -1
    if (next < 0) return 1 to 1
    return next to if (direction >= 0) 1 else -1
}

private fun fallGoal(position: PetPoint, rect: PetRect, margin: Float): PetPoint {
    val x = position.x.coerceIn(rect.left - margin, rect.right + margin)
    val top = rect.top - margin
    val bottom = rect.bottom + margin
    return when {
        top >= position.y -> PetPoint(x, top)
        bottom >= position.y -> PetPoint(x, bottom)
        else -> rect.boundaryPoint(position, margin)
    }
}

private fun close(first: Float, second: Float): Boolean = abs(first - second) <= 1e-3f

private fun distanceSquared(first: PetPoint, second: PetPoint): Float {
    val dx = first.x - second.x
    val dy = first.y - second.y
    return dx * dx + dy * dy
}
