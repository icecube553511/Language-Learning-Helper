from __future__ import annotations

from datetime import datetime
from pathlib import Path
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import tkinter.font as tkfont

from application.services import LearningService
from domain.models import ImportReport, ReviewRating, VocabularyEntry
from presentation.widgets import MemoryChart, NavItem, draw_icon


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
    ):
        super().__init__()
        self.service = service
        self.data_dir = data_dir
        self.catalog_count = catalog_count
        self.catalog_rejected = catalog_rejected
        self.catalog_error = catalog_error
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
        self._word_reminder_is_preview = False
        self._word_reminder_previous_id = ""
        self._word_reminder_next_at = 0.0
        self.answer_visible = False
        self.forecast_days = 7
        self._build_shell()
        self._build_pages()
        self._bind_shortcuts()
        self.show_page("dashboard")
        self.after(1_000, self._check_review_reminder)
        self.after(250, self._schedule_word_reminder)

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
        self.example_labels: list[tk.Label] = []
        for index in range(3):
            row = tk.Frame(examples_area, bg=SURFACE)
            row.grid(row=index, column=0, sticky="ew", pady=2)
            label = tk.Label(
                row,
                text="",
                bg=SURFACE,
                fg=TEXT,
                font="LexiExample",
                wraplength=680,
                justify="center",
                anchor="center",
                padx=4,
                pady=0,
            )
            label.pack(fill=tk.BOTH, expand=True)
            self.example_labels.append(label)
        self.study_mnemonic = tk.Label(self.answer_panel, text="", bg="#FFF1E2", fg="#8A531F", font="LexiSmall", wraplength=760, padx=12, pady=7)

    def _build_review_page(self):
        _, body = self._new_page("review", "复习", "按记忆权重巩固已经学习过的单词")
        toolbar = tk.Frame(body, bg=BG)
        toolbar.pack(fill=tk.X, pady=(0, 10))
        self.review_toolbar = toolbar
        self.review_summary = tk.Label(toolbar, text="", bg=BG, fg=MUTED, font="LexiBody")
        self.review_summary.pack(side=tk.LEFT)
        self.review_filter_vars = self._build_level_filters(toolbar, "复习", self.service.review_levels, self._save_review_levels, inline=True)
        self.review_start_button = self._primary_button(toolbar, "开始复习", self.start_review_session, width=10)
        self.review_start_button.pack(side=tk.RIGHT)
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
        self.review_example_labels: list[tk.Label] = []
        for index in range(3):
            row = tk.Frame(examples_area, bg=SURFACE)
            row.grid(row=index, column=0, sticky="ew", pady=2)
            label = tk.Label(row, text="", bg=SURFACE, fg=TEXT, font="LexiExample", wraplength=680, justify="center", anchor="center", padx=4, pady=0)
            label.pack(fill=tk.BOTH, expand=True)
            self.review_example_labels.append(label)
        self.refresh_review_page()

    def _resize_study_answer(self, event):
        wrap_width = max(360, event.width - 80)
        self.study_meaning.configure(wraplength=wrap_width)
        self.study_mnemonic.configure(wraplength=wrap_width)
        self._apply_answer_text(self.current_card, self.study_meaning, self.example_labels, wrap_width)

    def _resize_review_answer(self, event):
        wrap_width = max(360, event.width - 80)
        self.review_meaning.configure(wraplength=wrap_width)
        card = self.review_queue[0] if self.review_queue else None
        self._apply_answer_text(card, self.review_meaning, self.review_example_labels, wrap_width)

    def _elide_line(self, text: str, font_name: str, width: int) -> str:
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
        return text[:low].rstrip() + suffix

    def _apply_answer_text(
        self,
        card: VocabularyEntry | None,
        meaning_label: tk.Label,
        example_labels: list[tk.Label],
        width: int,
    ) -> None:
        if card is None:
            return
        meaning = card.meaning
        if int(meaning_label.cget("height")) == 1:
            meaning = self._elide_line(meaning, meaning_label.cget("font"), width)
        meaning_label.configure(text=meaning)
        for index, label in enumerate(example_labels):
            example = card.examples[index]
            english = self._elide_line(f"{index + 1}. {example.english}", label.cget("font"), width)
            chinese = self._elide_line(example.chinese, label.cget("font"), width)
            label.configure(text=f"{english}\n{chinese}", wraplength=width)

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
        elif key == "library":
            self.refresh_library()
        elif key == "analytics":
            self.refresh_analytics()
        elif key == "reminder":
            self._refresh_word_reminder_status()

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
        self._apply_answer_text(entry, self.study_meaning, self.example_labels, max(360, self.answer_panel.winfo_width() - 80))
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
        elif not self.review_toolbar.winfo_manager():
            self.review_toolbar.pack(fill=tk.X, pady=(0, 10), before=self.review_card)
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
        self.review_answer_visible = False
        self.review_answer_panel.pack_forget()
        self.review_rating_frame.pack_forget()
        self.review_controls.pack_forget()
        self.review_reveal_button.pack_forget()
        if not self.review_queue:
            self.refresh_review_page()
            return
        self.review_toolbar.pack_forget()
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
        self._apply_answer_text(card, self.review_meaning, self.review_example_labels, max(360, self.review_answer_panel.winfo_width() - 80))
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
        popup.geometry("680x760")
        popup.minsize(620, 700)
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
        for index, example in enumerate(entry.examples[:3], start=1):
            tk.Label(
                content,
                text=f"{index}. {example.english}\n   {example.chinese}",
                bg=SURFACE,
                fg=TEXT,
                font="LexiExample",
                wraplength=610,
                justify="left",
            ).pack(anchor="w", fill=tk.X, pady=(0, 4))
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
        try:
            self.bell()
        except tk.TclError:
            pass
        popup.after(100, popup.lift)

    def _dismiss_word_reminder(self):
        was_preview = self._word_reminder_is_preview
        popup = self._word_reminder_popup
        self._word_reminder_popup = None
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

    def batch_edit_labels(self):
        selected = self.library_tree.selection()
        word_ids = {self.library_item_ids[item_id] for item_id in selected if item_id in self.library_item_ids}
        if not word_ids:
            messagebox.showinfo("批量标签", "请先在词库中选择一个或多个自定义词条。", parent=self)
            return
        dialog = tk.Toplevel(self)
        dialog.title("批量修改标签")
        dialog.geometry("480x270")
        dialog.configure(bg=BG)
        dialog.transient(self)
        tk.Label(dialog, text=f"已选择 {len(word_ids)} 个词条", bg=BG, fg=TEXT, font="LexiHeading").pack(anchor="w", padx=24, pady=(22, 8))
        tk.Label(dialog, text="仅对自定义词条生效；level 可填 CET4、CET6、custom 或用 | 分隔多个词书。", bg=BG, fg=MUTED, font="LexiSmall", wraplength=420, justify="left").pack(anchor="w", padx=24)
        form = tk.Frame(dialog, bg=BG)
        form.pack(fill=tk.X, padx=24, pady=16)
        tk.Label(form, text="level", bg=BG, fg=MUTED, font="LexiSmall").grid(row=0, column=0, sticky="w", pady=6)
        level_var = tk.StringVar(value="custom")
        tk.Entry(form, textvariable=level_var, font="LexiBody", width=32).grid(row=0, column=1, padx=10, sticky="w")
        tk.Label(form, text="tags", bg=BG, fg=MUTED, font="LexiSmall").grid(row=1, column=0, sticky="w", pady=6)
        tags_var = tk.StringVar()
        tk.Entry(form, textvariable=tags_var, font="LexiBody", width=32).grid(row=1, column=1, padx=10, sticky="w")
        def save():
            levels = {item.strip().upper() for item in level_var.get().replace(",", "|").split("|") if item.strip()}
            if not levels or not levels.issubset({"CET4", "CET6", "CUSTOM"}):
                messagebox.showerror("标签有误", "level 只能包含 CET4、CET6、custom。", parent=dialog)
                return
            count = self.service.update_entry_labels(word_ids, "/".join(sorted(levels)), {item.strip() for item in tags_var.get().split("|") if item.strip()})
            dialog.destroy()
            self.refresh_library()
            messagebox.showinfo("批量标签", f"已更新 {count} 个自定义词条。", parent=self)
        self._primary_button(dialog, "保存标签", save, width=10).pack(side=tk.RIGHT, padx=24, pady=12)
        self._outline_button(dialog, "取消", dialog.destroy, width=8).pack(side=tk.RIGHT, pady=12)

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
            self.example_labels,
            max(360, self.answer_panel.winfo_width() - 80),
        )
        review_card = self.review_queue[0] if self.review_queue else None
        self._apply_answer_text(
            review_card,
            self.review_meaning,
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
    visited = []
    reminder_filters_ready = False
    for page in ("dashboard", "study", "review", "library", "analytics", "reminder", "settings"):
        app.show_page(page)
        app.update()
        visited.append(page)
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
    example_bounds, example_gaps, examples_compact = example_stack_metrics(
        app.example_labels,
        app.study_examples_area,
    )
    examples_centered_stack = app.current_card is None or (
        all(
            label.winfo_manager() == "pack"
            and label.cget("bg") == SURFACE
            and label.cget("justify") == "center"
            and label.cget("anchor") == "center"
            and abs(label.winfo_rootx() + label.winfo_width() / 2 - answer_center) <= 3
            and label.winfo_width() >= answer_width * 0.65
            for label in app.example_labels
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
    examples_visible = app.current_card is None or all(
        top >= answer_top - 2 and bottom <= answer_bottom + 2 and bottom <= window_bottom + 2
        for top, bottom in example_bounds
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
    original_font_scale = app.service.font_scale()
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
    max_scale_examples_top = app.study_examples_area.winfo_rooty()
    max_scale_examples_bottom = max_scale_examples_top + app.study_examples_area.winfo_height()
    max_scale_example_font = tkfont.nametofont("LexiExample")
    max_scale_examples_visible = all(
        label.winfo_height() >= 24
        for label in app.example_labels
    )
    max_scale_example_bounds, max_scale_example_gaps, max_scale_examples_compact = example_stack_metrics(
        app.example_labels,
        app.study_examples_area,
    )
    max_scale_example_bottoms = [bottom for _top, bottom in max_scale_example_bounds]
    max_scale_examples_fit = all(bottom <= max_scale_answer_bottom + 2 for bottom in max_scale_example_bottoms)
    max_scale_button_fit = all(
        button.winfo_width() >= max_scale_font.measure(label) + 24
        and button.winfo_height() >= max_scale_font.metrics("linespace") + 16
        for button, label in zip(app.rating_buttons, expected_labels)
    )
    max_scale_layout_fit = (
        max_scale_answer_bottom <= max_scale_rating_top + 2
        and max_scale_rating_bottom <= max_scale_window_bottom + 2
        and max_scale_examples_visible
        and max_scale_examples_compact
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
            app.review_example_labels,
            app.review_examples_area,
        )
        review_rating_top = app.review_rating_frame.winfo_rooty()
        review_rating_bottom = review_rating_top + app.review_rating_frame.winfo_height()
        review_card_bottom = app.review_card.winfo_rooty() + app.review_card.winfo_height()
        review_font = tkfont.nametofont("LexiBodyBold")
        review_examples_centered_stack = (
            all(
                label.winfo_manager() == "pack"
                and label.cget("bg") == SURFACE
                and label.cget("justify") == "center"
                and label.cget("anchor") == "center"
                and abs(label.winfo_rootx() + label.winfo_width() / 2 - review_answer_center) <= 3
                for label in app.review_example_labels
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
            app.review_example_labels,
            app.review_examples_area,
        )
        review_max_scale_font = tkfont.nametofont("LexiBodyBold")
        review_max_scale_example_font = tkfont.nametofont("LexiExample")
        review_max_scale_layout_ready = (
            all(
                label.winfo_manager() == "pack"
                and label.cget("bg") == SURFACE
                and label.cget("justify") == "center"
                and abs(label.winfo_rootx() + label.winfo_width() / 2 - review_max_scale_answer_center) <= 3
                and label.winfo_height() >= 24
                for label in app.review_example_labels
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
            and examples_compact
            and examples_centered_stack
            and rating_buttons_visible
            and max_scale_button_fit
            and max_scale_layout_fit
            and max_scale_examples_fit
            and review_header_ready
            and reminder_filters_ready
            and review_card_layout_ready
            and review_max_scale_layout_ready
        ),
        "pages": visited,
        "catalogCount": app.catalog_count,
        "studyCardReady": app.current_card is None or len(app.current_card.examples) >= 3,
        "fontScale": app.service.font_scale(),
        "viewport": [app.winfo_width(), app.winfo_height()],
        "revealLabel": reveal_label,
        "studyScrollDisabled": not study_has_scrollbar,
        "answerBounds": [answer_top, answer_bottom],
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
        "reviewHeaderReady": review_header_ready,
        "reminderFiltersReady": reminder_filters_ready,
        "reviewCardLayoutReady": review_card_layout_ready,
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
