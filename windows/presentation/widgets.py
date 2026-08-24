from __future__ import annotations

import tkinter as tk


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


class ScrollableFrame(tk.Frame):
    def __init__(self, parent, background: str = "#FFFFFF"):
        super().__init__(parent, bg=background)
        self.canvas = tk.Canvas(
            self,
            bg=background,
            bd=0,
            highlightthickness=0,
            takefocus=True,
        )
        self.scrollbar = tk.Scrollbar(
            self,
            orient=tk.VERTICAL,
            command=self.canvas.yview,
            width=14,
        )
        self.interior = tk.Frame(self.canvas, bg=background)
        self.window_id = self.canvas.create_window((0, 0), window=self.interior, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.interior.bind("<Configure>", self._sync_scrollregion)
        self.canvas.bind("<Configure>", self._sync_width)
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel, add="+")
        self.canvas.bind("<Prior>", lambda _event: self.canvas.yview_scroll(-1, "pages"))
        self.canvas.bind("<Next>", lambda _event: self.canvas.yview_scroll(1, "pages"))
        self.canvas.bind("<Home>", lambda _event: self.canvas.yview_moveto(0.0))
        self.canvas.bind("<End>", lambda _event: self.canvas.yview_moveto(1.0))

    def _sync_scrollregion(self, _event=None):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _sync_width(self, event):
        self.canvas.itemconfigure(self.window_id, width=event.width)

    def _on_mousewheel(self, event):
        pointer_x = self.canvas.winfo_pointerx()
        pointer_y = self.canvas.winfo_pointery()
        left = self.canvas.winfo_rootx()
        top = self.canvas.winfo_rooty()
        if not (
            left <= pointer_x <= left + self.canvas.winfo_width()
            and top <= pointer_y <= top + self.canvas.winfo_height()
        ):
            return None
        units = -1 if event.delta > 0 else 1
        self.canvas.yview_scroll(units * 3, "units")
        return "break"

    def scroll_to_top(self):
        self.canvas.yview_moveto(0.0)


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
