from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import ctypes
import ctypes.wintypes as wintypes
import math
import sys
import time
import tkinter as tk
from typing import Callable

STUDY_REWARD_COLOR = "#F4C542"
FRAME_MS = 16
WM_NCHITTEST = 0x0084
WM_MOUSEACTIVATE = 0x0021
HTTRANSPARENT = -1
MA_NOACTIVATE = 3
_GWL_WNDPROC = -4


@dataclass(frozen=True)
class RewardPoint:
    x: float
    y: float

    def __add__(self, other: RewardPoint) -> RewardPoint:
        return RewardPoint(self.x + other.x, self.y + other.y)

    def __sub__(self, other: RewardPoint) -> RewardPoint:
        return RewardPoint(self.x - other.x, self.y - other.y)

    def scaled(self, amount: float) -> RewardPoint:
        return RewardPoint(self.x * amount, self.y * amount)

    @property
    def length(self) -> float:
        return math.hypot(self.x, self.y)

    def normalized(self) -> RewardPoint:
        length = self.length
        return self.scaled(1.0 / length) if length > 1e-6 else RewardPoint(0.0, 0.0)

    def distance_to(self, other: RewardPoint) -> float:
        return (self - other).length


def _point(value: RewardPoint | tuple[float, float] | None) -> RewardPoint | None:
    if value is None or isinstance(value, RewardPoint):
        return value
    return RewardPoint(float(value[0]), float(value[1]))


def trail_length_for_speed(speed: float) -> float:
    """Return a short, speed-aware tail length for the v2 renderer."""
    value = max(0.0, float(speed)) if math.isfinite(float(speed)) else 0.0
    return min(84.0, 18.0 + value * 0.025)


def clip_trail_to_length(samples: list[RewardPoint], maximum_length: float) -> list[RewardPoint]:
    """Keep the newest trail suffix within a geometric length budget."""
    if not samples:
        return []
    limit = max(0.0, float(maximum_length))
    result = [samples[-1]]
    length = 0.0
    for index in range(len(samples) - 2, -1, -1):
        segment = samples[index].distance_to(result[-1])
        if length + segment > limit:
            break
        result.append(samples[index])
        length += segment
    return list(reversed(result))

def transparent_hit_test_result(message: int) -> int | None:
    try:
        return HTTRANSPARENT if int(message) == WM_NCHITTEST else None
    except (TypeError, ValueError):
        return None


class FlightPhase(str, Enum):
    INTRO = "intro"
    SEEK = "seek"
    BURST = "burst"
    FINISHED = "finished"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class OrbConfig:
    intro_ms: float = 150.0
    intro_arc: float = 15.0
    seek_speed: float = 260.0
    seek_acceleration: float = 1900.0
    max_speed: float = 1800.0
    contact_radius: float = 7.0
    burst_ms: float = 280.0
    burst_particles: int = 12
    max_age_ms: float = 2400.0
    missing_target_ms: float = 600.0


DEFAULT_CONFIG = OrbConfig()
# Public visual tuning values used by diagnostics and future themes.
VISUAL_ORB_RADIUS = 11.0
VISUAL_ORB_GLOW_RADIUS = 27.0
VISUAL_ORB_HIGHLIGHT_RADIUS = 2.5
TRAIL_MINIMUM_STROKE_WIDTH = 2.0
TRAIL_MAXIMUM_STROKE_WIDTH = 6.0
TRAIL_GLOW_WIDTH_MULTIPLIER = 1.7
BURST_PARTICLE_RADIUS = 3.0
BURST_PARTICLE_GLOW_RADIUS = 7.0
BURST_PARTICLE_COUNT = DEFAULT_CONFIG.burst_particles


@dataclass(frozen=True)
class Particle:
    direction: RewardPoint
    speed: float

    def position(self, origin: RewardPoint, elapsed_ms: float) -> RewardPoint:
        t = max(0.0, elapsed_ms) / 1000.0
        distance = self.speed * t * max(0.0, 1.0 - t / 0.34)
        return origin + self.direction.scaled(distance)


@dataclass
class RewardFlight:
    flight_id: int
    source: RewardPoint
    color: str
    created_at_ms: float
    config: OrbConfig = DEFAULT_CONFIG
    phase: FlightPhase = FlightPhase.INTRO
    position: RewardPoint = field(init=False)
    velocity: RewardPoint = field(default_factory=lambda: RewardPoint(0.0, 0.0))
    trail: list[RewardPoint] = field(default_factory=list)
    particles: list[Particle] = field(default_factory=list)
    burst_started_at_ms: float | None = None
    contact_point: RewardPoint | None = None
    missing_since_ms: float | None = None
    last_update_ms: float = field(init=False)

    def __post_init__(self) -> None:
        self.position = self.source
        self.last_update_ms = self.created_at_ms
        self.trail = [self.source]

    @property
    def active(self) -> bool:
        return self.phase not in (FlightPhase.FINISHED, FlightPhase.CANCELLED)

    @property
    def speed(self) -> float:
        return self.velocity.length

    def _hit(self, target: RewardPoint, now_ms: float, pet_half_size: float) -> bool:
        if self.position.distance_to(target) <= max(1.0, pet_half_size) + self.config.contact_radius:
            self.phase = FlightPhase.BURST
            self.contact_point = self.position
            self.burst_started_at_ms = now_ms
            self.velocity = RewardPoint(0.0, 0.0)
            count = max(4, self.config.burst_particles)
            self.particles = [
                Particle(RewardPoint(math.cos(math.tau * i / count), math.sin(math.tau * i / count)), 90.0 + (i % 3) * 26.0)
                for i in range(count)
            ]
            return True
        return False

    def update(self, now_ms: float, target: RewardPoint | tuple[float, float] | None, pet_half_size: float) -> bool:
        if not self.active:
            return False
        now_ms = max(self.last_update_ms, float(now_ms))
        age = now_ms - self.created_at_ms
        target_point = _point(target)
        if self.phase is not FlightPhase.BURST and age >= self.config.max_age_ms:
            self.phase = FlightPhase.CANCELLED
            return False
        if target_point is None:
            self.missing_since_ms = now_ms if self.missing_since_ms is None else self.missing_since_ms
            if now_ms - self.missing_since_ms >= self.config.missing_target_ms:
                self.phase = FlightPhase.CANCELLED
                return False
        else:
            self.missing_since_ms = None
        if self.phase is FlightPhase.BURST:
            if self.burst_started_at_ms is not None and now_ms - self.burst_started_at_ms >= self.config.burst_ms:
                self.phase = FlightPhase.FINISHED
                return False
            self.last_update_ms = now_ms
            return True
        previous = self.position
        if self.phase is FlightPhase.INTRO:
            p = min(1.0, max(0.0, age / self.config.intro_ms))
            eased = p * p * (3.0 - 2.0 * p)
            angle = math.tau * (0.15 + 0.55 * p)
            radius = self.config.intro_arc * (1.0 - p)
            self.position = self.source + RewardPoint(math.cos(angle) * radius, math.sin(angle) * radius)
            if p >= 1.0:
                self.phase = FlightPhase.SEEK
                if target_point is not None:
                    self.velocity = (target_point - self.position).normalized().scaled(self.config.seek_speed)
        elif target_point is not None:
            dt = max(0.0, now_ms - self.last_update_ms) / 1000.0
            direction = (target_point - self.position).normalized()
            self.velocity = self.velocity + direction.scaled(self.config.seek_acceleration * dt)
            if self.speed > self.config.max_speed:
                self.velocity = self.velocity.normalized().scaled(self.config.max_speed)
            self.position = self.position + self.velocity.scaled(dt)
            self._hit(target_point, now_ms, pet_half_size)
        self.trail.append(self.position)
        if len(self.trail) > 14:
            del self.trail[:-14]
        self.last_update_ms = now_ms
        return True


class RewardFeedbackModel:
    def __init__(self, config: OrbConfig = DEFAULT_CONFIG):
        self.config = config
        self.flights: list[RewardFlight] = []
        self._next_id = 1

    @property
    def active_count(self) -> int:
        return sum(f.active for f in self.flights)

    def emit(self, source: RewardPoint | tuple[float, float], color: str, now_ms: float | None = None) -> RewardFlight:
        flight = RewardFlight(self._next_id, _point(source) or RewardPoint(0.0, 0.0), str(color), _clock() if now_ms is None else float(now_ms), self.config)
        self._next_id += 1
        self.flights.append(flight)
        return flight

    def update(self, now_ms: float, target: RewardPoint | tuple[float, float] | None, pet_half_size: float) -> None:
        for flight in tuple(self.flights):
            flight.update(now_ms, target, pet_half_size)
        self.flights[:] = [flight for flight in self.flights if flight.active]

    def clear(self) -> None:
        self.flights.clear()


def _clock() -> float:
    return time.monotonic_ns() / 1_000_000.0


class RewardFeedbackLayer(tk.Toplevel):
    TRANSPARENT_KEY = "#ff00ff"

    def __init__(self, parent: tk.Misc):
        super().__init__(parent)
        self.withdraw()
        self.overrideredirect(True)
        self.configure(bg=self.TRANSPARENT_KEY, bd=0, highlightthickness=0)
        try:
            self.wm_attributes("-topmost", True)
            self.wm_attributes("-transparentcolor", self.TRANSPARENT_KEY)
        except tk.TclError:
            pass
        self._origin_x, self._origin_y, width, height = self._bounds(parent)
        self.geometry(f"{width}x{height}{self._origin_x:+d}{self._origin_y:+d}")
        self.canvas = tk.Canvas(self, bg=self.TRANSPARENT_KEY, bd=0, highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True)
        self.update_idletasks()
        self._passthrough_handles: list[tuple[int, int]] = []
        self._passthrough_callbacks: list[object] = []
        self._passthrough_failures: list[int] = []
        self._call_window_proc = None
        self._enable_mouse_passthrough()

    @staticmethod
    def _bounds(parent: tk.Misc) -> tuple[int, int, int, int]:
        if sys.platform == "win32":
            u = ctypes.windll.user32
            return int(u.GetSystemMetrics(76)), int(u.GetSystemMetrics(77)), max(1, int(u.GetSystemMetrics(78))), max(1, int(u.GetSystemMetrics(79)))
        return 0, 0, max(1, parent.winfo_screenwidth()), max(1, parent.winfo_screenheight())

    def _native_surfaces(self) -> list[int]:
        """Return the Tk top-level and every native child surface."""
        try:
            widget_hwnd = int(self.winfo_id() or 0)
        except (tk.TclError, TypeError, ValueError):
            return []
        root_hwnd = widget_hwnd
        handles: list[int] = []
        if sys.platform == "win32":
            try:
                user32 = ctypes.windll.user32
                get_style = getattr(user32, "GetWindowLongPtrW", None) or user32.GetWindowLongW
                get_style.restype = ctypes.c_void_p
                get_style.argtypes = [wintypes.HWND, ctypes.c_int]
                if int(get_style(widget_hwnd, -16) or 0) & 0x40000000:  # WS_CHILD
                    root_hwnd = int(user32.GetParent(widget_hwnd) or widget_hwnd)
                enum_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
                @enum_type
                def collect(child_hwnd, _lparam):
                    handles.append(int(child_hwnd))
                    return True
                user32.EnumChildWindows(root_hwnd, collect, 0)
            except (AttributeError, OSError, TypeError, ValueError, ctypes.ArgumentError, tk.TclError):
                pass
        for value in (root_hwnd, widget_hwnd):
            if value and value not in handles:
                handles.append(value)
        return handles

    def _enable_mouse_passthrough(self) -> None:
        if sys.platform != "win32":
            return
        try:
            u = ctypes.windll.user32
            surfaces = self._native_surfaces()
            if not surfaces:
                return
            get_style = getattr(u, "GetWindowLongPtrW", None) or u.GetWindowLongW
            set_style = getattr(u, "SetWindowLongPtrW", None) or u.SetWindowLongW
            get_style.restype = ctypes.c_void_p
            set_style.restype = ctypes.c_void_p
            top_level = surfaces[0]
            extended_style = int(get_style(top_level, -20) or 0)
            set_style(top_level, -20, extended_style | 0x00000020 | 0x00080000 | 0x08000000 | 0x00000080)
            for hwnd in surfaces:
                self._install_hit_test_passthrough(u, hwnd)
        except (AttributeError, OSError, TypeError, ValueError, ctypes.ArgumentError, tk.TclError):
            return

    def _install_hit_test_passthrough(self, user32, hwnd: int) -> bool:
        if any(h == hwnd for h, _ in self._passthrough_handles):
            return True
        get_proc = getattr(user32, "GetWindowLongPtrW", None) or user32.GetWindowLongW
        set_proc = getattr(user32, "SetWindowLongPtrW", None) or user32.SetWindowLongW
        call_proc = user32.CallWindowProcW
        pointer = ctypes.c_ssize_t if ctypes.sizeof(ctypes.c_void_p) > 4 else ctypes.c_long
        proc_type = ctypes.WINFUNCTYPE(pointer, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
        original = get_proc(hwnd, _GWL_WNDPROC)
        if not original:
            self._passthrough_failures.append(hwnd)
            return False
        original = int(original)
        @proc_type
        def callback(window, message, wparam, lparam):
            if transparent_hit_test_result(message) == HTTRANSPARENT:
                return HTTRANSPARENT
            if int(message) == WM_MOUSEACTIVATE:
                return MA_NOACTIVATE
            try:
                return call_proc(original, window, message, wparam, lparam)
            except Exception:
                return 0
        try:
            set_proc(hwnd, _GWL_WNDPROC, callback)
        except Exception:
            self._passthrough_failures.append(hwnd)
            return False
        self._passthrough_handles.append((hwnd, original))
        self._passthrough_callbacks.append(callback)
        self._call_window_proc = call_proc
        return True

    def native_hit_test(self, hwnd: int, x: int, y: int) -> int:
        if sys.platform != "win32":
            return 0
        try:
            return int(ctypes.windll.user32.SendMessageW(hwnd, WM_NCHITTEST, 0, ((int(y) & 0xFFFF) << 16) | (int(x) & 0xFFFF)))
        except Exception:
            return 0

    def show(self) -> None:
        if self.state() == "withdrawn":
            self.deiconify()
        self.lift()
        self._enable_mouse_passthrough()

    def hide(self) -> None:
        try:
            self.withdraw()
        except tk.TclError:
            pass

    def keep_above(self, other: tk.Misc | None = None) -> None:
        try:
            self.lift(aboveThis=other) if other is not None else self.lift()
        except tk.TclError:
            pass

    def _xy(self, p: RewardPoint) -> tuple[float, float]:
        return p.x - self._origin_x, p.y - self._origin_y

    def render(self, model: RewardFeedbackModel, now_ms: float) -> None:
        self.canvas.delete("all")
        for flight in model.flights:
            if len(flight.trail) > 1:
                for i, (a, b) in enumerate(zip(flight.trail, flight.trail[1:]), 1):
                    x1, y1 = self._xy(a); x2, y2 = self._xy(b)
                    width = TRAIL_MINIMUM_STROKE_WIDTH + (TRAIL_MAXIMUM_STROKE_WIDTH - TRAIL_MINIMUM_STROKE_WIDTH) * i / len(flight.trail)
                    self.canvas.create_line(x1, y1, x2, y2, fill=flight.color, width=width * TRAIL_GLOW_WIDTH_MULTIPLIER, stipple="gray50", capstyle=tk.ROUND)
                    self.canvas.create_line(x1, y1, x2, y2, fill=flight.color, width=width, capstyle=tk.ROUND)
            if flight.phase in (FlightPhase.INTRO, FlightPhase.SEEK):
                x, y = self._xy(flight.position)
                pulse = 1.0 + 0.08 * math.sin((now_ms - flight.created_at_ms) / 110.0)
                glow = VISUAL_ORB_GLOW_RADIUS * pulse
                self.canvas.create_oval(x-glow, y-glow, x+glow, y+glow, fill=flight.color, outline="", stipple="gray25")
                self.canvas.create_oval(x-17, y-17, x+17, y+17, outline=flight.color, width=1)
                r = VISUAL_ORB_RADIUS * pulse
                self.canvas.create_oval(x-r, y-r, x+r, y+r, fill=flight.color, outline=flight.color)
                h = VISUAL_ORB_HIGHLIGHT_RADIUS
                self.canvas.create_oval(x-r*.35-h, y-r*.4-h, x-r*.35+h, y-r*.4+h, fill="#FFFFFF", outline="#FFFFFF")
            elif flight.phase is FlightPhase.BURST and flight.contact_point is not None and flight.burst_started_at_ms is not None:
                elapsed = now_ms - flight.burst_started_at_ms
                p = min(1.0, max(0.0, elapsed / flight.config.burst_ms))
                x, y = self._xy(flight.contact_point)
                radius = 10.0 + 42.0 * (1.0 - (1.0-p)*(1.0-p))
                self.canvas.create_oval(x-radius, y-radius, x+radius, y+radius, outline=flight.color, width=max(1, round(3*(1-p))))
                for particle in flight.particles:
                    px, py = self._xy(particle.position(flight.contact_point, elapsed))
                    r = BURST_PARTICLE_RADIUS * (1.0 - .45*p)
                    self.canvas.create_oval(px-BURST_PARTICLE_GLOW_RADIUS, py-BURST_PARTICLE_GLOW_RADIUS, px+BURST_PARTICLE_GLOW_RADIUS, py+BURST_PARTICLE_GLOW_RADIUS, fill=flight.color, outline="", stipple="gray50")
                    self.canvas.create_oval(px-r, py-r, px+r, py+r, fill=flight.color, outline=flight.color)

    def destroy(self) -> None:
        if sys.platform == "win32":
            try:
                u = ctypes.windll.user32
                set_proc = getattr(u, "SetWindowLongPtrW", None) or u.SetWindowLongW
                for hwnd, original in self._passthrough_handles:
                    set_proc(hwnd, _GWL_WNDPROC, original)
            except Exception:
                pass
        self._passthrough_handles.clear(); self._passthrough_callbacks.clear()
        super().destroy()


class RewardFeedbackController:
    def __init__(self, host: tk.Misc, target_provider: Callable[[], RewardPoint | tuple[float, float] | None], *, pet_half_size: float, config: OrbConfig = DEFAULT_CONFIG):
        self.host = host
        self.target_provider = target_provider
        self.pet_half_size = float(pet_half_size)
        self.model = RewardFeedbackModel(config)
        self.layer = RewardFeedbackLayer(host)
        self._after_id: str | None = None
        self._destroyed = False
        self._now = _clock()

    def emit(self, source: RewardPoint | tuple[float, float], color: str) -> RewardFlight:
        if self._destroyed:
            raise RuntimeError("Reward effects controller is destroyed")
        self._now = _clock()
        flight = self.model.emit(source, color, self._now)
        try: self.layer.show()
        except tk.TclError: pass
        if self._after_id is None:
            self._after_id = self.host.after(FRAME_MS, self._tick)
        return flight

    def keep_above(self, other: tk.Misc | None = None) -> None:
        self.layer.keep_above(other)

    def _tick(self) -> None:
        self._after_id = None
        if self._destroyed: return
        self._now = _clock()
        try:
            target = self.target_provider()
            self.model.update(self._now, target, self.pet_half_size)
            if self.model.active_count:
                self.layer.show(); self.layer.render(self.model, self._now); self.layer.keep_above()
            else:
                self.layer.hide()
        except Exception:
            pass
        if self.model.active_count and not self._destroyed:
            self._after_id = self.host.after(FRAME_MS, self._tick)

    def destroy(self) -> None:
        if self._destroyed: return
        self._destroyed = True
        if self._after_id is not None:
            try: self.host.after_cancel(self._after_id)
            except tk.TclError: pass
            self._after_id = None
        self.model.clear()
        try: self.layer.destroy()
        except tk.TclError: pass










