"""Platform-neutral state and geometry rules for the Bingzi companion.

The domain knows nothing about Tkinter or image files.  Presentation registers
screen-space targets and feeds pointer/navigation events into these functions.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
import math
from typing import Iterable, Sequence


class PetMode(str, Enum):
    IDLE = "idle"
    SLIDE = "slide"
    ROLL = "roll"
    FLY = "fly"
    FALL = "fall"
    DRAGGING = "dragging"


class PetTargetKind(str, Enum):
    CONTROL = "control"
    SURFACE = "surface"
    CHART = "chart"
    EDGE = "edge"


@dataclass(frozen=True)
class PetPoint:
    x: float
    y: float


@dataclass(frozen=True)
class PetRect:
    """A rectangle represented as ``x, y, width, height``."""

    x: float
    y: float
    width: float
    height: float

    @property
    def left(self) -> float:
        return self.x

    @property
    def top(self) -> float:
        return self.y

    @property
    def right(self) -> float:
        return self.x + self.width

    @property
    def bottom(self) -> float:
        return self.y + self.height

    @property
    def valid(self) -> bool:
        return self.width > 0 and self.height > 0

    def closest_point(self, point: PetPoint, margin: float = 0.0) -> PetPoint:
        margin = max(0.0, margin)
        return PetPoint(
            min(max(point.x, self.left - margin), self.right + margin),
            min(max(point.y, self.top - margin), self.bottom + margin),
        )

    def boundary_point(self, point: PetPoint, margin: float = 0.0) -> PetPoint:
        """Project a point onto the nearest edge of the expanded rectangle."""
        margin = max(0.0, margin)
        left, right = self.left - margin, self.right + margin
        top, bottom = self.top - margin, self.bottom + margin
        if point.x < left or point.x > right or point.y < top or point.y > bottom:
            return self.closest_point(point, margin)
        candidates = (
            PetPoint(point.x, top),
            PetPoint(right, point.y),
            PetPoint(point.x, bottom),
            PetPoint(left, point.y),
        )
        return min(candidates, key=lambda candidate: math.hypot(
            candidate.x - point.x, candidate.y - point.y,
        ))

    def next_boundary_corner(self, point: PetPoint, margin: float = 0.0) -> PetPoint:
        """Move clockwise along either horizontal or vertical target borders."""
        margin = max(0.0, margin)
        left, right = self.left - margin, self.right + margin
        top, bottom = self.top - margin, self.bottom + margin
        epsilon = 1e-6
        if abs(point.x - right) <= epsilon and abs(point.y - top) <= epsilon:
            return PetPoint(right, bottom)
        if abs(point.x - right) <= epsilon and abs(point.y - bottom) <= epsilon:
            return PetPoint(left, bottom)
        if abs(point.x - left) <= epsilon and abs(point.y - bottom) <= epsilon:
            return PetPoint(left, top)
        if abs(point.x - left) <= epsilon and abs(point.y - top) <= epsilon:
            return PetPoint(right, top)
        side_distances = (
            (abs(point.y - top), PetPoint(right, top)),
            (abs(point.x - right), PetPoint(right, bottom)),
            (abs(point.y - bottom), PetPoint(left, bottom)),
            (abs(point.x - left), PetPoint(left, top)),
        )
        return min(side_distances, key=lambda item: item[0])[1]

    def distance_to(self, point: PetPoint, margin: float = 0.0) -> float:
        closest = self.closest_point(point, margin)
        return math.hypot(point.x - closest.x, point.y - closest.y)

    def clamp(self, point: PetPoint, margin: float = 0.0) -> PetPoint:
        """Clamp a pet centre to this viewport, accounting for its half-size."""
        half = max(0.0, margin)
        min_x = self.left + half
        max_x = max(min_x, self.right - half)
        min_y = self.top + half
        max_y = max(min_y, self.bottom - half)
        return PetPoint(
            min(max(point.x, min_x), max_x),
            min(max(point.y, min_y), max_y),
        )


@dataclass(frozen=True)
class PetTarget:
    id: str
    kind: PetTargetKind
    rect: PetRect
    path: tuple[PetPoint, ...] = ()
    visible: bool = True

    @property
    def valid(self) -> bool:
        return bool(self.id) and self.visible and self.rect.valid

    def distance_to(self, point: PetPoint, margin: float = 0.0) -> float:
        if self.kind == PetTargetKind.CHART and self.path:
            return min(math.hypot(point.x - sample.x, point.y - sample.y) for sample in self.path)
        boundary = self.rect.boundary_point(point, margin)
        return math.hypot(point.x - boundary.x, point.y - boundary.y)


@dataclass(frozen=True)
class PetState:
    position: PetPoint
    mode: PetMode = PetMode.IDLE
    target_id: str | None = None
    idle_ticks_remaining: int = 0
    path_index: int = 0
    path_direction: int = 1
    roll_corners: int = 0
    avoid_target_id: str | None = None


def nearest_pet_target(
    position: PetPoint,
    targets: Iterable[PetTarget],
    pet_size: float = 0.0,
) -> PetTarget | None:
    """Return the closest valid target, preserving registration-order ties."""
    valid_targets = (target for target in targets if target.valid)
    return min(
        valid_targets,
        key=lambda target: target.distance_to(position, max(0.0, pet_size)),
        default=None,
    )


def on_navigation(state: PetState) -> PetState:
    """Drop the pet toward the next page's targets before resuming movement."""
    return replace(
        state,
        mode=PetMode.FALL,
        target_id=None,
        idle_ticks_remaining=0,
        path_index=0,
        path_direction=1,
        roll_corners=0,
        avoid_target_id=None,
    )


def begin_drag(state: PetState, pointer: PetPoint) -> PetState:
    return replace(
        state,
        position=pointer,
        mode=PetMode.DRAGGING,
        target_id=None,
        idle_ticks_remaining=0,
        path_index=0,
        path_direction=1,
        roll_corners=0,
        avoid_target_id=None,
    )


def move_drag(
    state: PetState,
    pointer: PetPoint,
    viewport: PetRect,
    pet_size: float = 0.0,
) -> PetState:
    if state.mode != PetMode.DRAGGING:
        return state
    return replace(state, position=viewport.clamp(pointer, max(0.0, pet_size)))


def release_drag(state: PetState) -> PetState:
    """Keep the release position; the next tick chooses a new target."""
    return replace(
        state,
        mode=PetMode.IDLE,
        target_id=None,
        idle_ticks_remaining=0,
        path_index=0,
        path_direction=1,
        roll_corners=0,
        avoid_target_id=None,
    )


def _target_for_state(state: PetState, targets: Sequence[PetTarget], pet_size: float) -> PetTarget | None:
    if state.target_id:
        for target in targets:
            if target.id == state.target_id and target.valid:
                return target
    valid = tuple(target for target in targets if target.valid)
    if state.avoid_target_id:
        alternatives = tuple(target for target in valid if target.id != state.avoid_target_id)
        if alternatives:
            valid = alternatives
    if state.mode == PetMode.FALL:
        below = tuple(
            target for target in valid
            if target.rect.bottom + max(0.0, pet_size) >= state.position.y
        )
        if below:
            return nearest_pet_target(state.position, below, pet_size)
    return nearest_pet_target(state.position, valid, pet_size)


def _step_towards(position: PetPoint, goal: PetPoint, distance: float) -> tuple[PetPoint, bool]:
    delta_x = goal.x - position.x
    delta_y = goal.y - position.y
    remaining = math.hypot(delta_x, delta_y)
    if remaining <= max(0.0, distance) or remaining == 0:
        return goal, True
    ratio = distance / remaining
    return PetPoint(position.x + delta_x * ratio, position.y + delta_y * ratio), False


def _step_vertical_first(position: PetPoint, goal: PetPoint, distance: float) -> tuple[PetPoint, bool]:
    """Fly on the vertical axis before correcting any remaining horizontal gap."""
    if not math.isclose(position.y, goal.y, abs_tol=1e-6):
        delta_y = goal.y - position.y
        if abs(delta_y) <= distance:
            return PetPoint(position.x, goal.y), math.isclose(position.x, goal.x, abs_tol=1e-6)
        return PetPoint(position.x, position.y + math.copysign(distance, delta_y)), False
    return _step_towards(position, goal, distance)


def _nearest_path_index(position: PetPoint, path: Sequence[PetPoint]) -> int:
    return min(range(len(path)), key=lambda index: math.hypot(
        path[index].x - position.x, path[index].y - position.y,
    ))


def _next_path_index(index: int, direction: int, size: int) -> tuple[int, int]:
    if size <= 1:
        return 0, 1
    direction = 1 if direction >= 0 else -1
    next_index = index + direction
    if next_index >= size:
        return size - 2, -1
    if next_index < 0:
        return 1, 1
    return next_index, direction


def _fall_goal(position: PetPoint, rect: PetRect, margin: float) -> PetPoint:
    """Choose a landing point below the pet and directly on the target border."""
    margin = max(0.0, margin)
    x = min(max(position.x, rect.left - margin), rect.right + margin)
    top = rect.top - margin
    bottom = rect.bottom + margin
    if top >= position.y:
        return PetPoint(x, top)
    if bottom >= position.y:
        return PetPoint(x, bottom)
    return rect.boundary_point(position, margin)


def advance_pet(
    state: PetState,
    targets: Iterable[PetTarget],
    viewport: PetRect,
    *,
    speed: float = 8.0,
    pet_size: float = 0.0,
) -> PetState:
    """Advance one deterministic animation tick without platform dependencies."""
    if state.mode == PetMode.DRAGGING:
        return replace(state, position=viewport.clamp(state.position, pet_size))
    if state.idle_ticks_remaining > 0:
        return replace(state, idle_ticks_remaining=state.idle_ticks_remaining - 1)
    target_list = tuple(targets)
    target = _target_for_state(state, target_list, pet_size)
    if target is None:
        return replace(state, position=viewport.clamp(state.position, pet_size), mode=PetMode.IDLE, target_id=None)

    if target.kind == PetTargetKind.CHART and target.path:
        index = (
            min(max(0, state.path_index), len(target.path) - 1)
            if state.target_id == target.id
            else _nearest_path_index(state.position, target.path)
        )
        direction = state.path_direction if state.target_id == target.id else 1
        position, arrived = _step_towards(state.position, target.path[index], speed)
        position = viewport.clamp(position, pet_size)
        if arrived:
            completed_cycle = (
                state.target_id == target.id
                and state.path_direction < 0
                and index == 0
            )
            if completed_cycle:
                return PetState(
                    position=position,
                    mode=PetMode.IDLE,
                    target_id=None,
                    idle_ticks_remaining=10,
                    avoid_target_id=target.id,
                )
            index, direction = _next_path_index(index, direction, len(target.path))
        return PetState(
            position=position,
            mode=PetMode.SLIDE,
            target_id=target.id,
            path_index=index,
            path_direction=direction,
        )

    boundary = target.rect.boundary_point(state.position, pet_size)
    on_boundary = math.hypot(
        boundary.x - state.position.x,
        boundary.y - state.position.y,
    ) <= 1e-6
    rolling = state.target_id == target.id and on_boundary
    if rolling:
        goal = target.rect.next_boundary_corner(state.position, pet_size)
    elif state.mode == PetMode.FALL:
        goal = _fall_goal(state.position, target.rect, pet_size)
    else:
        goal = boundary
    vertical_flight = target.kind != PetTargetKind.CHART and not rolling and (
        state.mode in {PetMode.FALL, PetMode.FLY} or state.target_id != target.id
    )
    position, arrived = (
        _step_vertical_first(state.position, goal, speed)
        if vertical_flight
        else _step_towards(state.position, goal, speed)
    )
    position = viewport.clamp(position, pet_size)
    if not arrived:
        mode = PetMode.FALL if state.mode == PetMode.FALL else (
            PetMode.SLIDE if target.kind == PetTargetKind.CHART and target.path
            else PetMode.ROLL if rolling
            else PetMode.FLY
        )
        return PetState(
            position=position,
            mode=mode,
            target_id=target.id,
            roll_corners=state.roll_corners if rolling else 0,
        )
    if rolling:
        completed_corners = state.roll_corners + 1
        if completed_corners >= 4:
            return PetState(
                position=position,
                mode=PetMode.IDLE,
                target_id=None,
                idle_ticks_remaining=10,
                avoid_target_id=target.id,
            )
        return PetState(
            position=position,
            mode=PetMode.ROLL,
            target_id=target.id,
            roll_corners=completed_corners,
        )
    return PetState(
        position=position,
        mode=PetMode.IDLE,
        target_id=target.id,
        idle_ticks_remaining=10,
    )


class PetCompanion:
    """Small reducer wrapper convenient for presentation controllers."""

    def __init__(self, state: PetState | None = None, *, speed: float = 8.0, pet_size: float = 0.0):
        self.state = state or PetState(PetPoint(0.0, 0.0))
        self.speed = speed
        self.pet_size = pet_size

    def navigate(self) -> PetState:
        self.state = on_navigation(self.state)
        return self.state

    def drag_start(self, pointer: PetPoint) -> PetState:
        self.state = begin_drag(self.state, pointer)
        return self.state

    def drag_move(self, pointer: PetPoint, viewport: PetRect) -> PetState:
        self.state = move_drag(self.state, pointer, viewport, self.pet_size)
        return self.state

    def drag_release(self) -> PetState:
        self.state = release_drag(self.state)
        return self.state

    def tick(self, targets: Iterable[PetTarget], viewport: PetRect) -> PetState:
        self.state = advance_pet(
            self.state,
            targets,
            viewport,
            speed=self.speed,
            pet_size=self.pet_size,
        )
        return self.state


# Aliases mirror the shared Kotlin names in documentation and make the
# cross-platform reducer easy to discover without changing Python naming style.
nearestPetTarget = nearest_pet_target
onNavigation = on_navigation
beginDrag = begin_drag
moveDrag = move_drag
releaseDrag = release_drag
