package com.lexitrack.learning.presentation

import com.lexitrack.learning.domain.PetFacing
import com.lexitrack.learning.domain.PET_FLING_GRAVITY
import com.lexitrack.learning.domain.PetMode
import com.lexitrack.learning.domain.PetPoint
import com.lexitrack.learning.domain.PetRect
import com.lexitrack.learning.domain.PetState
import com.lexitrack.learning.domain.moveDrag
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import kotlin.math.abs
import kotlin.math.min
import kotlin.math.sqrt

/** Pure presentation geometry for transferring Bingzi between Compose windows. */
data class PetWindow(
    val id: String,
    val rect: PetRect,
    val order: Int = 0,
    val mapped: Boolean = true,
    val viewable: Boolean = true,
) {
    val eligible: Boolean get() = mapped && viewable && rect.valid
}

data class PetWindowEntry(
    val position: PetPoint,
    val mode: PetMode,
    val velocity: PetPoint,
    val facing: PetFacing,
)

/** Rendering and gesture-capture responsibilities are independent per host. */
data class PetOverlayOwnership(
    val renders: Boolean,
    val capturesGesture: Boolean,
)

fun petOverlayOwnership(
    activeWindowId: String?,
    windowId: String,
    dragCaptureActive: Boolean,
): PetOverlayOwnership = PetOverlayOwnership(
    renders = activeWindowId == windowId,
    capturesGesture = dragCaptureActive,
)

private fun clamp(value: Float, low: Float, high: Float): Float = value.coerceIn(low, maxOf(low, high))

/** Map a pet centre through a screen-space window portal. */
fun mapPetEntry(
    sourceRect: PetRect,
    targetRect: PetRect,
    positionInSource: PetPoint,
    direction: String,
    petHalfSize: Float,
    mode: PetMode = PetMode.FLING,
    velocity: PetPoint = PetPoint(0f, 0f),
    facing: PetFacing = PetFacing.RIGHT,
    dragging: Boolean = false,
): PetWindowEntry {
    val half = petHalfSize.coerceAtLeast(0f)
    val worldX = sourceRect.left + positionInSource.x
    val worldY = sourceRect.top + positionInSource.y
    val minX = targetRect.left + half
    val maxX = maxOf(minX, targetRect.right - half)
    val localX = clamp(worldX, minX, maxX) - targetRect.left
    val localY: Float
    val nextMode: PetMode
    when (direction.lowercase()) {
        "left" -> {
            localY = clamp(worldY, targetRect.top + half, targetRect.bottom - half) - targetRect.top
            return PetWindowEntry(
                PetPoint(half, localY),
                if (dragging) PetMode.DRAGGING else mode,
                velocity,
                facing,
            )
        }
        "right" -> {
            localY = clamp(worldY, targetRect.top + half, targetRect.bottom - half) - targetRect.top
            return PetWindowEntry(
                PetPoint(maxOf(half, targetRect.width - half), localY),
                if (dragging) PetMode.DRAGGING else mode,
                velocity,
                facing,
            )
        }
        "top" -> {
            localY = -half
            nextMode = if (dragging) PetMode.DRAGGING else PetMode.FALL
        }
        "bottom" -> {
            // Keep the same outside-in transition as top entry: the centre
            // starts one radius beyond the destination edge.  Unlike a top
            // entry, this portal is used by an upward fling, so retain the
            // incoming projectile mode/velocity while it crosses the edge.
            localY = targetRect.height + half
            nextMode = if (dragging) PetMode.DRAGGING else mode
        }
        else -> error("unknown pet window entry direction: $direction")
    }
    return PetWindowEntry(
        PetPoint(localX, localY),
        nextMode,
        velocity,
        facing,
    )
}

fun mapPetBetweenWindows(
    sourceRect: PetRect,
    targetRect: PetRect,
    positionInSource: PetPoint,
    direction: String,
    petHalfSize: Float,
    mode: PetMode = PetMode.FLING,
    velocity: PetPoint = PetPoint(0f, 0f),
    facing: PetFacing = PetFacing.RIGHT,
    dragging: Boolean = false,
): PetWindowEntry = mapPetEntry(sourceRect, targetRect, positionInSource, direction, petHalfSize, mode, velocity, facing, dragging)

private fun score(
    source: PetWindow,
    target: PetWindow,
    direction: String,
    world: PetPoint,
    allowOverlap: Boolean = false,
    motion: PetPoint? = null,
    maxTime: Float? = null,
): Triple<Float, Float, Int> {
    val s = source.rect
    val t = target.rect
    val gap = when (direction.lowercase()) {
        "right" -> {
            if (t.right <= world.x + 1e-3f) {
                return Triple(Float.POSITIVE_INFINITY, Float.POSITIVE_INFINITY, target.order)
            }
            t.left - s.right
        }
        "left" -> {
            if (t.left >= world.x - 1e-3f) {
                return Triple(Float.POSITIVE_INFINITY, Float.POSITIVE_INFINITY, target.order)
            }
            s.left - t.right
        }
        "bottom" -> {
            if (t.bottom <= world.y + 1e-3f) {
                return Triple(Float.POSITIVE_INFINITY, Float.POSITIVE_INFINITY, target.order)
            }
            t.top - s.bottom
        }
        "top" -> {
            if (t.top >= world.y - 1e-3f) {
                return Triple(Float.POSITIVE_INFINITY, Float.POSITIVE_INFINITY, target.order)
            }
            s.top - t.bottom
        }
        else -> return Triple(Float.POSITIVE_INFINITY, Float.POSITIVE_INFINITY, target.order)
    }
    // Autonomous portals require a genuine boundary between hosts.  Modal
    // dialogs commonly overlap the root window; treating that overlap as an
    // adjacent portal lets a background tick steal the active pet.  Dragging
    // may explicitly opt in because the pointer is intentionally crossing
    // into an overlapping host.
    if (!allowOverlap && gap < -1e-3f) {
        return Triple(Float.POSITIVE_INFINITY, Float.POSITIVE_INFINITY, target.order)
    }
    val ray = portalRayMotion(direction, motion)
    val entryTime = rayRectEntryTime(world, ray, t, maxTime)
        ?: return Triple(Float.POSITIVE_INFINITY, Float.POSITIVE_INFINITY, target.order)
    return Triple(entryTime, 0f, target.order)
}

private fun portalRayMotion(direction: String, motion: PetPoint?): PetPoint = motion
    ?.takeIf { it.x.isFinite() && it.y.isFinite() && abs(it.x) + abs(it.y) > 1e-3f }
    ?: when (direction.lowercase()) {
        "right" -> PetPoint(1f, 0f)
        "left" -> PetPoint(-1f, 0f)
        "bottom" -> PetPoint(0f, 1f)
        else -> PetPoint(0f, -1f)
    }

internal fun rayRectEntryTime(
    origin: PetPoint,
    motion: PetPoint,
    rect: PetRect,
    maxTime: Float? = null,
): Float? {
    var minimum = 0f
    var maximum = Float.POSITIVE_INFINITY
    fun clip(originValue: Float, directionValue: Float, low: Float, high: Float): Boolean {
        if (abs(directionValue) <= 1e-6f) return originValue in (low - 1e-3f)..(high + 1e-3f)
        val first = (low - originValue) / directionValue
        val second = (high - originValue) / directionValue
        minimum = maxOf(minimum, min(first, second))
        maximum = min(maximum, maxOf(first, second))
        return maximum + 1e-6f >= minimum
    }
    if (!clip(origin.x, motion.x, rect.left, rect.right)) return null
    if (!clip(origin.y, motion.y, rect.top, rect.bottom)) return null
    val entry = minimum.takeIf { it.isFinite() && it >= -1e-3f }?.coerceAtLeast(0f) ?: return null
    val limit = maxTime?.takeIf(Float::isFinite)?.coerceAtLeast(0f)
    return entry.takeIf { limit == null || it <= limit + 1e-6f }
}

/** Select the earliest mapped/viewable window intersecting the movement ray. */
fun selectAdjacentWindow(
    source: PetWindow,
    candidates: Iterable<PetWindow>,
    direction: String,
    positionInSource: PetPoint,
    allowOverlap: Boolean = false,
    motion: PetPoint? = null,
    maxTime: Float? = null,
): PetWindow? {
    val world = PetPoint(source.rect.left + positionInSource.x, source.rect.top + positionInSource.y)
    return candidates
        .asSequence()
        .filter { it.id != source.id && it.eligible }
        .map { it to score(source, it, direction, world, allowOverlap, motion, maxTime) }
        .filter { it.second.first.isFinite() }
        .minWithOrNull(compareBy({ it.second.first }, { it.second.second }, { it.second.third }))
        ?.first
}

fun findAdjacentWindow(
    source: PetWindow,
    candidates: Iterable<PetWindow>,
    direction: String,
    positionInSource: PetPoint,
    allowOverlap: Boolean = false,
    motion: PetPoint? = null,
    maxTime: Float? = null,
): PetWindow? = selectAdjacentWindow(source, candidates, direction, positionInSource, allowOverlap, motion, maxTime)

/**
 * Return portal exits during the next fixed simulation interval.
 *
 * Horizontal motion is linear; vertical motion uses the same constant
 * gravity as the domain reducer.  The result is sorted by the first
 * continuous edge crossing so a diagonal fling cannot be routed through a
 * later edge merely because the horizontal branch happened to run first.
 */
fun predictedExitTimes(
    state: PetState,
    viewport: PetRect,
    petHalfSize: Float,
    durationSeconds: Float = PET_TICK_MS / 1_000f,
    fallUnitScale: Float = 1f,
): List<Pair<Float, String>> {
    val half = petHalfSize.coerceAtLeast(0f)
    val duration = durationSeconds.coerceAtLeast(0f)
    val x = state.position.x
    val y = state.position.y
    val vx = state.velocity.x
    val vy = state.velocity.y
    val result = mutableListOf<Pair<Float, String>>()

    // A drag is migrated from the edge reached by the pointer.  It has no
    // physical velocity, so only already-clamped contacts are eligible.
    if (state.mode == PetMode.DRAGGING) {
        if (x >= viewport.right - half - 1e-3f) result += 0f to "right"
        if (x <= viewport.left + half + 1e-3f) result += 0f to "left"
        if (y >= viewport.bottom - half - 1e-3f) result += 0f to "bottom"
        if (y <= viewport.top + half + 1e-3f) result += 0f to "top"
        return result
    }

    val left = viewport.left + half
    val right = maxOf(left, viewport.right - half)
    val top = viewport.top + half
    val bottom = maxOf(top, viewport.bottom - half)
    fun addHorizontal(edge: Float, direction: String, velocity: Float) {
        if (abs(velocity) <= 1e-3f) return
        val time = if (direction == "right") {
            if (x >= edge - 1e-3f) 0f else (edge - x) / velocity
        } else {
            if (x <= edge + 1e-3f) 0f else (edge - x) / velocity
        }
        if (time >= -1e-3f && time <= duration + 1e-3f) {
            result += time.coerceAtLeast(0f) to direction
        }
    }
    if (vx > 1e-3f) addHorizontal(right, "right", vx)
    if (vx < -1e-3f) addHorizontal(left, "left", vx)

    val gravity = if (state.mode == PetMode.FLING || state.mode == PetMode.FALL) {
        PET_FLING_GRAVITY * fallUnitScale.coerceAtLeast(0f)
    } else {
        0f
    }
    fun addVertical(edge: Float, direction: String, outwardSign: Float) {
        // If already at an edge, retain the current outward contact.  This
        // also handles zero-duration calls used by deterministic tests.
        if (direction == "top" && y <= edge + 1e-3f && vy <= 1e-3f) {
            result += 0f to direction
            return
        }
        if (direction == "bottom" && y >= edge - 1e-3f && vy >= -1e-3f) {
            result += 0f to direction
            return
        }
        val roots = portalQuadraticRoots(
            0.5f * gravity,
            vy,
            y - edge,
            duration,
        )
        roots.firstOrNull { time ->
            val contactVelocity = vy + gravity * time
            if (outwardSign < 0f) contactVelocity <= 1e-3f else contactVelocity >= -1e-3f
        }?.let { time -> result += time to direction }
    }
    addVertical(top, "top", -1f)
    addVertical(bottom, "bottom", 1f)
    return result.sortedWith(compareBy<Pair<Float, String>>({ it.first }, { portalDirectionOrder(it.second) }))
}

/** Snake-case alias for parity adapters and contract tests. */
fun predicted_exit_times(
    state: PetState,
    viewport: PetRect,
    petHalfSize: Float,
    durationSeconds: Float = PET_TICK_MS / 1_000f,
    fallUnitScale: Float = 1f,
): List<Pair<Float, String>> = predictedExitTimes(state, viewport, petHalfSize, durationSeconds, fallUnitScale)

/**
 * Evaluate the state at a continuous portal crossing before changing hosts.
 * The fixed-step reducer remains authoritative; this presentation helper
 * only avoids throwing away the fraction of a tick that precedes the edge.
 */
fun stateAtExit(
    state: PetState,
    viewport: PetRect,
    petHalfSize: Float,
    elapsedSeconds: Float,
    direction: String,
    fallUnitScale: Float = 1f,
): PetState {
    val elapsed = elapsedSeconds.coerceAtLeast(0f)
    val scale = fallUnitScale
        .takeIf { it.isFinite() }
        ?.coerceAtLeast(0f)
        ?: 1f
    val gravity = if (state.mode == PetMode.FLING || state.mode == PetMode.FALL) {
        PET_FLING_GRAVITY * scale
    } else {
        0f
    }
    val vx = state.horizontalVelocity
    val vy = state.verticalVelocity + gravity * elapsed
    var position = PetPoint(
        state.position.x + vx * elapsed,
        state.position.y + state.verticalVelocity * elapsed + 0.5f * gravity * elapsed * elapsed,
    )
    val half = petHalfSize.coerceAtLeast(0f)
    when (direction.lowercase()) {
        "left" -> position = position.copy(x = viewport.left + half)
        "right" -> position = position.copy(x = maxOf(viewport.left + half, viewport.right - half))
        "top" -> position = position.copy(y = viewport.top + half)
        "bottom" -> position = position.copy(y = maxOf(viewport.top + half, viewport.bottom - half))
    }
    return state.copy(
        position = position,
        horizontalVelocity = vx,
        verticalVelocity = vy,
    )
}

fun state_at_exit(
    state: PetState,
    viewport: PetRect,
    petHalfSize: Float,
    elapsedSeconds: Float,
    direction: String,
    fallUnitScale: Float = 1f,
): PetState = stateAtExit(state, viewport, petHalfSize, elapsedSeconds, direction, fallUnitScale)

private fun portalDirectionOrder(direction: String): Int = when (direction) {
    "right" -> 0
    "left" -> 1
    "bottom" -> 2
    "top" -> 3
    else -> 4
}

private fun portalQuadraticRoots(a: Float, b: Float, c: Float, limit: Float): List<Float> {
    if (abs(a) <= 1e-6f) {
        if (abs(b) <= 1e-6f) return emptyList()
        return listOf(-c / b).filter { it >= -1e-3f && it <= limit + 1e-3f }
            .map { it.coerceIn(0f, limit) }
    }
    val discriminant = b * b - 4f * a * c
    if (discriminant < -1e-3f) return emptyList()
    val root = sqrt(discriminant.coerceAtLeast(0f))
    return listOf(
        (-b - root) / (2f * a),
        (-b + root) / (2f * a),
    ).filter { it >= -1e-3f && it <= limit + 1e-3f }
        .map { it.coerceIn(0f, limit) }
        .distinct()
        .sorted()
}

/**
 * Presentation-only coordinator shared by all Compose Dialog hosts. It keeps
 * one transient state and maps that state through a portal when focus moves
 * between mapped application windows; no learning data is persisted here.
 */
class PetWindowCoordinator(initialState: PetState? = null) {
    var state by mutableStateOf(initialState ?: PetState(PetPoint(0f, 0f)))
        private set
    var hasState: Boolean = initialState != null
        private set
    var activeWindowId by mutableStateOf<String?>(null)
        private set
    private val windows = linkedMapOf<String, PetWindow>()
    private val targetsByWindow = linkedMapOf<String, List<com.lexitrack.learning.domain.PetTarget>>()

    fun registerWindow(window: PetWindow, active: Boolean = false, petHalfSize: Float = 0f) {
        windows[window.id] = window
        if (active) activate(window.id, petHalfSize)
    }

    fun unregisterWindow(id: String, petHalfSize: Float = 0f) {
        val closing = windows[id]
        windows.remove(id)
        targetsByWindow.remove(id)
        if (activeWindowId == id) {
            val fallback = windows.values.lastOrNull { it.eligible }
                ?: windows.values.lastOrNull { it.mapped }
            if (closing != null && fallback != null) {
                val direction = portalDirection(closing.rect, fallback.rect)
                if (direction != null) {
                    val entryDirection = entryDirection(direction)
                    val entry = mapPetEntry(
                        closing.rect,
                        fallback.rect,
                        state.position,
                        entryDirection,
                        petHalfSize,
                        mode = state.mode,
                        velocity = state.velocity,
                        facing = state.facing,
                        dragging = state.mode == PetMode.DRAGGING,
                    )
                    state = stateFromEntry(entry)
                } else {
                    // Preserve the absolute centre when the fallback host is
                    // not adjacent (for example after a resize), rather than
                    // leaking a source-local coordinate into the new host.
                    val world = PetPoint(
                        closing.rect.left + state.position.x,
                        closing.rect.top + state.position.y,
                    )
                    state = state.copy(
                        position = PetPoint(
                            clampInner(world.x - fallback.rect.left, fallback.rect.width, petHalfSize),
                            clampInner(world.y - fallback.rect.top, fallback.rect.height, petHalfSize),
                        ),
                        targetId = null,
                        idleTicksRemaining = 0,
                        avoidTargetId = null,
                    )
                }
            }
            activeWindowId = fallback?.id
        }
    }

    fun windows(): List<PetWindow> = windows.values.toList()

    fun updateTargets(windowId: String, targets: List<com.lexitrack.learning.domain.PetTarget>) {
        targetsByWindow[windowId] = targets
    }

    fun targetsFor(windowId: String? = activeWindowId): List<com.lexitrack.learning.domain.PetTarget> =
        windowId?.let(targetsByWindow::get).orEmpty()

    fun viewportFor(windowId: String? = activeWindowId): PetRect? =
        windowId?.let { windows[it]?.rect?.let { rect -> PetRect(0f, 0f, rect.width, rect.height) } }

    fun worldPosition(windowId: String? = activeWindowId): PetPoint? =
        windowId?.let { windows[it]?.rect?.let { rect -> PetPoint(rect.left + state.position.x, rect.top + state.position.y) } }

    /** Promote a host and preserve world position/velocity through its edge. */
    fun activate(id: String, petHalfSize: Float = 0f): Boolean {
        val target = windows[id] ?: return false
        if (!target.eligible) return false
        val previousId = activeWindowId
        val source = previousId?.let(windows::get)
        if (source != null && source.eligible && previousId != id) {
            val direction = portalDirection(source.rect, target.rect)
            if (direction != null) {
                val entryDirection = entryDirection(direction)
                val entry = mapPetEntry(
                    source.rect,
                    target.rect,
                    state.position,
                    entryDirection,
                    petHalfSize = petHalfSize,
                    mode = state.mode,
                    velocity = state.velocity,
                    facing = state.facing,
                    dragging = state.mode == PetMode.DRAGGING,
                )
                state = stateFromEntry(entry)
            } else {
                // No geometric adjacency: keep the centre, clamped by the
                // target overlay on its next simulation frame.
                val world = PetPoint(source.rect.left + state.position.x, source.rect.top + state.position.y)
                state = state.copy(
                    position = PetPoint(
                        clampInner(world.x - target.rect.left, target.rect.width, petHalfSize),
                        clampInner(world.y - target.rect.top, target.rect.height, petHalfSize),
                    ),
                    targetId = null,
                    idleTicksRemaining = 0,
                    avoidTargetId = null,
                )
            }
        }
        activeWindowId = id
        return true
    }

    fun updateState(next: PetState) {
        state = next
        hasState = true
    }

    /**
     * Apply a captured pointer delta in whichever host currently owns the pet.
     * The gesture may still belong to the source Compose window after a portal
     * transfer, so neither the source viewport nor source-local state is used.
     */
    fun dragActiveBy(
        dragAmount: PetPoint,
        petHalfSize: Float,
        allowOverlap: Boolean = true,
    ): Boolean {
        val sourceId = activeWindowId ?: return false
        val sourceWindow = windows[sourceId] ?: return false
        val viewport = viewportFor(sourceId) ?: return false
        if (state.mode != PetMode.DRAGGING) return false
        val grabOffset = state.dragOffset ?: PetPoint(0f, 0f)
        val desiredWorldCenter = PetPoint(
            sourceWindow.rect.left + state.position.x + dragAmount.x,
            sourceWindow.rect.top + state.position.y + dragAmount.y,
        )
        state = moveDrag(
            state,
            PetPoint(
                state.position.x + grabOffset.x + dragAmount.x,
                state.position.y + grabOffset.y + dragAmount.y,
            ),
            viewport,
            petHalfSize,
        )
        hasState = true
        migrateIfNeeded(
            sourceId,
            petHalfSize,
            // Drag delta is a segment parameterized over t=0..1.
            lookaheadSeconds = 1f,
            allowOverlap = allowOverlap,
            motion = dragAmount,
        )
        val targetId = activeWindowId
        if (targetId != sourceId) {
            val targetWindow = targetId?.let(windows::get) ?: return true
            val targetViewport = viewportFor(targetId) ?: return true
            // Reapply the event's original world-space destination after the
            // portal mapping. This consumes the source edge, inter-window gap,
            // and target inner edge before applying any remaining overshoot.
            state = moveDrag(
                state,
                PetPoint(
                    desiredWorldCenter.x - targetWindow.rect.left + grabOffset.x,
                    desiredWorldCenter.y - targetWindow.rect.top + grabOffset.y,
                ),
                targetViewport,
                petHalfSize,
            )
        }
        return true
    }

    /**
     * Move the active state through an adjacent portal.
     *
     * `lookaheadSeconds` is used by the presentation tick before physics
     * integration.  A fast fling can otherwise hit the domain wall and
     * reverse before the host has a chance to hand it to the neighbouring
     * window.  The mapping still occurs at the source inner edge; the next
     * host owns all subsequent integration. For separated hosts, the state is
     * first moved along the same selection ray to the target AABB entry so the
     * tangential coordinate is not lost in the gap.
     */
    fun migrateIfNeeded(
        windowId: String,
        petHalfSize: Float,
        lookaheadSeconds: Float = PET_TICK_MS / 1_000f,
        fallUnitScale: Float = 1f,
        allowOverlap: Boolean = false,
        motion: PetPoint? = null,
    ): Boolean {
        val source = windows[windowId] ?: return false
        if (!source.eligible || activeWindowId != windowId) return false
        val viewport = PetRect(0f, 0f, source.rect.width, source.rect.height)
        val duration = lookaheadSeconds.coerceAtLeast(0f)
        // Try crossings in continuous time order.  A candidate may be absent
        // on the first edge (for example a diagonal path with no window to the
        // right), so continue to the next crossing rather than reordering it.
        for ((crossingTime, direction) in predictedExitTimes(
            state,
            viewport,
            petHalfSize,
            durationSeconds = duration,
            fallUnitScale = fallUnitScale,
        )) {
            val crossingState = stateAtExit(
                state,
                viewport,
                petHalfSize,
                crossingTime,
                direction,
                fallUnitScale,
            )
            val rayOrigin = portalRayOrigin(crossingState.position, direction, petHalfSize)
            val rayMotion = portalRayMotion(direction, motion ?: crossingState.velocity)
            val remainingDuration = (duration - crossingTime).coerceAtLeast(0f)
            val target = selectAdjacentWindow(
                source,
                windows.values,
                direction,
                rayOrigin,
                allowOverlap = allowOverlap,
                motion = rayMotion,
                maxTime = remainingDuration,
            ) ?: continue
            val worldRayOrigin = PetPoint(
                source.rect.left + rayOrigin.x,
                source.rect.top + rayOrigin.y,
            )
            val entryTime = rayRectEntryTime(worldRayOrigin, rayMotion, target.rect, remainingDuration)
                ?: continue
            val entryState = crossingState.copy(
                position = PetPoint(
                    crossingState.position.x + rayMotion.x * entryTime,
                    crossingState.position.y + rayMotion.y * entryTime,
                ),
            )
            val entry = mapPetEntry(
                source.rect,
                target.rect,
                entryState.position,
                entryDirection(direction),
                petHalfSize,
                mode = entryState.mode,
                velocity = entryState.velocity,
                facing = entryState.facing,
                dragging = entryState.mode == PetMode.DRAGGING,
            )
            state = stateFromEntry(entry, entryState)
            activeWindowId = target.id
            return true
        }
        return false
    }

    private fun portalDirection(source: PetRect, target: PetRect): String? = when {
        target.left >= source.right - 1f && verticalOverlap(source, target) -> "right"
        target.right <= source.left + 1f && verticalOverlap(source, target) -> "left"
        target.top >= source.bottom - 1f && horizontalOverlap(source, target) -> "bottom"
        target.bottom <= source.top + 1f && horizontalOverlap(source, target) -> "top"
        else -> null
    }

    private fun entryDirection(movementDirection: String): String = when (movementDirection) {
        "right" -> "left"
        "left" -> "right"
        "bottom" -> "top"
        "top" -> "bottom"
        else -> movementDirection
    }

    private fun portalRayOrigin(position: PetPoint, direction: String, petHalfSize: Float): PetPoint {
        val half = petHalfSize.coerceAtLeast(0f)
        return when (direction) {
            "right" -> position.copy(x = position.x + half)
            "left" -> position.copy(x = position.x - half)
            "bottom" -> position.copy(y = position.y + half)
            "top" -> position.copy(y = position.y - half)
            else -> position
        }
    }

    private fun verticalOverlap(a: PetRect, b: PetRect): Boolean = min(a.bottom, b.bottom) > maxOf(a.top, b.top)
    private fun horizontalOverlap(a: PetRect, b: PetRect): Boolean = min(a.right, b.right) > maxOf(a.left, b.left)

    private fun stateFromEntry(entry: PetWindowEntry, sourceState: PetState = state): PetState = sourceState.copy(
        position = entry.position,
        mode = entry.mode,
        // Target ids and idle timers are scoped to the source host.
        targetId = null,
        idleTicksRemaining = 0,
        avoidTargetId = null,
        horizontalVelocity = entry.velocity.x,
        verticalVelocity = entry.velocity.y,
        facing = entry.facing,
    )

    private fun clampInner(value: Float, extent: Float, petHalfSize: Float): Float {
        val half = petHalfSize.coerceAtLeast(0f)
        return value.coerceIn(half, maxOf(half, extent - half))
    }
}
