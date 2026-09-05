from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import ctypes
import ctypes.wintypes as wintypes
import math
import sys
import time
import tkinter as tk
from typing import Callable, Sequence


STUDY_REWARD_COLOR = "#F4C542"

# Animation constants are intentionally centralized because motion and visual
# balance will be tuned in later releases.
FRAME_MS = 16
SPIRAL_DURATION_MS = 180.0
SPIRAL_TURNS = 1.0
SPIRAL_RADIUS_START = 4.0
SPIRAL_RADIUS_END = 18.0
HOMING_INITIAL_SPEED = 180.0
HOMING_ACCELERATION = 2400.0
HOMING_MAXIMUM_SPEED = 2800.0
# Keep the physical contact radius separate from the visible feedback.  These
# presentation values are centralized because they will be tuned later.
ORB_RADIUS = 6.0
VISUAL_ORB_RADIUS = 13.0
VISUAL_ORB_GLOW_RADIUS = 30.0
VISUAL_ORB_HIGHLIGHT_RADIUS = 3.0
ORB_PULSE_AMPLITUDE = 0.14
STUDY_ORB_PULSE_PERIOD_MS = 460.0
REVIEW_ORB_PULSE_PERIOD_MS = 320.0
ORB_RING_RADIUS = 21.0
ORB_RING_STROKE_WIDTH = 1.5
TRAIL_LIFETIME_MS = 180.0
TRAIL_MAXIMUM_POINTS = 20
TRAIL_MINIMUM_LENGTH = 18.0
TRAIL_MAXIMUM_LENGTH = 96.0
TRAIL_MINIMUM_STROKE_WIDTH = 4.0
TRAIL_MAXIMUM_STROKE_WIDTH = 9.0
TRAIL_STROKE_SPEED_FACTOR = 0.0025
TRAIL_GLOW_WIDTH_MULTIPLIER = 1.8
BURST_PARTICLE_COUNT = 18
BURST_PARTICLE_RADIUS = 4.0
BURST_PARTICLE_GLOW_RADIUS = 9.0
BURST_RING_START_RADIUS = 12.0
BURST_RING_END_RADIUS = 52.0
BURST_RING_STROKE_WIDTH = 3.0
BURST_RING_DURATION_MS = 180.0
BURST_DURATION_MS = 350.0
MAXIMUM_LIFETIME_MS = 2500.0
MISSING_TARGET_TIMEOUT_MS = 500.0

# Win32 hit-testing constants.  ``WS_EX_TRANSPARENT`` only affects paint
# ordering; it does not make a top-level window ignore pointer input.  The
# effect layer therefore subclasses its native window procedure and returns
# ``HTTRANSPARENT`` for hit tests so the underlying Tk window receives the
# click.
WM_NCHITTEST = 0x0084
WM_MOUSEACTIVATE = 0x0021
HTTRANSPARENT = -1
MA_NOACTIVATE = 3
_GWL_WNDPROC = -4


def transparent_hit_test_result(message: int) -> int | None:
    """Return the Win32 result used to pass effect-layer hit tests through."""
    try:
        normalized = int(message)
    except (TypeError, ValueError):
        return None
    return HTTRANSPARENT if normalized == WM_NCHITTEST else None


@dataclass(frozen=True)
class RewardPoint:
    x: float
    y: float

    def __add__(self, other: RewardPoint) -> RewardPoint:
        return RewardPoint(self.x + other.x, self.y + other.y)

    def __sub__(self, other: RewardPoint) -> RewardPoint:
        return RewardPoint(self.x - other.x, self.y - other.y)

    def scaled(self, factor: float) -> RewardPoint:
        return RewardPoint(self.x * factor, self.y * factor)

    @property
    def length(self) -> float:
        return math.hypot(self.x, self.y)

    def normalized(self) -> RewardPoint:
        length = self.length
        return RewardPoint(0.0, 0.0) if length <= 1e-9 else self.scaled(1.0 / length)

    def distance_to(self, other: RewardPoint) -> float:
        return (self - other).length


@dataclass(frozen=True)
class RewardFlightConfig:
    spiral_duration_ms: float = SPIRAL_DURATION_MS
    spiral_turns: float = SPIRAL_TURNS
    spiral_radius_start: float = SPIRAL_RADIUS_START
    spiral_radius_end: float = SPIRAL_RADIUS_END
    homing_initial_speed: float = HOMING_INITIAL_SPEED
    homing_acceleration: float = HOMING_ACCELERATION
    homing_maximum_speed: float = HOMING_MAXIMUM_SPEED
    orb_radius: float = ORB_RADIUS
    trail_lifetime_ms: float = TRAIL_LIFETIME_MS
    trail_maximum_points: int = TRAIL_MAXIMUM_POINTS
    burst_particle_count: int = BURST_PARTICLE_COUNT
    burst_duration_ms: float = BURST_DURATION_MS
    maximum_lifetime_ms: float = MAXIMUM_LIFETIME_MS
    missing_target_timeout_ms: float = MISSING_TARGET_TIMEOUT_MS


DEFAULT_CONFIG = RewardFlightConfig()


class FlightPhase(str, Enum):
    SPIRAL = "spiral"
    HOMING = "homing"
    BURST = "burst"
    FINISHED = "finished"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class TrailSample:
    at_ms: float
    position: RewardPoint


@dataclass(frozen=True)
class BurstParticle:
    origin: RewardPoint
    velocity: RewardPoint
    started_at_ms: float

    def position_at(self, now_ms: float) -> RewardPoint:
        elapsed = max(0.0, now_ms - self.started_at_ms) / 1000.0
        # A small deceleration keeps the burst compact while retaining a
        # deterministic radial shape for both rendering and tests.
        damping = max(0.0, 1.0 - elapsed * 1.8)
        distance_factor = elapsed * (0.55 + 0.45 * damping)
        return self.origin + self.velocity.scaled(distance_factor)


def trail_length_for_speed(speed: float) -> float:
    return min(
        TRAIL_MAXIMUM_LENGTH,
        max(TRAIL_MINIMUM_LENGTH, max(0.0, float(speed)) * 0.04),
    )


def trail_stroke_width_for_speed(speed: float) -> float:
    """Return a readable, speed-responsive core width for the trail."""
    bounded_speed = max(0.0, float(speed)) if math.isfinite(float(speed)) else 0.0
    return min(
        TRAIL_MAXIMUM_STROKE_WIDTH,
        max(
            TRAIL_MINIMUM_STROKE_WIDTH,
            TRAIL_MINIMUM_STROKE_WIDTH + bounded_speed * TRAIL_STROKE_SPEED_FACTOR,
        ),
    )


def trail_polyline_length(samples: Sequence[TrailSample]) -> float:
    return sum(
        samples[index].position.distance_to(samples[index - 1].position)
        for index in range(1, len(samples))
    )


def clip_trail_to_length(
    samples: Sequence[TrailSample],
    maximum_length: float,
) -> list[TrailSample]:
    """Keep the newest polyline suffix, interpolating its exact boundary."""
    if not samples:
        return []
    limit = max(0.0, float(maximum_length))
    if len(samples) == 1 or trail_polyline_length(samples) <= limit:
        return list(samples)

    clipped_reversed = [samples[-1]]
    remaining = limit
    for index in range(len(samples) - 1, 0, -1):
        newer = samples[index]
        older = samples[index - 1]
        segment_length = newer.position.distance_to(older.position)
        if segment_length <= remaining:
            clipped_reversed.append(older)
            remaining -= segment_length
            if remaining <= 0.0:
                break
            continue
        if segment_length > 0.0 and remaining > 0.0:
            ratio = remaining / segment_length
            boundary = newer.position + (older.position - newer.position).scaled(ratio)
            boundary_time = newer.at_ms + (older.at_ms - newer.at_ms) * ratio
            clipped_reversed.append(TrailSample(boundary_time, boundary))
        break
    return list(reversed(clipped_reversed))


def _spiral_offset(config: RewardFlightConfig, progress: float) -> RewardPoint:
    accelerated_progress = progress * progress
    turns = config.spiral_turns * accelerated_progress
    radius = (
        config.spiral_radius_start
        + (config.spiral_radius_end - config.spiral_radius_start) * progress
    )
    quarter_turns = round(turns * 4.0)
    if math.isclose(turns * 4.0, quarter_turns, rel_tol=0.0, abs_tol=1e-12):
        cardinal = (
            RewardPoint(1.0, 0.0),
            RewardPoint(0.0, 1.0),
            RewardPoint(-1.0, 0.0),
            RewardPoint(0.0, -1.0),
        )[quarter_turns % 4]
        return cardinal.scaled(radius)
    angle = math.tau * turns
    return RewardPoint(math.cos(angle) * radius, math.sin(angle) * radius)


def _coerce_point(value: RewardPoint | tuple[float, float] | None) -> RewardPoint | None:
    if value is None or isinstance(value, RewardPoint):
        return value
    return RewardPoint(float(value[0]), float(value[1]))


def _swept_contact(
    start: RewardPoint,
    end: RewardPoint,
    center: RewardPoint,
    radius: float,
) -> RewardPoint | None:
    relative = start - center
    if relative.length <= radius:
        return start
    movement = end - start
    a = movement.x * movement.x + movement.y * movement.y
    if a <= 1e-12:
        return None
    b = 2.0 * (relative.x * movement.x + relative.y * movement.y)
    c = relative.x * relative.x + relative.y * relative.y - radius * radius
    discriminant = b * b - 4.0 * a * c
    if discriminant < 0.0:
        return None
    root = math.sqrt(discriminant)
    for candidate in sorted(((-b - root) / (2.0 * a), (-b + root) / (2.0 * a))):
        if 0.0 <= candidate <= 1.0:
            return start + movement.scaled(candidate)
    return None


@dataclass
class RewardFlight:
    flight_id: int
    source: RewardPoint
    color: str
    created_at_ms: float
    config: RewardFlightConfig = DEFAULT_CONFIG
    phase: FlightPhase = FlightPhase.SPIRAL
    position: RewardPoint = field(init=False)
    velocity: RewardPoint = field(default_factory=lambda: RewardPoint(0.0, 0.0))
    last_update_ms: float = field(init=False)
    missing_target_since_ms: float | None = None
    trail: list[TrailSample] = field(default_factory=list)
    particles: list[BurstParticle] = field(default_factory=list)
    burst_started_at_ms: float | None = None
    contact_point: RewardPoint | None = None

    def __post_init__(self) -> None:
        self.position = self.source
        self.last_update_ms = self.created_at_ms
        self.trail.append(TrailSample(self.created_at_ms, self.source))

    @property
    def speed(self) -> float:
        return self.velocity.length

    @property
    def active(self) -> bool:
        return self.phase not in (FlightPhase.FINISHED, FlightPhase.CANCELLED)

    def _append_trail(self, now_ms: float, previous: RewardPoint) -> None:
        elapsed_seconds = max(1e-6, now_ms - self.last_update_ms) / 1000.0
        measured_speed = self.position.distance_to(previous) / elapsed_seconds
        if self.phase is FlightPhase.SPIRAL:
            self.velocity = (self.position - previous).scaled(1.0 / elapsed_seconds)
        if not self.trail or self.trail[-1].position != self.position:
            self.trail.append(TrailSample(now_ms, self.position))
        cutoff = now_ms - self.config.trail_lifetime_ms
        self.trail[:] = [sample for sample in self.trail if sample.at_ms >= cutoff]
        if len(self.trail) > self.config.trail_maximum_points:
            del self.trail[: len(self.trail) - self.config.trail_maximum_points]

        maximum_length = trail_length_for_speed(max(self.speed, measured_speed))
        self.trail[:] = clip_trail_to_length(self.trail, maximum_length)

    def _begin_burst(self, at_ms: float, contact: RewardPoint) -> None:
        self.phase = FlightPhase.BURST
        self.position = contact
        self.contact_point = contact
        self.burst_started_at_ms = at_ms
        self.velocity = RewardPoint(0.0, 0.0)
        particles: list[BurstParticle] = []
        for index in range(self.config.burst_particle_count):
            angle = math.tau * index / self.config.burst_particle_count
            speed = 145.0 + 28.0 * (index % 4)
            particles.append(BurstParticle(
                origin=contact,
                velocity=RewardPoint(math.cos(angle) * speed, math.sin(angle) * speed),
                started_at_ms=at_ms,
            ))
        self.particles = particles

    def update(
        self,
        now_ms: float,
        target: RewardPoint | tuple[float, float] | None,
        pet_half_size: float,
    ) -> bool:
        if not self.active:
            return False
        now_ms = max(float(now_ms), self.last_update_ms)
        target_point = _coerce_point(target)
        age_ms = now_ms - self.created_at_ms
        if age_ms >= self.config.maximum_lifetime_ms and self.phase is not FlightPhase.BURST:
            self.phase = FlightPhase.CANCELLED
            return False

        if target_point is None:
            if self.missing_target_since_ms is None:
                self.missing_target_since_ms = now_ms
            elif now_ms - self.missing_target_since_ms >= self.config.missing_target_timeout_ms:
                self.phase = FlightPhase.CANCELLED
                return False
        else:
            self.missing_target_since_ms = None

        if self.phase is FlightPhase.BURST:
            if (
                self.burst_started_at_ms is not None
                and now_ms - self.burst_started_at_ms >= self.config.burst_duration_ms
            ):
                self.phase = FlightPhase.FINISHED
                return False
            self.last_update_ms = now_ms
            return True

        previous = self.position
        if self.phase is FlightPhase.SPIRAL:
            progress = min(1.0, max(0.0, age_ms / self.config.spiral_duration_ms))
            self.position = self.source + _spiral_offset(self.config, progress)
            self._append_trail(now_ms, previous)
            if progress >= 1.0:
                self.phase = FlightPhase.HOMING
                if target_point is not None:
                    self.velocity = (target_point - self.position).normalized().scaled(
                        self.config.homing_initial_speed
                    )
                    contact = _swept_contact(
                        self.position,
                        self.position,
                        target_point,
                        max(0.0, pet_half_size) + self.config.orb_radius,
                    )
                    if contact is not None:
                        self._begin_burst(now_ms, contact)
            self.last_update_ms = now_ms
            return True

        elapsed_seconds = max(0.0, now_ms - self.last_update_ms) / 1000.0
        if target_point is not None and elapsed_seconds > 0.0:
            direction = (target_point - self.position).normalized()
            self.velocity = self.velocity + direction.scaled(
                self.config.homing_acceleration * elapsed_seconds
            )
            if self.speed > self.config.homing_maximum_speed:
                self.velocity = self.velocity.normalized().scaled(
                    self.config.homing_maximum_speed
                )
            destination = self.position + self.velocity.scaled(elapsed_seconds)
            contact = _swept_contact(
                self.position,
                destination,
                target_point,
                max(0.0, pet_half_size) + self.config.orb_radius,
            )
            self.position = destination if contact is None else contact
            self._append_trail(now_ms, previous)
            if contact is not None:
                self._begin_burst(now_ms, contact)
        self.last_update_ms = now_ms
        return True


class RewardAnimationModel:
    """Pure transient state supporting any number of independent flights."""

    def __init__(self, config: RewardFlightConfig = DEFAULT_CONFIG):
        self.config = config
        self.flights: list[RewardFlight] = []
        self._next_flight_id = 1

    @property
    def active_count(self) -> int:
        return sum(flight.active for flight in self.flights)

    def emit(
        self,
        source: RewardPoint | tuple[float, float],
        color: str,
        now_ms: float | None = None,
    ) -> RewardFlight:
        created_at = _monotonic_ms() if now_ms is None else float(now_ms)
        flight = RewardFlight(
            flight_id=self._next_flight_id,
            source=_coerce_point(source) or RewardPoint(0.0, 0.0),
            color=str(color),
            created_at_ms=created_at,
            config=self.config,
        )
        self._next_flight_id += 1
        self.flights.append(flight)
        return flight

    def update(
        self,
        now_ms: float,
        target: RewardPoint | tuple[float, float] | None,
        pet_half_size: float,
    ) -> None:
        for flight in tuple(self.flights):
            flight.update(now_ms, target, pet_half_size)
        self.flights[:] = [flight for flight in self.flights if flight.active]

    def clear(self) -> None:
        self.flights.clear()


def _monotonic_ms() -> float:
    return time.monotonic_ns() / 1_000_000.0


class RewardEffectLayer(tk.Toplevel):
    """Desktop-coordinate transparent, mouse-pass-through effect surface."""

    TRANSPARENT_KEY = "#ff00ff"

    def __init__(self, parent: tk.Misc):
        super().__init__(parent)
        # Keep every native callback and API handle alive for as long as the
        # subclass is installed.  ctypes otherwise permits the callback
        # trampoline to be collected while Windows can still dispatch to it.
        # ``Win32`` forwards hits through a transparent surface only when the
        # window that actually receives ``WM_NCHITTEST`` returns ``HTTRANSPARENT``.
        # Tk renders the orb on a child ``Canvas``, so both the top-level and
        # that child are subclassed; keeping the callbacks referenced preserves
        # the trampoline used by the native window procedure.
        self._passthrough_handles: list[tuple[int, int]] = []
        self._passthrough_callbacks: list = []
        self._passthrough_failures: list[int] = []
        self._call_window_proc = None
        self.withdraw()
        self.overrideredirect(True)
        self.configure(bg=self.TRANSPARENT_KEY, bd=0, highlightthickness=0)
        try:
            self.wm_attributes("-topmost", True)
            self.wm_attributes("-transparentcolor", self.TRANSPARENT_KEY)
        except tk.TclError:
            pass
        self._origin_x, self._origin_y, width, height = self._virtual_screen_bounds(parent)
        self.geometry(f"{width}x{height}{self._origin_x:+d}{self._origin_y:+d}")
        self.canvas = tk.Canvas(
            self,
            bg=self.TRANSPARENT_KEY,
            bd=0,
            highlightthickness=0,
            relief=tk.FLAT,
        )
        self.canvas.pack(fill=tk.BOTH, expand=True)
        self.update_idletasks()
        self._enable_mouse_passthrough()

    @staticmethod
    def _virtual_screen_bounds(parent: tk.Misc) -> tuple[int, int, int, int]:
        if sys.platform == "win32":
            user32 = ctypes.windll.user32
            return (
                int(user32.GetSystemMetrics(76)),
                int(user32.GetSystemMetrics(77)),
                max(1, int(user32.GetSystemMetrics(78))),
                max(1, int(user32.GetSystemMetrics(79))),
            )
        return 0, 0, max(1, parent.winfo_screenwidth()), max(1, parent.winfo_screenheight())

    def _native_surfaces(self) -> list[int]:
        """Return the layer's top-level native window plus every descendant HWND.

        The effect surface must be click-transparent on *every* native window
        in its hierarchy.  Some Tk builds nest an extra wrapper or drawing
        window below the Toplevel; a single unsubclassed surface would swallow
        mouse events for as long as the flight is visible, which locks the
        page even though the orb animation itself keeps running.
        """
        result: list[int] = []
        try:
            widget_hwnd = int(self.winfo_id() or 0)
        except (tk.TclError, TypeError, ValueError):
            return result
        hwnd = widget_hwnd
        if sys.platform == "win32":
            try:
                user32 = ctypes.windll.user32
                get_style = getattr(user32, "GetWindowLongPtrW", None) or user32.GetWindowLongW
                get_style.restype = ctypes.c_void_p
                get_style.argtypes = [wintypes.HWND, ctypes.c_int]
                window_style = int(get_style(widget_hwnd, -16) or 0)
                if window_style & 0x40000000:  # WS_CHILD
                    parent_hwnd = int(user32.GetParent(widget_hwnd) or 0)
                    if parent_hwnd:
                        hwnd = parent_hwnd
                enumerator_type = ctypes.WINFUNCTYPE(
                    wintypes.BOOL,
                    wintypes.HWND,
                    wintypes.LPARAM,
                )

                @enumerator_type
                def collect(child_hwnd, _lparam):
                    result.append(int(child_hwnd))
                    return True

                user32.EnumChildWindows(hwnd, collect, 0)
            except (AttributeError, OSError, TypeError, ValueError, ctypes.ArgumentError, tk.TclError):
                pass
        for candidate in (hwnd, widget_hwnd):
            if candidate and candidate not in result:
                # EnumChildWindows returns descendants only; the top-level
                # itself must be subclassed too.
                result.append(candidate)
        try:
            canvas_hwnd = int(self.canvas.winfo_id() or 0)
        except (tk.TclError, TypeError, ValueError):
            canvas_hwnd = 0
        if canvas_hwnd and canvas_hwnd not in result:
            result.append(canvas_hwnd)
        return result

    def _enable_mouse_passthrough(self) -> None:
        if sys.platform != "win32":
            return
        try:
            self._enable_mouse_passthrough_with(ctypes.windll.user32)
        except (AttributeError, OSError, TypeError, ValueError, ctypes.ArgumentError, tk.TclError):
            pass

    def _enable_mouse_passthrough_with(self, user32) -> None:
        get_style = getattr(user32, "GetWindowLongPtrW", None) or user32.GetWindowLongW
        set_style = getattr(user32, "SetWindowLongPtrW", None) or user32.SetWindowLongW
        # Explicit pointer signatures avoid truncating a 64-bit WNDPROC.
        get_style.restype = ctypes.c_void_p
        get_style.argtypes = [wintypes.HWND, ctypes.c_int]
        set_style.restype = ctypes.c_void_p
        set_style.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]
        surfaces = self._native_surfaces()
        if not surfaces:
            return
        top_level = surfaces[0]
        extended_style = int(get_style(top_level, -20) or 0)
        try:
            set_style(
                top_level,
                -20,
                extended_style | 0x00000020 | 0x00080000 | 0x08000000 | 0x00000080,
            )
        except (OSError, TypeError, ValueError, ctypes.ArgumentError):
            pass
        # Subclass every native surface of the layer so Win32 forwards a
        # hit to the application window below regardless of how many
        # wrapper windows this Tk build creates.
        for surface in surfaces:
            self._install_hit_test_passthrough(user32, surface)

    def _install_hit_test_passthrough(self, user32, hwnd: int) -> bool:
        """Subclass the native layer window so hit tests reach Tk controls.

        Return ``False`` (without raising) when the surface could not be
        subclassed, so callers can diagnose a layer that would otherwise
        swallow input.
        """
        if any(existing == hwnd for existing, _original in self._passthrough_handles):
            return True
        get_proc = getattr(user32, "GetWindowLongPtrW", None) or user32.GetWindowLongW
        set_proc = getattr(user32, "SetWindowLongPtrW", None) or user32.SetWindowLongW
        call_proc = user32.CallWindowProcW
        pointer_type = ctypes.c_ssize_t if ctypes.sizeof(ctypes.c_void_p) > 4 else ctypes.c_long
        wnd_proc_type = ctypes.WINFUNCTYPE(
            pointer_type,
            wintypes.HWND,
            wintypes.UINT,
            wintypes.WPARAM,
            wintypes.LPARAM,
        )
        get_proc.restype = ctypes.c_void_p
        get_proc.argtypes = [wintypes.HWND, ctypes.c_int]
        set_proc.restype = ctypes.c_void_p
        set_proc.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]
        call_proc.restype = pointer_type
        call_proc.argtypes = [
            ctypes.c_void_p,
            wintypes.HWND,
            wintypes.UINT,
            wintypes.WPARAM,
            wintypes.LPARAM,
        ]
        original = get_proc(hwnd, _GWL_WNDPROC)
        if not original:
            self._note_passthrough_failure(hwnd, "no original window procedure")
            return False
        original_pointer = int(original)

        @wnd_proc_type
        def wnd_proc(window_hwnd, message, wparam, lparam):
            try:
                if transparent_hit_test_result(message) == HTTRANSPARENT:
                    return HTTRANSPARENT
                # Do not activate the transparent layer when Windows asks
                # which window should receive mouse activation.
                if int(message) == WM_MOUSEACTIVATE:
                    return MA_NOACTIVATE
                return call_proc(original_pointer, window_hwnd, message, wparam, lparam)
            except (OSError, RuntimeError, TypeError, ValueError, ctypes.ArgumentError, tk.TclError):
                # A teardown race can dispatch one final message after Tk has
                # started destroying the Toplevel.  Returning zero lets the
                # native default handling complete without raising through
                # the ctypes callback boundary.
                return 0

        try:
            set_proc(hwnd, _GWL_WNDPROC, wnd_proc)
        except (OSError, TypeError, ValueError, ctypes.ArgumentError):
            self._note_passthrough_failure(hwnd, f"SetWindowLongPtr failed")
            return False
        installed = get_proc(hwnd, _GWL_WNDPROC)
        expected = ctypes.cast(wnd_proc, ctypes.c_void_p).value
        if int(installed or 0) != int(expected or 0):
            self._note_passthrough_failure(hwnd, "window procedure not installed")
            return False
        self._passthrough_handles.append((hwnd, original_pointer))
        self._passthrough_callbacks.append(wnd_proc)
        self._call_window_proc = call_proc
        return True

    def _note_passthrough_failure(self, hwnd: int, reason: str) -> None:
        if self._passthrough_failures.count(hwnd) > 0:
            return
        self._passthrough_failures.append(hwnd)
        try:
            if sys.stderr is not None:
                sys.stderr.write(
                    f"LexiTrack reward layer: click-through not installed on {hwnd:#x} ({reason}); "
                    "mouse input may be blocked while a reward flight is visible.\n"
                )
        except (AttributeError, OSError, TypeError):
            pass

    def native_hit_test(self, hwnd: int, x: int, y: int) -> int:
        """Return the WM_NCHITTEST result of one of the layer's native surfaces.

        Used by the smoke probe to prove every surface of the overlay passes
        hits through while a flight is visible.
        """
        if sys.platform != "win32":
            return 0
        try:
            user32 = ctypes.windll.user32
            send_message = user32.SendMessageW
            pointer_type = ctypes.c_ssize_t if ctypes.sizeof(ctypes.c_void_p) > 4 else ctypes.c_long
            send_message.restype = pointer_type
            send_message.argtypes = [
                wintypes.HWND,
                wintypes.UINT,
                wintypes.WPARAM,
                wintypes.LPARAM,
            ]
            lparam = ((int(y) & 0xFFFF) << 16) | (int(x) & 0xFFFF)
            return int(send_message(hwnd, WM_NCHITTEST, 0, lparam))
        except (AttributeError, OSError, TypeError, ValueError, ctypes.ArgumentError, tk.TclError):
            return 0

    def _restore_hit_test_passthrough(self) -> None:
        """Restore Tk's original WNDPROC before the native window is freed."""
        if sys.platform == "win32":
            try:
                user32 = ctypes.windll.user32
                set_proc = getattr(user32, "SetWindowLongPtrW", None) or user32.SetWindowLongW
                set_proc.restype = ctypes.c_void_p
                set_proc.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]
                for hwnd, original in self._passthrough_handles:
                    set_proc(hwnd, _GWL_WNDPROC, original)
            except (AttributeError, OSError, TypeError, ValueError, ctypes.ArgumentError, tk.TclError):
                pass
        self._passthrough_handles.clear()
        self._passthrough_callbacks.clear()
        self._passthrough_failures.clear()
        self._call_window_proc = None

    def show(self) -> None:
        if self.state() == "withdrawn":
            self.deiconify()
        self.lift()
        self._enable_mouse_passthrough()

    def keep_above(self, other: tk.Misc | None = None) -> None:
        """Keep the transparent surface above the independently placed pet window."""
        if self.state() == "withdrawn":
            return
        try:
            if other is None:
                self.lift()
            else:
                self.lift(aboveThis=other)
        except tk.TclError:
            pass

    def hide(self) -> None:
        if self.state() != "withdrawn":
            self.withdraw()

    def _canvas_point(self, point: RewardPoint) -> tuple[float, float]:
        return point.x - self._origin_x, point.y - self._origin_y

    @staticmethod
    def _pulse_values(flight: RewardFlight, now_ms: float) -> tuple[float, float]:
        period = (
            STUDY_ORB_PULSE_PERIOD_MS
            if flight.color.upper() == STUDY_REWARD_COLOR
            else REVIEW_ORB_PULSE_PERIOD_MS
        )
        phase = math.tau * max(0.0, now_ms - flight.created_at_ms) / period
        pulse = 1.0 + ORB_PULSE_AMPLITUDE * math.sin(phase)
        normalized = (pulse - 1.0) / ORB_PULSE_AMPLITUDE
        return pulse, max(0.0, min(1.0, normalized))

    def render(self, model: RewardAnimationModel, now_ms: float) -> None:
        self.canvas.delete("all")
        for flight in model.flights:
            trail = flight.trail
            base_stroke_width = trail_stroke_width_for_speed(flight.speed)
            for index in range(1, len(trail)):
                x1, y1 = self._canvas_point(trail[index - 1].position)
                x2, y2 = self._canvas_point(trail[index].position)
                sequence = index / max(1, len(trail) - 1)
                width = base_stroke_width * (0.55 + sequence * 0.45)
                self.canvas.create_line(
                    x1,
                    y1,
                    x2,
                    y2,
                    fill=flight.color,
                    width=base_stroke_width * TRAIL_GLOW_WIDTH_MULTIPLIER,
                    capstyle=tk.ROUND,
                    stipple="gray50",
                )
                self.canvas.create_line(
                    x1,
                    y1,
                    x2,
                    y2,
                    fill=flight.color,
                    width=width,
                    capstyle=tk.ROUND,
                )
            if flight.phase in (FlightPhase.SPIRAL, FlightPhase.HOMING):
                x, y = self._canvas_point(flight.position)
                pulse, pulse_progress = self._pulse_values(flight, now_ms)
                core_radius = VISUAL_ORB_RADIUS * pulse
                glow_radius = VISUAL_ORB_GLOW_RADIUS * (0.92 + pulse_progress * 0.12)
                # Layered stipples approximate a radial alpha falloff on
                # Tk's binary transparent-color surface.  The outer halo is
                # sparse, while denser inner rings blend into the core.
                for radius, stipple in (
                    (glow_radius, "gray25"),
                    (glow_radius * 0.74, "gray50"),
                    (core_radius * 1.6, "gray75"),
                ):
                    self.canvas.create_oval(
                        x - radius,
                        y - radius,
                        x + radius,
                        y + radius,
                        fill=flight.color,
                        outline="",
                        stipple=stipple,
                    )
                self.canvas.create_oval(
                    x - ORB_RING_RADIUS,
                    y - ORB_RING_RADIUS,
                    x + ORB_RING_RADIUS,
                    y + ORB_RING_RADIUS,
                    outline=flight.color,
                    width=max(1, round(ORB_RING_STROKE_WIDTH)),
                )
                radius = core_radius
                self.canvas.create_oval(
                    x - radius,
                    y - radius,
                    x + radius,
                    y + radius,
                    fill=flight.color,
                    outline=flight.color,
                )
                self.canvas.create_oval(
                    x - radius * 0.34 - VISUAL_ORB_HIGHLIGHT_RADIUS,
                    y - radius * 0.42 - VISUAL_ORB_HIGHLIGHT_RADIUS,
                    x - radius * 0.34 + VISUAL_ORB_HIGHLIGHT_RADIUS,
                    y - radius * 0.42 + VISUAL_ORB_HIGHLIGHT_RADIUS,
                    fill="#FFFFFF",
                    outline="#FFFFFF",
                )
            elif flight.phase is FlightPhase.BURST:
                if flight.burst_started_at_ms is not None and flight.contact_point is not None:
                    progress = max(
                        0.0,
                        min(1.0, (now_ms - flight.burst_started_at_ms) / BURST_RING_DURATION_MS),
                    )
                    eased = 1.0 - (1.0 - progress) ** 2
                    radius = BURST_RING_START_RADIUS + (
                        BURST_RING_END_RADIUS - BURST_RING_START_RADIUS
                    ) * eased
                    x, y = self._canvas_point(flight.contact_point)
                    self.canvas.create_oval(
                        x - radius,
                        y - radius,
                        x + radius,
                        y + radius,
                        outline=flight.color,
                        width=max(1, round(BURST_RING_STROKE_WIDTH * (1.0 - progress))),
                    )
                for particle in flight.particles:
                    x, y = self._canvas_point(particle.position_at(now_ms))
                    progress = 0.0
                    if flight.burst_started_at_ms is not None:
                        progress = max(
                            0.0,
                            min(1.0, (now_ms - flight.burst_started_at_ms) / BURST_DURATION_MS),
                        )
                    particle_radius = BURST_PARTICLE_RADIUS * (0.68 + 0.32 * (1.0 - progress))
                    self.canvas.create_oval(
                        x - BURST_PARTICLE_GLOW_RADIUS,
                        y - BURST_PARTICLE_GLOW_RADIUS,
                        x + BURST_PARTICLE_GLOW_RADIUS,
                        y + BURST_PARTICLE_GLOW_RADIUS,
                        fill=flight.color,
                        outline="",
                        stipple="gray50",
                    )
                    self.canvas.create_oval(
                        x - particle_radius,
                        y - particle_radius,
                        x + particle_radius,
                        y + particle_radius,
                        fill=flight.color,
                        outline=flight.color,
                    )
                    self.canvas.create_oval(
                        x - 1.4,
                        y - 1.4,
                        x + 1.4,
                        y + 1.4,
                        fill="#FFFFFF",
                        outline="#FFFFFF",
                    )

    def destroy(self) -> None:
        self._restore_hit_test_passthrough()
        super().destroy()


class RewardEffectsController:
    def __init__(
        self,
        host: tk.Misc,
        target_provider: Callable[[], RewardPoint | tuple[float, float] | None],
        *,
        pet_half_size: float,
        config: RewardFlightConfig = DEFAULT_CONFIG,
    ):
        self.host = host
        self.target_provider = target_provider
        self.pet_half_size = float(pet_half_size)
        self.model = RewardAnimationModel(config)
        self.layer = RewardEffectLayer(host)
        self._after_id: str | None = None
        self._destroyed = False
        self._animation_now_ms = _monotonic_ms()
        self._last_wall_ms = self._animation_now_ms

    def emit(self, source: RewardPoint | tuple[float, float], color: str) -> RewardFlight:
        if self._destroyed:
            raise RuntimeError("Reward effects controller is destroyed")
        self._advance_clock()
        flight = self.model.emit(source, color, self._animation_now_ms)
        try:
            self.layer.show()
        except tk.TclError:
            # A transient layer failure must not lose the flight or skip the
            # animation loop; the next tick retries showing the surface.
            pass
        if self._after_id is None:
            self._after_id = self.host.after(FRAME_MS, self._tick)
        return flight

    def keep_above(self, other: tk.Misc | None = None) -> None:
        self.layer.keep_above(other)

    def _host_visible(self) -> bool:
        try:
            state = str(self.host.wm_state()) if hasattr(self.host, "wm_state") else "normal"
            return bool(self.host.winfo_exists() and self.host.winfo_viewable() and state != "iconic")
        except tk.TclError:
            return False

    def _advance_clock(self) -> None:
        wall_ms = _monotonic_ms()
        if self._host_visible():
            self._animation_now_ms += max(0.0, wall_ms - self._last_wall_ms)
        self._last_wall_ms = wall_ms

    def _tick(self) -> None:
        self._after_id = None
        if self._destroyed:
            return
        self._advance_clock()
        host_visible = True
        try:
            host_visible = self._host_visible()
            if host_visible:
                target = self.target_provider()
                self.model.update(self._animation_now_ms, target, self.pet_half_size)
            else:
                self.layer.hide()
        except Exception:
            # A single failed frame (for example a transient control teardown
            # while sampling the pet target) must not strand the overlay or
            # freeze the animation: skip the frame and keep the flights aging
            # so they still clean up and hide the layer.
            pass
        if host_visible and self.model.active_count:
            try:
                self.layer.show()
                self.layer.render(self.model, self._animation_now_ms)
                self.layer.keep_above()
            except Exception:
                pass
        elif not self.model.active_count:
            # The layer must come down even when every earlier attempt to
            # hide it failed; a lingering full-screen surface would block
            # input on the whole page.
            try:
                self.layer.hide()
            except tk.TclError:
                pass
        if self.model.active_count:
            self._after_id = self.host.after(FRAME_MS, self._tick)

    def destroy(self) -> None:
        if self._destroyed:
            return
        self._destroyed = True
        if self._after_id is not None:
            try:
                self.host.after_cancel(self._after_id)
            except tk.TclError:
                pass
            self._after_id = None
        self.model.clear()
        try:
            self.layer.destroy()
        except tk.TclError:
            pass


# Short aliases keep tests and callers readable without leaking Tk concerns.
RewardEffectsModel = RewardAnimationModel
Point = RewardPoint
