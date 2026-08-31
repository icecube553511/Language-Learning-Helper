from __future__ import annotations

from dataclasses import dataclass
import tkinter as tk
import tkinter.font as tkfont
from typing import Callable

from domain.pet_companion import PetPoint
from domain.word_bubbles import BubbleDefinition, BubbleStack, WordToken, normalize_token, tokenize_english


@dataclass(frozen=True)
class _TextLine:
    start: int
    end: int
    width: int


def popup_position_with_escape_corridor(
    default_x: int,
    default_y: int,
    popup_width: int,
    popup_height: int,
    screen_width: int,
    screen_height: int,
    host_bounds: tuple[int, int, int, int],
    pet_half_size: int,
) -> tuple[int, int]:
    """Keep at least one full pet sprite outside a popup when possible."""
    screen_left = 4
    screen_top = 4
    screen_right = max(screen_left, screen_width - popup_width - 8)
    screen_bottom = max(screen_top, screen_height - popup_height - 4)
    default = (
        min(max(default_x, screen_left), screen_right),
        min(max(default_y, screen_top), screen_bottom),
    )
    host_x, host_y, host_width, host_height = host_bounds
    half = max(0, pet_half_size)
    left = host_x + half
    right = max(left, host_x + host_width - half)
    top = host_y + half
    bottom = max(top, host_y + host_height - half)
    legal_corners = (
        (left, top),
        (right, top),
        (left, bottom),
        (right, bottom),
    )

    def leaves_escape(position: tuple[int, int]) -> bool:
        x, y = position
        return any(
            point_x + half <= x
            or point_x - half >= x + popup_width
            or point_y + half <= y
            or point_y - half >= y + popup_height
            for point_x, point_y in legal_corners
        )

    if leaves_escape(default):
        return default
    candidates = {
        (x, y)
        for x in (default[0], screen_left, screen_right)
        for y in (default[1], screen_top, screen_bottom)
    }
    viable = [position for position in candidates if leaves_escape(position)]
    if not viable:
        return default
    return min(
        viable,
        key=lambda position: (
            (position[0] - default[0]) ** 2 + (position[1] - default[1]) ** 2,
            position[1],
            position[0],
        ),
    )


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


def _text_block_origin(
    anchor: str,
    width: int,
    height: int,
    padx: int,
    pady: int,
    block_width: int,
    block_height: int,
) -> tuple[int, int]:
    horizontal = anchor if anchor in {"w", "e"} else anchor[-1:] if len(anchor) == 2 else ""
    vertical = anchor if anchor in {"n", "s"} else anchor[:1] if len(anchor) == 2 else ""
    block_left = (
        padx
        if horizontal == "w"
        else width - padx - block_width
        if horizontal == "e"
        else (width - block_width) // 2
    )
    block_top = (
        pady
        if vertical == "n"
        else height - pady - block_height
        if vertical == "s"
        else (height - block_height) // 2
    )
    return block_left, block_top


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


@dataclass(frozen=True)
class WordRegion:
    """Screen geometry of one rendered word, in local widget coordinates."""

    text: str
    x: int
    y: int
    width: int
    height: int


class WordClickableText(tk.Text):
    """Read-only sentence exposing each rendered word as an exact hit region.

    After ``set_sentence`` lays the text out, ``word_regions`` returns the
    on-page rectangle of every English token. ``hit_test`` uses those
    rectangles so a click always lands on the word actually rendered there,
    regardless of wrapping or font scaling.
    """

    def __init__(
        self,
        master,
        on_token,
        context: str = "",
        *,
        wrap: str = "word",
        **kwargs,
    ) -> None:
        self._justify = kwargs.pop("justify", "left")
        kwargs.setdefault("relief", tk.FLAT)
        kwargs.setdefault("borderwidth", 0)
        kwargs.setdefault("highlightthickness", 0)
        super().__init__(master, wrap=wrap, **kwargs)
        self._on_token = on_token
        self._context = context
        self._tag_tokens: list[str] = []
        self.bind("<Button-1>", self._on_click, add="+")

    def set_sentence(self, text: str, context: str | None = None, highlight_word: str | None = None) -> None:
        if context is not None:
            self._context = context
        highlight = normalize_token(highlight_word) if highlight_word else None
        self.configure(state="normal")
        self.delete("1.0", tk.END)
        self._tag_tokens = []
        cursor = 0
        for token in tokenize_english(text):
            self.insert(tk.END, text[cursor:token.start])
            tag = f"word{len(self._tag_tokens)}"
            self._tag_tokens.append(token.text)
            token_tags = [tag]
            if highlight is not None and normalize_token(token.text) == highlight:
                token_tags.append("hl")
            self.insert(tk.END, token.text, tuple(token_tags))
            cursor = token.end
        self.insert(tk.END, text[cursor:])
        self.tag_configure("align", justify=self._justify)
        self.tag_add("align", "1.0", "end-1c")
        if highlight is not None:
            bold_font = tkfont.Font(font=self.cget("font"))
            bold_font.configure(weight="bold")
            self.tag_configure("hl", foreground="#16866F", font=bold_font)
        self.update_idletasks()
        # Wrap by the widget's character width measured with its own font. This
        # is stable whether or not the widget is mapped yet, unlike
        # `count(..., "displaylines")`, which only agrees after a real layout.
        try:
            font = tkfont.Font(font=self.cget("font"))
            char_width = max(1.0, font.measure("0"))
            width_chars = max(1, int(float(self.cget("width"))))
            wrapped = _wrapped_text_lines(text, int(width_chars * char_width), font.measure)
            line_count = max(1, len(wrapped))
        except tk.TclError:
            line_count = 1
        self.configure(height=line_count)
        self.configure(state="disabled")

    def word_regions(self) -> tuple[WordRegion, ...]:
        """Return the bounding box of every rendered English word."""
        regions: list[WordRegion] = []
        for index, token in enumerate(self._tag_tokens):
            first = self.bbox(f"word{index}.first")
            last = self.bbox(f"word{index}.last")
            if first and last:
                left, top = first[0], first[1]
                right, bottom = last[0] + last[2], last[1] + last[3]
                regions.append(WordRegion(token, left, top, right - left, bottom - top))
        return tuple(regions)

    def hit_test(self, x: int, y: int) -> str | None:
        """Return the token whose rendered rectangle contains (x, y)."""
        for region in self.word_regions():
            if region.x <= x <= region.x + region.width and region.y <= y <= region.y + region.height:
                return region.text
        return None

    def _on_click(self, event):
        token = self.hit_test(event.x, event.y)
        self._on_token(token, self._context, event.x_root, event.y_root)
        return "break"


class WordBubbleManager:
    """Presentation-only controller for transient recursive vocabulary bubbles."""

    def __init__(
        self,
        root: tk.Misc,
        service,
        on_popup_created: Callable[[tk.Toplevel, str], None] | None = None,
        *,
        pet_half_size: int = 0,
    ):
        self.root = root
        self.service = service
        self._on_popup_created = on_popup_created
        self._pet_half_size = max(0, pet_half_size)
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

    def open_from_token(
        self,
        parent_depth: int,
        token_text: str | None,
        context_example: str,
        x_root: int,
        y_root: int,
        *,
        owner: tk.Misc | None = None,
    ) -> None:
        """Open a bubble from a concrete token, or clear on a blank click."""
        if token_text is None:
            if parent_depth >= 0:
                self._close_after(parent_depth)
            else:
                self.clear()
            return
        token = WordToken(token_text, 0, len(token_text))
        self._open(parent_depth, token, context_example, x_root, y_root, owner=owner)

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

    def _pet_host_window(self, owner_window: tk.Misc) -> tk.Misc:
        """Resolve recursive bubble owners back to the actual pet host."""
        current = owner_window.winfo_toplevel()
        visited: set[tk.Misc] = set()
        while current in self._windows and current not in visited:
            visited.add(current)
            master = current.master
            if master is None:
                break
            parent = master.winfo_toplevel()
            if parent is current:
                break
            current = parent
        return current

    def _on_example_click(self, event):
        widget = event.widget
        english = getattr(widget, "_word_bubble_english", "")
        context = getattr(widget, "_word_bubble_context", english)
        token = self._token_at(widget, english, event.x, event.y)
        if token is None:
            self.clear()
            return "break"
        self._open(
            -1,
            token,
            context,
            event.x_root,
            event.y_root,
            owner=widget.winfo_toplevel(),
        )
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
        block_left, block_top = _text_block_origin(
            anchor,
            width,
            height,
            padx,
            pady,
            block_width,
            block_height,
        )
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
        *,
        owner: tk.Misc | None = None,
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
        self._create_popup(
            self.stack.frames[-1].definition,
            depth,
            x_root,
            y_root,
            owner=owner,
        )

    def _destroy_from(self, depth: int) -> None:
        while self._windows and len(self._windows) > depth:
            window = self._windows.pop()
            if window.winfo_exists():
                window.destroy()

    def _create_popup(
        self,
        definition: BubbleDefinition,
        depth: int,
        x_root: int,
        y_root: int,
        *,
        owner: tk.Misc | None,
    ) -> None:
        # A proper, titled window (not an overrideredirect bubble) so it can be
        # moved/closed and stays above the main window; styled like the
        # word-learning reminder card.
        owner_window = (owner or self.root).winfo_toplevel()
        popup = tk.Toplevel(owner_window)
        popup.title("LexiTrack 词程 · 单词释义")
        popup.configure(bg="#F7F9FA")
        popup.transient(owner_window)
        try:
            popup.wm_attributes("-topmost", bool(owner_window.wm_attributes("-topmost")))
        except tk.TclError:
            pass
        popup.minsize(360, 240)
        popup.geometry("640x480")

        header = tk.Frame(popup, bg="#17212B")
        header.pack(fill=tk.X)
        title_row = tk.Frame(header, bg="#17212B")
        title_row.pack(fill=tk.X)
        tk.Label(title_row, text="单词释义", bg="#17212B", fg="#FFFFFF", font="LexiBodyBold").pack(side=tk.LEFT, padx=24, pady=(16, 2))
        tk.Label(header, text="点击例句中的英文单词可继续查看", bg="#17212B", fg="#92A0AD", font="LexiSmall").pack(anchor="w", padx=24, pady=(0, 14))

        wrap_width = 600
        example_char_width = 40
        try:
            example_char_width = max(
                1, int(wrap_width / max(1.0, tkfont.Font(font="LexiSmall").measure("0")))
            )
        except tk.TclError:
            pass
        body = tk.Frame(popup, bg="#FFFFFF")
        body.pack(fill=tk.BOTH, expand=True, padx=20, pady=14)
        body.bind("<Button-1>", lambda _event, d=depth: self._close_after(d), add="+")

        heading = tk.Label(body, text=definition.word, bg="#FFFFFF", fg="#1B2733", font="LexiWord", anchor="w")
        heading.pack(fill=tk.X, anchor="w")
        heading.bind("<Button-1>", lambda _event, d=depth: self._close_after(d), add="+")
        if definition.phonetic:
            phonetic = tk.Label(body, text=definition.phonetic, bg="#FFFFFF", fg="#65727E", font="LexiBody", anchor="w")
            phonetic.pack(fill=tk.X, anchor="w", pady=(0, 2))
            phonetic.bind("<Button-1>", lambda _event, d=depth: self._close_after(d), add="+")
        part_of_speech = tk.Label(body, text=definition.part_of_speech, bg="#FFFFFF", fg="#16866F", font="LexiSmall", anchor="w")
        part_of_speech.pack(fill=tk.X, anchor="w")
        part_of_speech.bind("<Button-1>", lambda _event, d=depth: self._close_after(d), add="+")
        meaning = tk.Label(body, text=definition.meaning, bg="#FFFFFF", fg="#1B2733", font="LexiBodyBold", wraplength=wrap_width, justify="left", anchor="w")
        meaning.pack(fill=tk.X, anchor="w", pady=(4, 10))
        meaning.bind("<Button-1>", lambda _event, d=depth: self._close_after(d), add="+")
        tk.Label(body, text="双语例句", bg="#FFFFFF", fg="#65727E", font="LexiSmall", anchor="w").pack(anchor="w", pady=(0, 2))

        example_pairs = definition.example_pairs or tuple((example, "") for example in definition.examples[:3])
        for english, chinese in example_pairs[:3]:
            sentence = WordClickableText(
                body,
                on_token=lambda token, ctx, x_root, y_root, d=depth: self.open_from_token(
                    d, token, ctx, x_root, y_root, owner=popup,
                ),
                context=english,
                bg="#FFFFFF",
                fg="#1B2733",
                font="LexiSmall",
                justify="left",
                wrap="word",
                padx=0,
                pady=2,
                cursor="hand2",
                width=example_char_width,
            )
            sentence.set_sentence(english, highlight_word=definition.word)
            sentence.pack(fill=tk.X)
            if chinese:
                translation = tk.Label(body, text=chinese, bg="#FFFFFF", fg="#65727E", font="LexiSmall", wraplength=wrap_width, justify="left", anchor="w")
                translation.pack(fill=tk.X, anchor="w", pady=(0, 3))
                translation.bind("<Button-1>", lambda _event, d=depth: self._close_after(d), add="+")

        actions = tk.Frame(popup, bg="#F7F9FA")
        actions.pack(fill=tk.X, side=tk.BOTTOM)
        actions_inner = tk.Frame(actions, bg="#F7F9FA")
        actions_inner.pack(fill=tk.X, padx=24, pady=14)
        close = tk.Button(
            actions_inner,
            text="知道了",
            command=lambda d=depth: self._close_current(d),
            bg="#16866F",
            fg="#FFFFFF",
            activebackground="#12705C",
            activeforeground="#FFFFFF",
            relief=tk.FLAT,
            bd=0,
            font="LexiBody",
            padx=18,
            pady=7,
        )
        close.pack(side=tk.RIGHT)
        popup.update_idletasks()
        # Auto-fit to the content so the meaning and every bilingual example are
        # fully visible; clamp to the screen and never go below the minimum.
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        natural_width = popup.winfo_reqwidth()
        natural_height = popup.winfo_reqheight()
        width = max(360, min(natural_width, screen_width - 16))
        height = max(240, min(natural_height, screen_height - 60))
        popup.geometry(f"{width}x{height}")
        popup.update_idletasks()
        width, height = popup.winfo_width(), popup.winfo_height()
        above = y_root - height - 8
        below = y_root + 22
        y = above if above >= 4 else min(below, screen_height - height - 4)
        x = max(4, min(x_root - width // 2, screen_width - width - 8))
        host_window = self._pet_host_window(owner_window)
        x, y = popup_position_with_escape_corridor(
            x,
            max(4, y),
            width,
            height,
            screen_width,
            screen_height,
            (
                host_window.winfo_x(),
                host_window.winfo_y(),
                host_window.winfo_width(),
                host_window.winfo_height(),
            ),
            self._pet_half_size,
        )
        popup.geometry(f"+{x}+{y}")
        popup.protocol("WM_DELETE_WINDOW", lambda d=depth: self._close_current(d))
        self._windows.append(popup)
        popup.bind(
            "<Destroy>",
            lambda event, window=popup, d=depth: self._on_popup_destroyed(event, window, d),
            add="+",
        )
        if self._on_popup_created is not None:
            self._on_popup_created(popup, f"word-bubble-{depth}")

    def _on_popup_destroyed(
        self,
        event: tk.Event,
        popup: tk.Toplevel,
        depth: int,
    ) -> None:
        """Keep the presentation stack aligned when an owner destroys a child."""
        if event.widget is not popup or popup not in self._windows:
            return
        popup_index = self._windows.index(popup)
        self._windows.pop(popup_index)
        if popup_index <= depth:
            self.stack = self.stack.close_bubble(popup_index)

    def _on_bubble_example(self, event, parent_depth: int, example: str, widget: tk.Label):
        token = self._token_at(widget, example, event.x, event.y)
        if token is not None:
            x_root = widget.winfo_rootx() + event.x
            y_root = widget.winfo_rooty() + event.y
            self._open(
                parent_depth,
                token,
                example,
                x_root,
                y_root,
                owner=widget.winfo_toplevel(),
            )
        else:
            self._close_after(parent_depth)
        return "break"

    def _close_after(self, depth: int) -> None:
        self.stack = self.stack.close_after(depth)
        self._destroy_from(depth + 1)

    def _close_current(self, depth: int) -> None:
        """Close the bubble at `depth` (and its descendants) via its dismiss control."""
        self.stack = self.stack.close_bubble(depth)
        self._destroy_from(depth)


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

    def pet_curve_points(self) -> tuple[PetPoint, ...]:
        """Return the rendered memory curve in this widget's local coordinates."""
        if len(self.curve) < 2:
            return ()
        width = max(320, self.winfo_width())
        height = max(220, self.winfo_height())
        left, right, top, bottom = 48, width - 20, 24, height - 38
        curve_step = (right - left) / max(1, len(self.curve) - 1)
        return tuple(
            PetPoint(left + index * curve_step, bottom - retention * (bottom - top))
            for index, retention in enumerate(self.curve)
        )

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


class DictationLoadingOverlay(tk.Frame):
    """Full-page overlay with an animated arc spinner for the dictation entry.

    Transient presentation state only: created on entering the dictation page and
    destroyed once the loading animation concludes. Default colours mirror the
    LexiTrack light palette so the overlay reads as part of the app.
    """

    def __init__(
        self,
        parent: tk.Misc,
        message: str = "正在准备默写词条…",
        background: str = "#F3F6F7",
        surface: str = "#FFFFFF",
        accent: str = "#16866F",
        text: str = "#1B2733",
        muted: str = "#65727E",
        border: str = "#DDE3E8",
        size: int = 56,
    ):
        super().__init__(parent, bg=background)
        self._size = size
        self._bg = background
        self._surface = surface
        self._accent = accent
        self._muted = muted
        self._border = border
        self._after_id: str | None = None
        self._angle = 0

        card = tk.Frame(self, bg=surface, highlightbackground=border, highlightthickness=1)
        card.place(relx=0.5, rely=0.5, anchor="center")
        inner = tk.Frame(card, bg=surface)
        inner.pack(padx=44, pady=30)
        self._spinner = tk.Canvas(
            inner,
            width=size,
            height=size,
            bg=surface,
            bd=0,
            highlightthickness=0,
        )
        self._spinner.pack()
        self._label = tk.Label(
            inner,
            text=message,
            bg=surface,
            fg=muted,
            font="LexiBody",
        )
        self._label.pack(pady=(14, 0))
        self._draw(0)

    def start(self) -> None:
        if self._after_id is None:
            self._after_id = self.after(80, self._tick)

    def stop(self) -> None:
        if self._after_id is not None:
            try:
                self.after_cancel(self._after_id)
            except tk.TclError:
                pass
            self._after_id = None

    def _tick(self) -> None:
        self._after_id = None
        self._angle = (self._angle + 24) % 360
        self._draw(self._angle)
        self._after_id = self.after(80, self._tick)

    def _draw(self, angle: int) -> None:
        self._spinner.delete("all")
        size = self._size
        bbox = (2, 2, size - 2, size - 2)
        self._spinner.create_arc(
            *bbox,
            start=0,
            extent=359.9,
            style=tk.ARC,
            outline=self._border,
            width=5,
        )
        self._spinner.create_arc(
            *bbox,
            start=angle,
            extent=120,
            style=tk.ARC,
            outline=self._accent,
            width=5,
        )

    def destroy(self) -> None:
        self.stop()
        super().destroy()


class PetOverlay(tk.Toplevel):
    """A stable-size transparent sprite window reporting drag gestures."""

    TRANSPARENT_KEY = "#ff00ff"

    def __init__(
        self,
        parent: tk.Misc,
        image: tk.PhotoImage,
        on_press,
        on_move,
        on_release,
        *,
        display_size: int,
    ):
        self._pet_image = image
        self._display_size = max(1, display_size)
        super().__init__(parent)
        self.withdraw()
        self.overrideredirect(True)
        self.transient(parent)
        self.configure(bg=self.TRANSPARENT_KEY, bd=0, highlightthickness=0)
        try:
            self.wm_attributes("-topmost", bool(parent.wm_attributes("-topmost")))
        except tk.TclError:
            pass
        try:
            self.wm_attributes("-transparentcolor", self.TRANSPARENT_KEY)
        except tk.TclError:
            pass
        self._sprite = tk.Label(
            self,
            image=image,
            width=self._display_size,
            height=self._display_size,
            bg=self.TRANSPARENT_KEY,
            bd=0,
            highlightthickness=0,
            relief=tk.FLAT,
            padx=0,
            pady=0,
            cursor="hand2",
        )
        self._sprite.pack(fill=tk.BOTH, expand=True)
        self._on_pet_press = on_press
        self._on_pet_move = on_move
        self._on_pet_release = on_release
        self._sprite.bind("<ButtonPress-1>", self._on_press, add="+")
        self._sprite.bind("<B1-Motion>", self._on_move, add="+")
        self._sprite.bind("<ButtonRelease-1>", self._on_release, add="+")

    @property
    def sprite_size(self) -> tuple[int, int]:
        return self._display_size, self._display_size

    def set_image(self, image: tk.PhotoImage) -> None:
        if image is self._pet_image:
            return
        self._pet_image = image
        self._sprite.configure(image=image)

    def place(self, *, x: int, y: int, width: int | None = None, height: int | None = None) -> None:
        width = width or self._display_size
        height = height or self._display_size
        root_x = self.master.winfo_rootx() + x
        root_y = self.master.winfo_rooty() + y
        self.geometry(f"{width}x{height}+{root_x}+{root_y}")
        if self.state() == "withdrawn":
            self.deiconify()

    def _on_press(self, event):
        self._on_pet_press(event)
        return "break"

    def _on_move(self, event):
        self._on_pet_move(event)
        return "break"

    def _on_release(self, event):
        self._on_pet_release(event)
        return "break"
