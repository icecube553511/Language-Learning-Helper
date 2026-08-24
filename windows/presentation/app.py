from __future__ import annotations

from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import tkinter.font as tkfont

from application.services import LearningService
from domain.models import ImportReport, ReviewRating, VocabularyEntry
from presentation.widgets import MemoryChart, NavItem, ScrollableFrame, draw_icon


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
            weight = "bold" if name in {"LexiBodyBold", "LexiHeading", "LexiTitle", "LexiWord"} else "normal"
            self.fonts[name] = tkfont.Font(root=root, name=name, family=family, size=size, weight=weight)
        self.apply(scale)

    def apply(self, scale: float):
        for name, base_size in self.BASE_SIZES.items():
            self.fonts[name].configure(size=max(8, round(base_size * scale)))


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
        self.minsize(800, 560)
        self.configure(bg=BG)
        self.font_manager = FontManager(self, self.service.font_scale())
        self._configure_styles()
        self.pages: dict[str, tk.Frame] = {}
        self.nav_items: dict[str, NavItem] = {}
        self.current_page = ""
        self.current_card: VocabularyEntry | None = None
        self.answer_visible = False
        self.forecast_days = 7
        self._build_shell()
        self._build_pages()
        self._bind_shortcuts()
        self.show_page("dashboard")

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
            ("library", "词库", "library"),
            ("analytics", "记忆分析", "analytics"),
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
        self._build_library_page()
        self._build_analytics_page()
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
        self._primary_button(action_inner, "开始学习", lambda: self.show_page("study")).pack(side=tk.RIGHT)
        chart_card = self._card(body)
        chart_card.pack(fill=tk.BOTH, expand=True)
        tk.Label(chart_card, text="未来 7 天记忆负载", bg=SURFACE, fg=TEXT, font="LexiHeading").pack(anchor="w", padx=22, pady=(18, 0))
        self.dashboard_chart = MemoryChart(chart_card)
        self.dashboard_chart.pack(fill=tk.BOTH, expand=True, padx=14, pady=(4, 12))

    def _build_study_page(self):
        _, body = self._new_page("study", "学习卡", "按记忆计划优先处理到期词条")
        self.study_card = self._card(body)
        self.study_card.pack(fill=tk.BOTH, expand=True)
        study_meta = tk.Frame(self.study_card, bg=SURFACE)
        study_meta.pack(fill=tk.X, padx=16, pady=(10, 0))
        self.study_level = tk.Label(study_meta, text="", bg="#E7F5F0", fg=ACCENT, font="LexiSmall", padx=10, pady=5)
        self.study_level.pack(side=tk.LEFT)
        self.study_status = tk.Label(study_meta, text="", bg=SURFACE, fg=MUTED, font="LexiSmall")
        self.study_status.pack(side=tk.RIGHT)
        self.study_word = tk.Label(self.study_card, text="", bg=SURFACE, fg=TEXT, font="LexiWord")
        self.study_word.pack(pady=(6, 0))
        self.study_phonetic = tk.Label(self.study_card, text="", bg=SURFACE, fg=MUTED, font="LexiBody")
        self.study_phonetic.pack()
        self.answer_scroller = ScrollableFrame(self.study_card, background=SURFACE)
        self.answer_panel = self.answer_scroller.interior
        self.answer_scroller.canvas.bind("<Configure>", self._resize_study_answer, add="+")
        self.study_meaning = tk.Label(self.answer_panel, text="", bg=SURFACE, fg=TEXT, font="LexiHeading", wraplength=780, justify="center")
        self.study_meaning.pack(pady=(10, 14))
        self.example_labels: list[tk.Label] = []
        for _index in range(3):
            label = tk.Label(self.answer_panel, text="", bg="#F5F8F9", fg=TEXT, font="LexiBody", wraplength=790, justify="left", anchor="w", padx=14, pady=8)
            label.pack(fill=tk.X, padx=40, pady=4)
            self.example_labels.append(label)
        self.study_mnemonic = tk.Label(self.answer_panel, text="", bg="#FFF1E2", fg="#8A531F", font="LexiSmall", wraplength=760, padx=12, pady=7)
        controls = tk.Frame(self.study_card, bg=SURFACE, height=64)
        controls.pack(side=tk.BOTTOM, fill=tk.X, pady=(4, 6))
        controls.pack_propagate(False)
        self.reveal_button = self._primary_button(controls, "揭晓答案", self.reveal_answer)
        self.reveal_button.pack(pady=5)
        self.rating_frame = tk.Frame(controls, bg=SURFACE)
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
                width=5,
            )
            button.grid(row=0, column=column, sticky="ew", padx=4)
    def _resize_study_answer(self, event):
        wrap_width = max(260, event.width - 96)
        self.study_meaning.configure(wraplength=wrap_width)
        self.study_mnemonic.configure(wraplength=wrap_width)
        for label in self.example_labels:
            label.configure(wraplength=wrap_width)

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
        self.library_count = tk.Label(body, text="", bg=BG, fg=MUTED, font="LexiSmall")
        self.library_count.pack(anchor="w", pady=(0, 7))
        table = self._card(body)
        table.pack(fill=tk.BOTH, expand=True)
        columns = ("word", "meaning", "level", "review")
        self.library_tree = ttk.Treeview(table, columns=columns, show="headings", selectmode="browse")
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

    def _bind_shortcuts(self):
        self.bind("<Control-k>", lambda _event: self._focus_search())
        self.bind("<space>", lambda _event: self.reveal_answer() if self.current_page == "study" else None)
        for key, rating in (("1", ReviewRating.AGAIN), ("2", ReviewRating.HARD), ("3", ReviewRating.GOOD), ("4", ReviewRating.EASY)):
            self.bind(key, lambda _event, value=rating: self.rate_current(value) if self.current_page == "study" and self.answer_visible else None)

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
        elif key == "library":
            self.refresh_library()
        elif key == "analytics":
            self.refresh_analytics()

    def refresh_dashboard(self):
        snapshot = self.service.dashboard()
        for key in self.stat_labels:
            self.stat_labels[key].configure(text=f"{getattr(snapshot, key):,}")
        self.dashboard_plan.configure(text=f"{snapshot.due_now} 个到期复习，{snapshot.new_words} 个未学习词条")
        self.dashboard_chart.set_data(self.service.forecast(7), self.service.retention_curve(7))

    def load_study_card(self, exclude_id: str = ""):
        self.current_card = self.service.next_card(exclude_id=exclude_id)
        self.answer_visible = False
        self.answer_scroller.pack_forget()
        self.rating_frame.pack_forget()
        self.reveal_button.pack()
        if self.current_card is None:
            self.study_level.configure(text="已完成")
            self.study_word.configure(text="本轮学习完成")
            self.study_phonetic.configure(text="")
            self.reveal_button.configure(text="刷新", command=lambda: self.load_study_card())
            self.study_status.configure(text="当前没有到期或未学习词条")
            return
        entry = self.current_card
        self.reveal_button.configure(text="揭晓答案", command=self.reveal_answer)
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
        self.study_meaning.configure(text=entry.meaning)
        for index, label in enumerate(self.example_labels):
            example = entry.examples[index]
            label.configure(text=f"{index + 1}. {example.english}\n   {example.chinese}")
        if entry.mnemonic:
            self.study_mnemonic.configure(text=f"助记  {entry.mnemonic}")
            self.study_mnemonic.pack(pady=(8, 0))
        else:
            self.study_mnemonic.pack_forget()
        self.answer_scroller.pack(fill=tk.BOTH, expand=True, padx=(12, 6), pady=(8, 2))
        self.answer_scroller.scroll_to_top()
        self.reveal_button.pack_forget()
        self.rating_frame.pack(fill=tk.X, padx=14, pady=5)

    def rate_current(self, rating: ReviewRating):
        if self.current_card is None or not self.answer_visible:
            return
        previous = self.current_card.word_id
        self.service.rate_card(previous, rating)
        self.load_study_card(exclude_id=previous)

    def refresh_library(self):
        entries = self.service.search(self.search_var.get())
        for item in self.library_tree.get_children():
            self.library_tree.delete(item)
        states = {state.word_id: state for state in self.service.repository.all_review_states()}
        visible = entries[:1000]
        for entry in visible:
            state = states.get(entry.word_id)
            due = "未学习" if state is None else datetime.fromtimestamp(state.due_at_utc).strftime("%m-%d %H:%M")
            self.library_tree.insert("", tk.END, values=(entry.word, entry.meaning.replace("\\r", " ")[:90], entry.level, due))
        suffix = "（仅显示前 1,000 条）" if len(entries) > 1000 else ""
        self.library_count.configure(text=f"找到 {len(entries):,} 条 {suffix}")

    def choose_csv(self):
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
        self.service.set_font_scale(scale)
        self.scale_text.configure(text=f"{round(scale * 100):d}%")
        ttk.Style(self).configure("Treeview", rowheight=max(32, round(34 * scale)))


def run_gui_smoke(app: LexiTrackApp) -> dict:
    app.geometry("815x565")
    try:
        app.attributes("-alpha", 0.0)
    except tk.TclError:
        pass
    app.update()
    visited = []
    for page in ("dashboard", "study", "library", "analytics", "settings"):
        app.show_page(page)
        app.update()
        visited.append(page)
    app.show_page("study")
    app.reveal_answer()
    app.update()
    scroll_bbox = app.answer_scroller.canvas.bbox("all")
    scrollregion_ready = bool(scroll_bbox and scroll_bbox[3] > 0)
    app.answer_scroller.canvas.yview_moveto(1.0)
    app.update()
    canvas_top = app.answer_scroller.canvas.winfo_rooty()
    canvas_bottom = canvas_top + app.answer_scroller.canvas.winfo_height()
    third_top = app.example_labels[2].winfo_rooty()
    third_bottom = third_top + app.example_labels[2].winfo_height()
    third_example_reachable = (
        app.current_card is None
        or (third_bottom > canvas_top + 2 and third_top < canvas_bottom - 2)
    )
    rating_bottom = app.rating_frame.winfo_rooty() + app.rating_frame.winfo_height()
    card_bottom = app.study_card.winfo_rooty() + app.study_card.winfo_height()
    window_bottom = app.winfo_rooty() + app.winfo_height()
    rating_buttons_visible = (
        app.rating_frame.winfo_manager() == "pack"
        and len(app.rating_frame.winfo_children()) == 4
        and all(button.winfo_manager() == "grid" and button.winfo_width() > 0 for button in app.rating_frame.winfo_children())
        and rating_bottom <= card_bottom + 2
        and rating_bottom <= window_bottom + 2
    )
    answer_viewport_usable = app.answer_scroller.canvas.winfo_height() >= 120
    result = {
        "ok": (
            set(visited) == set(app.pages)
            and scrollregion_ready
            and answer_viewport_usable
            and third_example_reachable
            and rating_buttons_visible
        ),
        "pages": visited,
        "catalogCount": app.catalog_count,
        "studyCardReady": app.current_card is None or len(app.current_card.examples) >= 3,
        "fontScale": app.service.font_scale(),
        "viewport": [app.winfo_width(), app.winfo_height()],
        "answerScrollregion": list(scroll_bbox) if scroll_bbox else [],
        "answerViewport": [canvas_top, canvas_bottom, app.answer_scroller.canvas.winfo_height(), *app.answer_scroller.canvas.yview()],
        "answerViewportUsable": answer_viewport_usable,
        "thirdExampleBounds": [third_top, third_bottom, app.example_labels[2].winfo_height()],
        "thirdExampleReachable": third_example_reachable,
        "ratingBounds": [app.rating_frame.winfo_rooty(), rating_bottom, card_bottom, window_bottom],
        "ratingButtonsVisible": rating_buttons_visible,
        "studyGeometry": {
            "card": [app.study_card.winfo_rooty(), card_bottom, app.study_card.winfo_height()],
            "level": [app.study_level.winfo_rooty(), app.study_level.winfo_height()],
            "word": [app.study_word.winfo_rooty(), app.study_word.winfo_height()],
            "phonetic": [app.study_phonetic.winfo_rooty(), app.study_phonetic.winfo_height()],
        },
    }
    app.destroy()
    return result
