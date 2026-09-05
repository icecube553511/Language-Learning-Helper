from __future__ import annotations

from datetime import datetime
from dataclasses import dataclass, replace
from pathlib import Path
import random
import re
import time
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import tkinter.font as tkfont
from typing import Callable

from application.services import LearningService
from domain.models import (
    DEFAULT_FONT_SCALE,
    ImportReport,
    ReviewRating,
    VocabularyEntry,
    font_scale_from_percent,
    sanitize_font_scale,
)
from domain.dictation import (
    DictationDraft,
    DictationDraftSyncMetadata,
    DictationField,
    DictationFormat,
    DictationOptions,
    MarkMode,
    dictation_range_ids,
    nearest_dictation_id,
    normalize_word_id,
)
from domain.dictation_sync import (
    DictationDraftSyncResult,
    DictationDraftSyncStatus,
)
from domain.pet_companion import (
    CRUISE_SPEED,
    estimate_release_velocity,
    PET_DISPLAY_SIZE,
    PET_TICK_MS,
    PetCompanion,
    PetFacing,
    PetMode,
    PetPoint,
    PetRect,
    PetState,
    PetTarget,
    PetTargetKind,
)
from presentation.pet_windows import (
    PetWindow,
    interpolate_pet_position,
    map_pet_entry,
    portal_direction,
    portal_ray_origin,
    predicted_exit_times,
    select_adjacent_window_hit,
    state_at_exit,
)
from presentation.reward_effects import (
    REVIEW_REWARD_COLOR,
    RewardEffectsController,
    RewardPoint,
    STUDY_REWARD_COLOR,
)
from presentation.widgets import (
    DictationLoadingOverlay,
    MemoryChart,
    NavItem,
    PetOverlay,
    ScrollableExamplePanel,
    WordBubbleManager,
    WordClickableText,
    centered_window_position,
    draw_icon,
)


BG = "#F3F6F7"
SURFACE = "#FFFFFF"
SIDEBAR = "#17212B"
TEXT = "#1B2733"
MUTED = "#65727E"
ACCENT = "#16866F"
ACCENT_HOVER = "#11705E"
BLUE = "#3973C6"
ORANGE = "#D9822B"
RED = "#C94B50"
BORDER = "#DDE3E8"
PET_RENDER_FRAME_MS = 4
PET_CONTROL_CLASSES = {
    "Button", "TButton", "Entry", "TEntry", "Checkbutton", "TCheckbutton",
    "Radiobutton", "TRadiobutton", "Scale", "TScale", "Spinbox", "TSpinbox",
    "Scrollbar", "TScrollbar", "Treeview", "TCombobox", "Listbox", "Text",
}
REMINDER_POPUP_WIDTH = 680
REMINDER_POPUP_HEIGHT = 760
REMINDER_EXAMPLES_WIDTH = 624
REMINDER_EXAMPLES_HEIGHT = 220
DICTATION_MEANING_COLUMN_WIDTH = 260
DICTATION_SELECTION_COLUMN_WIDTH = 76
DICTATION_CHECKBOX_FONT = ("Microsoft YaHei UI", 16)
DICTATION_CHECKBOX_PAD_Y = 4
DICTATION_RENDER_BUFFER = 20


def scroll_contract_ready(
    is_scrollable: bool,
    did_scroll: bool,
    before: list[float],
    after: list[float],
) -> bool:
    if is_scrollable:
        return did_scroll
    return before == [0.0, 1.0] and after == [0.0, 1.0]


@dataclass(frozen=True)
class DictationCandidateDisplay:
    word: str
    meaning: str
    tags: str
    evaluation_status: str
    evaluation_color: str


@dataclass(frozen=True)
class DictationGroupNavigation:
    """Transient group-browser state for the dictation page."""

    mode: str = "random"
    scope_group: str = "all"
    open_group: str | None = None


def preserve_pet_motion_for_targets(
    state: PetState,
    targets: list[PetTarget] | tuple[PetTarget, ...],
) -> PetState:
    """Drop a stale support id without resetting the companion's motion.

    Rating a card briefly unmaps the old answer/rating controls while the next
    card is laid out.  The support id is presentation-scoped, so retaining it
    through that gap would make the domain reducer interpret a normal layout
    refresh as a lost support and transition to FALL (clearing velocities).
    """
    target_id = state.target_id
    if not target_id or target_id == "__viewport-bottom__":
        return state
    if any(target.valid and target.id == target_id for target in targets):
        return state
    return replace(
        state,
        target_id=None,
        path_index=0,
        path_direction=1,
        roll_corners=0,
        avoid_target_id=None,
        curve_velocity=None,
    )


def _transfer_pet_axis(
    value: float,
    extent: float,
    pet_half_size: float,
    *,
    preserve_out_of_bounds: bool = False,
) -> float:
    """Map one host coordinate without collapsing an active fall."""
    half = max(0.0, float(pet_half_size))
    coordinate = float(value)
    if preserve_out_of_bounds and (coordinate < half or coordinate > extent - half):
        return coordinate
    return min(max(coordinate, half), max(half, extent - half))


def open_dictation_group(
    state: DictationGroupNavigation,
    group: str,
) -> DictationGroupNavigation:
    """Open a wordbook, and make it the random scope in random mode."""
    return replace(
        state,
        scope_group=group if state.mode == "random" else state.scope_group,
        open_group=group,
    )


def set_dictation_group_mode(
    state: DictationGroupNavigation,
    mode: str,
) -> DictationGroupNavigation:
    """Switch modes without losing the wordbook currently being inspected."""
    normalized_mode = "manual" if mode == "manual" else "random"
    scope_group = state.scope_group
    if normalized_mode == "random" and state.open_group is not None:
        scope_group = state.open_group
    return replace(state, mode=normalized_mode, scope_group=scope_group)


def close_dictation_group(state: DictationGroupNavigation) -> DictationGroupNavigation:
    return replace(state, open_group=None)


@dataclass
class DialogPetRuntime:
    key: str
    companion: PetCompanion
    overlay: PetOverlay
    drag_offset: PetPoint = PetPoint(0.0, 0.0)
    drag_samples: list[tuple[float, PetPoint]] | None = None
    tick_after_id: str | None = None
    render_after_ids: list[str] | None = None
    last_rendered_position: PetPoint | None = None
    render_generation: int = 0


def _resolve_pet_release_host(
    source_host: object,
    active_host: object | None,
    final_move: Callable[[], object | None],
) -> tuple[object | None, bool]:
    """Re-read pet ownership when the release event supplies the final move."""
    if active_host is None or active_host is source_host:
        return final_move(), True
    return active_host, False


def dictation_candidate_display(entry: VocabularyEntry) -> DictationCandidateDisplay:
    normalized_tags = sorted({tag.strip().casefold() for tag in entry.tags if tag.strip()})
    evaluated = "evaluated" in normalized_tags
    visible_tags = [tag for tag in normalized_tags if tag != "evaluated"]
    return DictationCandidateDisplay(
        word=entry.word,
        meaning=" ".join(entry.meaning.splitlines()),
        tags=" / ".join(visible_tags) or "-",
        evaluation_status="已考察" if evaluated else "未考察",
        evaluation_color="#000000" if evaluated else RED,
    )


def dictation_preview_blocks(document) -> list[str]:
    blocks: list[str] = []
    for index, row in enumerate(document.rows, 1):
        fields = "    ".join((row.word, row.part_of_speech, row.meaning)).rstrip()
        lines = [f"{index}. {fields}"]
        for offset, example in enumerate(row.examples):
            chinese = row.example_chinese[offset] if offset < len(row.example_chinese) else ""
            suffix = f"（{chinese}）" if chinese else ""
            lines.append(f"    e.g. {example}{suffix}")
        blocks.append("\n".join(lines))
    return blocks


def visible_dictation_selection(
    selected_ids: set[str],
    entries: list[VocabularyEntry],
) -> set[str]:
    return selected_ids & {entry.word_id for entry in entries}


def distribute_dictation_columns(
    word_width: int,
    meaning_width: int,
    tags_width: int,
    viewport_width: int,
    *,
    fixed_widths: int = 120 + DICTATION_SELECTION_COLUMN_WIDTH,
    minimum_word: int = 170,
    minimum_tags: int = 200,
) -> tuple[int, int, int]:
    """Grow the word/meaning/tags columns so the table fills the viewport.

    The status and selection columns stay fixed. When the viewport is wider
    than the content, spare width is distributed: meaning gets half, then
    word and tags split the rest. The three minimums are preserved so the
    table still scrolls horizontally when content is narrow.
    """
    minimums = word_width + meaning_width + tags_width + fixed_widths
    if viewport_width <= minimums:
        return word_width, meaning_width, tags_width
    headroom = viewport_width - minimums
    meaning_extra = int(headroom * 0.5)
    meaning_width += meaning_extra
    remaining = headroom - meaning_extra
    word_base = max(word_width, minimum_word)
    tags_base = max(tags_width, minimum_tags)
    word_extra = min(remaining, max(0, int(remaining * 0.4)))
    word_width = word_base + word_extra
    tags_width = tags_base + max(0, remaining - word_extra)
    return word_width, meaning_width, tags_width


def dictation_render_range(
    row_tops: list[int],
    row_heights: list[int],
    viewport_top: float,
    viewport_bottom: float,
    buffer: int = DICTATION_RENDER_BUFFER,
) -> tuple[int, int]:
    """Return the [start, end] row band that must be rendered.

    Only rows intersecting the viewport plus ``buffer`` rows on each side are
    needed; rows farther away are never drawn.
    """
    total = len(row_tops)
    if total == 0:
        return 0, -1
    first = 0
    while first < total and row_tops[first] + row_heights[first] < viewport_top:
        first += 1
    last = total - 1
    while last > 0 and row_tops[last] > viewport_bottom:
        last -= 1
    return max(0, first - buffer), min(total - 1, last + buffer)


def dictation_loading_delay_ms(rand: random.Random | None = None) -> int:
    """Random 1-2 second delay in 100 ms steps for the dictation entry animation."""
    rng = rand or random.SystemRandom()
    return rng.randint(10, 20) * 100


def dictation_preview_scroll_units(delta: int) -> tuple[int, int]:
    """Return ``(direction, units)`` for a dictation-preview mouse-wheel delta.

    Positive deltas scroll up; the step count scales with the delta so a single
    notch on Windows (typically ±120) moves the preview by one line unit.
    """
    if not delta:
        return 0, 0
    units = max(1, abs(delta) // 120)
    return (-1 if delta > 0 else 1), units


class FontManager:
    BASE_SIZES = {
        "LexiChart": 9,
        "LexiExample": 12,
        "LexiMeaningCompact": 11,
        "LexiSmall": 11,
        "LexiBody": 13,
        "LexiBodyBold": 13,
        "LexiHeading": 18,
        "LexiTitle": 24,
        "LexiWord": 28,
        "LexiMono": 14,
    }

    def __init__(self, root: tk.Tk, scale: object):
        self.root = root
        self.fonts: dict[str, tkfont.Font] = {}
        for name, size in self.BASE_SIZES.items():
            family = "Consolas" if name == "LexiMono" else "Microsoft YaHei UI"
            weight = "bold" if name in {"LexiBodyBold", "LexiHeading", "LexiTitle", "LexiWord", "LexiMeaningCompact"} else "normal"
            self.fonts[name] = tkfont.Font(root=root, name=name, family=family, size=size, weight=weight)
        self.apply(scale)

    def apply(self, scale: object):
        scale = sanitize_font_scale(scale, fallback=DEFAULT_FONT_SCALE)
        for name, base_size in self.BASE_SIZES.items():
            if name == "LexiExample":
                size = min(14, max(11, round(base_size * scale)))
            else:
                size = max(8, round(base_size * scale))
            self.fonts[name].configure(size=size)


class LexiTrackApp(tk.Tk):
    def __init__(
        self,
        service: LearningService,
        data_dir: Path,
        catalog_count: int,
        catalog_rejected: int = 0,
        catalog_error: str = "",
        pet_asset_path: Path | None = None,
        pet_asset_left_path: Path | None = None,
        dictation_sync_account_id: str | None = None,
    ):
        super().__init__()
        self.service = service
        self.data_dir = data_dir
        self.catalog_count = catalog_count
        self.catalog_rejected = catalog_rejected
        self.catalog_error = catalog_error
        self.pet_asset_path = pet_asset_path
        self.pet_asset_left_path = pet_asset_left_path
        # The account identifier is supplied by the composition root only;
        # presentation never reads endpoint or token configuration.
        self.dictation_sync_account_id = (dictation_sync_account_id or "").strip()
        self._dictation_sync_generation = 0
        self._dictation_sync_in_flight = False
        self._dictation_window_active = False
        self._smoke_testing = False
        self._dictation_sync_conflict: DictationDraftSyncResult | None = None
        # The editor keeps the last server token alongside its transient
        # controls.  New immutable drafts can therefore retain optimistic
        # concurrency metadata instead of resetting to revision ``0``.
        self._dictation_sync_metadata = DictationDraftSyncMetadata()
        self.title("LexiTrack 词程")
        self.geometry("1220x800")
        self.minsize(960, 700)
        self.configure(bg=BG)
        self.protocol("WM_DELETE_WINDOW", self._on_window_close)
        initial_font_scale = sanitize_font_scale(
            self.service.font_scale(),
            fallback=DEFAULT_FONT_SCALE,
        )
        self.font_manager = FontManager(self, initial_font_scale)
        self._configure_styles()
        self.pages: dict[str, tk.Frame] = {}
        self.nav_items: dict[str, NavItem] = {}
        self.current_page = ""
        self.current_card: VocabularyEntry | None = None
        self.review_queue: list[VocabularyEntry] = []
        self.review_total = 0
        self.review_answer_visible = False
        self._last_reminded_due_count = 0
        self._word_reminder_after_id: str | None = None
        self._word_reminder_popup: tk.Toplevel | None = None
        self._word_reminder_examples_view: ScrollableExamplePanel | None = None
        self._word_reminder_example_labels: list[tk.Label] = []
        self._word_reminder_is_preview = False
        self._word_reminder_previous_id = ""
        self._word_reminder_next_at = 0.0
        self.answer_visible = False
        self.forecast_days = 7
        self._dialog_pet_runtimes: dict[tk.Toplevel, DialogPetRuntime] = {}
        self._dialog_pet_stack: list[tk.Toplevel] = []
        self.word_bubbles = WordBubbleManager(
            self,
            self.service,
            pet_half_size=PET_DISPLAY_SIZE // 2,
        )
        self.dictation_document = None
        self.dictation_document_word_ids: set[str] = set()
        self.dictation_selected_ids: set[str] = set()
        # Contract marker: this is the explicit cross-group random subset
        # consumed by LearningService.dictation_candidates.
        self.dictationRandomCandidateIds: set[str] = set()
        # Selection is global so random mode can sample across books; the
        # per-group maps retain range/scroll state when users switch books.
        self.dictation_group_selected_ids: dict[str, set[str]] = {}
        self.dictation_group_anchors: dict[str, str | None] = {}
        self.dictation_group_endpoints: dict[str, str | None] = {}
        self.dictation_group_scroll_positions: dict[str, float] = {}
        self.dictation_expanded_groups: set[str] = set()
        self.dictation_range_enabled = True
        self.dictation_range_marker_text = "选取到这里"
        self._dictation_saved_fingerprint: tuple | None = None
        self._dictation_restored = False
        self._dictation_ignore_dirty = False
        self._dictation_loading: DictationLoadingOverlay | None = None
        self._dictation_loading_after_id: str | None = None
        self.pet_companion = PetCompanion(
            PetState(PetPoint(120.0, 120.0)),
            speed=CRUISE_SPEED,
            pet_size=PET_DISPLAY_SIZE / 2.0,
        )
        self._pet_image_sources: dict[PetFacing, tk.PhotoImage] = {}
        self._pet_images: dict[PetFacing, tk.PhotoImage] = {}
        self._pet_image_source: tk.PhotoImage | None = None
        self._pet_image: tk.PhotoImage | None = None
        self._pet_overlay: PetOverlay | None = None
        self._pet_targets: tuple[PetTarget, ...] = ()
        self._pet_refresh_after_id: str | None = None
        self._pet_tick_after_id: str | None = None
        self._pet_tick_failures = 0
        self._pet_render_after_ids: list[str] = []
        self._pet_render_generation = 0
        self._pet_drag_offset = PetPoint(0.0, 0.0)
        self._pet_drag_samples: list[tuple[float, PetPoint]] = []
        self._pet_dragging = False
        # The active drag host can be the root window or any dialog.  Keeping
        # the common ``tk.Misc`` type lets a grabbed overlay route a release
        # after the pet crosses back into the root host.
        self._pet_drag_host_dialog: tk.Misc | None = None
        self._pet_last_rendered_position: PetPoint | None = None
        self._pet_trace_handle = None
        self._pet_trace_after_id: str | None = None
        self._reward_effects: RewardEffectsController | None = None
        self._build_shell()
        self._build_pages()
        self._bind_shortcuts()
        self._setup_pet_overlay()
        self._reward_effects = RewardEffectsController(
            self,
            self._reward_pet_center,
            pet_half_size=PET_DISPLAY_SIZE / 2.0,
        )
        self.show_page("dashboard")
        self.after(1_000, self._check_review_reminder)
        self.after(250, self._schedule_word_reminder)
        # Optional remote restore is initiated from the presentation edge but
        # executed off the Tk event loop.  The service/port remains the only
        # layer that knows how to decode or persist a remote envelope.
        self.after_idle(self._pull_dictation_draft_async)

    def _setup_pet_overlay(self) -> None:
        """Load the injected runtime sprite and start the transient UI companion."""
        right_path = self.pet_asset_path
        if right_path is None or not right_path.is_file():
            return
        try:
            right_source = tk.PhotoImage(file=str(right_path))
            divisor = max(
                1,
                (max(right_source.width(), right_source.height()) + PET_DISPLAY_SIZE - 1)
                // PET_DISPLAY_SIZE,
            )
            right_image = right_source.subsample(divisor, divisor)
            left_source = (
                tk.PhotoImage(file=str(self.pet_asset_left_path))
                if self.pet_asset_left_path is not None and self.pet_asset_left_path.is_file()
                else right_source
            )
            left_image = (
                left_source.subsample(divisor, divisor)
                if left_source is not right_source
                else right_image
            )
        except (tk.TclError, OSError):
            return
        self._pet_image_sources = {
            PetFacing.RIGHT: right_source,
            PetFacing.LEFT: left_source,
        }
        self._pet_images = {
            PetFacing.RIGHT: right_image,
            PetFacing.LEFT: left_image,
        }
        self._pet_image_source = right_source
        self._pet_image = right_image
        self.pet_companion.pet_size = PET_DISPLAY_SIZE / 2.0
        self._pet_overlay = PetOverlay(
            self,
            right_image,
            self._pet_press,
            self._pet_move,
            self._pet_release,
            display_size=PET_DISPLAY_SIZE,
        )
        self._place_pet_overlay(
            self._pet_overlay,
            self.pet_companion.state,
            self.pet_companion.state.position,
        )
        self._pet_last_rendered_position = self.pet_companion.state.position
        self.bind("<Configure>", lambda _event: self._schedule_pet_target_refresh(), add="+")
        self._schedule_pet_target_refresh()
        self._pet_tick_after_id = self.after(PET_TICK_MS, self._pet_tick)

    def _reward_pet_center(self) -> RewardPoint | None:
        """Return the currently rendered Bingzi center in screen coordinates."""
        overlay: PetOverlay | None = None
        if self._dialog_pet_stack:
            runtime = self._dialog_pet_runtimes.get(self._dialog_pet_stack[-1])
            overlay = runtime.overlay if runtime is not None else None
        else:
            overlay = self._pet_overlay
        if overlay is None:
            return None
        try:
            if not overlay.winfo_exists() or not overlay.winfo_viewable():
                return None
            return RewardPoint(
                float(overlay.winfo_rootx()) + float(overlay.winfo_width()) / 2.0,
                float(overlay.winfo_rooty()) + float(overlay.winfo_height()) / 2.0,
            )
        except tk.TclError:
            return None

    def _remember_rating_pointer(self, event: tk.Event) -> None:
        event.widget._reward_pointer_down = (
            RewardPoint(float(event.x_root), float(event.y_root)),
            self._pet_now_ms(),
        )

    @staticmethod
    def _clear_rating_pointer(event: tk.Event) -> None:
        event.widget._reward_pointer_down = None

    def _rating_button_center(self, button: tk.Button) -> RewardPoint:
        button.update_idletasks()
        return RewardPoint(
            float(button.winfo_rootx()) + float(button.winfo_width()) / 2.0,
            float(button.winfo_rooty()) + float(button.winfo_height()) / 2.0,
        )

    def _rating_source_point(self, button: tk.Button) -> RewardPoint:
        pointer = getattr(button, "_reward_pointer_down", None)
        button._reward_pointer_down = None
        if pointer is not None and self._pet_now_ms() - float(pointer[1]) <= 1_000.0:
            return pointer[0]
        return self._rating_button_center(button)

    def _emit_rating_reward(self, source: RewardPoint, color: str) -> None:
        if self._reward_effects is not None:
            try:
                self._reward_effects.emit(source, color)
            except (RuntimeError, tk.TclError):
                pass

    def _apply_pet_facing(self, overlay: PetOverlay, state: PetState) -> None:
        image = self._pet_images.get(state.facing) or self._pet_image
        if image is not None:
            overlay.set_image(image)

    def _place_pet_overlay(
        self,
        overlay: PetOverlay,
        state: PetState,
        position: PetPoint,
    ) -> None:
        self._apply_pet_facing(overlay, state)
        width, height = overlay.sprite_size
        overlay.place(
            x=round(position.x - width / 2),
            y=round(position.y - height / 2),
            width=width,
            height=height,
        )
        overlay.lift()
        if self._reward_effects is not None:
            self._reward_effects.keep_above(overlay)

    def _cancel_main_pet_render(self) -> None:
        attributes = vars(self)
        if "_pet_render_generation" not in attributes:
            return
        self._pet_render_generation += 1
        for callback_id in attributes.get("_pet_render_after_ids") or ():
            try:
                self.after_cancel(callback_id)
            except tk.TclError:
                pass
        self._pet_render_after_ids = []

    def _invalidate_main_pet_render(self) -> None:
        """Drop queued frames before a layout operation changes pet targets.

        Tk can run an already scheduled interpolation callback after a card or
        page has been reflowed.  That callback carries the previous target
        geometry and can briefly place the sprite at a stale coordinate (most
        visible while a FALL is being retargeted).  Keep the reducer state and
        use it as the next interpolation anchor instead.
        """
        self._cancel_main_pet_render()
        if "pet_companion" in vars(self):
            self._pet_last_rendered_position = self.pet_companion.state.position

    def _cancel_dialog_pet_render(
        self,
        dialog: tk.Misc,
        runtime: DialogPetRuntime,
    ) -> None:
        runtime.render_generation += 1
        for callback_id in runtime.render_after_ids or []:
            try:
                dialog.after_cancel(callback_id)
            except tk.TclError:
                pass
        runtime.render_after_ids = []

    def _schedule_main_pet_render(
        self,
        state: PetState,
        previous_position: PetPoint,
    ) -> None:
        overlay = self._pet_overlay
        if overlay is None:
            return
        self._cancel_main_pet_render()
        start = self._pet_last_rendered_position or previous_position
        target = state.position
        if state.mode == PetMode.DRAGGING or start == target:
            self._place_pet_overlay(overlay, state, target)
            self._pet_last_rendered_position = target
            return
        generation = self._pet_render_generation
        steps = max(1, (PET_TICK_MS + PET_RENDER_FRAME_MS - 1) // PET_RENDER_FRAME_MS)
        for step in range(1, steps + 1):
            elapsed_ms = min(PET_TICK_MS, step * PET_RENDER_FRAME_MS)

            def render(elapsed: float = elapsed_ms) -> None:
                if generation != self._pet_render_generation or self._dialog_pet_stack:
                    return
                position = interpolate_pet_position(start, target, elapsed, PET_TICK_MS)
                self._place_pet_overlay(overlay, state, position)
                self._pet_last_rendered_position = position

            self._pet_render_after_ids.append(self.after(elapsed_ms, render))

    def _schedule_dialog_pet_render(
        self,
        dialog: tk.Toplevel,
        runtime: DialogPetRuntime,
        state: PetState,
        previous_position: PetPoint,
    ) -> None:
        self._cancel_dialog_pet_render(dialog, runtime)
        start = runtime.last_rendered_position or previous_position
        target = state.position
        if state.mode == PetMode.DRAGGING or start == target:
            self._place_pet_overlay(runtime.overlay, state, target)
            runtime.last_rendered_position = target
            return
        generation = runtime.render_generation
        steps = max(1, (PET_TICK_MS + PET_RENDER_FRAME_MS - 1) // PET_RENDER_FRAME_MS)
        for step in range(1, steps + 1):
            elapsed_ms = min(PET_TICK_MS, step * PET_RENDER_FRAME_MS)

            def render(elapsed: float = elapsed_ms) -> None:
                if (
                    generation != runtime.render_generation
                    or not self._dialog_pet_stack
                    or self._dialog_pet_stack[-1] is not dialog
                ):
                    return
                position = interpolate_pet_position(start, target, elapsed, PET_TICK_MS)
                self._place_pet_overlay(runtime.overlay, state, position)
                runtime.last_rendered_position = position

            runtime.render_after_ids = runtime.render_after_ids or []
            runtime.render_after_ids.append(dialog.after(elapsed_ms, render))

    def destroy(self) -> None:
        """Stop the transient pet window before tearing down the Tk root."""
        if self._reward_effects is not None:
            self._reward_effects.destroy()
            self._reward_effects = None
        self._cancel_main_pet_render()
        for dialog in tuple(self._dialog_pet_runtimes):
            self._detach_pet_from_dialog(dialog)
        for callback_id in (self._pet_refresh_after_id, self._pet_tick_after_id):
            if callback_id is not None:
                try:
                    self.after_cancel(callback_id)
                except tk.TclError:
                    pass
        self._pet_refresh_after_id = None
        self._pet_tick_after_id = None
        if self._pet_overlay is not None:
            try:
                self._pet_overlay.destroy()
            except tk.TclError:
                pass
            self._pet_overlay = None
        super().destroy()

    def _dictation_has_unsaved_changes(self) -> bool:
        if not hasattr(self, "dictation_status") or self._dictation_saved_fingerprint is None:
            return False
        return self._dictation_fingerprint() != self._dictation_saved_fingerprint

    def _confirm_dictation_leave(self) -> bool:
        """Return False when the user chooses to continue editing."""
        if self._smoke_testing:
            return True
        if self.current_page != "dictation" or not self._dictation_has_unsaved_changes():
            return True
        dialog = tk.Toplevel(self)
        dialog.title("保存默写选择")
        dialog.geometry("460x190")
        dialog.configure(bg=BG)
        dialog.transient(self)
        dialog.grab_set()
        tk.Label(
            dialog, text="默写纸有未保存的选择，是否保存？", bg=BG, fg=TEXT,
            font="LexiBodyBold", wraplength=400,
        ).pack(padx=20, pady=(28, 18))
        result = {"value": None}
        buttons = tk.Frame(dialog, bg=BG)
        buttons.pack()
        def finish(value):
            result["value"] = value
            dialog.destroy()
        self._primary_button(buttons, "保存", lambda: finish("save"), width=9).pack(side=tk.LEFT, padx=5)
        self._outline_button(buttons, "不保存", lambda: finish("discard"), width=9).pack(side=tk.LEFT, padx=5)
        self._outline_button(buttons, "继续编辑", lambda: finish("cancel"), width=10).pack(side=tk.LEFT, padx=5)
        self._attach_pet_to_dialog(dialog, "dictation-leave")
        self.wait_window(dialog)
        if result["value"] == "save":
            self.save_dictation_selection()
            return True
        if result["value"] == "discard":
            # Explicitly discard the current draft, including the prior saved
            # snapshot, as requested for a leave-without-saving action.
            try:
                metadata = self.service.stage_dictation_tombstone(
                    self.dictation_sync_account_id,
                )
            except (TypeError, ValueError) as exc:
                messagebox.showerror("保存失败", str(exc), parent=self)
                return False
            self._dictation_sync_metadata = metadata
            self._reset_dictation_editor()
            # Set the baseline only after the reset; clear/reset callbacks are
            # otherwise correctly treated as edits by the normal UI path.
            self._dictation_saved_fingerprint = self._dictation_fingerprint()
            self.dictation_status.configure(text="已放弃本次选择")
            self._push_dictation_tombstone_async(metadata)
            return True
        return False

    def _on_window_close(self) -> None:
        if self._confirm_dictation_leave():
            self._closing_after_prompt = True
            self.destroy()

    @staticmethod
    def _pet_viewport_for(root: tk.Misc) -> PetRect:
        return PetRect(
            0.0,
            0.0,
            float(max(1, root.winfo_width())),
            float(max(1, root.winfo_height())),
        )

    def _pet_viewport(self) -> PetRect:
        return self._pet_viewport_for(self)

    @staticmethod
    def _pet_now_ms() -> float:
        """Monotonic clock used exclusively for transient drag samples."""
        return time.monotonic_ns() / 1_000_000.0

    @staticmethod
    def _record_pet_sample(
        samples: list[tuple[float, PetPoint]],
        timestamp_ms: float,
        position: PetPoint,
        *,
        window: tk.Misc | None = None,
    ) -> None:
        """Append a constrained centre in screen coordinates.

        Domain positions are local to the active host window.  Keeping the
        drag history in screen space makes a cross-window handoff a pure
        translation, so the terminal velocity estimator never interprets the
        portal mapping as a large physical impulse.
        """
        if window is not None:
            try:
                position = PetPoint(
                    float(window.winfo_rootx()) + float(position.x),
                    float(window.winfo_rooty()) + float(position.y),
                )
            except tk.TclError:
                pass
        if samples and timestamp_ms < samples[-1][0]:
            timestamp_ms = samples[-1][0]
        samples.append((float(timestamp_ms), PetPoint(float(position.x), float(position.y))))
        cutoff = timestamp_ms - 250.0
        if len(samples) > 2:
            samples[:] = [sample for sample in samples if sample[0] >= cutoff]

    @staticmethod
    def _grab_pet_overlay(overlay: PetOverlay | None) -> None:
        """Keep drag events flowing while the pointer crosses Tk windows."""
        if overlay is None:
            return
        try:
            overlay.grab_pointer()
        except tk.TclError:
            # A window can be unmapped between the press event and this call;
            # the regular motion/release handlers still provide a safe
            # fallback when no active grab is available.
            pass

    @staticmethod
    def _release_pet_overlay(overlay: PetOverlay | None) -> None:
        if overlay is None:
            return
        try:
            overlay.release_pointer()
        except tk.TclError:
            pass

    def _window_screen_rect(self, window: tk.Misc) -> PetRect | None:
        try:
            window.update_idletasks()
            return PetRect(
                float(window.winfo_rootx()),
                float(window.winfo_rooty()),
                float(max(1, window.winfo_width())),
                float(max(1, window.winfo_height())),
            )
        except tk.TclError:
            return None

    @staticmethod
    def _window_is_mapped_viewable(window: tk.Misc) -> bool:
        try:
            return bool(
                window.winfo_exists()
                and window.winfo_ismapped()
                and window.winfo_viewable()
            )
        except tk.TclError:
            return False

    def _pet_window_registry(self) -> tuple[PetWindow, ...]:
        """Return mapped application windows in deterministic stack order."""
        windows: list[PetWindow] = []
        main_rect = self._window_screen_rect(self)
        if main_rect is not None:
            windows.append(PetWindow("main", main_rect, order=0))
        for order, dialog in enumerate(self._dialog_pet_stack, 1):
            runtime = self._dialog_pet_runtimes.get(dialog)
            rect = self._window_screen_rect(dialog)
            if runtime is None or rect is None:
                continue
            try:
                windows.append(PetWindow(
                    runtime.key,
                    rect,
                    order=order,
                    mapped=bool(dialog.winfo_ismapped()),
                    viewable=bool(dialog.winfo_viewable()),
                ))
            except tk.TclError:
                continue
        return tuple(windows)

    def _migrate_state_between_windows(
        self,
        source_window: tk.Misc,
        target_window: tk.Misc,
        source_state: PetState,
        *,
        dragging: bool = False,
        movement_direction: str | None = None,
    ) -> PetState | None:
        source_rect = self._window_screen_rect(source_window)
        target_rect = self._window_screen_rect(target_window)
        if source_rect is None or target_rect is None:
            return None
        # First establish a real geometric adjacency.  Inferring an entry
        # edge solely from rectangle ordering and velocity can teleport an
        # idle (or oppositely-moving) pet to the far edge when focus changes
        # between neighbouring windows.  Treat it as a portal only while the
        # user is dragging or the current trajectory points out through that
        # shared edge; otherwise preserve the absolute screen position below.
        # A ray-selected gapped target already has an authoritative movement
        # edge even when the two rectangles have no tangent-axis overlap.
        movement = movement_direction or portal_direction(source_rect, target_rect)
        direction = None
        if movement is not None:
            outward_velocity = {
                "right": source_state.horizontal_velocity > 1e-3,
                "left": source_state.horizontal_velocity < -1e-3,
                "bottom": source_state.vertical_velocity > 1e-3,
                "top": source_state.vertical_velocity < -1e-3,
            }[movement]
            if dragging or outward_velocity:
                direction = {
                    "right": "left",
                    "left": "right",
                    "bottom": "top",
                    "top": "bottom",
                }[movement]
        if direction is None:
            # Overlapping or non-adjacent hosts are not a portal.  Preserve
            # the absolute centre instead of inventing an edge entry, which
            # would teleport the pet to a misleading side of a modal dialog.
            world = PetPoint(
                source_rect.left + source_state.position.x,
                source_rect.top + source_state.position.y,
            )
            half = PET_DISPLAY_SIZE / 2.0
            local_x = min(
                max(world.x - target_rect.left, half),
                max(half, target_rect.width - half),
            )
            local_y = _transfer_pet_axis(
                world.y - target_rect.top,
                target_rect.height,
                half,
                preserve_out_of_bounds=source_state.mode == PetMode.FALL,
            )
            return replace(
                source_state,
                position=PetPoint(local_x, local_y),
                target_id=None,
                idle_ticks_remaining=0,
                avoid_target_id=None,
                curve_velocity=None,
            )
        entry = map_pet_entry(
            source_rect,
            target_rect,
            source_state.position,
            direction,
            PET_DISPLAY_SIZE / 2.0,
            mode=source_state.mode,
            velocity=source_state.velocity,
            facing=source_state.facing,
            dragging=dragging,
        )
        return replace(
            source_state,
            position=entry.position,
            mode=entry.mode,
            target_id=None,
            idle_ticks_remaining=0,
            vertical_velocity=entry.velocity.y,
            horizontal_velocity=entry.velocity.x,
            curve_velocity=None,
            facing=entry.facing,
        )

    def _adjacent_pet_window(
        self,
        source_window: tk.Misc,
        source_position: PetPoint,
        direction: str,
        *,
        allow_overlap: bool = False,
        motion: PetPoint | None = None,
        max_time: float | None = None,
    ) -> tuple[tk.Misc, PetPoint] | None:
        source_rect = self._window_screen_rect(source_window)
        if source_rect is None:
            return None
        source_id = "main" if source_window is self else next(
            (runtime.key for dialog, runtime in self._dialog_pet_runtimes.items() if dialog is source_window),
            "",
        )
        source = PetWindow(source_id, source_rect, order=0)
        candidates: list[PetWindow] = []
        windows_by_id: dict[str, tk.Misc] = {"main": self}
        # Dialog-owned pets can travel back into the root host.  The previous
        # registry only enumerated dialogs, making this direction impossible
        # even though the root id was present in ``windows_by_id``.
        if source_window is not self:
            main_rect = self._window_screen_rect(self)
            if main_rect is not None:
                try:
                    candidates.append(PetWindow(
                        "main",
                        main_rect,
                        order=0,
                        mapped=bool(self.winfo_ismapped()),
                        viewable=bool(self.winfo_viewable()),
                    ))
                except tk.TclError:
                    pass
        for order, dialog in enumerate(self._dialog_pet_runtimes, 1):
            rect = self._window_screen_rect(dialog)
            runtime = self._dialog_pet_runtimes.get(dialog)
            if rect is None or runtime is None:
                continue
            try:
                candidate = PetWindow(
                    runtime.key,
                    rect,
                    order=order,
                    mapped=bool(dialog.winfo_ismapped()),
                    viewable=bool(dialog.winfo_viewable()),
                )
            except tk.TclError:
                continue
            candidates.append(candidate)
            windows_by_id[candidate.id] = dialog
        hit = select_adjacent_window_hit(
            source,
            candidates,
            direction,
            portal_ray_origin(source_position, direction, PET_DISPLAY_SIZE / 2.0),
            allow_overlap=allow_overlap,
            motion=motion,
            max_time=max_time,
        )
        if hit is None:
            return None
        target_window = windows_by_id.get(hit.window.id)
        if target_window is None:
            return None
        return target_window, PetPoint(
            hit.intersection_world.x - source.rect.left,
            hit.intersection_world.y - source.rect.top,
        )

    def _pet_widget_target(
        self,
        widget: tk.Widget,
        page_key: str,
        root: tk.Misc | None = None,
    ) -> PetTarget | None:
        root = root or self
        if isinstance(widget, PetOverlay) or not widget.winfo_ismapped():
            return None
        try:
            width, height = widget.winfo_width(), widget.winfo_height()
            x = widget.winfo_rootx() - root.winfo_rootx()
            y = widget.winfo_rooty() - root.winfo_rooty()
        except tk.TclError:
            return None
        if width < 8 or height < 8:
            return None
        kind: PetTargetKind
        path: tuple[PetPoint, ...] = ()
        if isinstance(widget, MemoryChart):
            kind = PetTargetKind.CHART
            local_path = widget.pet_curve_points()
            path = tuple(PetPoint(x + point.x, y + point.y) for point in local_path)
        elif isinstance(widget, NavItem):
            kind = PetTargetKind.CONTROL
        elif widget.winfo_class() in PET_CONTROL_CLASSES:
            kind = PetTargetKind.CONTROL
        elif widget.winfo_class() in {"Frame", "TFrame", "Labelframe", "TLabelframe", "Canvas"}:
            try:
                border_width = int(float(widget.cget("borderwidth")))
            except (tk.TclError, ValueError):
                border_width = 0
            try:
                highlight_width = int(float(widget.cget("highlightthickness")))
            except (tk.TclError, ValueError):
                highlight_width = 0
            if border_width <= 0 and highlight_width <= 0:
                return None
            kind = PetTargetKind.SURFACE
        else:
            # Plain labels and borderless layout frames are not surfaces. This
            # avoids treating a full-page container as a zero-distance target.
            return None
        viewport = self._pet_viewport_for(root)
        left = max(viewport.left, float(x))
        top = max(viewport.top, float(y))
        right = min(viewport.right, float(x + width))
        bottom = min(viewport.bottom, float(y + height))
        ancestor = widget.master
        while ancestor is not None and ancestor is not root:
            try:
                if not ancestor.winfo_ismapped():
                    return None
                ancestor_left = float(ancestor.winfo_rootx() - root.winfo_rootx())
                ancestor_top = float(ancestor.winfo_rooty() - root.winfo_rooty())
                left = max(left, ancestor_left)
                top = max(top, ancestor_top)
                right = min(right, ancestor_left + ancestor.winfo_width())
                bottom = min(bottom, ancestor_top + ancestor.winfo_height())
            except tk.TclError:
                return None
            ancestor = ancestor.master
        if right <= left or bottom <= top:
            return None
        return PetTarget(
            id=self._pet_widget_id(widget, page_key),
            kind=kind,
            rect=PetRect(left, top, right - left, bottom - top),
            path=tuple(point for point in path if left <= point.x <= right and top <= point.y <= bottom),
        )

    def _pet_widget_id(self, widget: tk.Widget, page_key: str) -> str:
        """Return a semantic widget id, falling back to its structural path."""
        semantic_id = getattr(widget, "pet_target_id", None)
        if isinstance(semantic_id, str) and semantic_id.strip():
            return f"{page_key}:{semantic_id.strip()}"
        parts: list[str] = []
        current: tk.Misc | None = widget
        while current is not None and current is not self:
            parent = current.master
            if parent is None:
                break
            try:
                sibling_index = parent.winfo_children().index(current)
                widget_class = current.winfo_class().lower()
            except (tk.TclError, ValueError):
                break
            parts.append(f"{widget_class}-{sibling_index}")
            current = parent
        return f"{page_key}:{'/'.join(reversed(parts))}"

    def _walk_pet_widgets(self, widget: tk.Misc):
        for child in widget.winfo_children():
            if isinstance(child, PetOverlay):
                continue
            yield child
            yield from self._walk_pet_widgets(child)

    def _collect_dialog_pet_targets(self, dialog: tk.Toplevel, key: str) -> tuple[PetTarget, ...]:
        viewport = self._pet_viewport_for(dialog)
        targets = [
            PetTarget(f"dialog:{key}:surface", PetTargetKind.SURFACE, viewport),
        ]
        for widget in self._walk_pet_widgets(dialog):
            target = self._pet_widget_target(widget, f"dialog:{key}", dialog)
            if target is not None:
                targets.append(target)
        edge_size = 3.0
        targets.extend((
            PetTarget(f"dialog:{key}:edge:right", PetTargetKind.EDGE, PetRect(max(0, viewport.width - edge_size), 0, edge_size, viewport.height)),
            PetTarget(f"dialog:{key}:edge:bottom", PetTargetKind.EDGE, PetRect(0, max(0, viewport.height - edge_size), viewport.width, edge_size)),
            PetTarget(f"dialog:{key}:edge:left", PetTargetKind.EDGE, PetRect(0, 0, edge_size, viewport.height)),
        ))
        return tuple(targets)

    def _sync_pet_overlay_visibility(self) -> None:
        """Show exactly one companion: the newest dialog, or the main window."""
        active_dialog = self._dialog_pet_stack[-1] if self._dialog_pet_stack else None
        if self._pet_overlay is not None:
            try:
                if active_dialog is None:
                    self._cancel_main_pet_render()
                    state = self.pet_companion.state
                    self._place_pet_overlay(self._pet_overlay, state, state.position)
                    self._pet_last_rendered_position = state.position
                else:
                    self._cancel_main_pet_render()
                    self._pet_last_rendered_position = None
                    self._pet_overlay.withdraw()
            except tk.TclError:
                pass

        for dialog, runtime in tuple(self._dialog_pet_runtimes.items()):
            try:
                if dialog is active_dialog:
                    self._cancel_dialog_pet_render(dialog, runtime)
                    state = runtime.companion.state
                    self._place_pet_overlay(runtime.overlay, state, state.position)
                    runtime.last_rendered_position = state.position
                else:
                    self._cancel_dialog_pet_render(dialog, runtime)
                    runtime.last_rendered_position = None
                    runtime.overlay.withdraw()
            except tk.TclError:
                pass

    def _migrate_main_pet_to_dialog(
        self,
        dialog: tk.Toplevel,
        *,
        dragging: bool = False,
        source_state: PetState | None = None,
        movement_direction: str | None = None,
    ) -> bool:
        """Transfer the main companion state into a newly mapped dialog."""
        if self._pet_overlay is None or dialog not in self._dialog_pet_runtimes:
            return False
        runtime = self._dialog_pet_runtimes[dialog]
        active_state = source_state or self.pet_companion.state
        migrated = self._migrate_state_between_windows(
            self,
            dialog,
            active_state,
            dragging=dragging,
            movement_direction=movement_direction,
        )
        if migrated is None:
            return False
        runtime.companion.state = migrated
        if dragging:
            runtime.drag_samples = list(self._pet_drag_samples)
            runtime.drag_offset = self._pet_drag_offset
            self._release_pet_overlay(self._pet_overlay)
        self._pet_overlay.withdraw()
        self._promote_dialog_pet(dialog, synchronize=False)
        if dragging:
            self._grab_pet_overlay(runtime.overlay)
        return True

    def _migrate_dialog_pet_to_dialog(
        self,
        source: tk.Toplevel,
        target: tk.Toplevel,
        *,
        dragging: bool = False,
        source_state: PetState | None = None,
        movement_direction: str | None = None,
    ) -> bool:
        source_runtime = self._dialog_pet_runtimes.get(source)
        target_runtime = self._dialog_pet_runtimes.get(target)
        if source_runtime is None or target_runtime is None:
            return False
        active_state = source_state or source_runtime.companion.state
        migrated = self._migrate_state_between_windows(
            source,
            target,
            active_state,
            dragging=dragging,
            movement_direction=movement_direction,
        )
        if migrated is None:
            return False
        target_runtime.companion.state = migrated
        target_runtime.drag_samples = list(source_runtime.drag_samples or [])
        target_runtime.drag_offset = source_runtime.drag_offset
        try:
            if dragging:
                self._release_pet_overlay(source_runtime.overlay)
            source_runtime.overlay.withdraw()
        except tk.TclError:
            pass
        self._promote_dialog_pet(target, synchronize=False)
        if dragging:
            self._grab_pet_overlay(target_runtime.overlay)
        return True

    def _migrate_dialog_pet_to_main(
        self,
        source: tk.Toplevel,
        *,
        dragging: bool = False,
        source_state: PetState | None = None,
        movement_direction: str | None = None,
    ) -> bool:
        """Transfer a dialog-owned companion back to the root host.

        Dialogs are ordinary application windows, not one-way child stages.
        Keep the state and terminal drag samples intact when a pet exits a
        dialog toward the main window, then make the root overlay the sole
        visible owner.  The dialog remains registered so it can be promoted
        again when focus returns to it.
        """
        runtime = self._dialog_pet_runtimes.get(source)
        if runtime is None or self._pet_overlay is None:
            return False
        active_state = source_state or runtime.companion.state
        migrated = self._migrate_state_between_windows(
            source,
            self,
            active_state,
            dragging=dragging,
            movement_direction=movement_direction,
        )
        if migrated is None:
            return False
        self.pet_companion.state = migrated
        if dragging:
            self._pet_drag_samples = list(runtime.drag_samples or [])
            self._pet_drag_offset = runtime.drag_offset
            self._release_pet_overlay(runtime.overlay)
        try:
            runtime.overlay.withdraw()
        except tk.TclError:
            pass
        # The pet now physically belongs to the root host.  Clear the active
        # dialog stack so a lower still-open Toplevel cannot hide the root
        # overlay; those runtimes remain registered and will be promoted again
        # if the user focuses one of them later.
        self._dialog_pet_stack = []
        self._sync_pet_overlay_visibility()
        if dragging:
            self._grab_pet_overlay(self._pet_overlay)
        return True

    def _migrate_main_pet_if_needed(self) -> bool:
        state = self.pet_companion.state
        if state.mode not in {PetMode.FLING, PetMode.FALL}:
            return False
        viewport = self._pet_viewport()
        half = PET_DISPLAY_SIZE / 2.0
        local_viewport = PetRect(0.0, 0.0, viewport.width, viewport.height)
        for crossing_time, direction in predicted_exit_times(state, local_viewport, half):
            crossing_state = state_at_exit(
                state,
                local_viewport,
                half,
                crossing_time,
                direction,
            )
            selection = self._adjacent_pet_window(
                self,
                crossing_state.position,
                direction,
                motion=crossing_state.velocity,
                max_time=max(0.0, PET_TICK_MS / 1_000.0 - crossing_time),
            )
            if selection is None:
                continue
            target, intersection_in_source = selection
            intersection_state = replace(crossing_state, position=intersection_in_source)
            if self._migrate_main_pet_to_dialog(
                target,
                source_state=intersection_state,
                movement_direction=direction,
            ):
                return True
        return False

    def _migrate_dialog_pet_if_needed(self, dialog: tk.Toplevel) -> bool:
        runtime = self._dialog_pet_runtimes.get(dialog)
        if runtime is None or runtime.companion.state.mode not in {PetMode.FLING, PetMode.FALL}:
            return False
        state = runtime.companion.state
        viewport = self._pet_viewport_for(dialog)
        half = PET_DISPLAY_SIZE / 2.0
        local_viewport = PetRect(0.0, 0.0, viewport.width, viewport.height)
        for crossing_time, direction in predicted_exit_times(state, local_viewport, half):
            crossing_state = state_at_exit(
                state,
                local_viewport,
                half,
                crossing_time,
                direction,
            )
            selection = self._adjacent_pet_window(
                dialog,
                crossing_state.position,
                direction,
                motion=crossing_state.velocity,
                max_time=max(0.0, PET_TICK_MS / 1_000.0 - crossing_time),
            )
            if selection is None:
                continue
            target, intersection_in_source = selection
            if target is dialog:
                continue
            intersection_state = replace(crossing_state, position=intersection_in_source)
            if isinstance(target, tk.Toplevel):
                if self._migrate_dialog_pet_to_dialog(
                    dialog,
                    target,
                    dragging=False,
                    source_state=intersection_state,
                    movement_direction=direction,
                ):
                    return True
            elif target is self and self._migrate_dialog_pet_to_main(
                dialog,
                source_state=intersection_state,
                movement_direction=direction,
            ):
                return True
        return False

    def _promote_dialog_pet(self, dialog: tk.Toplevel, *, synchronize: bool = True) -> None:
        """Make a focused or newly mapped application window own the pet."""
        if dialog not in self._dialog_pet_runtimes:
            return
        # Focus can return to a dialog after the companion travelled through
        # another host (including the root).  Refresh that runtime from the
        # currently visible owner before changing the stack, otherwise the
        # dialog would resurrect an old position and briefly render a second
        # logical pet trajectory.
        source_dialog = self._dialog_pet_stack[-1] if self._dialog_pet_stack else None
        if synchronize and source_dialog is not dialog:
            source_window: tk.Misc = source_dialog or self
            source_runtime = self._dialog_pet_runtimes.get(source_dialog) if source_dialog is not None else None
            source_state = source_runtime.companion.state if source_runtime is not None else self.pet_companion.state
            migrated = self._migrate_state_between_windows(source_window, dialog, source_state)
            if migrated is not None:
                self._dialog_pet_runtimes[dialog].companion.state = migrated
        self._dialog_pet_stack = [item for item in self._dialog_pet_stack if item is not dialog]
        self._dialog_pet_stack.append(dialog)
        self._sync_pet_overlay_visibility()

    def _handoff_dialog_state(self, source: tk.Toplevel, target: tk.Misc) -> PetState | None:
        """Transfer an active dialog's transient pet state to ``target``.

        A dialog can disappear via ``withdraw``/``unmap`` without being
        destroyed.  In that case the live state must move before the overlay
        is hidden.  Adjacent hosts use the same portal mapping as a normal
        migration; non-adjacent fallbacks preserve absolute screen position
        and clear source-local target/idle bookkeeping.
        """
        runtime = self._dialog_pet_runtimes.get(source)
        if runtime is None:
            return None
        source_rect = self._window_screen_rect(source)
        target_rect = self._window_screen_rect(target)
        if source_rect is None or target_rect is None:
            return None
        state = runtime.companion.state
        movement = portal_direction(source_rect, target_rect)
        transferred: PetState | None
        if movement is not None:
            transferred = self._migrate_state_between_windows(
                source,
                target,
                state,
                dragging=state.mode == PetMode.DRAGGING,
            )
        else:
            world = PetPoint(
                source_rect.left + state.position.x,
                source_rect.top + state.position.y,
            )
            local_y = world.y - target_rect.top
            local = self._pet_viewport_for(target).clamp(
                PetPoint(world.x - target_rect.left, local_y),
                PET_DISPLAY_SIZE / 2.0,
            )
            if state.mode == PetMode.FALL:
                local = PetPoint(
                    local.x,
                    _transfer_pet_axis(
                        local_y,
                        target_rect.height,
                        PET_DISPLAY_SIZE / 2.0,
                        preserve_out_of_bounds=True,
                    ),
                )
            transferred = replace(
                state,
                position=local,
                target_id=None,
                idle_ticks_remaining=0,
                avoid_target_id=None,
            )
        if transferred is None:
            return None
        target_runtime = self._dialog_pet_runtimes.get(target) if isinstance(target, tk.Toplevel) else None
        if target_runtime is not None:
            target_runtime.companion.state = transferred
            target_runtime.drag_samples = list(runtime.drag_samples or [])
            target_runtime.drag_offset = runtime.drag_offset
        else:
            self.pet_companion.state = transferred
            self._pet_drag_samples = list(runtime.drag_samples or [])
            self._pet_drag_offset = runtime.drag_offset
        # Keep the hidden runtime coherent for a possible remap.  Its local
        # coordinates are intentionally replaced with the target state; the
        # next synchronized promotion maps it back through the portal.
        runtime.companion.state = transferred
        return transferred

    def _deactivate_dialog_pet(self, dialog: tk.Toplevel) -> None:
        if dialog not in self._dialog_pet_stack:
            return
        runtime = self._dialog_pet_runtimes.get(dialog)
        was_active = bool(self._dialog_pet_stack and self._dialog_pet_stack[-1] is dialog)
        if was_active and runtime is not None:
            # Unmap events are not guaranteed to be followed by Destroy (for
            # example a transient reminder can be withdrawn and shown again).
            # Move the live state to the next mapped host before hiding this
            # overlay so the companion never disappears from every window.
            previous_dialog = next(
                (
                    item
                    for item in reversed(self._dialog_pet_stack[:-1])
                    if item in self._dialog_pet_runtimes
                    and self._window_is_mapped_viewable(item)
                ),
                None,
            )
            target_window: tk.Misc = previous_dialog or self
            self._handoff_dialog_state(dialog, target_window)
        self._dialog_pet_stack = [item for item in self._dialog_pet_stack if item is not dialog]
        self._sync_pet_overlay_visibility()

    def _release_dialog_pet(
        self,
        event: object,
        dialog: tk.Toplevel,
        runtime: DialogPetRuntime,
        key: str,
        move: Callable[[object], None],
    ) -> None:
        def final_move() -> tk.Misc | None:
            move(event)
            return self._pet_drag_host_dialog

        active_dialog, moved_for_release = _resolve_pet_release_host(
            dialog,
            self._pet_drag_host_dialog,
            final_move,
        )
        if active_dialog is not None and active_dialog is not dialog:
            if active_dialog is self:
                if not moved_for_release:
                    event_point = PetPoint(
                        float(event.x_root - self.winfo_rootx()),
                        float(event.y_root - self.winfo_rooty()),
                    )
                    moved = self.pet_companion.drag_move(
                        PetPoint(event_point.x + self._pet_drag_offset.x, event_point.y + self._pet_drag_offset.y),
                        self._pet_viewport(),
                    )
                    self._record_pet_sample(
                        self._pet_drag_samples,
                        self._pet_now_ms(),
                        moved.position,
                        window=self,
                    )
                velocity = estimate_release_velocity(self._pet_drag_samples)
                self.pet_companion.drag_release(
                    self._collect_pet_targets(),
                    self._pet_viewport(),
                    release_velocity=velocity,
                )
                self._release_pet_overlay(self._pet_overlay)
                self._pet_drag_samples = []
            else:
                target_runtime = self._dialog_pet_runtimes.get(active_dialog)
                if target_runtime is not None:
                    if not moved_for_release:
                        target_point = PetPoint(
                            float(event.x_root - active_dialog.winfo_rootx()),
                            float(event.y_root - active_dialog.winfo_rooty()),
                        )
                        moved = target_runtime.companion.drag_move(
                            PetPoint(target_point.x + target_runtime.drag_offset.x, target_point.y + target_runtime.drag_offset.y),
                            self._pet_viewport_for(active_dialog),
                        )
                        target_runtime.drag_samples = target_runtime.drag_samples or []
                        self._record_pet_sample(
                            target_runtime.drag_samples,
                            self._pet_now_ms(),
                            moved.position,
                            window=active_dialog,
                        )
                    velocity = estimate_release_velocity(target_runtime.drag_samples)
                    target_runtime.companion.drag_release(
                        self._collect_dialog_pet_targets(active_dialog, target_runtime.key),
                        self._pet_viewport_for(active_dialog),
                        release_velocity=velocity,
                    )
                    self._release_pet_overlay(target_runtime.overlay)
                    target_runtime.drag_samples = []
            self._pet_drag_host_dialog = None
            self._pet_dragging = False
            return
        velocity = estimate_release_velocity(runtime.drag_samples or [])
        runtime.companion.drag_release(
            self._collect_dialog_pet_targets(dialog, key),
            self._pet_viewport_for(dialog),
            release_velocity=velocity,
        )
        self._release_pet_overlay(runtime.overlay)
        runtime.drag_samples = []
        self._pet_drag_host_dialog = None
        self._pet_dragging = False

    def _attach_pet_to_dialog(self, dialog: tk.Toplevel, key: str) -> None:
        """Attach a transient companion that uses only this dialog's coordinates."""
        if dialog in self._dialog_pet_runtimes or self._pet_image is None:
            return
        dialog.update_idletasks()
        half_size = PET_DISPLAY_SIZE / 2.0
        viewport = self._pet_viewport_for(dialog)
        start = viewport.clamp(PetPoint(half_size + 12.0, half_size + 12.0), half_size)
        # Preserve the currently active companion when a new application
        # window appears.  The source remains registered but hidden, allowing
        # the state to be handed back if the dialog closes.
        source_state: PetState | None = None
        if self._dialog_pet_stack:
            source_runtime = self._dialog_pet_runtimes.get(self._dialog_pet_stack[-1])
            if source_runtime is not None:
                source_state = source_runtime.companion.state
        elif self._pet_overlay is not None:
            source_state = self.pet_companion.state
        if source_state is not None:
            migrated = self._migrate_state_between_windows(
                self._dialog_pet_stack[-1] if self._dialog_pet_stack else self,
                dialog,
                source_state,
            )
            if migrated is not None:
                start_state = migrated
            else:
                start_state = PetState(start)
        else:
            start_state = PetState(start)
        companion = PetCompanion(start_state, speed=CRUISE_SPEED, pet_size=half_size)
        runtime_holder: dict[str, DialogPetRuntime] = {}

        def pointer(event) -> PetPoint:
            return PetPoint(
                float(event.x_root - dialog.winfo_rootx()),
                float(event.y_root - dialog.winfo_rooty()),
            )

        def press(event) -> None:
            runtime = runtime_holder["runtime"]
            self._cancel_dialog_pet_render(dialog, runtime)
            event_point = pointer(event)
            state = runtime.companion.state
            runtime.drag_offset = PetPoint(
                state.position.x - event_point.x,
                state.position.y - event_point.y,
            )
            runtime.companion.drag_start(state.position)
            runtime.drag_samples = []
            self._record_pet_sample(
                runtime.drag_samples,
                self._pet_now_ms(),
                runtime.companion.state.position,
                window=dialog,
            )
            self._pet_dragging = True
            self._pet_drag_host_dialog = dialog
            self._grab_pet_overlay(runtime.overlay)

        def move(event) -> None:
            runtime = runtime_holder["runtime"]
            event_point = pointer(event)
            desired = PetPoint(
                event_point.x + runtime.drag_offset.x,
                event_point.y + runtime.drag_offset.y,
            )
            drag_origin = runtime.companion.state.position
            drag_motion = PetPoint(
                desired.x - drag_origin.x,
                desired.y - drag_origin.y,
            )
            viewport_now = self._pet_viewport_for(dialog)
            direction = None
            if desired.x < viewport_now.left + PET_DISPLAY_SIZE / 2.0:
                direction = "left"
            elif desired.x > viewport_now.right - PET_DISPLAY_SIZE / 2.0:
                direction = "right"
            if direction is not None:
                selection = self._adjacent_pet_window(
                    dialog,
                    drag_origin,
                    direction,
                    allow_overlap=True,
                    motion=drag_motion,
                    max_time=1.0,
                )
                target = selection[0] if selection is not None else None
                intersection_state = (
                    replace(runtime.companion.state, position=selection[1])
                    if selection is not None
                    else runtime.companion.state
                )
                if isinstance(target, tk.Toplevel) and target is not dialog and self._migrate_dialog_pet_to_dialog(
                    dialog,
                    target,
                    dragging=True,
                    source_state=intersection_state,
                    movement_direction=direction,
                ):
                    self._pet_drag_host_dialog = target
                    target_runtime = self._dialog_pet_runtimes.get(target)
                    if target_runtime is not None:
                        target_point = PetPoint(
                            float(event.x_root - target.winfo_rootx()),
                            float(event.y_root - target.winfo_rooty()),
                        )
                        moved = target_runtime.companion.drag_move(
                            PetPoint(target_point.x + target_runtime.drag_offset.x, target_point.y + target_runtime.drag_offset.y),
                            self._pet_viewport_for(target),
                        )
                        target_runtime.drag_samples = target_runtime.drag_samples or []
                        self._record_pet_sample(
                            target_runtime.drag_samples,
                            self._pet_now_ms(),
                            moved.position,
                            window=target,
                        )
                    return
                if target is self and self._migrate_dialog_pet_to_main(
                    dialog,
                    dragging=True,
                    source_state=intersection_state,
                    movement_direction=direction,
                ):
                    self._pet_drag_host_dialog = self
                    event_point = PetPoint(
                        float(event.x_root - self.winfo_rootx()),
                        float(event.y_root - self.winfo_rooty()),
                    )
                    moved = self.pet_companion.drag_move(
                        PetPoint(event_point.x + self._pet_drag_offset.x, event_point.y + self._pet_drag_offset.y),
                        self._pet_viewport(),
                    )
                    self._record_pet_sample(
                        self._pet_drag_samples,
                        self._pet_now_ms(),
                        moved.position,
                        window=self,
                    )
                    return
            if desired.y < viewport_now.top + PET_DISPLAY_SIZE / 2.0:
                direction = "top"
            elif desired.y > viewport_now.bottom - PET_DISPLAY_SIZE / 2.0:
                direction = "bottom"
            else:
                direction = None
            if direction is not None:
                selection = self._adjacent_pet_window(
                    dialog,
                    drag_origin,
                    direction,
                    allow_overlap=True,
                    motion=drag_motion,
                    max_time=1.0,
                )
                target = selection[0] if selection is not None else None
                intersection_state = (
                    replace(runtime.companion.state, position=selection[1])
                    if selection is not None
                    else runtime.companion.state
                )
                if isinstance(target, tk.Toplevel) and target is not dialog and self._migrate_dialog_pet_to_dialog(
                    dialog,
                    target,
                    dragging=True,
                    source_state=intersection_state,
                    movement_direction=direction,
                ):
                    self._pet_drag_host_dialog = target
                    target_runtime = self._dialog_pet_runtimes.get(target)
                    if target_runtime is not None:
                        target_point = PetPoint(
                            float(event.x_root - target.winfo_rootx()),
                            float(event.y_root - target.winfo_rooty()),
                        )
                        moved = target_runtime.companion.drag_move(
                            PetPoint(target_point.x + target_runtime.drag_offset.x, target_point.y + target_runtime.drag_offset.y),
                            self._pet_viewport_for(target),
                        )
                        target_runtime.drag_samples = target_runtime.drag_samples or []
                        self._record_pet_sample(
                            target_runtime.drag_samples,
                            self._pet_now_ms(),
                            moved.position,
                            window=target,
                        )
                    return
                if target is self and self._migrate_dialog_pet_to_main(
                    dialog,
                    dragging=True,
                    source_state=intersection_state,
                    movement_direction=direction,
                ):
                    self._pet_drag_host_dialog = self
                    event_point = PetPoint(
                        float(event.x_root - self.winfo_rootx()),
                        float(event.y_root - self.winfo_rooty()),
                    )
                    moved = self.pet_companion.drag_move(
                        PetPoint(event_point.x + self._pet_drag_offset.x, event_point.y + self._pet_drag_offset.y),
                        self._pet_viewport(),
                    )
                    self._record_pet_sample(
                        self._pet_drag_samples,
                        self._pet_now_ms(),
                        moved.position,
                        window=self,
                    )
                    return
            moved = runtime.companion.drag_move(desired, viewport_now)
            if runtime.drag_samples is None:
                runtime.drag_samples = []
            self._record_pet_sample(
                runtime.drag_samples,
                self._pet_now_ms(),
                moved.position,
                window=dialog,
            )

        def release(event) -> None:
            self._release_dialog_pet(
                event,
                dialog,
                runtime_holder["runtime"],
                key,
                move,
            )

        overlay = PetOverlay(
            dialog,
            self._pet_image,
            press,
            move,
            release,
            display_size=PET_DISPLAY_SIZE,
        )
        runtime = DialogPetRuntime(key=key, companion=companion, overlay=overlay)
        runtime_holder["runtime"] = runtime
        self._dialog_pet_runtimes[dialog] = runtime
        self._dialog_pet_stack.append(dialog)
        self._sync_pet_overlay_visibility()

        def tick() -> None:
            runtime.tick_after_id = None
            try:
                if not dialog.winfo_exists():
                    self._detach_pet_from_dialog(dialog)
                    return
                if self._dialog_pet_stack and self._dialog_pet_stack[-1] is dialog:
                    viewport_now = self._pet_viewport_for(dialog)
                    targets = self._collect_dialog_pet_targets(dialog, key)
                    companion.state = preserve_pet_motion_for_targets(companion.state, targets)
                    if self._migrate_dialog_pet_if_needed(dialog):
                        runtime.tick_after_id = dialog.after(PET_TICK_MS, tick)
                        return
                    previous_position = companion.state.position
                    companion.tick(targets, viewport_now)
                    if self._migrate_dialog_pet_if_needed(dialog):
                        runtime.tick_after_id = dialog.after(PET_TICK_MS, tick)
                        return
                    state = companion.state
                    self._schedule_dialog_pet_render(
                        dialog,
                        runtime,
                        state,
                        previous_position,
                    )
                else:
                    self._cancel_dialog_pet_render(dialog, runtime)
                    runtime.last_rendered_position = None
                    overlay.withdraw()
                runtime.tick_after_id = dialog.after(PET_TICK_MS, tick)
            except tk.TclError:
                self._detach_pet_from_dialog(dialog)

        def on_destroy(event) -> None:
            if event.widget is dialog:
                self._detach_pet_from_dialog(dialog)

        def on_map(event) -> None:
            if event.widget is dialog:
                self._promote_dialog_pet(dialog)

        def on_unmap(event) -> None:
            if event.widget is dialog:
                self._deactivate_dialog_pet(dialog)

        dialog.bind("<Destroy>", on_destroy, add="+")
        dialog.bind("<FocusIn>", lambda _event: self._promote_dialog_pet(dialog), add="+")
        dialog.bind("<Map>", on_map, add="+")
        dialog.bind("<Unmap>", on_unmap, add="+")
        runtime.tick_after_id = dialog.after(PET_TICK_MS, tick)

    def _detach_pet_from_dialog(self, dialog: tk.Toplevel) -> None:
        runtime = self._dialog_pet_runtimes.get(dialog)
        if runtime is None:
            return
        self._cancel_dialog_pet_render(dialog, runtime)
        self._release_pet_overlay(runtime.overlay)
        was_active = bool(self._dialog_pet_stack and self._dialog_pet_stack[-1] is dialog)
        if was_active:
            # Return the latest state to the next visible host before removing
            # this runtime.  Only the local position changes; velocities,
            # facing and fling mode remain intact across the handoff.
            previous_dialog = next(
                (
                    item
                    for item in reversed(self._dialog_pet_stack[:-1])
                    if item in self._dialog_pet_runtimes
                    and self._window_is_mapped_viewable(item)
                ),
                None,
            )
            target_window: tk.Misc = previous_dialog or self
            self._handoff_dialog_state(dialog, target_window)
        self._dialog_pet_runtimes.pop(dialog, None)
        self._dialog_pet_stack = [item for item in self._dialog_pet_stack if item is not dialog]
        if runtime.tick_after_id is not None:
            try:
                dialog.after_cancel(runtime.tick_after_id)
            except tk.TclError:
                pass
            runtime.tick_after_id = None
        try:
            if runtime.overlay.winfo_exists():
                runtime.overlay.destroy()
        except tk.TclError:
            pass
        self._sync_pet_overlay_visibility()

    def _collect_pet_targets(self) -> tuple[PetTarget, ...]:
        if not self.current_page or self.current_page not in self.pages:
            return ()
        page = self.pages[self.current_page]
        targets: list[PetTarget] = []
        for widget in (self.nav_items.get(key) for key in self.nav_items):
            if widget is not None:
                target = self._pet_widget_target(widget, "navigation")
                if target is not None:
                    targets.append(target)
        for widget in self._walk_pet_widgets(page):
            target = self._pet_widget_target(widget, self.current_page)
            if target is not None:
                targets.append(target)
                if isinstance(widget, MemoryChart):
                    # Keep the rendered curve target and expose the chart border
                    # as a separate surface so both paths are traversable.
                    targets.append(
                        PetTarget(
                            id=f"{target.id}:border",
                            kind=PetTargetKind.SURFACE,
                            rect=target.rect,
                        )
                    )
        if self.current_page == "dictation":
            existing_ids = {target.id for target in targets}
            targets.extend(
                target for target in self._dictation_pet_targets()
                if target.id not in existing_ids
            )
        viewport = self._pet_viewport()
        edge_size = 3.0
        targets.extend((
            PetTarget("edge:right", PetTargetKind.EDGE, PetRect(max(0, viewport.width - edge_size), 0, edge_size, viewport.height)),
            PetTarget("edge:bottom", PetTargetKind.EDGE, PetRect(0, max(0, viewport.height - edge_size), viewport.width, edge_size)),
            PetTarget("edge:left", PetTargetKind.EDGE, PetRect(0, 0, edge_size, viewport.height)),
        ))
        return tuple(targets)

    def _dictation_pet_targets(self) -> tuple[PetTarget, ...]:
        """Project visible virtualized rows from canvas space into window space."""
        if not hasattr(self, "dictation_table_canvas") or not self.dictation_candidates:
            return ()
        canvas = self.dictation_table_canvas
        if not canvas.winfo_ismapped() or not self._dictation_table_column_lefts:
            return ()
        viewport = self._pet_viewport()
        canvas_left = max(viewport.left, float(canvas.winfo_rootx() - self.winfo_rootx()))
        canvas_top = max(viewport.top, float(canvas.winfo_rooty() - self.winfo_rooty()))
        canvas_right = min(viewport.right, canvas_left + canvas.winfo_width())
        canvas_bottom = min(viewport.bottom, canvas_top + canvas.winfo_height())
        if canvas_right <= canvas_left or canvas_bottom <= canvas_top:
            return ()
        content_left = float(canvas.canvasx(0))
        content_top = float(canvas.canvasy(0))
        selection_left = float(self._dictation_table_column_lefts[4])
        selection_width = float(self._dictation_table_column_widths[4])
        targets: list[PetTarget] = []
        for index, row_top in enumerate(self._dictation_table_row_tops):
            row_height = self._dictation_table_row_heights[index]
            top = max(canvas_top, canvas_top + row_top - content_top)
            bottom = min(canvas_bottom, canvas_top + row_top + row_height - content_top)
            if bottom <= top:
                continue
            word_id = self.dictation_candidates[index].word_id
            targets.append(PetTarget(
                id=f"dictation:dictation-row:{word_id}",
                kind=PetTargetKind.SURFACE,
                rect=PetRect(canvas_left, top, canvas_right - canvas_left, bottom - top),
            ))
            left = max(canvas_left, canvas_left + selection_left - content_left)
            right = min(canvas_right, canvas_left + selection_left + selection_width - content_left)
            if right > left:
                targets.append(PetTarget(
                    id=f"dictation:dictation-selection:{word_id}",
                    kind=PetTargetKind.CONTROL,
                    rect=PetRect(left, top, right - left, bottom - top),
                ))
        return tuple(targets)

    def _schedule_pet_target_refresh(self) -> None:
        if self._pet_refresh_after_id is not None:
            return
        try:
            self._pet_refresh_after_id = self.after_idle(self._refresh_pet_targets)
        except tk.TclError:
            self._pet_refresh_after_id = None

    def _refresh_pet_targets(self) -> None:
        self._pet_refresh_after_id = None
        if self._pet_overlay is not None:
            self._pet_targets = self._collect_pet_targets()

    def enable_pet_trace(self, path) -> None:
        """Write a one-line-per-second pet state trace to ``path``.

        Debug-only composition-root wiring: the trace records the main
        companion's mode, position, retained target and ticker liveness so a
        frozen-pet report can be diagnosed from the user's own session.
        """
        self._pet_trace_handle = open(path, "w", encoding="utf-8", buffering=1)

        def trace() -> None:
            try:
                state = self.pet_companion.state
                dialog = self._dialog_pet_stack[-1] if self._dialog_pet_stack else None
                self._pet_trace_handle.write(
                    f"{time.time():.3f} mode={state.mode.value} pos=({state.position.x:.1f},{state.position.y:.1f}) "
                    f"target={state.target_id} idle={state.idle_ticks_remaining} "
                    f"spd={state.movement_speed:.2f} tick={'alive' if self._pet_tick_after_id else 'DEAD'} "
                    f"fail={self._pet_tick_failures} stack={len(self._dialog_pet_stack)} "
                    f"dialog={dialog}\n"
                )
                if self._pet_trace_after_id is not None:
                    self.after_cancel(self._pet_trace_after_id)
                self._pet_trace_after_id = self.after(1_000, trace)
            except (tk.TclError, OSError, ValueError):
                self._pet_trace_after_id = None

        self._pet_trace_after_id = self.after(1_000, trace)

    def _pet_tick(self) -> None:
        self._pet_tick_after_id = None
        overlay = self._pet_overlay
        if overlay is None:
            return
        try:
            if self._dialog_pet_stack:
                self._cancel_main_pet_render()
                self._pet_last_rendered_position = None
                overlay.withdraw()
                self._pet_tick_failures = 0
                self._pet_tick_after_id = self.after(PET_TICK_MS, self._pet_tick)
                return
            # Geometry can change without resizing the root (scrolling, lazy rows,
            # pack/forget), so animation consumes a fresh visible target snapshot.
            self._pet_targets = self._collect_pet_targets()
            # Portal checks run before the next physics step.  The domain keeps
            # a fling inside a host with wall restitution, so waiting until
            # after integration would reflect the outward velocity before the
            # presentation had a chance to hand it to an adjacent window.
            self.pet_companion.state = preserve_pet_motion_for_targets(
                self.pet_companion.state,
                self._pet_targets,
            )
            if self._migrate_main_pet_if_needed():
                self._pet_tick_failures = 0
                self._pet_tick_after_id = self.after(PET_TICK_MS, self._pet_tick)
                return
            previous_position = self.pet_companion.state.position
            self.pet_companion.tick(self._pet_targets, self._pet_viewport())
            if self._migrate_main_pet_if_needed():
                self._pet_tick_failures = 0
                self._pet_tick_after_id = self.after(PET_TICK_MS, self._pet_tick)
                return
            state = self.pet_companion.state
            self._schedule_main_pet_render(state, previous_position)
            self._pet_tick_failures = 0
            self._pet_tick_after_id = self.after(PET_TICK_MS, self._pet_tick)
        except tk.TclError:
            # A rating card rebuild can unmount a control mid-tick, which
            # surfaces as a transient TclError from winfo geometry.  A single
            # failure must not permanently kill the pet loop (that is what
            # stops Bingzi after a click), so retry a bounded number of times.
            self._pet_tick_failures += 1
            if self._pet_tick_failures < 5 and self._pet_overlay is not None:
                try:
                    self._pet_tick_after_id = self.after(PET_TICK_MS, self._pet_tick)
                    return
                except tk.TclError:
                    self._pet_tick_after_id = None
            self._pet_tick_after_id = None
        except Exception:
            # A non-Tk presentation error on a single frame (a geometry or
            # reducer edge case) must not cancel the companion loop either.
            # Skip the failed frame and keep ticking, mirroring the Android
            # ticker.  The loop still exits when the overlay is destroyed or
            # when scheduling itself fails during host teardown.
            try:
                self._pet_tick_after_id = self.after(PET_TICK_MS, self._pet_tick)
            except tk.TclError:
                self._pet_tick_after_id = None

    def _pet_pointer(self, event) -> PetPoint:
        return PetPoint(
            float(event.x_root - self.winfo_rootx()),
            float(event.y_root - self.winfo_rooty()),
        )

    def _pet_press(self, event) -> None:
        self._cancel_main_pet_render()
        pointer = self._pet_pointer(event)
        state = self.pet_companion.state
        self._pet_drag_offset = PetPoint(state.position.x - pointer.x, state.position.y - pointer.y)
        self.pet_companion.drag_start(state.position)
        self._pet_drag_samples = []
        self._pet_dragging = True
        self._pet_drag_host_dialog = None
        try:
            self._record_pet_sample(
                self._pet_drag_samples,
                self._pet_now_ms(),
                self.pet_companion.state.position,
                window=self,
            )
            self._grab_pet_overlay(self._pet_overlay)
        except tk.TclError:
            # A transient teardown must not leave the pet in a grabbed drag
            # that would swallow every subsequent pointer event.
            self._release_pet_overlay(self._pet_overlay)
            self._pet_dragging = False

    def _pet_move(self, event) -> None:
        pointer = self._pet_pointer(event)
        desired = PetPoint(pointer.x + self._pet_drag_offset.x, pointer.y + self._pet_drag_offset.y)
        drag_origin = self.pet_companion.state.position
        drag_motion = PetPoint(
            desired.x - drag_origin.x,
            desired.y - drag_origin.y,
        )
        viewport = self._pet_viewport()
        direction = None
        if desired.x < viewport.left + PET_DISPLAY_SIZE / 2.0:
            direction = "left"
        elif desired.x > viewport.right - PET_DISPLAY_SIZE / 2.0:
            direction = "right"
        if direction is not None:
            selection = self._adjacent_pet_window(
                self,
                drag_origin,
                direction,
                allow_overlap=True,
                motion=drag_motion,
                max_time=1.0,
            )
            target = selection[0] if selection is not None else None
            intersection_state = (
                replace(self.pet_companion.state, position=selection[1])
                if selection is not None
                else self.pet_companion.state
            )
            if isinstance(target, tk.Toplevel) and self._migrate_main_pet_to_dialog(
                target,
                dragging=True,
                source_state=intersection_state,
                movement_direction=direction,
            ):
                self._pet_drag_host_dialog = target
                runtime = self._dialog_pet_runtimes.get(target)
                if runtime is not None:
                    event_point = PetPoint(
                        float(event.x_root - target.winfo_rootx()),
                        float(event.y_root - target.winfo_rooty()),
                    )
                    moved = runtime.companion.drag_move(
                        PetPoint(event_point.x + runtime.drag_offset.x, event_point.y + runtime.drag_offset.y),
                        self._pet_viewport_for(target),
                    )
                    runtime.drag_samples = runtime.drag_samples or []
                    self._record_pet_sample(
                        runtime.drag_samples,
                        self._pet_now_ms(),
                        moved.position,
                        window=target,
                    )
                return
        if desired.y < viewport.top + PET_DISPLAY_SIZE / 2.0:
            direction = "top"
        elif desired.y > viewport.bottom - PET_DISPLAY_SIZE / 2.0:
            direction = "bottom"
        else:
            direction = None
        if direction is not None:
            selection = self._adjacent_pet_window(
                self,
                drag_origin,
                direction,
                allow_overlap=True,
                motion=drag_motion,
                max_time=1.0,
            )
            target = selection[0] if selection is not None else None
            intersection_state = (
                replace(self.pet_companion.state, position=selection[1])
                if selection is not None
                else self.pet_companion.state
            )
            if isinstance(target, tk.Toplevel) and self._migrate_main_pet_to_dialog(
                target,
                dragging=True,
                source_state=intersection_state,
                movement_direction=direction,
            ):
                self._pet_drag_host_dialog = target
                runtime = self._dialog_pet_runtimes.get(target)
                if runtime is not None:
                    event_point = PetPoint(
                        float(event.x_root - target.winfo_rootx()),
                        float(event.y_root - target.winfo_rooty()),
                    )
                    moved = runtime.companion.drag_move(
                        PetPoint(event_point.x + runtime.drag_offset.x, event_point.y + runtime.drag_offset.y),
                        self._pet_viewport_for(target),
                    )
                    runtime.drag_samples = runtime.drag_samples or []
                    self._record_pet_sample(
                        runtime.drag_samples,
                        self._pet_now_ms(),
                        moved.position,
                        window=target,
                    )
                return
        moved = self.pet_companion.drag_move(desired, viewport)
        self._record_pet_sample(
            self._pet_drag_samples,
            self._pet_now_ms(),
            moved.position,
            window=self,
        )

    def _pet_release(self, event) -> None:
        def final_move() -> tk.Misc | None:
            self._pet_move(event)
            return self._pet_drag_host_dialog

        try:
            dialog, moved_for_release = _resolve_pet_release_host(
                self,
                self._pet_drag_host_dialog,
                final_move,
            )
            if dialog is not None:
                if dialog is self:
                    if not moved_for_release:
                        pointer = self._pet_pointer(event)
                        moved = self.pet_companion.drag_move(
                            PetPoint(pointer.x + self._pet_drag_offset.x, pointer.y + self._pet_drag_offset.y),
                            self._pet_viewport(),
                        )
                        self._record_pet_sample(
                            self._pet_drag_samples,
                            self._pet_now_ms(),
                            moved.position,
                            window=self,
                        )
                    velocity = estimate_release_velocity(self._pet_drag_samples)
                    self.pet_companion.drag_release(
                        self._collect_pet_targets(),
                        self._pet_viewport(),
                        release_velocity=velocity,
                    )
                    self._pet_drag_samples = []
                else:
                    runtime = self._dialog_pet_runtimes.get(dialog)
                    if runtime is not None:
                        if not moved_for_release:
                            event_point = PetPoint(
                                float(event.x_root - dialog.winfo_rootx()),
                                float(event.y_root - dialog.winfo_rooty()),
                            )
                            moved = runtime.companion.drag_move(
                                PetPoint(event_point.x + runtime.drag_offset.x, event_point.y + runtime.drag_offset.y),
                                self._pet_viewport_for(dialog),
                            )
                            runtime.drag_samples = runtime.drag_samples or []
                            self._record_pet_sample(
                                runtime.drag_samples,
                                self._pet_now_ms(),
                                moved.position,
                                window=dialog,
                            )
                        velocity = estimate_release_velocity(runtime.drag_samples)
                        runtime.companion.drag_release(
                            self._collect_dialog_pet_targets(dialog, runtime.key),
                            self._pet_viewport_for(dialog),
                            release_velocity=velocity,
                        )
                        runtime.drag_samples = []
            else:
                self._pet_targets = self._collect_pet_targets()
                velocity = estimate_release_velocity(self._pet_drag_samples)
                self.pet_companion.drag_release(
                    self._pet_targets,
                    self._pet_viewport(),
                    release_velocity=velocity,
                )
                self._pet_drag_samples = []
        finally:
            # Pointer capture (``grab_set``) must always be released.  A drag
            # handler error otherwise leaves every subsequent mouse event
            # routed to the sprite window, which locks the whole page even
            # though the application is still responsive.
            self._release_pet_overlay(self._pet_overlay)
            for runtime in self._dialog_pet_runtimes.values():
                self._release_pet_overlay(runtime.overlay)
            self._pet_drag_host_dialog = None
            self._pet_dragging = False

    def _configure_styles(self):
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("Treeview", background=SURFACE, fieldbackground=SURFACE, foreground=TEXT, rowheight=34, font="LexiSmall", borderwidth=0)
        style.configure("Treeview.Heading", background="#E9EEF1", foreground=TEXT, font="LexiBodyBold", padding=8, relief="flat")
        style.map("Treeview", background=[("selected", "#D8EEE7")], foreground=[("selected", TEXT)])
        style.configure("TEntry", padding=8, font="LexiBody")
        style.configure("Horizontal.TScale", background=SURFACE, troughcolor="#DDE6E4")

    def _build_shell(self):
        sidebar = tk.Frame(self, bg=SIDEBAR, width=230)
        sidebar.pack(side=tk.LEFT, fill=tk.Y)
        sidebar.pack_propagate(False)
        brand = tk.Frame(sidebar, bg=SIDEBAR)
        brand.pack(fill=tk.X, padx=22, pady=(28, 30))
        tk.Label(brand, text="词程", bg=SIDEBAR, fg="#FFFFFF", font="LexiTitle").pack(anchor="w")
        tk.Label(brand, text="LEXITRACK", bg=SIDEBAR, fg="#92A0AD", font="LexiSmall").pack(anchor="w", pady=(3, 0))
        nav_specs = [
            ("dashboard", "总览", "dashboard"),
            ("study", "学习", "study"),
            ("review", "复习", "review"),
            ("dictation", "默写纸", "edit"),
            ("library", "词库", "library"),
            ("analytics", "记忆分析", "analytics"),
            ("reminder", "学习提醒", "clock"),
            ("settings", "设置", "settings"),
        ]
        for key, label, icon in nav_specs:
            item = NavItem(sidebar, label, icon, lambda page=key: self.show_page(page))
            item.pack(fill=tk.X, padx=10, pady=3)
            self.nav_items[key] = item
        footer = tk.Frame(sidebar, bg=SIDEBAR)
        footer.pack(side=tk.BOTTOM, fill=tk.X, padx=22, pady=22)
        tk.Label(footer, text=f"内置词条  {self.catalog_count:,}", bg=SIDEBAR, fg="#92A0AD", font="LexiSmall").pack(anchor="w")
        tk.Label(footer, text="离线保存", bg=SIDEBAR, fg="#54C8AA", font="LexiSmall").pack(anchor="w", pady=(4, 0))
        self.content = tk.Frame(self, bg=BG)
        self.content.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

    def _build_pages(self):
        self._build_dashboard_page()
        self._build_study_page()
        self._build_review_page()
        self._build_dictation_page()
        self._build_library_page()
        self._build_analytics_page()
        self._build_reminder_page()
        self._build_settings_page()

    def _new_page(self, key: str, title: str, subtitle: str) -> tuple[tk.Frame, tk.Frame]:
        page = tk.Frame(self.content, bg=BG)
        self.pages[key] = page
        header = tk.Frame(page, bg=BG)
        header.pack(fill=tk.X, padx=24, pady=(12, 8))
        tk.Label(header, text=title, bg=BG, fg=TEXT, font="LexiHeading").pack(anchor="w")
        tk.Label(header, text=subtitle, bg=BG, fg=MUTED, font="LexiSmall").pack(anchor="w", pady=(4, 0))
        body = tk.Frame(page, bg=BG)
        body.pack(fill=tk.BOTH, expand=True, padx=24, pady=(0, 14))
        return page, body

    def _primary_button(self, parent, text: str, command, color: str = ACCENT, width: int = 13):
        return tk.Button(
            parent,
            text=text,
            command=command,
            bg=color,
            activebackground=color,
            fg="#FFFFFF",
            activeforeground="#FFFFFF",
            font="LexiBodyBold",
            relief="flat",
            bd=0,
            cursor="hand2",
            padx=16,
            pady=9,
            width=width,
        )

    def _outline_button(self, parent, text: str, command, width: int = 11):
        return tk.Button(
            parent,
            text=text,
            command=command,
            bg=SURFACE,
            activebackground="#EDF3F2",
            fg=TEXT,
            activeforeground=TEXT,
            font="LexiBodyBold",
            relief="solid",
            bd=1,
            cursor="hand2",
            padx=12,
            pady=8,
            width=width,
        )

    def _card(self, parent):
        return tk.Frame(parent, bg=SURFACE, highlightbackground=BORDER, highlightthickness=1)

    def _center_toplevel(
        self,
        window: tk.Toplevel,
        width: int,
        height: int,
        *,
        owner: tk.Misc | None = None,
    ) -> None:
        """Apply one complete size+position geometry while ``window`` is hidden."""
        owner_window = (owner or self).winfo_toplevel()
        try:
            owner_window.update_idletasks()
            window.update_idletasks()
            owner_bounds = (
                owner_window.winfo_rootx(),
                owner_window.winfo_rooty(),
                owner_window.winfo_width(),
                owner_window.winfo_height(),
            )
            x, y = centered_window_position(
                width,
                height,
                owner_bounds=owner_bounds,
                screen_width=window.winfo_screenwidth(),
                screen_height=window.winfo_screenheight(),
            )
            window.geometry(f"{int(width)}x{int(height)}+{x}+{y}")
            window.update_idletasks()
        except tk.TclError:
            # A dialog can be closed by its owner while it is being prepared.
            return

    @staticmethod
    def _show_prepared_toplevel(window: tk.Toplevel) -> None:
        """Map a dialog only after its final geometry has been assigned."""
        try:
            window.deiconify()
            window.lift()
        except tk.TclError:
            pass

    def _build_dashboard_page(self):
        _, body = self._new_page("dashboard", "学习总览", "今日安排与近期记忆负载")
        stats = tk.Frame(body, bg=BG)
        stats.pack(fill=tk.X)
        self.stat_labels: dict[str, tk.Label] = {}
        specs = [
            ("due_now", "待复习", ACCENT),
            ("new_words", "未学习", BLUE),
            ("reviewed_today", "今日完成", ORANGE),
            ("total_words", "可学习词条", TEXT),
        ]
        for column, (key, label, color) in enumerate(specs):
            card = self._card(stats)
            card.grid(row=0, column=column, sticky="nsew", padx=(0 if column == 0 else 6, 0 if column == 3 else 6))
            stats.grid_columnconfigure(column, weight=1, uniform="stats")
            tk.Label(card, text=label, bg=SURFACE, fg=MUTED, font="LexiSmall").pack(anchor="w", padx=18, pady=(16, 4))
            value = tk.Label(card, text="0", bg=SURFACE, fg=color, font="LexiHeading")
            value.pack(anchor="w", padx=18, pady=(0, 16))
            self.stat_labels[key] = value
        action = self._card(body)
        action.pack(fill=tk.X, pady=16)
        action_inner = tk.Frame(action, bg=SURFACE)
        action_inner.pack(fill=tk.X, padx=22, pady=18)
        text = tk.Frame(action_inner, bg=SURFACE)
        text.pack(side=tk.LEFT, fill=tk.X, expand=True)
        tk.Label(text, text="今日学习", bg=SURFACE, fg=TEXT, font="LexiHeading").pack(anchor="w")
        self.dashboard_plan = tk.Label(text, text="", bg=SURFACE, fg=MUTED, font="LexiBody")
        self.dashboard_plan.pack(anchor="w", pady=(4, 0))
        self.dashboard_action_button = self._primary_button(action_inner, "开始学习", lambda: self.show_page("study"))
        self.dashboard_action_button.pack(side=tk.RIGHT)
        chart_card = self._card(body)
        chart_card.pack(fill=tk.BOTH, expand=True)
        tk.Label(chart_card, text="未来 7 天记忆负载", bg=SURFACE, fg=TEXT, font="LexiHeading").pack(anchor="w", padx=22, pady=(18, 0))
        self.dashboard_chart = MemoryChart(chart_card)
        self.dashboard_chart.pack(fill=tk.BOTH, expand=True, padx=14, pady=(4, 12))

    def _build_study_page(self):
        _, body = self._new_page("study", "学习卡", "学习尚未接触的新词")
        self.study_card = self._card(body)
        self.study_card.pack(fill=tk.BOTH, expand=True)
        study_meta = tk.Frame(self.study_card, bg=SURFACE)
        study_meta.pack(fill=tk.X, padx=16, pady=(10, 0))
        self.study_level = tk.Label(study_meta, text="", bg="#E7F5F0", fg=ACCENT, font="LexiSmall", padx=10, pady=5)
        self.study_level.pack(side=tk.LEFT)
        self.study_filter_vars = self._build_level_filters(study_meta, "学习", self.service.study_levels, self._save_study_levels, inline=True)
        self.study_status = tk.Label(study_meta, text="", bg=SURFACE, fg=MUTED, font="LexiSmall")
        self.study_status.pack(side=tk.RIGHT)
        self.study_word = tk.Label(self.study_card, text="", bg=SURFACE, fg=TEXT, font="LexiWord")
        self.study_word.pack(pady=(6, 0))
        self.study_phonetic = tk.Label(self.study_card, text="", bg=SURFACE, fg=MUTED, font="LexiBody")
        self.study_phonetic.pack()
        self.study_controls = tk.Frame(self.study_card, bg=SURFACE, height=60)
        self.study_controls.pack(fill=tk.X, pady=(4, 2))
        self.study_controls.pack_propagate(False)
        self.reveal_button = self._primary_button(self.study_controls, "查看答案", self.reveal_answer)
        self.reveal_button.pack(pady=4)
        self.rating_frame = tk.Frame(self.study_card, bg=SURFACE, height=70)
        self.rating_frame.pack_propagate(False)
        self.rating_buttons: list[tk.Button] = []
        for column, (label, rating, color) in enumerate((
            ("忘记", ReviewRating.AGAIN, RED),
            ("模糊", ReviewRating.HARD, ORANGE),
            ("认识", ReviewRating.GOOD, ACCENT),
            ("很熟", ReviewRating.EASY, BLUE),
        )):
            self.rating_frame.grid_columnconfigure(column, weight=1, uniform="rating")
            button = self._primary_button(
                self.rating_frame,
                label,
                lambda value=rating, index=column: self.rate_current(
                    value,
                    self._rating_source_point(self.rating_buttons[index]),
                ),
                color=color,
                width=8,
            )
            button.grid(row=0, column=column, sticky="nsew", padx=6, pady=0)
            button.bind("<ButtonPress-1>", self._remember_rating_pointer, add="+")
            button.bind("<Leave>", self._clear_rating_pointer, add="+")
            self.rating_buttons.append(button)
        self.answer_panel = tk.Frame(self.study_card, bg=SURFACE)
        self.answer_panel.bind("<Configure>", self._resize_study_answer, add="+")
        self.study_meaning = tk.Label(
            self.answer_panel,
            text="",
            bg=SURFACE,
            fg=TEXT,
            font="LexiBodyBold",
            wraplength=780,
            justify="center",
            height=1,
        )
        self.study_meaning.pack()
        examples_area = tk.Frame(self.answer_panel, bg=SURFACE)
        examples_area.pack(fill=tk.BOTH, expand=True, padx=32, pady=(6, 2))
        self.study_examples_area = examples_area
        examples_area.grid_columnconfigure(0, weight=1)
        self.example_texts: list[WordClickableText] = []
        self.example_labels: list[tk.Label] = []
        self.example_rows: list[tk.Frame] = []
        for index in range(3):
            row = tk.Frame(examples_area, bg=SURFACE)
            row.grid(row=index, column=0, sticky="ew", pady=2)
            english = WordClickableText(
                row,
                on_token=lambda token, ctx, x_root, y_root: self.word_bubbles.open_from_token(
                    -1, token, ctx, x_root, y_root,
                ),
                bg=SURFACE,
                fg=TEXT,
                font="LexiExample",
                justify="center",
                wrap="word",
                padx=4,
                pady=0,
            )
            english.pack(fill=tk.BOTH, expand=True)
            label = tk.Label(
                row,
                text="",
                bg=SURFACE,
                fg=TEXT,
                font="LexiExample",
                justify="center",
                anchor="center",
                padx=4,
                pady=0,
            )
            label.pack(fill=tk.BOTH, expand=True)
            self.example_texts.append(english)
            self.example_labels.append(label)
            self.example_rows.append(row)
        self.study_mnemonic = tk.Label(self.answer_panel, text="", bg="#FFF1E2", fg="#8A531F", font="LexiSmall", wraplength=760, padx=12, pady=7)

    def _build_review_page(self):
        _, body = self._new_page("review", "复习", "按记忆权重巩固已经学习过的单词")
        toolbar = tk.Frame(body, bg=BG)
        toolbar.pack(fill=tk.X, pady=(0, 10))
        self.review_toolbar = toolbar
        self.review_summary = tk.Label(toolbar, text="", bg=BG, fg=MUTED, font="LexiBody")
        self.review_summary.pack(side=tk.LEFT)
        self.review_filter_vars = self._build_level_filters(toolbar, "复习", self.service.review_levels, self._save_review_levels, inline=True)
        self.review_start_row = tk.Frame(body, bg=BG)
        self.review_start_row.pack(fill=tk.X, pady=(0, 10))
        self.review_start_button = self._primary_button(
            self.review_start_row, "开始复习", self.start_review_session, width=22, color=ACCENT,
        )
        self.review_start_button.pack(anchor="center", pady=8)
        self.review_card = self._card(body)
        self.review_card.pack(fill=tk.BOTH, expand=True)
        review_meta = tk.Frame(self.review_card, bg=SURFACE)
        review_meta.pack(fill=tk.X, padx=16, pady=(10, 0))
        self.review_level = tk.Label(review_meta, text="已学词", bg="#E7F5F0", fg=ACCENT, font="LexiSmall", padx=10, pady=5)
        self.review_level.pack(side=tk.LEFT)
        self.review_progress = tk.Label(review_meta, text="", bg=SURFACE, fg=MUTED, font="LexiSmall")
        self.review_progress.pack(side=tk.RIGHT)
        self.review_word = tk.Label(self.review_card, text="先开始一轮复习", bg=SURFACE, fg=TEXT, font="LexiWord")
        self.review_word.pack(pady=(8, 0))
        self.review_phonetic = tk.Label(self.review_card, text="", bg=SURFACE, fg=MUTED, font="LexiBody")
        self.review_phonetic.pack()
        self.review_controls = tk.Frame(self.review_card, bg=SURFACE, height=60)
        self.review_controls.pack_propagate(False)
        self.review_reveal_button = self._primary_button(self.review_controls, "查看答案", self.reveal_review_answer)
        self.review_rating_frame = tk.Frame(self.review_card, bg=SURFACE, height=70)
        self.review_rating_frame.pack_propagate(False)
        self.review_rating_buttons: list[tk.Button] = []
        for column, (label, rating, color) in enumerate((
            ("忘记", ReviewRating.AGAIN, RED),
            ("模糊", ReviewRating.HARD, ORANGE),
            ("认识", ReviewRating.GOOD, ACCENT),
            ("很熟", ReviewRating.EASY, BLUE),
        )):
            self.review_rating_frame.grid_columnconfigure(column, weight=1, uniform="review-rating")
            button = self._primary_button(
                self.review_rating_frame,
                label,
                lambda value=rating, index=column: self.rate_review_current(
                    value,
                    self._rating_source_point(self.review_rating_buttons[index]),
                ),
                color=color,
                width=8,
            )
            button.grid(row=0, column=column, sticky="nsew", padx=6, pady=0)
            button.bind("<ButtonPress-1>", self._remember_rating_pointer, add="+")
            button.bind("<Leave>", self._clear_rating_pointer, add="+")
            self.review_rating_buttons.append(button)
        self.review_answer_panel = tk.Frame(self.review_card, bg=SURFACE)
        self.review_answer_panel.bind("<Configure>", self._resize_review_answer, add="+")
        self.review_meaning = tk.Label(self.review_answer_panel, text="", bg=SURFACE, fg=TEXT, font="LexiBodyBold", wraplength=780, justify="center", height=1)
        self.review_meaning.pack()
        examples_area = tk.Frame(self.review_answer_panel, bg=SURFACE)
        examples_area.pack(fill=tk.BOTH, expand=True, padx=32, pady=(6, 2))
        self.review_examples_area = examples_area
        examples_area.grid_columnconfigure(0, weight=1)
        self.review_example_texts: list[WordClickableText] = []
        self.review_example_labels: list[tk.Label] = []
        self.review_example_rows: list[tk.Frame] = []
        for index in range(3):
            row = tk.Frame(examples_area, bg=SURFACE)
            row.grid(row=index, column=0, sticky="ew", pady=2)
            english = WordClickableText(
                row,
                on_token=lambda token, ctx, x_root, y_root: self.word_bubbles.open_from_token(
                    -1, token, ctx, x_root, y_root,
                ),
                bg=SURFACE,
                fg=TEXT,
                font="LexiExample",
                justify="center",
                wrap="word",
                padx=4,
                pady=0,
            )
            english.pack(fill=tk.BOTH, expand=True)
            label = tk.Label(
                row,
                text="",
                bg=SURFACE,
                fg=TEXT,
                font="LexiExample",
                justify="center",
                anchor="center",
                padx=4,
                pady=0,
            )
            label.pack(fill=tk.BOTH, expand=True)
            self.review_example_texts.append(english)
            self.review_example_labels.append(label)
            self.review_example_rows.append(row)
        self.refresh_review_page()

    def _build_dictation_page(self):
        _, body = self._new_page("dictation", "默写纸", "选择词库内容，生成可打印的 A4 默写页")
        self.dictation_body = body
        controls = self._card(body)
        controls.pack(fill=tk.X, pady=(0, 12))
        inner = tk.Frame(controls, bg=SURFACE)
        inner.pack(fill=tk.X, padx=18, pady=14)

        row = tk.Frame(inner, bg=SURFACE)
        row.pack(fill=tk.X, pady=(0, 9))
        tk.Label(row, text="选择方式", bg=SURFACE, fg=MUTED, font="LexiSmall").pack(side=tk.LEFT, padx=(0, 8))
        self.dictation_mode_var = tk.StringVar(value="random")
        for value, label in (("random", "随机填写"), ("manual", "从词库选择")):
            tk.Radiobutton(
                row, text=label, value=value, variable=self.dictation_mode_var,
                command=self._refresh_dictation_candidates, bg=SURFACE, fg=TEXT,
                activebackground=SURFACE, selectcolor=SURFACE, font="LexiBody",
            ).pack(side=tk.LEFT, padx=(0, 14))
        tk.Label(row, text="默写数量", bg=SURFACE, fg=MUTED, font="LexiSmall").pack(side=tk.LEFT, padx=(12, 5))
        self.dictation_count_var = tk.StringVar(value="10")
        ttk.Spinbox(row, from_=1, to=9999, textvariable=self.dictation_count_var, width=7).pack(side=tk.LEFT)
        self.dictation_include_evaluated_var = tk.BooleanVar(value=False)
        tk.Checkbutton(
            row, text="包含已考察词", variable=self.dictation_include_evaluated_var,
            command=self._refresh_dictation_candidates, bg=SURFACE, fg=TEXT,
            activebackground=SURFACE, selectcolor=SURFACE, font="LexiSmall",
        ).pack(side=tk.LEFT, padx=(16, 0))

        format_row = tk.Frame(inner, bg=SURFACE)
        format_row.pack(fill=tk.X, pady=(0, 9))
        tk.Label(format_row, text="输出格式", bg=SURFACE, fg=MUTED, font="LexiSmall").pack(side=tk.LEFT, padx=(0, 8))
        self.dictation_format_vars = {
            DictationFormat.DOCX: tk.BooleanVar(value=True),
            DictationFormat.PDF: tk.BooleanVar(value=True),
        }
        for value, label in ((DictationFormat.DOCX, "Word"), (DictationFormat.PDF, "PDF")):
            tk.Checkbutton(
                format_row, text=label, variable=self.dictation_format_vars[value],
                bg=SURFACE, fg=TEXT, activebackground=SURFACE, selectcolor=SURFACE,
                font="LexiSmall", padx=0,
            ).pack(side=tk.LEFT, padx=(0, 12))
        tk.Label(format_row, text="字号", bg=SURFACE, fg=MUTED, font="LexiSmall").pack(side=tk.LEFT, padx=(10, 5))
        self.dictation_font_size_var = tk.StringVar(value="12")
        ttk.Spinbox(format_row, from_=8, to=24, textvariable=self.dictation_font_size_var, width=5).pack(side=tk.LEFT)

        field_row = tk.Frame(inner, bg=SURFACE)
        field_row.pack(fill=tk.X, pady=(0, 9))
        tk.Label(field_row, text="缺失项", bg=SURFACE, fg=MUTED, font="LexiSmall").pack(side=tk.LEFT, padx=(0, 8))
        self.dictation_field_vars = {
            DictationField.WORD: tk.BooleanVar(value=True),
            DictationField.PART_OF_SPEECH: tk.BooleanVar(value=False),
            DictationField.MEANING: tk.BooleanVar(value=False),
        }
        for value, label in ((DictationField.WORD, "单词"), (DictationField.PART_OF_SPEECH, "词性"), (DictationField.MEANING, "中文")):
            tk.Checkbutton(
                field_row, text=label, variable=self.dictation_field_vars[value],
                bg=SURFACE, fg=TEXT, activebackground=SURFACE, selectcolor=SURFACE,
                font="LexiSmall", padx=0,
            ).pack(side=tk.LEFT, padx=(0, 12))
        self.dictation_initial_var = tk.BooleanVar(value=False)
        tk.Checkbutton(
            field_row, text="显示首字母", variable=self.dictation_initial_var,
            bg=SURFACE, fg=TEXT, activebackground=SURFACE, selectcolor=SURFACE,
            font="LexiSmall", padx=0,
        ).pack(side=tk.LEFT, padx=(8, 0))

        example_row = tk.Frame(inner, bg=SURFACE)
        example_row.pack(fill=tk.X, pady=(0, 10))
        self.dictation_examples_var = tk.BooleanVar(value=False)
        tk.Checkbutton(
            example_row, text="添加例句", variable=self.dictation_examples_var,
            bg=SURFACE, fg=TEXT, activebackground=SURFACE, selectcolor=SURFACE,
            font="LexiSmall", padx=0,
        ).pack(side=tk.LEFT, padx=(0, 10))
        self.dictation_example_chinese_var = tk.BooleanVar(value=False)
        tk.Checkbutton(
            example_row, text="例句含中文释义", variable=self.dictation_example_chinese_var,
            bg=SURFACE, fg=TEXT, activebackground=SURFACE, selectcolor=SURFACE,
            font="LexiSmall", padx=0,
        ).pack(side=tk.LEFT, padx=(0, 10))
        tk.Label(example_row, text="自填例句（可选，应用于本次所有词条）", bg=SURFACE, fg=MUTED, font="LexiSmall").pack(side=tk.LEFT)
        self.dictation_custom_example_var = tk.StringVar()
        ttk.Entry(example_row, textvariable=self.dictation_custom_example_var, width=58).pack(side=tk.LEFT, padx=(8, 0), fill=tk.X, expand=True)

        actions = tk.Frame(inner, bg=SURFACE)
        actions.pack(fill=tk.X)
        self.dictation_preview_download_button = self._primary_button(
            actions, "预览并下载文档", self.preview_dictation, width=16,
        )
        self.dictation_preview_download_button.pack(side=tk.LEFT)
        self.dictation_save_button = self._outline_button(
            actions, "保存选择", self.save_dictation_selection, width=11,
        )
        self.dictation_save_button.pack(side=tk.LEFT, padx=(8, 0))
        self.dictation_clear_button = self._outline_button(
            actions, "清空本次选择", self.clear_dictation_selection, width=13,
        )
        self.dictation_clear_button.pack(side=tk.LEFT, padx=(8, 0))
        self.dictation_end_range_button = self._outline_button(
            actions, "结束范围选择", self.end_dictation_range, width=13,
        )
        self.dictation_end_range_button.pack(side=tk.LEFT, padx=(8, 0))
        self.dictation_status = tk.Label(actions, text="", bg=SURFACE, fg=MUTED, font="LexiSmall")
        self.dictation_status.pack(side=tk.LEFT, padx=14)

        selection = self._card(body)
        selection.pack(fill=tk.BOTH, expand=True)
        self.dictation_selection_heading = tk.Frame(selection, bg=SURFACE)
        self.dictation_selection_heading.pack(fill=tk.X, padx=16, pady=(8, 2))
        self.dictation_selection_title = tk.Label(
            self.dictation_selection_heading,
            text="选词范围",
            bg=SURFACE,
            fg=TEXT,
            font="LexiHeading",
        )
        self.dictation_selection_title.pack(side=tk.LEFT)
        self.dictation_group: str | None = None
        self.dictation_scope_group: str = "all"
        self.dictation_selection_count = tk.Label(selection, text="随机模式不需要手选", bg=SURFACE, fg=MUTED, font="LexiSmall")
        self.dictation_selection_count.pack(anchor="w", padx=16, pady=(0, 8))
        self.dictation_group_actions = tk.Frame(self.dictation_selection_heading, bg=SURFACE)
        self.dictation_back_button = self._outline_button(
            self.dictation_group_actions, "← 返回词书", self._back_to_dictation_groups, width=12,
        )
        self.dictation_back_button.pack(side=tk.LEFT)
        self.dictation_open_group_label = tk.Label(
            self.dictation_group_actions, text="", bg=SURFACE, fg=TEXT, font="LexiBodyBold",
        )
        self.dictation_open_group_label.pack(side=tk.LEFT, padx=12)
        self.dictation_manual_group_button = self._primary_button(
            self.dictation_group_actions,
            "从该词书手选",
            self._select_open_dictation_group_manually,
            width=13,
        )
        self.dictation_manual_group_button.pack(side=tk.RIGHT)
        self.dictation_groups_frame = tk.Frame(selection, bg=SURFACE)
        self.dictation_groups_header = tk.Label(self.dictation_groups_frame, text="", bg=SURFACE, fg=MUTED, font="LexiSmall")
        self.dictation_groups_header.pack(anchor="w", padx=16, pady=(0, 8))
        groups_canvas = tk.Canvas(self.dictation_groups_frame, bg=SURFACE, highlightthickness=0)
        groups_scrollbar = ttk.Scrollbar(self.dictation_groups_frame, orient=tk.VERTICAL, command=groups_canvas.yview)
        self.dictation_groups_inner = tk.Frame(groups_canvas, bg=SURFACE)
        self.dictation_groups_inner.bind(
            "<Configure>",
            lambda _e: groups_canvas.configure(scrollregion=groups_canvas.bbox("all")),
        )
        dictation_group_window = groups_canvas.create_window((0, 0), window=self.dictation_groups_inner, anchor="nw")
        groups_canvas.bind(
            "<Configure>",
            lambda e: groups_canvas.itemconfigure(dictation_group_window, width=e.width),
        )
        groups_canvas.configure(yscrollcommand=groups_scrollbar.set)
        groups_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=12, pady=(0, 12))
        groups_scrollbar.pack(side=tk.RIGHT, fill=tk.Y, pady=(0, 12))
        table = tk.Frame(selection, bg=SURFACE)
        table.pack(fill=tk.BOTH, expand=True, padx=12, pady=(0, 12))
        self.dictation_table_frame = table
        table.grid_rowconfigure(1, weight=1)
        table.grid_columnconfigure(0, weight=1)
        self.dictation_table_header = tk.Canvas(
            table, height=40, bg="#E9EEF1", bd=0, highlightthickness=0,
            xscrollincrement=24,
        )
        self.dictation_table_header.grid(row=0, column=0, sticky="ew")
        self.dictation_table_canvas = tk.Canvas(
            table, height=56, bg=SURFACE, bd=0, highlightthickness=0,
            xscrollincrement=24, yscrollincrement=34,
        )
        self.dictation_table_canvas.grid(row=1, column=0, sticky="nsew")
        vertical_scrollbar = ttk.Scrollbar(
            table, orient=tk.VERTICAL, command=self._scroll_dictation_vertically,
        )
        vertical_scrollbar.grid(row=1, column=1, sticky="ns")
        self.dictation_horizontal_scrollbar = ttk.Scrollbar(
            table, orient=tk.HORIZONTAL, command=self._scroll_dictation_horizontally,
        )
        self.dictation_horizontal_scrollbar.grid(row=2, column=0, sticky="ew")
        self.dictation_table_canvas.configure(
            yscrollcommand=vertical_scrollbar.set,
            xscrollcommand=self.dictation_horizontal_scrollbar.set,
        )
        self.dictation_table_canvas.bind("<MouseWheel>", self._on_dictation_table_mousewheel, add="+")
        self.dictation_table_canvas.bind("<Shift-MouseWheel>", self._on_dictation_table_mousewheel, add="+")
        self.dictation_table_canvas.bind("<ButtonPress-1>", self._on_dictation_table_click, add="+")
        self.dictation_table_canvas.bind("<B1-Motion>", self._on_dictation_table_drag, add="+")
        self.dictation_table_canvas.bind(
            "<Configure>", lambda _event: self._schedule_visible_dictation_checkboxes(), add="+",
        )
        table.bind(
            "<Configure>", lambda _event: self._schedule_dictation_table_resize(), add="+",
        )
        self._dictation_table_resize_id: str | None = None
        self._dictation_draw_start: int = 0
        self._dictation_draw_end: int = -1
        self.dictation_candidates: list[VocabularyEntry] = []
        self.dictation_selection_vars: dict[str, tk.BooleanVar] = {}
        self.dictation_selection_checkboxes: dict[str, tk.Checkbutton] = {}
        self.dictation_row_backgrounds: dict[str, int] = {}
        self._dictation_checkbox_refresh_id: str | None = None
        self._dictation_table_row_height = 56
        self._dictation_table_row_tops: list[int] = []
        self._dictation_table_row_heights: list[int] = []
        self._dictation_table_column_lefts: list[int] = []
        self._dictation_table_column_widths: list[int] = []
        self._dictation_drag_anchor_id: str | None = None
        self._dictation_drag_anchor_selected: bool | None = None
        self.dictation_table_canvas.bind("<ButtonRelease-1>", self._on_dictation_table_release, add="+")
        self._bind_dictation_dirty_traces()

    def _bind_dictation_dirty_traces(self) -> None:
        variables = [
            self.dictation_mode_var,
            self.dictation_count_var,
            self.dictation_include_evaluated_var,
            self.dictation_font_size_var,
            self.dictation_initial_var,
            self.dictation_examples_var,
            self.dictation_example_chinese_var,
            self.dictation_custom_example_var,
            *self.dictation_format_vars.values(),
            *self.dictation_field_vars.values(),
        ]
        for variable in variables:
            variable.trace_add("write", lambda *_args: self._mark_dictation_dirty())

    def _refresh_dictation_candidates(self):
        if not hasattr(self, "dictation_table_canvas"):
            return
        if not self._dictation_restored:
            self._restore_dictation_draft()
            self._dictation_restored = True
        self._apply_dictation_navigation(set_dictation_group_mode(
            self._dictation_navigation(),
            self.dictation_mode_var.get(),
        ))
        include = self.dictation_include_evaluated_var.get()
        # Keep selections for evaluated entries while that filter is off;
        # they remain persisted and become available again when re-enabled.
        known_pool = self.service.dictation_pool(True)
        self.dictation_selected_ids = visible_dictation_selection(self.dictation_selected_ids, known_pool)
        self._sync_dictation_group_selection()
        if self.dictation_group is not None:
            pool = self.service.dictation_words_in_group(self.dictation_group, include)
            self.dictation_candidates = pool[:2000]
            self._show_dictation_sel_view("words")
            self._render_dictation_candidates()
        else:
            self._show_dictation_sel_view("groups")
            self._render_dictation_groups()
        self._update_dictation_selection_count()

    def _dictation_current_group_key(self) -> str:
        return self.dictation_group or self.dictation_scope_group or "all"

    def _sync_dictation_group_selection(self) -> None:
        """Drop stale IDs while retaining selections from other groups."""
        known = {normalize_word_id(entry.word_id) for entry in self.service.dictation_pool(True)}
        self.dictation_selected_ids = {
            normalize_word_id(value) for value in self.dictation_selected_ids if normalize_word_id(value) in known
        }
        self.dictationRandomCandidateIds = {
            normalize_word_id(value)
            for value in self.dictationRandomCandidateIds
            if normalize_word_id(value) in known
        }
        self.dictation_selected_ids.intersection_update(known)
        for key, values in list(self.dictation_group_selected_ids.items()):
            canonical_key = str(key).strip().casefold()
            normalized_values = {
                normalize_word_id(value) for value in values if normalize_word_id(value) in known
            }
            if canonical_key != key:
                self.dictation_group_selected_ids.pop(key, None)
                self.dictation_group_selected_ids.setdefault(canonical_key, set()).update(normalized_values)
                values = self.dictation_group_selected_ids[canonical_key]
            else:
                values.clear()
                values.update(normalized_values)
            if not values:
                self.dictation_group_selected_ids.pop(canonical_key, None)
        for key in set(self.dictation_group_anchors) | set(self.dictation_group_endpoints):
            valid_ids = {
                normalize_word_id(entry.word_id)
                for entry in self.service.dictation_words_in_group(key, True)
            }
            anchor = normalize_word_id(self.dictation_group_anchors.get(key) or "") or None
            endpoint = normalize_word_id(self.dictation_group_endpoints.get(key) or "") or None
            if anchor not in valid_ids:
                self.dictation_group_anchors[key] = None
            else:
                self.dictation_group_anchors[key] = anchor
            if endpoint not in valid_ids:
                self.dictation_group_endpoints[key] = None
            else:
                self.dictation_group_endpoints[key] = endpoint
            if self.dictation_group_anchors.get(key) is None:
                self.dictation_group_endpoints[key] = None
        # Keep the explicit random pool in sync with group maps, while not
        # making a manual-only selection leak into random mode after a mode
        # switch.  The current draft contract uses selectedIds as the shared
        # portable candidate set; this assignment canonicalizes it only.
        self.dictation_selected_ids = {
            normalize_word_id(value) for value in self.dictation_selected_ids if normalize_word_id(value)
        }

    def _dictation_draft(self) -> DictationDraft:
        def selected_map() -> dict[str, tuple[str, ...]]:
            return {key: tuple(sorted(values)) for key, values in self.dictation_group_selected_ids.items() if values}
        metadata = getattr(
            self,
            "_dictation_sync_metadata",
            DictationDraftSyncMetadata(),
        )
        if not isinstance(metadata, DictationDraftSyncMetadata):
            metadata = DictationDraftSyncMetadata()
        return DictationDraft(
            mode=self.dictation_mode_var.get(),
            scope_group=self.dictation_scope_group,
            open_group=self.dictation_group,
            count=max(1, int(self.dictation_count_var.get() or 1)),
            include_evaluated=self.dictation_include_evaluated_var.get(),
            formats=tuple(value.value for value, variable in self.dictation_format_vars.items() if variable.get()),
            font_size_pt=int(self.dictation_font_size_var.get() or 12),
            missing_fields=tuple(value.value for value, variable in self.dictation_field_vars.items() if variable.get()),
            show_initial=self.dictation_initial_var.get(),
            include_examples=self.dictation_examples_var.get(),
            include_example_chinese=self.dictation_example_chinese_var.get(),
            custom_example=self.dictation_custom_example_var.get(),
            selected_ids=tuple(sorted(self.dictation_selected_ids)),
            group_selected_ids=selected_map(),
            group_anchors=dict(self.dictation_group_anchors),
            group_endpoints=dict(self.dictation_group_endpoints),
            group_scroll_positions=dict(self.dictation_group_scroll_positions),
            expanded_groups=tuple(sorted(self.dictation_expanded_groups)),
            range_enabled=self.dictation_range_enabled,
            sync_metadata=metadata,
        )

    def _dictation_fingerprint(self) -> tuple:
        try:
            return tuple(sorted(self._dictation_draft().to_dict().items(), key=lambda item: item[0]))
        except (TypeError, ValueError):
            # Spinboxes briefly expose an empty/non-numeric value while the
            # user edits them; treat that as dirty without breaking Tk traces.
            return ("invalid",)

    def _mark_dictation_dirty(self) -> None:
        if self._dictation_ignore_dirty or not hasattr(self, "dictation_status"):
            return
        if self._dictation_saved_fingerprint is None:
            self.dictation_status.configure(text="有未保存的选择")
        elif self._dictation_fingerprint() != self._dictation_saved_fingerprint:
            self.dictation_status.configure(text="有未保存的选择")

    def _restore_dictation_draft(self) -> None:
        draft = self.service.dictation_draft()
        if draft is None:
            metadata_getter = getattr(self.service, "dictation_sync_metadata", None)
            if callable(metadata_getter):
                metadata = metadata_getter()
                if isinstance(metadata, DictationDraftSyncMetadata):
                    self._dictation_sync_metadata = metadata
            self._dictation_saved_fingerprint = self._dictation_fingerprint()
            return
        self._dictation_ignore_dirty = True
        try:
            self.dictation_mode_var.set(draft.mode)
            self.dictation_scope_group = draft.scope_group
            self.dictation_group = draft.open_group
            self.dictation_count_var.set(str(draft.count))
            self.dictation_include_evaluated_var.set(draft.include_evaluated)
            self.dictation_font_size_var.set(str(draft.font_size_pt))
            self.dictation_initial_var.set(draft.show_initial)
            self.dictation_examples_var.set(draft.include_examples)
            self.dictation_example_chinese_var.set(draft.include_example_chinese)
            self.dictation_custom_example_var.set(draft.custom_example)
            for value, variable in self.dictation_format_vars.items():
                variable.set(value.value in draft.formats)
            for value, variable in self.dictation_field_vars.items():
                variable.set(value.value in draft.missing_fields)
            self.dictation_selected_ids = {
                normalize_word_id(value) for value in draft.selected_ids if normalize_word_id(value)
            }
            self.dictationRandomCandidateIds = set(self.dictation_selected_ids)
            self.dictation_group_selected_ids = {key: set(values) for key, values in (draft.group_selected_ids or {}).items()}
            self.dictation_group_anchors = dict(draft.group_anchors or {})
            self.dictation_group_endpoints = dict(draft.group_endpoints or {})
            self.dictation_group_scroll_positions = dict(draft.group_scroll_positions or {})
            self.dictation_expanded_groups = set(draft.expanded_groups)
            self.dictation_range_enabled = draft.range_enabled
            self._dictation_sync_metadata = draft.sync_metadata
            self.dictation_status.configure(text="已恢复上次选择")
        finally:
            self._dictation_ignore_dirty = False
        # Catalog changes may invalidate IDs; retain only currently known ones.
        self._sync_dictation_group_selection()
        self._dictation_saved_fingerprint = self._dictation_fingerprint()

    def save_dictation_selection(self) -> None:
        try:
            draft = self._dictation_draft()
            self.service.save_dictation_draft(draft)
        except (TypeError, ValueError) as exc:
            messagebox.showerror("保存失败", str(exc), parent=self)
            return
        self._dictation_saved_fingerprint = self._dictation_fingerprint()
        self.dictation_status.configure(text="已保存（本地）")
        self._push_dictation_draft_async(draft)

    def _push_dictation_draft_async(self, draft: DictationDraft | None = None) -> None:
        """Push a saved snapshot without blocking Tk's event loop."""
        account_id = self.dictation_sync_account_id
        adapter = getattr(self.service, "dictation_draft_sync", None)
        if not account_id or adapter is None or not getattr(adapter, "enabled", False):
            if hasattr(self, "dictation_status"):
                self.dictation_status.configure(text="已保存（仅本地，未配置同步）")
            return
        snapshot = draft or self._dictation_draft()
        self._dictation_sync_generation += 1
        generation = self._dictation_sync_generation
        fingerprint = self._dictation_fingerprint()
        self._dictation_sync_in_flight = True
        self.dictation_status.configure(text="已保存，正在同步…")

        def worker() -> None:
            try:
                # Push the immutable snapshot captured on Tk's thread.  The
                # service must not re-read a newer repository draft while this
                # request is queued or waiting on the network.
                result = self.service.push_dictation_draft(
                    account_id,
                    draft=snapshot,
                    apply_response=False,
                )
            except Exception:
                result = DictationDraftSyncResult(
                    status=DictationDraftSyncStatus.INVALID,
                    message="dictation draft sync request failed",
                )
            try:
                self.after(0, lambda: self._finish_dictation_sync_push(result, generation, fingerprint, snapshot))
            except tk.TclError:
                pass

        threading.Thread(target=worker, name="lexitrack-dictation-sync", daemon=True).start()

    def _push_dictation_tombstone_async(
        self,
        metadata: DictationDraftSyncMetadata,
    ) -> None:
        account_id = self.dictation_sync_account_id or metadata.account_id
        adapter = getattr(self.service, "dictation_draft_sync", None)
        if not account_id or adapter is None or not getattr(adapter, "enabled", False):
            return
        self._dictation_sync_generation += 1
        generation = self._dictation_sync_generation
        fingerprint = self._dictation_fingerprint()
        self._dictation_sync_in_flight = True

        def worker() -> None:
            try:
                result = self.service.push_dictation_draft(
                    account_id,
                    revision=metadata.revision,
                    updated_at_utc=metadata.updated_at_utc,
                    deleted=True,
                    apply_response=False,
                )
            except Exception:
                result = DictationDraftSyncResult(
                    status=DictationDraftSyncStatus.INVALID,
                    message="dictation draft sync request failed",
                )
            try:
                self.after(0, lambda: self._finish_dictation_tombstone_sync(
                    result, generation, fingerprint, account_id,
                ))
            except tk.TclError:
                pass

        threading.Thread(target=worker, name="lexitrack-dictation-delete-sync", daemon=True).start()

    def _finish_dictation_tombstone_sync(
        self,
        result: DictationDraftSyncResult,
        generation: int,
        fingerprint: tuple,
        account_id: str,
    ) -> None:
        if generation != self._dictation_sync_generation:
            return
        self._dictation_sync_in_flight = False
        if result.status is DictationDraftSyncStatus.CONFLICT:
            self.dictation_status.configure(text="同步冲突，请选择本机或远端版本")
            self._show_dictation_sync_conflict(result)
            return
        if result.status in {DictationDraftSyncStatus.SYNCED, DictationDraftSyncStatus.TOMBSTONE}:
            if self._dictation_fingerprint() == fingerprint:
                self.service.apply_push_dictation_result(account_id, result)
            elif result.envelope is not None:
                self.service.remember_dictation_sync_envelope(result.envelope)
            if result.envelope is not None:
                self._dictation_sync_metadata = result.envelope.metadata
            self.dictation_status.configure(text="已同步删除")

    def _finish_dictation_sync_push(
        self,
        result: DictationDraftSyncResult,
        generation: int,
        fingerprint: tuple,
        snapshot: DictationDraft,
    ) -> None:
        if generation != self._dictation_sync_generation:
            return
        self._dictation_sync_in_flight = False
        # A user may have edited while the request was in flight.  The worker
        # deliberately did not apply its response, so leave the newer editor
        # state untouched and ignore a stale acknowledgement.  Only an
        # unchanged editor may accept the returned server metadata.
        current_changed = self._dictation_fingerprint() != fingerprint
        if not current_changed:
            result = self.service.apply_push_dictation_result(
                self.dictation_sync_account_id,
                result,
            )
            if result.envelope is not None:
                self._dictation_sync_metadata = result.envelope.metadata
                # The server may return a fresh revision/timestamp while the
                # editor content is unchanged.  Treat that acknowledged
                # snapshot as the new clean baseline.
                self._dictation_saved_fingerprint = self._dictation_fingerprint()
        elif result.status is DictationDraftSyncStatus.CONFLICT:
            # The conflict still belongs to the user-visible saved snapshot;
            # keep it actionable, but never apply its remote payload here.
            self.dictation_status.configure(text="同步冲突，请选择本机或远端版本")
            self._show_dictation_sync_conflict(result)
            return
        else:
            return
        if result.status is DictationDraftSyncStatus.CONFLICT:
            self.dictation_status.configure(text="同步冲突，请选择本机或远端版本")
            self._show_dictation_sync_conflict(result)
        elif result.status in {DictationDraftSyncStatus.SYNCED, DictationDraftSyncStatus.TOMBSTONE}:
            self.dictation_status.configure(text="已同步")
        elif result.status is DictationDraftSyncStatus.TOO_LARGE:
            self.dictation_status.configure(text="已保存（草稿过大，暂未同步）")
        else:
            self.dictation_status.configure(text="已保存（仅本地，未配置同步）")

    def _pull_dictation_draft_async(self) -> None:
        account_id = self.dictation_sync_account_id
        adapter = getattr(self.service, "dictation_draft_sync", None)
        if (
            self._dictation_sync_in_flight
            or self._dictation_has_unsaved_changes()
            or not account_id
            or adapter is None
            or not getattr(adapter, "enabled", False)
        ):
            return
        generation = self._dictation_sync_generation = self._dictation_sync_generation + 1
        self._dictation_sync_in_flight = True

        def worker() -> None:
            try:
                # Pull transport/reconciliation without mutating the local
                # repository.  The Tk callback performs the dirty check first
                # and applies the snapshot only when it is still safe.
                result = self.service.pull_dictation_draft(account_id, apply=False)
            except Exception:
                result = DictationDraftSyncResult(
                    status=DictationDraftSyncStatus.INVALID,
                    message="dictation draft sync request failed",
                )
            try:
                self.after(0, lambda: self._finish_dictation_sync_pull(result, generation, account_id))
            except tk.TclError:
                pass

        threading.Thread(target=worker, name="lexitrack-dictation-pull", daemon=True).start()

    def _finish_dictation_sync_pull(
        self,
        result: DictationDraftSyncResult,
        generation: int,
        account_id: str | None = None,
    ) -> None:
        if generation != self._dictation_sync_generation:
            return
        self._dictation_sync_in_flight = False
        if result.status is DictationDraftSyncStatus.CONFLICT:
            self._show_dictation_sync_conflict(result)
            return
        if result.status not in {DictationDraftSyncStatus.SYNCED, DictationDraftSyncStatus.TOMBSTONE}:
            return
        if self._dictation_has_unsaved_changes():
            # Never replace an active editor with a background pull.  The next
            # explicit save will reconcile revisions and surface a conflict.
            return
        applied = self.service.apply_pulled_dictation_draft(
            account_id or self.dictation_sync_account_id,
            result,
        )
        if applied.status is DictationDraftSyncStatus.CONFLICT:
            self._show_dictation_sync_conflict(applied)
            return
        if applied.status is DictationDraftSyncStatus.INVALID:
            return
        if result.envelope is not None:
            self._dictation_sync_metadata = result.envelope.metadata
        if result.status is DictationDraftSyncStatus.TOMBSTONE:
            # A remote delete is a complete editor reset, while the service
            # retains the tombstone metadata for the next guarded save.
            self._dictation_restored = True
            self._reset_dictation_editor()
            self._dictation_saved_fingerprint = self._dictation_fingerprint()
        else:
            self._dictation_restored = False
            self._restore_dictation_draft()
            self._dictation_restored = True
        if self.current_page == "dictation":
            self._refresh_dictation_candidates()

    def _show_dictation_sync_conflict(self, result: DictationDraftSyncResult) -> None:
        conflict = result.conflict
        if conflict is None or not hasattr(self, "dictation_status"):
            return
        dialog = tk.Toplevel(self)
        dialog.title("默写选择同步冲突")
        dialog.geometry("520x230")
        dialog.configure(bg=BG)
        dialog.transient(self)
        dialog.grab_set()
        tk.Label(
            dialog,
            text="本机和远端均有不同的默写选择。请选择要保留的版本。",
            bg=BG,
            fg=TEXT,
            font="LexiBodyBold",
            wraplength=460,
        ).pack(padx=20, pady=(24, 10))
        tk.Label(
            dialog,
            text=f"本机修订 {conflict.local.revision} · 远端修订 {conflict.remote.revision}",
            bg=BG,
            fg=MUTED,
            font="LexiSmall",
        ).pack(pady=(0, 14))
        buttons = tk.Frame(dialog, bg=BG)
        buttons.pack()

        def choose_local() -> None:
            try:
                rebased = self.service.prepare_local_dictation_conflict_retry(
                    conflict,
                    None if conflict.local.deleted else self._dictation_draft(),
                )
            except (TypeError, ValueError, RuntimeError, OSError) as exc:
                messagebox.showerror("同步失败", str(exc), parent=dialog)
                return
            dialog.destroy()
            if rebased is None:
                self._dictation_sync_metadata = self.service.dictation_sync_metadata()
                self._reset_dictation_editor()
                self._dictation_saved_fingerprint = self._dictation_fingerprint()
                self.dictation_status.configure(text="已保留本地删除，正在同步")
                self._push_dictation_tombstone_async(self._dictation_sync_metadata)
                return
            self._dictation_sync_metadata = rebased.sync_metadata
            self._dictation_saved_fingerprint = self._dictation_fingerprint()
            self._push_dictation_draft_async(rebased)

        def choose_remote() -> None:
            remote = conflict.remote
            try:
                accepted = self.service.accept_remote_dictation_conflict(conflict)
            except (TypeError, ValueError, RuntimeError, OSError) as exc:
                messagebox.showerror("同步失败", str(exc), parent=dialog)
                return
            dialog.destroy()
            self._dictation_sync_metadata = remote.metadata
            if accepted is None:
                self._reset_dictation_editor()
                self._dictation_saved_fingerprint = self._dictation_fingerprint()
            else:
                self._dictation_restored = False
                self._restore_dictation_draft()
                self._dictation_restored = True
                self._refresh_dictation_candidates()
            self.dictation_status.configure(text="已采用远端版本")

        self._primary_button(buttons, "保留本机", choose_local, width=10).pack(side=tk.LEFT, padx=5)
        self._outline_button(buttons, "采用远端", choose_remote, width=10).pack(side=tk.LEFT, padx=5)
        self._outline_button(buttons, "稍后处理", dialog.destroy, width=10).pack(side=tk.LEFT, padx=5)
        self._attach_pet_to_dialog(dialog, "dictation-sync-conflict")

    def clear_dictation_selection(self) -> None:
        self.dictation_selected_ids.clear()
        self.dictationRandomCandidateIds.clear()
        self.dictation_group_selected_ids.clear()
        self.dictation_group_anchors.clear()
        self.dictation_group_endpoints.clear()
        self.dictation_range_enabled = True
        self._render_dictation_candidates()
        self._mark_dictation_dirty()

    def _reset_dictation_editor(self) -> None:
        """Return to a clean unsaved editor without preserving a snapshot."""
        self._dictation_ignore_dirty = True
        try:
            self.dictation_selected_ids.clear()
            self.dictationRandomCandidateIds.clear()
            self.dictation_group_selected_ids.clear()
            self.dictation_group_anchors.clear()
            self.dictation_group_endpoints.clear()
            self.dictation_group_scroll_positions.clear()
            self.dictation_expanded_groups.clear()
            self.dictation_range_enabled = True
            self.dictation_scope_group = "all"
            self.dictation_group = None
            self.dictation_mode_var.set("random")
            self.dictation_count_var.set("10")
            self.dictation_include_evaluated_var.set(False)
            self.dictation_font_size_var.set("12")
            self.dictation_initial_var.set(False)
            self.dictation_examples_var.set(False)
            self.dictation_example_chinese_var.set(False)
            self.dictation_custom_example_var.set("")
            for output_format, variable in self.dictation_format_vars.items():
                variable.set(output_format in {DictationFormat.DOCX, DictationFormat.PDF})
            for field, variable in self.dictation_field_vars.items():
                variable.set(field is DictationField.WORD)
            self.dictation_document = None
            self.dictation_document_word_ids.clear()
            self._refresh_dictation_candidates()
        finally:
            self._dictation_ignore_dirty = False

    def end_dictation_range(self) -> None:
        key = self._dictation_current_group_key()
        self.dictation_group_anchors[key] = None
        self.dictation_group_endpoints[key] = None
        self.dictation_range_enabled = False
        self._render_dictation_candidates()
        self._mark_dictation_dirty()

    def _show_dictation_sel_view(self, view: str):
        if view == "groups":
            self.dictation_table_frame.pack_forget()
            self.dictation_group_actions.pack_forget()
            self.dictation_selection_title.configure(text="选词范围")
            self.dictation_groups_frame.pack(fill=tk.BOTH, expand=True)
        else:
            self.dictation_groups_frame.pack_forget()
            self.dictation_table_frame.pack_forget()
            self.dictation_group_actions.pack_forget()
            manual = self.dictation_mode_var.get() == "manual"
            self.dictation_selection_title.configure(
                text="手选词条" if manual else "随机词书内容",
            )
            self.dictation_open_group_label.configure(
                text=self._dictation_group_label(self.dictation_group or "all"),
            )
            if manual:
                self.dictation_manual_group_button.pack_forget()
            elif not self.dictation_manual_group_button.winfo_manager():
                self.dictation_manual_group_button.pack(side=tk.RIGHT)
            self.dictation_group_actions.pack(side=tk.RIGHT)
            self.dictation_table_frame.pack(fill=tk.BOTH, expand=True, padx=12, pady=(0, 12))

    def _render_dictation_groups(self):
        for child in self.dictation_groups_inner.winfo_children():
            child.destroy()
        include = self.dictation_include_evaluated_var.get()
        manual = self.dictation_mode_var.get() == "manual"
        groups = self.service.dictation_groups(include)
        total = next((group.count for group in groups if group.key == "all"), 0)
        scope_label = next((group.label for group in groups if group.key == self.dictation_scope_group), self.dictation_scope_group)
        header = f"手选词书分组（共 {total:,} 个候选词条，点击进入分组勾选）" if manual else f"随机范围：点击词书分组设置（当前：{scope_label}）"
        self.dictation_groups_header.configure(text=header)
        for group in groups:
            is_selected_scope = (not manual) and group.key == self.dictation_scope_group
            row_color = "#E2F1EC" if is_selected_scope else SURFACE
            card = tk.Frame(
                self.dictation_groups_inner,
                bg=row_color,
                bd=0,
                highlightthickness=1,
                highlightbackground="#54C8AA" if is_selected_scope else "#DDE6E4",
                cursor="hand2",
            )
            card.pack(fill=tk.X, pady=(0, 8))
            label = tk.Label(card, text=group.label, bg=row_color, fg=TEXT, font="LexiBody", anchor="w")
            label.pack(side=tk.LEFT, padx=16, pady=14)
            selected_count = len(self.dictation_group_selected_ids.get(group.key, set()))
            if not include:
                group_ids = {entry.word_id for entry in self.service.dictation_words_in_group(group.key, True)}
                unavailable_count = len(self.dictation_group_selected_ids.get(group.key, set()) & group_ids) - len({entry.word_id for entry in self.service.dictation_words_in_group(group.key, False)} & self.dictation_group_selected_ids.get(group.key, set()))
            else:
                unavailable_count = 0
            anchor_state = self.dictation_group_anchors.get(group.key)
            badges = []
            if selected_count:
                badges.append(f"已选 {selected_count}")
            if unavailable_count:
                badges.append(f"暂不可用 {unavailable_count}")
            if anchor_state:
                badges.append("范围中")
            suffix = (" · " + " · ".join(badges)) if badges else (" · 当前" if is_selected_scope else "")
            count = tk.Label(card, text=f"{group.count:,} 词{suffix}", bg=row_color, fg=MUTED, font="LexiSmall")
            count.pack(side=tk.RIGHT, padx=16, pady=14)
            for widget in (card, label, count):
                widget.bind("<Button-1>", lambda _e, key=group.key: self._click_dictation_group(key))

    def _click_dictation_group(self, key: str):
        self._remember_dictation_scroll_position()
        self.dictation_expanded_groups.add(key)
        self._apply_dictation_navigation(open_dictation_group(
            self._dictation_navigation(),
            key,
        ))
        self._refresh_dictation_candidates()

    def _back_to_dictation_groups(self):
        self._remember_dictation_scroll_position()
        self._apply_dictation_navigation(close_dictation_group(self._dictation_navigation()))
        self._refresh_dictation_candidates()

    def _select_open_dictation_group_manually(self):
        self._apply_dictation_navigation(set_dictation_group_mode(
            self._dictation_navigation(),
            "manual",
        ))
        self._refresh_dictation_candidates()

    def _dictation_navigation(self) -> DictationGroupNavigation:
        return DictationGroupNavigation(
            mode=self.dictation_mode_var.get(),
            scope_group=self.dictation_scope_group,
            open_group=self.dictation_group,
        )

    def _apply_dictation_navigation(self, state: DictationGroupNavigation) -> None:
        self.dictation_mode_var.set(state.mode)
        self.dictation_scope_group = state.scope_group
        self.dictation_group = state.open_group

    def _dictation_group_label(self, key: str) -> str:
        for group in self.service.dictation_groups(self.dictation_include_evaluated_var.get()):
            if group.key == key:
                return group.label
        return key

    def _dictation_scope_label(self) -> str:
        return self._dictation_group_label(self.dictation_scope_group)

    def _render_dictation_candidates(self):
        if not hasattr(self, "dictation_table_canvas"):
            return
        for checkbox in self.dictation_selection_checkboxes.values():
            checkbox.destroy()
        self.dictation_selection_vars.clear()
        self.dictation_selection_checkboxes.clear()
        self.dictation_row_backgrounds.clear()
        self._dictation_drag_anchor_id = None
        self._dictation_drag_anchor_selected = None
        self.dictation_table_header.delete("all")
        self.dictation_table_canvas.delete("all")
        self._dictation_draw_start = 0
        self._dictation_draw_end = -1

        body_font = self.font_manager.fonts["LexiSmall"]
        heading_font = self.font_manager.fonts["LexiBodyBold"]

        # Pure content measurement + layout is expensive, so cache it. It only
        # depends on the candidate list, never on the window size.
        fingerprint = tuple(entry.word_id for entry in self.dictation_candidates)
        if not hasattr(self, "_dictation_content_fingerprint") or self._dictation_content_fingerprint != fingerprint:
            displays = [dictation_candidate_display(entry) for entry in self.dictation_candidates]
            self._dictation_displays = displays
            default_meaning_width = DICTATION_MEANING_COLUMN_WIDTH - 20

            def measure(values: list[str], minimum: int) -> int:
                return max([minimum, *(body_font.measure(value) + 24 for value in values)])

            word_content = measure([item.word for item in displays], 170)
            tags_content = measure([item.tags for item in displays], 200)
            row_heights = [
                max(56, body_font.metrics("linespace") * self._wrapped_line_count(item.meaning, default_meaning_width, body_font) + 14)
                for item in displays
            ]
            row_tops: list[int] = []
            cursor = 0
            for height in row_heights:
                row_tops.append(cursor)
                cursor += height
            self._dictation_table_row_height = max(row_heights, default=56)
            self._dictation_table_row_tops = row_tops
            self._dictation_table_row_heights = row_heights
            self._dictation_content_widths = (word_content, tags_content)
            self._dictation_content_fingerprint = fingerprint
            self._dictation_body_height = cursor

        word_content, tags_content = self._dictation_content_widths
        total_width = self._apply_dictation_columns(word_content, tags_content, heading_font)

        body_height = self._dictation_body_height
        self.dictation_table_header.configure(scrollregion=(0, 0, total_width, 40))
        self.dictation_table_canvas.configure(scrollregion=(0, 0, total_width, body_height))
        self._scroll_dictation_horizontally("moveto", 0)
        position = self.dictation_group_scroll_positions.get(self.dictation_group or "", 0.0)
        self.dictation_table_canvas.yview_moveto(max(0.0, min(1.0, float(position))))
        self._refresh_dictation_rows()

    def _apply_dictation_columns(self, word_content: int, tags_content: int, heading_font: tkfont.Font) -> int:
        """Rebuild column widths/header for the current viewport."""
        fixed_widths = 120 + DICTATION_SELECTION_COLUMN_WIDTH
        try:
            viewport_width = max(320, self.dictation_table_frame.winfo_width() - 18)
        except tk.TclError:
            viewport_width = max(320, self.dictation_table_canvas.winfo_width())
        word_width, meaning_width, tags_width = distribute_dictation_columns(
            word_content,
            DICTATION_MEANING_COLUMN_WIDTH,
            tags_content,
            viewport_width,
            fixed_widths=fixed_widths,
        )
        column_specs = (
            ("单词", word_width),
            ("中文释义", meaning_width),
            ("标签", tags_width),
            ("考察状态", 120),
            ("选择", DICTATION_SELECTION_COLUMN_WIDTH),
        )
        new_widths = [width for _, width in column_specs]
        layout_changed = getattr(self, "_dictation_table_column_widths", None) != new_widths
        self._dictation_table_column_widths = new_widths
        if layout_changed:
            # Column positions moved, so redraw the whole visible band.
            self.dictation_table_canvas.delete("dictation_row")
            self.dictation_row_backgrounds.clear()
            self._dictation_draw_start = 0
            self._dictation_draw_end = -1
        column_lefts: list[int] = []
        total_width = 0
        self.dictation_table_header.delete("all")
        for title, width in column_specs:
            column_lefts.append(total_width)
            self.dictation_table_header.create_rectangle(
                total_width, 0, total_width + width, 40,
                fill="#E9EEF1", outline=BORDER,
            )
            self.dictation_table_header.create_text(
                total_width + 10, 20, text=title, anchor="w", fill=TEXT, font=heading_font,
            )
            total_width += width
        self._dictation_table_column_lefts = column_lefts
        return total_width

    @staticmethod
    def _wrapped_line_count(value: str, meaning_width: int, body_font: tkfont.Font) -> int:
        count = 0
        for paragraph in value.splitlines() or [""]:
            current = ""
            paragraph_lines = 1
            for character in paragraph:
                candidate = current + character
                if current and body_font.measure(candidate) > meaning_width:
                    paragraph_lines += 1
                    current = character
                else:
                    current = candidate
            count += paragraph_lines
        return max(1, count)

    def _refresh_dictation_rows(self):
        """Render only the visible rows plus a small preload buffer.

        Rows outside the viewport (± ``DICTATION_RENDER_BUFFER``) are dropped
        so opening or stretching the table never draws the whole catalog.
        """
        if not hasattr(self, "dictation_table_canvas") or not self.dictation_candidates:
            return
        canvas = self.dictation_table_canvas
        viewport_top = max(0.0, canvas.canvasy(0))
        viewport_height = max(1, canvas.winfo_height())
        viewport_bottom = viewport_top + viewport_height
        row_tops = self._dictation_table_row_tops
        row_heights = self._dictation_table_row_heights
        render_start, render_end = dictation_render_range(
            row_tops,
            row_heights,
            viewport_top,
            viewport_bottom,
            DICTATION_RENDER_BUFFER,
        )

        # Drop rows that fell outside the band.
        for index in range(self._dictation_draw_start, self._dictation_draw_end + 1):
            if index < render_start or index > render_end:
                canvas.delete(f"dictation_row_{index}")

        body_font = self.font_manager.fonts["LexiSmall"]
        meaning_width = self._dictation_table_column_widths[1] - 20
        column_lefts = self._dictation_table_column_lefts
        column_widths = self._dictation_table_column_widths
        total_width = sum(column_widths)
        displays = self._dictation_displays
        manual = self.dictation_mode_var.get() == "manual"
        for index in range(render_start, render_end + 1):
            if canvas.find_withtag(f"dictation_row_{index}"):
                continue
            entry = self.dictation_candidates[index]
            display = displays[index]
            top = row_tops[index]
            row_height = row_heights[index]
            background = "#F8FAFB" if index % 2 else SURFACE
            if entry.word_id in self.dictation_selected_ids:
                background = "#E2F1EC"
            rectangle = canvas.create_rectangle(
                0, top, total_width, top + row_height,
                fill=background, outline=BORDER,
                tags=(f"dictation_row_{index}", "dictation_row"),
            )
            self.dictation_row_backgrounds[entry.word_id] = rectangle
            values = (display.word, display.meaning, display.tags, display.evaluation_status)
            colors = (TEXT, TEXT, TEXT, display.evaluation_color)
            for column, (value, color) in enumerate(zip(values, colors)):
                text_options = {"fill": color, "font": body_font}
                if column == 1:
                    text_options.update(width=meaning_width, justify="left")
                canvas.create_text(
                    column_lefts[column] + 10,
                    top + row_height / 2,
                    text=value,
                    anchor="w",
                    tags=(f"dictation_row_{index}", "dictation_row"),
                    **text_options,
                )
        self._dictation_draw_start = render_start
        self._dictation_draw_end = render_end
        # A visible cyan guide marks the current range endpoint.  It is drawn
        # only when an anchor exists, and remains actionable after scrolling
        # because the virtualized row is rebuilt from the stable word ID.
        canvas.delete("dictation_range_marker")
        anchor_id = self.dictation_group_anchors.get(self._dictation_current_group_key())
        if anchor_id and self.dictation_range_enabled:
            for index in range(render_start, render_end + 1):
                entry = self.dictation_candidates[index]
                marker_tag = f"dictation-range-{entry.word_id}"
                top = row_tops[index]
                row_height = row_heights[index]
                marker = canvas.create_line(
                    0, top + row_height - 2, total_width, top + row_height - 2,
                    fill="#18B7C9", width=2, arrow=tk.LAST,
                    tags=(marker_tag, "dictation_range_marker"),
                )
                canvas.create_text(
                    max(8, total_width - 112), top + 10,
                    text=self.dictation_range_marker_text, anchor="e",
                    fill="#18B7C9", font="LexiSmall",
                    tags=(marker_tag, "dictation_range_marker"),
                )
                canvas.tag_bind(marker_tag, "<Button-1>", lambda _event, word_id=entry.word_id: self._select_dictation_range_to_here(word_id))
        # Column separator lines only within the drawn band.
        canvas.delete("dictation_separator")
        for left in column_lefts[1:]:
            canvas.create_line(left, 0, left, self._dictation_body_height, fill=BORDER, tags=("dictation_separator",))
        self._refresh_visible_dictation_checkboxes()
        self._schedule_pet_target_refresh()

    def _scroll_dictation_horizontally(self, *args):
        self.dictation_table_header.xview(*args)
        self.dictation_table_canvas.xview(*args)

    def _scroll_dictation_vertically(self, *args):
        self.dictation_table_canvas.yview(*args)
        self._remember_dictation_scroll_position()
        self._schedule_dictation_rows()

    def _remember_dictation_scroll_position(self) -> None:
        if not hasattr(self, "dictation_table_canvas") or self.dictation_group is None:
            return
        try:
            self.dictation_group_scroll_positions[self.dictation_group] = float(self.dictation_table_canvas.yview()[0])
        except (tk.TclError, ValueError):
            pass

    def _schedule_visible_dictation_checkboxes(self):
        if self._dictation_checkbox_refresh_id is not None:
            self.after_cancel(self._dictation_checkbox_refresh_id)
        self._dictation_checkbox_refresh_id = self.after_idle(self._refresh_visible_dictation_checkboxes)

    def _schedule_dictation_rows(self):
        if self._dictation_checkbox_refresh_id is not None:
            self.after_cancel(self._dictation_checkbox_refresh_id)
            self._dictation_checkbox_refresh_id = None
        if self._dictation_table_resize_id is not None:
            self.after_cancel(self._dictation_table_resize_id)
            self._dictation_table_resize_id = None
        self._dictation_table_resize_id = self.after_idle(self._refresh_dictation_rows)

    def _schedule_dictation_table_resize(self):
        if self._dictation_table_resize_id is not None:
            self.after_cancel(self._dictation_table_resize_id)
        self._dictation_table_resize_id = self.after_idle(self._apply_dictation_table_resize)

    def _apply_dictation_table_resize(self):
        self._dictation_table_resize_id = None
        if not hasattr(self, "dictation_table_canvas") or not self.dictation_candidates:
            return
        if not hasattr(self, "_dictation_content_widths"):
            self._render_dictation_candidates()
            return
        word_content, tags_content = self._dictation_content_widths
        heading_font = self.font_manager.fonts["LexiBodyBold"]
        total_width = self._apply_dictation_columns(word_content, tags_content, heading_font)
        self.dictation_table_header.configure(scrollregion=(0, 0, total_width, 40))
        self.dictation_table_canvas.configure(
            scrollregion=(0, 0, total_width, self._dictation_body_height),
        )
        self._refresh_dictation_rows()

    def _refresh_visible_dictation_checkboxes(self):
        self._dictation_checkbox_refresh_id = None
        for checkbox in self.dictation_selection_checkboxes.values():
            checkbox.destroy()
        self.dictation_table_canvas.delete("dictation_checkbox")
        self.dictation_selection_vars.clear()
        self.dictation_selection_checkboxes.clear()
        if not self.dictation_candidates or not self._dictation_table_column_lefts:
            return

        viewport_top = max(0.0, self.dictation_table_canvas.canvasy(0))
        viewport_height = max(1, self.dictation_table_canvas.winfo_height())
        viewport_bottom = viewport_top + viewport_height
        manual = self.dictation_mode_var.get() == "manual"
        interactive = self.dictation_group is not None
        selection_center = (
            self._dictation_table_column_lefts[4]
            + self._dictation_table_column_widths[4] / 2
        )
        for index, row_top in enumerate(self._dictation_table_row_tops):
            row_height = self._dictation_table_row_heights[index]
            if row_top + row_height < viewport_top - row_height or row_top > viewport_bottom + row_height:
                continue
            entry = self.dictation_candidates[index]
            selected = interactive and entry.word_id in self.dictation_selected_ids
            background = "#E2F1EC" if selected else ("#F8FAFB" if index % 2 else SURFACE)
            variable = tk.BooleanVar(value=selected)
            checkbox = tk.Checkbutton(
                self.dictation_table_canvas,
                variable=variable,
                command=lambda word_id=entry.word_id, value=variable: self._set_dictation_selected(word_id, value.get()),
                bg=background,
                activebackground=background,
                selectcolor=SURFACE,
                state=tk.NORMAL if interactive else tk.DISABLED,
                font=DICTATION_CHECKBOX_FONT,
                padx=0,
                pady=DICTATION_CHECKBOX_PAD_Y,
                bd=0,
                highlightthickness=0,
                indicatoron=True,
            )
            # This widget is virtualized and recreated as the table scrolls;
            # entry.word_id keeps its pet target identity stable across redraws.
            checkbox.pet_target_id = f"dictation-selection:{entry.word_id}"
            checkbox.bind("<MouseWheel>", self._on_dictation_table_mousewheel, add="+")
            checkbox.bind("<Shift-MouseWheel>", self._on_dictation_table_mousewheel, add="+")
            self.dictation_table_canvas.create_window(
                selection_center,
                row_top + row_height / 2,
                window=checkbox,
                anchor="center",
                tags=("dictation_checkbox",),
            )
            self.dictation_selection_vars[entry.word_id] = variable
            self.dictation_selection_checkboxes[entry.word_id] = checkbox

    def _on_dictation_table_mousewheel(self, event):
        if not event.delta:
            return "break"
        units = max(1, abs(event.delta) // 120)
        direction = -1 if event.delta > 0 else 1
        if event.state & 0x0001:
            self.dictation_table_header.xview_scroll(direction * units, "units")
            self.dictation_table_canvas.xview_scroll(direction * units, "units")
        else:
            self.dictation_table_canvas.yview_scroll(direction * units, "units")
            self._schedule_dictation_rows()
        return "break"

    def _dictation_row_index_at(self, canvas_y: float) -> int | None:
        for index, row_top in enumerate(self._dictation_table_row_tops):
            if row_top <= canvas_y <= row_top + self._dictation_table_row_heights[index]:
                return index
        return None

    def _dictation_entry_at(self, canvas_y: float) -> VocabularyEntry | None:
        index = self._dictation_row_index_at(canvas_y)
        if index is None or index >= len(self.dictation_candidates):
            return None
        return self.dictation_candidates[index]

    def _on_dictation_table_click(self, event):
        if self.dictation_group is None:
            return "break"
        # Marker clicks are range actions, not checkbox toggles.
        for item_id in self.dictation_table_canvas.find_withtag("current"):
            tags = self.dictation_table_canvas.gettags(item_id)
            marker = next((tag for tag in tags if tag.startswith("dictation-range-")), None)
            if marker:
                self._select_dictation_range_to_here(marker.removeprefix("dictation-range-"))
                return "break"
        canvas_y = self.dictation_table_canvas.canvasy(event.y)
        entry = self._dictation_entry_at(canvas_y)
        if entry is None:
            return "break"
        selected = entry.word_id not in self.dictation_selected_ids
        self._set_dictation_selected(entry.word_id, selected)
        # Remember the anchor so a subsequent drag extends the same action.
        self._dictation_drag_anchor_id = entry.word_id
        self._dictation_drag_anchor_selected = selected
        return "break"

    def _on_dictation_table_drag(self, event):
        if self.dictation_group is None:
            return "break"
        canvas_y = self.dictation_table_canvas.canvasy(event.y)
        entry = self._dictation_entry_at(canvas_y)
        if entry is None:
            return "break"
        if self._dictation_drag_anchor_id is None:
            self._dictation_drag_anchor_id = entry.word_id
            self._dictation_drag_anchor_selected = entry.word_id not in self.dictation_selected_ids
        anchor_selected = self._dictation_drag_anchor_selected
        start = next(
            (i for i, item in enumerate(self.dictation_candidates) if item.word_id == self._dictation_drag_anchor_id),
            0,
        )
        end = next((i for i, item in enumerate(self.dictation_candidates) if item.word_id == entry.word_id), start)
        low, high = sorted((start, end))
        for index in range(low, high + 1):
            target = self.dictation_candidates[index]
            self._set_dictation_selected(target.word_id, anchor_selected, update_anchor=False)
        if anchor_selected and entry.word_id:
            self._set_dictation_anchor(entry.word_id)
        return "break"

    def _set_dictation_anchor(self, word_id: str) -> None:
        key = self._dictation_current_group_key()
        # A fresh ordinary selection starts a new range; the previous endpoint
        # is retained only for cancellation fallback until this point.
        self.dictation_group_endpoints[key] = None
        self.dictation_group_anchors[key] = word_id
        self.dictation_range_enabled = True

    def _set_dictation_selected(self, word_id: str, selected: bool, *, update_anchor: bool = True):
        word_id = normalize_word_id(word_id)
        if not word_id:
            return
        key = self._dictation_current_group_key()
        if selected:
            self.dictation_selected_ids.add(word_id)
            self.dictationRandomCandidateIds.add(word_id)
            self.dictation_group_selected_ids.setdefault(key, set()).add(word_id)
            if update_anchor:
                self._set_dictation_anchor(word_id)
        else:
            self.dictation_group_selected_ids.setdefault(key, set()).discard(word_id)
            if not any(word_id in values for values in self.dictation_group_selected_ids.values()):
                self.dictation_selected_ids.discard(word_id)
                self.dictationRandomCandidateIds.discard(word_id)
            if update_anchor:
                reference = self.dictation_group_endpoints.get(key) or word_id
                remaining_ids = self.dictation_group_selected_ids.get(key, set())
                self.dictation_group_anchors[key] = nearest_dictation_id(
                    self.dictation_candidates, reference, remaining_ids,
                )
                if not remaining_ids:
                    self.dictation_group_anchors[key] = None
                    self.dictation_group_endpoints[key] = None
        background = "#E2F1EC" if selected else (
            "#F8FAFB" if next(
                (index for index, entry in enumerate(self.dictation_candidates) if entry.word_id == word_id),
                0,
            ) % 2 else SURFACE
        )
        rectangle = self.dictation_row_backgrounds.get(word_id)
        if rectangle is not None:
            self.dictation_table_canvas.itemconfigure(rectangle, fill=background)
        checkbox = self.dictation_selection_checkboxes.get(word_id)
        if checkbox is not None:
            checkbox.configure(bg=background, activebackground=background)
            variable = self.dictation_selection_vars.get(word_id)
            if variable is not None:
                variable.set(selected)
        self._update_dictation_selection_count()
        self._mark_dictation_dirty()

    def _select_dictation_range_to_here(self, word_id: str) -> None:
        word_id = normalize_word_id(word_id)
        if not word_id:
            return
        key = self._dictation_current_group_key()
        anchor = self.dictation_group_anchors.get(key)
        if not anchor or not self.dictation_range_enabled:
            return
        # ``dictation_candidates`` is a virtualized, display-capped slice
        # (currently 2,000 rows).  Range semantics are defined over the full
        # filtered group sequence so an endpoint remains valid after
        # scrolling, virtualization, or a large catalog.
        full_group = self.service.dictation_words_in_group(
            key,
            self.dictation_include_evaluated_var.get(),
        )
        ids = dictation_range_ids(full_group, anchor, word_id)
        if not ids:
            return
        for candidate_id in ids:
            self.dictation_selected_ids.add(candidate_id)
            self.dictation_group_selected_ids.setdefault(key, set()).add(candidate_id)
        self.dictation_group_endpoints[key] = word_id
        self.dictation_group_anchors[key] = word_id
        self._render_dictation_candidates()
        self._mark_dictation_dirty()

    def _on_dictation_table_release(self, _event):
        self._dictation_drag_anchor_id = None
        self._dictation_drag_anchor_selected = None

    def _update_dictation_selection_count(self):
        if self.dictation_mode_var.get() == "manual":
            self.dictation_selection_count.configure(text=f"已选择 {len(self.dictation_selected_ids)} 个词条")
        else:
            suffix = f" · 已勾选 {len(self.dictation_selected_ids)} 个" if self.dictation_selected_ids else ""
            self.dictation_selection_count.configure(
                text=f"随机范围：{self._dictation_scope_label()}{suffix}",
            )

    def _dictation_options(self) -> DictationOptions:
        formats = frozenset(value for value, variable in self.dictation_format_vars.items() if variable.get())
        fields = frozenset(value for value, variable in self.dictation_field_vars.items() if variable.get())
        custom = self.dictation_custom_example_var.get().strip()
        custom_examples = None if not custom else {word_id: custom for word_id in self.dictation_selected_ids}
        return DictationOptions(
            formats=formats,
            font_size_pt=int(self.dictation_font_size_var.get()),
            missing_fields=fields,
            show_initial=self.dictation_initial_var.get(),
            include_examples=self.dictation_examples_var.get(),
            include_example_chinese=self.dictation_example_chinese_var.get(),
            custom_examples=custom_examples,
        )

    def preview_dictation(self):
        try:
            count = int(self.dictation_count_var.get())
            if count < 1:
                raise ValueError("默写数量必须大于 0")
            options = self._dictation_options()
            manual = self.dictation_mode_var.get() == "manual"
            if manual:
                if not self.dictation_selected_ids:
                    raise ValueError("请先选择至少一个词条")
                available_ids = {
                    entry.word_id
                    for entry in self.service.dictation_pool(self.dictation_include_evaluated_var.get())
                }
                available_selected_count = len(self.dictation_selected_ids & available_ids)
                if available_selected_count < count and not self._confirm_manual_dictation(available_selected_count, count):
                    return
                selected_entries = self.service.selected_dictation_candidates(
                    self.dictation_selected_ids,
                    self.dictation_include_evaluated_var.get(),
                )
                document = self.service.build_dictation_document(
                    options, entries=selected_entries,
                )
            else:
                # Any explicit row selections form a cross-group random pool;
                # with no selections we preserve the existing whole-scope
                # behavior for the active book.
                candidate_ids = set(self.dictation_selected_ids) or None
                selected_entries = self.service.dictation_candidates(
                    count,
                    self.dictation_include_evaluated_var.get(),
                    group=None if candidate_ids is not None else self.dictation_scope_group,
                    candidate_ids=candidate_ids,
                )
                document = self.service.build_dictation_document(
                    options, entries=selected_entries,
                )
            custom = self.dictation_custom_example_var.get().strip()
            if custom:
                options = replace(options, custom_examples={entry.word_id: custom for entry in selected_entries})
                document = self.service.build_dictation_document(options, entries=selected_entries)
            if not document.rows:
                raise ValueError("没有符合当前条件的词条")
        except (TypeError, ValueError) as exc:
            messagebox.showerror("默写设置有误", str(exc), parent=self)
            return
        self.dictation_document = document
        self.dictation_document_word_ids = {entry.word_id for entry in selected_entries}
        self._open_dictation_preview(document)

    def _confirm_manual_dictation(self, selected_count: int, requested_count: int) -> bool:
        dialog = tk.Toplevel(self)
        dialog.withdraw()
        dialog.title("确认选择")
        dialog.configure(bg=BG)
        dialog.transient(self)
        tk.Label(dialog, text=f"当前仅选择了{selected_count}/{requested_count}，是否确定选择", bg=BG, fg=TEXT, font="LexiBodyBold", wraplength=380).pack(padx=20, pady=(28, 18))
        result = {"value": False}
        buttons = tk.Frame(dialog, bg=BG)
        buttons.pack()
        def finish(value):
            result["value"] = value
            dialog.destroy()
        self._primary_button(buttons, "确定选择", lambda: finish(True), width=10).pack(side=tk.LEFT, padx=6)
        self._outline_button(buttons, "返回选择", lambda: finish(False), width=10).pack(side=tk.LEFT, padx=6)
        self._center_toplevel(dialog, 430, 170)
        self._show_prepared_toplevel(dialog)
        self._attach_pet_to_dialog(dialog, "dictation-confirm")
        dialog.grab_set()
        self.wait_window(dialog)
        return result["value"]

    def _open_dictation_preview(self, document):
        preview = tk.Toplevel(self)
        preview.withdraw()
        preview.title("默写预览 · A4 portrait")
        preview.minsize(620, 620)
        preview.configure(bg=BG)
        preview.transient(self)
        tk.Label(preview, text="A4 页面预览", bg=BG, fg=TEXT, font="LexiTitle").pack(anchor="w", padx=20, pady=(18, 2))
        tk.Label(preview, text=f"{len(document.rows)} 个词条 · {document.options.font_size_pt} pt · {', '.join(item.value.upper() for item in sorted(document.options.formats, key=lambda value: value.value))}", bg=BG, fg=MUTED, font="LexiSmall").pack(anchor="w", padx=20, pady=(0, 10))
        frame = tk.Frame(preview, bg=BG)
        frame.pack(fill=tk.BOTH, expand=True, padx=20)
        canvas = tk.Canvas(frame, bg="#DCE3E5", highlightthickness=0)
        scrollbar = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)

        def scroll_preview(event) -> str:
            direction, units = dictation_preview_scroll_units(getattr(event, "delta", 0))
            if units:
                canvas.yview_scroll(direction * units, "units")
            return "break"

        canvas.bind("<MouseWheel>", scroll_preview)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        page_width, page_height, gap = 520, 736, 22
        page_left = 35
        content_left = page_left + 26
        content_width = page_width - 52
        content_top_padding = 30
        content_bottom_padding = 34
        preview_font = tkfont.Font(
            root=preview,
            family="Microsoft YaHei UI",
            size=max(8, round(document.options.font_size_pt * page_width / 595)),
        )
        preview._dictation_preview_font = preview_font

        page_count = 0
        cursor_y = 0

        def add_page() -> None:
            nonlocal page_count, cursor_y
            page_count += 1
            page_top = gap + (page_count - 1) * (page_height + gap)
            canvas.create_rectangle(
                page_left, page_top, page_left + page_width, page_top + page_height,
                fill="#FFFFFF", outline="#C8D0D3",
            )
            cursor_y = page_top + content_top_padding

        add_page()
        for block in dictation_preview_blocks(document):
            page_top = gap + (page_count - 1) * (page_height + gap)
            text_item = canvas.create_text(
                content_left,
                cursor_y,
                anchor="nw",
                width=content_width,
                text=block,
                fill=TEXT,
                font=preview_font,
            )
            bounds = canvas.bbox(text_item)
            if bounds and bounds[3] > page_top + page_height - content_bottom_padding and cursor_y > page_top + content_top_padding:
                canvas.delete(text_item)
                add_page()
                text_item = canvas.create_text(
                    content_left,
                    cursor_y,
                    anchor="nw",
                    width=content_width,
                    text=block,
                    fill=TEXT,
                    font=preview_font,
                )
                bounds = canvas.bbox(text_item)
            cursor_y = (bounds[3] if bounds else cursor_y + preview_font.metrics("linespace")) + 10

        total_height = page_count * (page_height + gap) + gap
        canvas.configure(scrollregion=(0, 0, page_width + 80, total_height))
        for page_index in range(page_count):
            page_top = gap + page_index * (page_height + gap)
            canvas.create_text(
                page_left + page_width - 24,
                page_top + page_height - 18,
                anchor="e",
                text=f"{page_index + 1} / {page_count}",
                fill=MUTED,
                font=("Microsoft YaHei UI", 8),
            )
        actions = tk.Frame(preview, bg=BG)
        actions.pack(fill=tk.X, padx=20, pady=14)
        download_button = self._primary_button(
            actions, "下载文档", lambda: (preview.destroy(), self.download_dictation()), width=12,
        )
        download_button.pack(side=tk.RIGHT)
        self._outline_button(actions, "返回修改", preview.destroy, width=10).pack(side=tk.RIGHT, padx=8)
        self._center_toplevel(preview, 720, 780)
        self._show_prepared_toplevel(preview)
        self._attach_pet_to_dialog(preview, "dictation-preview")

    def download_dictation(self):
        document = self.dictation_document
        if document is None:
            return
        try:
            outputs = self.service.export_dictation(document)
        except Exception as exc:
            messagebox.showerror("下载失败", str(exc), parent=self)
            return
        successful: list[Path] = []
        for output in outputs:
            path = filedialog.asksaveasfilename(
                title=f"保存 {output.file_name}",
                initialfile=output.file_name,
                defaultextension=Path(output.file_name).suffix,
                filetypes=[("Word 文档", "*.docx")] if output.file_name.endswith(".docx") else [("PDF 文件", "*.pdf")],
                parent=self,
            )
            if not path:
                continue
            try:
                Path(path).write_bytes(output.bytes)
                successful.append(Path(path))
            except OSError as exc:
                messagebox.showerror("保存失败", str(exc), parent=self)
        if successful:
            self._apply_dictation_mark()
            messagebox.showinfo("下载完成", f"已保存 {len(successful)} 个文件。", parent=self)

    def export_dictation(self):
        """Keep the old internal entry point compatible with the download flow."""
        self.download_dictation()

    def _apply_dictation_mark(self):
        ids = {row_id for row_id in self._dictation_document_word_ids()}
        mode = self.service.mark_mode()
        if mode is MarkMode.ALWAYS:
            self.service.update_program_tags(ids, {"evaluated"}, set())
        elif mode is MarkMode.ASK:
            self._show_dictation_mark_dialog(ids)

    def _dictation_document_word_ids(self) -> set[str]:
        return set(self.dictation_document_word_ids)

    def _show_dictation_mark_dialog(self, word_ids: set[str]):
        dialog = tk.Toplevel(self)
        dialog.withdraw()
        dialog.title("标记默写词条")
        dialog.configure(bg=BG)
        dialog.transient(self)
        tk.Label(dialog, text="是否将本次导出的词条标记为 evaluated？", bg=BG, fg=TEXT, font="LexiBodyBold", wraplength=370).pack(padx=20, pady=(26, 12))
        dont_ask = tk.BooleanVar(value=False)
        tk.Checkbutton(dialog, text="不再提示", variable=dont_ask, bg=BG, fg=TEXT, activebackground=BG, selectcolor=BG, font="LexiSmall").pack()
        buttons = tk.Frame(dialog, bg=BG)
        buttons.pack(pady=18)
        def finish(mark: bool):
            if dont_ask.get():
                self.service.set_mark_mode(MarkMode.ALWAYS if mark else MarkMode.NEVER)
            if mark:
                self.service.update_program_tags(word_ids, {"evaluated"}, set())
            dialog.destroy()
        self._primary_button(buttons, "标记", lambda: finish(True), width=8).pack(side=tk.LEFT, padx=6)
        self._outline_button(buttons, "不标记", lambda: finish(False), width=8).pack(side=tk.LEFT, padx=6)
        self._center_toplevel(dialog, 420, 205)
        self._show_prepared_toplevel(dialog)
        self._attach_pet_to_dialog(dialog, "dictation-mark")
        dialog.grab_set()
        self.wait_window(dialog)

    def _resize_study_answer(self, event):
        wrap_width = max(360, event.width - 80)
        self.study_meaning.configure(wraplength=wrap_width)
        self.study_mnemonic.configure(wraplength=wrap_width)
        self._apply_answer_text(
            self.current_card,
            self.study_meaning,
            self.example_texts,
            self.example_labels,
            wrap_width,
            wrap_width,
            preserve_examples=True,
        )

    def _resize_review_answer(self, event):
        wrap_width = max(360, event.width - 80)
        self.review_meaning.configure(wraplength=wrap_width)
        card = self.review_queue[0] if self.review_queue else None
        self._apply_answer_text(card, self.review_meaning, self.review_example_texts, self.review_example_labels, wrap_width)

    def _elide_line(self, text: str, font_name: str, width: int, whole_words: bool = False) -> str:
        font = tkfont.nametofont(font_name)
        if font.measure(text) <= width:
            return text
        suffix = "..."
        low, high = 0, len(text)
        while low < high:
            middle = (low + high + 1) // 2
            if font.measure(text[:middle] + suffix) <= width:
                low = middle
            else:
                high = middle - 1
        if whole_words and low < len(text):
            space = text.rfind(" ", 0, low)
            if space > 0:
                low = space
        return text[:low].rstrip() + suffix

    def _apply_answer_text(
        self,
        card: VocabularyEntry | None,
        meaning_label: tk.Label,
        example_texts: list,
        example_labels: list[tk.Label],
        width: int,
        example_width: int | None = None,
        preserve_examples: bool = False,
    ) -> None:
        if card is None:
            return
        meaning = card.meaning
        if int(meaning_label.cget("height")) == 1:
            meaning = self._elide_line(meaning, meaning_label.cget("font"), width)
        meaning_label.configure(text=meaning)
        example_width = example_width or width
        for index, (text_widget, label) in enumerate(zip(example_texts, example_labels)):
            example = card.examples[index]
            english = f"{index + 1}. {example.english}"
            chinese = example.chinese
            if not preserve_examples:
                english = self._elide_line(english, label.cget("font"), example_width, whole_words=True)
                chinese = self._elide_line(chinese, label.cget("font"), example_width)
            text_widget.set_sentence(english, example.english)
            label.configure(text=chinese, wraplength=example_width)

    def _build_library_page(self):
        _, body = self._new_page("library", "词库", "先选择词书分组，再查看该组的单词")
        toolbar = tk.Frame(body, bg=BG)
        toolbar.pack(fill=tk.X, pady=(0, 12))
        icon = tk.Canvas(toolbar, width=28, height=28, bg=BG, bd=0, highlightthickness=0)
        icon.pack(side=tk.LEFT, padx=(0, 8))
        draw_icon(icon, "search", MUTED)
        self.search_var = tk.StringVar()
        self.search_entry = tk.Entry(toolbar, textvariable=self.search_var, font="LexiBody", relief="solid", bd=1)
        self.search_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=7)
        self.search_entry.bind("<KeyRelease>", lambda _event: self.refresh_library())
        upload_icon = tk.Canvas(toolbar, width=28, height=28, bg=BG, bd=0, highlightthickness=0)
        upload_icon.pack(side=tk.LEFT, padx=(16, 4))
        draw_icon(upload_icon, "upload", ACCENT)
        self._outline_button(toolbar, "导入 CSV", self.choose_csv, width=10).pack(side=tk.LEFT)
        self._outline_button(toolbar, "批量标签", self.batch_edit_labels, width=10).pack(side=tk.LEFT, padx=(8, 0))
        tk.Label(body, text="导入 CSV 时填写 level（CET4/CET6/custom，可用 | 分隔）和 tags（用 | 分隔）；点击分组进入该组单词，可批量修改。", bg=BG, fg=MUTED, font="LexiSmall", anchor="w").pack(fill=tk.X, pady=(0, 7))

        self.library_stack = tk.Frame(body, bg=BG)
        self.library_stack.pack(fill=tk.BOTH, expand=True)

        # Group browser sub-view.
        self.library_groups_view = tk.Frame(self.library_stack, bg=BG)
        self.library_groups_header = tk.Label(self.library_groups_view, text="", bg=BG, fg=MUTED, font="LexiSmall")
        self.library_groups_header.pack(anchor="w", pady=(0, 10))
        groups_canvas = tk.Canvas(self.library_groups_view, bg=BG, highlightthickness=0)
        groups_scrollbar = ttk.Scrollbar(self.library_groups_view, orient=tk.VERTICAL, command=groups_canvas.yview)
        self.library_groups_inner = tk.Frame(groups_canvas, bg=BG)
        self.library_groups_inner.bind(
            "<Configure>",
            lambda _e: groups_canvas.configure(scrollregion=groups_canvas.bbox("all")),
        )
        group_window = groups_canvas.create_window((0, 0), window=self.library_groups_inner, anchor="nw")
        groups_canvas.bind(
            "<Configure>",
            lambda e: groups_canvas.itemconfigure(group_window, width=e.width),
        )
        groups_canvas.configure(yscrollcommand=groups_scrollbar.set)
        groups_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        groups_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # Words sub-view (the existing word table).
        self.library_words_view = tk.Frame(self.library_stack, bg=BG)
        words_header = tk.Frame(self.library_words_view, bg=BG)
        words_header.pack(fill=tk.X, pady=(0, 7))
        self._outline_button(words_header, "← 返回词书", self._back_to_groups, width=12).pack(side=tk.LEFT)
        self.library_group_title = tk.Label(words_header, text="", bg=BG, fg=TEXT, font="LexiHeading")
        self.library_group_title.pack(side=tk.LEFT, padx=(16, 0))
        self.library_count = tk.Label(self.library_words_view, text="", bg=BG, fg=MUTED, font="LexiSmall")
        self.library_count.pack(anchor="w", pady=(0, 7))
        table = self._card(self.library_words_view)
        table.pack(fill=tk.BOTH, expand=True)
        columns = ("word", "meaning", "level", "review")
        self.library_tree = ttk.Treeview(table, columns=columns, show="headings", selectmode="extended")
        self.library_item_ids: dict[str, str] = {}
        for key, title, width in (("word", "单词", 180), ("meaning", "中文释义", 430), ("level", "词书", 120), ("review", "下次复习", 150)):
            self.library_tree.heading(key, text=title)
            self.library_tree.column(key, width=width, anchor="w", stretch=key == "meaning")
        scrollbar = ttk.Scrollbar(table, orient=tk.VERTICAL, command=self.library_tree.yview)
        self.library_tree.configure(yscrollcommand=scrollbar.set)
        self.library_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.library_group: str | None = None
        self._show_library_view("groups")

    def _show_library_view(self, view: str):
        if view == "groups":
            self.library_words_view.pack_forget()
            self.library_groups_view.pack(fill=tk.BOTH, expand=True)
        else:
            self.library_groups_view.pack_forget()
            self.library_words_view.pack(fill=tk.BOTH, expand=True)

    def _refresh_group_cards(self):
        for child in self.library_groups_inner.winfo_children():
            child.destroy()
        groups = self.service.library_groups()
        total = next((group.count for group in groups if group.key == "all"), 0)
        self.library_groups_header.configure(text=f"词书分组（共 {total:,} 条词条，点击进入分组查看单词）")
        for group in groups:
            card = tk.Frame(
                self.library_groups_inner,
                bg=SURFACE,
                bd=0,
                highlightthickness=1,
                highlightbackground="#DDE6E4",
                cursor="hand2",
            )
            card.pack(fill=tk.X, pady=(0, 8))
            label = tk.Label(card, text=group.label, bg=SURFACE, fg=TEXT, font="LexiBody", anchor="w")
            label.pack(side=tk.LEFT, padx=16, pady=14)
            count = tk.Label(card, text=f"{group.count:,} 词", bg=SURFACE, fg=MUTED, font="LexiSmall")
            count.pack(side=tk.RIGHT, padx=16, pady=14)
            for widget in (card, label, count):
                widget.bind("<Button-1>", lambda _e, key=group.key: self._open_library_group(key))

    def _open_library_group(self, key: str):
        self.library_group = key
        self.search_var.set("")
        self.refresh_library()

    def _back_to_groups(self):
        self.library_group = None
        self.search_var.set("")
        self.refresh_library()

    def _build_analytics_page(self):
        _, body = self._new_page("analytics", "记忆分析", "复习负载与平均保持率")
        controls = tk.Frame(body, bg=BG)
        controls.pack(fill=tk.X, pady=(0, 12))
        self.forecast_7_button = self._outline_button(controls, "未来 7 天", lambda: self.set_forecast_days(7))
        self.forecast_7_button.pack(side=tk.LEFT)
        self.forecast_30_button = self._outline_button(controls, "未来 30 天", lambda: self.set_forecast_days(30))
        self.forecast_30_button.pack(side=tk.LEFT, padx=8)
        self.analytics_summary = tk.Label(controls, text="", bg=BG, fg=MUTED, font="LexiBody")
        self.analytics_summary.pack(side=tk.RIGHT)
        chart_card = self._card(body)
        chart_card.pack(fill=tk.BOTH, expand=True)
        self.analytics_chart = MemoryChart(chart_card)
        self.analytics_chart.pack(fill=tk.BOTH, expand=True, padx=14, pady=14)

    def _build_reminder_page(self):
        _, body = self._new_page(
            "reminder",
            "学习提醒",
            "应用运行期间，按设定间隔弹出一张置顶单词卡片",
        )
        panel = self._card(body)
        panel.pack(fill=tk.BOTH, expand=True)
        inner = tk.Frame(panel, bg=SURFACE)
        inner.pack(fill=tk.X, padx=30, pady=26)

        tk.Label(inner, text="单词卡片提醒", bg=SURFACE, fg=TEXT, font="LexiHeading").pack(anchor="w")
        tk.Label(
            inner,
            text="间隔单位为分钟，可输入小数；有效范围为 0.5 到 120 min。",
            bg=SURFACE,
            fg=MUTED,
            font="LexiSmall",
        ).pack(anchor="w", pady=(5, 18))

        self.reminder_enabled_var = tk.BooleanVar(value=self.service.reminder_enabled())
        tk.Checkbutton(
            inner,
            text="开启弹窗单词卡片",
            variable=self.reminder_enabled_var,
            bg=SURFACE,
            fg=TEXT,
            activebackground=SURFACE,
            activeforeground=TEXT,
            selectcolor=SURFACE,
            font="LexiBodyBold",
            cursor="hand2",
        ).pack(anchor="w", pady=(0, 18))

        interval_row = tk.Frame(inner, bg=SURFACE)
        interval_row.pack(anchor="w")
        tk.Label(interval_row, text="弹窗间隔", bg=SURFACE, fg=MUTED, font="LexiSmall").pack(side=tk.LEFT)
        self.reminder_interval_var = tk.StringVar(value=f"{self.service.reminder_interval_minutes():g}")
        ttk.Entry(interval_row, textvariable=self.reminder_interval_var, width=12).pack(side=tk.LEFT, padx=(10, 6))
        tk.Label(interval_row, text="min", bg=SURFACE, fg=TEXT, font="LexiBodyBold").pack(side=tk.LEFT)

        reminder_filter = tk.Frame(inner, bg=SURFACE)
        reminder_filter.pack(fill=tk.X, pady=(18, 0))
        self.reminder_filter_vars = self._build_level_filters(
            reminder_filter,
            "弹窗词汇组",
            self.service.reminder_levels,
            self._save_reminder_levels,
        )

        self.reminder_status = tk.Label(
            inner,
            text="",
            bg="#E7F5F0",
            fg=ACCENT,
            font="LexiBodyBold",
            padx=12,
            pady=9,
        )
        self.reminder_status.pack(anchor="w", pady=(24, 18))
        actions = tk.Frame(inner, bg=SURFACE)
        actions.pack(fill=tk.X)
        self._primary_button(actions, "保存设置", self.save_reminder_settings, width=10).pack(side=tk.LEFT)
        self._outline_button(actions, "立即预览", self.preview_word_reminder, width=10).pack(side=tk.LEFT, padx=10)

        tk.Label(
            panel,
            text="弹窗展示单词、音标、释义和三组双语例句。关闭应用后不会继续计时。",
            bg="#F7F9FA",
            fg=MUTED,
            font="LexiSmall",
            wraplength=760,
            justify="left",
            padx=24,
            pady=16,
        ).pack(fill=tk.X, side=tk.BOTTOM)
        self._refresh_word_reminder_status()

    def _build_settings_page(self):
        _, body = self._new_page("settings", "设置", "显示与本地数据")
        display = self._card(body)
        display.pack(fill=tk.X)
        tk.Label(display, text="字体大小", bg=SURFACE, fg=TEXT, font="LexiHeading").pack(anchor="w", padx=22, pady=(20, 4))
        self.scale_text = tk.Label(display, text="", bg=SURFACE, fg=ACCENT, font="LexiBodyBold")
        self.scale_text.pack(anchor="w", padx=22)
        initial_font_scale = sanitize_font_scale(
            self.service.font_scale(),
            fallback=DEFAULT_FONT_SCALE,
        )
        self.scale_var = tk.DoubleVar(value=initial_font_scale * 100)
        scale = tk.Scale(
            display,
            from_=90,
            to=140,
            resolution=5,
            orient=tk.HORIZONTAL,
            variable=self.scale_var,
            command=self.change_font_scale,
            showvalue=False,
            bg=SURFACE,
            fg=TEXT,
            activebackground=ACCENT,
            highlightthickness=0,
            troughcolor="#DDE6E4",
            length=460,
        )
        scale.pack(anchor="w", padx=18, pady=(6, 18))
        review = self._card(body)
        review.pack(fill=tk.X, pady=(16, 0))
        tk.Label(review, text="每轮复习数量", bg=SURFACE, fg=TEXT, font="LexiHeading").pack(anchor="w", padx=22, pady=(18, 4))
        self.review_batch_text = tk.Label(review, text="", bg=SURFACE, fg=ACCENT, font="LexiBodyBold")
        self.review_batch_text.pack(anchor="w", padx=22)
        learnt_count = self.service.learnt_word_count()
        self.review_batch_var = tk.IntVar(value=self.service.review_batch_size())
        self.review_batch_scale = tk.Scale(
            review,
            from_=1,
            to=max(1, learnt_count),
            resolution=1,
            orient=tk.HORIZONTAL,
            variable=self.review_batch_var,
            command=self.change_review_batch_size,
            showvalue=False,
            state=tk.NORMAL if learnt_count else tk.DISABLED,
            bg=SURFACE,
            activebackground=ACCENT,
            highlightthickness=0,
            troughcolor="#DDE6E4",
            length=460,
        )
        self.review_batch_scale.pack(anchor="w", padx=18, pady=(6, 18))
        order = self._card(body)
        order.pack(fill=tk.X, pady=(16, 0))
        tk.Label(order, text="学习顺序", bg=SURFACE, fg=TEXT, font="LexiHeading").pack(anchor="w", padx=22, pady=(18, 4))
        tk.Label(order, text="默认随机；可切换为按字母排序。", bg=SURFACE, fg=MUTED, font="LexiSmall").pack(anchor="w", padx=22)
        self.study_order_var = tk.StringVar(value=self.service.study_order())
        options = tk.Frame(order, bg=SURFACE)
        options.pack(anchor="w", padx=18, pady=(8, 18))
        for value, label in (("random", "随机顺序"), ("alphabetical", "按字母排序")):
            tk.Radiobutton(options, text=label, value=value, variable=self.study_order_var, command=self.save_study_order, bg=SURFACE, fg=TEXT, activebackground=SURFACE, selectcolor=SURFACE, font="LexiBody").pack(side=tk.LEFT, padx=(0, 20))
        mark = self._card(body)
        mark.pack(fill=tk.X, pady=(0, 0))
        tk.Label(mark, text="默写后的标记", bg=SURFACE, fg=TEXT, font="LexiHeading").pack(anchor="w", padx=22, pady=(18, 4))
        tk.Label(mark, text="选择是否默认给本次导出的词条添加 evaluated 标签。", bg=SURFACE, fg=MUTED, font="LexiSmall").pack(anchor="w", padx=22)
        self.mark_mode_var = tk.StringVar(value=self.service.mark_mode().value)
        mark_options = tk.Frame(mark, bg=SURFACE)
        mark_options.pack(anchor="w", padx=18, pady=(8, 18))
        for value, label in ((MarkMode.ALWAYS.value, "默认标记"), (MarkMode.NEVER.value, "默认不标记"), (MarkMode.ASK.value, "每次询问")):
            tk.Radiobutton(mark_options, text=label, value=value, variable=self.mark_mode_var, command=self.save_mark_mode, bg=SURFACE, fg=TEXT, activebackground=SURFACE, selectcolor=SURFACE, font="LexiBody").pack(side=tk.LEFT, padx=(0, 20))
        storage = self._card(body)
        storage.pack(fill=tk.X, pady=16)
        tk.Label(storage, text="本地数据", bg=SURFACE, fg=TEXT, font="LexiHeading").pack(anchor="w", padx=22, pady=(20, 5))
        tk.Label(storage, text=str(self.data_dir), bg=SURFACE, fg=MUTED, font="LexiSmall", wraplength=760, justify="left").pack(anchor="w", padx=22, pady=(0, 8))
        catalog_message = f"共享词库已加载 {self.catalog_count:,} 条"
        if self.catalog_error:
            catalog_message = "共享词库读取失败，当前以空库启动"
        elif not self.catalog_count:
            catalog_message = "未发现共享词库，当前以空库启动"
        elif self.catalog_rejected:
            catalog_message += f"；门禁排除 {self.catalog_rejected:,} 条"
        tk.Label(storage, text=catalog_message, bg=SURFACE, fg=ACCENT if self.catalog_count else ORANGE, font="LexiBody").pack(anchor="w", padx=22, pady=(0, 20))
        self.change_font_scale(str(self.scale_var.get()))
        self.change_review_batch_size(str(self.review_batch_var.get()))

    def save_mark_mode(self):
        try:
            self.service.set_mark_mode(MarkMode(self.mark_mode_var.get()))
        except ValueError as exc:
            messagebox.showerror("设置有误", str(exc), parent=self)

    def _build_level_filters(self, parent, title: str, selected_getter, on_change, inline: bool = False):
        background = parent.cget("bg")
        frame = tk.Frame(parent, bg=background)
        if inline:
            frame.pack(side=tk.RIGHT, padx=(8, 0))
        else:
            frame.configure(height=26)
            frame.pack(fill=tk.X, pady=(0, 4))
            frame.pack_propagate(False)
        tk.Label(frame, text=title, bg=background, fg=MUTED, font="LexiSmall").pack(side=tk.LEFT, padx=(0, 6))
        selected = selected_getter()
        if not selected:
            selected = {"CET4", "CET6", "CUSTOM"}
        variables: dict[str, tk.BooleanVar] = {}
        for value, label in (("CET4", "四级"), ("CET6", "六级"), ("CUSTOM", "自定义")):
            var = tk.BooleanVar(value=value in selected)
            variables[value] = var
            tk.Checkbutton(frame, text=label, variable=var, command=on_change, bg=background, fg=TEXT, activebackground=background, selectcolor=background, font="LexiSmall", padx=0, pady=0, height=1).pack(side=tk.LEFT, padx=(0, 5))
        return variables

    def _selected_levels(self, variables: dict[str, tk.BooleanVar]) -> set[str]:
        selected = {level for level, variable in variables.items() if variable.get()}
        if selected:
            return selected
        for variable in variables.values():
            variable.set(True)
        return set(variables)

    def _save_study_levels(self):
        self.service.set_study_levels(self._selected_levels(self.study_filter_vars))
        self.load_study_card()

    def _save_review_levels(self):
        self.service.set_review_levels(self._selected_levels(self.review_filter_vars))
        self.review_queue = []
        self.refresh_review_page()

    def _save_reminder_levels(self):
        self.service.set_reminder_levels(self._selected_levels(self.reminder_filter_vars))

    def save_study_order(self):
        self.service.set_study_order(self.study_order_var.get())
        if self.current_page == "study":
            self.load_study_card()

    def _bind_shortcuts(self):
        self.bind("<Control-k>", lambda _event: self._focus_search())
        self.bind("<Control-s>", self._on_control_s, add="+")
        self.bind("<FocusIn>", self._on_app_focus_in, add="+")
        self.bind("<FocusOut>", self._on_app_focus_out, add="+")
        self.bind("<space>", lambda _event: self._reveal_current_answer())
        for key, rating in (("1", ReviewRating.AGAIN), ("2", ReviewRating.HARD), ("3", ReviewRating.GOOD), ("4", ReviewRating.EASY)):
            self.bind(key, lambda _event, value=rating: self._rate_visible_card(value))

    def _on_control_s(self, _event):
        if self.current_page == "dictation":
            self.save_dictation_selection()
            return "break"
        return None

    def _on_app_focus_in(self, _event) -> None:
        if self._dictation_window_active:
            return
        self._dictation_window_active = True
        self._pull_dictation_draft_async()

    def _on_app_focus_out(self, _event) -> None:
        # FocusOut also fires while focus moves between child controls.  Wait
        # for Tk to settle before deciding that the application lost focus.
        self.after_idle(self._refresh_dictation_window_active)

    def _refresh_dictation_window_active(self) -> None:
        try:
            self._dictation_window_active = self.focus_displayof() is not None
        except tk.TclError:
            self._dictation_window_active = False

    def _focus_search(self):
        self.show_page("library")
        self.after_idle(self.search_entry.focus_set)

    def show_page(self, key: str):
        if self.current_page == "dictation" and key != "dictation":
            if not self._confirm_dictation_leave():
                return
        if self.current_page != key:
            reward_effects = vars(self).get("_reward_effects")
            if reward_effects is not None:
                reward_effects.clear()
        # Page packing immediately changes target geometry.  Invalidate
        # callbacks scheduled against the previous page before navigation
        # turns the companion into a FALL transition.
        self._invalidate_main_pet_render()
        self.word_bubbles.clear()
        if self.current_page and self.current_page != key:
            self.pet_companion.navigate()
            self._pet_targets = ()
        if key != "dictation":
            self._cancel_dictation_loading()
        if self.current_page:
            self.pages[self.current_page].pack_forget()
            self.nav_items[self.current_page].set_selected(False)
        self.current_page = key
        self.pages[key].pack(fill=tk.BOTH, expand=True)
        self.nav_items[key].set_selected(True)
        if key == "dashboard":
            self.refresh_dashboard()
        elif key == "study":
            self.load_study_card()
        elif key == "review":
            self.refresh_review_page()
        elif key == "dictation":
            self._begin_dictation_loading()
            self._pull_dictation_draft_async()
        elif key == "library":
            self.refresh_library()
        elif key == "analytics":
            self.refresh_analytics()
        elif key == "reminder":
            self._refresh_word_reminder_status()
        self._schedule_pet_target_refresh()

    def _begin_dictation_loading(self) -> None:
        self._cancel_dictation_loading()
        overlay = DictationLoadingOverlay(self.dictation_body)
        overlay.place(x=0, y=0, relwidth=1, relheight=1)
        self._dictation_loading = overlay
        overlay.start()
        delay_ms = dictation_loading_delay_ms()
        self._dictation_loading_after_id = self.after(delay_ms, self._complete_dictation_loading)

    def _complete_dictation_loading(self) -> None:
        self._cancel_dictation_loading_timer()
        overlay = self._dictation_loading
        if overlay is None:
            return
        self._refresh_dictation_candidates()
        self._dictation_loading = None
        overlay.stop()
        overlay.destroy()

    def _cancel_dictation_loading(self) -> None:
        self._cancel_dictation_loading_timer()
        overlay = self._dictation_loading
        if overlay is not None:
            self._dictation_loading = None
            overlay.stop()
            overlay.destroy()

    def _cancel_dictation_loading_timer(self) -> None:
        if self._dictation_loading_after_id is not None:
            try:
                self.after_cancel(self._dictation_loading_after_id)
            except tk.TclError:
                pass
            self._dictation_loading_after_id = None

    def refresh_dashboard(self):
        snapshot = self.service.dashboard()
        for key in self.stat_labels:
            self.stat_labels[key].configure(text=f"{getattr(snapshot, key):,}")
        self.dashboard_plan.configure(text=f"{snapshot.due_now} 个到期复习，{snapshot.new_words} 个未学习词条")
        if snapshot.due_now:
            self.dashboard_action_button.configure(text="开始复习", command=lambda: self.show_page("review"))
        else:
            self.dashboard_action_button.configure(text="开始学习", command=lambda: self.show_page("study"))
        self.dashboard_chart.set_data(self.service.forecast(7), self.service.retention_curve(7))

    def load_study_card(self, exclude_id: str = ""):
        # Rating a card unpacks and repacks answer controls; queued frames may
        # otherwise write the old card position after the reflow.
        self._invalidate_main_pet_render()
        self.word_bubbles.clear()
        self.current_card = self.service.next_card(exclude_id=exclude_id)
        self.answer_visible = False
        self.answer_panel.pack_forget()
        self.rating_frame.pack_forget()
        self.study_controls.pack(fill=tk.X, pady=(4, 2))
        self.reveal_button.pack(pady=4)
        if self.current_card is None:
            self.study_level.configure(text="已完成")
            self.study_word.configure(text="本轮学习完成")
            self.study_phonetic.configure(text="")
            self.reveal_button.configure(text="刷新", command=lambda: self.load_study_card())
            self.study_status.configure(text="当前没有到期或未学习词条")
            return
        entry = self.current_card
        self.reveal_button.configure(text="查看答案", command=self.reveal_answer)
        self.study_level.configure(text=entry.level or "custom")
        self.study_word.configure(text=entry.word)
        self.study_phonetic.configure(text=entry.phonetic)
        state = self.service.repository.review_state(entry.word_id)
        status = "新词" if state.last_reviewed_at_utc is None else f"已复习 {state.repetitions} 次 · 遗忘 {state.lapses} 次"
        self.study_status.configure(text=status)

    def reveal_answer(self):
        if self.current_card is None or self.answer_visible:
            return
        self._invalidate_main_pet_render()
        entry = self.current_card
        self.answer_visible = True
        self._apply_answer_text(
            entry,
            self.study_meaning,
            self.example_texts,
            self.example_labels,
            max(360, self.answer_panel.winfo_width() - 80),
            max(360, self.answer_panel.winfo_width() - 80),
            preserve_examples=True,
        )
        if entry.mnemonic:
            self.study_mnemonic.configure(text=f"助记  {entry.mnemonic}")
            self.study_mnemonic.pack(pady=(8, 0))
        else:
            self.study_mnemonic.pack_forget()
        self.study_controls.pack_forget()
        self.rating_frame.pack(side=tk.BOTTOM, fill=tk.X, padx=14, pady=(2, 4))
        self.answer_panel.pack(fill=tk.BOTH, expand=True, padx=12, pady=(2, 4))

    def rate_current(
        self,
        rating: ReviewRating,
        source: RewardPoint | None = None,
    ):
        if self.current_card is None or not self.answer_visible:
            return
        previous = self.current_card.word_id
        if source is None:
            index = tuple(ReviewRating).index(rating)
            source = self._rating_button_center(self.rating_buttons[index])
        # Start the transient feedback before persistence/reflow can unmap
        # the rating controls and move the pet target.
        self._emit_rating_reward(source, STUDY_REWARD_COLOR)
        self.service.rate_card(previous, rating)
        self._sync_review_batch_control()
        self.load_study_card(exclude_id=previous)

    def refresh_review_page(self):
        self._sync_review_batch_control()
        if self.review_queue:
            self.review_toolbar.pack_forget()
            self.review_start_row.pack_forget()
        elif not self.review_toolbar.winfo_manager():
            self.review_toolbar.pack(fill=tk.X, pady=(0, 4), before=self.review_card)
            self.review_start_row.pack(fill=tk.X, pady=(0, 10), before=self.review_card)
        learnt_count = self.service.learnt_word_count()
        due_count = self.service.due_review_count()
        batch_size = min(self.service.review_batch_size(), learnt_count) if learnt_count else 0
        self.review_summary.configure(text=f"已学 {learnt_count} 词 · 到期 {due_count} 词 · 每轮 {batch_size} 词")
        self.review_start_button.configure(state=tk.NORMAL if learnt_count else tk.DISABLED)
        if self.review_queue:
            self._show_next_review_card()
        elif self.review_total:
            self.review_word.configure(text="本轮复习完成")
            self.review_phonetic.configure(text="")
            self.review_progress.configure(text=f"已完成 {self.review_total} / {self.review_total}")
        elif not learnt_count:
            self.review_word.configure(text="先在学习中完成单词评分")
            self.review_phonetic.configure(text="")
            self.review_progress.configure(text="暂无已学词")

    def start_review_session(self):
        self.review_queue = self.service.start_review_session()
        self.review_total = len(self.review_queue)
        if self.review_queue:
            self.review_toolbar.pack_forget()
        self._show_next_review_card()

    def _show_next_review_card(self):
        self._invalidate_main_pet_render()
        self.word_bubbles.clear()
        self.review_answer_visible = False
        self.review_answer_panel.pack_forget()
        self.review_rating_frame.pack_forget()
        self.review_controls.pack_forget()
        self.review_reveal_button.pack_forget()
        if not self.review_queue:
            self.refresh_review_page()
            return
        self.review_toolbar.pack_forget()
        self.review_start_row.pack_forget()
        card = self.review_queue[0]
        self.review_level.configure(text=card.level or "custom")
        self.review_word.configure(text=card.word)
        self.review_phonetic.configure(text=card.phonetic)
        completed = self.review_total - len(self.review_queue)
        self.review_progress.configure(text=f"{completed + 1} / {self.review_total}")
        self.review_reveal_button.configure(text="查看答案", command=self.reveal_review_answer)
        self.review_controls.pack(fill=tk.X, pady=(4, 2))
        self.review_reveal_button.pack(pady=4)

    def reveal_review_answer(self):
        if not self.review_queue or self.review_answer_visible:
            return
        self._invalidate_main_pet_render()
        card = self.review_queue[0]
        self.review_answer_visible = True
        self._apply_answer_text(card, self.review_meaning, self.review_example_texts, self.review_example_labels, max(360, self.review_answer_panel.winfo_width() - 80))
        self.review_controls.pack_forget()
        self.review_rating_frame.pack(side=tk.BOTTOM, fill=tk.X, padx=14, pady=(2, 4))
        self.review_answer_panel.pack(fill=tk.BOTH, expand=True, padx=12, pady=(2, 4))

    def rate_review_current(
        self,
        rating: ReviewRating,
        source: RewardPoint | None = None,
    ):
        if not self.review_queue or not self.review_answer_visible:
            return
        card = self.review_queue[0]
        if source is None:
            index = tuple(ReviewRating).index(rating)
            source = self._rating_button_center(self.review_rating_buttons[index])
        # Keep the visual response independent from the review repository;
        # the card may be rebuilt immediately after this call.
        self._emit_rating_reward(source, REVIEW_REWARD_COLOR)
        self.service.rate_review_card(card.word_id, rating)
        self.review_queue.pop(0)
        self._show_next_review_card()

    def _reveal_current_answer(self):
        if self.current_page == "study":
            self.reveal_answer()
        elif self.current_page == "review":
            self.reveal_review_answer()

    def _rate_visible_card(self, rating: ReviewRating):
        if self.current_page == "study" and self.answer_visible:
            index = tuple(ReviewRating).index(rating)
            self.rate_current(rating, self._rating_button_center(self.rating_buttons[index]))
        elif self.current_page == "review" and self.review_answer_visible:
            index = tuple(ReviewRating).index(rating)
            self.rate_review_current(rating, self._rating_button_center(self.review_rating_buttons[index]))

    def _check_review_reminder(self):
        due_count = self.service.due_review_count()
        if self._smoke_testing:
            self._last_reminded_due_count = due_count
        elif due_count > 0 and due_count != self._last_reminded_due_count:
            self._last_reminded_due_count = due_count
            messagebox.showinfo("复习提醒", f"有 {due_count} 个单词已按记忆曲线到期。", parent=self)
        elif due_count == 0:
            self._last_reminded_due_count = 0
        self.after(60_000, self._check_review_reminder)

    def save_reminder_settings(self):
        try:
            interval = float(self.reminder_interval_var.get().strip())
            self.service.set_reminder_settings(self.reminder_enabled_var.get(), interval)
            self.service.set_reminder_levels(self._selected_levels(self.reminder_filter_vars))
        except (TypeError, ValueError) as exc:
            message = str(exc) or "提醒间隔必须是有效数字"
            messagebox.showerror("设置有误", message, parent=self)
            return False
        self.reminder_interval_var.set(f"{interval:g}")
        self._schedule_word_reminder()
        return True

    def _cancel_word_reminder(self):
        if self._word_reminder_after_id is not None:
            try:
                self.after_cancel(self._word_reminder_after_id)
            except tk.TclError:
                pass
            self._word_reminder_after_id = None
        self._word_reminder_next_at = 0.0

    def _schedule_word_reminder(self, delay_minutes: float | None = None):
        self._cancel_word_reminder()
        if not self.service.reminder_enabled():
            self._refresh_word_reminder_status()
            return
        interval = self.service.reminder_interval_minutes() if delay_minutes is None else float(delay_minutes)
        delay_ms = max(1, round(interval * 60_000))
        self._word_reminder_next_at = time.time() + delay_ms / 1000
        self._word_reminder_after_id = self.after(delay_ms, self._on_word_reminder_due)
        self._refresh_word_reminder_status()

    def _refresh_word_reminder_status(self):
        if not hasattr(self, "reminder_status"):
            return
        if not self.service.reminder_enabled():
            self.reminder_status.configure(text="提醒已关闭", bg="#EDF1F4", fg=MUTED)
        elif self._word_reminder_next_at:
            remaining_minutes = max(0.0, (self._word_reminder_next_at - time.time()) / 60)
            self.reminder_status.configure(
                text=f"下一张卡片约在 {remaining_minutes:.1f} min 后弹出",
                bg="#E7F5F0",
                fg=ACCENT,
            )
        else:
            self.reminder_status.configure(text="提醒将在应用启动后安排", bg="#EAF1FA", fg=BLUE)

    def _on_word_reminder_due(self):
        self._word_reminder_after_id = None
        self._word_reminder_next_at = 0.0
        self._show_word_reminder_popup(preview=False)

    def preview_word_reminder(self):
        self._show_word_reminder_popup(preview=True)

    def _show_word_reminder_popup(self, preview: bool = False):
        if self._word_reminder_popup is not None and self._word_reminder_popup.winfo_exists():
            if not preview:
                self._word_reminder_is_preview = False
            self._word_reminder_popup.deiconify()
            self._word_reminder_popup.lift()
            return
        entry = self.service.reminder_card(exclude_id=self._word_reminder_previous_id)
        if entry is None:
            if preview:
                messagebox.showinfo("暂无单词", "当前词库中没有可展示的单词。", parent=self)
            else:
                self._schedule_word_reminder()
            return
        self._word_reminder_previous_id = entry.word_id
        self._word_reminder_is_preview = preview

        popup = tk.Toplevel(self)
        popup.withdraw()
        self._word_reminder_popup = popup
        popup.title("LexiTrack 词程 · 单词提醒")
        popup.minsize(REMINDER_POPUP_WIDTH, REMINDER_POPUP_HEIGHT)
        popup.maxsize(REMINDER_POPUP_WIDTH, REMINDER_POPUP_HEIGHT)
        popup.resizable(False, False)
        popup.configure(bg=SURFACE)
        popup.transient(self)
        try:
            popup.attributes("-topmost", True)
        except tk.TclError:
            pass

        heading = tk.Frame(popup, bg=SIDEBAR)
        heading.pack(fill=tk.X)
        tk.Label(heading, text="单词学习提醒", bg=SIDEBAR, fg="#FFFFFF", font="LexiBodyBold").pack(anchor="w", padx=26, pady=(18, 2))
        tk.Label(heading, text="用一分钟巩固这张卡片", bg=SIDEBAR, fg="#92A0AD", font="LexiSmall").pack(anchor="w", padx=26, pady=(0, 18))

        content = tk.Frame(popup, bg=SURFACE)
        content.pack(fill=tk.BOTH, expand=True, padx=28, pady=14)
        tk.Label(content, text=entry.word, bg=SURFACE, fg=TEXT, font="LexiWord").pack(anchor="w")
        tk.Label(content, text=entry.phonetic or "音标待补充", bg=SURFACE, fg=MUTED, font="LexiBody").pack(anchor="w", pady=(2, 14))
        tk.Label(content, text=entry.meaning, bg=SURFACE, fg=TEXT, font="LexiBodyBold", wraplength=610, justify="left").pack(anchor="w")
        tk.Label(content, text="双语例句", bg=SURFACE, fg=MUTED, font="LexiSmall").pack(anchor="w", pady=(12, 4))
        examples_view = ScrollableExamplePanel(
            content,
            SURFACE,
            BORDER,
            viewport_width=REMINDER_EXAMPLES_WIDTH,
            viewport_height=REMINDER_EXAMPLES_HEIGHT,
        )
        examples_view.pack(anchor="w")
        self._word_reminder_examples_view = examples_view
        self._word_reminder_example_labels: list[tk.Label] = []
        for index, example in enumerate(entry.examples[:3], start=1):
            english = WordClickableText(
                examples_view.content,
                on_token=lambda token, ctx, x_root, y_root: self.word_bubbles.open_from_token(
                    -1, token, ctx, x_root, y_root, owner=popup,
                ),
                bg=SURFACE,
                fg=TEXT,
                font="LexiExample",
                justify="left",
                wrap="word",
                padx=8,
                pady=4,
            )
            english.set_sentence(f"{index}. {example.english}", example.english)
            english.pack(anchor="w", fill=tk.X, padx=(8, 4), pady=(0, 2))
            chinese = tk.Label(
                examples_view.content,
                text=f"   {example.chinese}",
                bg=SURFACE,
                fg=TEXT,
                font="LexiExample",
                justify="left",
                anchor="w",
                wraplength=REMINDER_EXAMPLES_WIDTH - 28,
            )
            chinese.pack(anchor="w", fill=tk.X, padx=(8, 4), pady=(0, 4))
            examples_view.bind_mousewheel(english, chinese)
            self._word_reminder_example_labels.append(english)
        examples_view.scroll_to_top()
        if entry.mnemonic:
            tk.Label(
                content,
                text=f"助记  {entry.mnemonic}",
                bg="#FFF1E2",
                fg="#8A531F",
                font="LexiSmall",
                wraplength=580,
                justify="left",
                padx=12,
                pady=8,
            ).pack(fill=tk.X, pady=(8, 0))

        actions = tk.Frame(popup, bg="#F7F9FA")
        actions.pack(fill=tk.X, side=tk.BOTTOM)
        action_inner = tk.Frame(actions, bg="#F7F9FA")
        action_inner.pack(fill=tk.X, padx=24, pady=18)
        self._primary_button(action_inner, "在词库查看", lambda: self._open_reminder_word(entry.word), width=10).pack(side=tk.LEFT)
        self._outline_button(action_inner, "知道了", self._dismiss_word_reminder, width=8).pack(side=tk.RIGHT)
        actions.pack_configure(before=content)
        popup.protocol("WM_DELETE_WINDOW", self._dismiss_word_reminder)
        self._center_toplevel(popup, REMINDER_POPUP_WIDTH, REMINDER_POPUP_HEIGHT)
        self._show_prepared_toplevel(popup)
        self._attach_pet_to_dialog(popup, "word-reminder")
        try:
            self.bell()
        except tk.TclError:
            pass
        popup.after(100, popup.lift)

    def _dismiss_word_reminder(self):
        was_preview = self._word_reminder_is_preview
        popup = self._word_reminder_popup
        self._word_reminder_popup = None
        self._word_reminder_examples_view = None
        self._word_reminder_example_labels = []
        self._word_reminder_is_preview = False
        if popup is not None and popup.winfo_exists():
            popup.destroy()
        if not was_preview:
            self._schedule_word_reminder()

    def _open_reminder_word(self, word: str):
        self._dismiss_word_reminder()
        self.search_var.set(word)
        self.show_page("library")
        self.deiconify()
        self.lift()

    def refresh_library(self):
        query = self.search_var.get().strip()
        if not query and self.library_group is None:
            self._show_library_view("groups")
            self._refresh_group_cards()
            return
        group = self.library_group if self.library_group is not None else "all"
        self._show_library_view("words")
        self._fill_library_words(group, query)

    def _fill_library_words(self, group: str, query: str):
        entries = self.service.words_in_group(group, query)
        for item in self.library_tree.get_children():
            self.library_tree.delete(item)
        states = {state.word_id: state for state in self.service.repository.all_review_states()}
        visible = entries[:1000]
        self.library_item_ids.clear()
        for entry in visible:
            state = states.get(entry.word_id)
            due = "未学习" if state is None else datetime.fromtimestamp(state.due_at_utc).strftime("%m-%d %H:%M")
            item_id = self.library_tree.insert("", tk.END, values=(entry.word, entry.meaning.replace("\\r", " ")[:90], entry.level, due))
            self.library_item_ids[item_id] = entry.word_id
        suffix = "（仅显示前 1,000 条）" if len(entries) > 1000 else ""
        if group == "all":
            title = "全部词条"
        else:
            title = next((item.label for item in self.service.library_groups() if item.key == group), group)
        self.library_group_title.configure(text=title)
        self.library_count.configure(text=f"找到 {len(entries):,} 条 {suffix}")

    def choose_csv(self):
        messagebox.showinfo(
            "导入标签",
            "请在 CSV 的 level 列填写 CET4、CET6 或 custom；多个词书用 | 分隔。\n"
            "tags 列也支持用 | 分隔多个标签，可对整批行填写相同标签。导入后可在词库中批量修改自定义词条。",
            parent=self,
        )
        path = filedialog.askopenfilename(title="导入 CSV v1", filetypes=[("CSV 文件", "*.csv"), ("所有文件", "*.*")])
        if not path:
            return
        report = self.service.import_csv(Path(path))
        self.refresh_library()
        self._show_import_report(report)

    def _show_import_report(self, report: ImportReport):
        dialog = tk.Toplevel(self)
        dialog.withdraw()
        dialog.title("CSV 导入结果")
        dialog.minsize(700, 420)
        dialog.configure(bg=BG)
        dialog.transient(self)
        summary = f"总行数 {report.total_rows}    成功 {report.succeeded}    跳过 {report.skipped}    失败 {report.failed}"
        tk.Label(dialog, text="CSV 导入结果", bg=BG, fg=TEXT, font="LexiTitle").pack(anchor="w", padx=24, pady=(22, 4))
        tk.Label(dialog, text=summary, bg=BG, fg=MUTED, font="LexiBody").pack(anchor="w", padx=24, pady=(0, 12))
        if report.warnings:
            tk.Label(dialog, text="；".join(report.warnings), bg="#FFF1E2", fg="#8A531F", font="LexiSmall", padx=10, pady=7).pack(fill=tk.X, padx=24, pady=(0, 10))
        frame = self._card(dialog)
        frame.pack(fill=tk.BOTH, expand=True, padx=24, pady=(0, 18))
        tree = ttk.Treeview(frame, columns=("row", "status", "field", "code", "message"), show="headings")
        for key, title, width in (("row", "行", 55), ("status", "结果", 75), ("field", "字段", 110), ("code", "错误码", 145), ("message", "说明", 330)):
            tree.heading(key, text=title)
            tree.column(key, width=width, anchor="w", stretch=key == "message")
        for issue in report.issues:
            tree.insert("", tk.END, values=(issue.row, "跳过" if issue.status == "skipped" else "失败", issue.field, issue.error_code, issue.message))
        tree.pack(fill=tk.BOTH, expand=True)
        self._primary_button(dialog, "关闭", dialog.destroy, width=9).pack(anchor="e", padx=24, pady=(0, 20))
        self._center_toplevel(dialog, 820, 500)
        self._show_prepared_toplevel(dialog)
        self._attach_pet_to_dialog(dialog, "csv-import-report")

    def batch_edit_labels(self):
        if self.library_group is None:
            self.library_group = "all"
            self.search_var.set("")
            self.refresh_library()
        selected = self.library_tree.selection()
        word_ids = {self.library_item_ids[item_id] for item_id in selected if item_id in self.library_item_ids}
        if not word_ids:
            messagebox.showinfo("批量标签", "请先在词库中选择一个或多个词条。", parent=self)
            return
        dialog = tk.Toplevel(self)
        dialog.withdraw()
        dialog.title("批量修改标签")
        dialog.configure(bg=BG)
        dialog.transient(self)
        tk.Label(dialog, text=f"已选择 {len(word_ids)} 个词条", bg=BG, fg=TEXT, font="LexiHeading").pack(anchor="w", padx=24, pady=(22, 8))
        tk.Label(dialog, text="只能操作程序内置标签；内置词库也可保留本地覆盖。", bg=BG, fg=MUTED, font="LexiSmall", wraplength=460, justify="left").pack(anchor="w", padx=24)
        add_vars: dict[str, tk.BooleanVar] = {}
        remove_vars: dict[str, tk.BooleanVar] = {}
        for title, variables in (("添加标签", add_vars), ("删除标签", remove_vars)):
            frame = tk.Frame(dialog, bg=BG)
            frame.pack(fill=tk.X, padx=24, pady=(14, 0))
            tk.Label(frame, text=title, bg=BG, fg=MUTED, font="LexiSmall").pack(side=tk.LEFT, padx=(0, 12))
            for tag in sorted(self.service.available_program_tags()):
                variable = tk.BooleanVar(value=False)
                variables[tag] = variable
                tk.Checkbutton(frame, text=tag, variable=variable, bg=BG, fg=TEXT, activebackground=BG, selectcolor=BG, font="LexiSmall", padx=0).pack(side=tk.LEFT, padx=(0, 8))
        def save():
            add = {tag for tag, variable in add_vars.items() if variable.get()}
            remove = {tag for tag, variable in remove_vars.items() if variable.get()}
            if add & remove:
                messagebox.showerror("标签有误", "同一标签不能同时添加和删除。", parent=dialog)
                return
            try:
                count = self.service.update_program_tags(word_ids, add, remove)
            except ValueError as exc:
                messagebox.showerror("标签有误", str(exc), parent=dialog)
                return
            dialog.destroy()
            self.refresh_library()
            messagebox.showinfo("批量标签", f"已更新 {count} 个词条。", parent=self)
        actions = tk.Frame(dialog, bg=BG)
        actions.pack(side=tk.BOTTOM, fill=tk.X, pady=16)
        self._primary_button(actions, "保存标签", save, width=10).pack(side=tk.RIGHT, padx=24)
        self._outline_button(actions, "取消", dialog.destroy, width=8).pack(side=tk.RIGHT)
        self._center_toplevel(dialog, 520, 330)
        self._show_prepared_toplevel(dialog)
        self._attach_pet_to_dialog(dialog, "batch-labels")

    def set_forecast_days(self, days: int):
        self.forecast_days = days
        self.refresh_analytics()

    def refresh_analytics(self):
        forecast = self.service.forecast(self.forecast_days)
        curve = self.service.retention_curve(self.forecast_days)
        total = sum(value for _, value in forecast)
        final_retention = curve[-1] if curve else 0
        self.analytics_summary.configure(text=f"到期 {total} 次 · 期末平均保持率 {final_retention:.0%}")
        self.analytics_chart.set_data(forecast, curve)
        selected = self.forecast_7_button if self.forecast_days == 7 else self.forecast_30_button
        other = self.forecast_30_button if self.forecast_days == 7 else self.forecast_7_button
        selected.configure(bg="#D8EEE7", fg=ACCENT)
        other.configure(bg=SURFACE, fg=TEXT)

    def change_font_scale(self, raw_value: object):
        # Tk invokes Scale callbacks with strings; malformed values can also
        # arrive while restoring a damaged local settings file.  Normalize
        # before any arithmetic so ``round`` and Tk font metrics never see NaN.
        # ``tk.Tk.__getattr__`` forwards unknown names into Tcl.  Reading
        # ``__dict__`` avoids that fallback while the object is still being
        # assembled (and makes this callback safe for headless tests).
        if self.__dict__.get("_font_scale_callback_active", False):
            return
        self._font_scale_callback_active = True
        try:
            scale = font_scale_from_percent(
                raw_value,
                fallback=self.service.font_scale(),
            )
            percent = round(scale * 100)
            scale_var = self.__dict__.get("scale_var")
            if scale_var is not None:
                try:
                    scale_var.set(percent)
                except (AttributeError, tk.TclError, TypeError, ValueError):
                    pass

            self.font_manager.apply(scale)
            self.minsize(960, 800 if scale >= 1.3 else 700)
            meaning_font = "LexiMeaningCompact" if scale >= 1.3 else "LexiBodyBold"
            self.study_meaning.configure(height=1, font=meaning_font)
            self.review_meaning.configure(height=1, font=meaning_font)
            self._apply_answer_text(
                self.current_card,
                self.study_meaning,
                self.example_texts,
                self.example_labels,
                max(360, self.answer_panel.winfo_width() - 80),
                max(360, self.answer_panel.winfo_width() - 80),
                preserve_examples=True,
            )
            review_card = self.review_queue[0] if self.review_queue else None
            self._apply_answer_text(
                review_card,
                self.review_meaning,
                self.review_example_texts,
                self.review_example_labels,
                max(360, self.review_answer_panel.winfo_width() - 80),
            )
            if self.answer_visible and self.answer_panel.winfo_manager():
                self.answer_panel.pack_forget()
                self.answer_panel.pack(fill=tk.BOTH, expand=True, padx=12, pady=(2, 4))
            if self.review_answer_visible and self.review_answer_panel.winfo_manager():
                self.review_answer_panel.pack_forget()
                self.review_answer_panel.pack(fill=tk.BOTH, expand=True, padx=12, pady=(2, 4))
            self.service.set_font_scale(scale)
            self.scale_text.configure(text=f"{percent:d}%")
            ttk.Style(self).configure("Treeview", rowheight=max(32, round(34 * scale)))
            if self.current_page == "dictation":
                self._render_dictation_candidates()
        finally:
            self._font_scale_callback_active = False

    def change_review_batch_size(self, raw_value: str):
        learnt_count = self.service.learnt_word_count()
        if not learnt_count:
            self.review_batch_text.configure(text="暂无已学词")
            return
        value = self.service.set_review_batch_size(round(float(raw_value)))
        self.review_batch_var.set(value)
        self.review_batch_text.configure(text=f"{value} 个单词（上限 {learnt_count}）")

    def _sync_review_batch_control(self):
        if not hasattr(self, "review_batch_scale"):
            return
        learnt_count = self.service.learnt_word_count()
        self.review_batch_scale.configure(
            to=max(1, learnt_count),
            state=tk.NORMAL if learnt_count else tk.DISABLED,
        )
        if learnt_count:
            value = min(self.service.review_batch_size(), learnt_count)
            self.review_batch_var.set(value)
            self.review_batch_text.configure(text=f"{value} 个单词（上限 {learnt_count}）")
        else:
            self.review_batch_text.configure(text="暂无已学词")


def _descendant_labels(widget: tk.Misc) -> list[tk.Label]:
    return [
        label
        for child in widget.winfo_children()
        for label in ([child] if isinstance(child, tk.Label) else []) + _descendant_labels(child)
    ]


def run_gui_smoke(app: LexiTrackApp) -> dict:
    # Smoke probes deliberately mutate controls and may reuse a data directory
    # containing due reviews.  Product confirmation dialogs require a human
    # decision and must not become part of this unattended readiness check.
    app._smoke_testing = True

    def visible_pet_count() -> int:
        overlays = [app._pet_overlay] + [
            runtime.overlay for runtime in app._dialog_pet_runtimes.values()
        ]
        count = 0
        for overlay in overlays:
            if overlay is None:
                continue
            try:
                count += int(overlay.winfo_exists() and overlay.winfo_viewable())
            except tk.TclError:
                pass
        return count

    def window_is_above(upper: tk.Misc, lower: tk.Misc) -> bool:
        try:
            return bool(app.tk.call("wm", "stackorder", str(upper), "isabove", str(lower)))
        except tk.TclError:
            return False

    def example_stack_metrics(labels: list[tk.Label], area: tk.Frame) -> tuple[list[list[int]], list[int], bool]:
        bounds = [
            [label.winfo_rooty(), label.winfo_rooty() + label.winfo_height()]
            for label in labels
        ]
        gaps = [
            bounds[index + 1][0] - bounds[index][1]
            for index in range(len(bounds) - 1)
        ]
        area_top = area.winfo_rooty()
        area_bottom = area_top + area.winfo_height()
        compact = (
            all(label.winfo_height() <= label.winfo_reqheight() + 2 for label in labels)
            and all(0 <= gap <= 8 for gap in gaps)
            and all(top >= area_top - 2 and bottom <= area_bottom + 2 for top, bottom in bounds)
            and (not bounds or bounds[0][0] <= area_top + 8)
        )
        return bounds, gaps, compact

    app.geometry("960x640")
    try:
        app.attributes("-alpha", 0.0)
    except tk.TclError:
        pass
    app.update()
    if app._pet_overlay is not None:
        try:
            app._pet_overlay.attributes("-alpha", 0.0)
        except tk.TclError:
            pass
    app._refresh_pet_targets()
    pet_overlay_ready = bool(
        app._pet_overlay is not None
        and app._pet_overlay.sprite_size == (PET_DISPLAY_SIZE, PET_DISPLAY_SIZE)
    )
    pet_motion_contract_ready = bool(
        app.pet_companion.speed == CRUISE_SPEED
        and app.pet_companion.pet_size == PET_DISPLAY_SIZE / 2.0
        and set(app._pet_images) == {PetFacing.LEFT, PetFacing.RIGHT}
        and app._pet_images.get(PetFacing.LEFT) is not app._pet_images.get(PetFacing.RIGHT)
    )
    pet_facing_assets_ready = False
    if app._pet_overlay is not None and pet_motion_contract_ready:
        app._apply_pet_facing(
            app._pet_overlay,
            replace(app.pet_companion.state, facing=PetFacing.LEFT),
        )
        left_ready = app._pet_overlay._pet_image is app._pet_images[PetFacing.LEFT]
        app._apply_pet_facing(
            app._pet_overlay,
            replace(app.pet_companion.state, facing=PetFacing.RIGHT),
        )
        right_ready = app._pet_overlay._pet_image is app._pet_images[PetFacing.RIGHT]
        pet_facing_assets_ready = left_ready and right_ready
    pet_target_kinds = {target.kind for target in app._pet_targets}
    pet_targets_ready = {
        PetTargetKind.CONTROL,
        PetTargetKind.SURFACE,
        PetTargetKind.CHART,
        PetTargetKind.EDGE,
    }.issubset(pet_target_kinds) and any(
        target.kind == PetTargetKind.CHART and target.path
        for target in app._pet_targets
    )
    chart_target_ids = {
        target.id for target in app._pet_targets if target.kind == PetTargetKind.CHART
    }
    pet_chart_border_ready = any(
        target.kind == PetTargetKind.SURFACE
        and target.id.removesuffix(":border") in chart_target_ids
        for target in app._pet_targets
    )
    edge_ids = {target.id for target in app._pet_targets if target.kind == PetTargetKind.EDGE}
    pet_edge_contract_ready = bool(
        "edge:top" not in edge_ids
        and {"edge:left", "edge:right", "edge:bottom"}.issubset(edge_ids)
    )
    pet_dialog_overlay_ready = False
    pet_dialog_focus_promotion_ready = False
    if app._pet_image is not None:
        first_dialog = tk.Toplevel(app)
        first_dialog.withdraw()
        first_dialog.configure(bg=BG)
        first_surface = app._card(first_dialog)
        first_surface.pack(fill=tk.BOTH, expand=True, padx=16, pady=16)
        app._primary_button(first_surface, "确认", lambda: None).pack(pady=50)
        app._center_toplevel(first_dialog, 360, 220)
        app._show_prepared_toplevel(first_dialog)
        app._attach_pet_to_dialog(first_dialog, "smoke-dialog-first")
        app.update_idletasks()
        app.update()
        first_runtime = app._dialog_pet_runtimes.get(first_dialog)
        first_is_only_visible_pet = bool(
            first_runtime is not None
            and first_runtime.overlay.winfo_viewable()
            and app._pet_overlay is not None
            and app._pet_overlay.state() == "withdrawn"
        )
        dialog_targets = app._collect_dialog_pet_targets(first_dialog, "smoke-dialog-first")
        dialog_viewport = app._pet_viewport_for(first_dialog)
        dialog_target_kinds = {target.kind for target in dialog_targets}
        targets_ready = bool(
            {
                PetTargetKind.CONTROL,
                PetTargetKind.SURFACE,
                PetTargetKind.EDGE,
            }.issubset(dialog_target_kinds)
            and all(
                0 <= target.rect.left <= target.rect.right <= dialog_viewport.right
                and 0 <= target.rect.top <= target.rect.bottom <= dialog_viewport.bottom
                for target in dialog_targets
            )
            and not any(target.id.endswith(":edge:top") for target in dialog_targets)
        )

        second_dialog = tk.Toplevel(app)
        second_dialog.withdraw()
        second_dialog.configure(bg=BG)
        second_surface = app._card(second_dialog)
        second_surface.pack(fill=tk.BOTH, expand=True, padx=16, pady=16)
        app._primary_button(second_surface, "继续", lambda: None).pack(pady=32)
        app._center_toplevel(second_dialog, 320, 180)
        app._show_prepared_toplevel(second_dialog)
        app._attach_pet_to_dialog(second_dialog, "smoke-dialog-second")
        app.update_idletasks()
        app.update()
        second_runtime = app._dialog_pet_runtimes.get(second_dialog)
        second_is_only_visible_pet = bool(
            first_runtime is not None
            and first_runtime.overlay.state() == "withdrawn"
            and second_runtime is not None
            and second_runtime.overlay.winfo_viewable()
            and app._pet_overlay is not None
            and app._pet_overlay.state() == "withdrawn"
            and app._dialog_pet_stack == [first_dialog, second_dialog]
        )

        first_dialog.event_generate("<FocusIn>")
        app.update_idletasks()
        app.update()
        first_focus_promoted = bool(
            first_runtime is not None
            and first_runtime.overlay.winfo_viewable()
            and second_runtime is not None
            and second_runtime.overlay.state() == "withdrawn"
            and app._dialog_pet_stack == [second_dialog, first_dialog]
            and visible_pet_count() == 1
        )
        second_dialog.event_generate("<FocusIn>")
        app.update_idletasks()
        app.update()
        second_focus_promoted = bool(
            first_runtime is not None
            and first_runtime.overlay.state() == "withdrawn"
            and second_runtime is not None
            and second_runtime.overlay.winfo_viewable()
            and app._dialog_pet_stack == [first_dialog, second_dialog]
            and visible_pet_count() == 1
        )
        pet_dialog_focus_promotion_ready = first_focus_promoted and second_focus_promoted

        second_dialog.destroy()
        app.update_idletasks()
        app.update()
        first_restored = bool(
            second_dialog not in app._dialog_pet_runtimes
            and first_runtime is not None
            and first_runtime.overlay.winfo_viewable()
            and app._pet_overlay is not None
            and app._pet_overlay.state() == "withdrawn"
            and app._dialog_pet_stack == [first_dialog]
        )

        first_dialog.destroy()
        app.update_idletasks()
        app.update()
        pet_dialog_overlay_ready = bool(
            first_is_only_visible_pet
            and targets_ready
            and second_is_only_visible_pet
            and pet_dialog_focus_promotion_ready
            and first_restored
            and first_dialog not in app._dialog_pet_runtimes
            and not app._dialog_pet_stack
            and app._pet_overlay is not None
            and app._pet_overlay.winfo_viewable()
            and first_runtime is not None
            and first_runtime.overlay.sprite_size == (PET_DISPLAY_SIZE, PET_DISPLAY_SIZE)
        )
    app.show_page("study")
    pet_navigation_ready = app.pet_companion.state.mode == PetMode.FALL
    app.update()
    visited = []
    dictation_table_ready = False
    dictation_horizontal_scrollbar_ready = False
    dictation_horizontal_scroll_sync = False
    dictation_checkbox_ready = False
    dictation_pet_target_stability_ready = False
    dictation_download_entry_ready = False
    pet_control_coverage_ready = True
    pet_control_classes_seen: set[str] = set()
    reminder_filters_ready = False
    reminder_popup_ready = False
    reminder_popup_pet_ready = False
    reminder_popup_examples_scrollable = False
    reminder_popup_wheel_scroll = False
    reminder_popup_only_examples_wheel = False
    reminder_pet_z_order_ready = False
    reminder_bubble_z_order_ready = False
    reminder_bubble_above_owner_ready = False
    reminder_word_bubble_bounds_ready = False
    original_font_scale = app.service.font_scale()
    for page in ("dashboard", "study", "review", "dictation", "library", "analytics", "reminder", "settings"):
        app.show_page(page)
        app.update()
        app._complete_dictation_loading()
        app.update()
        visited.append(page)
        app._refresh_pet_targets()
        target_ids = {target.id for target in app._pet_targets}
        for widget in app._walk_pet_widgets(app.pages[page]):
            if widget.winfo_class() not in PET_CONTROL_CLASSES:
                continue
            target = app._pet_widget_target(widget, page)
            if target is not None:
                pet_control_classes_seen.add(widget.winfo_class())
                pet_control_coverage_ready = pet_control_coverage_ready and target.id in target_ids
        if page == "library":
            app._open_library_group("all")
            app.update_idletasks()
            app.update()
            app._refresh_pet_targets()
            target_ids = {target.id for target in app._pet_targets}
            for widget in app._walk_pet_widgets(app.pages[page]):
                if widget.winfo_class() not in PET_CONTROL_CLASSES:
                    continue
                target = app._pet_widget_target(widget, page)
                if target is not None:
                    pet_control_classes_seen.add(widget.winfo_class())
                    pet_control_coverage_ready = (
                        pet_control_coverage_ready and target.id in target_ids
                    )
            app._back_to_groups()
        if page == "dictation":
            app.dictation_mode_var.set("manual")
            app.dictation_group = "all"
            app._refresh_dictation_candidates()
            app._refresh_visible_dictation_checkboxes()
            app.update_idletasks()
            app.update()
            dictation_table_ready = (
                app._dictation_table_column_widths[1] == DICTATION_MEANING_COLUMN_WIDTH
                and app._dictation_table_column_widths[3:] == [120, DICTATION_SELECTION_COLUMN_WIDTH]
                and len(app._dictation_table_column_lefts) == 5
            )
            dictation_horizontal_scrollbar_ready = (
                app.dictation_horizontal_scrollbar.winfo_manager() == "grid"
                and app.dictation_table_canvas.xview()[1] < 1.0
            )
            before_header = list(app.dictation_table_header.xview())
            before_body = list(app.dictation_table_canvas.xview())
            app._scroll_dictation_horizontally("scroll", 1, "units")
            after_header = list(app.dictation_table_header.xview())
            after_body = list(app.dictation_table_canvas.xview())
            dictation_horizontal_scroll_sync = (
                after_header[0] > before_header[0]
                and after_body[0] > before_body[0]
            )
            app._scroll_dictation_horizontally("moveto", 0)
            # The selection column is horizontally scrollable, so expose it
            # before validating its semantic targets across vertical redraws.
            app._scroll_dictation_horizontally("moveto", 1)
            app.update_idletasks()
            app.update()
            app._refresh_pet_targets()
            selection_prefix = "dictation:dictation-selection:"
            before_pet_ids = {
                target.id.removeprefix(selection_prefix): target.id
                for target in app._pet_targets
                if target.id.startswith(selection_prefix)
            }
            app._scroll_dictation_vertically("scroll", 3, "units")
            app.update_idletasks()
            app.update()
            app._refresh_pet_targets()
            app._scroll_dictation_vertically("moveto", 0)
            app.update_idletasks()
            app.update()
            # Capture the post-scroll snapshot deterministically instead of
            # depending on the next 16 ms pet tick to refresh virtualized rows.
            app._refresh_pet_targets()
            after_pet_ids = {
                target.id.removeprefix(selection_prefix): target.id
                for target in app._pet_targets
                if target.id.startswith(selection_prefix)
            }
            shared_word_ids = set(before_pet_ids) & set(after_pet_ids)
            dictation_pet_target_stability_ready = not app.dictation_candidates or (
                bool(shared_word_ids)
                and all(
                    before_pet_ids[word_id] == after_pet_ids[word_id]
                    for word_id in shared_word_ids
                )
            )
            app._scroll_dictation_horizontally("moveto", 0)
            visible_checkboxes = list(app.dictation_selection_checkboxes.values())
            dictation_checkbox_ready = not app.dictation_candidates or bool(visible_checkboxes) and all(
                int(checkbox.cget("indicatoron")) == 1
                and int(checkbox.cget("pady")) == DICTATION_CHECKBOX_PAD_Y
                and "16" in str(checkbox.cget("font"))
                and checkbox.cget("state") == tk.NORMAL
                for checkbox in visible_checkboxes
            )
            dictation_download_entry_ready = (
                callable(getattr(app, "download_dictation", None))
                and app.dictation_preview_download_button.cget("text") == "预览并下载文档"
            )
            # The smoke probe intentionally mutates editor controls. Treat
            # that synthetic state as its baseline so navigating to the next
            # page does not block forever in the real unsaved-changes dialog.
            app._dictation_saved_fingerprint = app._dictation_fingerprint()
        if page == "reminder":
            reminder_filters_ready = (
                set(app.reminder_filter_vars) == {"CET4", "CET6", "CUSTOM"}
                and all(variable.get() for variable in app.reminder_filter_vars.values())
            )
    app.show_page("review")
    app.update()
    review_header_ready = (
        app.review_start_button.winfo_width() > 0
        and app.review_summary.winfo_width() > 0
    )
    app.show_page("study")
    app.update()
    # Word-definition bubble: bilingual examples, enlarged surface, dismiss control.
    word_bubble_known_ready = False
    word_bubble_size_ready = False
    word_bubble_close_ready = False
    word_bubble_pet_ready = False
    word_bubble_pet_bounds_ready = False
    word_bubble_host_retained_ready = False
    reminder_word_bubble_owner_ready = False
    reminder_word_bubble_cleanup_ready = False
    popup: tk.Toplevel | None = None
    app.word_bubbles.open_from_token(-1, "a", "A conference in Tokyo.", 400, 300)
    for _ in range(3):
        app.update_idletasks()
        app.update()
    bubble_windows = [window for window in app.word_bubbles._windows if window.winfo_exists()]
    if bubble_windows:
        popup = bubble_windows[-1]
        label_texts = [label.cget("text") for label in _descendant_labels(popup)]
        word_bubble_size_ready = (
            abs(popup.winfo_width() - popup.winfo_reqwidth()) <= 8
            and abs(popup.winfo_height() - popup.winfo_reqheight()) <= 8
        )
        word_bubble_known_ready = sum(
            1 for text in label_texts if re.search(r"[\u3400-\u9fff]", str(text))
        ) >= 3
        word_bubble_pet_ready = bool(
            popup not in app._dialog_pet_runtimes
            and not app._dialog_pet_stack
            and app._pet_overlay is not None
            and app._pet_overlay.winfo_viewable()
            and window_is_above(app._pet_overlay, popup)
            and visible_pet_count() == 1
        )
        host_viewport = app._pet_viewport()
        half_size = PET_DISPLAY_SIZE / 2.0
        popup_rect = PetRect(
            float(popup.winfo_rootx() - app.winfo_rootx()),
            float(popup.winfo_rooty() - app.winfo_rooty()),
            float(popup.winfo_width()),
            float(popup.winfo_height()),
        )
        host_corners = (
            PetPoint(half_size, half_size),
            PetPoint(host_viewport.right - half_size, half_size),
            PetPoint(half_size, host_viewport.bottom - half_size),
            PetPoint(host_viewport.right - half_size, host_viewport.bottom - half_size),
        )
        escape_point = next(
            point for point in host_corners
            if not (
                popup_rect.left <= point.x <= popup_rect.right
                and popup_rect.top <= point.y <= popup_rect.bottom
            )
        )
        app.pet_companion.drag_start(app.pet_companion.state.position)
        escaped = app.pet_companion.drag_move(escape_point, host_viewport)
        app.pet_companion.drag_release(app._collect_pet_targets(), host_viewport)
        word_bubble_pet_bounds_ready = bool(
            escaped.position == escape_point
            and host_viewport.left + half_size <= escaped.position.x <= host_viewport.right - half_size
            and host_viewport.top + half_size <= escaped.position.y <= host_viewport.bottom - half_size
            and not (
                popup_rect.left <= escaped.position.x <= popup_rect.right
                and popup_rect.top <= escaped.position.y <= popup_rect.bottom
            )
        )
        app.word_bubbles.open_from_token(
            0,
            "conference",
            "A conference in Tokyo.",
            popup.winfo_rootx() + 120,
            popup.winfo_rooty() + 120,
            owner=popup,
        )
        # Packaged builds can create the nested window before the next timed
        # pet tick. Synchronize explicitly so this probe does not depend on
        # process speed when it verifies the active overlay's stacking order.
        app._sync_pet_overlay_visibility()
        for _ in range(2):
            app.update_idletasks()
            app.update()
        child_popup = app.word_bubbles._windows[-1]
        word_bubble_host_retained_ready = bool(
            child_popup not in app._dialog_pet_runtimes
            and popup not in app._dialog_pet_runtimes
            and not app._dialog_pet_stack
            and str(child_popup.transient()) == str(popup)
            and child_popup.master is popup
            and app._pet_overlay is not None
            and app._pet_overlay.winfo_viewable()
            and window_is_above(app._pet_overlay, child_popup)
            and visible_pet_count() == 1
        )
        app.word_bubbles._close_current(0)
        for _ in range(2):
            app.update_idletasks()
            app.update()
        word_bubble_close_ready = bool(
            not app.word_bubbles._windows
            and not app.word_bubbles.stack.frames
        )
        word_bubble_pet_ready = bool(
            word_bubble_pet_ready
            and popup not in app._dialog_pet_runtimes
            and child_popup not in app._dialog_pet_runtimes
            and not app._dialog_pet_stack
            and app._pet_overlay is not None
            and app._pet_overlay.winfo_viewable()
            and visible_pet_count() == 1
        )
    app.change_font_scale("140")
    for _ in range(3):
        app.update_idletasks()
        app.update()
    app.preview_word_reminder()
    for _ in range(3):
        app.update_idletasks()
        app.update()
    reminder_popup = app._word_reminder_popup
    reminder_examples_view = app._word_reminder_examples_view
    if reminder_popup is not None and reminder_examples_view is not None:
        reminder_popup_ready = bool(reminder_popup.winfo_exists() and reminder_examples_view.winfo_ismapped())
        reminder_pet_runtime = app._dialog_pet_runtimes.get(reminder_popup)
        reminder_pet_z_order_ready = bool(
            reminder_pet_runtime is not None
            and bool(reminder_pet_runtime.overlay.wm_attributes("-topmost"))
            and window_is_above(reminder_pet_runtime.overlay, reminder_popup)
        )
        reminder_popup_pet_ready = bool(
            reminder_pet_runtime is not None
            and reminder_pet_runtime.overlay.winfo_viewable()
            and not app.word_bubbles._windows
            and not app.word_bubbles.stack.frames
            and app._pet_overlay is not None
            and app._pet_overlay.state() == "withdrawn"
            and reminder_pet_z_order_ready
            and visible_pet_count() == 1
        )
        reminder_popup_size = [reminder_popup.winfo_width(), reminder_popup.winfo_height()]
        reminder_popup_resizable = tuple(int(value) for value in reminder_popup.resizable()) == (0, 0)
        reminder_popup_fixed_limits = (
            tuple(int(value) for value in reminder_popup.minsize())
            == (REMINDER_POPUP_WIDTH, REMINDER_POPUP_HEIGHT)
            and tuple(int(value) for value in reminder_popup.maxsize())
            == (REMINDER_POPUP_WIDTH, REMINDER_POPUP_HEIGHT)
        )
        reminder_popup_examples_scrollable = reminder_examples_view.is_scrollable()
        popup_yview_before = list(reminder_examples_view.canvas.yview())
        reminder_examples_view.canvas.event_generate("<MouseWheel>", delta=-120)
        app.update_idletasks()
        app.update()
        popup_yview_after = list(reminder_examples_view.canvas.yview())
        reminder_popup_wheel_scroll = (
            reminder_popup_examples_scrollable
            and popup_yview_after[0] > popup_yview_before[0]
        )
        reminder_popup_only_examples_wheel = (
            not bool(reminder_popup.bind("<MouseWheel>"))
            and bool(reminder_examples_view.content.bind("<MouseWheel>"))
            and bool(reminder_examples_view.bind("<MouseWheel>"))
            and all(bool(label.bind("<MouseWheel>")) for label in app._word_reminder_example_labels)
        )
        reminder_examples_view.scroll_to_top()
    else:
        reminder_popup_size = [0, 0]
        reminder_popup_resizable = False
        reminder_popup_fixed_limits = False
        popup_yview_before = []
        popup_yview_after = []
    reminder_popup_scroll_contract_ready = scroll_contract_ready(
        reminder_popup_examples_scrollable,
        reminder_popup_wheel_scroll,
        popup_yview_before,
        popup_yview_after,
    )
    if reminder_popup is not None and reminder_popup.winfo_exists():
        bubble_x = reminder_popup.winfo_rootx() + reminder_popup.winfo_width() // 2
        bubble_y = reminder_popup.winfo_rooty() + reminder_popup.winfo_height() // 2
        app.word_bubbles.open_from_token(
            -1,
            "conference",
            "A conference in Tokyo.",
            bubble_x,
            bubble_y,
            owner=reminder_popup,
        )
        for _ in range(2):
            app.update_idletasks()
            app.update()
        reminder_bubble = app.word_bubbles._windows[-1]
        reminder_pet_runtime = app._dialog_pet_runtimes.get(reminder_popup)
        if reminder_pet_runtime is not None:
            reminder_viewport = app._pet_viewport_for(reminder_popup)
            reminder_half_size = PET_DISPLAY_SIZE / 2.0
            reminder_bubble_rect = PetRect(
                float(reminder_bubble.winfo_rootx() - reminder_popup.winfo_rootx()),
                float(reminder_bubble.winfo_rooty() - reminder_popup.winfo_rooty()),
                float(reminder_bubble.winfo_width()),
                float(reminder_bubble.winfo_height()),
            )
            reminder_host_corners = (
                PetPoint(reminder_half_size, reminder_half_size),
                PetPoint(reminder_viewport.right - reminder_half_size, reminder_half_size),
                PetPoint(reminder_half_size, reminder_viewport.bottom - reminder_half_size),
                PetPoint(
                    reminder_viewport.right - reminder_half_size,
                    reminder_viewport.bottom - reminder_half_size,
                ),
            )
            reminder_escape_point = next((
                point for point in reminder_host_corners
                if not (
                    reminder_bubble_rect.left <= point.x <= reminder_bubble_rect.right
                    and reminder_bubble_rect.top <= point.y <= reminder_bubble_rect.bottom
                )
            ), None)
            if reminder_escape_point is not None:
                reminder_pet_runtime.companion.drag_start(
                    reminder_pet_runtime.companion.state.position,
                )
                reminder_escaped = reminder_pet_runtime.companion.drag_move(
                    reminder_escape_point,
                    reminder_viewport,
                )
                reminder_pet_runtime.companion.drag_release(
                    app._collect_dialog_pet_targets(reminder_popup, reminder_pet_runtime.key),
                    reminder_viewport,
                )
                reminder_word_bubble_bounds_ready = bool(
                    reminder_escaped.position == reminder_escape_point
                    and not (
                        reminder_bubble_rect.left <= reminder_escaped.position.x <= reminder_bubble_rect.right
                        and reminder_bubble_rect.top <= reminder_escaped.position.y <= reminder_bubble_rect.bottom
                    )
                )
        nested_owner_ready = bool(
            str(reminder_bubble.transient()) == str(reminder_popup)
            and reminder_bubble.master is reminder_popup
            and reminder_bubble not in app._dialog_pet_runtimes
            and reminder_pet_runtime is not None
            and reminder_pet_runtime.overlay.winfo_viewable()
            and app._dialog_pet_stack[-1:] == [reminder_popup]
            and app._pet_overlay is not None
            and app._pet_overlay.state() == "withdrawn"
            and bool(reminder_bubble.wm_attributes("-topmost"))
            and visible_pet_count() == 1
            and reminder_word_bubble_bounds_ready
        )
        reminder_bubble_above_owner_ready = window_is_above(reminder_bubble, reminder_popup)
        reminder_bubble_z_order_ready = bool(
            reminder_bubble_above_owner_ready and reminder_pet_z_order_ready
        )
        nested_owner_ready = nested_owner_ready and reminder_bubble_z_order_ready
        app.word_bubbles._close_current(0)
        for _ in range(2):
            app.update_idletasks()
            app.update()
        reminder_restored = bool(
            reminder_bubble not in app._dialog_pet_runtimes
            and not app.word_bubbles._windows
            and not app.word_bubbles.stack.frames
            and reminder_pet_runtime is not None
            and reminder_pet_runtime.overlay.winfo_viewable()
            and app._dialog_pet_stack[-1:] == [reminder_popup]
            and visible_pet_count() == 1
        )
        reminder_word_bubble_owner_ready = nested_owner_ready and reminder_restored

        # Reopen the same definition, then destroy its owner. Tk destroys the
        # child Toplevel implicitly; the manager must discard all stale frames.
        app.word_bubbles.open_from_token(
            -1,
            "conference",
            "A conference in Tokyo.",
            bubble_x,
            bubble_y,
            owner=reminder_popup,
        )
        for _ in range(2):
            app.update_idletasks()
            app.update()
        lifecycle_bubble = app.word_bubbles._windows[-1]
        lifecycle_reopened = bool(
            lifecycle_bubble.winfo_exists()
            and lifecycle_bubble not in app._dialog_pet_runtimes
            and reminder_pet_runtime is not None
            and reminder_pet_runtime.overlay.winfo_viewable()
            and app._dialog_pet_stack[-1:] == [reminder_popup]
        )
        app._dismiss_word_reminder()
        for _ in range(2):
            app.update_idletasks()
            app.update()
        reminder_word_bubble_cleanup_ready = bool(
            lifecycle_reopened
            and reminder_popup not in app._dialog_pet_runtimes
            and lifecycle_bubble not in app._dialog_pet_runtimes
            and not app.word_bubbles._windows
            and not app.word_bubbles.stack.frames
            and not app._dialog_pet_stack
            and app._pet_overlay is not None
            and app._pet_overlay.winfo_viewable()
            and visible_pet_count() == 1
        )
        reminder_popup_pet_ready = bool(
            reminder_popup_pet_ready
            and reminder_restored
            and reminder_word_bubble_cleanup_ready
        )
    else:
        app._dismiss_word_reminder()
    app.change_font_scale(str(original_font_scale * 100))
    for _ in range(3):
        app.update_idletasks()
        app.update()
    reveal_label = app.reveal_button.cget("text")
    phonetic_bottom = app.study_phonetic.winfo_rooty() + app.study_phonetic.winfo_height()
    reveal_top = app.reveal_button.winfo_rooty()
    reveal_bottom = reveal_top + app.reveal_button.winfo_height()
    card_bottom = app.study_card.winfo_rooty() + app.study_card.winfo_height()
    reveal_above_answer_area = (
        reveal_top >= phonetic_bottom - 2
        and reveal_bottom <= card_bottom + 2
    )
    app.reveal_answer()
    app.update()
    answer_top = app.answer_panel.winfo_rooty()
    answer_bottom = answer_top + app.answer_panel.winfo_height()
    answer_left = app.answer_panel.winfo_rootx()
    answer_width = app.answer_panel.winfo_width()
    answer_center = answer_left + answer_width / 2
    example_area = app.study_examples_area
    example_area_top = example_area.winfo_rooty()
    example_area_bottom = example_area_top + example_area.winfo_height()
    example_area_center = example_area.winfo_rootx() + example_area.winfo_width() / 2
    example_content_center = app.study_examples_area.winfo_rootx() + app.study_examples_area.winfo_width() / 2
    study_examples_no_scroll = not any(isinstance(widget, tk.Scrollbar) for widget in example_area.winfo_children())
    study_examples_visible = app.current_card is None or (
        example_area.winfo_manager() == "pack"
        and abs(example_area_center - answer_center) <= 3
        and all(label.winfo_manager() == "pack" and label.winfo_height() >= 24 for label in app.example_labels)
        and all(row.winfo_manager() == "grid" and row.winfo_width() > 0 for row in app.example_rows)
        and study_examples_no_scroll
    )
    example_bounds, example_gaps, examples_compact = example_stack_metrics(
        app.example_rows,
        app.study_examples_area,
    )
    examples_centered_stack = app.current_card is None or (
        all(
            row.winfo_manager() == "grid"
            and row.cget("bg") == SURFACE
            and abs(row.winfo_rootx() + row.winfo_width() / 2 - example_content_center) <= 3
            and row.winfo_width() >= app.study_examples_area.winfo_width() * 0.95
            for row in app.example_rows
        )
        and all(
            example_bounds[index][1] <= example_bounds[index + 1][0] + 2
            for index in range(len(example_bounds) - 1)
        )
    )
    rating_top = app.rating_frame.winfo_rooty()
    rating_bottom = rating_top + app.rating_frame.winfo_height()
    window_bottom = app.winfo_rooty() + app.winfo_height()
    expected_labels = ("忘记", "模糊", "认识", "很熟")
    rating_font = tkfont.nametofont("LexiBodyBold")
    rating_button_fit = all(
        button.cget("text") == label
        and button.winfo_width() >= rating_font.measure(label) + 24
        and button.winfo_height() >= rating_font.metrics("linespace") + 16
        and button.winfo_rooty() >= rating_top - 2
        and button.winfo_rooty() + button.winfo_height() <= rating_bottom + 2
        for button, label in zip(app.rating_buttons, expected_labels)
    )
    rating_buttons_visible = (
        app.rating_frame.winfo_manager() == "pack"
        and len(app.rating_buttons) == 4
        and all(button.winfo_manager() == "grid" and button.winfo_width() > 0 for button in app.rating_buttons)
        and rating_button_fit
        and rating_bottom <= card_bottom + 2
        and rating_bottom <= window_bottom + 2
    )
    examples_visible = app.current_card is None or (
        example_area_top >= answer_top - 2
        and example_area_bottom <= answer_bottom + 2
        and example_area_bottom <= rating_top + 2
        and example_area_bottom <= window_bottom + 2
    )
    example_font = tkfont.nametofont("LexiExample")
    expected_example_font_size = min(14, max(11, round(FontManager.BASE_SIZES["LexiExample"] * app.service.font_scale())))
    examples_compact = examples_compact and int(example_font.cget("size")) == expected_example_font_size
    answers_above_ratings = (
        answer_top >= phonetic_bottom - 2
        and answer_bottom <= rating_top + 2
    )
    card_center = app.study_card.winfo_rootx() + app.study_card.winfo_width() / 2
    study_header_centered = all(
        abs(widget.winfo_rootx() + widget.winfo_width() / 2 - card_center) <= 3
        for widget in (app.study_word, app.study_phonetic, app.study_meaning)
    )
    reveal_controls_hidden = app.study_controls.winfo_manager() == ""
    study_has_scrollbar = any(isinstance(widget, tk.Scrollbar) for widget in app.study_card.winfo_children())
    app.change_font_scale("140")
    for _ in range(3):
        app.update_idletasks()
        app.update()
    max_scale_font = tkfont.nametofont("LexiBodyBold")
    max_scale_rating_top = app.rating_frame.winfo_rooty()
    max_scale_rating_bottom = app.rating_frame.winfo_rooty() + app.rating_frame.winfo_height()
    max_scale_answer_top = app.answer_panel.winfo_rooty()
    max_scale_answer_bottom = app.answer_panel.winfo_rooty() + app.answer_panel.winfo_height()
    max_scale_window_bottom = app.winfo_rooty() + app.winfo_height()
    max_scale_examples_top = example_area.winfo_rooty()
    max_scale_examples_bottom = max_scale_examples_top + example_area.winfo_height()
    max_scale_example_font = tkfont.nametofont("LexiExample")
    max_scale_examples_visible = study_examples_visible
    max_scale_example_bounds, max_scale_example_gaps, max_scale_examples_compact = example_stack_metrics(
        app.example_rows,
        app.study_examples_area,
    )
    max_scale_example_bottoms = [bottom for _top, bottom in max_scale_example_bounds]
    max_scale_examples_fit = (
        max_scale_examples_top >= max_scale_answer_top - 2
        and max_scale_examples_bottom <= max_scale_answer_bottom + 2
        and max_scale_examples_bottom <= max_scale_rating_top + 2
        and max_scale_examples_bottom <= max_scale_window_bottom + 2
    )
    max_scale_button_fit = all(
        button.winfo_width() >= max_scale_font.measure(label) + 24
        and button.winfo_height() >= max_scale_font.metrics("linespace") + 16
        for button, label in zip(app.rating_buttons, expected_labels)
    )
    max_scale_layout_fit = (
        max_scale_answer_bottom <= max_scale_rating_top + 2
        and max_scale_rating_bottom <= max_scale_window_bottom + 2
        and max_scale_examples_visible
        and int(max_scale_example_font.cget("size")) == 14
    )
    app.change_font_scale(str(original_font_scale * 100))
    for _ in range(3):
        app.update_idletasks()
        app.update()

    if app.current_card is not None:
        app.rate_current(ReviewRating.GOOD)
    app.show_page("review")
    app.start_review_session()
    app.update()
    review_example_bounds: list[list[int]] = []
    review_example_gaps: list[int] = []
    review_examples_compact = False
    review_examples_clickable = False
    review_card_layout_ready = False
    review_max_scale_example_bounds: list[list[int]] = []
    review_max_scale_example_gaps: list[int] = []
    review_max_scale_layout_ready = False
    if app.review_queue:
        review_reveal_top = app.review_reveal_button.winfo_rooty()
        review_phonetic_bottom = app.review_phonetic.winfo_rooty() + app.review_phonetic.winfo_height()
        app.reveal_review_answer()
        for _ in range(3):
            app.update_idletasks()
            app.update()
        review_answer_top = app.review_answer_panel.winfo_rooty()
        review_answer_bottom = review_answer_top + app.review_answer_panel.winfo_height()
        review_answer_center = app.review_answer_panel.winfo_rootx() + app.review_answer_panel.winfo_width() / 2
        review_example_bounds, review_example_gaps, review_examples_compact = example_stack_metrics(
            app.review_example_rows,
            app.review_examples_area,
        )
        review_examples_clickable = (
            app.review_queue
            and len(app.review_example_texts) == 3
            and all(len(text._tag_tokens) > 0 for text in app.review_example_texts)
        )
        review_rating_top = app.review_rating_frame.winfo_rooty()
        review_rating_bottom = review_rating_top + app.review_rating_frame.winfo_height()
        review_card_bottom = app.review_card.winfo_rooty() + app.review_card.winfo_height()
        review_font = tkfont.nametofont("LexiBodyBold")
        review_examples_centered_stack = (
            all(
                row.winfo_manager() == "grid"
                and row.cget("bg") == SURFACE
                and abs(row.winfo_rootx() + row.winfo_width() / 2 - review_answer_center) <= 3
                for row in app.review_example_rows
            )
            and all(
                review_example_bounds[index][1] <= review_example_bounds[index + 1][0] + 2
                for index in range(len(review_example_bounds) - 1)
            )
        )
        review_buttons_fit = all(
            button.cget("text") == label
            and button.winfo_width() >= review_font.measure(label) + 24
            and button.winfo_height() >= review_font.metrics("linespace") + 16
            for button, label in zip(app.review_rating_buttons, expected_labels)
        )
        review_card_layout_ready = (
            review_reveal_top >= review_phonetic_bottom - 2
            and app.review_controls.winfo_manager() == ""
            and app.review_answer_panel.winfo_manager() == "pack"
            and review_examples_centered_stack
            and review_examples_compact
            and review_answer_bottom <= review_rating_top + 2
            and app.review_rating_frame.winfo_manager() == "pack"
            and review_rating_bottom <= review_card_bottom + 2
            and review_buttons_fit
            and not any(isinstance(widget, tk.Scrollbar) for widget in app.review_card.winfo_children())
        )
        app.change_font_scale("140")
        for _ in range(3):
            app.update_idletasks()
            app.update()
        review_max_scale_answer_top = app.review_answer_panel.winfo_rooty()
        review_max_scale_answer_bottom = review_max_scale_answer_top + app.review_answer_panel.winfo_height()
        review_max_scale_answer_center = app.review_answer_panel.winfo_rootx() + app.review_answer_panel.winfo_width() / 2
        review_max_scale_rating_top = app.review_rating_frame.winfo_rooty()
        review_max_scale_rating_bottom = review_max_scale_rating_top + app.review_rating_frame.winfo_height()
        review_max_scale_card_bottom = app.review_card.winfo_rooty() + app.review_card.winfo_height()
        review_max_scale_example_bounds, review_max_scale_example_gaps, review_max_scale_examples_compact = example_stack_metrics(
            app.review_example_rows,
            app.review_examples_area,
        )
        review_max_scale_font = tkfont.nametofont("LexiBodyBold")
        review_max_scale_example_font = tkfont.nametofont("LexiExample")
        review_max_scale_layout_ready = (
            all(
                row.winfo_manager() == "grid"
                and row.cget("bg") == SURFACE
                and abs(row.winfo_rootx() + row.winfo_width() / 2 - review_max_scale_answer_center) <= 3
                and row.winfo_height() >= 24
                for row in app.review_example_rows
            )
            and all(
                review_max_scale_example_bounds[index][1] <= review_max_scale_example_bounds[index + 1][0] + 2
                for index in range(len(review_max_scale_example_bounds) - 1)
            )
            and review_max_scale_examples_compact
            and int(review_max_scale_example_font.cget("size")) == 14
            and all(
                top >= review_max_scale_answer_top - 2 and bottom <= review_max_scale_answer_bottom + 2
                for top, bottom in review_max_scale_example_bounds
            )
            and review_max_scale_answer_bottom <= review_max_scale_rating_top + 2
            and review_max_scale_rating_bottom <= review_max_scale_card_bottom + 2
            and all(
                button.winfo_width() >= review_max_scale_font.measure(label) + 24
                and button.winfo_height() >= review_max_scale_font.metrics("linespace") + 16
                for button, label in zip(app.review_rating_buttons, expected_labels)
            )
        )
        app.change_font_scale(str(original_font_scale * 100))
        for _ in range(3):
            app.update_idletasks()
            app.update()

    result = {
        "ok": (
            set(visited) == set(app.pages)
            and reveal_label == "查看答案"
            and not study_has_scrollbar
            and reveal_above_answer_area
            and reveal_controls_hidden
            and study_header_centered
            and answers_above_ratings
            and examples_visible
            and examples_centered_stack
            and study_examples_visible
            and study_examples_no_scroll
            and rating_buttons_visible
            and max_scale_button_fit
            and max_scale_layout_fit
            and max_scale_examples_fit
            and review_header_ready
            and reminder_filters_ready
            and reminder_popup_ready
            and reminder_popup_pet_ready
            and reminder_popup_resizable
            and reminder_popup_fixed_limits
            and reminder_popup_scroll_contract_ready
            and reminder_popup_only_examples_wheel
            and review_card_layout_ready
            and review_examples_clickable
            and review_max_scale_layout_ready
            and dictation_table_ready
            and dictation_horizontal_scrollbar_ready
            and dictation_horizontal_scroll_sync
            and dictation_checkbox_ready
            and dictation_pet_target_stability_ready
            and dictation_download_entry_ready
            and pet_overlay_ready
            and pet_motion_contract_ready
            and pet_facing_assets_ready
            and pet_targets_ready
            and pet_chart_border_ready
            and pet_edge_contract_ready
            and pet_dialog_overlay_ready
            and pet_dialog_focus_promotion_ready
            and word_bubble_pet_ready
            and word_bubble_pet_bounds_ready
            and word_bubble_host_retained_ready
            and reminder_word_bubble_owner_ready
            and reminder_word_bubble_cleanup_ready
            and pet_navigation_ready
            and pet_control_coverage_ready
            and all(
                pet_control_classes_seen & alternatives
                for alternatives in (
                    {"Button", "TButton"},
                    {"Entry", "TEntry"},
                    {"Checkbutton", "TCheckbutton"},
                    {"Radiobutton", "TRadiobutton"},
                    {"Scale", "TScale"},
                    {"Spinbox", "TSpinbox"},
                    {"Scrollbar", "TScrollbar"},
                    {"Treeview"},
                )
            )
        ),
        "pages": visited,
        "dictationTableReady": dictation_table_ready,
        "dictationHorizontalScrollbarReady": dictation_horizontal_scrollbar_ready,
        "dictationHorizontalScrollSync": dictation_horizontal_scroll_sync,
        "dictationCheckboxReady": dictation_checkbox_ready,
        "dictationPetTargetStabilityReady": dictation_pet_target_stability_ready,
        "dictationDownloadEntryReady": dictation_download_entry_ready,
        "petOverlayReady": pet_overlay_ready,
        "petMotionContractReady": pet_motion_contract_ready,
        "petFacingAssetsReady": pet_facing_assets_ready,
        "petTargetsReady": pet_targets_ready,
        "petChartBorderReady": pet_chart_border_ready,
        "petEdgeContractReady": pet_edge_contract_ready,
        "petDialogOverlayReady": pet_dialog_overlay_ready,
        "petDialogFocusPromotionReady": pet_dialog_focus_promotion_ready,
        "petNavigationReady": pet_navigation_ready,
        "petControlCoverageReady": pet_control_coverage_ready,
        "petControlClasses": sorted(pet_control_classes_seen),
        "catalogCount": app.catalog_count,
        "studyCardReady": app.current_card is None or len(app.current_card.examples) >= 3,
        "fontScale": app.service.font_scale(),
        "viewport": [app.winfo_width(), app.winfo_height()],
        "revealLabel": reveal_label,
        "studyPageScrollDisabled": not study_has_scrollbar,
        "answerBounds": [answer_top, answer_bottom],
        "studyExamplesNoScroll": study_examples_no_scroll,
        "studyExamplesVisible": study_examples_visible,
        "studyExamplesAreaSize": [example_area.winfo_width(), example_area.winfo_height()],
        "exampleBounds": example_bounds,
        "exampleGaps": example_gaps,
        "examplesVisible": examples_visible,
        "examplesCompact": examples_compact,
        "examplesCenteredStack": examples_centered_stack,
        "studyHeaderCentered": study_header_centered,
        "revealAboveAnswerArea": reveal_above_answer_area,
        "revealControlsHidden": reveal_controls_hidden,
        "answersAboveRatings": answers_above_ratings,
        "ratingBounds": [app.rating_frame.winfo_rooty(), rating_bottom, card_bottom, window_bottom],
        "ratingButtonsVisible": rating_buttons_visible,
        "ratingButtonFit": rating_button_fit,
        "maxScaleButtonFit": max_scale_button_fit,
        "maxScaleLayoutFit": max_scale_layout_fit,
        "maxScaleBounds": [max_scale_answer_top, max_scale_answer_bottom, max_scale_rating_top, max_scale_rating_bottom, max_scale_window_bottom],
        "maxScaleAnswerChildren": [
            [child.winfo_name(), child.winfo_rooty(), child.winfo_height()]
            for child in app.answer_panel.winfo_children()
            if child.winfo_manager()
        ],
        "maxScaleExamplesBottom": max_scale_examples_bottom,
        "maxScaleExamplesVisible": max_scale_examples_visible,
        "maxScaleExamplesGeometry": [max_scale_examples_top, max_scale_answer_bottom, max_scale_example_font.metrics("linespace")],
        "maxScaleExampleBottoms": max_scale_example_bottoms,
        "maxScaleExampleGaps": max_scale_example_gaps,
        "maxScaleExamplesCompact": max_scale_examples_compact,
        "maxScaleExamplesFit": max_scale_examples_fit,
        "wordBubbleKnownReady": word_bubble_known_ready,
        "wordBubbleSizeReady": word_bubble_size_ready,
        "wordBubbleCloseReady": word_bubble_close_ready,
        "wordBubblePetReady": word_bubble_pet_ready,
        "wordBubblePetBoundsReady": word_bubble_pet_bounds_ready,
        "wordBubbleHostRetainedReady": word_bubble_host_retained_ready,
        "reviewHeaderReady": review_header_ready,
        "reminderFiltersReady": reminder_filters_ready,
        "reminderPopupReady": reminder_popup_ready,
        "reminderPopupPetReady": reminder_popup_pet_ready,
        "reminderPetZOrderReady": reminder_pet_z_order_ready,
        "reminderBubbleZOrderReady": reminder_bubble_z_order_ready,
        "reminderBubbleAboveOwnerReady": reminder_bubble_above_owner_ready,
        "reminderWordBubbleOwnerReady": reminder_word_bubble_owner_ready,
        "reminderWordBubbleBoundsReady": reminder_word_bubble_bounds_ready,
        "reminderWordBubbleCleanupReady": reminder_word_bubble_cleanup_ready,
        "reminderPopupSize": reminder_popup_size,
        "reminderPopupResizable": reminder_popup_resizable,
        "reminderPopupFixedLimits": reminder_popup_fixed_limits,
        "reminderPopupExamplesScrollable": reminder_popup_examples_scrollable,
        "reminderPopupWheelScroll": reminder_popup_wheel_scroll,
        "reminderPopupOnlyExamplesWheel": reminder_popup_only_examples_wheel,
        "reminderPopupYView": [popup_yview_before, popup_yview_after],
        "reviewCardLayoutReady": review_card_layout_ready,
        "reviewExamplesClickable": review_examples_clickable,
        "reviewExampleBounds": review_example_bounds,
        "reviewExampleGaps": review_example_gaps,
        "reviewExamplesCompact": review_examples_compact,
        "reviewMaxScaleLayoutReady": review_max_scale_layout_ready,
        "reviewMaxScaleExampleBounds": review_max_scale_example_bounds,
        "reviewMaxScaleExampleGaps": review_max_scale_example_gaps,
        "studyGeometry": {
            "card": [app.study_card.winfo_rooty(), card_bottom, app.study_card.winfo_height()],
            "level": [app.study_level.winfo_rooty(), app.study_level.winfo_height()],
            "word": [app.study_word.winfo_rooty(), app.study_word.winfo_height()],
            "phonetic": [app.study_phonetic.winfo_rooty(), app.study_phonetic.winfo_height()],
        },
    }
    app.destroy()
    return result
