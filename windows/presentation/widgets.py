from __future__ import annotations

from dataclasses import dataclass
import tkinter as tk
import tkinter.font as tkfont
from typing import Callable

from domain.word_bubbles import BubbleDefinition, BubbleStack, WordToken


@dataclass(frozen=True)
class _TextLine:
    start: int
    end: int
    width: int


def _wrapped_text_lines(text: str, max_width: int, measure: Callable[[str], int]) -> tuple[_TextLine, ...]:
    """Approximate Tk label word wrapping while retaining source offsets."""
    lines: list[_TextLine] = []
    paragraph_start = 0
    for paragraph in text.split("\n"):
        paragraph_end = paragraph_start + len(paragraph)
        if not paragraph:
            lines.append(_TextLine(paragraph_start, paragraph_start, 0))
        cursor = paragraph_start
        while cursor < paragraph_end:
            end = cursor
            while end < paragraph_end and measure(text[cursor:end + 1]) <= max_width:
                end += 1
            if end == paragraph_end:
                lines.append(_TextLine(cursor, end, measure(text[cursor:end])))
                break
            if end == cursor:
                end += 1
            whitespace = max(
                (index for index in range(cursor + 1, end + 1) if text[index - 1].isspace()),
                default=-1,
            )
            line_end = whitespace - 1 if whitespace >= 0 else end
            while line_end > cursor and text[line_end - 1].isspace():
                line_end -= 1
            if line_end == cursor:
                line_end = end
            lines.append(_TextLine(cursor, line_end, measure(text[cursor:line_end])))
            cursor = whitespace if whitespace >= 0 else end
            while cursor < paragraph_end and text[cursor].isspace():
                cursor += 1
        paragraph_start = paragraph_end + 1
    return tuple(lines)


def _hit_test_lines(
    tokens: tuple[WordToken, ...],
    lines: tuple[_TextLine, ...],
    measure: Callable[[str], int],
    text: str,
    x: int,
    y: int,
    block_left: int,
    block_top: int,
    block_width: int,
    line_height: int,
    justify: str,
    source_offset: int = 0,
) -> WordToken | None:
    if line_height <= 0 or y < block_top:
        return None
    line_index = (y - block_top) // line_height
    if line_index >= len(lines):
        return None
    line = lines[line_index]
    if justify == "left":
        line_left = block_left
    elif justify == "right":
        line_left = block_left + block_width - line.width
    else:
        line_left = block_left + (block_width - line.width) // 2
    for token in tokens:
        start = source_offset + token.start
        end = source_offset + token.end
        if line.start <= start and end <= line.end:
            left = line_left + measure(text[line.start:start])
            right = line_left + measure(text[line.start:end])
            if left - 2 <= x <= right + 2:
                return token
    return None


class Tooltip:
    def __init__(self, widget: tk.Widget, text: str):
        self.widget = widget
        self.text = text
        self.window: tk.Toplevel | None = None
        self.pending: str | None = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")

    def _schedule(self, _event=None):
        self.pending = self.widget.after(450, self._show)

    def _show(self):
        if self.window is not None:
            return
        x = self.widget.winfo_rootx() + self.widget.winfo_width() + 8
        y = self.widget.winfo_rooty() + 4
        self.window = tk.Toplevel(self.widget)
        self.window.overrideredirect(True)
        self.window.geometry(f"+{x}+{y}")
        tk.Label(
            self.window,
            text=self.text,
            bg="#17212B",
            fg="#FFFFFF",
            font="LexiSmall",
            padx=9,
            pady=6,
        ).pack()

    def _hide(self, _event=None):
        if self.pending:
            self.widget.after_cancel(self.pending)
            self.pending = None
        if self.window is not None:
            self.window.destroy()
            self.window = None


class WordBubbleManager:
    """Presentation-only controller for transient recursive vocabulary bubbles."""

    def __init__(self, root: tk.Misc, service):
        self.root = root
        self.service = service
        self.stack = BubbleStack()
        self._windows: list[tk.Toplevel] = []
        self._bound_widgets: set[tk.Widget] = set()
        root.bind_all("<Button-1>", self._on_global_click, add="+")

    def bind_example(self, widget: tk.Label, english: str, context_example: str = "") -> None:
        widget._word_bubble_english = english  # type: ignore[attr-defined]
        widget._word_bubble_context = context_example  # type: ignore[attr-defined]
        widget.configure(cursor="hand2")
        if widget not in self._bound_widgets:
            widget.bind("<Button-1>", self._on_example_click, add="+")
            self._bound_widgets.add(widget)

    def clear(self) -> None:
        self.stack = self.stack.close_all()
        self._destroy_from(0)

    def _on_global_click(self, event) -> None:
        widget = event.widget
        if any(self._is_descendant(widget, window) for window in self._windows):
            return
        self.clear()

    @staticmethod
    def _is_descendant(widget: tk.Widget, parent: tk.Widget) -> bool:
        current: tk.Widget | None = widget
        while current is not None:
            if current == parent:
                return True
            current = current.master
        return False

    def _on_example_click(self, event):
        widget = event.widget
        english = getattr(widget, "_word_bubble_english", "")
        context = getattr(widget, "_word_bubble_context", english)
        token = self._token_at(widget, english, event.x, event.y)
        if token is None:
            self.clear()
            return "break"
        self._open(-1, token, context, event.x_root, event.y_root)
        return "break"

    def _token_at(self, widget: tk.Label, text: str, x: int, y: int) -> WordToken | None:
        tokens = self.service.example_tokens(text)
        if not tokens:
            return None
        displayed_text = str(widget.cget("text"))
        source_offset = displayed_text.find(text)
        if source_offset < 0:
            return None
        font = widget.cget("font")
        try:
            measured = tkfont.Font(font=font)
        except tk.TclError:
            return None
        width = widget.winfo_width()
        height = widget.winfo_height()
        padx = int(float(widget.cget("padx")))
        pady = int(float(widget.cget("pady")))
        wrap_length = int(float(widget.cget("wraplength")))
        content_width = max(1, width - padx * 2)
        max_width = min(content_width, wrap_length) if wrap_length > 0 else content_width
        lines = _wrapped_text_lines(displayed_text, max_width, measured.measure)
        block_width = max((line.width for line in lines), default=0)
        line_height = measured.metrics("linespace")
        block_height = line_height * len(lines)
        anchor = str(widget.cget("anchor"))
        block_left = padx if "w" in anchor else width - padx - block_width if "e" in anchor else (width - block_width) // 2
        block_top = pady if "n" in anchor else height - pady - block_height if "s" in anchor else (height - block_height) // 2
        return _hit_test_lines(
            tokens,
            lines,
            measured.measure,
            displayed_text,
            x,
            y,
            block_left,
            block_top,
            block_width,
            line_height,
            str(widget.cget("justify")),
            source_offset,
        )

    def _open(
        self,
        parent_depth: int,
        token: WordToken,
        context: str,
        x_root: int,
        y_root: int,
    ) -> None:
        definition = self.service.word_bubble(token.text, context)
        previous = self.stack
        if parent_depth < 0:
            self.stack = self.stack.open_root(definition)
            depth = 0
        else:
            self.stack = self.stack.open_child(parent_depth, definition)
            depth = len(self.stack.frames) - 1
        if self.stack == previous:
            return
        self._destroy_from(depth)
        if not self.stack.frames:
            return
        self._create_popup(self.stack.frames[-1].definition, depth, x_root, y_root)

    def _destroy_from(self, depth: int) -> None:
        while len(self._windows) > depth:
            window = self._windows.pop()
            if window.winfo_exists():
                window.destroy()

    def _create_popup(self, definition: BubbleDefinition, depth: int, x_root: int, y_root: int) -> None:
        popup = tk.Toplevel(self.root)
        popup.overrideredirect(True)
        popup.configure(bg="#B8C5CC")
        popup.transient(self.root.winfo_toplevel())
        shell = tk.Frame(popup, bg="#FFFFFF", highlightbackground="#B8C5CC", highlightthickness=1)
        shell.pack(padx=1, pady=1)
        shell.bind("<Button-1>", lambda _event, d=depth: self._close_after(d), add="+")
        heading = tk.Label(shell, text=definition.word, bg="#FFFFFF", fg="#1B2733", font="LexiBodyBold", anchor="w")
        heading.pack(fill=tk.X, padx=12, pady=(9, 1))
        heading.bind("<Button-1>", lambda _event, d=depth: self._close_after(d), add="+")
        part_of_speech = tk.Label(shell, text=definition.part_of_speech, bg="#FFFFFF", fg="#16866F", font="LexiSmall", anchor="w")
        part_of_speech.pack(fill=tk.X, padx=12)
        part_of_speech.bind("<Button-1>", lambda _event, d=depth: self._close_after(d), add="+")
        meaning = tk.Label(shell, text=definition.meaning, bg="#FFFFFF", fg="#1B2733", font="LexiBody", wraplength=320, justify="left", anchor="w")
        meaning.pack(fill=tk.X, padx=12, pady=(2, 7))
        meaning.bind("<Button-1>", lambda _event, d=depth: self._close_after(d), add="+")
        for example in definition.examples[:3]:
            label = tk.Label(shell, text=example, bg="#FFFFFF", fg="#1B2733", font="LexiSmall", wraplength=320, justify="left", anchor="w", cursor="hand2")
            label.pack(fill=tk.X, padx=12, pady=(0, 4))
            self.bind_example(label, example, example)
            label.unbind("<Button-1>")
            label.bind("<Button-1>", lambda event, d=depth, item=example, target=label: self._on_bubble_example(event, d, item, target), add="+")
        popup.update_idletasks()
        width, height = popup.winfo_width(), popup.winfo_height()
        above = y_root - height - 8
        below = y_root + 22
        screen_height = self.root.winfo_screenheight()
        y = above if above >= 4 else min(below, screen_height - height - 4)
        x = max(4, min(x_root - width // 2, self.root.winfo_screenwidth() - width - 8))
        popup.geometry(f"+{x}+{max(4, y)}")
        self._windows.append(popup)

    def _on_bubble_example(self, event, parent_depth: int, example: str, widget: tk.Label):
        token = self._token_at(widget, example, event.x, event.y)
        if token is not None:
            x_root = widget.winfo_rootx() + event.x
            y_root = widget.winfo_rooty() + event.y
            self._open(parent_depth, token, example, x_root, y_root)
        else:
            self._close_after(parent_depth)
        return "break"

    def _close_after(self, depth: int) -> None:
        self.stack = self.stack.close_after(depth)
        self._destroy_from(depth + 1)


def draw_icon(canvas: tk.Canvas, name: str, color: str) -> None:
    canvas.delete("all")
    line = {"fill": color, "width": 2, "capstyle": tk.ROUND, "joinstyle": tk.ROUND}
    if name == "dashboard":
        canvas.create_rectangle(4, 4, 12, 12, outline=color, width=2)
        canvas.create_rectangle(16, 4, 24, 12, outline=color, width=2)
        canvas.create_rectangle(4, 16, 12, 24, outline=color, width=2)
        canvas.create_rectangle(16, 16, 24, 24, outline=color, width=2)
    elif name == "study":
        canvas.create_line(4, 7, 11, 6, 14, 9, 17, 6, 24, 7, **line)
        canvas.create_line(4, 7, 4, 23, 11, 22, 14, 25, **line)
        canvas.create_line(24, 7, 24, 23, 17, 22, 14, 25, **line)
        canvas.create_line(14, 9, 14, 25, **line)
    elif name == "review":
        canvas.create_arc(5, 5, 23, 23, start=35, extent=270, style=tk.ARC, outline=color, width=2)
        canvas.create_line(20, 4, 24, 5, 23, 9, **line)
        canvas.create_line(10, 14, 13, 17, 19, 10, **line)
    elif name == "library":
        canvas.create_rectangle(4, 5, 9, 24, outline=color, width=2)
        canvas.create_rectangle(11, 7, 16, 24, outline=color, width=2)
        canvas.create_polygon(18, 6, 22, 5, 25, 23, 21, 24, fill="", outline=color, width=2)
    elif name == "analytics":
        canvas.create_line(4, 24, 24, 24, **line)
        canvas.create_rectangle(6, 15, 10, 23, outline=color, width=2)
        canvas.create_rectangle(13, 10, 17, 23, outline=color, width=2)
        canvas.create_rectangle(20, 5, 24, 23, outline=color, width=2)
    elif name == "settings":
        canvas.create_oval(9, 9, 19, 19, outline=color, width=2)
        canvas.create_oval(12, 12, 16, 16, outline=color, width=2)
        for x1, y1, x2, y2 in ((14, 3, 14, 8), (14, 20, 14, 25), (3, 14, 8, 14), (20, 14, 25, 14), (6, 6, 9, 9), (19, 19, 22, 22), (22, 6, 19, 9), (9, 19, 6, 22)):
            canvas.create_line(x1, y1, x2, y2, **line)
    elif name == "search":
        canvas.create_oval(4, 4, 18, 18, outline=color, width=2)
        canvas.create_line(17, 17, 25, 25, **line)
    elif name == "upload":
        canvas.create_line(14, 22, 14, 5, **line)
        canvas.create_line(8, 11, 14, 5, 20, 11, **line)
        canvas.create_line(5, 18, 5, 24, 23, 24, 23, 18, **line)
    elif name == "clock":
        canvas.create_oval(4, 4, 24, 24, outline=color, width=2)
        canvas.create_line(14, 8, 14, 14, 19, 17, **line)
    elif name == "edit":
        canvas.create_line(7, 22, 21, 8, **line)
        canvas.create_line(6, 24, 10, 23, **line)
        canvas.create_line(20, 5, 23, 8, **line)


class NavItem(tk.Frame):
    def __init__(self, parent, label: str, icon: str, command):
        super().__init__(parent, bg="#17212B", cursor="hand2", height=50)
        self.label_text = label
        self.icon_name = icon
        self.command = command
        self.icon = tk.Canvas(self, width=28, height=28, bg="#17212B", bd=0, highlightthickness=0)
        self.icon.pack(side=tk.LEFT, padx=(18, 10))
        self.label = tk.Label(self, text=label, bg="#17212B", fg="#D9E0E6", font="LexiBody", cursor="hand2")
        self.label.pack(side=tk.LEFT)
        self.pack_propagate(False)
        for widget in (self, self.icon, self.label):
            widget.bind("<Button-1>", lambda _event: self.command())
        self.set_selected(False)
        Tooltip(self.icon, label)

    def set_selected(self, selected: bool):
        background = "#244035" if selected else "#17212B"
        foreground = "#54C8AA" if selected else "#D9E0E6"
        self.configure(bg=background)
        self.icon.configure(bg=background)
        self.label.configure(bg=background, fg=foreground, font="LexiBodyBold" if selected else "LexiBody")
        draw_icon(self.icon, self.icon_name, foreground)


class ScrollableExamplePanel(tk.Frame):
    VIEWPORT_WIDTH = 640
    VIEWPORT_HEIGHT = 140

    def __init__(
        self,
        parent,
        background: str,
        border: str,
        viewport_width: int = VIEWPORT_WIDTH,
        viewport_height: int = VIEWPORT_HEIGHT,
    ):
        self.viewport_width = viewport_width
        self.viewport_height = viewport_height
        super().__init__(
            parent,
            bg=background,
            width=viewport_width,
            height=viewport_height,
            highlightbackground=border,
            highlightthickness=1,
        )
        self.pack_propagate(False)
        self.canvas = tk.Canvas(
            self,
            bg=background,
            bd=0,
            highlightthickness=0,
            yscrollincrement=12,
        )
        self.scrollbar = tk.Scrollbar(
            self,
            orient=tk.VERTICAL,
            command=self.canvas.yview,
            width=12,
            bd=0,
            relief=tk.FLAT,
            troughcolor="#EEF2F4",
            bg="#B7C2CA",
            activebackground="#8D9AA5",
        )
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.content = tk.Frame(self.canvas, bg=background)
        self._content_window = self.canvas.create_window((0, 0), window=self.content, anchor="nw")
        self.content.bind("<Configure>", self._sync_scroll_region, add="+")
        self.canvas.bind("<Configure>", self._sync_content_width, add="+")
        self.bind_mousewheel(self, self.canvas, self.content, self.scrollbar)

    def _sync_scroll_region(self, _event=None):
        bounds = self.canvas.bbox("all")
        if bounds is not None:
            self.canvas.configure(scrollregion=bounds)

    def _sync_content_width(self, event):
        self.canvas.itemconfigure(self._content_window, width=event.width)

    def bind_mousewheel(self, *widgets: tk.Widget) -> None:
        for widget in widgets:
            widget.bind("<MouseWheel>", self._on_mousewheel, add="+")

    def _on_mousewheel(self, event):
        if event.delta:
            units = max(1, abs(event.delta) // 120)
            direction = -1 if event.delta > 0 else 1
            self.canvas.yview_scroll(direction * units, "units")
        return "break"

    def available_text_width(self) -> int:
        canvas_width = self.canvas.winfo_width()
        if canvas_width <= 1:
            canvas_width = self.viewport_width - int(self.scrollbar.cget("width"))
        return max(360, canvas_width - 24)

    def scroll_to_top(self) -> None:
        self.canvas.yview_moveto(0.0)

    def is_scrollable(self) -> bool:
        bounds = self.canvas.bbox("all")
        return bool(bounds and bounds[3] - bounds[1] > self.canvas.winfo_height())


class MemoryChart(tk.Canvas):
    def __init__(self, parent, **kwargs):
        super().__init__(parent, bg="#FFFFFF", bd=0, highlightthickness=0, height=260, **kwargs)
        self.forecast: list[tuple[str, int]] = []
        self.curve: list[float] = []
        self.bind("<Configure>", lambda _event: self.redraw())

    def set_data(self, forecast: list[tuple[str, int]], curve: list[float]):
        self.forecast = forecast
        self.curve = curve
        self.redraw()

    def redraw(self):
        self.delete("all")
        width = max(320, self.winfo_width())
        height = max(220, self.winfo_height())
        left, right, top, bottom = 48, width - 20, 24, height - 38
        self.create_line(left, bottom, right, bottom, fill="#BAC4CC", width=1)
        self.create_line(left, top, left, bottom, fill="#BAC4CC", width=1)
        if not self.forecast:
            self.create_text(width / 2, height / 2, text="暂无已排期的复习", fill="#65727E", font="LexiBody")
            return
        maximum = max(1, max(value for _, value in self.forecast))
        step = (right - left) / max(1, len(self.forecast))
        bar_width = max(2, step * 0.58)
        for index, (day, value) in enumerate(self.forecast):
            x = left + step * index + step / 2
            bar_height = (bottom - top) * value / maximum
            self.create_rectangle(x - bar_width / 2, bottom - bar_height, x + bar_width / 2, bottom, fill="#BFE6DA", outline="")
            if index in (0, len(self.forecast) - 1) or (len(self.forecast) > 10 and index % 7 == 0):
                self.create_text(x, bottom + 14, text=day[5:], fill="#65727E", font="LexiChart")
        if self.curve:
            points = []
            curve_step = (right - left) / max(1, len(self.curve) - 1)
            for index, retention in enumerate(self.curve):
                points.extend((left + index * curve_step, bottom - retention * (bottom - top)))
            if len(points) >= 4:
                self.create_line(*points, fill="#3973C6", width=3, smooth=True)
        self.create_text(left, 9, text=f"每日到期数  最大 {maximum}", anchor="w", fill="#65727E", font="LexiChart")
        self.create_text(right, 9, text="蓝线：平均保持率", anchor="e", fill="#3973C6", font="LexiChart")
