"""Pure presentation geometry for moving Bingzi between Tk windows.

The reducer owns motion state; this module only maps a centre point between
screen-space window rectangles.  Keeping the portal calculation Tk-free makes
it deterministic in unit tests and keeps platform APIs at the presentation
edge.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import math
from typing import Iterable

from domain.pet_companion import (
    FALL_GRAVITY,
    FALL_TIME_STEP_SECONDS,
    PET_TICK_MS,
    PetFacing,
    PetMode,
    PetPoint,
    PetRect,
    PetState,
)


@dataclass(frozen=True)
class PetWindow:
    """A mapped application window in screen coordinates."""

    id: str
    rect: PetRect
    order: int = 0
    mapped: bool = True
    viewable: bool = True

    @property
    def eligible(self) -> bool:
        return self.mapped and self.viewable and self.rect.valid


@dataclass(frozen=True)
class PetWindowEntry:
    position: PetPoint
    mode: PetMode
    velocity: PetPoint
    facing: PetFacing


@dataclass(frozen=True)
class PetWindowHit:
    window: PetWindow
    entry_time: float
    intersection_world: PetPoint


def _clamp(value: float, low: float, high: float) -> float:
    return min(max(value, low), max(low, high))


def interpolate_pet_position(
    start: PetPoint,
    end: PetPoint,
    elapsed_ms: float,
    duration_ms: float = PET_TICK_MS,
) -> PetPoint:
    """Linearly interpolate presentation position without changing state."""
    try:
        duration = float(duration_ms)
        elapsed = float(elapsed_ms)
    except (TypeError, ValueError):
        return end
    if not math.isfinite(duration) or duration <= 0.0:
        return end
    if not math.isfinite(elapsed):
        elapsed = duration if elapsed > 0 else 0.0
    progress = _clamp(elapsed / duration, 0.0, 1.0)
    return PetPoint(
        start.x + (end.x - start.x) * progress,
        start.y + (end.y - start.y) * progress,
    )


interpolatePetPosition = interpolate_pet_position


def map_pet_entry(
    source_rect: PetRect,
    target_rect: PetRect,
    position_in_source: PetPoint,
    direction: str,
    pet_half_size: float,
    *,
    mode: PetMode = PetMode.FLING,
    velocity: PetPoint = PetPoint(0.0, 0.0),
    facing: PetFacing = PetFacing.RIGHT,
    dragging: bool = False,
) -> PetWindowEntry:
    """Map a pet centre through a left/right/top/bottom portal.

    ``source_rect`` and ``target_rect`` are screen-space rectangles while
    ``position_in_source`` is local to the source window.  Horizontal portals
    enter exactly one full sprite radius inside the target.  A top portal keeps
    the centre one radius above the target so FALL integration can visibly
    bring it through the title bar; this also prevents a frame of clipping.
    """
    # Keep direction handling identical to the Compose adapter and the
    # versioned contract.  Presentation callers often derive this value from
    # a platform edge enum whose string form is not guaranteed to be lower
    # case.
    direction = str(direction).lower()
    half = max(0.0, float(pet_half_size))
    world_x = source_rect.left + position_in_source.x
    world_y = source_rect.top + position_in_source.y
    target_min_x = target_rect.left + half
    target_max_x = max(target_min_x, target_rect.right - half)
    local_x = _clamp(world_x, target_min_x, target_max_x) - target_rect.left
    if direction == "left":
        local_x = half
        local_y = _clamp(world_y, target_rect.top + half, target_rect.bottom - half) - target_rect.top
        next_mode = PetMode.DRAGGING if dragging else mode
    elif direction == "right":
        local_x = max(half, target_rect.width - half)
        local_y = _clamp(world_y, target_rect.top + half, target_rect.bottom - half) - target_rect.top
        next_mode = PetMode.DRAGGING if dragging else mode
    elif direction == "top":
        local_y = -half
        next_mode = PetMode.DRAGGING if dragging else PetMode.FALL
    elif direction == "bottom":
        # A bottom entry is the counterpart of a top entry: the pet starts
        # just below the destination viewport and continues its upward arc
        # before gravity brings it back through the edge.  Keeping the
        # outside-in position avoids a one-frame teleport to the top/bottom
        # clamp and matches the Android presentation adapter.
        local_y = target_rect.height + half
        next_mode = PetMode.DRAGGING if dragging else mode
    else:
        raise ValueError(f"unknown pet window entry direction: {direction!r}")
    if direction in {"top", "bottom"}:
        local_x = _clamp(world_x, target_min_x, target_max_x) - target_rect.left
    return PetWindowEntry(
        position=PetPoint(local_x, local_y),
        mode=next_mode,
        velocity=PetPoint(float(velocity.x), float(velocity.y)),
        facing=facing,
    )


def map_pet_between_windows(*args, **kwargs) -> PetWindowEntry:
    """Descriptive alias for :func:`map_pet_entry`."""
    return map_pet_entry(*args, **kwargs)


mapPetEntry = map_pet_entry
mapPetBetweenWindows = map_pet_between_windows


def _candidate_score(
    source: PetWindow,
    candidate: PetWindow,
    direction: str,
    world: PetPoint,
    *,
    allow_overlap: bool = False,
    motion: PetPoint | None = None,
    max_time: float | None = None,
) -> tuple[float, float, int]:
    source_rect, target = source.rect, candidate.rect
    if direction == "right":
        gap = target.left - source_rect.right
        if target.right <= world.x + 1e-6:
            return math.inf, math.inf, candidate.order
    elif direction == "left":
        gap = source_rect.left - target.right
        if target.left >= world.x - 1e-6:
            return math.inf, math.inf, candidate.order
    elif direction == "bottom":
        gap = target.top - source_rect.bottom
        if target.bottom <= world.y + 1e-6:
            return math.inf, math.inf, candidate.order
    elif direction == "top":
        gap = source_rect.top - target.bottom
        if target.top >= world.y - 1e-6:
            return math.inf, math.inf, candidate.order
    else:
        return math.inf, math.inf, candidate.order
    # A portal is a boundary between two hosts, not an arbitrary overlap.
    # Reject rectangles that already overlap the source along the movement
    # axis; otherwise a newly-created modal dialog (which normally sits on
    # top of the root window) can be selected by an autonomous tick and steal
    # the pet from its real owner.  Explicit drag hand-off may opt into an
    # overlap-aware path at the caller when the pointer is intentionally moved
    # into such a dialog.
    if not allow_overlap and gap < -1e-6:
        return math.inf, math.inf, candidate.order
    if motion is None or not (
        math.isfinite(motion.x)
        and math.isfinite(motion.y)
        and math.hypot(motion.x, motion.y) > 1e-9
    ):
        motion = {
            "right": PetPoint(1.0, 0.0),
            "left": PetPoint(-1.0, 0.0),
            "bottom": PetPoint(0.0, 1.0),
            "top": PetPoint(0.0, -1.0),
        }[direction]

    entry_time = ray_rect_entry_time(world, motion, target, max_time=max_time)
    if entry_time is None:
        return math.inf, math.inf, candidate.order
    return entry_time, 0.0, candidate.order


def ray_rect_entry_time(
    origin: PetPoint,
    motion: PetPoint,
    rect: PetRect,
    max_time: float | None = None,
) -> float | None:
    """Return the first non-negative ray/AABB entry within ``max_time``."""
    if not rect.valid or not all(
        math.isfinite(value)
        for value in (origin.x, origin.y, motion.x, motion.y)
    ):
        return None
    entry_time = 0.0
    exit_time = math.inf
    for origin_value, velocity, minimum, maximum in (
        (origin.x, motion.x, rect.left, rect.right),
        (origin.y, motion.y, rect.top, rect.bottom),
    ):
        if abs(velocity) <= 1e-9:
            if origin_value < minimum - 1e-6 or origin_value > maximum + 1e-6:
                return None
            continue
        first = (minimum - origin_value) / velocity
        second = (maximum - origin_value) / velocity
        axis_entry, axis_exit = sorted((first, second))
        entry_time = max(entry_time, axis_entry)
        exit_time = min(exit_time, axis_exit)
        if exit_time < entry_time - 1e-9:
            return None
    if exit_time < -1e-9 or not math.isfinite(entry_time):
        return None
    entry_time = max(0.0, entry_time)
    if max_time is not None:
        try:
            limit = float(max_time)
        except (TypeError, ValueError):
            limit = math.inf
        if math.isfinite(limit) and entry_time > max(0.0, limit) + 1e-9:
            return None
    return entry_time


rayRectEntryTime = ray_rect_entry_time


def select_adjacent_window_hit(
    source: PetWindow,
    candidates: Iterable[PetWindow],
    direction: str,
    position_in_source: PetPoint,
    *,
    allow_overlap: bool = False,
    motion: PetPoint | None = None,
    max_time: float | None = None,
) -> PetWindowHit | None:
    """Return the earliest eligible window plus its exact ray intersection."""
    direction = str(direction).lower()
    world = PetPoint(source.rect.left + position_in_source.x, source.rect.top + position_in_source.y)
    if motion is None or not (
        math.isfinite(motion.x)
        and math.isfinite(motion.y)
        and math.hypot(motion.x, motion.y) > 1e-9
    ):
        motion = {
            "right": PetPoint(1.0, 0.0),
            "left": PetPoint(-1.0, 0.0),
            "bottom": PetPoint(0.0, 1.0),
            "top": PetPoint(0.0, -1.0),
        }.get(direction)
    if motion is None:
        return None
    eligible = (candidate for candidate in candidates if candidate.eligible and candidate.id != source.id)
    ranked = sorted(
        (
            (
                _candidate_score(
                    source,
                    candidate,
                    direction,
                    world,
                    allow_overlap=allow_overlap,
                    motion=motion,
                    max_time=max_time,
                ),
                candidate,
            )
            for candidate in eligible
        ),
        key=lambda item: item[0],
    )
    if not ranked or not math.isfinite(ranked[0][0][0]):
        return None
    entry_time = ranked[0][0][0]
    return PetWindowHit(
        window=ranked[0][1],
        entry_time=entry_time,
        intersection_world=PetPoint(
            world.x + motion.x * entry_time,
            world.y + motion.y * entry_time,
        ),
    )


def select_adjacent_window(
    source: PetWindow,
    candidates: Iterable[PetWindow],
    direction: str,
    position_in_source: PetPoint,
    *,
    allow_overlap: bool = False,
    motion: PetPoint | None = None,
    max_time: float | None = None,
) -> PetWindow | None:
    """Choose the first mapped/viewable window intersecting the motion ray."""
    hit = select_adjacent_window_hit(
        source,
        candidates,
        direction,
        position_in_source,
        allow_overlap=allow_overlap,
        motion=motion,
        max_time=max_time,
    )
    return hit.window if hit is not None else None


find_adjacent_window = select_adjacent_window
selectAdjacentWindow = select_adjacent_window
selectAdjacentWindowHit = select_adjacent_window_hit
findAdjacentWindow = find_adjacent_window


class PetWindowCoordinator:
    """Presentation-only registry that keeps one state across Tk hosts.

    Tk windows register/unregister themselves as they map and unmap.  The
    coordinator never touches learning data; it only maps the transient pet
    state through an adjacent portal and exposes the currently active host.
    """

    def __init__(self, initial_state: PetState | None = None) -> None:
        self.state = initial_state or PetState(PetPoint(0.0, 0.0))
        self.has_state = initial_state is not None
        self.active_window_id: str | None = None
        self._windows: dict[str, PetWindow] = {}
        self._targets_by_window: dict[str, tuple[object, ...]] = {}

    def register_window(
        self,
        window: PetWindow,
        *,
        active: bool = False,
        pet_half_size: float = 0.0,
    ) -> None:
        self._windows[window.id] = window
        if active:
            self.activate(window.id, pet_half_size=pet_half_size)

    def unregister_window(self, window_id: str, *, pet_half_size: float = 0.0) -> None:
        closing = self._windows.pop(window_id, None)
        self._targets_by_window.pop(window_id, None)
        if self.active_window_id != window_id:
            return
        fallback = next((item for item in reversed(tuple(self._windows.values())) if item.eligible), None)
        if fallback is None:
            # A host can be mapped but briefly not viewable during a focus/map
            # transition. Keep a valid mapped fallback instead of dropping
            # the transient pet state altogether.
            fallback = next(
                (
                    item
                    for item in reversed(tuple(self._windows.values()))
                    if item.mapped and item.rect.valid
                ),
                None,
            )
        if closing is not None and fallback is not None:
            movement = _portal_direction(closing.rect, fallback.rect)
            if movement is not None:
                entry_direction = _entry_direction(movement)
                entry = map_pet_entry(
                    closing.rect,
                    fallback.rect,
                    self.state.position,
                    entry_direction,
                    pet_half_size,
                    mode=self.state.mode,
                    velocity=self.state.velocity,
                    facing=self.state.facing,
                    dragging=self.state.mode == PetMode.DRAGGING,
                )
                self.state = self._state_from_entry(entry)
            else:
                # Preserve absolute screen position for a non-adjacent
                # fallback (for example after a resize), and clear state that
                # referred to controls in the closing host.
                world = PetPoint(
                    closing.rect.left + self.state.position.x,
                    closing.rect.top + self.state.position.y,
                )
                self.state = replace(
                    self.state,
                    position=PetPoint(
                        _clamp(
                            world.x - fallback.rect.left,
                            max(0.0, pet_half_size),
                            max(max(0.0, pet_half_size), fallback.rect.width - max(0.0, pet_half_size)),
                        ),
                        _clamp(
                            world.y - fallback.rect.top,
                            max(0.0, pet_half_size),
                            max(max(0.0, pet_half_size), fallback.rect.height - max(0.0, pet_half_size)),
                        ),
                    ),
                    target_id=None,
                    idle_ticks_remaining=0,
                    avoid_target_id=None,
                )
        self.active_window_id = fallback.id if fallback is not None else None

    # Kotlin/Compose uses lower-camel names for the same presentation API.
    # Keep aliases here so platform-level tests and adapters can share the
    # migration contract without branching on naming conventions.
    @property
    def activeWindowId(self) -> str | None:  # noqa: N802 - cross-platform alias
        return self.active_window_id

    def registerWindow(
        self,
        window: PetWindow,
        active: bool = False,
        petHalfSize: float = 0.0,  # noqa: N803
    ) -> None:
        self.register_window(window, active=active, pet_half_size=petHalfSize)

    def unregisterWindow(self, window_id: str, petHalfSize: float = 0.0) -> None:  # noqa: N803
        self.unregister_window(window_id, pet_half_size=petHalfSize)

    def windows(self) -> list[PetWindow]:
        return list(self._windows.values())

    def activate(self, window_id: str, *, pet_half_size: float = 0.0) -> bool:
        target = self._windows.get(window_id)
        if target is None or not target.eligible:
            return False
        previous = self._windows.get(self.active_window_id or "")
        if previous is not None and previous.eligible and previous.id != target.id:
            movement = _portal_direction(previous.rect, target.rect)
            if movement is not None:
                entry = map_pet_entry(
                    previous.rect,
                    target.rect,
                    self.state.position,
                    _entry_direction(movement),
                    pet_half_size,
                    mode=self.state.mode,
                    velocity=self.state.velocity,
                    facing=self.state.facing,
                    dragging=self.state.mode == PetMode.DRAGGING,
                )
                self.state = self._state_from_entry(entry)
            else:
                world = PetPoint(
                    previous.rect.left + self.state.position.x,
                    previous.rect.top + self.state.position.y,
                )
                self.state = replace(
                    self.state,
                    position=PetPoint(
                        _clamp(
                            world.x - target.rect.left,
                            max(0.0, pet_half_size),
                            max(max(0.0, pet_half_size), target.rect.width - max(0.0, pet_half_size)),
                        ),
                        _clamp(
                            world.y - target.rect.top,
                            max(0.0, pet_half_size),
                            max(max(0.0, pet_half_size), target.rect.height - max(0.0, pet_half_size)),
                        ),
                    ),
                    target_id=None,
                    idle_ticks_remaining=0,
                    avoid_target_id=None,
                )
        self.active_window_id = target.id
        return True

    def update_state(self, state: PetState) -> None:
        self.state = state
        self.has_state = True

    def updateState(self, state: PetState) -> None:  # noqa: N802 - cross-platform alias
        self.update_state(state)

    def migrate_if_needed(
        self,
        window_id: str,
        pet_half_size: float,
        lookahead_seconds: float | None = None,
        *,
        lookaheadSeconds: float | None = None,  # noqa: N803 - cross-platform alias
        allow_overlap: bool = False,
        fall_unit_scale: float = 1.0,
        fallUnitScale: float | None = None,  # noqa: N803 - cross-platform alias
    ) -> bool:
        source = self._windows.get(window_id)
        if source is None or not source.eligible or self.active_window_id != window_id:
            return False
        state = self.state
        half = max(0.0, float(pet_half_size))
        # Check every edge crossed during the next fixed tick.  This is
        # important for high-speed flings: the reducer can otherwise reflect
        # at a local wall before presentation gets a chance to migrate the
        # state through an adjacent host.
        if lookaheadSeconds is not None:
            lookahead_seconds = lookaheadSeconds
        if fallUnitScale is not None:
            fall_unit_scale = fallUnitScale
        duration = (
            FALL_TIME_STEP_SECONDS
            if lookahead_seconds is None
            else max(0.0, float(lookahead_seconds))
        )
        for crossing_time, direction in _predicted_exit_times(
            state,
            PetRect(0.0, 0.0, source.rect.width, source.rect.height),
            half,
            duration=duration,
            fall_unit_scale=fall_unit_scale,
        ):
            crossing_state = state_at_exit(
                state,
                PetRect(0.0, 0.0, source.rect.width, source.rect.height),
                half,
                crossing_time,
                direction,
                fall_unit_scale=fall_unit_scale,
            )
            ray_origin = portal_ray_origin(crossing_state.position, direction, half)
            hit = select_adjacent_window_hit(
                source,
                self._windows.values(),
                direction,
                ray_origin,
                allow_overlap=allow_overlap,
                motion=crossing_state.velocity,
                max_time=max(0.0, duration - crossing_time),
            )
            if hit is None:
                continue
            intersection_in_source = PetPoint(
                hit.intersection_world.x - source.rect.left,
                hit.intersection_world.y - source.rect.top,
            )
            entry = map_pet_entry(
                source.rect,
                hit.window.rect,
                intersection_in_source,
                _entry_direction(direction),
                half,
                mode=crossing_state.mode,
                velocity=crossing_state.velocity,
                facing=crossing_state.facing,
                dragging=crossing_state.mode == PetMode.DRAGGING,
            )
            self.state = self._state_from_entry(entry, crossing_state)
            self.active_window_id = hit.window.id
            return True
        return False

    def migrateIfNeeded(
        self,
        window_id: str,
        petHalfSize: float,
        lookaheadSeconds: float | None = None,  # noqa: N803
        allowOverlap: bool = False,  # noqa: N803
        fallUnitScale: float = 1.0,  # noqa: N803
    ) -> bool:  # noqa: N802
        return self.migrate_if_needed(
            window_id,
            petHalfSize,
            lookahead_seconds=lookaheadSeconds,
            allow_overlap=allowOverlap,
            fall_unit_scale=fallUnitScale,
        )

    def update_targets(self, window_id: str, targets: Iterable[object]) -> None:
        """Keep presentation target snapshots scoped to each host."""
        self._targets_by_window[window_id] = tuple(targets)

    def updateTargets(self, window_id: str, targets: Iterable[object]) -> None:  # noqa: N802
        self.update_targets(window_id, targets)

    def targets_for(self, window_id: str | None = None) -> tuple[object, ...]:
        key = self.active_window_id if window_id is None else window_id
        return self._targets_by_window.get(key or "", ())

    def targetsFor(self, window_id: str | None = None) -> tuple[object, ...]:  # noqa: N802
        return self.targets_for(window_id)

    def viewport_for(self, window_id: str | None = None) -> PetRect | None:
        key = self.active_window_id if window_id is None else window_id
        window = self._windows.get(key or "")
        if window is None:
            return None
        return PetRect(0.0, 0.0, window.rect.width, window.rect.height)

    def viewportFor(self, window_id: str | None = None) -> PetRect | None:  # noqa: N802
        return self.viewport_for(window_id)

    def world_position(self, window_id: str | None = None) -> PetPoint | None:
        key = self.active_window_id if window_id is None else window_id
        window = self._windows.get(key or "")
        if window is None:
            return None
        return PetPoint(
            window.rect.left + self.state.position.x,
            window.rect.top + self.state.position.y,
        )

    def worldPosition(self, window_id: str | None = None) -> PetPoint | None:  # noqa: N802
        return self.world_position(window_id)

    def _state_from_entry(
        self,
        entry: PetWindowEntry,
        source_state: PetState | None = None,
    ) -> PetState:
        source = source_state or self.state
        return PetState(
            position=entry.position,
            mode=entry.mode,
            target_id=None,
            idle_ticks_remaining=0,
            path_index=source.path_index,
            path_direction=source.path_direction,
            roll_corners=source.roll_corners,
            # Target/avoidance bookkeeping is local to the source host.  A
            # migrated state must not immediately skip an identically named
            # target in the destination or remain biased away from it.
            avoid_target_id=None,
            movement_speed=source.movement_speed,
            vertical_velocity=entry.velocity.y,
            bounces_remaining=source.bounces_remaining,
            facing=entry.facing,
            drag_offset=source.drag_offset,
            horizontal_velocity=entry.velocity.x,
        )


def _portal_direction(source: PetRect, target: PetRect) -> str | None:
    if target.left >= source.right - 1.0 and _vertical_overlap(source, target):
        return "right"
    if target.right <= source.left + 1.0 and _vertical_overlap(source, target):
        return "left"
    if target.top >= source.bottom - 1.0 and _horizontal_overlap(source, target):
        return "bottom"
    if target.bottom <= source.top + 1.0 and _horizontal_overlap(source, target):
        return "top"
    return None


def portal_direction(source: PetRect, target: PetRect) -> str | None:
    """Return the source edge facing an adjacent target window.

    The returned value is a *movement* direction (``right`` means the pet
    leaves the source through its right edge).  Keeping this geometry helper
    in the Tk-free presentation module lets lifecycle code use exactly the
    same adjacency rule as the coordinator and the Android adapter.
    """
    return _portal_direction(source, target)


portalDirection = portal_direction


def _entry_direction(movement_direction: str) -> str:
    return {
        "right": "left",
        "left": "right",
        "bottom": "top",
        "top": "bottom",
    }.get(movement_direction, movement_direction)


def portal_ray_origin(
    position: PetPoint,
    direction: str,
    pet_half_size: float,
) -> PetPoint:
    """Move a centre at a host clamp to the sprite edge that crossed it."""
    half = max(0.0, float(pet_half_size))
    return {
        "right": PetPoint(position.x + half, position.y),
        "left": PetPoint(position.x - half, position.y),
        "bottom": PetPoint(position.x, position.y + half),
        "top": PetPoint(position.x, position.y - half),
    }.get(str(direction).lower(), position)


portalRayOrigin = portal_ray_origin


def _predicted_exit_times(
    state: PetState,
    viewport: PetRect,
    pet_half_size: float,
    *,
    duration: float = FALL_TIME_STEP_SECONDS,
    fall_unit_scale: float = 1.0,
) -> list[tuple[float, str]]:
    """Return outward portal crossings during the next fixed simulation tick.

    The domain reducer intentionally reflects a fling at a local wall.  A
    presentation host must therefore inspect the trajectory *before* ticking,
    otherwise a fast pet can hit and bounce inside one tick without ever being
    handed to an adjacent host.  Horizontal motion is linear; vertical motion
    includes the same constant gravity used by the reducer.  Results are
    sorted by the earliest continuous crossing, with registration-independent
    directional tie breaking left to the caller's target selection.
    """
    half = max(0.0, float(pet_half_size))
    dt = max(0.0, float(duration))
    x, y = float(state.position.x), float(state.position.y)
    vx, vy = float(state.horizontal_velocity), float(state.vertical_velocity)
    # A drag has no physical velocity.  Its presentation adapter calls this
    # method after constraining the centre, so only an already crossed edge is
    # eligible here; pointer-driven migration remains event based.
    if state.mode == PetMode.DRAGGING:
        result: list[tuple[float, str]] = []
        if x >= viewport.right - half - 1e-6:
            result.append((0.0, "right"))
        if x <= viewport.left + half + 1e-6:
            result.append((0.0, "left"))
        if y >= viewport.bottom - half - 1e-6:
            result.append((0.0, "bottom"))
        if y <= viewport.top + half + 1e-6:
            result.append((0.0, "top"))
        return result

    result = []
    # ``viewport`` may be expressed in world coordinates by direct callers;
    # use its edges rather than assuming a local origin at (0, 0).
    left = viewport.left + half
    right = max(left, viewport.right - half)
    top = viewport.top + half
    bottom = max(top, viewport.bottom - half)
    if vx > 1e-9:
        if x >= right - 1e-6:
            result.append((0.0, "right"))
        else:
            t = (right - x) / vx
            if -1e-9 <= t <= dt + 1e-9:
                result.append((max(0.0, t), "right"))
    elif vx < -1e-9:
        if x <= left + 1e-6:
            result.append((0.0, "left"))
        else:
            t = (left - x) / vx
            if -1e-9 <= t <= dt + 1e-9:
                result.append((max(0.0, t), "left"))

    # Solve 0.5*g*t^2 + vy*t + (y-edge) = 0.  Only roots whose velocity is
    # outward at contact are portal candidates; an upward fling that has not
    # reached the top edge is not treated as an immediate migration.
    try:
        scale = max(0.0, float(fall_unit_scale))
    except (TypeError, ValueError):
        scale = 1.0
    if not math.isfinite(scale):
        scale = 1.0 if scale > 0 else 0.0
    gravity = FALL_GRAVITY * scale if state.mode in {PetMode.FLING, PetMode.FALL} else 0.0
    for edge, direction, sign in (
        (top, "top", -1),
        (bottom, "bottom", 1),
    ):
        if direction == "top" and y <= edge + 1e-6 and vy <= 1e-9:
            result.append((0.0, direction))
            continue
        if direction == "bottom" and y >= edge - 1e-6 and vy >= -1e-9:
            result.append((0.0, direction))
            continue
        a = 0.5 * gravity
        b = vy
        c = y - edge
        roots: list[float]
        if abs(a) <= 1e-12:
            roots = [] if abs(b) <= 1e-12 else [-c / b]
        else:
            discriminant = b * b - 4.0 * a * c
            if discriminant < -1e-9:
                roots = []
            else:
                root = math.sqrt(max(0.0, discriminant))
                roots = [(-b - root) / (2.0 * a), (-b + root) / (2.0 * a)]
        for t in sorted(roots):
            if t < -1e-9 or t > dt + 1e-9:
                continue
            t = max(0.0, t)
            contact_velocity = vy + gravity * t
            if sign * contact_velocity < -1e-6:
                continue
            # ``top`` is reached with an upward (negative) velocity; ``bottom``
            # is reached while descending.  At exactly zero, retain the side
            # only when the current point is already touching it.
            if direction == "top" and contact_velocity > 1e-6:
                continue
            if direction == "bottom" and contact_velocity < -1e-6:
                continue
            result.append((t, direction))
            break
    result.sort(key=lambda item: item[0])
    return result


def predicted_exit_times(
    state: PetState,
    viewport: PetRect,
    pet_half_size: float,
    *,
    duration: float = FALL_TIME_STEP_SECONDS,
    fall_unit_scale: float = 1.0,
    fallUnitScale: float | None = None,  # noqa: N803 - cross-platform alias
) -> tuple[tuple[float, str], ...]:
    """Public read-only wrapper used by Tk/Compose adapters before a tick."""
    if fallUnitScale is not None:
        fall_unit_scale = fallUnitScale
    return tuple(
        _predicted_exit_times(
            state,
            viewport,
            pet_half_size,
            duration=duration,
            fall_unit_scale=fall_unit_scale,
        )
    )


predictedExitTimes = predicted_exit_times


def state_at_exit(
    state: PetState,
    viewport: PetRect,
    pet_half_size: float,
    elapsed_seconds: float,
    direction: str,
    *,
    fall_unit_scale: float = 1.0,
    fallUnitScale: float | None = None,  # noqa: N803 - cross-platform alias
) -> PetState:
    """Return the transient state at a predicted portal crossing.

    Portal prediction is continuous, while the reducer itself advances in
    fixed ticks.  Mapping the tick-start state would discard the portion of
    the trajectory before the edge and create a visible jump in the target
    host.  This helper evaluates the same closed-form projectile equation at
    the crossing time and pins only the crossed coordinate to the inner edge.
    """
    if fallUnitScale is not None:
        fall_unit_scale = fallUnitScale
    try:
        elapsed = max(0.0, float(elapsed_seconds))
    except (TypeError, ValueError):
        elapsed = 0.0
    try:
        scale = max(0.0, float(fall_unit_scale))
    except (TypeError, ValueError):
        scale = 1.0
    if not math.isfinite(scale):
        scale = 1.0 if scale > 0 else 0.0
    gravity = FALL_GRAVITY * scale if state.mode in {PetMode.FLING, PetMode.FALL} else 0.0
    vx = float(state.horizontal_velocity)
    vy = float(state.vertical_velocity) + gravity * elapsed
    position = PetPoint(
        state.position.x + vx * elapsed,
        state.position.y + state.vertical_velocity * elapsed + 0.5 * gravity * elapsed * elapsed,
    )
    half = max(0.0, float(pet_half_size))
    direction = str(direction).lower()
    if direction == "left":
        position = PetPoint(viewport.left + half, position.y)
    elif direction == "right":
        position = PetPoint(max(viewport.left + half, viewport.right - half), position.y)
    elif direction == "top":
        position = PetPoint(position.x, viewport.top + half)
    elif direction == "bottom":
        position = PetPoint(position.x, max(viewport.top + half, viewport.bottom - half))
    return replace(
        state,
        position=position,
        horizontal_velocity=vx,
        vertical_velocity=vy,
    )


stateAtExit = state_at_exit


def _vertical_overlap(a: PetRect, b: PetRect) -> bool:
    return min(a.bottom, b.bottom) > max(a.top, b.top)


def _horizontal_overlap(a: PetRect, b: PetRect) -> bool:
    return min(a.right, b.right) > max(a.left, b.left)
