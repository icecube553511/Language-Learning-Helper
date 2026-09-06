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
# Chart motion intentionally accelerates more gently than ordinary flying.
# Keep the legacy ``MOTION_ACCELERATION`` value for controls and expose the
# contract value separately so existing callers retain their tuning.
CURVE_ACCELERATION = 0.25
CURVE_MOTION_ACCELERATION = CURVE_ACCELERATION
CURVE_LANDING_SPEED_LIMIT = 8.0
CURVE_DOWNHILL_TERMINAL_SPEED = 4.0
CURVE_DOWNHILL_RESPONSE_PER_TICK = 0.0625
CURVE_DIRECTION_EPSILON = 0.000001
FALL_TIME_STEP_SECONDS = PET_TICK_MS / 1000.0
FALL_GRAVITY = 2148.4375
FLING_GRAVITY = FALL_GRAVITY
FLING_HORIZONTAL_RESTITUTION = 0.72
MAX_SUBSTEP_SECONDS = 0.004
MAX_SUBSTEPS_PER_TICK = 8
RELEASE_VELOCITY_SAMPLE_WINDOW_MS = 120
MINIMUM_FLING_SPEED = 90.0
MAX_FLING_SPEED = 1800.0
MAX_FALL_SPEED = None
HARD_LANDING_SPEED = 437.5
BOUNCE_COUNT = 2
FIRST_BOUNCE_SPEED = 312.5
BOUNCE_DECAY = 0.55
CENTER_BIAS_WEIGHT = 0.65
EDGE_PENALTY_RATIO = 0.15
IDLE_TICKS = 24

# Cross-platform constant aliases (the Android domain uses the ``PET_*``
# spelling; retaining both avoids platform adapters having to special-case
# imports).
PET_CURVE_ACCELERATION = CURVE_ACCELERATION
PET_CURVE_MOTION_ACCELERATION = CURVE_MOTION_ACCELERATION
PET_CURVE_LANDING_SPEED_LIMIT = CURVE_LANDING_SPEED_LIMIT
PET_CURVE_DOWNHILL_TERMINAL_SPEED = CURVE_DOWNHILL_TERMINAL_SPEED
PET_CURVE_DOWNHILL_RESPONSE_PER_TICK = CURVE_DOWNHILL_RESPONSE_PER_TICK
PET_CURVE_DIRECTION_EPSILON = CURVE_DIRECTION_EPSILON
PET_FLING_GRAVITY = FLING_GRAVITY
PET_FLING_HORIZONTAL_RESTITUTION = FLING_HORIZONTAL_RESTITUTION
PET_MAX_SUBSTEP_SECONDS = MAX_SUBSTEP_SECONDS
PET_MAX_SUBSTEPS_PER_TICK = MAX_SUBSTEPS_PER_TICK
PET_RELEASE_VELOCITY_SAMPLE_WINDOW_MS = RELEASE_VELOCITY_SAMPLE_WINDOW_MS
PET_MINIMUM_FLING_SPEED = MINIMUM_FLING_SPEED
PET_MAX_FLING_SPEED = MAX_FLING_SPEED

_VIEWPORT_BOTTOM_TARGET_ID = "__viewport-bottom__"


class PetMode(str, Enum):
    IDLE = "idle"
    SLIDE = "slide"
    ROLL = "roll"
    FLY = "fly"
    FALL = "fall"
    BOUNCE = "bounce"
    DRAGGING = "dragging"
    FLING = "fling"


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
            path = self.shifted_path(pet_size)
            if len(path) == 1:
                return path[0]
            # A chart is a polyline, so its legal support includes every
            # point along each segment, not only the sampled vertices.
            return min(
                (_closest_point_on_segment(point, start, end) for start, end in zip(path, path[1:])),
                key=lambda sample: math.hypot(point.x - sample.x, point.y - sample.y),
            )
        start, end = self.support_segment(point, pet_size)
        if math.isclose(start.x, end.x, abs_tol=1e-6):
            low, high = sorted((start.y, end.y))
            return PetPoint(start.x, min(max(point.y, low), high))
        low, high = sorted((start.x, end.x))
        return PetPoint(min(max(point.x, low), high), start.y)

    def distance_to(self, point: PetPoint, pet_size: float = 0.0) -> float:
        support = self.support_point(point, pet_size)
        return math.hypot(point.x - support.x, point.y - support.y)


def _closest_point_on_segment(point: PetPoint, start: PetPoint, end: PetPoint) -> PetPoint:
    """Project ``point`` onto a finite segment, including its endpoints."""
    dx = end.x - start.x
    dy = end.y - start.y
    length_squared = dx * dx + dy * dy
    if length_squared <= 1e-12:
        return start
    ratio = ((point.x - start.x) * dx + (point.y - start.y) * dy) / length_squared
    ratio = min(1.0, max(0.0, ratio))
    return PetPoint(start.x + dx * ratio, start.y + dy * ratio)


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
    drag_offset: PetPoint | None = None
    # ``horizontal_velocity`` is non-zero only for a user fling.  Keeping it
    # beside the existing vertical component preserves compatibility with the
    # original reducer while making the two-dimensional projectile explicit.
    horizontal_velocity: float = 0.0
    # Signed arc speed in canonical chart-path order. ``None`` retains the
    # autonomous chart traversal; a numeric value marks physical chart contact.
    curve_velocity: float | None = None

    @property
    def velocity_x(self) -> float:
        """Alias used by presentation adapters and cross-platform tests."""
        return self.horizontal_velocity

    @property
    def velocity_y(self) -> float:
        return self.vertical_velocity

    @property
    def velocityX(self) -> float:  # noqa: N802 - cross-platform contract alias
        return self.horizontal_velocity

    @property
    def velocityY(self) -> float:  # noqa: N802 - cross-platform contract alias
        return self.vertical_velocity

    @property
    def velocity(self) -> PetPoint:
        return PetPoint(self.horizontal_velocity, self.vertical_velocity)

    @property
    def curveVelocity(self) -> float | None:  # noqa: N802 - contract alias
        return self.curve_velocity


@dataclass(frozen=True)
class PetMotionSample:
    """A constrained pet-centre sample captured during a drag."""

    timestamp_ms: float
    position: PetPoint


PetDragSample = PetMotionSample
PetVelocitySample = PetMotionSample


def _facing_after_move(previous: PetPoint, current: PetPoint, facing: PetFacing) -> PetFacing:
    if current.x < previous.x - 1e-6:
        return PetFacing.LEFT
    if current.x > previous.x + 1e-6:
        return PetFacing.RIGHT
    return facing


def _coerce_velocity(value: PetPoint | Sequence[float] | None) -> PetPoint:
    """Normalize public velocity inputs without leaking mutable containers."""
    if value is None:
        return PetPoint(0.0, 0.0)
    if isinstance(value, PetPoint):
        return PetPoint(float(value.x), float(value.y))
    try:
        x, y = value
        return PetPoint(float(x), float(y))
    except (TypeError, ValueError):
        return PetPoint(0.0, 0.0)


def limit_fling_velocity(
    velocity: PetPoint | Sequence[float],
    maximum: float = MAX_FLING_SPEED,
) -> PetPoint:
    """Limit a fling vector proportionally, preserving its tangent direction."""
    vector = _coerce_velocity(velocity)
    if not (math.isfinite(vector.x) and math.isfinite(vector.y)):
        return PetPoint(0.0, 0.0)
    try:
        maximum = float(maximum)
    except (TypeError, ValueError):
        maximum = MAX_FLING_SPEED
    if not math.isfinite(maximum):
        maximum = MAX_FLING_SPEED if maximum > 0 else 0.0
    maximum = max(0.0, maximum)
    magnitude = math.hypot(vector.x, vector.y)
    if not math.isfinite(magnitude):
        return PetPoint(0.0, 0.0)
    if magnitude <= maximum or magnitude <= 1e-9:
        return vector
    scale = maximum / magnitude
    return PetPoint(vector.x * scale, vector.y * scale)


def _sample_parts(sample) -> tuple[float, PetPoint] | None:
    """Accept ``(timestamp, point)`` samples and the convenient reversed form."""
    if isinstance(sample, PetMotionSample):
        return float(sample.timestamp_ms), sample.position
    if isinstance(sample, dict):
        timestamp = sample.get(
            "timeMs",
            sample.get("timestampMs", sample.get("timestamp_ms", sample.get("timestamp"))),
        )
        position = sample.get("position")
        if timestamp is None or position is None:
            return None
        try:
            if isinstance(position, PetPoint):
                return float(timestamp), position
            return float(timestamp), PetPoint(float(position[0]), float(position[1]))
        except (TypeError, ValueError, IndexError, KeyError):
            return None
    try:
        first, second = sample
    except (TypeError, ValueError):
        return None
    if isinstance(second, PetPoint):
        try:
            return float(first), second
        except (TypeError, ValueError):
            return None
    if isinstance(first, PetPoint):
        try:
            return float(second), first
        except (TypeError, ValueError):
            return None
    try:
        x, y = second
        return float(first), PetPoint(float(x), float(y))
    except (TypeError, ValueError):
        return None


def estimate_release_velocity(
    samples: Iterable[object],
    *,
    now_ms: float | None = None,
    window_ms: float = RELEASE_VELOCITY_SAMPLE_WINDOW_MS,
    nowMs: float | None = None,  # noqa: N803 - contract spelling
    windowMs: float | None = None,  # noqa: N803 - contract spelling
) -> PetPoint:
    """Estimate the terminal two-dimensional drag velocity.

    Samples are expected to contain monotonic millisecond timestamps and the
    *constrained* pet centre.  A weighted least-squares slope gives the latest
    samples more influence while remaining stable when Tk emits duplicate
    motion events.  The result is expressed in logical units per second.
    """
    if now_ms is None:
        now_ms = nowMs
    if windowMs is not None:
        window_ms = windowMs
    parsed = [part for sample in samples if (part := _sample_parts(sample)) is not None]
    if len(parsed) < 2:
        return PetPoint(0.0, 0.0)
    parsed.sort(key=lambda item: item[0])
    end_ms = float(now_ms) if now_ms is not None else parsed[-1][0]
    cutoff = end_ms - max(0.0, float(window_ms))
    recent = [item for item in parsed if item[0] >= cutoff and item[0] <= end_ms + 1e-6]
    if len(recent) < 2:
        recent = parsed[-2:]
    origin = recent[0][0]
    times = [(timestamp - origin) / 1000.0 for timestamp, _ in recent]
    # Remove zero/negative intervals; they do not carry velocity information.
    if times[-1] <= 1e-9:
        return PetPoint(0.0, 0.0)
    # Weights rise smoothly from .25 to 1.0 over the selected window.
    span = max(times[-1], 1e-9)
    weights = [0.25 + 0.75 * (value / span) for value in times]
    weight_total = sum(weights)
    mean_t = sum(weight * value for weight, value in zip(weights, times)) / weight_total
    denominator = sum(weight * (value - mean_t) ** 2 for weight, value in zip(weights, times))
    if denominator <= 1e-12:
        return PetPoint(0.0, 0.0)
    mean_x = sum(weight * point.x for weight, (_, point) in zip(weights, recent)) / weight_total
    mean_y = sum(weight * point.y for weight, (_, point) in zip(weights, recent)) / weight_total
    slope_x = sum(weight * (time - mean_t) * (point.x - mean_x) for weight, time, (_, point) in zip(weights, times, recent)) / denominator
    slope_y = sum(weight * (time - mean_t) * (point.y - mean_y) for weight, time, (_, point) in zip(weights, times, recent)) / denominator
    return PetPoint(slope_x, slope_y)


# Short aliases make the reducer convenient for platform adapters and golden
# tests without introducing another platform-specific velocity estimator.
estimate_drag_velocity = estimate_release_velocity
estimateReleaseVelocity = estimate_release_velocity


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
    # Edge targets are presentation hints used to roam a window boundary or
    # reach a portal.  When real content (control/surface/chart) is available,
    # prefer it so a card rebuild can never strand the companion on a thin
    # screen edge rolling in place.
    content_targets = tuple(target for target in valid_targets if target.kind != PetTargetKind.EDGE)
    candidates = content_targets if content_targets else valid_targets
    margin = max(0.0, pet_size)
    if viewport is None:
        return min(candidates, key=lambda target: target.distance_to(position, margin))
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

    return min(candidates, key=score)


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
        horizontal_velocity=0.0,
        curve_velocity=None,
        drag_offset=None,
    )


def begin_drag(state: PetState, pointer: PetPoint) -> PetState:
    offset = PetPoint(float(pointer.x) - state.position.x, float(pointer.y) - state.position.y)
    return replace(
        state,
        # Keep the historical reducer contract: the first pointer event is
        # already the constrained centre supplied by presentation.  The
        # offset is retained for callers that pass the raw grab point.
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
        horizontal_velocity=0.0,
        curve_velocity=None,
        drag_offset=offset,
    )


def move_drag(
    state: PetState,
    pointer: PetPoint,
    viewport: PetRect,
    pet_size: float = 0.0,
) -> PetState:
    if state.mode != PetMode.DRAGGING:
        return state
    offset = state.drag_offset or PetPoint(0.0, 0.0)
    position = viewport.clamp(
        PetPoint(pointer.x - offset.x, pointer.y - offset.y),
        max(0.0, pet_size),
    )
    return replace(
        state,
        position=position,
        facing=_facing_after_move(state.position, position, state.facing),
    )


def release_drag(
    state: PetState,
    targets: Iterable[PetTarget] = (),
    viewport: PetRect | None = None,
    pet_size: float = 0.0,
    release_velocity: PetPoint | Sequence[float] | None = None,
    *,
    velocity: PetPoint | Sequence[float] | None = None,
    releaseVelocity: PetPoint | Sequence[float] | None = None,  # noqa: N803
) -> PetState:
    margin = max(0.0, pet_size)
    if release_velocity is None:
        release_velocity = velocity if velocity is not None else releaseVelocity
    fling_velocity = limit_fling_velocity(release_velocity or PetPoint(0.0, 0.0))
    fling_speed = math.hypot(fling_velocity.x, fling_velocity.y)
    if fling_speed >= MINIMUM_FLING_SPEED:
        # A release vector takes precedence over support snapping.  This is
        # what makes a diagonal throw continue as a projectile even when the
        # pointer happens to leave the pet on a card edge.
        return replace(
            state,
            mode=PetMode.FLING,
            target_id=None,
            idle_ticks_remaining=0,
            path_index=0,
            path_direction=1,
            roll_corners=0,
            avoid_target_id=None,
            movement_speed=0.0,
            vertical_velocity=fling_velocity.y,
            bounces_remaining=0,
            horizontal_velocity=fling_velocity.x,
            curve_velocity=None,
            drag_offset=None,
        )
    support = next((
        target for target in targets
        if target.valid and _is_on_support(target, state.position, margin, viewport)
    ), None)
    if (
        support is not None
        and support.kind == PetTargetKind.CHART
        and support.path
        and viewport is not None
    ):
        return _chart_landing_state(
            state,
            support,
            state.position,
            PetPoint(0.0, 0.0),
            viewport,
            margin,
        )
    return replace(
        state,
        mode=PetMode.IDLE if support is not None else PetMode.FALL,
        target_id=support.id if support is not None else None,
        idle_ticks_remaining=IDLE_TICKS if support is not None else 0,
        path_index=0,
        path_direction=1,
        roll_corners=0,
        avoid_target_id=None,
        movement_speed=0.0,
        vertical_velocity=0.0,
        bounces_remaining=0,
        horizontal_velocity=0.0,
        curve_velocity=None,
        drag_offset=None,
    )


def _fall_landing_point(
    position: PetPoint,
    target: PetTarget,
    pet_size: float,
) -> PetPoint | None:
    if target.kind == PetTargetKind.CHART and target.path:
        path = target.shifted_path(pet_size)
        intersections: list[PetPoint] = []
        if len(path) == 1:
            if math.isclose(path[0].x, position.x, abs_tol=1e-6):
                intersections.append(path[0])
        else:
            for start, end in zip(path, path[1:]):
                minimum_x, maximum_x = sorted((start.x, end.x))
                if not minimum_x - 1e-6 <= position.x <= maximum_x + 1e-6:
                    continue
                delta_x = end.x - start.x
                if math.isclose(delta_x, 0.0, abs_tol=1e-6):
                    if math.isclose(position.x, start.x, abs_tol=1e-6):
                        minimum_y, maximum_y = sorted((start.y, end.y))
                        intersections.append(PetPoint(
                            position.x,
                            min(max(position.y, minimum_y), maximum_y),
                        ))
                else:
                    ratio = (position.x - start.x) / delta_x
                    intersections.append(PetPoint(
                        position.x,
                        start.y + (end.y - start.y) * ratio,
                    ))
        below = tuple(point for point in intersections if point.y >= position.y - 1e-6)
        return min(below, key=lambda point: point.y - position.y, default=None)

    start, end = target.support_segment(position, pet_size)
    if not math.isclose(start.y, end.y, abs_tol=1e-6):
        return None
    minimum_x, maximum_x = sorted((start.x, end.x))
    if not minimum_x - 1e-6 <= position.x <= maximum_x + 1e-6:
        return None
    point = PetPoint(position.x, start.y)
    return point if point.y >= position.y - 1e-6 else None


def _is_on_support(
    target: PetTarget,
    position: PetPoint,
    pet_size: float,
    viewport: PetRect | None,
) -> bool:
    if target.kind == PetTargetKind.CHART and target.path:
        points = target.shifted_path(pet_size)
        if viewport is not None:
            points = tuple(viewport.clamp(point, pet_size) for point in points)
        if len(points) == 1:
            return math.hypot(position.x - points[0].x, position.y - points[0].y) <= 1e-6
        return any(
            math.hypot(
                position.x - (closest := _closest_point_on_segment(position, start, end)).x,
                position.y - closest.y,
            ) <= 1e-6
            for start, end in zip(points, points[1:])
        )
    start, end = target.support_segment(position, pet_size)
    if viewport is not None:
        start = viewport.clamp(start, pet_size)
        end = viewport.clamp(end, pet_size)
    if math.isclose(start.x, end.x, abs_tol=1e-6):
        low, high = sorted((start.y, end.y))
        closest = PetPoint(start.x, min(max(position.y, low), high))
    else:
        low, high = sorted((start.x, end.x))
        closest = PetPoint(min(max(position.x, low), high), start.y)
    return math.hypot(position.x - closest.x, position.y - closest.y) <= 1e-6


def _target_for_state(
    state: PetState,
    targets: Sequence[PetTarget],
    pet_size: float,
    viewport: PetRect,
) -> PetTarget | None:
    # A falling pet must re-evaluate the vertical ray every tick. Geometry can
    # appear or move while it is falling; retaining an older, lower target
    # would let the pet pass through a newly available support above it.
    if state.target_id and state.mode != PetMode.FALL:
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
            if (
                (landing := _fall_landing_point(state.position, target, pet_size)) is not None
                and landing.y >= state.position.y - 1e-6
            )
        )
        return min(
            below,
            key=lambda target: (
                _fall_landing_point(state.position, target, pet_size).y - state.position.y
            ),
            default=None,
        )
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
    # ``cruise_speed`` is only a cap.  The shared contract fixes chart
    # acceleration independently so a larger legacy step cannot change the
    # curve dynamics.
    acceleration = CURVE_ACCELERATION
    accelerated = min(max(0.0, cruise_speed), max(0.0, current_speed) + acceleration)
    braking_limit = math.sqrt(2.0 * acceleration * remaining)
    next_speed = min(accelerated, braking_limit)
    distance = min(remaining, next_speed)
    if remaining - distance <= acceleration:
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
) -> tuple[PetPoint, int, bool, float]:
    endpoint = len(path) - 1 if direction > 0 else 0
    cursor = min(max(index, 0), len(path) - 1)
    current = position
    remaining_step = max(0.0, distance)
    while True:
        goal = path[cursor]
        segment = math.hypot(goal.x - current.x, goal.y - current.y)
        if segment > remaining_step + 1e-6:
            current, _ = _step_towards(current, goal, remaining_step)
            return current, cursor, False, 0.0
        current = goal
        remaining_step = max(0.0, remaining_step - segment)
        if cursor == endpoint:
            return current, cursor, True, remaining_step
        cursor += direction
        if remaining_step <= 1e-6:
            return current, cursor, False, 0.0


def _closest_path_segment(
    position: PetPoint,
    path: Sequence[PetPoint],
) -> tuple[int, PetPoint, PetPoint]:
    """Return segment index, projection, and canonical unit tangent."""
    candidates: list[tuple[float, int, PetPoint, PetPoint]] = []
    for index, (start, end) in enumerate(zip(path, path[1:])):
        dx = end.x - start.x
        dy = end.y - start.y
        length = math.hypot(dx, dy)
        if length <= 1e-9:
            continue
        projection = _closest_point_on_segment(position, start, end)
        distance = math.hypot(position.x - projection.x, position.y - projection.y)
        candidates.append((distance, index, projection, PetPoint(dx / length, dy / length)))
    if not candidates:
        fallback = path[0] if path else position
        return 0, fallback, PetPoint(1.0, 0.0)
    _, index, projection, tangent = min(candidates, key=lambda item: (item[0], item[1]))
    return index, projection, tangent


def _curve_downhill_direction(tangent: PetPoint) -> int:
    if tangent.y > CURVE_DIRECTION_EPSILON:
        return 1
    if tangent.y < -CURVE_DIRECTION_EPSILON:
        return -1
    return 1


def _curve_endpoint_is_downhill(
    path: Sequence[PetPoint],
    endpoint: int,
    direction: int,
) -> bool:
    """Return whether travel reached the locally downhill end segment."""
    segment = 0 if endpoint <= 0 else len(path) - 2
    start = path[segment]
    end = path[segment + 1]
    dx = end.x - start.x
    dy = end.y - start.y
    length = math.hypot(dx, dy)
    tangent = (
        PetPoint(dx / length, dy / length)
        if length > CURVE_DIRECTION_EPSILON
        else PetPoint(1.0, 0.0)
    )
    canonical_direction = -1 if direction < 0 else 1
    return canonical_direction == _curve_downhill_direction(tangent)


def _chart_landing_state(
    state: PetState,
    target: PetTarget,
    contact: PetPoint,
    incoming_velocity: PetPoint,
    viewport: PetRect,
    pet_size: float,
) -> PetState:
    """Resolve chart contact by projecting world velocity onto its tangent."""
    path = tuple(viewport.clamp(point, pet_size) for point in target.shifted_path(pet_size))
    if len(path) < 2:
        return replace(
            state,
            position=viewport.clamp(contact, pet_size),
            mode=PetMode.IDLE,
            target_id=target.id,
            idle_ticks_remaining=IDLE_TICKS,
            movement_speed=0.0,
            vertical_velocity=0.0,
            horizontal_velocity=0.0,
            curve_velocity=None,
        )
    segment, projection, tangent = _closest_path_segment(contact, path)
    projected_velocity = (
        incoming_velocity.x * tangent.x + incoming_velocity.y * tangent.y
    ) * FALL_TIME_STEP_SECONDS
    if not math.isfinite(projected_velocity):
        projected_velocity = 0.0
    curve_velocity = min(
        CURVE_LANDING_SPEED_LIMIT,
        max(-CURVE_LANDING_SPEED_LIMIT, projected_velocity),
    )
    if curve_velocity > CURVE_DIRECTION_EPSILON:
        direction = 1
    elif curve_velocity < -CURVE_DIRECTION_EPSILON:
        direction = -1
    else:
        curve_velocity = 0.0
        direction = _curve_downhill_direction(tangent)
    waypoint = segment + 1 if direction > 0 else segment
    return replace(
        state,
        position=viewport.clamp(projection, pet_size),
        mode=PetMode.SLIDE,
        target_id=target.id,
        idle_ticks_remaining=0,
        path_index=waypoint,
        path_direction=direction,
        roll_corners=0,
        avoid_target_id=None,
        movement_speed=abs(curve_velocity),
        vertical_velocity=0.0,
        bounces_remaining=0,
        horizontal_velocity=0.0,
        curve_velocity=curve_velocity,
        drag_offset=None,
    )


def _advance_landed_chart(
    state: PetState,
    target: PetTarget,
    path: Sequence[PetPoint],
    viewport: PetRect,
    pet_size: float,
) -> PetState:
    segment, projection, tangent = _closest_path_segment(state.position, path)
    downhill = _curve_downhill_direction(tangent)
    terminal = downhill * CURVE_DOWNHILL_TERMINAL_SPEED
    raw_velocity = float(state.curve_velocity or 0.0)
    if not math.isfinite(raw_velocity):
        raw_velocity = 0.0
    current_velocity = min(
        CURVE_LANDING_SPEED_LIMIT,
        max(-CURVE_LANDING_SPEED_LIMIT, raw_velocity),
    )
    curve_velocity = current_velocity + (
        terminal - current_velocity
    ) * CURVE_DOWNHILL_RESPONSE_PER_TICK
    if abs(terminal - curve_velocity) <= CURVE_DIRECTION_EPSILON:
        curve_velocity = terminal
    direction = (
        1 if curve_velocity > CURVE_DIRECTION_EPSILON
        else -1 if curve_velocity < -CURVE_DIRECTION_EPSILON
        else downhill
    )
    waypoint = segment + 1 if direction > 0 else segment
    start = projection if math.hypot(
        state.position.x - projection.x,
        state.position.y - projection.y,
    ) <= 1e-3 else state.position
    position, index, reached_endpoint, _ = _move_along_path(
        start,
        path,
        waypoint,
        direction,
        abs(curve_velocity),
    )
    position = viewport.clamp(position, pet_size)
    facing = _facing_after_move(state.position, position, state.facing)
    if reached_endpoint:
        endpoint = len(path) - 1 if direction > 0 else 0
        reached_downhill = _curve_endpoint_is_downhill(path, endpoint, direction)
        if reached_downhill:
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
                vertical_velocity=0.0,
                horizontal_velocity=0.0,
                curve_velocity=None,
                facing=facing,
            )
        reverse = -direction
        return replace(
            state,
            position=position,
            mode=PetMode.SLIDE,
            target_id=target.id,
            path_index=endpoint + reverse,
            path_direction=reverse,
            movement_speed=0.0,
            vertical_velocity=0.0,
            horizontal_velocity=0.0,
            curve_velocity=0.0,
            facing=facing,
        )
    return replace(
        state,
        position=position,
        mode=PetMode.SLIDE,
        target_id=target.id,
        idle_ticks_remaining=0,
        path_index=index,
        path_direction=direction,
        movement_speed=abs(curve_velocity),
        vertical_velocity=0.0,
        horizontal_velocity=0.0,
        curve_velocity=curve_velocity,
        facing=facing,
    )


def _gravity_step(vertical_velocity: float, *, allow_upward: bool = False) -> tuple[float, float]:
    initial_velocity = vertical_velocity if allow_upward else max(0.0, vertical_velocity)
    displacement = (
        initial_velocity * FALL_TIME_STEP_SECONDS
        + 0.5 * FALL_GRAVITY * FALL_TIME_STEP_SECONDS ** 2
    )
    return displacement, initial_velocity + FALL_GRAVITY * FALL_TIME_STEP_SECONDS


def _fall_impact_velocity(vertical_velocity: float, distance: float) -> float:
    # Preserve the signed incoming velocity for a portal entry that is still
    # travelling upward.  Energy uses v^2, so the eventual contact speed is
    # correct even when the pet first rises before falling back down.
    initial_velocity = float(vertical_velocity)
    return math.sqrt(max(
        0.0,
        initial_velocity * initial_velocity + 2.0 * FALL_GRAVITY * max(0.0, distance),
    ))


def _advance_bounce(
    state: PetState,
    target: PetTarget,
    viewport: PetRect,
    pet_size: float,
) -> PetState:
    landing = viewport.clamp(
        _fall_landing_point(state.position, target, pet_size)
        or target.support_point(state.position, pet_size),
        pet_size,
    )
    return _advance_bounce_at(
        state,
        landing,
        target.id,
        target.id,
        viewport,
        pet_size,
    )


def _advance_viewport_bottom_bounce(
    state: PetState,
    viewport: PetRect,
    pet_size: float,
) -> PetState:
    landing = viewport.clamp(PetPoint(state.position.x, viewport.bottom), pet_size)
    return _advance_bounce_at(
        state,
        landing,
        _VIEWPORT_BOTTOM_TARGET_ID,
        None,
        viewport,
        pet_size,
    )


def _advance_bounce_at(
    state: PetState,
    landing: PetPoint,
    bounce_target_id: str,
    resting_target_id: str | None,
    viewport: PetRect,
    pet_size: float,
) -> PetState:
    displacement, velocity = _gravity_step(state.vertical_velocity, allow_upward=True)
    next_y = state.position.y + displacement
    if velocity > 0.0 and next_y >= landing.y:
        position = viewport.clamp(PetPoint(state.position.x, landing.y), pet_size)
        if state.bounces_remaining > 1:
            return replace(
                state,
                position=position,
                target_id=bounce_target_id,
                vertical_velocity=-(FIRST_BOUNCE_SPEED * BOUNCE_DECAY),
                bounces_remaining=state.bounces_remaining - 1,
                movement_speed=0.0,
                horizontal_velocity=0.0,
                curve_velocity=None,
            )
        return replace(
            state,
            position=position,
            mode=PetMode.IDLE,
            target_id=resting_target_id,
            idle_ticks_remaining=IDLE_TICKS,
            movement_speed=0.0,
            vertical_velocity=0.0,
            bounces_remaining=0,
            horizontal_velocity=0.0,
            curve_velocity=None,
        )
    position = viewport.clamp(PetPoint(state.position.x, next_y), pet_size)
    return replace(
        state,
        position=position,
        mode=PetMode.BOUNCE,
        target_id=bounce_target_id,
        vertical_velocity=velocity,
        movement_speed=0.0,
        horizontal_velocity=0.0,
        curve_velocity=None,
    )


def _land_at_viewport_bottom(
    state: PetState,
    position: PetPoint,
    impact_velocity: float,
) -> PetState:
    if impact_velocity >= HARD_LANDING_SPEED:
        return replace(
            state,
            position=position,
            mode=PetMode.BOUNCE,
            target_id=_VIEWPORT_BOTTOM_TARGET_ID,
            idle_ticks_remaining=0,
            movement_speed=0.0,
            vertical_velocity=-FIRST_BOUNCE_SPEED,
            bounces_remaining=BOUNCE_COUNT,
            horizontal_velocity=0.0,
            curve_velocity=None,
        )
    return replace(
        state,
        position=position,
        mode=PetMode.IDLE,
        target_id=None,
        idle_ticks_remaining=IDLE_TICKS,
        movement_speed=0.0,
        vertical_velocity=0.0,
        bounces_remaining=0,
        horizontal_velocity=0.0,
        curve_velocity=None,
    )


def _advance_free_fall(
    state: PetState,
    viewport: PetRect,
    pet_size: float,
) -> PetState:
    # A FALL may enter through a neighbouring window's top portal with its
    # centre above the local viewport.  Preserve that y coordinate while
    # constraining only x; clamping the whole point here would make the first
    # frame teleport to the top edge instead of following the gravity arc.
    clamped_x = viewport.clamp(PetPoint(state.position.x, viewport.top + pet_size), pet_size).x
    current = PetPoint(clamped_x, state.position.y)
    bottom = viewport.clamp(PetPoint(clamped_x, viewport.bottom), pet_size)
    if current.y >= bottom.y - 1e-6:
        return _land_at_viewport_bottom(state, bottom, state.vertical_velocity)
    displacement, velocity = _gravity_step(
        state.vertical_velocity,
        allow_upward=state.position.y < viewport.top - 1e-6,
    )
    next_y = min(bottom.y, current.y + displacement)
    landed = math.isclose(next_y, bottom.y, abs_tol=1e-6)
    if landed:
        impact_velocity = _fall_impact_velocity(
            state.vertical_velocity,
            bottom.y - current.y,
        )
        return _land_at_viewport_bottom(state, bottom, impact_velocity)
    return replace(
        state,
        position=PetPoint(clamped_x, next_y),
        mode=PetMode.FALL,
        target_id=None,
        idle_ticks_remaining=0,
        movement_speed=0.0,
        vertical_velocity=velocity,
        bounces_remaining=0,
        curve_velocity=None,
    )


def _advance_fall(
    state: PetState,
    target: PetTarget,
    viewport: PetRect,
    pet_size: float,
) -> PetState:
    raw_landing = _fall_landing_point(state.position, target, pet_size)
    if raw_landing is None:
        return _advance_free_fall(replace(state, target_id=None), viewport, pet_size)
    landing = viewport.clamp(raw_landing, pet_size)
    if landing.y < state.position.y - 1e-6:
        return _advance_free_fall(replace(state, target_id=None), viewport, pet_size)
    if not math.isclose(landing.y, state.position.y, abs_tol=1e-6):
        displacement, velocity = _gravity_step(
            state.vertical_velocity,
            allow_upward=state.position.y < viewport.top - 1e-6,
        )
        next_y = state.position.y + displacement
        if next_y < landing.y:
            # Keep y outside the top edge while entering through a portal;
            # only x is constrained until the projectile crosses the viewport.
            constrained_x = viewport.clamp(
                PetPoint(state.position.x, viewport.top + pet_size),
                pet_size,
            ).x
            position = PetPoint(constrained_x, next_y)
            return replace(
                state,
                position=position,
                mode=PetMode.FALL,
                target_id=target.id,
                movement_speed=0.0,
                vertical_velocity=velocity,
                curve_velocity=None,
            )
    position = viewport.clamp(PetPoint(state.position.x, landing.y), pet_size)
    if not math.isclose(position.x, landing.x, abs_tol=1e-6):
        # FALL is a vertical-only state.  A clipped/shifted support that no
        # longer intersects the current x-ray is not a legal landing target;
        # keep x fixed and continue toward the synthetic viewport floor.
        return _advance_free_fall(replace(state, target_id=None), viewport, pet_size)
    impact_velocity = _fall_impact_velocity(
        state.vertical_velocity,
        landing.y - state.position.y,
    )
    if impact_velocity >= HARD_LANDING_SPEED:
        return replace(
            state,
            position=position,
            mode=PetMode.BOUNCE,
            target_id=target.id,
            movement_speed=0.0,
            vertical_velocity=-FIRST_BOUNCE_SPEED,
            bounces_remaining=BOUNCE_COUNT,
            horizontal_velocity=0.0,
            curve_velocity=None,
        )
    if target.kind == PetTargetKind.CHART and target.path:
        return _chart_landing_state(
            state,
            target,
            position,
            PetPoint(0.0, impact_velocity),
            viewport,
            pet_size,
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
        horizontal_velocity=0.0,
        curve_velocity=None,
    )


def _quadratic_positive_root(a: float, b: float, c: float, limit: float) -> float | None:
    """Return the earliest root in ``[0, limit]`` for a contact equation."""
    epsilon = 1e-9
    if abs(a) <= epsilon:
        if abs(b) <= epsilon:
            return 0.0 if abs(c) <= epsilon else None
        root = -c / b
        return root if -epsilon <= root <= limit + epsilon else None
    discriminant = b * b - 4.0 * a * c
    if discriminant < -epsilon:
        return None
    root_discriminant = math.sqrt(max(0.0, discriminant))
    roots = sorted(((-b - root_discriminant) / (2.0 * a), (-b + root_discriminant) / (2.0 * a)))
    for root in roots:
        if -epsilon <= root <= limit + epsilon:
            return max(0.0, min(limit, root))
    return None


def _quadratic_descending_root(a: float, b: float, c: float, limit: float) -> float | None:
    """Find the first root reached while moving from the positive side.

    Fling support collision can begin below a support while the pet is still
    travelling upward (for example after entering through a neighbouring
    window's lower edge).  Selecting only the first quadratic root would
    discard the later descending crossing.  This helper evaluates both roots
    and requires the signed velocity at contact to be non-negative, with the
    trajectory just before contact on/above the support.
    """
    epsilon = 1e-9
    if abs(a) <= epsilon:
        if abs(b) <= epsilon:
            return 0.0 if abs(c) <= epsilon else None
        roots = [-c / b]
    else:
        discriminant = b * b - 4.0 * a * c
        if discriminant < -epsilon:
            return None
        root_discriminant = math.sqrt(max(0.0, discriminant))
        roots = [
            (-b - root_discriminant) / (2.0 * a),
            (-b + root_discriminant) / (2.0 * a),
        ]
    for root in sorted(roots):
        if root < -epsilon or root > limit + epsilon:
            continue
        root = max(0.0, min(limit, root))
        contact_velocity = b + 2.0 * a * root
        if contact_velocity < -1e-6:
            continue
        if root > 1e-7:
            before = root - min(root, 1e-7)
            if a * before * before + b * before + c > 1e-5:
                continue
        elif c > 1e-5:
            continue
        return root
    return None


def _fling_target_contact_time(
    position: PetPoint,
    horizontal_velocity: float,
    vertical_velocity: float,
    target: PetTarget,
    pet_size: float,
    duration: float,
) -> float | None:
    """Find the first descending intersection with a horizontal support."""
    if target.kind == PetTargetKind.CHART and target.path:
        # Curves are represented by short line strips.  A conservative sample
        # over the strip endpoints prevents an upward fling from snapping to a
        # curve while still allowing a descending projectile to land on it.
        path = target.shifted_path(pet_size)
        candidates: list[float] = []
        for start, end in zip(path, path[1:]):
            minimum_x, maximum_x = sorted((start.x, end.x))
            if abs(horizontal_velocity) <= 1e-9:
                if not minimum_x - 1e-6 <= position.x <= maximum_x + 1e-6:
                    continue
                support_y = start.y + (end.y - start.y) * ((position.x - start.x) / (end.x - start.x)) if not math.isclose(end.x, start.x, abs_tol=1e-9) else min(start.y, end.y)
                root = _quadratic_descending_root(0.5 * FLING_GRAVITY, vertical_velocity, position.y - support_y, duration)
                if root is not None:
                    candidates.append(root)
                continue
            # Solve against the line y = m*x + q, yielding one quadratic.
            if math.isclose(end.x, start.x, abs_tol=1e-9):
                continue
            slope = (end.y - start.y) / (end.x - start.x)
            intercept = start.y - slope * start.x
            a = 0.5 * FLING_GRAVITY
            b = vertical_velocity - slope * horizontal_velocity
            c = position.y - slope * position.x - intercept
            root = _quadratic_descending_root(a, b, c, duration)
            if root is None:
                continue
            x_at = position.x + horizontal_velocity * root
            if minimum_x - 1e-6 <= x_at <= maximum_x + 1e-6:
                candidates.append(root)
        return min(candidates, default=None)

    start, end = target.support_segment(position, pet_size)
    if not math.isclose(start.y, end.y, abs_tol=1e-6):
        return None
    support_y = start.y
    minimum_x, maximum_x = sorted((start.x, end.x))
    # An upward fling cannot hit an upper support; the root check below also
    # handles a projectile that starts exactly on the support.
    root = _quadratic_descending_root(
        0.5 * FLING_GRAVITY,
        vertical_velocity,
        position.y - support_y,
        duration,
    )
    if root is None:
        return None
    x_at = position.x + horizontal_velocity * root
    if not minimum_x - 1e-6 <= x_at <= maximum_x + 1e-6:
        return None
    return root


def _fling_tangent_support_exit_time(
    position: PetPoint,
    horizontal_velocity: float,
    vertical_velocity: float,
    target: PetTarget,
    pet_size: float,
) -> float | None:
    """Return when a purely tangential fling leaves a horizontal support."""
    if (
        target.kind == PetTargetKind.CHART
        or abs(vertical_velocity) > 1e-6
        or abs(horizontal_velocity) <= 1e-9
    ):
        return None
    start, end = target.support_segment(position, pet_size)
    if not math.isclose(start.y, end.y, abs_tol=1e-6):
        return None
    if not math.isclose(position.y, start.y, abs_tol=1e-6):
        return None
    minimum_x, maximum_x = sorted((start.x, end.x))
    if not minimum_x - 1e-6 <= position.x <= maximum_x + 1e-6:
        return None
    if horizontal_velocity > 0.0:
        return max(0.0, (maximum_x - position.x) / horizontal_velocity)
    return max(0.0, (minimum_x - position.x) / horizontal_velocity)


def _advance_fling_substep(
    state: PetState,
    targets: Sequence[PetTarget],
    viewport: PetRect,
    pet_size: float,
    duration: float,
) -> PetState:
    """Integrate one fling substep, resolving the earliest wall/support hit."""
    position = state.position
    vx = float(state.horizontal_velocity)
    vy = float(state.vertical_velocity)
    remaining = max(0.0, duration)
    minimum_x = viewport.left + pet_size
    maximum_x = max(minimum_x, viewport.right - pet_size)
    minimum_y = viewport.top + pet_size
    maximum_y = max(minimum_y, viewport.bottom - pet_size)

    # A handful of iterations handles a very fast vector reflecting from a
    # wall and then reaching a support in the same 16 ms simulation tick.
    for _ in range(4):
        if remaining <= 1e-9:
            break
        # A horizontal throw that starts exactly on a support is a resting
        # contact, not a downward impact at t=0.  Keep the normal coordinate
        # constrained while the pet travels to the support edge, then resume
        # the regular projectile integration for the unused substep time.
        tangent_exit_times = [
            exit_time
            for target in targets
            if (
                exit_time := _fling_tangent_support_exit_time(
                    position,
                    vx,
                    vy,
                    target,
                    pet_size,
                )
            )
            is not None
        ]
        if tangent_exit_times:
            support_exit_time = max(tangent_exit_times)
            wall_time = math.inf
            wall_kind: str | None = None
            if vx > 1e-9:
                wall_time = max(0.0, (maximum_x - position.x) / vx)
                wall_kind = "right"
            elif vx < -1e-9:
                wall_time = max(0.0, (minimum_x - position.x) / vx)
                wall_kind = "left"
            travel_time = min(remaining, support_exit_time, wall_time)
            position = PetPoint(position.x + vx * travel_time, position.y)
            remaining -= travel_time
            if wall_kind is not None and wall_time <= support_exit_time + 1e-9 and wall_time <= travel_time + 1e-9:
                vx = -vx * FLING_HORIZONTAL_RESTITUTION
                position = PetPoint(
                    (minimum_x + 1e-6) if wall_kind == "left" else (maximum_x - 1e-6),
                    position.y,
                )
                continue
            if support_exit_time <= travel_time + 1e-9:
                position = PetPoint(
                    position.x + math.copysign(1e-6, vx),
                    position.y,
                )
                continue
            break
        candidates: list[tuple[float, str, PetTarget | None]] = []
        if vx > 1e-9:
            wall_time = (maximum_x - position.x) / vx
            if wall_time <= remaining + 1e-9:
                candidates.append((max(0.0, wall_time), "right", None))
        elif vx < -1e-9:
            wall_time = (minimum_x - position.x) / vx
            if wall_time <= remaining + 1e-9:
                candidates.append((max(0.0, wall_time), "left", None))

        for target in targets:
            contact = _fling_target_contact_time(position, vx, vy, target, pet_size, remaining)
            if contact is not None:
                candidates.append((contact, "target", target))

        # Keep an upward fling inside the host.  The top edge is a reflective
        # boundary, whereas a FALL entering from above intentionally bypasses
        # this reducer until it crosses into the new host.
        top_contact = _quadratic_positive_root(
            0.5 * FLING_GRAVITY,
            vy,
            position.y - minimum_y,
            remaining,
        )
        if top_contact is not None and vy + FLING_GRAVITY * top_contact <= 1e-6:
            candidates.append((top_contact, "top", None))
        elif position.y < minimum_y and vy < 0.0:
            candidates.append((0.0, "top", None))
        elif position.y <= minimum_y + 1e-6 and vy < 0.0:
            candidates.append((0.0, "top", None))

        # Synthetic viewport bottom is always a legal landing surface.
        bottom_contact = _quadratic_positive_root(
            0.5 * FLING_GRAVITY,
            vy,
            position.y - maximum_y,
            remaining,
        )
        if bottom_contact is not None and vy + FLING_GRAVITY * bottom_contact >= -1e-6:
            candidates.append((bottom_contact, "bottom", None))
        elif position.y >= maximum_y - 1e-6 and vy >= 0.0:
            # If a previous coarse update left the centre just outside the
            # viewport, resolve the boundary at t=0 instead of integrating
            # farther out with no quadratic root.
            candidates.append((0.0, "bottom", None))

        if not candidates:
            position = PetPoint(
                position.x + vx * remaining,
                position.y + vy * remaining + 0.5 * FLING_GRAVITY * remaining * remaining,
            )
            vy += FLING_GRAVITY * remaining
            remaining = 0.0
            break

        contact_time, kind, target = min(candidates, key=lambda item: item[0])
        # Ignore a zero-time wall candidate after a reflection to avoid looping
        # on the same edge; the small epsilon is below display precision.
        if contact_time <= 1e-9 and kind in {"left", "right"}:
            vx = -vx * FLING_HORIZONTAL_RESTITUTION
            position = PetPoint(
                (minimum_x + 1e-6) if kind == "left" else (maximum_x - 1e-6),
                position.y,
            )
            continue
        if contact_time <= 1e-9 and kind == "top":
            position = PetPoint(position.x, minimum_y)
            vy = abs(vy) * 0.5
            continue
        position = PetPoint(
            position.x + vx * contact_time,
            position.y + vy * contact_time + 0.5 * FLING_GRAVITY * contact_time * contact_time,
        )
        vy_at_contact = vy + FLING_GRAVITY * contact_time
        remaining -= contact_time
        if kind in {"left", "right"}:
            position = PetPoint(minimum_x if kind == "left" else maximum_x, position.y)
            vx = -vx * FLING_HORIZONTAL_RESTITUTION
            vy = vy_at_contact
            continue
        if kind == "top":
            position = PetPoint(position.x, minimum_y)
            vy = abs(vy_at_contact) * 0.5
            continue
        if kind == "target" and target is not None:
            position = viewport.clamp(position, pet_size)
            if abs(vy_at_contact) >= HARD_LANDING_SPEED:
                return replace(
                    state,
                    position=position,
                    mode=PetMode.BOUNCE,
                    target_id=target.id,
                    movement_speed=0.0,
                    vertical_velocity=-FIRST_BOUNCE_SPEED,
                    bounces_remaining=BOUNCE_COUNT,
                    horizontal_velocity=0.0,
                    curve_velocity=None,
                )
            if target.kind == PetTargetKind.CHART and target.path:
                return _chart_landing_state(
                    state,
                    target,
                    position,
                    PetPoint(vx, vy_at_contact),
                    viewport,
                    pet_size,
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
                horizontal_velocity=0.0,
                curve_velocity=None,
            )
        # Bottom impact follows the existing continuous-contact/bounce rules.
        position = PetPoint(min(max(position.x, minimum_x), maximum_x), maximum_y)
        return _land_at_viewport_bottom(
            replace(state, horizontal_velocity=vx),
            position,
            abs(vy_at_contact),
        )

    # Keep the vertical coordinate un-clamped for a frame while entering from
    # a neighbouring window's top edge.  Horizontal bounds remain strict so a
    # presentation portal can detect the edge without rendering a partial
    # sprite; the next host maps the centre to its inner edge.
    position = PetPoint(
        min(max(position.x, minimum_x), maximum_x),
        position.y,
    )
    return replace(
        state,
        position=position,
        mode=PetMode.FLING,
        target_id=None,
        idle_ticks_remaining=0,
        movement_speed=0.0,
        vertical_velocity=vy,
        bounces_remaining=0,
        horizontal_velocity=vx,
        curve_velocity=None,
        facing=_facing_after_move(state.position, position, state.facing),
    )


def _advance_fling(
    state: PetState,
    targets: Sequence[PetTarget],
    viewport: PetRect,
    pet_size: float,
) -> PetState:
    """Advance one fixed tick using deterministic high-speed substeps."""
    substeps = min(
        MAX_SUBSTEPS_PER_TICK,
        max(1, int(math.ceil(FALL_TIME_STEP_SECONDS / MAX_SUBSTEP_SECONDS))),
    )
    step = FALL_TIME_STEP_SECONDS / substeps
    current = state
    for _ in range(substeps):
        if current.mode != PetMode.FLING:
            break
        current = _advance_fling_substep(current, targets, viewport, pet_size, step)
    return current


def _advance_chart(
    state: PetState,
    target: PetTarget,
    viewport: PetRect,
    speed: float,
    pet_size: float,
) -> PetState:
    path = tuple(viewport.clamp(point, pet_size) for point in target.shifted_path(pet_size))
    if state.curve_velocity is not None and len(path) > 1:
        return _advance_landed_chart(state, target, path, viewport, pet_size)
    same_target = state.target_id == target.id and state.mode == PetMode.SLIDE
    if same_target:
        direction = -1 if state.path_direction < 0 else 1
        index = min(max(state.path_index, 0), len(path) - 1)
    elif len(path) > 1:
        segment, projection, tangent = _closest_path_segment(state.position, path)
        if math.hypot(
            state.position.x - projection.x,
            state.position.y - projection.y,
        ) <= 1e-3:
            direction = _curve_downhill_direction(tangent)
            index = segment + 1 if direction > 0 else segment
        else:
            direction = 1
            index = _path_goal_index(state.position, path, direction)
    else:
        direction = 1
        index = 0
    remaining = _path_distance_to_endpoint(state.position, path, index, direction)
    distance, movement_speed = _accelerated_path_distance(state.movement_speed, remaining, speed)
    position, index, reached_endpoint, remaining_budget = _move_along_path(
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
                curve_velocity=None,
                facing=facing,
            )
        direction *= -1
        index = max(0, min(len(path) - 1, index + direction))
        # Keep consuming the current tick's distance after a corner.  The
        # previous implementation reset the speed at every endpoint, which
        # produced a visible hitch on the memory curve.
        if remaining_budget > 1e-6 and len(path) > 1:
            position, index, reached_again, remaining_budget = _move_along_path(
                position,
                path,
                index,
                direction,
                remaining_budget,
            )
            if reached_again:
                # A very short path can be crossed twice in one tick.  Stop at
                # the second endpoint and let the next tick continue smoothly.
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
            movement_speed=movement_speed,
            vertical_velocity=0.0,
            horizontal_velocity=0.0,
            curve_velocity=None,
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
        horizontal_velocity=0.0,
        curve_velocity=None,
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
            curve_velocity=None,
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
                curve_velocity=None,
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
            curve_velocity=None,
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
        curve_velocity=None,
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
    # Fling/fall states may intentionally start just outside a newly opened
    # window (for example, entering through its top edge).  Clamp only the
    # horizontal coordinate here; vertical integration below brings the pet
    # into the viewport naturally.  Legacy modes retain the strict viewport
    # clamp used by the original reducer.
    if state.mode in {PetMode.FLING, PetMode.FALL, PetMode.BOUNCE}:
        state = replace(
            state,
            position=PetPoint(
                viewport.clamp(PetPoint(state.position.x, 0.0), margin).x,
                state.position.y,
            ),
        )
    else:
        state = replace(state, position=viewport.clamp(state.position, margin))
    if state.mode == PetMode.DRAGGING:
        return state
    target_list = tuple(target for target in targets if target.valid)
    if (
        state.target_id
        and state.target_id != _VIEWPORT_BOTTOM_TARGET_ID
        and not any(target.id == state.target_id for target in target_list)
    ):
        state = replace(
            state,
            mode=PetMode.FALL,
            target_id=None,
            idle_ticks_remaining=0,
            movement_speed=0.0,
            vertical_velocity=max(0.0, state.vertical_velocity),
            bounces_remaining=0,
            curve_velocity=None,
        )
    if state.idle_ticks_remaining > 0:
        return replace(
            state,
            idle_ticks_remaining=state.idle_ticks_remaining - 1,
            movement_speed=0.0,
        )
    if state.mode == PetMode.BOUNCE and state.target_id == _VIEWPORT_BOTTOM_TARGET_ID:
        return _advance_viewport_bottom_bounce(state, viewport, margin)
    if state.mode == PetMode.FLING:
        # Fling integration is independent of support selection; supports are
        # queried by the integrator solely for continuous collision detection.
        return _advance_fling(state, target_list, viewport, margin)
    target = _target_for_state(state, target_list, margin, viewport)
    if target is None:
        if state.mode == PetMode.FALL:
            return _advance_free_fall(state, viewport, margin)
        return replace(
            state,
            position=viewport.clamp(state.position, margin),
            mode=PetMode.IDLE,
            target_id=None,
            movement_speed=0.0,
            vertical_velocity=0.0,
            bounces_remaining=0,
            curve_velocity=None,
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
        # Presentation adapters pass an already offset-adjusted centre to the
        # wrapper.  Keep the low-level reducer's raw-pointer offset available,
        # but avoid applying it a second time in ``drag_move`` here.
        self.state = begin_drag(self.state, pointer)
        self.state = replace(self.state, drag_offset=None)
        return self.state

    def drag_move(self, pointer: PetPoint, viewport: PetRect) -> PetState:
        # The wrapper receives a centre position from presentation (which
        # already applied its grab offset); the low-level ``move_drag`` helper
        # remains available for raw pointer semantics.
        if self.state.mode == PetMode.DRAGGING:
            position = viewport.clamp(pointer, max(0.0, self.pet_size))
            self.state = replace(
                self.state,
                position=position,
                facing=_facing_after_move(self.state.position, position, self.state.facing),
            )
        return self.state

    def drag_release(
        self,
        targets: Iterable[PetTarget] = (),
        viewport: PetRect | None = None,
        release_velocity: PetPoint | Sequence[float] | None = None,
        *,
        velocity: PetPoint | Sequence[float] | None = None,
        releaseVelocity: PetPoint | Sequence[float] | None = None,  # noqa: N803
    ) -> PetState:
        if release_velocity is None:
            release_velocity = velocity if velocity is not None else releaseVelocity
        self.state = release_drag(
            self.state,
            targets,
            viewport,
            self.pet_size,
            release_velocity,
        )
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
limitFlingVelocity = limit_fling_velocity
estimateDragVelocity = estimate_release_velocity
