from __future__ import annotations

import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk
from tkinter.scrolledtext import ScrolledText

from .cleanup import (
    cleanup_selected_targets,
    deep_clean_system,
    delete_leftover_candidates,
    open_in_explorer,
    scan_cleanup_targets,
    scan_leftover_candidates,
)
from .assets import asset_path
from .models import (
    ActionResult,
    CleanupTarget,
    DeepCleanResult,
    LeftoverCandidate,
    PerformanceSnapshot,
    ProcessEntry,
)
from .monitor import get_performance_snapshot, get_processes, prime_counters, terminate_process
from .tray_icon import SystemTrayController
from .utils import format_bytes, format_datetime, format_percent, format_uptime

BACKGROUND = "#0D1521"
SURFACE = "#132033"
SURFACE_ALT = "#182840"
SURFACE_SOFT = "#223553"
BORDER = "#2A3E5A"
TEXT = "#F5F8FC"
MUTED = "#9DB0C8"
ACCENT = "#36C88B"
ACCENT_HOVER = "#28A974"
ACCENT_DARK = "#1E7C58"
INFO = "#53A8FF"
INFO_HOVER = "#2B87E6"
WARNING = "#F6BC52"
WARNING_HOVER = "#D7982A"
ERROR = "#EF6C6C"
ERROR_HOVER = "#D65252"


def make_button(
    parent: tk.Widget,
    text: str,
    command,
    kind: str = "secondary",
    width: int | None = None,
) -> tk.Button:
    palettes = {
        "primary": (ACCENT, ACCENT_HOVER, "#FFFFFF"),
        "secondary": (SURFACE_SOFT, "#2A4265", TEXT),
        "info": (INFO, INFO_HOVER, "#FFFFFF"),
        "warning": (WARNING, WARNING_HOVER, "#1A1408"),
        "danger": (ERROR, ERROR_HOVER, "#FFFFFF"),
    }
    base, hover, foreground = palettes[kind]
    button = tk.Button(
        parent,
        text=text,
        command=command,
        bg=base,
        fg=foreground,
        activebackground=hover,
        activeforeground=foreground,
        relief="flat",
        bd=0,
        highlightthickness=0,
        padx=16,
        pady=10,
        cursor="hand2",
        font=("Segoe UI Semibold", 10),
        width=width,
    )
    button.normal_bg = base
    button.hover_bg = hover
    button.bind("<Enter>", lambda _event, btn=button: _button_set_hover(btn, True))
    button.bind("<Leave>", lambda _event, btn=button: _button_set_hover(btn, False))
    return button


def _button_set_hover(button: tk.Button, hovered: bool) -> None:
    if str(button["state"]) == "disabled":
        return
    button.configure(bg=button.hover_bg if hovered else button.normal_bg)


class Panel(tk.Frame):
    def __init__(self, parent: tk.Widget, title: str, subtitle: str = "") -> None:
        super().__init__(
            parent,
            bg=SURFACE,
            highlightthickness=1,
            highlightbackground=BORDER,
            bd=0,
        )
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        header = tk.Frame(self, bg=SURFACE)
        header.grid(row=0, column=0, sticky="ew", padx=16, pady=(14, 8))
        header.columnconfigure(0, weight=1)

        tk.Label(
            header,
            text=title,
            bg=SURFACE,
            fg=TEXT,
            font=("Segoe UI Semibold", 13),
        ).grid(row=0, column=0, sticky="w")

        if subtitle:
            tk.Label(
                header,
                text=subtitle,
                bg=SURFACE,
                fg=MUTED,
                font=("Segoe UI", 9),
            ).grid(row=1, column=0, sticky="w", pady=(3, 0))

        self.body = tk.Frame(self, bg=SURFACE)
        self.body.grid(row=1, column=0, sticky="nsew", padx=16, pady=(0, 16))
        self.body.columnconfigure(0, weight=1)


class QuickPanel(tk.Toplevel):
    def __init__(self, app: "CleanerApp") -> None:
        super().__init__(app)
        self.app = app
        self.process_entries: dict[str, ProcessEntry] = {}
        self.withdraw()
        self.transient(app)
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.resizable(False, False)
        try:
            self.wm_attributes("-toolwindow", True)
        except Exception:
            pass
        self.configure(bg=BORDER)
        self.geometry("430x540")
        self.bind("<Escape>", lambda _event: self.hide())
        self.bind("<FocusOut>", self._on_focus_out)

        shell = tk.Frame(self, bg=SURFACE, highlightthickness=1, highlightbackground=BORDER)
        shell.pack(fill="both", expand=True)
        shell.columnconfigure(0, weight=1)
        shell.rowconfigure(3, weight=1)

        header = tk.Frame(shell, bg=SURFACE)
        header.grid(row=0, column=0, sticky="ew", padx=16, pady=(14, 10))
        header.columnconfigure(0, weight=1)

        tk.Label(
            header,
            text="CleanerPro Quick Panel",
            bg=SURFACE,
            fg=TEXT,
            font=("Segoe UI Semibold", 13),
        ).grid(row=0, column=0, sticky="w")
        tk.Label(
            header,
            text="Quick scan, cleanup, and task control from the tray.",
            bg=SURFACE,
            fg=MUTED,
            font=("Segoe UI", 9),
        ).grid(row=1, column=0, sticky="w", pady=(3, 0))

        close_button = tk.Button(
            header,
            text="x",
            command=self.hide,
            bg=SURFACE_ALT,
            fg=TEXT,
            activebackground="#20324F",
            activeforeground=TEXT,
            relief="flat",
            bd=0,
            highlightthickness=0,
            font=("Segoe UI Semibold", 10),
            width=3,
            cursor="hand2",
        )
        close_button.grid(row=0, column=1, rowspan=2, sticky="e")

        self.summary_var = tk.StringVar(value="System data is loading...")
        self.loader_var = tk.StringVar(value="Idle")
        self.health_var = tk.StringVar(value="Quick cleanup and task control are available here.")

        summary = tk.Frame(shell, bg=SURFACE_ALT, highlightthickness=1, highlightbackground=BORDER)
        summary.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 12))
        summary.columnconfigure(0, weight=1)
        tk.Label(
            summary,
            textvariable=self.summary_var,
            bg=SURFACE_ALT,
            fg=TEXT,
            justify="left",
            wraplength=380,
            font=("Segoe UI", 10),
        ).grid(row=0, column=0, sticky="w", padx=14, pady=(12, 6))
        tk.Label(
            summary,
            textvariable=self.health_var,
            bg=SURFACE_ALT,
            fg=MUTED,
            justify="left",
            wraplength=380,
            font=("Segoe UI", 9),
        ).grid(row=1, column=0, sticky="w", padx=14, pady=(0, 12))

        actions = tk.Frame(shell, bg=SURFACE)
        actions.grid(row=2, column=0, sticky="ew", padx=16, pady=(0, 12))
        actions.columnconfigure(0, weight=1)
        actions.columnconfigure(1, weight=1)
        make_button(actions, "Scan Junk", app.open_cleanup_and_scan, "primary").grid(
            row=0, column=0, sticky="ew", padx=(0, 6), pady=(0, 8)
        )
        make_button(actions, "Clean Safe", app.quick_clean_async, "info").grid(
            row=0, column=1, sticky="ew", padx=(6, 0), pady=(0, 8)
        )
        make_button(actions, "Quick Boost", app.quick_boost_async, "warning").grid(
            row=1, column=0, sticky="ew", padx=(0, 6), pady=(0, 8)
        )
        make_button(actions, "Delete All Junk", app.deep_clean_all_async, "danger").grid(
            row=1, column=1, sticky="ew", padx=(6, 0), pady=(0, 8)
        )
        make_button(actions, "Open Full App", app.show_main_window, "secondary").grid(
            row=2, column=0, columnspan=2, sticky="ew"
        )

        tasks_panel = tk.Frame(shell, bg=SURFACE, highlightthickness=1, highlightbackground=BORDER)
        tasks_panel.grid(row=3, column=0, sticky="nsew", padx=16)
        tasks_panel.columnconfigure(0, weight=1)
        tasks_panel.rowconfigure(1, weight=1)

        task_header = tk.Frame(tasks_panel, bg=SURFACE)
        task_header.grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 8))
        task_header.columnconfigure(0, weight=1)
        tk.Label(
            task_header,
            text="Top Running Tasks",
            bg=SURFACE,
            fg=TEXT,
            font=("Segoe UI Semibold", 11),
        ).grid(row=0, column=0, sticky="w")
        tk.Label(
            task_header,
            textvariable=self.loader_var,
            bg=SURFACE,
            fg=MUTED,
            font=("Segoe UI", 9),
        ).grid(row=0, column=1, sticky="e")

        self.process_tree = ttk.Treeview(
            tasks_panel,
            columns=("process", "ram", "cpu"),
            show="headings",
            height=7,
            selectmode="browse",
        )
        self.process_tree.grid(row=1, column=0, sticky="nsew", padx=12)
        self.process_tree.heading("process", text="Process")
        self.process_tree.heading("ram", text="RAM")
        self.process_tree.heading("cpu", text="CPU")
        self.process_tree.column("process", width=190, anchor="w")
        self.process_tree.column("ram", width=90, anchor="w")
        self.process_tree.column("cpu", width=75, anchor="w")

        task_buttons = tk.Frame(tasks_panel, bg=SURFACE)
        task_buttons.grid(row=2, column=0, sticky="ew", padx=12, pady=(10, 12))
        task_buttons.columnconfigure(0, weight=1)
        task_buttons.columnconfigure(1, weight=1)
        task_buttons.columnconfigure(2, weight=1)
        make_button(task_buttons, "Refresh", app.open_tasks_and_refresh, "secondary").grid(
            row=0, column=0, sticky="ew", padx=(0, 6)
        )
        make_button(task_buttons, "End Task", self._end_selected_task, "danger").grid(
            row=0, column=1, sticky="ew", padx=6
        )
        make_button(task_buttons, "Quit", app.quit_app, "secondary").grid(
            row=0, column=2, sticky="ew", padx=(6, 0)
        )

    def _on_focus_out(self, _event) -> None:
        self.after(150, self._hide_if_not_focused)

    def _hide_if_not_focused(self) -> None:
        if self.winfo_viewable() and self.focus_displayof() is None:
            self.hide()

    def show(self) -> None:
        width = 430
        height = 500
        taskbar_gap = 72
        x = max(self.winfo_screenwidth() - width - 18, 0)
        y = max(self.winfo_screenheight() - height - taskbar_gap, 0)
        self.geometry(f"{width}x{height}+{x}+{y}")
        self.deiconify()
        self.lift()
        self.focus_force()

    def hide(self) -> None:
        self.withdraw()

    def toggle(self) -> None:
        if self.winfo_viewable():
            self.hide()
        else:
            self.show()

    def update_data(
        self,
        snapshot: PerformanceSnapshot | None,
        latest_junk_total: int,
        process_entries: list[ProcessEntry],
        loader_text: str,
    ) -> None:
        if snapshot is None:
            self.summary_var.set("System metrics are loading...")
        else:
            self.summary_var.set(
                "CPU "
                f"{format_percent(snapshot.cpu_percent)} | RAM {format_percent(snapshot.memory_percent)} | "
                f"Junk {format_bytes(latest_junk_total)} | Tasks {snapshot.process_count}"
            )

            if snapshot.memory_percent >= 85:
                self.health_var.set(
                    "RAM usage is high. Closing heavy apps and cleaning junk can make the system feel smoother."
                )
            elif latest_junk_total >= 2 * 1024 * 1024 * 1024:
                self.health_var.set(
                    "A large amount of reclaimable junk was found. Run Safe Clean to free storage and reduce temp clutter."
                )
            else:
                self.health_var.set(
                    "Use the quick panel to scan, clean, and manage heavy tasks."
                )

        self.loader_var.set(loader_text)
        self.process_entries = {str(entry.pid): entry for entry in process_entries[:8]}
        for item in self.process_tree.get_children():
            self.process_tree.delete(item)
        for entry in process_entries[:8]:
            self.process_tree.insert(
                "",
                "end",
                iid=str(entry.pid),
                values=(entry.name, f"{entry.memory_mb:.0f} MB", f"{entry.cpu_percent:.0f}%"),
            )

    def _end_selected_task(self) -> None:
        selection = self.process_tree.selection()
        if not selection:
            messagebox.showinfo("CleanerPro", "Select a task in the quick panel first.")
            return
        entry = self.process_entries.get(selection[0])
        if entry is None:
            return
        self.app.end_process_entry(entry)


class CleanerApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("CleanerPro")
        self.geometry("1320x860")
        self.minsize(1160, 780)
        self.configure(bg=BACKGROUND)
        try:
            self.iconbitmap(default=str(asset_path("cleanerpro.ico")))
        except Exception:
            pass

        self.cleanup_targets: dict[str, CleanupTarget] = {}
        self.leftover_candidates: dict[str, LeftoverCandidate] = {}
        self.process_entries: dict[str, ProcessEntry] = {}
        self.latest_cleanup_total = 0
        self.latest_snapshot: PerformanceSnapshot | None = None
        self.latest_process_list: list[ProcessEntry] = []
        self.process_refresh_in_progress = False
        self.process_loop_after: str | None = None
        self.search_refresh_after: str | None = None
        self.active_jobs: set[str] = set()
        self.busy_depth = 0
        self.busy_buttons: list[tk.Button] = []
        self.closing_to_tray = False

        self.status_var = tk.StringVar(value="CleanerPro is ready. Run a junk scan or use the tray quick panel.")
        self.cleanup_info_var = tk.StringVar(
            value="Run a junk scan to find temp files, caches, and reclaimable space."
        )
        self.leftover_info_var = tk.StringVar(
            value="Leftover scan finds likely folders left behind after uninstall and shows them in a review list."
        )
        self.process_info_var = tk.StringVar(value="Live task list loading...")
        self.system_summary_var = tk.StringVar(
            value="Live overview of CPU, RAM, disk space, and heavy tasks."
        )
        self.health_summary_var = tk.StringVar(
            value="Quick Boost runs a safe junk cleanup and then refreshes the task list."
        )
        self.search_var = tk.StringVar()
        self.activity_title_var = tk.StringVar(value="No background job running")
        self.activity_detail_var = tk.StringVar(value="Buttons are sharp and responsive; heavy actions run with a visible loader.")

        self.metric_cards: dict[str, dict[str, tk.Widget]] = {}

        self._configure_styles()
        self._build_layout()
        self.quick_panel = QuickPanel(self)
        self.tray = SystemTrayController(self)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        prime_counters()
        self.after(400, self._start_services)

    def _configure_styles(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure(".", font=("Segoe UI", 10), background=BACKGROUND, foreground=TEXT)
        style.configure("TFrame", background=BACKGROUND)
        style.configure("TLabel", background=BACKGROUND, foreground=TEXT)
        style.configure(
            "TNotebook",
            background=BACKGROUND,
            borderwidth=0,
            tabmargins=(0, 6, 0, 0),
        )
        style.configure(
            "TNotebook.Tab",
            padding=(18, 12),
            background=SURFACE_ALT,
            foreground=MUTED,
            font=("Segoe UI Semibold", 10),
            borderwidth=0,
        )
        style.map(
            "TNotebook.Tab",
            background=[("selected", SURFACE)],
            foreground=[("selected", TEXT)],
        )
        style.configure(
            "Treeview",
            background=SURFACE_ALT,
            fieldbackground=SURFACE_ALT,
            foreground=TEXT,
            rowheight=32,
            borderwidth=0,
            relief="flat",
        )
        style.configure(
            "Treeview.Heading",
            background=SURFACE,
            foreground=TEXT,
            font=("Segoe UI Semibold", 10),
            relief="flat",
        )
        style.map(
            "Treeview",
            background=[("selected", "#244B68")],
            foreground=[("selected", "#FFFFFF")],
        )
        style.configure(
            "Horizontal.TProgressbar",
            troughcolor="#203047",
            bordercolor="#203047",
            background=ACCENT,
            lightcolor=ACCENT,
            darkcolor=ACCENT,
        )

    def _build_layout(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        hero = tk.Frame(self, bg=BACKGROUND)
        hero.grid(row=0, column=0, sticky="ew", padx=22, pady=(20, 14))
        hero.columnconfigure(0, weight=3)
        hero.columnconfigure(1, weight=2)

        brand_card = tk.Frame(hero, bg=SURFACE, highlightthickness=1, highlightbackground=BORDER)
        brand_card.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        brand_card.columnconfigure(1, weight=1)
        brand_card.rowconfigure(0, weight=1)
        tk.Frame(brand_card, bg=ACCENT, width=8).grid(row=0, column=0, sticky="ns")

        brand_body = tk.Frame(brand_card, bg=SURFACE)
        brand_body.grid(row=0, column=1, sticky="nsew", padx=18, pady=18)
        brand_body.columnconfigure(0, weight=1)

        tk.Label(
            brand_body,
            text="CleanerPro",
            bg=SURFACE,
            fg=TEXT,
            font=("Segoe UI Semibold", 28),
        ).grid(row=0, column=0, sticky="w")
        tk.Label(
            brand_body,
            text="Junk cleanup, leftover review, live tasks, and a tray quick panel in one Windows app.",
            bg=SURFACE,
            fg=MUTED,
            font=("Segoe UI", 11),
            wraplength=560,
            justify="left",
        ).grid(row=1, column=0, sticky="w", pady=(6, 12))

        badges = tk.Frame(brand_body, bg=SURFACE)
        badges.grid(row=2, column=0, sticky="w", pady=(0, 16))
        self._badge(badges, "High-DPI Sharp UI", INFO).pack(side="left", padx=(0, 8))
        self._badge(badges, "Tray Quick Panel", WARNING).pack(side="left", padx=(0, 8))
        self._badge(badges, "Safe Junk Cleaning", ACCENT).pack(side="left")

        hero_actions = tk.Frame(brand_body, bg=SURFACE)
        hero_actions.grid(row=3, column=0, sticky="w")
        self._register_busy_button(make_button(hero_actions, "Scan Junk", self.open_cleanup_and_scan, "primary")).pack(
            side="left", padx=(0, 8)
        )
        self._register_busy_button(make_button(hero_actions, "Clean Safe Junk", self.quick_clean_async, "info")).pack(
            side="left", padx=(0, 8)
        )
        self._register_busy_button(make_button(hero_actions, "Scan + Delete All", self.deep_clean_all_async, "danger")).pack(
            side="left", padx=(0, 8)
        )
        self._register_busy_button(make_button(hero_actions, "Quick Boost", self.quick_boost_async, "warning")).pack(
            side="left", padx=(0, 8)
        )
        make_button(hero_actions, "Hide To Tray", self.hide_to_tray, "secondary").pack(side="left")

        activity_card = tk.Frame(hero, bg=SURFACE_ALT, highlightthickness=1, highlightbackground=BORDER)
        activity_card.grid(row=0, column=1, sticky="nsew")
        activity_card.columnconfigure(0, weight=1)

        tk.Label(
            activity_card,
            text="Live Activity",
            bg=SURFACE_ALT,
            fg=TEXT,
            font=("Segoe UI Semibold", 13),
        ).grid(row=0, column=0, sticky="w", padx=18, pady=(18, 4))
        tk.Label(
            activity_card,
            textvariable=self.activity_title_var,
            bg=SURFACE_ALT,
            fg=TEXT,
            font=("Segoe UI Semibold", 16),
            wraplength=360,
            justify="left",
        ).grid(row=1, column=0, sticky="w", padx=18)
        tk.Label(
            activity_card,
            textvariable=self.activity_detail_var,
            bg=SURFACE_ALT,
            fg=MUTED,
            font=("Segoe UI", 10),
            wraplength=360,
            justify="left",
        ).grid(row=2, column=0, sticky="w", padx=18, pady=(6, 14))

        self.activity_progress = ttk.Progressbar(activity_card, mode="indeterminate")
        self.activity_progress.grid(row=3, column=0, sticky="ew", padx=18)
        tk.Label(
            activity_card,
            textvariable=self.health_summary_var,
            bg=SURFACE_ALT,
            fg=MUTED,
            font=("Segoe UI", 10),
            wraplength=360,
            justify="left",
        ).grid(row=4, column=0, sticky="w", padx=18, pady=(14, 18))

        notebook = ttk.Notebook(self)
        notebook.grid(row=1, column=0, sticky="nsew", padx=22, pady=(0, 12))
        self.notebook = notebook

        self.overview_tab = tk.Frame(notebook, bg=BACKGROUND)
        self.cleanup_tab = tk.Frame(notebook, bg=BACKGROUND)
        self.leftovers_tab = tk.Frame(notebook, bg=BACKGROUND)
        self.process_tab = tk.Frame(notebook, bg=BACKGROUND)
        notebook.add(self.overview_tab, text="Overview")
        notebook.add(self.cleanup_tab, text="Cleanup")
        notebook.add(self.leftovers_tab, text="Leftovers")
        notebook.add(self.process_tab, text="Tasks")

        self._build_overview_tab()
        self._build_cleanup_tab()
        self._build_leftovers_tab()
        self._build_process_tab()

        status = tk.Frame(self, bg=SURFACE, highlightthickness=1, highlightbackground=BORDER)
        status.grid(row=2, column=0, sticky="ew", padx=22, pady=(0, 20))
        status.columnconfigure(0, weight=1)
        tk.Label(
            status,
            textvariable=self.status_var,
            bg=SURFACE,
            fg=MUTED,
            font=("Segoe UI", 10),
        ).grid(row=0, column=0, sticky="w", padx=14, pady=12)

    def _build_overview_tab(self) -> None:
        tab = self.overview_tab
        tab.columnconfigure(0, weight=1)
        tab.columnconfigure(1, weight=1)
        tab.rowconfigure(2, weight=1)

        boost_panel = Panel(
            tab,
            "System Health",
            "CleanerPro helps keep Windows responsive with junk cleanup and task control.",
        )
        boost_panel.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 16))
        boost_panel.body.columnconfigure(0, weight=1)
        boost_panel.body.columnconfigure(1, weight=0)

        tk.Label(
            boost_panel.body,
            textvariable=self.system_summary_var,
            bg=SURFACE,
            fg=TEXT,
            justify="left",
            wraplength=760,
            font=("Segoe UI", 11),
        ).grid(row=0, column=0, sticky="w")

        callout = tk.Frame(boost_panel.body, bg=SURFACE_ALT, highlightthickness=1, highlightbackground=BORDER)
        callout.grid(row=0, column=1, sticky="e", padx=(20, 0))
        tk.Label(
            callout,
            text="One-click flow",
            bg=SURFACE_ALT,
            fg=MUTED,
            font=("Segoe UI", 9),
        ).grid(row=0, column=0, sticky="w", padx=14, pady=(12, 2))
        tk.Label(
            callout,
            text="Scan -> Clean -> Refresh Tasks",
            bg=SURFACE_ALT,
            fg=TEXT,
            font=("Segoe UI Semibold", 12),
        ).grid(row=1, column=0, sticky="w", padx=14)
        make_button(callout, "Run Quick Boost", self.quick_boost_async, "warning").grid(
            row=2, column=0, sticky="ew", padx=14, pady=(10, 14)
        )

        cards_row = tk.Frame(tab, bg=BACKGROUND)
        cards_row.grid(row=1, column=0, columnspan=2, sticky="ew")
        for index in range(5):
            cards_row.columnconfigure(index, weight=1)

        self.metric_cards["cpu"] = self._create_metric_card(cards_row, 0, "CPU Usage")
        self.metric_cards["memory"] = self._create_metric_card(cards_row, 1, "RAM Usage")
        self.metric_cards["disk"] = self._create_metric_card(cards_row, 2, "System Drive")
        self.metric_cards["junk"] = self._create_metric_card(cards_row, 3, "Recoverable Space")
        self.metric_cards["tasks"] = self._create_metric_card(cards_row, 4, "Running Tasks")

        top_panel = Panel(tab, "Top Memory Tasks", "The heaviest apps appear here.")
        top_panel.grid(row=2, column=0, sticky="nsew", padx=(0, 10), pady=(16, 0))
        top_panel.body.rowconfigure(0, weight=1)
        top_panel.body.columnconfigure(0, weight=1)
        self.top_process_tree = self._make_tree(
            top_panel.body,
            columns=("name", "cpu", "ram", "status"),
            headings={
                "name": "Process",
                "cpu": "CPU",
                "ram": "RAM",
                "status": "Status",
            },
            widths={"name": 250, "cpu": 90, "ram": 120, "status": 140},
            row=0,
            column=0,
        )

        advice_panel = Panel(tab, "Performance Guidance", "Fast feel lane ke liye practical guidance.")
        advice_panel.grid(row=2, column=1, sticky="nsew", pady=(16, 0))
        advice_text = (
            "CleanerPro performs safe temp/cache cleanup and helps you identify heavy background tasks.\n\n"
            "If RAM usage is very high, closing the browser or editor apps using the most memory usually gives the biggest improvement.\n\n"
            "Leftover folders stay review-based, so important app data is less likely to be deleted by mistake."
        )
        tk.Label(
            advice_panel.body,
            text=advice_text,
            bg=SURFACE,
            fg=MUTED,
            justify="left",
            wraplength=430,
            font=("Segoe UI", 10),
        ).grid(row=0, column=0, sticky="nw")

    def _build_cleanup_tab(self) -> None:
        tab = self.cleanup_tab
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(1, weight=1)
        tab.rowconfigure(2, weight=0)

        toolbar = tk.Frame(tab, bg=BACKGROUND)
        toolbar.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        self._register_busy_button(make_button(toolbar, "Run Junk Scan", self.open_cleanup_and_scan, "primary")).pack(
            side="left", padx=(0, 8)
        )
        self._register_busy_button(make_button(toolbar, "Clean Selected", self.clean_selected_cleanup_targets, "info")).pack(
            side="left", padx=(0, 8)
        )
        self._register_busy_button(make_button(toolbar, "Scan + Delete All", self.deep_clean_all_async, "danger")).pack(
            side="left", padx=(0, 8)
        )
        make_button(toolbar, "Select All", self.select_all_cleanup_targets, "secondary").pack(
            side="left", padx=(0, 12)
        )
        tk.Label(
            toolbar,
            textvariable=self.cleanup_info_var,
            bg=BACKGROUND,
            fg=MUTED,
            font=("Segoe UI", 10),
        ).pack(side="left")

        panel = Panel(tab, "Cleanup Targets", "After scanning, safe targets are selected automatically.")
        panel.grid(row=1, column=0, sticky="nsew")
        panel.body.rowconfigure(1, weight=1)
        panel.body.columnconfigure(0, weight=1)

        self.cleanup_loader_label = tk.Label(
            panel.body,
            text="No scan has been run yet.",
            bg=SURFACE,
            fg=MUTED,
            font=("Segoe UI", 10),
        )
        self.cleanup_loader_label.grid(row=0, column=0, sticky="w", pady=(0, 10))

        self.cleanup_loader = ttk.Progressbar(panel.body, mode="indeterminate")
        self.cleanup_loader.grid(row=0, column=1, sticky="e", pady=(0, 10), padx=(10, 0))

        self.cleanup_tree = self._make_tree(
            panel.body,
            columns=("name", "category", "items", "size", "location"),
            headings={
                "name": "Target",
                "category": "Category",
                "items": "Files",
                "size": "Size",
                "location": "Location",
            },
            widths={
                "name": 220,
                "category": 150,
                "items": 90,
                "size": 120,
                "location": 470,
            },
            row=1,
            column=0,
        )
        self.cleanup_tree.bind("<<TreeviewSelect>>", self._on_cleanup_selection)

        self.cleanup_detail_var = tk.StringVar(value="Target details will appear here.")
        tk.Label(
            panel.body,
            textvariable=self.cleanup_detail_var,
            bg=SURFACE,
            fg=MUTED,
            justify="left",
            wraplength=860,
            font=("Segoe UI", 9),
        ).grid(row=3, column=0, columnspan=2, sticky="w", pady=(10, 0))

        log_panel = Panel(tab, "Activity Log", "Record of scans and cleanup actions.")
        log_panel.grid(row=2, column=0, sticky="ew", pady=(12, 0))
        self.cleanup_log = ScrolledText(
            log_panel.body,
            height=7,
            bg=SURFACE_ALT,
            fg=TEXT,
            insertbackground=TEXT,
            relief="flat",
            font=("Consolas", 10),
            wrap="word",
        )
        self.cleanup_log.pack(fill="both", expand=True)
        self.cleanup_log.insert("end", "CleanerPro log started.\n")
        self.cleanup_log.configure(state="disabled")

    def _build_leftovers_tab(self) -> None:
        tab = self.leftovers_tab
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(1, weight=1)

        toolbar = tk.Frame(tab, bg=BACKGROUND)
        toolbar.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        self._register_busy_button(make_button(toolbar, "Scan Leftovers", self.scan_leftovers_async, "warning")).pack(
            side="left", padx=(0, 8)
        )
        self._register_busy_button(make_button(toolbar, "Delete Selected", self.delete_selected_leftovers, "danger")).pack(
            side="left", padx=(0, 8)
        )
        make_button(toolbar, "Open Folder", self.open_selected_leftover, "secondary").pack(side="left", padx=(0, 12))
        tk.Label(
            toolbar,
            textvariable=self.leftover_info_var,
            bg=BACKGROUND,
            fg=MUTED,
            font=("Segoe UI", 10),
        ).pack(side="left")

        panel = Panel(tab, "Possible Uninstall Leftovers", "Review-based cleanup. Auto-delete is disabled by default.")
        panel.grid(row=1, column=0, sticky="nsew")
        panel.body.rowconfigure(1, weight=1)
        panel.body.columnconfigure(0, weight=1)

        self.leftover_loader_label = tk.Label(
            panel.body,
            text="No leftover scan has been run yet.",
            bg=SURFACE,
            fg=WARNING,
            font=("Segoe UI Semibold", 10),
        )
        self.leftover_loader_label.grid(row=0, column=0, sticky="w", pady=(0, 10))
        self.leftover_loader = ttk.Progressbar(panel.body, mode="indeterminate")
        self.leftover_loader.grid(row=0, column=1, sticky="e", pady=(0, 10), padx=(10, 0))

        self.leftovers_tree = self._make_tree(
            panel.body,
            columns=("folder", "size", "modified", "confidence", "root", "reason"),
            headings={
                "folder": "Folder",
                "size": "Size",
                "modified": "Last Modified",
                "confidence": "Confidence",
                "root": "Root",
                "reason": "Why It Was Flagged",
            },
            widths={
                "folder": 310,
                "size": 110,
                "modified": 150,
                "confidence": 110,
                "root": 130,
                "reason": 330,
            },
            row=1,
            column=0,
        )

    def _build_process_tab(self) -> None:
        tab = self.process_tab
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(1, weight=1)

        toolbar = tk.Frame(tab, bg=BACKGROUND)
        toolbar.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        make_button(toolbar, "Refresh Tasks", self.open_tasks_and_refresh, "primary").pack(
            side="left", padx=(0, 8)
        )
        make_button(toolbar, "End Selected Task", self.end_selected_process, "danger").pack(
            side="left", padx=(0, 8)
        )
        make_button(toolbar, "Open App Folder", self.open_selected_process_folder, "secondary").pack(
            side="left", padx=(0, 12)
        )

        search = tk.Entry(
            toolbar,
            textvariable=self.search_var,
            bg=SURFACE_ALT,
            fg=TEXT,
            insertbackground=TEXT,
            relief="flat",
            width=32,
            font=("Segoe UI", 10),
            highlightthickness=1,
            highlightbackground=BORDER,
            highlightcolor=INFO,
        )
        search.pack(side="left", ipady=7)
        search.bind("<KeyRelease>", self._on_search_change)

        tk.Label(
            toolbar,
            textvariable=self.process_info_var,
            bg=BACKGROUND,
            fg=MUTED,
            font=("Segoe UI", 10),
        ).pack(side="left", padx=(12, 0))

        panel = Panel(tab, "Live Task Manager", "Search and manage RAM- and CPU-heavy apps.")
        panel.grid(row=1, column=0, sticky="nsew")
        panel.body.rowconfigure(1, weight=1)
        panel.body.columnconfigure(0, weight=1)

        self.process_loader_label = tk.Label(
            panel.body,
            text="The task list refreshes automatically.",
            bg=SURFACE,
            fg=MUTED,
            font=("Segoe UI", 10),
        )
        self.process_loader_label.grid(row=0, column=0, sticky="w", pady=(0, 10))

        self.process_tree = self._make_tree(
            panel.body,
            columns=("pid", "name", "cpu", "ram", "status", "user", "started"),
            headings={
                "pid": "PID",
                "name": "Process",
                "cpu": "CPU",
                "ram": "RAM",
                "status": "Status",
                "user": "User",
                "started": "Started",
            },
            widths={
                "pid": 80,
                "name": 250,
                "cpu": 85,
                "ram": 100,
                "status": 120,
                "user": 170,
                "started": 145,
            },
            row=1,
            column=0,
        )

    def _badge(self, parent: tk.Widget, text: str, color: str) -> tk.Frame:
        badge = tk.Frame(parent, bg=color, bd=0, highlightthickness=0)
        tk.Label(
            badge,
            text=text,
            bg=color,
            fg="#FFFFFF" if color != WARNING else "#1A1408",
            font=("Segoe UI Semibold", 9),
            padx=10,
            pady=5,
        ).pack()
        return badge

    def _register_busy_button(self, button: tk.Button) -> tk.Button:
        self.busy_buttons.append(button)
        return button

    def _create_metric_card(self, parent: tk.Widget, column: int, title: str) -> dict[str, tk.Widget]:
        card = tk.Frame(parent, bg=SURFACE, highlightthickness=1, highlightbackground=BORDER)
        card.grid(row=0, column=column, sticky="nsew", padx=(0 if column == 0 else 8, 0))
        card.columnconfigure(0, weight=1)

        tk.Label(card, text=title, bg=SURFACE, fg=MUTED, font=("Segoe UI", 10)).grid(
            row=0, column=0, sticky="w", padx=16, pady=(14, 2)
        )
        value_label = tk.Label(
            card,
            text="--",
            bg=SURFACE,
            fg=TEXT,
            font=("Segoe UI Semibold", 20),
        )
        value_label.grid(row=1, column=0, sticky="w", padx=16)
        detail_label = tk.Label(
            card,
            text="",
            bg=SURFACE,
            fg=MUTED,
            font=("Segoe UI", 10),
        )
        detail_label.grid(row=2, column=0, sticky="w", padx=16, pady=(2, 10))
        progress = ttk.Progressbar(card, orient="horizontal", mode="determinate")
        progress.grid(row=3, column=0, sticky="ew", padx=16, pady=(0, 14))
        return {"value": value_label, "detail": detail_label, "progress": progress}

    def _make_tree(
        self,
        parent: tk.Widget,
        columns: tuple[str, ...],
        headings: dict[str, str],
        widths: dict[str, int],
        row: int,
        column: int,
    ) -> ttk.Treeview:
        tree = ttk.Treeview(parent, columns=columns, show="headings", selectmode="extended")
        y_scroll = ttk.Scrollbar(parent, orient="vertical", command=tree.yview)
        x_scroll = ttk.Scrollbar(parent, orient="horizontal", command=tree.xview)
        tree.configure(yscrollcommand=y_scroll.set, xscrollcommand=x_scroll.set)
        tree.grid(row=row, column=column, sticky="nsew")
        y_scroll.grid(row=row, column=column + 1, sticky="ns")
        x_scroll.grid(row=row + 1, column=column, sticky="ew", pady=(6, 0))

        for key in columns:
            tree.heading(key, text=headings[key])
            tree.column(key, width=widths[key], anchor="w")
        return tree

    def _start_services(self) -> None:
        self.refresh_dashboard()
        self.open_cleanup_and_scan()
        self.refresh_processes_async(manual=False)
        self.tray.start()

    def refresh_dashboard(self) -> None:
        snapshot = get_performance_snapshot()
        self.latest_snapshot = snapshot
        self._update_snapshot_cards(snapshot)
        self._refresh_quick_panel()
        self.after(2200, self.refresh_dashboard)

    def _update_snapshot_cards(self, snapshot: PerformanceSnapshot) -> None:
        self._set_card(
            "cpu",
            format_percent(snapshot.cpu_percent),
            "Live CPU load across the system",
            snapshot.cpu_percent,
        )
        self._set_card(
            "memory",
            format_percent(snapshot.memory_percent),
            f"{format_bytes(snapshot.memory_used)} of {format_bytes(snapshot.memory_total)} in use",
            snapshot.memory_percent,
        )
        self._set_card(
            "disk",
            format_percent(snapshot.disk_percent),
            f"{format_bytes(snapshot.disk_free)} free of {format_bytes(snapshot.disk_total)}",
            snapshot.disk_percent,
        )
        self._set_card(
            "junk",
            format_bytes(self.latest_cleanup_total),
            "Latest junk scan total",
            min((self.latest_cleanup_total / max(snapshot.disk_total, 1)) * 100, 100),
        )
        tasks_percent = min(snapshot.process_count / 220 * 100, 100)
        self._set_card(
            "tasks",
            str(snapshot.process_count),
            f"Uptime {format_uptime(snapshot.uptime_seconds)}",
            tasks_percent,
        )

        self.system_summary_var.set(
            "CPU "
            f"{format_percent(snapshot.cpu_percent)}, RAM {format_percent(snapshot.memory_percent)}, "
            f"{snapshot.process_count} tasks are running, and {format_bytes(snapshot.disk_free)} is free on the system drive."
        )

        if snapshot.memory_percent >= 85:
            self.health_summary_var.set(
                "RAM usage is high. After Quick Boost, manually closing heavy browser or editor tasks usually gives the biggest improvement."
            )
        elif self.latest_cleanup_total >= 2 * 1024 * 1024 * 1024:
            self.health_summary_var.set(
                "A large amount of reclaimable junk was found. Run Safe Clean to reduce temp clutter and storage pressure."
            )
        else:
            self.health_summary_var.set(
                "Live monitoring and safe cleanup are active. The tray quick panel is also available."
            )

    def _set_card(self, key: str, value: str, detail: str, progress_value: float) -> None:
        card = self.metric_cards[key]
        card["value"].configure(text=value)
        card["detail"].configure(text=detail)
        card["progress"]["value"] = progress_value

    def open_cleanup_and_scan(self) -> None:
        self.notebook.select(self.cleanup_tab)
        self.scan_cleanup_targets_async()

    def open_tasks_and_refresh(self) -> None:
        self.notebook.select(self.process_tab)
        self.refresh_processes_async(manual=True)

    def scan_cleanup_targets_async(self) -> None:
        self.cleanup_loader_label.configure(text="Scanning junk files, browser cache, and temp folders...")
        self.cleanup_loader.start(10)
        self._run_background(
            "scan_cleanup",
            "Scanning junk files...",
            scan_cleanup_targets,
            self._load_cleanup_targets,
        )

    def _load_cleanup_targets(self, targets: list[CleanupTarget]) -> None:
        self.cleanup_loader.stop()
        self.cleanup_loader_label.configure(text="Scan complete. Targets were selected automatically.")
        self.cleanup_targets = {target.key: target for target in targets}
        self.latest_cleanup_total = sum(target.size_bytes for target in targets)
        total_files = sum(target.item_count for target in targets)
        rows = [
            (
                target.key,
                (
                    target.name,
                    target.category,
                    str(target.item_count),
                    format_bytes(target.size_bytes),
                    target.location,
                ),
            )
            for target in targets
        ]
        self._replace_tree_rows(self.cleanup_tree, rows)
        if rows:
            self.cleanup_tree.selection_set(*(item_id for item_id, _values in rows))
            self._show_cleanup_detail(rows[0][0])
        self.cleanup_info_var.set(
            f"{len(targets)} targets found, {total_files} files/items, about {format_bytes(self.latest_cleanup_total)} safe junk selected."
        )
        self._log_cleanup(f"Scan complete. Found {format_bytes(self.latest_cleanup_total)} of junk/caches.")
        self._set_status("Junk scan completed.")
        self._refresh_quick_panel()

    def select_all_cleanup_targets(self) -> None:
        ids = list(self.cleanup_targets.keys())
        if not ids:
            return
        self.cleanup_tree.selection_set(*ids)
        self.cleanup_detail_var.set("All safe junk targets are selected.")

    def _on_cleanup_selection(self, _event) -> None:
        selection = self.cleanup_tree.selection()
        if selection:
            self._show_cleanup_detail(selection[0])

    def _show_cleanup_detail(self, key: str) -> None:
        target = self.cleanup_targets.get(key)
        if target is None:
            self.cleanup_detail_var.set("Target details will appear here.")
            return
        self.cleanup_detail_var.set(
            f"{target.name}: {target.description} Location: {target.location}. "
            f"Estimated size {format_bytes(target.size_bytes)} across {target.item_count} files."
        )

    def clean_selected_cleanup_targets(self) -> None:
        selected = [self.cleanup_targets[item] for item in self.cleanup_tree.selection() if item in self.cleanup_targets]
        if not selected:
            if self.cleanup_targets:
                selected = list(self.cleanup_targets.values())
            else:
                messagebox.showinfo("CleanerPro", "Run a junk scan first.")
                return

        if not messagebox.askyesno(
            "Confirm Cleanup",
            "Delete the selected safe junk/cache items? Locked or very recent files will be skipped.",
        ):
            return

        self.cleanup_loader_label.configure(text="Cleaning selected junk files...")
        self.cleanup_loader.start(10)
        self._run_background(
            "cleanup_selected",
            "Cleaning selected junk files...",
            lambda: cleanup_selected_targets(selected),
            self._after_cleanup_run,
        )

    def quick_clean_async(self) -> None:
        if not messagebox.askyesno(
            "Clean Safe Junk",
            "Run a fresh scan and clean all safe junk targets?",
        ):
            return

        self.notebook.select(self.cleanup_tab)
        self.cleanup_loader_label.configure(text="Running quick clean...")
        self.cleanup_loader.start(10)
        self._run_background(
            "quick_clean",
            "Scanning and cleaning safe junk...",
            self._run_quick_clean_job,
            self._after_quick_clean,
        )

    def _run_quick_clean_job(self) -> tuple[list[CleanupTarget], ActionResult]:
        targets = scan_cleanup_targets()
        result = cleanup_selected_targets(targets)
        return targets, result

    def _after_quick_clean(self, payload: tuple[list[CleanupTarget], ActionResult]) -> None:
        _targets, result = payload
        self._handle_cleanup_result(result, "Quick clean finished")

    def deep_clean_all_async(self) -> None:
        if not messagebox.askyesno(
            "Scan + Delete All Junk",
            "This one-click action will scan and delete safe junk files and also remove high-confidence old software leftover folders. Continue?",
        ):
            return

        self.notebook.select(self.cleanup_tab)
        self.cleanup_loader_label.configure(
            text="Scanning full junk set and old-software leftovers, then deleting..."
        )
        self.cleanup_loader.start(10)
        self._run_background(
            "deep_clean_all",
            "Scanning and deleting all junk...",
            deep_clean_system,
            self._after_deep_clean_all,
        )

    def _after_deep_clean_all(self, result: DeepCleanResult) -> None:
        action_result = result.action_result
        self._handle_cleanup_result(action_result, "Scan + Delete All finished")
        self.health_summary_var.set(
            f"Deep clean complete. {result.leftover_deleted_count} old software leftover folders were auto-removed, "
            f"and {result.leftover_remaining_review_count} lower-confidence leftovers remain for review."
        )

    def quick_boost_async(self) -> None:
        if not messagebox.askyesno(
            "Quick Boost",
            "Quick Boost will run a safe junk cleanup and refresh the task view. Continue?",
        ):
            return

        self.notebook.select(self.overview_tab)
        self.cleanup_loader_label.configure(text="Quick Boost running...")
        self.cleanup_loader.start(10)
        self._run_background(
            "quick_boost",
            "Running Quick Boost...",
            self._run_quick_boost_job,
            self._after_quick_boost,
        )

    def _run_quick_boost_job(self) -> tuple[ActionResult, list[ProcessEntry]]:
        targets = scan_cleanup_targets()
        result = cleanup_selected_targets(targets)
        processes = get_processes(limit=12)
        return result, processes

    def _after_quick_boost(self, payload: tuple[ActionResult, list[ProcessEntry]]) -> None:
        result, processes = payload
        self.latest_process_list = processes
        self._handle_cleanup_result(result, "Quick Boost finished")
        self._load_process_entries(processes, schedule_next=False)
        if processes:
            top_names = ", ".join(entry.name for entry in processes[:3])
            self.health_summary_var.set(
                f"Boost complete. Current heaviest tasks: {top_names}. Review them if the system still feels slow."
            )

    def _after_cleanup_run(self, result: ActionResult) -> None:
        self._handle_cleanup_result(result, "Cleanup finished")

    def _handle_cleanup_result(self, result: ActionResult, prefix: str) -> None:
        self.cleanup_loader.stop()
        self.cleanup_loader_label.configure(
            text=(
                f"{prefix}. Freed {format_bytes(result.freed_bytes)}, deleted {result.deleted_items} items, "
                f"skipped {result.skipped_items}, failed {result.failed_items}."
            )
        )
        self._log_cleanup(
            f"{prefix}. Freed {format_bytes(result.freed_bytes)}, deleted {result.deleted_items} items, "
            f"skipped {result.skipped_items}, failed {result.failed_items}."
        )
        for message in result.messages:
            self._log_cleanup(message)
        if result.deleted_items == 0 and (result.skipped_items or result.failed_items):
            self.cleanup_info_var.set(
                "No files deleted in this pass. Some items were still active/recent; close browsers or apps and scan again."
            )
        self._set_status(f"{prefix}. Freed {format_bytes(result.freed_bytes)}.")
        self.scan_cleanup_targets_async()
        self.refresh_processes_async(manual=False)

    def scan_leftovers_async(self) -> None:
        self.notebook.select(self.leftovers_tab)
        self.leftover_loader_label.configure(text="Scanning for old uninstall leftovers...")
        self.leftover_loader.start(10)
        self._run_background(
            "scan_leftovers",
            "Scanning uninstall leftovers...",
            scan_leftover_candidates,
            self._load_leftover_candidates,
        )

    def _load_leftover_candidates(self, candidates: list[LeftoverCandidate]) -> None:
        self.leftover_loader.stop()
        self.leftover_loader_label.configure(text="Leftover scan complete. Review carefully before deleting.")
        self.leftover_candidates = {str(candidate.path): candidate for candidate in candidates}
        rows = [
            (
                str(candidate.path),
                (
                    candidate.path.name,
                    format_bytes(candidate.size_bytes),
                    format_datetime(candidate.modified_at),
                    f"{candidate.confidence}%",
                    candidate.root_label,
                    candidate.reason,
                ),
            )
            for candidate in candidates
        ]
        self._replace_tree_rows(self.leftovers_tree, rows)
        total_space = sum(candidate.size_bytes for candidate in candidates)
        self.leftover_info_var.set(
            f"{len(candidates)} possible leftovers found, around {format_bytes(total_space)}."
        )
        self._set_status("Leftover scan completed. Manual review recommended.")

    def delete_selected_leftovers(self) -> None:
        selected = [
            self.leftover_candidates[item]
            for item in self.leftovers_tree.selection()
            if item in self.leftover_candidates
        ]
        if not selected:
            messagebox.showinfo("CleanerPro", "Select leftover folders to delete.")
            return

        if not messagebox.askyesno(
            "Confirm Folder Removal",
            "Delete the selected leftover folders? This action is intended for old app data.",
        ):
            return

        self.leftover_loader_label.configure(text="Deleting selected leftover folders...")
        self.leftover_loader.start(10)
        self._run_background(
            "delete_leftovers",
            "Deleting leftover folders...",
            lambda: delete_leftover_candidates(selected),
            self._after_leftover_delete,
        )

    def _after_leftover_delete(self, result: ActionResult) -> None:
        self.leftover_loader.stop()
        self.leftover_loader_label.configure(
            text=f"Leftover cleanup finished. Freed {format_bytes(result.freed_bytes)}."
        )
        for message in result.messages:
            self._log_cleanup(message)
        self._set_status(f"Leftover cleanup finished. Freed {format_bytes(result.freed_bytes)}.")
        self.scan_leftovers_async()
        self.scan_cleanup_targets_async()

    def open_selected_leftover(self) -> None:
        selection = self.leftovers_tree.selection()
        if not selection:
            messagebox.showinfo("CleanerPro", "Select a leftover folder first.")
            return
        candidate = self.leftover_candidates.get(selection[0])
        if candidate is not None:
            open_in_explorer(candidate.path)

    def refresh_processes_async(self, manual: bool = True) -> None:
        if self.process_refresh_in_progress:
            if manual:
                self._set_status("The task list is already refreshing.")
            return

        self.process_refresh_in_progress = True
        search = self.search_var.get()
        if manual:
            self.process_loader_label.configure(text="Refreshing task list...")
        self._run_background(
            "refresh_processes",
            "Refreshing task list...",
            lambda: get_processes(search=search),
            lambda entries: self._load_process_entries(entries, schedule_next=False),
            on_complete=self._mark_process_refresh_done,
            show_loader=manual,
        )

    def _mark_process_refresh_done(self) -> None:
        self.process_refresh_in_progress = False
        if self.process_loop_after is not None:
            self.after_cancel(self.process_loop_after)
        self.process_loop_after = self.after(4000, lambda: self.refresh_processes_async(manual=False))

    def _load_process_entries(self, entries: list[ProcessEntry], schedule_next: bool = True) -> None:
        self.latest_process_list = entries
        self.process_entries = {str(entry.pid): entry for entry in entries}
        rows = [
            (
                str(entry.pid),
                (
                    str(entry.pid),
                    entry.name,
                    f"{entry.cpu_percent:.1f}%",
                    f"{entry.memory_mb:.1f} MB",
                    entry.status,
                    entry.username,
                    format_datetime(entry.started_at),
                ),
            )
            for entry in entries
        ]
        self._replace_tree_rows(self.process_tree, rows)
        self._replace_tree_rows(
            self.top_process_tree,
            [
                (
                    f"top-{entry.pid}",
                    (
                        entry.name,
                        f"{entry.cpu_percent:.1f}%",
                        f"{entry.memory_mb:.1f} MB",
                        entry.status,
                    ),
                )
                for entry in entries[:10]
            ],
        )

        self.process_loader_label.configure(text="Task list refreshed. Search by name or PID.")
        self.process_info_var.set(f"{len(entries)} tasks listed. Live refresh is active.")
        self._set_status("Task list refreshed.")
        self._refresh_quick_panel()

        if entries and self.latest_snapshot is not None:
            top_entry = entries[0]
            self.health_summary_var.set(
                "Current heaviest task: "
                f"{top_entry.name} ({top_entry.memory_mb:.0f} MB). Review apps like this if RAM pressure stays high."
            )

        if schedule_next:
            self._mark_process_refresh_done()

    def end_selected_process(self) -> None:
        selection = self.process_tree.selection()
        if not selection:
            messagebox.showinfo("CleanerPro", "Select a process first.")
            return
        entry = self.process_entries.get(selection[0])
        if entry is not None:
            self.end_process_entry(entry)

    def end_process_entry(self, entry: ProcessEntry) -> None:
        if not messagebox.askyesno(
            "End Task",
            f"End {entry.name} ({entry.pid})? Unsaved data in that app may be lost.",
        ):
            return

        self.process_loader_label.configure(text=f"Ending {entry.name}...")
        self._run_background(
            "end_process",
            "Ending selected process...",
            lambda: terminate_process(entry.pid),
            self._after_end_process,
        )

    def _after_end_process(self, result: tuple[bool, str]) -> None:
        ok, message = result
        self._set_status(message)
        self.process_loader_label.configure(text=message)
        if ok:
            self.refresh_processes_async(manual=False)
        else:
            messagebox.showwarning("CleanerPro", message)

    def open_selected_process_folder(self) -> None:
        selection = self.process_tree.selection()
        if not selection:
            messagebox.showinfo("CleanerPro", "Select a process first.")
            return

        entry = self.process_entries.get(selection[0])
        if entry is None or not entry.exe_path:
            messagebox.showinfo("CleanerPro", "File location is not available for the selected process.")
            return
        open_in_explorer(Path(entry.exe_path).parent)

    def _on_search_change(self, _event) -> None:
        if self.search_refresh_after is not None:
            self.after_cancel(self.search_refresh_after)
        self.search_refresh_after = self.after(500, self.open_tasks_and_refresh)

    def _replace_tree_rows(self, tree: ttk.Treeview, rows: list[tuple[str, tuple[str, ...]]]) -> None:
        for item in tree.get_children():
            tree.delete(item)
        for item_id, values in rows:
            tree.insert("", "end", iid=item_id, values=values)

    def _run_background(
        self,
        job_key: str,
        status: str,
        work,
        on_success,
        on_complete=None,
        show_loader: bool = True,
    ) -> None:
        if job_key in self.active_jobs:
            self._set_status(f"{status} already running.")
            return

        self.active_jobs.add(job_key)
        if show_loader:
            self._begin_activity(status)
        else:
            self._set_status(status)

        def runner() -> None:
            try:
                result = work()
            except Exception as exc:  # pragma: no cover - GUI error reporting
                self.after(0, lambda: self._handle_background_error(job_key, exc, on_complete, show_loader))
                return
            self.after(0, lambda: self._handle_background_success(job_key, result, on_success, on_complete, show_loader))

        threading.Thread(target=runner, daemon=True).start()

    def _handle_background_success(
        self,
        job_key: str,
        result,
        on_success,
        on_complete=None,
        show_loader: bool = True,
    ) -> None:
        try:
            on_success(result)
        finally:
            if on_complete is not None:
                on_complete()
            self.active_jobs.discard(job_key)
            if show_loader:
                self._end_activity()
            self._refresh_quick_panel()

    def _handle_background_error(
        self,
        job_key: str,
        exc: Exception,
        on_complete=None,
        show_loader: bool = True,
    ) -> None:
        if on_complete is not None:
            on_complete()
        self.active_jobs.discard(job_key)
        if show_loader:
            self._end_activity()
        self._set_status("Action failed.")
        messagebox.showerror("CleanerPro", str(exc))

    def _begin_activity(self, title: str) -> None:
        self.busy_depth += 1
        if self.busy_depth == 1:
            self.activity_progress.start(10)
            self._set_busy_buttons_state("disabled")
        self.activity_title_var.set(title)
        self.activity_detail_var.set("The loader is active. The action is running in the background and the UI will remain responsive.")
        self._refresh_quick_panel(loader_override=title)

    def _end_activity(self) -> None:
        self.busy_depth = max(self.busy_depth - 1, 0)
        if self.busy_depth == 0:
            self.activity_progress.stop()
            self._set_busy_buttons_state("normal")
            self.activity_title_var.set("Ready for next action")
            self.activity_detail_var.set(
                "Scan, cleanup, Quick Boost, and the tray quick panel are ready to use again."
            )
            self._refresh_quick_panel(loader_override="Idle")

    def _set_busy_buttons_state(self, state: str) -> None:
        for button in self.busy_buttons:
            button.configure(state=state)
            if state == "disabled":
                button.configure(bg="#40516A", fg="#D7DEEA", cursor="arrow")
            else:
                button.configure(bg=button.normal_bg, fg=button["activeforeground"], cursor="hand2")

    def _refresh_quick_panel(self, loader_override: str | None = None) -> None:
        loader_text = loader_override or (self.activity_title_var.get() if self.busy_depth else "Idle")
        self.quick_panel.update_data(
            self.latest_snapshot,
            self.latest_cleanup_total,
            self.latest_process_list,
            loader_text,
        )

    def show_main_window(self) -> None:
        self.closing_to_tray = False
        self.deiconify()
        self.lift()
        self.focus_force()
        self.quick_panel.hide()
        self._set_status("Main window restored.")

    def hide_to_tray(self) -> None:
        self.quick_panel.hide()
        self.withdraw()
        self._set_status("CleanerPro was sent to the tray. Click the tray icon to open the quick panel.")

    def toggle_quick_panel_from_tray(self) -> None:
        self._refresh_quick_panel()
        self.quick_panel.toggle()

    def quit_app(self) -> None:
        self.tray.stop()
        self.quick_panel.destroy()
        self.destroy()

    def _log_cleanup(self, message: str) -> None:
        self.cleanup_log.configure(state="normal")
        self.cleanup_log.insert("end", message + "\n")
        self.cleanup_log.see("end")
        self.cleanup_log.configure(state="disabled")

    def _set_status(self, message: str) -> None:
        self.status_var.set(message)

    def _on_close(self) -> None:
        self.hide_to_tray()
