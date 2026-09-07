from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from functools import lru_cache
import ctypes
import ctypes.wintypes as wintypes
import math
import sys
import time
import tkinter as tk
from typing import Callable

from PIL import Image, ImageDraw

from presentation.layered_surface import present_alpha_frame


STUDY_REWARD_COLOR = "#F5C451"
REVIEW_REWARD_COLOR = "#39D9D0"

FRAME_MS = 16
SIMULATION_STEP_MS = 1000.0 / 120.0
MAXIMUM_FRAME_MS = 100.0
HOMING_INITIAL_SPEED = 65.0
HOMING_ACCELERATION = 230.0
REFERENCE_PET_HALF_SIZE = 56.0
ORB_RADIUS = 7.0
VISUAL_ORB_RADIUS = 7.0
VISUAL_ORB_GLOW_RADIUS = 46.0
VISUAL_ORB_HIGHLIGHT_RADIUS = 4.0
TRAIL_MAXIMUM_POINTS = 42
TRAIL_SAMPLE_STRIDE = 3
TRAIL_STROKE_WIDTH = 7.0
TRAIL_HEAD_OPACITY = 0.55
BURST_PARTICLE_COUNT = 8
BURST_PARTICLE_RADIUS = 2.0
BURST_DURATION_MS = 420.0
BURST_RING_RADIUS_START = 20.0
BURST_RING_RADIUS_END = 58.0
BURST_PARTICLE_DISTANCE_START = 22.0
BURST_PARTICLE_DISTANCE_END = 66.0

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
    homing_initial_speed: float = HOMING_INITIAL_SPEED
    homing_acceleration: float = HOMING_ACCELERATION
    orb_radius: float = ORB_RADIUS
    trail_maximum_points: int = TRAIL_MAXIMUM_POINTS
    burst_particle_count: int = BURST_PARTICLE_COUNT
    burst_duration_ms: float = BURST_DURATION_MS


DEFAULT_CONFIG = RewardFlightConfig()


class FlightPhase(str, Enum):
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
    direction: RewardPoint
    started_at_ms: float
    scale: float = 1.0

    def position_at(self, now_ms: float) -> RewardPoint:
        progress = min(1.0, max(0.0, now_ms - self.started_at_ms) / BURST_DURATION_MS)
        radius = BURST_PARTICLE_DISTANCE_START + (
            BURST_PARTICLE_DISTANCE_END - BURST_PARTICLE_DISTANCE_START
        ) * progress
        return self.origin + self.direction.scaled(radius * self.scale)


@dataclass(frozen=True)
class RewardTarget:
    center: RewardPoint
    half_size: float
    continuity_key: object = None


def _coerce_point(value: RewardPoint | tuple[float, float] | None) -> RewardPoint | None:
    if value is None or isinstance(value, RewardPoint):
        return value
    return RewardPoint(float(value[0]), float(value[1]))


def collision_fraction(
    start: RewardPoint,
    end: RewardPoint,
    target_start: RewardPoint,
    target_end: RewardPoint,
    radius: float,
) -> float | None:
    """Intersect relative motion so a dragged target cannot cross an orb unseen."""
    relative = start - target_start
    if relative.length <= radius:
        return 0.0
    movement = (end - target_end) - relative
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
            return candidate
    return None


@dataclass
class RewardFlight:
    flight_id: int
    source: RewardPoint
    color: str
    created_at_ms: float
    config: RewardFlightConfig = DEFAULT_CONFIG
    phase: FlightPhase = FlightPhase.HOMING
    position: RewardPoint = field(init=False)
    velocity: RewardPoint = field(default_factory=lambda: RewardPoint(0.0, 0.0))
    last_update_ms: float = field(init=False)
    elapsed_ms: float = 0.0
    scale: float = 1.0
    _speed: float = field(init=False)
    _previous_target: RewardPoint | None = None
    _previous_step_target: RewardPoint | None = None
    _target_key: object = None
    _paused: bool = False
    _accumulator_ms: float = 0.0
    trail: list[TrailSample] = field(default_factory=list)
    particles: list[BurstParticle] = field(default_factory=list)
    burst_started_at_ms: float | None = None
    contact_point: RewardPoint | None = None

    def __post_init__(self) -> None:
        self.position = self.source
        self.last_update_ms = self.created_at_ms
        self._speed = self.config.homing_initial_speed
        self.trail.append(TrailSample(0.0, self.source))

    @property
    def speed(self) -> float:
        return self._speed

    @property
    def active(self) -> bool:
        return self.phase not in (FlightPhase.FINISHED, FlightPhase.CANCELLED)

    def _append_trail(self) -> None:
        self.trail.append(TrailSample(self.elapsed_ms, self.position))
        if len(self.trail) > self.config.trail_maximum_points:
            del self.trail[: len(self.trail) - self.config.trail_maximum_points]

    def _begin_burst(self, contact: RewardPoint, center: RewardPoint) -> None:
        self.phase = FlightPhase.BURST
        self.position = center
        self.contact_point = contact
        self.burst_started_at_ms = self.elapsed_ms
        self.velocity = RewardPoint(0.0, 0.0)
        self._speed = 0.0
        self.trail.clear()
        for index in range(self.config.burst_particle_count):
            angle = math.tau * index / self.config.burst_particle_count
            self.particles.append(BurstParticle(
                origin=center,
                direction=RewardPoint(math.cos(angle), math.sin(angle)),
                started_at_ms=self.elapsed_ms,
                scale=self.scale,
            ))

    def reset_target(self) -> None:
        self._previous_target = None
        self._previous_step_target = None

    def pause(self, now_ms: float) -> None:
        self.last_update_ms = max(self.last_update_ms, float(now_ms))
        self._paused = True
        self.reset_target()

    def update(
        self,
        now_ms: float,
        target: RewardPoint | tuple[float, float] | None,
        pet_half_size: float,
        target_key: object = None,
    ) -> bool:
        if not self.active:
            return False
        now_ms = max(float(now_ms), self.last_update_ms)
        target_point = _coerce_point(target)
        if target_point is None:
            self.pause(now_ms)
            return True
        delta_ms = 0.0 if self._paused else now_ms - self.last_update_ms
        self.last_update_ms = now_ms
        self._paused = False
        self.scale = max(0.0, float(pet_half_size)) / REFERENCE_PET_HALF_SIZE
        initial_target = self._previous_target
        if initial_target is None or target_key != self._target_key:
            initial_target = target_point
            self._previous_step_target = target_point
        self._previous_target = target_point
        self._target_key = target_key
        old_remainder = self._accumulator_ms
        self._accumulator_ms += delta_ms
        step_count = math.floor((self._accumulator_ms + 1e-9) / SIMULATION_STEP_MS)
        for index in range(step_count):
            fraction = min(1.0, max(0.0, ((index + 1) * SIMULATION_STEP_MS - old_remainder) / delta_ms)) if delta_ms else 1.0
            target_start = self._previous_step_target or initial_target
            target_end = initial_target + (target_point - initial_target).scaled(fraction)
            self._previous_step_target = target_end
            self.elapsed_ms += SIMULATION_STEP_MS
            if self.phase is FlightPhase.BURST:
                if self.elapsed_ms - self.burst_started_at_ms >= self.config.burst_duration_ms - 1e-9:
                    self.phase = FlightPhase.FINISHED
                    break
                continue
            dt = SIMULATION_STEP_MS / 1000.0
            direction = (target_start - self.position).normalized()
            distance = (self._speed * dt + 0.5 * self.config.homing_acceleration * dt * dt) * self.scale
            self._speed += self.config.homing_acceleration * dt
            self.velocity = direction.scaled(self._speed * self.scale)
            destination = self.position + direction.scaled(distance)
            fraction = collision_fraction(self.position, destination, target_start, target_end,
                                          max(0.0, pet_half_size) + self.config.orb_radius * self.scale)
            if fraction is not None:
                contact = self.position + (destination - self.position).scaled(fraction)
                center = target_start + (target_end - target_start).scaled(fraction)
                self._begin_burst(contact, center)
                continue
            self.position = destination
            self._append_trail()
        self._accumulator_ms = max(0.0, self._accumulator_ms - step_count * SIMULATION_STEP_MS)
        return self.active


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
        target_key: object = None,
    ) -> None:
        for flight in tuple(self.flights):
            flight.update(now_ms, target, pet_half_size, target_key)
        self.flights[:] = [flight for flight in self.flights if flight.active]

    def pause(self, now_ms: float) -> None:
        for flight in self.flights:
            flight.pause(now_ms)

    def reset_target(self) -> None:
        for flight in self.flights:
            flight.reset_target()

    def clear(self) -> None:
        self.flights.clear()


def _monotonic_ms() -> float:
    return time.monotonic_ns() / 1_000_000.0


@lru_cache(maxsize=32)
def _orb_glow(radius: int, color: str) -> Image.Image:
    glow = Image.new("RGBA", (radius * 2 + 2, radius * 2 + 2))
    draw = ImageDraw.Draw(glow)
    rgb = tuple(int(color[index:index + 2], 16) for index in (1, 3, 5))
    center = radius + 1
    for ring in range(radius, 0, -1):
        alpha = round(105 * (1.0 - ring / radius) ** 2)
        draw.ellipse((center - ring, center - ring, center + ring, center + ring),
                     fill=(*rgb, alpha))
    return glow


def render_reward_frame(model: RewardAnimationModel, bounds: tuple[int, int, int, int]) -> tuple[Image.Image, int, int]:
    """Rasterize source-demo visuals using real alpha over arbitrary page colors."""
    screen_x, screen_y, screen_width, screen_height = bounds
    points = [(point, 70.0 * flight.scale) for flight in model.flights
              for point in [flight.position, *(sample.position for sample in flight.trail)]]
    if not points:
        return Image.new("RGBA", (1, 1)), screen_x, screen_y
    left = max(screen_x, math.floor(min(point.x - radius for point, radius in points)))
    top = max(screen_y, math.floor(min(point.y - radius for point, radius in points)))
    right = min(screen_x + screen_width, math.ceil(max(point.x + radius for point, radius in points)))
    bottom = min(screen_y + screen_height, math.ceil(max(point.y + radius for point, radius in points)))
    if right <= left or bottom <= top:
        return Image.new("RGBA", (1, 1)), screen_x, screen_y
    # Supersampling smooths narrow trailing strokes and the expanding impact ring.
    factor = 2
    frame = Image.new("RGBA", ((right - left) * factor, (bottom - top) * factor))
    draw = ImageDraw.Draw(frame)

    def point(value: RewardPoint) -> tuple[float, float]:
        return (value.x - left) * factor, (value.y - top) * factor

    def circle(center: RewardPoint, radius: float, color, width: int = 0) -> None:
        x, y = point(center)
        radius *= factor
        box = (x - radius, y - radius, x + radius, y + radius)
        if width:
            draw.ellipse(box, outline=color, width=width)
        else:
            draw.ellipse(box, fill=color)

    for flight in model.flights:
        rgb = tuple(int(flight.color[index:index + 2], 16) for index in (1, 3, 5))
        scale = flight.scale
        if flight.phase is FlightPhase.HOMING:
            samples = flight.trail[::TRAIL_SAMPLE_STRIDE]
            for index in range(1, len(samples)):
                strength = index / len(samples)
                draw.line((point(samples[index - 1].position), point(samples[index].position)),
                          fill=(*rgb, round(255 * strength * TRAIL_HEAD_OPACITY)),
                          width=max(1, round(TRAIL_STROKE_WIDTH * scale * strength * factor)))
            radius = max(1, round(VISUAL_ORB_GLOW_RADIUS * scale * factor))
            glow = _orb_glow(radius, flight.color)
            x, y = point(flight.position)
            frame.alpha_composite(glow, (round(x - radius - 1), round(y - radius - 1)))
            circle(flight.position, VISUAL_ORB_RADIUS * scale, (*rgb, 255))
            circle(flight.position, VISUAL_ORB_HIGHLIGHT_RADIUS * scale, (255, 250, 228, 255))
        elif flight.phase is FlightPhase.BURST:
            progress = min(1.0, (flight.elapsed_ms - flight.burst_started_at_ms) / flight.config.burst_duration_ms)
            color = (*rgb, round(255 * (1.0 - progress)))
            radius = BURST_RING_RADIUS_START + (BURST_RING_RADIUS_END - BURST_RING_RADIUS_START) * progress
            circle(flight.position, radius * scale, color, width=max(1, round(2 * scale * factor)))
            for particle in flight.particles:
                circle(particle.position_at(flight.elapsed_ms), BURST_PARTICLE_RADIUS * scale, color)
    return frame.resize((right - left, bottom - top), Image.Resampling.LANCZOS), left, top


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
            if sys.platform != "win32":
                self.wm_attributes("-transparentcolor", self.TRANSPARENT_KEY)
        except tk.TclError:
            pass
        self._origin_x, self._origin_y, width, height = self._virtual_screen_bounds(parent)
        self._screen_bounds = (self._origin_x, self._origin_y, width, height)
        self._alpha_frame: Image.Image | None = None
        self._alpha_origin = (self._origin_x, self._origin_y)
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
                    get_parent = user32.GetParent
                    get_parent.argtypes, get_parent.restype = [wintypes.HWND], wintypes.HWND
                    parent_hwnd = int(get_parent(widget_hwnd) or 0)
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

                enumerate_children = user32.EnumChildWindows
                enumerate_children.argtypes = [wintypes.HWND, enumerator_type, wintypes.LPARAM]
                enumerate_children.restype = wintypes.BOOL
                enumerate_children(hwnd, collect, 0)
            except (AttributeError, OSError, TypeError, ValueError, ctypes.ArgumentError, tk.TclError):
                pass
        descendants, result = result, []
        for candidate in (hwnd, widget_hwnd, *descendants):
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
            # Tk's relative restack can replace the reference Toplevel's
            # pending geometry with its old native bounds. Raising this
            # already-topmost layer preserves the pet's queued movement.
            self.lift()
        except tk.TclError:
            pass

    def hide(self) -> None:
        if self.state() != "withdrawn":
            self.withdraw()

    def _canvas_point(self, point: RewardPoint) -> tuple[float, float]:
        return point.x - self._origin_x, point.y - self._origin_y

    def render(self, model: RewardAnimationModel, now_ms: float) -> None:
        frame, x, y = render_reward_frame(model, self._screen_bounds)
        self._alpha_frame, self._alpha_origin = frame, (x, y)
        if sys.platform == "win32":
            surfaces = self._native_surfaces()
            if not surfaces:
                raise RuntimeError("Reward layer has no native window")
            present_alpha_frame(surfaces[0], frame, x, y)
        else:
            from PIL import ImageTk
            self.canvas.delete("all")
            self._tk_frame = ImageTk.PhotoImage(frame)
            self.canvas.create_image(x - self._origin_x, y - self._origin_y,
                                     image=self._tk_frame, anchor=tk.NW)

    def destroy(self) -> None:
        self._restore_hit_test_passthrough()
        super().destroy()


class RewardEffectsController:
    def __init__(
        self,
        host: tk.Misc,
        target_provider: Callable[[], RewardTarget | RewardPoint | tuple[float, float] | None],
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
        self._render_error: str | None = None
        self._ready_last_tick = False

    def emit(self, source: RewardPoint | tuple[float, float], color: str) -> RewardFlight:
        if self._destroyed:
            raise RuntimeError("Reward effects controller is destroyed")
        target = self._advance_clock()
        flight = self.model.emit(source, color, self._animation_now_ms)
        flight.scale = (target.half_size if target is not None else self.pet_half_size) / REFERENCE_PET_HALF_SIZE
        try:
            if target is not None:
                self.layer.show()
                self.layer.render(self.model, self._animation_now_ms)
                self.layer.update_idletasks()
            else:
                self.layer.hide()
        except Exception as error:
            self._render_error = f"{type(error).__name__}: {error}"
            # A transient layer failure must not lose the flight or skip the
            # animation loop; the next tick retries showing the surface.
            pass
        if self._after_id is None:
            self._after_id = self.host.after(FRAME_MS, self._tick)
        return flight

    def keep_above(self, other: tk.Misc | None = None) -> None:
        self.layer.keep_above(other)

    def reset_target(self) -> None:
        """Retarget after layout migration without sweeping across a teleport."""
        self.model.reset_target()

    def clear(self) -> None:
        """Cancel all active flights and hide the transient layer immediately."""
        self.model.clear()
        if self._after_id is not None:
            try:
                self.host.after_cancel(self._after_id)
            except tk.TclError:
                pass
            self._after_id = None
        try:
            self.layer.hide()
        except tk.TclError:
            pass

    def _host_visible(self) -> bool:
        try:
            state = str(self.host.wm_state()) if hasattr(self.host, "wm_state") else "normal"
            focused = self.host.focus_displayof() is not None
            return bool(self.host.winfo_exists() and self.host.winfo_viewable()
                        and state not in ("iconic", "withdrawn") and focused)
        except tk.TclError:
            return False

    def _advance_clock(self) -> RewardTarget | None:
        wall_ms = _monotonic_ms()
        target = None
        try:
            raw = self.target_provider() if self._host_visible() else None
            if isinstance(raw, RewardTarget):
                target = raw
            elif raw is not None:
                target = RewardTarget(_coerce_point(raw), self.pet_half_size)
        except Exception:
            # Target widgets can disappear during a page or host rebuild.
            target = None
        if target is not None and self._ready_last_tick:
            self._animation_now_ms += min(MAXIMUM_FRAME_MS, max(0.0, wall_ms - self._last_wall_ms))
        elif target is None:
            self.model.pause(self._animation_now_ms)
        self._ready_last_tick = target is not None
        self._last_wall_ms = wall_ms
        return target

    def _tick(self) -> None:
        self._after_id = None
        if self._destroyed:
            return
        target = self._advance_clock()
        try:
            if target is not None:
                self.model.update(self._animation_now_ms, target.center, target.half_size, target.continuity_key)
            else:
                self.layer.hide()
        except Exception:
            self.model.pause(self._animation_now_ms)
        if target is not None and self.model.active_count:
            try:
                self.layer.show()
                self.layer.render(self.model, self._animation_now_ms)
                self.layer.keep_above()
                self._render_error = None
            except Exception as error:
                # Keep the animation alive, but retain one diagnostic for the
                # smoke/debug caller instead of silently hiding a bad Canvas
                # option or native window state.
                self._render_error = f"{type(error).__name__}: {error}"
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
