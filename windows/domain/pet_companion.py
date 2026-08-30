"""Platform-neutral state and geometry rules for the Bingzi companion.

The domain knows nothing about Tkinter or image files. Presentation registers
window-space targets and feeds pointer and navigation events into this reducer.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
import math
from typing import Iterable, Sequence


PET_TICK_MS = 16
PET_DISPLAY_SIZE = 112
MOTION_ACCELERATION = 0.5
CRUISE_SPEED = 4.0
FALL_GRAVITY = 0.55
MAX_FALL_SPEED = 10.0
HARD_LANDING_SPEED = 7.0
BOUNCE_COUNT = 2
FIRST_BOUNCE_SPEED = 5.0
BOUNCE_DECAY = 0.55
CENTER_BIAS_WEIGHT = 0.65
EDGE_PENALTY_RATIO = 0.15
IDLE_TICKS = 24


class PetMode(str, Enum):
    IDLE = "idle"
    SLIDE = "slide"
    ROLL = "roll"
    FLY = "fly"
    FALL = "fall"
    BOUNCE = "bounce"
    DRAGGING = "dragging"


class PetFacing(str, Enum):
    LEFT = "left"
    RIGHT = "right"


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
        """Project onto the closest side of the expanded rectangle."""
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
            candidate.x - point.x,
            candidate.y - point.y,
        ))

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

    def shifted_path(self, pet_size: float = 0.0) -> tuple[PetPoint, ...]:
        offset = max(0.0, pet_size)
        return tuple(PetPoint(point.x, point.y - offset) for point in self.path)

    def support_segment(self, point: PetPoint, pet_size: float = 0.0) -> tuple[PetPoint, PetPoint]:
        """Return this target's legal horizontal or vertical support line."""
        margin = max(0.0, pet_size)
        if self.kind != PetTargetKind.EDGE:
            y = self.rect.top - margin
            return PetPoint(self.rect.left - margin, y), PetPoint(self.rect.right + margin, y)
        if self.rect.height > self.rect.width:
            candidates = (self.rect.left - margin, self.rect.right + margin)
            x = min(candidates, key=lambda candidate: abs(candidate - point.x))
            return (
                PetPoint(x, self.rect.top - margin),
                PetPoint(x, self.rect.bottom + margin),
            )
        y = self.rect.top - margin
        return (
            PetPoint(self.rect.left - margin, y),
            PetPoint(self.rect.right + margin, y),
        )

    def support_point(self, point: PetPoint, pet_size: float = 0.0) -> PetPoint:
        if self.kind == PetTargetKind.CHART and self.path:
            return min(self.shifted_path(pet_size), key=lambda sample: math.hypot(
                point.x - sample.x,
                point.y - sample.y,
            ))
        start, end = self.support_segment(point, pet_size)
        if math.isclose(start.x, end.x, abs_tol=1e-6):
            low, high = sorted((start.y, end.y))
            return PetPoint(start.x, min(max(point.y, low), high))
        low, high = sorted((start.x, end.x))
        return PetPoint(min(max(point.x, low), high), start.y)

    def distance_to(self, point: PetPoint, pet_size: float = 0.0) -> float:
        support = self.support_point(point, pet_size)
        return math.hypot(point.x - support.x, point.y - support.y)


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
    movement_speed: float = 0.0
    vertical_velocity: float = 0.0
    bounces_remaining: int = 0
    facing: PetFacing = PetFacing.RIGHT


def _facing_after_move(previous: PetPoint, current: PetPoint, facing: PetFacing) -> PetFacing:
    if current.x < previous.x - 1e-6:
        return PetFacing.LEFT
    if current.x > previous.x + 1e-6:
        return PetFacing.RIGHT
    return facing


def nearest_pet_target(
    position: PetPoint,
    targets: Iterable[PetTarget],
    pet_size: float = 0.0,
    viewport: PetRect | None = None,
) -> PetTarget | None:
    """Choose a valid target with stable ties and an interior-screen bias."""
    valid_targets = tuple(target for target in targets if target.valid)
    if not valid_targets:
        return None
    margin = max(0.0, pet_size)
    if viewport is None:
        return min(valid_targets, key=lambda target: target.distance_to(position, margin))
    centre = PetPoint(
        viewport.left + viewport.width / 2.0,
        viewport.top + viewport.height / 2.0,
    )
    diagonal = math.hypot(viewport.width, viewport.height)

    def score(target: PetTarget) -> float:
        support = viewport.clamp(target.support_point(position, margin), margin)
        centre_support = viewport.clamp(target.support_point(centre, margin), margin)
        position_distance = math.hypot(position.x - support.x, position.y - support.y)
        centre_distance = math.hypot(centre.x - centre_support.x, centre.y - centre_support.y)
        edge_penalty = diagonal * EDGE_PENALTY_RATIO if target.kind == PetTargetKind.EDGE else 0.0
        return position_distance + CENTER_BIAS_WEIGHT * centre_distance + edge_penalty

    return min(valid_targets, key=score)


def on_navigation(state: PetState) -> PetState:
    return replace(
        state,
        mode=PetMode.FALL,
        target_id=None,
        idle_ticks_remaining=0,
        path_index=0,
        path_direction=1,
        roll_corners=0,
        avoid_target_id=None,
        movement_speed=0.0,
        vertical_velocity=0.0,
        bounces_remaining=0,
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
        movement_speed=0.0,
        vertical_velocity=0.0,
        bounces_remaining=0,
    )


def move_drag(
    state: PetState,
    pointer: PetPoint,
    viewport: PetRect,
    pet_size: float = 0.0,
) -> PetState:
    if state.mode != PetMode.DRAGGING:
        return state
    position = viewport.clamp(pointer, max(0.0, pet_size))
    return replace(
        state,
        position=position,
        facing=_facing_after_move(state.position, position, state.facing),
    )


def release_drag(state: PetState) -> PetState:
    return replace(
        state,
        mode=PetMode.IDLE,
        target_id=None,
        idle_ticks_remaining=0,
        path_index=0,
        path_direction=1,
        roll_corners=0,
        avoid_target_id=None,
        movement_speed=0.0,
        vertical_velocity=0.0,
        bounces_remaining=0,
    )


def _fall_landing_point(position: PetPoint, target: PetTarget, pet_size: float) -> PetPoint:
    if target.kind == PetTargetKind.CHART and target.path:
        path = target.shifted_path(pet_size)
        below = tuple(point for point in path if point.y >= position.y)
        candidates = below or path
        return min(candidates, key=lambda point: math.hypot(
            position.x - point.x,
            position.y - point.y,
        ))
    return target.support_point(position, pet_size)


def _target_for_state(
    state: PetState,
    targets: Sequence[PetTarget],
    pet_size: float,
    viewport: PetRect,
) -> PetTarget | None:
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
            if _fall_landing_point(state.position, target, pet_size).y > state.position.y + 1e-6
        )
        return nearest_pet_target(state.position, below or valid, pet_size)
    return nearest_pet_target(state.position, valid, pet_size, viewport)


def _step_towards(position: PetPoint, goal: PetPoint, distance: float) -> tuple[PetPoint, bool]:
    delta_x = goal.x - position.x
    delta_y = goal.y - position.y
    remaining = math.hypot(delta_x, delta_y)
    if remaining <= max(0.0, distance) or remaining == 0:
        return goal, True
    ratio = distance / remaining
    return PetPoint(position.x + delta_x * ratio, position.y + delta_y * ratio), False


def _step_vertical_first(position: PetPoint, goal: PetPoint, distance: float) -> tuple[PetPoint, bool]:
    if not math.isclose(position.y, goal.y, abs_tol=1e-6):
        delta_y = goal.y - position.y
        if abs(delta_y) <= distance:
            next_position = PetPoint(position.x, goal.y)
            return next_position, math.isclose(position.x, goal.x, abs_tol=1e-6)
        return PetPoint(position.x, position.y + math.copysign(distance, delta_y)), False
    return _step_towards(position, goal, distance)


def _eased_distance(current_speed: float, remaining: float, cruise_speed: float) -> tuple[float, float]:
    if remaining <= 1e-6:
        return 0.0, 0.0
    accelerated = min(max(0.0, cruise_speed), max(0.0, current_speed) + MOTION_ACCELERATION)
    braking_limit = math.sqrt(2.0 * MOTION_ACCELERATION * remaining)
    next_speed = min(accelerated, braking_limit)
    distance = min(remaining, next_speed)
    if remaining - distance < 0.5:
        return remaining, 0.0
    return distance, next_speed


def _accelerated_path_distance(current_speed: float, remaining: float, cruise_speed: float) -> tuple[float, float]:
    if remaining <= 1e-6:
        return 0.0, 0.0
    next_speed = min(max(0.0, cruise_speed), max(0.0, current_speed) + MOTION_ACCELERATION)
    distance = min(remaining, next_speed)
    if remaining - distance <= 1.0:
        return remaining, 0.0
    return distance, next_speed


def _nearest_path_index(position: PetPoint, path: Sequence[PetPoint]) -> int:
    return min(range(len(path)), key=lambda index: math.hypot(
        path[index].x - position.x,
        path[index].y - position.y,
    ))


def _path_goal_index(position: PetPoint, path: Sequence[PetPoint], direction: int) -> int:
    index = _nearest_path_index(position, path)
    if math.hypot(path[index].x - position.x, path[index].y - position.y) <= 1e-6:
        if direction > 0 and index < len(path) - 1:
            return index + 1
        if direction < 0 and index > 0:
            return index - 1
    return index


def _path_distance_to_endpoint(
    position: PetPoint,
    path: Sequence[PetPoint],
    index: int,
    direction: int,
) -> float:
    distance = math.hypot(path[index].x - position.x, path[index].y - position.y)
    cursor = index
    endpoint = len(path) - 1 if direction > 0 else 0
    while cursor != endpoint:
        following = cursor + direction
        distance += math.hypot(
            path[following].x - path[cursor].x,
            path[following].y - path[cursor].y,
        )
        cursor = following
    return distance


def _move_along_path(
    position: PetPoint,
    path: Sequence[PetPoint],
    index: int,
    direction: int,
    distance: float,
) -> tuple[PetPoint, int, bool]:
    endpoint = len(path) - 1 if direction > 0 else 0
    cursor = min(max(index, 0), len(path) - 1)
    current = position
    remaining_step = max(0.0, distance)
    while True:
        goal = path[cursor]
        segment = math.hypot(goal.x - current.x, goal.y - current.y)
        if segment > remaining_step + 1e-6:
            current, _ = _step_towards(current, goal, remaining_step)
            return current, cursor, False
        current = goal
        remaining_step = max(0.0, remaining_step - segment)
        if cursor == endpoint:
            return current, cursor, True
        cursor += direction
        if remaining_step <= 1e-6:
            return current, cursor, False


def _advance_bounce(
    state: PetState,
    target: PetTarget,
    viewport: PetRect,
    pet_size: float,
) -> PetState:
    landing = viewport.clamp(_fall_landing_point(state.position, target, pet_size), pet_size)
    velocity = min(MAX_FALL_SPEED, state.vertical_velocity + FALL_GRAVITY)
    next_y = state.position.y + velocity
    if velocity > 0.0 and next_y >= landing.y:
        position = viewport.clamp(PetPoint(state.position.x, landing.y), pet_size)
        if state.bounces_remaining > 1:
            return replace(
                state,
                position=position,
                vertical_velocity=-(FIRST_BOUNCE_SPEED * BOUNCE_DECAY),
                bounces_remaining=state.bounces_remaining - 1,
                movement_speed=0.0,
            )
        return replace(
            state,
            position=position,
            mode=PetMode.IDLE,
            idle_ticks_remaining=IDLE_TICKS,
            movement_speed=0.0,
            vertical_velocity=0.0,
            bounces_remaining=0,
        )
    position = viewport.clamp(PetPoint(state.position.x, next_y), pet_size)
    return replace(state, position=position, vertical_velocity=velocity, movement_speed=0.0)


def _advance_fall(
    state: PetState,
    target: PetTarget,
    viewport: PetRect,
    pet_size: float,
) -> PetState:
    landing = viewport.clamp(_fall_landing_point(state.position, target, pet_size), pet_size)
    if landing.y <= state.position.y + 1e-6:
        return replace(
            state,
            mode=PetMode.FLY,
            target_id=target.id,
            movement_speed=0.0,
            vertical_velocity=0.0,
        )
    velocity = min(MAX_FALL_SPEED, max(0.0, state.vertical_velocity) + FALL_GRAVITY)
    next_y = state.position.y + velocity
    if next_y < landing.y:
        position = viewport.clamp(PetPoint(state.position.x, next_y), pet_size)
        return replace(
            state,
            position=position,
            mode=PetMode.FALL,
            target_id=target.id,
            movement_speed=0.0,
            vertical_velocity=velocity,
        )
    position = viewport.clamp(PetPoint(state.position.x, landing.y), pet_size)
    if not math.isclose(position.x, landing.x, abs_tol=1e-6):
        return replace(
            state,
            position=position,
            mode=PetMode.FLY,
            target_id=target.id,
            movement_speed=0.0,
            vertical_velocity=0.0,
        )
    if velocity >= HARD_LANDING_SPEED:
        return replace(
            state,
            position=position,
            mode=PetMode.BOUNCE,
            target_id=target.id,
            movement_speed=0.0,
            vertical_velocity=-FIRST_BOUNCE_SPEED,
            bounces_remaining=BOUNCE_COUNT,
        )
    return replace(
        state,
        position=position,
        mode=PetMode.IDLE,
        target_id=target.id,
        idle_ticks_remaining=IDLE_TICKS,
        movement_speed=0.0,
        vertical_velocity=0.0,
        bounces_remaining=0,
    )


def _advance_chart(
    state: PetState,
    target: PetTarget,
    viewport: PetRect,
    speed: float,
    pet_size: float,
) -> PetState:
    path = tuple(viewport.clamp(point, pet_size) for point in target.shifted_path(pet_size))
    same_target = state.target_id == target.id and state.mode == PetMode.SLIDE
    direction = state.path_direction if same_target else 1
    index = (
        min(max(state.path_index, 0), len(path) - 1)
        if same_target
        else _path_goal_index(state.position, path, direction)
    )
    remaining = _path_distance_to_endpoint(state.position, path, index, direction)
    distance, movement_speed = _accelerated_path_distance(state.movement_speed, remaining, speed)
    position, index, reached_endpoint = _move_along_path(
        state.position,
        path,
        index,
        direction,
        distance,
    )
    position = viewport.clamp(position, pet_size)
    facing = _facing_after_move(state.position, position, state.facing)
    if reached_endpoint:
        completed_ends = state.roll_corners + 1 if same_target else 1
        if completed_ends >= 2:
            return replace(
                state,
                position=position,
                mode=PetMode.IDLE,
                target_id=None,
                idle_ticks_remaining=IDLE_TICKS,
                path_index=0,
                path_direction=1,
                roll_corners=0,
                avoid_target_id=target.id,
                movement_speed=0.0,
                facing=facing,
            )
        direction *= -1
        index = max(0, min(len(path) - 1, index + direction))
        return replace(
            state,
            position=position,
            mode=PetMode.SLIDE,
            target_id=target.id,
            path_index=index,
            path_direction=direction,
            roll_corners=completed_ends,
            movement_speed=0.0,
            vertical_velocity=0.0,
            facing=facing,
        )
    return replace(
        state,
        position=position,
        mode=PetMode.SLIDE,
        target_id=target.id,
        path_index=index,
        path_direction=direction,
        roll_corners=state.roll_corners if same_target else 0,
        movement_speed=movement_speed,
        vertical_velocity=0.0,
        facing=facing,
    )


def _advance_support(
    state: PetState,
    target: PetTarget,
    viewport: PetRect,
    speed: float,
    pet_size: float,
) -> PetState:
    raw_start, raw_end = target.support_segment(state.position, pet_size)
    start = viewport.clamp(raw_start, pet_size)
    end = viewport.clamp(raw_end, pet_size)
    if math.isclose(start.x, end.x, abs_tol=1e-6):
        low, high = sorted((start.y, end.y))
        support = PetPoint(start.x, min(max(state.position.y, low), high))
    else:
        low, high = sorted((start.x, end.x))
        support = PetPoint(min(max(state.position.x, low), high), start.y)
    on_support = math.hypot(
        support.x - state.position.x,
        support.y - state.position.y,
    ) <= 1e-6
    rolling = state.target_id == target.id and on_support
    if rolling:
        direction = 1 if state.path_direction >= 0 else -1
        goal = end if direction > 0 else start
    else:
        direction = state.path_direction
        goal = support
    remaining = math.hypot(goal.x - state.position.x, goal.y - state.position.y)
    distance, movement_speed = _eased_distance(state.movement_speed, remaining, speed)
    position, arrived = (
        _step_towards(state.position, goal, distance)
        if rolling
        else _step_vertical_first(state.position, goal, distance)
    )
    position = viewport.clamp(position, pet_size)
    facing = _facing_after_move(state.position, position, state.facing)
    if not arrived:
        return replace(
            state,
            position=position,
            mode=PetMode.ROLL if rolling else PetMode.FLY,
            target_id=target.id,
            path_direction=direction,
            roll_corners=state.roll_corners if rolling else 0,
            movement_speed=movement_speed,
            vertical_velocity=0.0,
            facing=facing,
        )
    if rolling:
        completed_ends = state.roll_corners + 1
        if completed_ends >= 2:
            return replace(
                state,
                position=position,
                mode=PetMode.IDLE,
                target_id=None,
                idle_ticks_remaining=IDLE_TICKS,
                path_direction=1,
                roll_corners=0,
                avoid_target_id=target.id,
                movement_speed=0.0,
                vertical_velocity=0.0,
                facing=facing,
            )
        return replace(
            state,
            position=position,
            mode=PetMode.ROLL,
            target_id=target.id,
            path_direction=-direction,
            roll_corners=completed_ends,
            movement_speed=0.0,
            vertical_velocity=0.0,
            facing=facing,
        )
    return replace(
        state,
        position=position,
        mode=PetMode.IDLE,
        target_id=target.id,
        idle_ticks_remaining=IDLE_TICKS,
        movement_speed=0.0,
        vertical_velocity=0.0,
        facing=facing,
    )


def advance_pet(
    state: PetState,
    targets: Iterable[PetTarget],
    viewport: PetRect,
    *,
    speed: float = CRUISE_SPEED,
    pet_size: float = 0.0,
) -> PetState:
    margin = max(0.0, pet_size)
    if state.mode == PetMode.DRAGGING:
        return replace(state, position=viewport.clamp(state.position, margin))
    if state.idle_ticks_remaining > 0:
        return replace(
            state,
            idle_ticks_remaining=state.idle_ticks_remaining - 1,
            movement_speed=0.0,
        )
    target_list = tuple(targets)
    target = _target_for_state(state, target_list, margin, viewport)
    if target is None:
        return replace(
            state,
            position=viewport.clamp(state.position, margin),
            mode=PetMode.IDLE,
            target_id=None,
            movement_speed=0.0,
            vertical_velocity=0.0,
            bounces_remaining=0,
        )
    if state.mode == PetMode.BOUNCE:
        return _advance_bounce(state, target, viewport, margin)
    if state.mode == PetMode.FALL:
        return _advance_fall(state, target, viewport, margin)
    if target.kind == PetTargetKind.CHART and target.path:
        return _advance_chart(state, target, viewport, max(0.0, speed), margin)
    return _advance_support(state, target, viewport, max(0.0, speed), margin)


class PetCompanion:
    """Small reducer wrapper convenient for presentation controllers."""

    def __init__(
        self,
        state: PetState | None = None,
        *,
        speed: float = CRUISE_SPEED,
        pet_size: float = 0.0,
    ):
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


nearestPetTarget = nearest_pet_target
onNavigation = on_navigation
beginDrag = begin_drag
moveDrag = move_drag
releaseDrag = release_drag
