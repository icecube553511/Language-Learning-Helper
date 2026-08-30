from __future__ import annotations

from datetime import datetime
from dataclasses import dataclass, replace
from pathlib import Path
import random
import re
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import tkinter.font as tkfont

from application.services import LearningService
from domain.models import ImportReport, ReviewRating, VocabularyEntry
from domain.dictation import DictationField, DictationFormat, DictationOptions, MarkMode
from domain.pet_companion import (
    PetCompanion,
    PetMode,
    PetPoint,
    PetRect,
    PetState,
    PetTarget,
    PetTargetKind,
)
from presentation.widgets import (
    DictationLoadingOverlay,
    MemoryChart,
    NavItem,
    PetOverlay,
    ScrollableExamplePanel,
    WordBubbleManager,
    WordClickableText,
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


@dataclass
class DialogPetRuntime:
    key: str
    companion: PetCompanion
    overlay: PetOverlay
    drag_offset: PetPoint = PetPoint(0.0, 0.0)
    tick_after_id: str | None = None


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

    def __init__(self, root: tk.Tk, scale: float):
        self.root = root
        self.fonts: dict[str, tkfont.Font] = {}
        for name, size in self.BASE_SIZES.items():
            family = "Consolas" if name == "LexiMono" else "Microsoft YaHei UI"
            weight = "bold" if name in {"LexiBodyBold", "LexiHeading", "LexiTitle", "LexiWord", "LexiMeaningCompact"} else "normal"
            self.fonts[name] = tkfont.Font(root=root, name=name, family=family, size=size, weight=weight)
        self.apply(scale)

    def apply(self, scale: float):
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
    ):
        super().__init__()
        self.service = service
        self.data_dir = data_dir
        self.catalog_count = catalog_count
        self.catalog_rejected = catalog_rejected
        self.catalog_error = catalog_error
        self.pet_asset_path = pet_asset_path
        self.title("LexiTrack 词程")
        self.geometry("1220x800")
        self.minsize(960, 700)
        self.configure(bg=BG)
        self.font_manager = FontManager(self, self.service.font_scale())
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
        self.word_bubbles = WordBubbleManager(self, self.service, self._attach_pet_to_dialog)
        self.dictation_document = None
        self.dictation_document_word_ids: set[str] = set()
        self.dictation_selected_ids: set[str] = set()
        self._dictation_loading: DictationLoadingOverlay | None = None
        self._dictation_loading_after_id: str | None = None
        self.pet_companion = PetCompanion(PetState(PetPoint(120.0, 120.0)), speed=7.0, pet_size=28.0)
        self._pet_image_source: tk.PhotoImage | None = None
        self._pet_image: tk.PhotoImage | None = None
        self._pet_overlay: PetOverlay | None = None
        self._pet_targets: tuple[PetTarget, ...] = ()
        self._pet_refresh_after_id: str | None = None
        self._pet_tick_after_id: str | None = None
        self._pet_drag_offset = PetPoint(0.0, 0.0)
        self._build_shell()
        self._build_pages()
        self._bind_shortcuts()
        self._setup_pet_overlay()
        self.show_page("dashboard")
        self.after(1_000, self._check_review_reminder)
        self.after(250, self._schedule_word_reminder)

    def _setup_pet_overlay(self) -> None:
        """Load the injected runtime sprite and start the transient UI companion."""
        path = self.pet_asset_path
        if path is None or not path.is_file():
            return
        try:
            source = tk.PhotoImage(file=str(path))
            # The source sheet is intentionally high resolution; keep a stable
            # hit box around a small display sprite regardless of DPI scaling.
            divisor = max(1, (max(source.width(), source.height()) + 63) // 64)
            image = source.subsample(divisor, divisor)
        except (tk.TclError, OSError):
            return
        self._pet_image_source = source
        self._pet_image = image
        self.pet_companion.pet_size = max(image.width(), image.height()) / 2.0
        self._pet_overlay = PetOverlay(
            self,
            image,
            self._pet_press,
            self._pet_move,
            self._pet_release,
        )
        self._pet_overlay.place(x=0, y=0)
        self.bind("<Configure>", lambda _event: self._schedule_pet_target_refresh(), add="+")
        self._schedule_pet_target_refresh()
        self._pet_tick_after_id = self.after(50, self._pet_tick)

    def destroy(self) -> None:
        """Stop the transient pet window before tearing down the Tk root."""
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
            PetTarget(f"dialog:{key}:edge:top", PetTargetKind.EDGE, PetRect(0, 0, viewport.width, edge_size)),
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
                    state = self.pet_companion.state
                    width, height = self._pet_overlay.sprite_size
                    self._pet_overlay.place(
                        x=round(state.position.x - width / 2),
                        y=round(state.position.y - height / 2),
                        width=width,
                        height=height,
                    )
                    self._pet_overlay.lift()
                else:
                    self._pet_overlay.withdraw()
            except tk.TclError:
                pass
        for dialog, runtime in tuple(self._dialog_pet_runtimes.items()):
            try:
                if dialog is active_dialog:
                    state = runtime.companion.state
                    width, height = runtime.overlay.sprite_size
                    runtime.overlay.place(
                        x=round(state.position.x - width / 2),
                        y=round(state.position.y - height / 2),
                        width=width,
                        height=height,
                    )
                    runtime.overlay.lift()
                else:
                    runtime.overlay.withdraw()
            except tk.TclError:
                pass

    def _attach_pet_to_dialog(self, dialog: tk.Toplevel, key: str) -> None:
        """Attach a transient companion that uses only this dialog's coordinates."""
        if dialog in self._dialog_pet_runtimes or self._pet_image is None:
            return
        dialog.update_idletasks()
        half_size = max(self._pet_image.width(), self._pet_image.height()) / 2.0
        viewport = self._pet_viewport_for(dialog)
        start = viewport.clamp(PetPoint(half_size + 12.0, half_size + 12.0), half_size)
        companion = PetCompanion(PetState(start), speed=7.0, pet_size=half_size)
        runtime_holder: dict[str, DialogPetRuntime] = {}

        def pointer(event) -> PetPoint:
            return PetPoint(
                float(event.x_root - dialog.winfo_rootx()),
                float(event.y_root - dialog.winfo_rooty()),
            )

        def press(event) -> None:
            runtime = runtime_holder["runtime"]
            event_point = pointer(event)
            state = runtime.companion.state
            runtime.drag_offset = PetPoint(
                state.position.x - event_point.x,
                state.position.y - event_point.y,
            )
            runtime.companion.drag_start(state.position)

        def move(event) -> None:
            runtime = runtime_holder["runtime"]
            event_point = pointer(event)
            runtime.companion.drag_move(
                PetPoint(
                    event_point.x + runtime.drag_offset.x,
                    event_point.y + runtime.drag_offset.y,
                ),
                self._pet_viewport_for(dialog),
            )

        def release(event) -> None:
            move(event)
            runtime_holder["runtime"].companion.drag_release()

        overlay = PetOverlay(dialog, self._pet_image, press, move, release)
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
                    state = companion.tick(targets, viewport_now)
                    width, height = overlay.sprite_size
                    overlay.place(
                        x=round(state.position.x - width / 2),
                        y=round(state.position.y - height / 2),
                        width=width,
                        height=height,
                    )
                    overlay.lift()
                else:
                    overlay.withdraw()
                runtime.tick_after_id = dialog.after(50, tick)
            except tk.TclError:
                self._detach_pet_from_dialog(dialog)

        def on_destroy(event) -> None:
            if event.widget is dialog:
                self._detach_pet_from_dialog(dialog)

        dialog.bind("<Destroy>", on_destroy, add="+")
        runtime.tick_after_id = dialog.after(50, tick)

    def _detach_pet_from_dialog(self, dialog: tk.Toplevel) -> None:
        runtime = self._dialog_pet_runtimes.pop(dialog, None)
        if runtime is None:
            return
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
            PetTarget("edge:top", PetTargetKind.EDGE, PetRect(0, 0, viewport.width, edge_size)),
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

    def _pet_tick(self) -> None:
        self._pet_tick_after_id = None
        overlay = self._pet_overlay
        if overlay is None:
            return
        try:
            if self._dialog_pet_stack:
                overlay.withdraw()
                self._pet_tick_after_id = self.after(50, self._pet_tick)
                return
            # Geometry can change without resizing the root (scrolling, lazy rows,
            # pack/forget), so animation consumes a fresh visible target snapshot.
            self._pet_targets = self._collect_pet_targets()
            state = self.pet_companion.tick(self._pet_targets, self._pet_viewport())
            width, height = overlay.sprite_size
            overlay.place(
                x=round(state.position.x - width / 2),
                y=round(state.position.y - height / 2),
                width=width,
                height=height,
            )
            overlay.lift()
            self._pet_tick_after_id = self.after(50, self._pet_tick)
        except tk.TclError:
            self._pet_tick_after_id = None

    def _pet_pointer(self, event) -> PetPoint:
        return PetPoint(
            float(event.x_root - self.winfo_rootx()),
            float(event.y_root - self.winfo_rooty()),
        )

    def _pet_press(self, event) -> None:
        pointer = self._pet_pointer(event)
        state = self.pet_companion.state
        self._pet_drag_offset = PetPoint(state.position.x - pointer.x, state.position.y - pointer.y)
        self.pet_companion.drag_start(state.position)

    def _pet_move(self, event) -> None:
        pointer = self._pet_pointer(event)
        self.pet_companion.drag_move(
            PetPoint(pointer.x + self._pet_drag_offset.x, pointer.y + self._pet_drag_offset.y),
            self._pet_viewport(),
        )

    def _pet_release(self, event) -> None:
        pointer = self._pet_pointer(event)
        self.pet_companion.drag_move(
            PetPoint(pointer.x + self._pet_drag_offset.x, pointer.y + self._pet_drag_offset.y),
            self._pet_viewport(),
        )
        self.pet_companion.drag_release()

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
                lambda value=rating: self.rate_current(value),
                color=color,
                width=8,
            )
            button.grid(row=0, column=column, sticky="nsew", padx=6, pady=0)
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
                lambda value=rating: self.rate_review_current(value),
                color=color,
                width=8,
            )
            button.grid(row=0, column=column, sticky="nsew", padx=6, pady=0)
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

        level_row = tk.Frame(inner, bg=SURFACE)
        level_row.pack(fill=tk.X, pady=(0, 9))
        tk.Label(level_row, text="词库", bg=SURFACE, fg=MUTED, font="LexiSmall").pack(side=tk.LEFT, padx=(0, 8))
        self.dictation_level_vars: dict[str, tk.BooleanVar] = {}
        for value, label in (("CET4", "四级"), ("CET6", "六级"), ("CUSTOM", "自定义")):
            variable = tk.BooleanVar(value=True)
            self.dictation_level_vars[value] = variable
            tk.Checkbutton(
                level_row, text=label, variable=variable, command=self._refresh_dictation_candidates,
                bg=SURFACE, fg=TEXT, activebackground=SURFACE, selectcolor=SURFACE,
                font="LexiSmall", padx=0,
            ).pack(side=tk.LEFT, padx=(0, 8))

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
        self.dictation_status = tk.Label(actions, text="", bg=SURFACE, fg=MUTED, font="LexiSmall")
        self.dictation_status.pack(side=tk.LEFT, padx=14)

        selection = self._card(body)
        selection.pack(fill=tk.BOTH, expand=True)
        tk.Label(selection, text="手选词条", bg=SURFACE, fg=TEXT, font="LexiHeading").pack(anchor="w", padx=16, pady=(13, 2))
        self.dictation_selection_count = tk.Label(selection, text="随机模式不需要手选", bg=SURFACE, fg=MUTED, font="LexiSmall")
        self.dictation_selection_count.pack(anchor="w", padx=16, pady=(0, 8))
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

    def _dictation_levels(self) -> set[str]:
        selected = {level for level, variable in self.dictation_level_vars.items() if variable.get()}
        return selected or set(self.dictation_level_vars)

    def _refresh_dictation_candidates(self):
        if not hasattr(self, "dictation_table_canvas"):
            return
        self.dictation_candidates = self.service.dictation_pool(
            self._dictation_levels(),
            self.dictation_include_evaluated_var.get(),
        )[:2000]
        self.dictation_selected_ids = visible_dictation_selection(
            self.dictation_selected_ids,
            self.dictation_candidates,
        )
        self._render_dictation_candidates()
        self._update_dictation_selection_count()

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
        self.dictation_table_canvas.yview_moveto(0)
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
        # Column separator lines only within the drawn band.
        canvas.delete("dictation_separator")
        for left in column_lefts[1:]:
            canvas.create_line(left, 0, left, self._dictation_body_height, fill=BORDER, tags=("dictation_separator",))
        self._refresh_visible_dictation_checkboxes()

    def _scroll_dictation_horizontally(self, *args):
        self.dictation_table_header.xview(*args)
        self.dictation_table_canvas.xview(*args)

    def _scroll_dictation_vertically(self, *args):
        self.dictation_table_canvas.yview(*args)
        self._schedule_dictation_rows()

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
        selection_center = (
            self._dictation_table_column_lefts[4]
            + self._dictation_table_column_widths[4] / 2
        )
        for index, row_top in enumerate(self._dictation_table_row_tops):
            row_height = self._dictation_table_row_heights[index]
            if row_top + row_height < viewport_top - row_height or row_top > viewport_bottom + row_height:
                continue
            entry = self.dictation_candidates[index]
            selected = entry.word_id in self.dictation_selected_ids
            background = "#E2F1EC" if selected else ("#F8FAFB" if index % 2 else SURFACE)
            variable = tk.BooleanVar(value=selected)
            checkbox = tk.Checkbutton(
                self.dictation_table_canvas,
                variable=variable,
                command=lambda word_id=entry.word_id, value=variable: self._set_dictation_selected(word_id, value.get()),
                bg=background,
                activebackground=background,
                selectcolor=SURFACE,
                state=tk.NORMAL if manual else tk.DISABLED,
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
        if self.dictation_mode_var.get() != "manual":
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
        if self.dictation_mode_var.get() != "manual":
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
            self._set_dictation_selected(target.word_id, anchor_selected)
        return "break"

    def _set_dictation_selected(self, word_id: str, selected: bool):
        if selected:
            self.dictation_selected_ids.add(word_id)
        else:
            self.dictation_selected_ids.discard(word_id)
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

    def _update_dictation_selection_count(self):
        if self.dictation_mode_var.get() == "manual":
            self.dictation_selection_count.configure(text=f"已选择 {len(self.dictation_selected_ids)} 个词条")
        else:
            self.dictation_selection_count.configure(text="随机模式不需要手选")

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
                if len(self.dictation_selected_ids) < count and not self._confirm_manual_dictation(len(self.dictation_selected_ids), count):
                    return
                selected_entries = self.service.selected_dictation_candidates(
                    self.dictation_selected_ids,
                    self._dictation_levels(),
                    self.dictation_include_evaluated_var.get(),
                )
                document = self.service.build_dictation_document(
                    options, word_ids=self.dictation_selected_ids,
                    levels=self._dictation_levels(),
                    include_evaluated=self.dictation_include_evaluated_var.get(),
                    entries=selected_entries,
                )
            else:
                selected_entries = self.service.dictation_candidates(
                    count, self._dictation_levels(), self.dictation_include_evaluated_var.get(),
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
        dialog.title("确认选择")
        dialog.geometry("430x170")
        dialog.configure(bg=BG)
        dialog.transient(self)
        dialog.grab_set()
        tk.Label(dialog, text=f"当前仅选择了{selected_count}/{requested_count}，是否确定选择", bg=BG, fg=TEXT, font="LexiBodyBold", wraplength=380).pack(padx=20, pady=(28, 18))
        result = {"value": False}
        buttons = tk.Frame(dialog, bg=BG)
        buttons.pack()
        def finish(value):
            result["value"] = value
            dialog.destroy()
        self._primary_button(buttons, "确定选择", lambda: finish(True), width=10).pack(side=tk.LEFT, padx=6)
        self._outline_button(buttons, "返回选择", lambda: finish(False), width=10).pack(side=tk.LEFT, padx=6)
        self._attach_pet_to_dialog(dialog, "dictation-confirm")
        self.wait_window(dialog)
        return result["value"]

    def _open_dictation_preview(self, document):
        preview = tk.Toplevel(self)
        preview.title("默写预览 · A4 portrait")
        preview.geometry("720x780")
        preview.minsize(620, 620)
        preview.configure(bg=BG)
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
        dialog.title("标记默写词条")
        dialog.geometry("420x205")
        dialog.configure(bg=BG)
        dialog.transient(self)
        dialog.grab_set()
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
        self._attach_pet_to_dialog(dialog, "dictation-mark")
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
        _, body = self._new_page("library", "词库", "CET-4、CET-6 与自定义词条")
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
        tk.Label(body, text="导入 CSV 时填写 level（CET4/CET6/custom，可用 | 分隔）和 tags（用 | 分隔）；词库列表支持批量修改自定义词条。", bg=BG, fg=MUTED, font="LexiSmall", anchor="w").pack(fill=tk.X, pady=(0, 7))
        self.library_count = tk.Label(body, text="", bg=BG, fg=MUTED, font="LexiSmall")
        self.library_count.pack(anchor="w", pady=(0, 7))
        table = self._card(body)
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
        self.scale_var = tk.DoubleVar(value=self.service.font_scale() * 100)
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
        self.bind("<space>", lambda _event: self._reveal_current_answer())
        for key, rating in (("1", ReviewRating.AGAIN), ("2", ReviewRating.HARD), ("3", ReviewRating.GOOD), ("4", ReviewRating.EASY)):
            self.bind(key, lambda _event, value=rating: self._rate_visible_card(value))

    def _focus_search(self):
        self.show_page("library")
        self.after_idle(self.search_entry.focus_set)

    def show_page(self, key: str):
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

    def rate_current(self, rating: ReviewRating):
        if self.current_card is None or not self.answer_visible:
            return
        previous = self.current_card.word_id
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
        card = self.review_queue[0]
        self.review_answer_visible = True
        self._apply_answer_text(card, self.review_meaning, self.review_example_texts, self.review_example_labels, max(360, self.review_answer_panel.winfo_width() - 80))
        self.review_controls.pack_forget()
        self.review_rating_frame.pack(side=tk.BOTTOM, fill=tk.X, padx=14, pady=(2, 4))
        self.review_answer_panel.pack(fill=tk.BOTH, expand=True, padx=12, pady=(2, 4))

    def rate_review_current(self, rating: ReviewRating):
        if not self.review_queue or not self.review_answer_visible:
            return
        card = self.review_queue.pop(0)
        self.service.rate_review_card(card.word_id, rating)
        self._show_next_review_card()

    def _reveal_current_answer(self):
        if self.current_page == "study":
            self.reveal_answer()
        elif self.current_page == "review":
            self.reveal_review_answer()

    def _rate_visible_card(self, rating: ReviewRating):
        if self.current_page == "study" and self.answer_visible:
            self.rate_current(rating)
        elif self.current_page == "review" and self.review_answer_visible:
            self.rate_review_current(rating)

    def _check_review_reminder(self):
        due_count = self.service.due_review_count()
        if due_count > 0 and due_count != self._last_reminded_due_count:
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
        self._word_reminder_popup = popup
        popup.title("LexiTrack 词程 · 单词提醒")
        popup.geometry(f"{REMINDER_POPUP_WIDTH}x{REMINDER_POPUP_HEIGHT}")
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
                    -1, token, ctx, x_root, y_root,
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
        entries = self.service.search(self.search_var.get())
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
        dialog.title("CSV 导入结果")
        dialog.geometry("820x500")
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
        self._attach_pet_to_dialog(dialog, "csv-import-report")

    def batch_edit_labels(self):
        selected = self.library_tree.selection()
        word_ids = {self.library_item_ids[item_id] for item_id in selected if item_id in self.library_item_ids}
        if not word_ids:
            messagebox.showinfo("批量标签", "请先在词库中选择一个或多个词条。", parent=self)
            return
        dialog = tk.Toplevel(self)
        dialog.title("批量修改标签")
        dialog.geometry("520x330")
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

    def change_font_scale(self, raw_value: str):
        scale = min(1.4, max(0.9, float(raw_value) / 100.0))
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
        self.scale_text.configure(text=f"{round(scale * 100):d}%")
        ttk.Style(self).configure("Treeview", rowheight=max(32, round(34 * scale)))
        if self.current_page == "dictation":
            self._render_dictation_candidates()

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
        and app._pet_overlay.sprite_size[0] > 0
        and app._pet_overlay.sprite_size[1] > 0
    )
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
    pet_dialog_overlay_ready = False
    if app._pet_image is not None:
        first_dialog = tk.Toplevel(app)
        first_dialog.geometry("360x220")
        first_dialog.configure(bg=BG)
        first_surface = app._card(first_dialog)
        first_surface.pack(fill=tk.BOTH, expand=True, padx=16, pady=16)
        app._primary_button(first_surface, "确认", lambda: None).pack(pady=50)
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
        )

        second_dialog = tk.Toplevel(app)
        second_dialog.geometry("320x180")
        second_dialog.configure(bg=BG)
        second_surface = app._card(second_dialog)
        second_surface.pack(fill=tk.BOTH, expand=True, padx=16, pady=16)
        app._primary_button(second_surface, "继续", lambda: None).pack(pady=32)
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
            and first_restored
            and first_dialog not in app._dialog_pet_runtimes
            and not app._dialog_pet_stack
            and app._pet_overlay is not None
            and app._pet_overlay.winfo_viewable()
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
        if page == "dictation":
            app.dictation_mode_var.set("manual")
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
        bubble_pet_runtime = app._dialog_pet_runtimes.get(popup)
        word_bubble_pet_ready = bool(
            bubble_pet_runtime is not None
            and bubble_pet_runtime.overlay.winfo_viewable()
        )
        app.word_bubbles._close_current(0)
        for _ in range(2):
            app.update_idletasks()
            app.update()
        word_bubble_close_ready = not any(window.winfo_exists() for window in app.word_bubbles._windows)
        word_bubble_pet_ready = word_bubble_pet_ready and popup not in app._dialog_pet_runtimes
        app.word_bubbles.clear()
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
        reminder_popup_pet_ready = bool(
            reminder_pet_runtime is not None
            and reminder_pet_runtime.overlay.winfo_viewable()
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
    app._dismiss_word_reminder()
    reminder_popup_pet_ready = (
        reminder_popup_pet_ready
        and reminder_popup not in app._dialog_pet_runtimes
    )
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
            and pet_targets_ready
            and pet_chart_border_ready
            and pet_dialog_overlay_ready
            and word_bubble_pet_ready
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
        "petTargetsReady": pet_targets_ready,
        "petChartBorderReady": pet_chart_border_ready,
        "petDialogOverlayReady": pet_dialog_overlay_ready,
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
        "reviewHeaderReady": review_header_ready,
        "reminderFiltersReady": reminder_filters_ready,
        "reminderPopupReady": reminder_popup_ready,
        "reminderPopupPetReady": reminder_popup_pet_ready,
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
