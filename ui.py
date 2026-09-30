import os
import sys
import json
import time
import queue
import threading
import webbrowser
import subprocess
import re
import urllib.parse
from datetime import datetime
from typing import Optional, List, Dict, Any

import tkinter as tk
from tkinter import ttk, messagebox, filedialog, scrolledtext
from PIL import Image, ImageTk

# Enable high DPI awareness on Windows if possible
try:
    import ctypes
    try:
        ctypes.windll.user32.SetProcessDpiAwarenessContext(-2)
    except Exception:
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            ctypes.windll.user32.SetProcessDPIAware()
except Exception:
    pass

import autorun
from database import (
    DEFAULT_DB_PATH,
    init_db,
    get_connection,
    get_all_contacts,
    get_all_projects,
    get_contact_by_id,
    get_project_by_id,
    get_ambiguous_reviews,
    get_cache_stats,
    get_base_dir,
    get_crm_pipeline_items,
    get_lead_crm_status,
    save_lead_crm_status,
    add_crm_activity,
    get_crm_activities,
    get_crm_templates,
    save_crm_template,
)
import updater
from models import ContactEntity, ActiveProject
from normalizer import normalize_persian_text
from exporters import (
    export_all_csvs,
    export_contacts_to_csv,
    export_projects_to_csv,
    CONTACTS_CSV_PATH,
    PROJECTS_CSV_PATH,
)
from crawler import LeadDiscoveryCrawler, SEED_QUERIES
from validate_benchmark import run_benchmark_audit


# ==============================================================================
# 🎨 Modern Persian Architectural Theme & Fonts (Synchronized with Website)
# ==============================================================================

def init_persian_fonts() -> str:
    """
    Dynamically loads Vazirmatn TTF fonts into Windows GDI font table.
    Returns the font family name ('Vazirmatn' if successfully loaded, else 'Tahoma' or 'Segoe UI').
    """
    font_dirs = [
        os.path.join(getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__))), "assets", "fonts"),
        os.path.join(get_base_dir(), "assets", "fonts"),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "fonts"),
    ]
    for fdir in font_dirs:
        if os.path.isdir(fdir):
            for fname in ["Vazirmatn-Regular.ttf", "Vazirmatn-Bold.ttf", "Vazirmatn-Medium.ttf"]:
                fpath = os.path.join(fdir, fname)
                if os.path.exists(fpath):
                    try:
                        ctypes.windll.gdi32.AddFontResourceExW(os.path.abspath(fpath), 0x10, 0)
                    except Exception:
                        pass
    try:
        import tkinter.font as tkfont
        families = list(tkfont.families())
        for f in families:
            if "vazir" in f.lower():
                return f
        if "Tahoma" in families:
            return "Tahoma"
        if "Segoe UI" in families:
            return "Segoe UI"
    except Exception:
        pass
    return "Vazirmatn"


ACTIVE_FONT = init_persian_fonts()

# Noavaran Luxury Obsidian & Crimson Architectural Design Tokens
# Exact match with Noavaran Panjereh website (noavaranpanjereh.com)
THEME = {
    "bg_dark": "#0a0002",          # Ink 950 - Main canvas & root
    "bg_header": "#0d0003",        # Header background
    "bg_card": "#140005",          # Card surface / container background
    "bg_card_elevated": "#1c0007", # Elevated surface for toolbars & badges
    "bg_input": "#180006",         # Text areas, entries, and inputs
    "bg_tree_row": "#120004",      # Treeview primary row
    "bg_tree_alt": "#190006",      # Treeview alternating row
    "bg_tree_sel": "#7b0010",      # Treeview selected row
    "bg_tip": "#200007",           # Contextual tip box background
    "border": "#3b0008",           # Subtle dark crimson border
    "border_card": "#4a000a",      # Distinct card border
    "border_highlight": "#6b000e", # Active border
    "border_tip": "#8b0012",       # Tip card border
    "signal": "#ab0017",           # Signal 500 - Primary brand red
    "signal_hover": "#c4001a",     # Signal 400 - Button hover
    "signal_active": "#d1001c",    # Signal 300 - Active / pressed
    "blood": "#5c000c",            # Secondary dark crimson
    "blood_hover": "#7a0010",      # Secondary hover
    "blood_active": "#8b0012",     # Secondary active
    "text_white": "#fefefe",       # Steel 100 - High contrast text
    "text_steel": "#e3e4e6",       # Steel 200 - Main body text
    "text_copper": "#cca699",      # Copper 500 - Warm architectural secondary text
    "text_copper_light": "#e6c3b8",# Copper 400 - Accent text & headings
    "text_dim": "#8b7e7b",         # Steel 500 - Muted hints, timestamps
    "success": "#10b981",          # Emerald 500
    "warning": "#f59e0b",          # Amber 500
    "danger": "#ef4444",           # Red 500
    "info": "#06b6d4",             # Cyan 500
}


def create_modern_button(
    parent,
    text: str,
    command=None,
    bg: str = THEME["signal"],
    hover_bg: str = THEME["signal_hover"],
    active_bg: str = THEME["signal_active"],
    fg: str = THEME["text_white"],
    font: Any = None,
    padx: int = 10,
    pady: int = 5,
    width: Optional[int] = None,
    state: str = tk.NORMAL,
) -> tk.Button:
    """Creates a modern flat button with responsive hover feedback."""
    btn = tk.Button(
        parent,
        text=text,
        command=command,
        bg=bg,
        fg=fg,
        activebackground=active_bg,
        activeforeground=fg,
        disabledforeground="#64748b",
        font=font or (ACTIVE_FONT, 9, "bold"),
        relief=tk.FLAT,
        bd=0,
        padx=padx,
        pady=pady,
        cursor="hand2" if state == tk.NORMAL else "arrow",
        state=state,
        highlightthickness=0,
    )
    if width is not None:
        btn.config(width=width)

    orig_bg = bg
    def on_enter(e):
        if btn["state"] == tk.NORMAL:
            btn.config(bg=hover_bg)

    def on_leave(e):
        if btn["state"] == tk.NORMAL:
            btn.config(bg=orig_bg)

    btn.bind("<Enter>", on_enter)
    btn.bind("<Leave>", on_leave)
    return btn


class ScraperApp:
    def __init__(self, root: tk.Tk, db_path: str = DEFAULT_DB_PATH, auto_start_crawl: bool = False):
        self.root = root
        self.db_path = db_path
        self.auto_start_crawl = auto_start_crawl
        # Ensure database tables exist immediately before any query
        init_db(self.db_path)

        self.root.title("نوآوران پنجره | Noavaran Panjereh - Lead & Project Intelligence Scraper")
        self.root.geometry("1120x760")
        self.root.minsize(960, 620)

        # Window icon
        icon_path = os.path.join(getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__))), "icon.ico")
        if not os.path.exists(icon_path):
            icon_path = os.path.join(get_base_dir(), "icon.ico")
        if os.path.exists(icon_path):
            try:
                self.root.iconbitmap(icon_path)
            except Exception:
                pass

        # Worker thread & communication queue
        self.worker_thread: Optional[threading.Thread] = None
        self.stop_event = threading.Event()
        self.msg_queue: queue.Queue = queue.Queue()
        self.is_busy = False

        # In-memory cached table data
        self.contacts_cache: List[ContactEntity] = []
        self.projects_cache: List[ActiveProject] = []
        self.reviews_cache: List[Dict[str, Any]] = []
        self.crm_items_cache: List[Dict[str, Any]] = []

        # Sort order trackers
        self.contacts_sort_state = {}
        self.projects_sort_state = {}
        self.reviews_sort_state = {}
        self.crm_sort_state = {}

        # CRM selection
        self.selected_crm_item: Optional[Dict[str, Any]] = None
        self._update_check_job = None

        self._configure_styles()
        self._build_header()
        self._build_notebook()
        self._build_statusbar()

        # Start queue polling loop
        self._poll_job = self.root.after(50, self._poll_queue)

        # Protocol for graceful window closing
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        # Initial load of stats & tables
        self._init_job = self.root.after(200, self._initial_load)
        if self.auto_start_crawl:
            self.root.after(2500, self._auto_start_crawl_on_launch)

        # Background update check (non-blocking)
        self._update_check_job = self.root.after(3500, lambda: self._check_updates_flow(interactive=False))

    def _configure_styles(self):
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass

        self.font_family = ACTIVE_FONT
        self.font_default = (ACTIVE_FONT, 9)
        self.font_bold = (ACTIVE_FONT, 9, "bold")
        self.font_header = (ACTIVE_FONT, 11, "bold")
        self.font_title = (ACTIVE_FONT, 13, "bold")
        self.font_small = (ACTIVE_FONT, 8)
        self.font_stat_val = (ACTIVE_FONT, 13, "bold")

        # Root and Popup option database
        self.root.configure(bg=THEME["bg_dark"])
        self.root.option_add("*TCombobox*Listbox.background", THEME["bg_input"])
        self.root.option_add("*TCombobox*Listbox.foreground", THEME["text_white"])
        self.root.option_add("*TCombobox*Listbox.selectBackground", THEME["signal"])
        self.root.option_add("*TCombobox*Listbox.selectForeground", THEME["text_white"])
        self.root.option_add("*TCombobox*Listbox.font", self.font_default)
        self.root.option_add("*Menu.background", THEME["bg_card"])
        self.root.option_add("*Menu.foreground", THEME["text_white"])
        self.root.option_add("*Menu.selectColor", THEME["signal"])

        # Base ttk style
        style.configure(".", background=THEME["bg_dark"], foreground=THEME["text_steel"], font=self.font_default)

        # Notebook & Tabs
        style.configure("TNotebook", background=THEME["bg_dark"], borderwidth=0, tabmargins=[0, 0, 0, 0])
        style.configure(
            "TNotebook.Tab",
            background=THEME["bg_card"],
            foreground=THEME["text_copper"],
            font=self.font_bold,
            padding=[14, 8],
            borderwidth=0,
        )
        style.map(
            "TNotebook.Tab",
            background=[("selected", THEME["signal"]), ("active", THEME["bg_card_elevated"])],
            foreground=[("selected", THEME["text_white"]), ("active", THEME["text_white"])],
        )

        # Treeview (Modern Luxury Dark Table)
        style.configure(
            "Treeview",
            background=THEME["bg_tree_row"],
            foreground=THEME["text_white"],
            fieldbackground=THEME["bg_tree_row"],
            font=self.font_default,
            rowheight=29,
            borderwidth=0,
            relief="flat",
        )
        style.map(
            "Treeview",
            background=[("selected", THEME["bg_tree_sel"])],
            foreground=[("selected", THEME["text_white"])],
        )
        style.configure(
            "Treeview.Heading",
            background=THEME["bg_card_elevated"],
            foreground=THEME["text_copper_light"],
            font=self.font_bold,
            padding=[6, 6],
            borderwidth=1,
            relief="flat",
        )
        style.map(
            "Treeview.Heading",
            background=[("active", THEME["blood"])],
            foreground=[("active", THEME["text_white"])],
        )

        # LabelFrame
        style.configure(
            "TLabelframe",
            background=THEME["bg_card"],
            bordercolor=THEME["border_card"],
            borderwidth=1,
            relief="solid",
        )
        style.configure(
            "TLabelframe.Label",
            background=THEME["bg_card"],
            foreground=THEME["text_copper_light"],
            font=self.font_bold,
            padding=[6, 2],
        )

        # Frames & Labels
        style.configure("TFrame", background=THEME["bg_dark"])
        style.configure("Card.TFrame", background=THEME["bg_card"])
        style.configure("Header.TLabel", font=self.font_header, background=THEME["bg_card"], foreground=THEME["text_white"])
        style.configure("Title.TLabel", font=self.font_title, background=THEME["bg_dark"], foreground=THEME["text_white"])
        style.configure("StatValue.TLabel", font=self.font_stat_val, foreground=THEME["signal"])
        style.configure("StatTitle.TLabel", font=self.font_small, foreground=THEME["text_copper"])
        style.configure("Muted.TLabel", font=self.font_small, foreground=THEME["text_dim"])

        # Entry, Combobox, Spinbox
        style.configure(
            "TEntry",
            fieldbackground=THEME["bg_input"],
            foreground=THEME["text_white"],
            bordercolor=THEME["border"],
            lightcolor=THEME["border_card"],
            darkcolor=THEME["border"],
            padding=[6, 4],
            font=self.font_default,
        )
        style.configure(
            "TCombobox",
            fieldbackground=THEME["bg_input"],
            foreground=THEME["text_white"],
            background=THEME["bg_card_elevated"],
            arrowcolor=THEME["text_copper"],
            bordercolor=THEME["border"],
            font=self.font_default,
            padding=[4, 3],
        )
        style.map(
            "TCombobox",
            fieldbackground=[("readonly", THEME["bg_input"])],
            foreground=[("readonly", THEME["text_white"])],
            selectbackground=[("readonly", THEME["signal"])],
            selectforeground=[("readonly", THEME["text_white"])],
        )
        style.configure(
            "TSpinbox",
            fieldbackground=THEME["bg_input"],
            foreground=THEME["text_white"],
            background=THEME["bg_card_elevated"],
            arrowcolor=THEME["text_copper"],
            bordercolor=THEME["border"],
            font=self.font_default,
        )

        # Scrollbar
        style.configure(
            "TScrollbar",
            background=THEME["bg_card_elevated"],
            troughcolor=THEME["bg_dark"],
            bordercolor=THEME["bg_dark"],
            arrowcolor=THEME["text_copper"],
            relief="flat",
        )
        style.map(
            "TScrollbar",
            background=[("active", THEME["signal"]), ("pressed", THEME["signal_active"])],
        )

        # Progressbar
        style.configure(
            "Horizontal.TProgressbar",
            background=THEME["signal"],
            troughcolor=THEME["bg_input"],
            bordercolor=THEME["border"],
            thickness=12,
        )

        # Checkbutton
        style.configure(
            "TCheckbutton",
            background=THEME["bg_card"],
            foreground=THEME["text_steel"],
            font=self.font_default,
            indicatorbackground=THEME["bg_input"],
            indicatorforeground=THEME["signal"],
        )
        style.map(
            "TCheckbutton",
            background=[("active", THEME["bg_card"])],
            foreground=[("active", THEME["text_white"])],
        )

        # Separator
        style.configure("TSeparator", background=THEME["border"])

    def _build_header(self):
        # Red-Black brand header from Noavaran website (Ink 950: #0a0002, Signal: #ab0017 / #d1001c)
        header_outer = tk.Frame(self.root, bg=THEME["signal"], height=86)
        header_outer.pack(side=tk.TOP, fill=tk.X)
        header_outer.pack_propagate(False)

        header_frame = tk.Frame(header_outer, bg=THEME["bg_dark"])
        header_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True, pady=(0, 2))

        # Brand box with Logo (RTL: Placed on the RIGHT side)
        brand_box = tk.Frame(header_frame, bg=THEME["bg_dark"])
        brand_box.pack(side=tk.RIGHT, fill=tk.Y, padx=16, pady=8)

        # Load official logo
        self._logo_photo = None
        logo_candidates = [
            os.path.join(getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__))), "assets", "logo-white.png"),
            os.path.join(getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__))), "assets", "icon.png"),
            os.path.join(get_base_dir(), "assets", "logo-white.png"),
            os.path.join(get_base_dir(), "assets", "icon.png"),
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "logo-white.png"),
            r"C:\Users\PC\prj\noavaran\public\logo-white.png",
            r"C:\Users\PC\prj\noavaran\public\icon.png",
        ]
        for lp in logo_candidates:
            if os.path.exists(lp):
                try:
                    img = Image.open(lp)
                    target_h = 48
                    target_w = int(img.width * (target_h / img.height))
                    img_res = img.resize((target_w, target_h), Image.Resampling.LANCZOS)
                    self._logo_photo = ImageTk.PhotoImage(img_res)
                    break
                except Exception:
                    pass

        if self._logo_photo:
            logo_lbl = tk.Label(brand_box, image=self._logo_photo, bg=THEME["bg_dark"])
            logo_lbl.pack(side=tk.RIGHT, padx=(14, 0))

        # Title text container (Persian RTL aligned to right)
        text_box = tk.Frame(brand_box, bg=THEME["bg_dark"])
        text_box.pack(side=tk.RIGHT, fill=tk.Y)

        title_lbl = tk.Label(
            text_box,
            text="نوآوران پنجره | Noavaran Panjereh",
            font=self.font_title,
            fg=THEME["text_white"],
            bg=THEME["bg_dark"],
            anchor="e",
        )
        title_lbl.pack(anchor="e")

        subtitle_lbl = tk.Label(
            text_box,
            text="سامانه هوشمند استخراج سرنخ‌ها، معماران و پروژه‌های ساختمانی سراسر کشور",
            font=self.font_small,
            fg=THEME["text_copper"],
            bg=THEME["bg_dark"],
            anchor="e",
        )
        subtitle_lbl.pack(anchor="e")

        # Stats badges (RTL: Placed on the LEFT side)
        stats_box = tk.Frame(header_frame, bg=THEME["bg_dark"])
        stats_box.pack(side=tk.LEFT, fill=tk.Y, padx=16, pady=8)

        # Quick update check action button with modern styling
        self.btn_check_update = create_modern_button(
            stats_box,
            text=f"🔄 به‌روزرسانی (v{updater.CURRENT_VERSION})",
            font=self.font_bold,
            bg=THEME["blood"],
            hover_bg=THEME["signal"],
            active_bg=THEME["signal_active"],
            fg=THEME["text_white"],
            padx=10,
            pady=6,
            command=lambda: self._check_updates_flow(interactive=True),
        )
        self.btn_check_update.pack(side=tk.LEFT, padx=(0, 10))

        def make_stat_card(parent, title_text, var_name):
            card = tk.Frame(
                parent,
                bg=THEME["bg_card"],
                padx=12,
                pady=4,
                relief=tk.SOLID,
                bd=1,
                highlightbackground=THEME["border_card"],
                highlightthickness=1,
            )
            card.pack(side=tk.LEFT, padx=4)
            val_lbl = tk.Label(card, text="0", font=self.font_stat_val, fg=THEME["text_white"], bg=THEME["bg_card"])
            val_lbl.pack()
            setattr(self, var_name, val_lbl)
            lbl = tk.Label(card, text=title_text, font=self.font_small, fg=THEME["text_copper"], bg=THEME["bg_card"])
            lbl.pack()

        make_stat_card(stats_box, "مخاطبین (Contacts)", "lbl_stat_contacts")
        make_stat_card(stats_box, "پروژه‌ها (Projects)", "lbl_stat_projects")
        make_stat_card(stats_box, "رکوردهای خام (Raw)", "lbl_stat_raw")
        make_stat_card(stats_box, "برخوردهای مبهم (Reviews)", "lbl_stat_reviews")

    def _build_notebook(self):
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=8, pady=6)

        # Tab 1: Crawl & Monitor
        self.tab_crawl = ttk.Frame(self.notebook, padding=8)
        self.notebook.add(self.tab_crawl, text=" 🚀 داشبورد و کنترل پویشگر (Crawl Control) ")
        self._setup_crawl_tab()

        # Tab 2: Contacts & Leads
        self.tab_contacts = ttk.Frame(self.notebook, padding=8)
        self.notebook.add(self.tab_contacts, text=" 👥 مخاطبین و سرنخ‌ها (Contacts) ")
        self._setup_contacts_tab()

        # Tab 3: Active Projects
        self.tab_projects = ttk.Frame(self.notebook, padding=8)
        self.notebook.add(self.tab_projects, text=" 🏗️ پروژه‌های فعال ساختمانی (Active Projects) ")
        self._setup_projects_tab()

        # Tab 4: Construction CRM Pipeline & Sales Workflow
        self.tab_crm = ttk.Frame(self.notebook, padding=8)
        self.notebook.add(self.tab_crm, text=" 💼 خط فروش و مدیریت فروش (CRM) ")
        self._setup_crm_tab()

        # Tab 5: Export & Files
        self.tab_export = ttk.Frame(self.notebook, padding=8)
        self.notebook.add(self.tab_export, text=" 📁 خروجی‌ها و فایل‌ها (Export & Files) ")
        self._setup_export_tab()

        # Tab 6: Ambiguous Reviews
        self.tab_reviews = ttk.Frame(self.notebook, padding=8)
        self.notebook.add(self.tab_reviews, text=" ⚖️ بررسی برخوردهای مبهم (Ambiguous Reviews) ")
        self._setup_reviews_tab()

    def _setup_crawl_tab(self):
        # Horizontal Split: Console on Left, Configuration & Controls on Right (Persian RTL)
        paned = ttk.PanedWindow(self.tab_crawl, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True)

        # Left: Live Execution Logs
        log_frame = ttk.LabelFrame(paned, text="لاگ زنده و خروجی کنسول (Live Execution Logs)", padding=6)
        paned.add(log_frame, weight=3)

        # Log toolbar
        log_tools = ttk.Frame(log_frame)
        log_tools.pack(fill=tk.X, pady=(0, 4))

        self.var_autoscroll = tk.BooleanVar(value=True)
        chk_scroll = ttk.Checkbutton(log_tools, text="اسکرول خودکار (Auto-scroll)", variable=self.var_autoscroll)
        chk_scroll.pack(side=tk.RIGHT, padx=4)

        btn_clear_log = create_modern_button(
            log_tools,
            text="🗑️ پاکسازی (Clear)",
            bg=THEME["bg_card_elevated"],
            hover_bg=THEME["blood"],
            fg=THEME["text_copper"],
            font=self.font_small,
            padx=8,
            pady=3,
            command=self._clear_log,
        )
        btn_clear_log.pack(side=tk.LEFT, padx=2)

        btn_copy_log = create_modern_button(
            log_tools,
            text="📋 کپی لاگ (Copy)",
            bg=THEME["bg_card_elevated"],
            hover_bg=THEME["blood"],
            fg=THEME["text_copper"],
            font=self.font_small,
            padx=8,
            pady=3,
            command=self._copy_log,
        )
        btn_copy_log.pack(side=tk.LEFT, padx=2)

        # Log text area (Deep Obsidian Terminal)
        self.txt_log = scrolledtext.ScrolledText(
            log_frame,
            wrap=tk.WORD,
            bg="#070002",
            fg=THEME["text_white"],
            insertbackground=THEME["signal"],
            font=("Consolas", 9),
            relief=tk.FLAT,
            bd=0,
            highlightthickness=1,
            highlightbackground=THEME["border"],
            highlightcolor=THEME["signal"],
        )
        self.txt_log.pack(fill=tk.BOTH, expand=True)

        # Tag configuration for colored logs
        self.txt_log.tag_configure("info", foreground=THEME["info"])
        self.txt_log.tag_configure("success", foreground=THEME["success"])
        self.txt_log.tag_configure("warning", foreground=THEME["warning"])
        self.txt_log.tag_configure("error", foreground=THEME["danger"])
        self.txt_log.tag_configure("dim", foreground=THEME["text_dim"])

        # Right: Configuration & Execution Panel (RTL Layout)
        config_frame = ttk.LabelFrame(paned, text="تنظیمات و دستورات پویش (Configuration & Execution)", padding=10)
        paned.add(config_frame, weight=2)

        # Form fields grid: Labels on right (col 1), Inputs on left (col 0)
        form_grid = ttk.Frame(config_frame)
        form_grid.pack(fill=tk.X, pady=(0, 6))

        def add_config_row(row, label_text, var_name, from_, to_, default_val):
            ttk.Label(form_grid, text=label_text, anchor="e").grid(row=row, column=1, sticky="e", pady=4, padx=(4, 0))
            spn = ttk.Spinbox(form_grid, from_=from_, to=to_, width=8)
            spn.set(default_val)
            spn.grid(row=row, column=0, sticky="w", pady=4, padx=(0, 4))
            setattr(self, var_name, spn)

        add_config_row(0, "حداکثر دفعات جستجو (Max Passes):", "spn_passes", 1, 100, 12)
        add_config_row(1, "محدودیت توقف توالی صفر (Streak Limit):", "spn_streak", 1, 20, 4)
        add_config_row(2, "بودجه زمانی (ثانیه) (Budget Sec):", "spn_budget", 30, 3600, 180)
        add_config_row(3, "کانال‌های تلگرام (Telegram Channels):", "spn_tg", 1, 10, 4)
        add_config_row(4, "نتایج به ازای جستجو (Results/Query):", "spn_results", 1, 30, 5)
        add_config_row(5, "کاوش عمیق وب‌سایت‌ها (Max Frontier):", "spn_frontier", 1, 50, 10)

        form_grid.grid_columnconfigure(0, weight=1)
        form_grid.grid_columnconfigure(1, weight=1)

        # Action Buttons
        btn_frame = ttk.Frame(config_frame, padding=(0, 6, 0, 0))
        btn_frame.pack(fill=tk.X)

        self.btn_run = create_modern_button(
            btn_frame,
            text="▶ شروع پویش خودکار (Start Scraper)",
            bg=THEME["signal"],
            hover_bg=THEME["signal_hover"],
            active_bg=THEME["signal_active"],
            fg=THEME["text_white"],
            font=self.font_bold,
            padx=10,
            pady=7,
            command=self._on_start_crawler,
        )
        self.btn_run.pack(fill=tk.X, pady=3)

        self.btn_stop = create_modern_button(
            btn_frame,
            text="⏹ توقف عملیات (Stop Scraper)",
            bg=THEME["blood"],
            hover_bg=THEME["blood_hover"],
            active_bg=THEME["blood_active"],
            fg=THEME["text_white"],
            font=self.font_bold,
            state=tk.DISABLED,
            padx=10,
            pady=5,
            command=self._on_stop_crawler,
        )
        self.btn_stop.pack(fill=tk.X, pady=3)

        ttk.Separator(btn_frame, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=6)

        self.btn_rebuild = create_modern_button(
            btn_frame,
            text="🔄 بازسازی و بازپردازش کش (Rebuild Cache)",
            bg=THEME["bg_card_elevated"],
            hover_bg=THEME["blood"],
            active_bg=THEME["blood_hover"],
            fg=THEME["text_copper_light"],
            font=self.font_default,
            padx=8,
            pady=4,
            command=self._on_rebuild_cache,
        )
        self.btn_rebuild.pack(fill=tk.X, pady=2)

        self.btn_benchmark = create_modern_button(
            btn_frame,
            text="🧪 ارزیابی بنچ‌مارک اصفهان (Run Benchmark)",
            bg=THEME["bg_card_elevated"],
            hover_bg=THEME["blood"],
            active_bg=THEME["blood_hover"],
            fg=THEME["text_copper_light"],
            font=self.font_default,
            padx=8,
            pady=4,
            command=self._on_run_benchmark,
        )
        self.btn_benchmark.pack(fill=tk.X, pady=2)

        # Progress bar & status
        self.crawl_status_lbl = ttk.Label(
            config_frame,
            text="آماده به کار (Idle)",
            font=self.font_small,
            anchor="e",
        )
        self.crawl_status_lbl.pack(fill=tk.X, pady=(10, 2))

        self.progressbar = ttk.Progressbar(config_frame, orient=tk.HORIZONTAL, mode="determinate")
        self.progressbar.pack(fill=tk.X, pady=(0, 4))

        # Daily Autorun on Windows Startup
        autorun_card = ttk.LabelFrame(config_frame, text="⏱️ اجرای خودکار روزانه (Daily Startup Autorun)", padding=8)
        autorun_card.pack(fill=tk.X, pady=(8, 2))

        self.var_autorun = tk.BooleanVar(value=autorun.is_autorun_enabled())
        self.var_autorun_crawl = tk.BooleanVar(value=True)

        chk_autorun = ttk.Checkbutton(
            autorun_card,
            text="اجرای خودکار با روشن شدن سیستم (Run on Startup)",
            variable=self.var_autorun,
            command=self._on_toggle_autorun,
        )
        chk_autorun.pack(anchor="e", pady=2)

        chk_crawl = ttk.Checkbutton(
            autorun_card,
            text="شروع خودکار پویش سرنخ‌ها هنگام بالا آمدن ویندوز",
            variable=self.var_autorun_crawl,
            command=self._on_toggle_autorun,
        )
        chk_crawl.pack(anchor="e", pady=2)

        is_act = self.var_autorun.get()
        self.lbl_autorun_status = tk.Label(
            autorun_card,
            text="وضعیت: فعال در استارت‌آپ ویندوز (Active)" if is_act else "وضعیت: غیرفعال (Disabled)",
            font=self.font_bold,
            fg=THEME["success"] if is_act else THEME["text_dim"],
            bg=THEME["bg_card"],
            anchor="e",
        )
        self.lbl_autorun_status.pack(anchor="e", pady=(2, 0))

    def _setup_contacts_tab(self):
        # Filter Frame (Persian RTL Layout)
        filter_frame = tk.Frame(self.tab_contacts, bg=THEME["bg_card"], padx=10, pady=8, relief=tk.SOLID, bd=1, highlightbackground=THEME["border"], highlightthickness=1)
        filter_frame.pack(fill=tk.X, pady=(0, 6))

        # Packed Right-to-Left
        ttk.Label(filter_frame, text="🔍 جستجو:").pack(side=tk.RIGHT, padx=(4, 2))
        self.ent_search_contacts = ttk.Entry(filter_frame, width=24)
        self.ent_search_contacts.pack(side=tk.RIGHT, padx=(0, 10))
        self.ent_search_contacts.bind("<KeyRelease>", lambda e: self._filter_contacts())

        ttk.Label(filter_frame, text="دسته‌بندی:").pack(side=tk.RIGHT, padx=(4, 2))
        self.cmb_filter_type = ttk.Combobox(
            filter_frame,
            values=["همه (All)", "office", "contractor", "student", "individual"],
            state="readonly",
            width=14,
        )
        self.cmb_filter_type.set("همه (All)")
        self.cmb_filter_type.pack(side=tk.RIGHT, padx=(0, 10))
        self.cmb_filter_type.bind("<<ComboboxSelected>>", lambda e: self._filter_contacts())

        ttk.Label(filter_frame, text="شهر:").pack(side=tk.RIGHT, padx=(4, 2))
        self.cmb_filter_city = ttk.Combobox(
            filter_frame,
            values=["همه (All)", "Isfahan", "Tehran", "Other"],
            state="readonly",
            width=12,
        )
        self.cmb_filter_city.set("همه (All)")
        self.cmb_filter_city.pack(side=tk.RIGHT, padx=(0, 10))
        self.cmb_filter_city.bind("<<ComboboxSelected>>", lambda e: self._filter_contacts())

        btn_refresh = create_modern_button(
            filter_frame,
            text="🔄 بازخوانی (Refresh)",
            bg=THEME["bg_card_elevated"],
            hover_bg=THEME["signal"],
            fg=THEME["text_white"],
            font=self.font_small,
            padx=8,
            pady=3,
            command=self._load_contacts_from_db,
        )
        btn_refresh.pack(side=tk.RIGHT, padx=4)

        self.lbl_contacts_count = ttk.Label(filter_frame, text="در حال بارگذاری...", font=self.font_bold)
        self.lbl_contacts_count.pack(side=tk.LEFT, padx=4)

        # Paned Window for Table + Detail View
        paned = ttk.PanedWindow(self.tab_contacts, orient=tk.VERTICAL)
        paned.pack(fill=tk.BOTH, expand=True)

        # Treeview Frame
        tree_frame = ttk.Frame(paned)
        paned.add(tree_frame, weight=3)

        cols = ("type", "name", "role", "company", "city", "phone", "email", "confidence", "social", "source")
        self.tree_contacts = ttk.Treeview(tree_frame, columns=cols, show="headings", selectmode="browse")

        col_defs = [
            ("type", "دسته (Type)", 80, "center"),
            ("name", "نام / عنوان (Name)", 150, "e"),
            ("role", "نقش (Role)", 110, "e"),
            ("company", "شرکت / دفتر (Company)", 150, "e"),
            ("city", "شهر (City)", 75, "center"),
            ("phone", "تلفن (Phone)", 115, "center"),
            ("email", "ایمیل (Email)", 140, "w"),
            ("confidence", "اطمینان", 75, "center"),
            ("social", "سوشال / هندل", 95, "center"),
            ("source", "منبع (Source URL)", 180, "w"),
        ]

        for col_id, col_name, col_w, col_anchor in col_defs:
            self.tree_contacts.heading(col_id, text=col_name, command=lambda c=col_id: self._sort_tree(self.tree_contacts, self.contacts_sort_state, c))
            self.tree_contacts.column(col_id, width=col_w, minwidth=60, anchor=col_anchor)

        self.tree_contacts.tag_configure("evenrow", background=THEME["bg_tree_row"], foreground=THEME["text_white"])
        self.tree_contacts.tag_configure("oddrow", background=THEME["bg_tree_alt"], foreground=THEME["text_white"])

        # Scrollbars for treeview
        vsb = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.tree_contacts.yview)
        hsb = ttk.Scrollbar(tree_frame, orient=tk.HORIZONTAL, command=self.tree_contacts.xview)
        self.tree_contacts.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        self.tree_contacts.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")

        tree_frame.grid_rowconfigure(0, weight=1)
        tree_frame.grid_columnconfigure(0, weight=1)

        self.tree_contacts.bind("<<TreeviewSelect>>", self._on_contact_selected)

        # Detail Frame below
        detail_frame = ttk.LabelFrame(paned, text="جزئیات مخاطب انتخاب شده (Selected Contact Details)", padding=8)
        paned.add(detail_frame, weight=1)

        self.txt_contact_detail = tk.Text(
            detail_frame,
            height=4,
            font=self.font_default,
            wrap=tk.WORD,
            bg=THEME["bg_input"],
            fg=THEME["text_white"],
            insertbackground=THEME["signal"],
            relief=tk.FLAT,
            bd=0,
            highlightthickness=1,
            highlightbackground=THEME["border"],
            highlightcolor=THEME["signal"],
        )
        self.txt_contact_detail.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        detail_actions = ttk.Frame(detail_frame)
        detail_actions.pack(side=tk.RIGHT, fill=tk.Y, padx=(8, 0))

        self.btn_copy_phone = create_modern_button(
            detail_actions,
            text="📋 کپی تلفن",
            bg=THEME["bg_card_elevated"],
            hover_bg=THEME["blood"],
            fg=THEME["text_copper_light"],
            font=self.font_small,
            padx=8,
            pady=3,
            command=self._copy_selected_contact_phone,
        )
        self.btn_copy_phone.pack(fill=tk.X, pady=2)

        self.btn_copy_email = create_modern_button(
            detail_actions,
            text="📋 کپی ایمیل",
            bg=THEME["bg_card_elevated"],
            hover_bg=THEME["blood"],
            fg=THEME["text_copper_light"],
            font=self.font_small,
            padx=8,
            pady=3,
            command=self._copy_selected_contact_email,
        )
        self.btn_copy_email.pack(fill=tk.X, pady=2)

        self.btn_open_contact_url = create_modern_button(
            detail_actions,
            text="🌐 باز کردن لینک منبع",
            bg=THEME["bg_card_elevated"],
            hover_bg=THEME["signal"],
            fg=THEME["text_white"],
            font=self.font_small,
            padx=8,
            pady=3,
            command=self._open_selected_contact_url,
        )
        self.btn_open_contact_url.pack(fill=tk.X, pady=2)

    def _setup_projects_tab(self):
        # Filter Frame (Persian RTL Layout)
        filter_frame = tk.Frame(self.tab_projects, bg=THEME["bg_card"], padx=10, pady=8, relief=tk.SOLID, bd=1, highlightbackground=THEME["border"], highlightthickness=1)
        filter_frame.pack(fill=tk.X, pady=(0, 6))

        # Packed Right-to-Left
        ttk.Label(filter_frame, text="🔍 جستجو:").pack(side=tk.RIGHT, padx=(4, 2))
        self.ent_search_projects = ttk.Entry(filter_frame, width=28)
        self.ent_search_projects.pack(side=tk.RIGHT, padx=(0, 10))
        self.ent_search_projects.bind("<KeyRelease>", lambda e: self._filter_projects())

        ttk.Label(filter_frame, text="شهر:").pack(side=tk.RIGHT, padx=(4, 2))
        self.cmb_proj_city = ttk.Combobox(
            filter_frame,
            values=["همه (All)", "Isfahan", "Tehran", "Other"],
            state="readonly",
            width=12,
        )
        self.cmb_proj_city.set("همه (All)")
        self.cmb_proj_city.pack(side=tk.RIGHT, padx=(0, 10))
        self.cmb_proj_city.bind("<<ComboboxSelected>>", lambda e: self._filter_projects())

        btn_refresh = create_modern_button(
            filter_frame,
            text="🔄 بازخوانی (Refresh)",
            bg=THEME["bg_card_elevated"],
            hover_bg=THEME["signal"],
            fg=THEME["text_white"],
            font=self.font_small,
            padx=8,
            pady=3,
            command=self._load_projects_from_db,
        )
        btn_refresh.pack(side=tk.RIGHT, padx=4)

        self.lbl_projects_count = ttk.Label(filter_frame, text="در حال بارگذاری...", font=self.font_bold)
        self.lbl_projects_count.pack(side=tk.LEFT, padx=4)

        # Paned Window for Table + Detail View
        paned = ttk.PanedWindow(self.tab_projects, orient=tk.VERTICAL)
        paned.pack(fill=tk.BOTH, expand=True)

        tree_frame = ttk.Frame(paned)
        paned.add(tree_frame, weight=3)

        cols = ("name", "city", "scope", "contractors", "architects", "contact", "confidence", "date", "source")
        self.tree_projects = ttk.Treeview(tree_frame, columns=cols, show="headings", selectmode="browse")

        col_defs = [
            ("name", "نام پروژه (Project Name)", 180, "e"),
            ("city", "شهر", 75, "center"),
            ("scope", "مقیاس و مشخصات (Scale/Scope)", 140, "e"),
            ("contractors", "پیمانکار(ان) مرتبط", 140, "e"),
            ("architects", "معمار(ان) / مشاور", 140, "e"),
            ("contact", "اطلاعات تماس", 110, "center"),
            ("confidence", "اطمینان", 75, "center"),
            ("date", "تاریخ کشف", 85, "center"),
            ("source", "منبع (Source URL)", 180, "w"),
        ]

        for col_id, col_name, col_w, col_anchor in col_defs:
            self.tree_projects.heading(col_id, text=col_name, command=lambda c=col_id: self._sort_tree(self.tree_projects, self.projects_sort_state, c))
            self.tree_projects.column(col_id, width=col_w, minwidth=60, anchor=col_anchor)

        self.tree_projects.tag_configure("evenrow", background=THEME["bg_tree_row"], foreground=THEME["text_white"])
        self.tree_projects.tag_configure("oddrow", background=THEME["bg_tree_alt"], foreground=THEME["text_white"])

        vsb = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.tree_projects.yview)
        hsb = ttk.Scrollbar(tree_frame, orient=tk.HORIZONTAL, command=self.tree_projects.xview)
        self.tree_projects.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        self.tree_projects.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")

        tree_frame.grid_rowconfigure(0, weight=1)
        tree_frame.grid_columnconfigure(0, weight=1)

        self.tree_projects.bind("<<TreeviewSelect>>", self._on_project_selected)

        # Detail Frame below
        detail_frame = ttk.LabelFrame(paned, text="مشخصات کامل پروژه (Selected Project Details)", padding=8)
        paned.add(detail_frame, weight=1)

        self.txt_project_detail = tk.Text(
            detail_frame,
            height=4,
            font=self.font_default,
            wrap=tk.WORD,
            bg=THEME["bg_input"],
            fg=THEME["text_white"],
            insertbackground=THEME["signal"],
            relief=tk.FLAT,
            bd=0,
            highlightthickness=1,
            highlightbackground=THEME["border"],
            highlightcolor=THEME["signal"],
        )
        self.txt_project_detail.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        detail_actions = ttk.Frame(detail_frame)
        detail_actions.pack(side=tk.RIGHT, fill=tk.Y, padx=(8, 0))

        self.btn_copy_proj = create_modern_button(
            detail_actions,
            text="📋 کپی مشخصات",
            bg=THEME["bg_card_elevated"],
            hover_bg=THEME["blood"],
            fg=THEME["text_copper_light"],
            font=self.font_small,
            padx=8,
            pady=3,
            command=self._copy_selected_project_info,
        )
        self.btn_copy_proj.pack(fill=tk.X, pady=2)

        self.btn_open_proj_url = create_modern_button(
            detail_actions,
            text="🌐 باز کردن لینک منبع",
            bg=THEME["bg_card_elevated"],
            hover_bg=THEME["signal"],
            fg=THEME["text_white"],
            font=self.font_small,
            padx=8,
            pady=3,
            command=self._open_selected_project_url,
        )
        self.btn_open_proj_url.pack(fill=tk.X, pady=2)

    def _setup_reviews_tab(self):
        top_frame = tk.Frame(self.tab_reviews, bg=THEME["bg_card"], padx=10, pady=8, relief=tk.SOLID, bd=1, highlightbackground=THEME["border"], highlightthickness=1)
        top_frame.pack(fill=tk.X, pady=(0, 6))

        info_lbl = ttk.Label(
            top_frame,
            text="برخوردهای مبهم در قرنطینه (امتیاز شباهت فازی ۷۰ الی ۸۷ درصد جهت بازبینی کاربر):",
            font=self.font_bold,
        )
        info_lbl.pack(side=tk.RIGHT, padx=4)

        btn_refresh = create_modern_button(
            top_frame,
            text="🔄 بازخوانی لاگ بازبینی (Refresh)",
            bg=THEME["bg_card_elevated"],
            hover_bg=THEME["signal"],
            fg=THEME["text_white"],
            font=self.font_small,
            padx=8,
            pady=3,
            command=self._load_reviews_from_db,
        )
        btn_refresh.pack(side=tk.LEFT, padx=4)

        paned = ttk.PanedWindow(self.tab_reviews, orient=tk.VERTICAL)
        paned.pack(fill=tk.BOTH, expand=True)

        tree_frame = ttk.Frame(paned)
        paned.add(tree_frame, weight=2)

        cols = ("id", "type", "score", "reason", "existing_id", "date")
        self.tree_reviews = ttk.Treeview(tree_frame, columns=cols, show="headings", selectmode="browse")

        col_defs = [
            ("id", "شناسه", 50, "center"),
            ("type", "نوع کاندید", 80, "center"),
            ("score", "امتیاز شباهت", 90, "center"),
            ("reason", "دلیل برخورد فازی / بازبینی", 220, "e"),
            ("existing_id", "شناسه موجود در دیتابیس", 160, "center"),
            ("date", "تاریخ لاگ", 140, "center"),
        ]

        for col_id, col_name, col_w, col_anchor in col_defs:
            self.tree_reviews.heading(col_id, text=col_name, command=lambda c=col_id: self._sort_tree(self.tree_reviews, self.reviews_sort_state, c))
            self.tree_reviews.column(col_id, width=col_w, anchor=col_anchor)

        self.tree_reviews.tag_configure("evenrow", background=THEME["bg_tree_row"], foreground=THEME["text_white"])
        self.tree_reviews.tag_configure("oddrow", background=THEME["bg_tree_alt"], foreground=THEME["text_white"])

        vsb = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.tree_reviews.yview)
        self.tree_reviews.configure(yscrollcommand=vsb.set)
        self.tree_reviews.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)

        self.tree_reviews.bind("<<TreeviewSelect>>", self._on_review_selected)

        detail_frame = ttk.LabelFrame(paned, text="محتوای خام کاندید مورد بررسی (Candidate Payload JSON)", padding=8)
        paned.add(detail_frame, weight=2)

        self.txt_review_detail = tk.Text(
            detail_frame,
            height=8,
            font=self.font_default,
            wrap=tk.WORD,
            bg=THEME["bg_input"],
            fg=THEME["text_white"],
            insertbackground=THEME["signal"],
            relief=tk.FLAT,
            bd=0,
            highlightthickness=1,
            highlightbackground=THEME["border"],
            highlightcolor=THEME["signal"],
        )
        self.txt_review_detail.pack(fill=tk.BOTH, expand=True)

    def _setup_export_tab(self):
        main_frame = ttk.Frame(self.tab_export, padding=16)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Card 1: Contacts CSV
        c_card = ttk.LabelFrame(main_frame, text="خروجی سرنخ‌ها و مخاطبین (contacts.csv)", padding=12)
        c_card.pack(fill=tk.X, pady=8)

        self.lbl_contacts_file_status = ttk.Label(c_card, text=f"مسیر فایل: {CONTACTS_CSV_PATH}", font=self.font_default)
        self.lbl_contacts_file_status.pack(anchor="w", pady=2)

        btn_box1 = ttk.Frame(c_card)
        btn_box1.pack(anchor="w", pady=6)

        create_modern_button(btn_box1, text="⚡ استخراج سریع (Export Now)", bg=THEME["signal"], hover_bg=THEME["signal_hover"], font=self.font_bold, command=self._export_contacts_quick).pack(side=tk.LEFT, padx=4)
        create_modern_button(btn_box1, text="💾 ذخیره در مسیر دلخواه... (Save As)", bg=THEME["bg_card_elevated"], hover_bg=THEME["blood"], fg=THEME["text_copper_light"], font=self.font_default, command=self._export_contacts_custom).pack(side=tk.LEFT, padx=4)
        create_modern_button(btn_box1, text="📊 باز کردن فایل با اکسل (Open CSV)", bg=THEME["bg_card_elevated"], hover_bg=THEME["blood"], fg=THEME["text_copper_light"], font=self.font_default, command=lambda: self._open_file(CONTACTS_CSV_PATH)).pack(side=tk.LEFT, padx=4)

        # Card 2: Projects CSV
        p_card = ttk.LabelFrame(main_frame, text="خروجی پروژه‌های فعال ساختمانی (active_projects.csv)", padding=12)
        p_card.pack(fill=tk.X, pady=8)

        self.lbl_projects_file_status = ttk.Label(p_card, text=f"مسیر فایل: {PROJECTS_CSV_PATH}", font=self.font_default)
        self.lbl_projects_file_status.pack(anchor="w", pady=2)

        btn_box2 = ttk.Frame(p_card)
        btn_box2.pack(anchor="w", pady=6)

        create_modern_button(btn_box2, text="⚡ استخراج سریع (Export Now)", bg=THEME["signal"], hover_bg=THEME["signal_hover"], font=self.font_bold, command=self._export_projects_quick).pack(side=tk.LEFT, padx=4)
        create_modern_button(btn_box2, text="💾 ذخیره در مسیر دلخواه... (Save As)", bg=THEME["bg_card_elevated"], hover_bg=THEME["blood"], fg=THEME["text_copper_light"], font=self.font_default, command=self._export_projects_custom).pack(side=tk.LEFT, padx=4)
        create_modern_button(btn_box2, text="📊 باز کردن فایل با اکسل (Open CSV)", bg=THEME["bg_card_elevated"], hover_bg=THEME["blood"], fg=THEME["text_copper_light"], font=self.font_default, command=lambda: self._open_file(PROJECTS_CSV_PATH)).pack(side=tk.LEFT, padx=4)

        # Card 3: Directory & DB Actions
        d_card = ttk.LabelFrame(main_frame, text="پایگاه داده و پوشه پروژه (Database & Explorer)", padding=12)
        d_card.pack(fill=tk.X, pady=8)

        base_d = get_base_dir()
        self.lbl_db_path = ttk.Label(d_card, text=f"پایگاه داده SQLite: {self.db_path}\nپوشه برنامه: {base_d}", font=self.font_default)
        self.lbl_db_path.pack(anchor="w", pady=2)

        btn_box3 = ttk.Frame(d_card)
        btn_box3.pack(anchor="w", pady=6)

        create_modern_button(btn_box3, text="📂 باز کردن پوشه فایل‌ها (Open Output Folder)", bg=THEME["bg_card_elevated"], hover_bg=THEME["blood"], fg=THEME["text_copper_light"], font=self.font_default, command=self._open_base_dir).pack(side=tk.LEFT, padx=4)
        create_modern_button(btn_box3, text="🔄 استخراج هر دو فایل هم‌زمان (Export All CSVs)", bg=THEME["signal"], hover_bg=THEME["signal_hover"], font=self.font_bold, command=self._export_all_now).pack(side=tk.LEFT, padx=4)

    # ========================== CRM Pipeline Tab ==========================

    def _setup_crm_tab(self):
        # Master CRM Layout (Persian RTL)
        top_filter_bar = tk.Frame(self.tab_crm, bg=THEME["bg_card"], padx=10, pady=8, relief=tk.SOLID, bd=1, highlightbackground=THEME["border"], highlightthickness=1)
        top_filter_bar.pack(fill=tk.X, pady=(0, 6))

        # Packed Right-to-Left
        ttk.Label(top_filter_bar, text="مرحله فروش (Stage):", font=self.font_bold).pack(side=tk.RIGHT, padx=(4, 2))
        self.cmb_crm_filter_stage = ttk.Combobox(
            top_filter_bar,
            values=[
                "همه مراحل (All Stages)",
                "new: سرنخ جدید",
                "qualified: تماس اولیه و ارزیابی",
                "drawings: دریافت نقشه‌های فاز ۲",
                "quoted: صدور پیش‌فاکتور مهندسی",
                "negotiation: جلسه حضوری و بازدید",
                "won: عقد قرارداد و تولید",
                "lost: انصراف / رد شده",
            ],
            state="readonly",
            width=24,
        )
        self.cmb_crm_filter_stage.current(0)
        self.cmb_crm_filter_stage.pack(side=tk.RIGHT, padx=(0, 10))
        self.cmb_crm_filter_stage.bind("<<ComboboxSelected>>", lambda e: self._filter_crm_items())

        ttk.Label(top_filter_bar, text="جستجو:").pack(side=tk.RIGHT, padx=(4, 2))
        self.ent_crm_search = ttk.Entry(top_filter_bar, width=20)
        self.ent_crm_search.pack(side=tk.RIGHT, padx=(0, 10))
        self.ent_crm_search.bind("<KeyRelease>", lambda e: self._filter_crm_items())

        btn_refresh = create_modern_button(
            top_filter_bar,
            text="🔄 بازخوانی سرنخ‌ها",
            bg=THEME["bg_card_elevated"],
            hover_bg=THEME["signal"],
            fg=THEME["text_white"],
            font=self.font_small,
            padx=8,
            pady=3,
            command=self._load_crm_from_db,
        )
        btn_refresh.pack(side=tk.RIGHT, padx=4)

        self.lbl_crm_count = ttk.Label(top_filter_bar, text="تعداد سرنخ‌ها: 0", font=self.font_bold)
        self.lbl_crm_count.pack(side=tk.LEFT, padx=4)

        # Horizontal split: Workspace on left, Leads list on right (natural RTL flow)
        paned = ttk.PanedWindow(self.tab_crm, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True)

        # Workspace panel (Left side)
        right_frame = ttk.Frame(paned)
        paned.add(right_frame, weight=4)

        # Lead Header Card
        header_card = tk.Frame(right_frame, bg=THEME["bg_card"], relief=tk.SOLID, bd=1, highlightbackground=THEME["border_card"], highlightthickness=1, padx=12, pady=10)
        header_card.pack(fill=tk.X, pady=(0, 6))

        self.lbl_crm_active_title = tk.Label(header_card, text="هیچ سرنخی انتخاب نشده است", font=self.font_header, fg=THEME["text_white"], bg=THEME["bg_card"], anchor="e")
        self.lbl_crm_active_title.pack(anchor="e")

        self.lbl_crm_active_subtitle = tk.Label(header_card, text="یک ردیف از جدول سرنخ‌ها را انتخاب فرمایید", font=self.font_small, fg=THEME["text_copper"], bg=THEME["bg_card"], anchor="e")
        self.lbl_crm_active_subtitle.pack(anchor="e", pady=(2, 6))

        quick_btns = tk.Frame(header_card, bg=THEME["bg_card"])
        quick_btns.pack(anchor="e")

        self.btn_crm_copy_phone = create_modern_button(
            quick_btns,
            text="📋 کپی شماره",
            bg=THEME["bg_card_elevated"],
            hover_bg=THEME["blood"],
            fg=THEME["text_copper_light"],
            font=self.font_small,
            padx=8,
            pady=3,
            command=self._copy_crm_phone,
        )
        self.btn_crm_copy_phone.pack(side=tk.RIGHT, padx=(4, 0))

        self.btn_crm_open_url = create_modern_button(
            quick_btns,
            text="🌐 باز کردن لینک منبع",
            bg=THEME["bg_card_elevated"],
            hover_bg=THEME["signal"],
            fg=THEME["text_white"],
            font=self.font_small,
            padx=8,
            pady=3,
            command=self._open_crm_source_url,
        )
        self.btn_crm_open_url.pack(side=tk.RIGHT, padx=4)

        # Sub Notebook for CRM
        self.crm_notebook = ttk.Notebook(right_frame)
        self.crm_notebook.pack(fill=tk.BOTH, expand=True)

        # SubTab 1: Pipeline & Stage Details
        sub_pipeline = ttk.Frame(self.crm_notebook, padding=8)
        self.crm_notebook.add(sub_pipeline, text="📌 وضعیت و مرحله فروش")

        # Form fields: Labels on right (col 1), inputs on left (col 0)
        form = ttk.Frame(sub_pipeline)
        form.pack(fill=tk.X, pady=(0, 6))

        ttk.Label(form, text="مرحله جاری:", anchor="e").grid(row=0, column=1, sticky="e", pady=3, padx=(4, 0))
        self.cmb_crm_lead_stage = ttk.Combobox(
            form,
            values=[
                "new: سرنخ جدید",
                "qualified: تماس اولیه و ارزیابی",
                "drawings: دریافت نقشه‌های فاز ۲",
                "quoted: صدور پیش‌فاکتور مهندسی",
                "negotiation: جلسه حضوری و بازدید",
                "won: عقد قرارداد و تولید",
                "lost: انصراف / رد شده",
            ],
            state="readonly",
            width=26,
        )
        self.cmb_crm_lead_stage.grid(row=0, column=0, sticky="ew", pady=3, padx=4)
        self.cmb_crm_lead_stage.bind("<<ComboboxSelected>>", self._on_crm_stage_dropdown_change)

        ttk.Label(form, text="کارشناس مسئول:", anchor="e").grid(row=1, column=1, sticky="e", pady=3, padx=(4, 0))
        self.ent_crm_assigned = ttk.Entry(form, width=26)
        self.ent_crm_assigned.grid(row=1, column=0, sticky="ew", pady=3, padx=4)

        ttk.Label(form, text="ارزش برآوردی (تومان):", anchor="e").grid(row=2, column=1, sticky="e", pady=3, padx=(4, 0))
        self.ent_crm_deal_val = ttk.Entry(form, width=26)
        self.ent_crm_deal_val.grid(row=2, column=0, sticky="ew", pady=3, padx=4)

        ttk.Label(form, text="موعد پیگیری بعدی:", anchor="e").grid(row=3, column=1, sticky="e", pady=3, padx=(4, 0))
        self.ent_crm_followup_date = ttk.Entry(form, width=26)
        self.ent_crm_followup_date.grid(row=3, column=0, sticky="ew", pady=3, padx=4)

        ttk.Label(form, text="یادداشت پرونده:", anchor="ne").grid(row=4, column=1, sticky="ne", pady=3, padx=(4, 0))
        self.txt_crm_lead_notes = tk.Text(
            form,
            height=3,
            font=self.font_default,
            wrap=tk.WORD,
            bg=THEME["bg_input"],
            fg=THEME["text_white"],
            insertbackground=THEME["signal"],
            relief=tk.FLAT,
            bd=0,
            highlightthickness=1,
            highlightbackground=THEME["border"],
            highlightcolor=THEME["signal"],
        )
        self.txt_crm_lead_notes.grid(row=4, column=0, sticky="ew", pady=3, padx=4)

        form.grid_columnconfigure(0, weight=1)

        btn_save_status = create_modern_button(
            sub_pipeline,
            text="💾 ذخیره تغییرات مرحله و پرونده",
            bg=THEME["signal"],
            hover_bg=THEME["signal_hover"],
            active_bg=THEME["signal_active"],
            fg=THEME["text_white"],
            font=self.font_bold,
            padx=10,
            pady=5,
            command=self._save_crm_status_changes,
        )
        btn_save_status.pack(fill=tk.X, pady=(2, 6))

        # Contextual Sales Tip Box (Website Red/Black Architectural Theme)
        self.tip_frame = tk.Frame(
            sub_pipeline,
            bg=THEME["bg_tip"],
            relief=tk.SOLID,
            bd=1,
            highlightbackground=THEME["border_tip"],
            highlightthickness=1,
            padx=10,
            pady=8,
        )
        self.tip_frame.pack(fill=tk.BOTH, expand=True, pady=4)

        tip_title = tk.Label(
            self.tip_frame,
            text="💡 فوت‌وفن فروش نوآوران پنجره در این مرحله:",
            font=self.font_bold,
            fg="#f87171",
            bg=THEME["bg_tip"],
            anchor="e",
        )
        tip_title.pack(anchor="e")

        self.lbl_crm_sales_tip = tk.Label(
            self.tip_frame,
            text="با انتخاب مرحله، نکات و استراتژی‌های فروش مهندسی نوآوران پنجره نمایش داده می‌شود.",
            font=self.font_small,
            fg=THEME["text_copper"],
            bg=THEME["bg_tip"],
            justify=tk.RIGHT,
            anchor="e",
            wraplength=380,
        )
        self.lbl_crm_sales_tip.pack(anchor="e", pady=(4, 0), fill=tk.BOTH, expand=True)

        # SubTab 2: SMS & Email Center
        sub_comm = ttk.Frame(self.crm_notebook, padding=8)
        self.crm_notebook.add(sub_comm, text="💬 مرکز پیامک و ایمیل (ارتباط سریع)")

        ttk.Label(sub_comm, text="انتخاب الگوی ارتباطی:", font=self.font_bold, anchor="e").pack(anchor="e")
        self.cmb_crm_template = ttk.Combobox(sub_comm, state="readonly", width=40)
        self.cmb_crm_template.pack(fill=tk.X, pady=(2, 6))
        self.cmb_crm_template.bind("<<ComboboxSelected>>", self._on_crm_template_selected)

        ttk.Label(sub_comm, text="موضوع ایمیل (فقط برای ایمیل):", font=self.font_small, anchor="e").pack(anchor="e")
        self.ent_crm_template_subj = ttk.Entry(sub_comm)
        self.ent_crm_template_subj.pack(fill=tk.X, pady=(1, 4))

        ttk.Label(sub_comm, text="متن ارسالی (قابل ویرایش قبل از کپی یا ارسال):", font=self.font_small, anchor="e").pack(anchor="e")
        self.txt_crm_template_content = scrolledtext.ScrolledText(
            sub_comm,
            height=6,
            font=self.font_default,
            wrap=tk.WORD,
            bg=THEME["bg_input"],
            fg=THEME["text_white"],
            insertbackground=THEME["signal"],
            relief=tk.FLAT,
            bd=0,
            highlightthickness=1,
            highlightbackground=THEME["border"],
            highlightcolor=THEME["signal"],
        )
        self.txt_crm_template_content.pack(fill=tk.BOTH, expand=True, pady=(2, 6))

        comm_actions = ttk.Frame(sub_comm)
        comm_actions.pack(fill=tk.X)

        btn_copy_sms = create_modern_button(
            comm_actions,
            text="📱 کپی متن پیامک و ثبت در سوابق",
            bg="#0f766e",
            hover_bg="#115e59",
            fg=THEME["text_white"],
            font=self.font_bold,
            padx=8,
            pady=4,
            command=self._copy_crm_sms_and_log,
        )
        btn_copy_sms.pack(side=tk.RIGHT, padx=(4, 0))

        btn_send_mail = create_modern_button(
            comm_actions,
            text="✉️ باز کردن ایمیل (Mailto) و ثبت در سوابق",
            bg=THEME["signal"],
            hover_bg=THEME["signal_hover"],
            fg=THEME["text_white"],
            font=self.font_bold,
            padx=8,
            pady=4,
            command=self._send_crm_email_and_log,
        )
        btn_send_mail.pack(side=tk.RIGHT, padx=4)

        # SubTab 3: Activity Timeline
        sub_timeline = ttk.Frame(self.crm_notebook, padding=8)
        self.crm_notebook.add(sub_timeline, text="📜 تاریخچه و لاگ فعالیت‌ها")

        act_frame = ttk.Frame(sub_timeline)
        act_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 6))

        act_cols = ("date", "type", "summary")
        self.tree_crm_activities = ttk.Treeview(act_frame, columns=act_cols, show="headings", height=5)
        self.tree_crm_activities.heading("date", text="تاریخ و زمان")
        self.tree_crm_activities.heading("type", text="نوع فعالیت")
        self.tree_crm_activities.heading("summary", text="شرح رویداد")
        self.tree_crm_activities.column("date", width=120, anchor="center")
        self.tree_crm_activities.column("type", width=90, anchor="center")
        self.tree_crm_activities.column("summary", width=220, anchor="e")

        self.tree_crm_activities.tag_configure("evenrow", background=THEME["bg_tree_row"], foreground=THEME["text_white"])
        self.tree_crm_activities.tag_configure("oddrow", background=THEME["bg_tree_alt"], foreground=THEME["text_white"])

        act_vsb = ttk.Scrollbar(act_frame, orient=tk.VERTICAL, command=self.tree_crm_activities.yview)
        self.tree_crm_activities.configure(yscrollcommand=act_vsb.set)
        self.tree_crm_activities.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        act_vsb.pack(side=tk.RIGHT, fill=tk.Y)

        # Add Activity Form (RTL)
        add_box = ttk.LabelFrame(sub_timeline, text="ثبت فعالیت جدید در پرونده", padding=6)
        add_box.pack(fill=tk.X)

        act_in_f = ttk.Frame(add_box)
        act_in_f.pack(fill=tk.X, pady=2)

        ttk.Label(act_in_f, text="نوع:").pack(side=tk.RIGHT, padx=(4, 2))
        self.cmb_new_act_type = ttk.Combobox(
            act_in_f,
            values=["تماس تلفنی", "پیامک ارسالی", "ایمیل ارسالی", "جلسه حضوری", "بازدید کارگاه", "صدور پیش‌فاکتور", "یادداشت داخلی"],
            state="readonly",
            width=14,
        )
        self.cmb_new_act_type.current(0)
        self.cmb_new_act_type.pack(side=tk.RIGHT, padx=2)

        ttk.Label(act_in_f, text="خلاصه:").pack(side=tk.RIGHT, padx=(6, 2))
        self.ent_new_act_summary = ttk.Entry(act_in_f, width=28)
        self.ent_new_act_summary.pack(side=tk.RIGHT, fill=tk.X, expand=True, padx=2)

        btn_add_act = create_modern_button(act_in_f, text="➕ ثبت فعالیت", bg=THEME["signal"], hover_bg=THEME["signal_hover"], font=self.font_bold, padx=8, pady=3, command=self._add_crm_manual_activity)
        btn_add_act.pack(side=tk.LEFT, padx=(4, 0))

        # Leads list panel (Right side)
        left_frame = ttk.Frame(paned)
        paned.add(left_frame, weight=3)

        cols = ("title", "type", "city", "phone", "stage", "deal", "follow_up")
        self.tree_crm = ttk.Treeview(left_frame, columns=cols, show="headings", selectmode="browse")

        col_defs = [
            ("title", "عنوان سرنخ / پروژه / شخص", 160, "e"),
            ("type", "نوع", 80, "center"),
            ("city", "شهر", 70, "center"),
            ("phone", "شماره تماس", 105, "center"),
            ("stage", "مرحله فروش", 130, "e"),
            ("deal", "ارزش (تومان)", 85, "center"),
            ("follow_up", "موعد پیگیری", 85, "center"),
        ]
        for c_id, c_name, c_w, c_anchor in col_defs:
            self.tree_crm.heading(c_id, text=c_name, command=lambda c=c_id: self._sort_tree(self.tree_crm, self.crm_sort_state, c))
            self.tree_crm.column(c_id, width=c_w, minwidth=60, anchor=c_anchor)

        self.tree_crm.tag_configure("evenrow", background=THEME["bg_tree_row"], foreground=THEME["text_white"])
        self.tree_crm.tag_configure("oddrow", background=THEME["bg_tree_alt"], foreground=THEME["text_white"])

        vsb = ttk.Scrollbar(left_frame, orient=tk.VERTICAL, command=self.tree_crm.yview)
        hsb = ttk.Scrollbar(left_frame, orient=tk.HORIZONTAL, command=self.tree_crm.xview)
        self.tree_crm.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        self.tree_crm.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        left_frame.grid_rowconfigure(0, weight=1)
        left_frame.grid_columnconfigure(0, weight=1)

        self.tree_crm.bind("<<TreeviewSelect>>", self._on_crm_lead_selected)

    def _build_statusbar(self):
        status_frame = tk.Frame(self.root, bg=THEME["bg_dark"], height=28, relief=tk.FLAT, bd=0)
        status_frame.pack(side=tk.BOTTOM, fill=tk.X)

        # Subtle top accent line (brand crimson)
        top_line = tk.Frame(status_frame, bg=THEME["border"], height=1)
        top_line.pack(side=tk.TOP, fill=tk.X)

        inner_status = tk.Frame(status_frame, bg=THEME["bg_dark"])
        inner_status.pack(side=tk.TOP, fill=tk.X, expand=True)

        self.lbl_status_left = tk.Label(inner_status, text=f"Noavaran Scraper | DB: {os.path.basename(self.db_path)}", font=self.font_small, bg=THEME["bg_dark"], fg=THEME["text_dim"])
        self.lbl_status_left.pack(side=tk.LEFT, padx=12, pady=3)

        self.lbl_status_right = tk.Label(inner_status, text="آماده به کار (Ready)", font=self.font_small, bg=THEME["bg_dark"], fg=THEME["text_copper"], anchor="e")
        self.lbl_status_right.pack(side=tk.RIGHT, padx=12, pady=3)

    # ========================== Data Loading & Stats ==========================

    def _initial_load(self):
        if self.stop_event.is_set():
            return
        try:
            if not self.root.winfo_exists():
                return
        except Exception:
            return
        self._refresh_stats()
        self._load_contacts_from_db()
        self._load_projects_from_db()
        self._load_reviews_from_db()
        self._load_crm_from_db()
        self._append_log("✨ سامانه هوشمند کشف سرنخ نوآوران پنجره آماده است.", tag="success")
        self._append_log(f"📁 پایگاه داده در حال استفاده: {self.db_path}", tag="dim")

    def _refresh_stats(self):
        try:
            stats = get_cache_stats(self.db_path)
            self.lbl_stat_contacts.config(text=str(stats["contacts"]))
            self.lbl_stat_projects.config(text=str(stats["projects"]))
            self.lbl_stat_raw.config(text=str(stats["raw_records"]))
            self.lbl_stat_reviews.config(text=str(stats["ambiguous_reviews"]))
        except Exception as e:
            self._append_log(f"خطا در دریافت آمار: {e}", tag="error")

    def _load_contacts_from_db(self):
        try:
            self.contacts_cache = get_all_contacts(self.db_path)
            self._filter_contacts()
        except Exception as e:
            self._append_log(f"خطا در بارگذاری لیست مخاطبین: {e}", tag="error")

    def _load_projects_from_db(self):
        try:
            self.projects_cache = get_all_projects(self.db_path)
            self._filter_projects()
        except Exception as e:
            self._append_log(f"خطا در بارگذاری لیست پروژه‌ها: {e}", tag="error")

    def _load_reviews_from_db(self):
        try:
            self.reviews_cache = get_ambiguous_reviews(self.db_path)
            self.tree_reviews.delete(*self.tree_reviews.get_children())
            for rev in self.reviews_cache:
                self.tree_reviews.insert(
                    "",
                    tk.END,
                    values=(
                        rev["id"],
                        rev["candidate_type"],
                        f"{rev['match_score']:.1f}%",
                        rev["match_reason"],
                        rev["existing_id"][:12] + "...",
                        rev.get("created_at", "")[:19].replace("T", " "),
                    ),
                    tags=("review_row",)
                )
        except Exception as e:
            self._append_log(f"خطا در بارگذاری برخوردهای مبهم: {e}", tag="error")

    CRM_STAGE_LABELS = {
        "new": "سرنخ جدید",
        "qualified": "تماس اولیه و ارزیابی",
        "drawings": "دریافت نقشه‌های فاز ۲",
        "quoted": "صدور پیش‌فاکتور مهندسی",
        "negotiation": "جلسه حضوری و بازدید",
        "won": "عقد قرارداد و تولید",
        "lost": "انصراف / رد شده",
    }

    CRM_STAGE_TIPS = {
        "new": "💡 راهنمای فروش نوآوران پنجره: در اولین تماس به هیچ وجه اصرار بر فروش نکنید؛ صرفاً تخصص نوآوران پنجره در سیستم‌های ترمال‌بریک و کرتین‌وال را معرفی و لینک کاتالوگ مهندسی را ارسال نمایید تا پیش‌زمینه فنی شکل گیرد.",
        "qualified": "💡 راهنمای فروش نوآوران پنجره: بررسی کنید پروژه در چه مرحله‌ای است (اسکلت یا نازک‌کاری)؟ تقاضای ارسال فایل اتوکد فاز ۲ و تیپ‌بندی بازشوها را جهت برآورد متراژ و ابعاد مطرح فرمایید.",
        "drawings": "💡 راهنمای فروش نوآوران پنجره: محاسبات دقیق ممان اینرسی، بار باد و ضخامت شیشه‌ها (دوجداره لمینت/گاز آرگون) را انجام دهید. سیستم‌های لیفت‌اند‌اسلاید یا لولایی متناسب با ابعاد دهانه‌ها پیشنهاد گردد.",
        "quoted": "💡 راهنمای فروش نوآوران پنجره: پیش‌فاکتور تفکیکی به همراه دفترچه مشخصات فنی (برند پروفیل آکپا/رینرز، یراق‌آلات اروپایی) ارسال شود. حداکثر ظرف ۴۸ ساعت جهت رفع ابهامات فنی پیگیری تلفنی فرمایید.",
        "negotiation": "💡 راهنمای فروش نوآوران پنجره: بهترین روش تصمیم‌گیری نهایی کارفرما و معمار، دعوت به شوروم و خط تولید نوآوران پنجره یا نمایش نمونه مقطع واقعی (Corner Sample) در کارگاه است.",
        "won": "💡 راهنمای فروش نوآوران پنجره: نقشه‌های نهایی تولید (شاپ‌دراوینگ) به امضای معمار و کارفرما برسد. برنامه زمانبندی ارسال فریم‌های آهنی و پنجره‌ها با کارگاه هماهنگ شود.",
        "lost": "💡 علت انصراف (قیمت، انتخاب پیمانکار دیگر، تغییر کاربری یا تاخیر پروژه) را ثبت نمایید تا در کمپین‌های بازگشت مشتری یا مشاوره‌های آتی استفاده گردد."
    }

    def _load_crm_from_db(self):
        try:
            self.crm_items_cache = get_crm_pipeline_items(db_path=self.db_path)
            self._filter_crm_items()
            # Load templates
            self._crm_templates = get_crm_templates(db_path=self.db_path)
            template_titles = [f"{t['id']}: {t['title']}" for t in self._crm_templates]
            self.cmb_crm_template["values"] = template_titles
            if template_titles:
                self.cmb_crm_template.current(0)
                self._on_crm_template_selected()
        except Exception as e:
            self._append_log(f"خطا در بارگذاری اطلاعات CRM: {e}", tag="error")

    def _filter_crm_items(self):
        query = normalize_persian_text(self.ent_crm_search.get()).strip().lower()
        filter_stage = self.cmb_crm_filter_stage.get()

        selected_code = "all"
        if filter_stage and ":" in filter_stage:
            selected_code = filter_stage.split(":")[0].strip()

        self.tree_crm.delete(*self.tree_crm.get_children())
        shown = 0

        for item in self.crm_items_cache:
            if selected_code != "all" and item["stage"] != selected_code:
                continue

            if query:
                search_blob = normalize_persian_text(
                    f"{item.get('title', '')} {item.get('company', '')} {item.get('city', '')} {item.get('phone', '')} {item.get('notes', '')}"
                ).lower()
                if query not in search_blob:
                    continue

            stage_text = self.CRM_STAGE_LABELS.get(item["stage"], item["stage"])
            deal_str = f"{item.get('deal_value', 0):,}" if item.get('deal_value') else "-"
            self.tree_crm.insert(
                "",
                tk.END,
                iid=item["lead_id"],
                values=(
                    item.get("title", ""),
                    item.get("subtitle", ""),
                    item.get("city", ""),
                    item.get("phone", ""),
                    stage_text,
                    deal_str,
                    item.get("follow_up_date", "") or "-",
                )
            )
            shown += 1

        self.lbl_crm_count.config(text=f"تعداد سرنخ‌ها: {shown} از {len(self.crm_items_cache)}")

    def _on_crm_lead_selected(self, event=None):
        selection = self.tree_crm.selection()
        if not selection:
            return
        lead_id = selection[0]
        item = next((x for x in self.crm_items_cache if x["lead_id"] == lead_id), None)
        if not item:
            return

        self.selected_crm_item = item

        # Update header card
        self.lbl_crm_active_title.config(text=f"{item.get('title', 'نامشخص')} ({item.get('subtitle', '')})")
        details_sub = f"شرکت: {item.get('company') or '-'} | شهر: {item.get('city') or '-'} | تماس: {item.get('phone') or '-'} | ایمیل: {item.get('email') or '-'}"
        self.lbl_crm_active_subtitle.config(text=details_sub)

        # Get latest CRM status from DB
        status = get_lead_crm_status(lead_id, db_path=self.db_path)
        current_stage = status.get("stage", "new") if status else item.get("stage", "new")
        assigned = status.get("assigned_to", "واحد مهندسی فروش") if status else item.get("assigned_to", "واحد مهندسی فروش")
        deal_val = status.get("deal_value", 0) if status else item.get("deal_value", 0)
        follow_up = status.get("follow_up_date", "") if status else item.get("follow_up_date", "")
        notes = status.get("notes", "") if status else item.get("notes", "")

        # Set stage dropdown
        for i, val in enumerate(self.cmb_crm_lead_stage["values"]):
            if val.startswith(f"{current_stage}:"):
                self.cmb_crm_lead_stage.current(i)
                break

        self.ent_crm_assigned.delete(0, tk.END)
        self.ent_crm_assigned.insert(0, assigned or "")

        self.ent_crm_deal_val.delete(0, tk.END)
        self.ent_crm_deal_val.insert(0, str(deal_val) if deal_val else "0")

        self.ent_crm_followup_date.delete(0, tk.END)
        self.ent_crm_followup_date.insert(0, follow_up or "")

        self.txt_crm_lead_notes.delete("1.0", tk.END)
        if notes:
            self.txt_crm_lead_notes.insert("1.0", notes)

        # Update contextual sales tip
        self._update_sales_tip(current_stage)

        # Load activities
        self._load_crm_activities(lead_id)

        # Update template preview with active lead interpolation
        self._on_crm_template_selected()

    def _on_crm_stage_dropdown_change(self, event=None):
        val = self.cmb_crm_lead_stage.get()
        if ":" in val:
            stage_code = val.split(":")[0].strip()
            self._update_sales_tip(stage_code)

    def _update_sales_tip(self, stage_code: str):
        tip_text = self.CRM_STAGE_TIPS.get(stage_code, "نکته‌ای برای این مرحله ثبت نشده است.")
        self.lbl_crm_sales_tip.config(text=tip_text)

    def _load_crm_activities(self, lead_id: str):
        try:
            self.tree_crm_activities.delete(*self.tree_crm_activities.get_children())
            acts = get_crm_activities(lead_id, db_path=self.db_path)
            for a in acts:
                self.tree_crm_activities.insert(
                    "",
                    tk.END,
                    values=(
                        a.get("created_at", "")[:19].replace("T", " "),
                        a.get("activity_type", ""),
                        a.get("summary", ""),
                    )
                )
        except Exception as e:
            self._append_log(f"خطا در دریافت تاریخچه فعالیت‌ها: {e}", tag="error")

    def _save_crm_status_changes(self):
        if not self.selected_crm_item:
            messagebox.showwarning("انتخاب سرنخ", "لطفاً ابتدا یک سرنخ را از جدول انتخاب نمایید.")
            return

        lead_id = self.selected_crm_item["lead_id"]
        lead_type = self.selected_crm_item.get("lead_type", "contact")

        stage_val = self.cmb_crm_lead_stage.get()
        stage_code = stage_val.split(":")[0].strip() if ":" in stage_val else "new"

        assigned_to = self.ent_crm_assigned.get().strip() or "واحد مهندسی فروش"
        try:
            deal_val = int(re.sub(r"[^\d]", "", self.ent_crm_deal_val.get() or "0"))
        except Exception:
            deal_val = 0

        follow_up = self.ent_crm_followup_date.get().strip()
        notes = self.txt_crm_lead_notes.get("1.0", tk.END).strip()

        try:
            save_lead_crm_status(
                lead_id=lead_id,
                stage=stage_code,
                lead_type=lead_type,
                assigned_to=assigned_to,
                deal_value=deal_val,
                follow_up_date=follow_up,
                notes=notes,
                db_path=self.db_path,
            )

            stage_name = self.CRM_STAGE_LABELS.get(stage_code, stage_code)
            add_crm_activity(
                lead_id=lead_id,
                activity_type="تغییر وضعیت",
                summary=f"تغییر مرحله فروش به '{stage_name}' | ارزش: {deal_val:,} تومان",
                details=notes,
                db_path=self.db_path,
            )

            self.selected_crm_item["stage"] = stage_code
            self.selected_crm_item["assigned_to"] = assigned_to
            self.selected_crm_item["deal_value"] = deal_val
            self.selected_crm_item["follow_up_date"] = follow_up
            self.selected_crm_item["notes"] = notes

            self._filter_crm_items()
            self._load_crm_activities(lead_id)
            messagebox.showinfo("ذخیره شد", f"وضعیت پرونده {self.selected_crm_item.get('title', '')} با موفقیت به‌روزرسانی شد.")
        except Exception as e:
            messagebox.showerror("خطا در ذخیره", f"خطا در ثبت تغییرات پرونده: {e}")

    def _copy_crm_phone(self):
        if not self.selected_crm_item:
            return
        phone = self.selected_crm_item.get("phone", "")
        if not phone:
            messagebox.showinfo("اطلاعات تماس", "شماره تلفنی برای این سرنخ ثبت نشده است.")
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(phone)
        messagebox.showinfo("کپی شد", f"شماره تماس {phone} در کلیپ‌بورد کپی شد.")

    def _open_crm_source_url(self):
        if not self.selected_crm_item:
            return
        url = self.selected_crm_item.get("source_url", "")
        if not url:
            messagebox.showinfo("منبع", "آدرس اینترنتی برای این رکورد موجود نیست.")
            return
        first_url = url.split(" | ")[0].strip()
        try:
            webbrowser.open(first_url)
        except Exception as e:
            messagebox.showerror("خطا", f"امکان باز کردن لینک وجود ندارد: {e}")

    def _on_crm_template_selected(self, event=None):
        if not hasattr(self, "_crm_templates") or not self._crm_templates:
            return

        idx = self.cmb_crm_template.current()
        if idx < 0 or idx >= len(self._crm_templates):
            return

        tpl = self._crm_templates[idx]
        name = "محترم"
        company = "پروژه ساختمانی"
        project = "ساختمانی"

        if self.selected_crm_item:
            name = self.selected_crm_item.get("title", "") or "مهندس گرامی"
            company = self.selected_crm_item.get("company", "") or self.selected_crm_item.get("title", "")
            project = self.selected_crm_item.get("title", "") or "جاری"

        subj = tpl.get("subject", "").replace("{name}", name).replace("{company}", company).replace("{project}", project)
        content = tpl.get("content", "").replace("{name}", name).replace("{company}", company).replace("{project}", project)

        self.ent_crm_template_subj.delete(0, tk.END)
        self.ent_crm_template_subj.insert(0, subj)

        self.txt_crm_template_content.delete("1.0", tk.END)
        self.txt_crm_template_content.insert("1.0", content)

    def _copy_crm_sms_and_log(self):
        if not self.selected_crm_item:
            messagebox.showwarning("انتخاب سرنخ", "لطفاً ابتدا یک سرنخ را انتخاب فرمایید.")
            return

        text = self.txt_crm_template_content.get("1.0", tk.END).strip()
        if not text:
            messagebox.showwarning("متن خالی", "متن پیامک خالی است.")
            return

        self.root.clipboard_clear()
        self.root.clipboard_append(text)

        lead_id = self.selected_crm_item["lead_id"]
        tpl_title = self.cmb_crm_template.get()
        add_crm_activity(
            lead_id=lead_id,
            activity_type="پیامک",
            summary=f"کپی متن پیامک به کلیپ‌بورد ({tpl_title[:30]})",
            details=text[:150],
            db_path=self.db_path,
        )
        self._load_crm_activities(lead_id)
        messagebox.showinfo("پیامک آماده شد", "متن پیامک در کلیپ‌بورد کپی شد و در تاریخچه پرونده ثبت گردید.\nمی‌توانید آن را در پنل پیامک یا پیام‌رسان جای‌گذاری (Paste) فرمایید.")

    def _send_crm_email_and_log(self):
        if not self.selected_crm_item:
            messagebox.showwarning("انتخاب سرنخ", "لطفاً ابتدا یک سرنخ را انتخاب فرمایید.")
            return

        email = self.selected_crm_item.get("email", "").strip()
        subj = self.ent_crm_template_subj.get().strip()
        body = self.txt_crm_template_content.get("1.0", tk.END).strip()

        encoded_subj = urllib.parse.quote(subj)
        encoded_body = urllib.parse.quote(body)
        mailto_url = f"mailto:{email}?subject={encoded_subj}&body={encoded_body}"

        try:
            webbrowser.open(mailto_url)
            lead_id = self.selected_crm_item["lead_id"]
            add_crm_activity(
                lead_id=lead_id,
                activity_type="ایمیل",
                summary=f"ارسال ایمیل: {subj[:40]}",
                details=body[:150],
                db_path=self.db_path,
            )
            self._load_crm_activities(lead_id)
            messagebox.showinfo("ایمیل باز شد", "نرم‌افزار ایمیل سیستم با متن و موضوع پیش‌فرض باز شد و رویداد در پرونده ثبت گردید.")
        except Exception as e:
            messagebox.showerror("خطا در ارسال ایمیل", f"امکان باز کردن نرم‌افزار ایمیل وجود ندارد: {e}")

    def _add_crm_manual_activity(self):
        if not self.selected_crm_item:
            messagebox.showwarning("انتخاب سرنخ", "لطفاً ابتدا یک سرنخ را از جدول انتخاب نمایید.")
            return

        act_type = self.cmb_new_act_type.get()
        summary = self.ent_new_act_summary.get().strip()
        if not summary:
            messagebox.showwarning("شرح خالی", "لطفاً شرح مختصری از فعالیت انجام شده را وارد فرمایید.")
            return

        lead_id = self.selected_crm_item["lead_id"]
        try:
            add_crm_activity(
                lead_id=lead_id,
                activity_type=act_type,
                summary=summary,
                details="",
                db_path=self.db_path,
            )
            self.ent_new_act_summary.delete(0, tk.END)
            self._load_crm_activities(lead_id)
            self._append_log(f"رویداد جدید '{summary}' برای سرنخ {self.selected_crm_item.get('title')} ثبت شد.", tag="success")
        except Exception as e:
            messagebox.showerror("خطا", f"خطا در ثبت فعالیت: {e}")

    # ========================== Auto-Update Logic ==========================

    def _check_updates_flow(self, interactive: bool = False):
        def worker():
            res = updater.check_for_updates()
            self.msg_queue.put(("update_check_result", (res, interactive)))
        threading.Thread(target=worker, daemon=True).start()

    def _start_download_and_install(self, download_url: str, asset_name: Optional[str] = None):
        dl_win = tk.Toplevel(self.root)
        dl_win.title("دریافت نسخه جدید نوآوران پنجره")
        dl_win.geometry("440x180")
        dl_win.configure(bg=THEME["bg_dark"])
        dl_win.resizable(False, False)
        dl_win.transient(self.root)
        dl_win.grab_set()

        lbl_head = tk.Label(
            dl_win,
            text="در حال دانلود نسخه جدید از مخزن گیت‌هاب...",
            font=self.font_header,
            fg=THEME["text_white"],
            bg=THEME["bg_dark"],
        )
        lbl_head.pack(pady=(18, 6))

        pbar = ttk.Progressbar(dl_win, orient=tk.HORIZONTAL, mode="determinate", maximum=100)
        pbar.pack(fill=tk.X, padx=24, pady=8)

        lbl_status = tk.Label(
            dl_win,
            text="در حال برقراری ارتباط با سرور...",
            font=self.font_small,
            fg=THEME["text_copper"],
            bg=THEME["bg_dark"],
        )
        lbl_status.pack(pady=(2, 8))

        def run_download():
            def on_progress(pct, downloaded, total):
                self.msg_queue.put(("update_download_progress", (pct, downloaded, total, pbar, lbl_status)))

            try:
                downloaded_file = updater.download_update(download_url, progress_callback=on_progress)
                self.msg_queue.put(("update_download_done", (downloaded_file, dl_win)))
            except Exception as e:
                self.msg_queue.put(("update_error", (str(e), dl_win)))

        threading.Thread(target=run_download, daemon=True).start()

    def _filter_contacts(self):
        query = normalize_persian_text(self.ent_search_contacts.get()).strip().lower()
        filter_type = self.cmb_filter_type.get()
        filter_city = self.cmb_filter_city.get()

        self.tree_contacts.delete(*self.tree_contacts.get_children())
        shown = 0

        for c in self.contacts_cache:
            # Type match
            if filter_type != "همه (All)" and c.entity_type != filter_type:
                continue

            # City match
            if filter_city != "همه (All)":
                c_city = (c.city or "").strip().lower()
                f_city = filter_city.strip().lower()
                if f_city == "other" and c_city in ("isfahan", "tehran"):
                    continue
                elif f_city in ("isfahan", "tehran") and c_city != f_city:
                    continue

            # Text query match across multiple fields with Persian normalization
            if query:
                search_blob = normalize_persian_text(
                    f"{c.name} {c.role} {c.company} {c.city} {c.phone} {c.email} {c.social_handle}"
                ).lower()
                if query not in search_blob:
                    continue

            self.tree_contacts.insert(
                "",
                tk.END,
                values=(
                    c.entity_type,
                    c.name,
                    c.role,
                    c.company,
                    c.city,
                    c.phone,
                    c.email,
                    c.confidence,
                    c.social_handle,
                    c.source_url,
                )
            )
            shown += 1

        self.lbl_contacts_count.config(text=f"نمایش {shown} از {len(self.contacts_cache)} مخاطب")

    def _filter_projects(self):
        query = normalize_persian_text(self.ent_search_projects.get()).strip().lower()
        filter_city = self.cmb_proj_city.get()

        self.tree_projects.delete(*self.tree_projects.get_children())
        shown = 0

        for p in self.projects_cache:
            if filter_city != "همه (All)":
                p_city = (p.city or "").strip().lower()
                f_city = filter_city.strip().lower()
                if f_city == "other" and p_city in ("isfahan", "tehran"):
                    continue
                elif f_city in ("isfahan", "tehran") and p_city != f_city:
                    continue

            if query:
                search_blob = normalize_persian_text(
                    f"{p.project_name} {p.associated_contractors} {p.associated_architects} {p.city} {p.scale_scope} {p.contact_info}"
                ).lower()
                if query not in search_blob:
                    continue

            self.tree_projects.insert(
                "",
                tk.END,
                values=(
                    p.project_name,
                    p.city,
                    p.scale_scope,
                    p.associated_contractors,
                    p.associated_architects,
                    p.contact_info,
                    p.confidence,
                    p.date_found,
                    p.source_url,
                )
            )
            shown += 1

        self.lbl_projects_count.config(text=f"نمایش {shown} از {len(self.projects_cache)} پروژه")

    # ========================== Selection Handlers ==========================

    def _on_contact_selected(self, event):
        sel = self.tree_contacts.selection()
        if not sel:
            return
        vals = self.tree_contacts.item(sel[0], "values")
        if not vals:
            return
        text = (
            f"نام: {vals[1]} | نقش: {vals[2]} | شرکت: {vals[3]} | شهر: {vals[4]}\n"
            f"شماره تماس: {vals[5]}\n"
            f"ایمیل: {vals[6]} | شبکه‌های اجتماعی: {vals[8]}\n"
            f"آدرس منبع (URL): {vals[9]}"
        )
        self.txt_contact_detail.delete("1.0", tk.END)
        self.txt_contact_detail.insert("1.0", text)

    def _on_project_selected(self, event):
        sel = self.tree_projects.selection()
        if not sel:
            return
        vals = self.tree_projects.item(sel[0], "values")
        if not vals:
            return
        text = (
            f"نام پروژه: {vals[0]} | شهر: {vals[1]} | مقیاس: {vals[2]}\n"
            f"پیمانکار(ان) مرتبط: {vals[3]}\n"
            f"معمار(ان) / مشاور: {vals[4]}\n"
            f"اطلاعات تماس: {vals[5]} | منبع: {vals[8]}"
        )
        self.txt_project_detail.delete("1.0", tk.END)
        self.txt_project_detail.insert("1.0", text)

    def _on_review_selected(self, event):
        sel = self.tree_reviews.selection()
        if not sel:
            return
        vals = self.tree_reviews.item(sel[0], "values")
        if not vals:
            return
        rev_id = int(vals[0])
        match_item = next((r for r in self.reviews_cache if r["id"] == rev_id), None)
        if match_item:
            try:
                parsed_json = json.loads(match_item["candidate_json"])
                pretty = json.dumps(parsed_json, indent=2, ensure_ascii=False)
            except Exception:
                parsed_json = {}
                pretty = match_item["candidate_json"]

            c_type = match_item.get("candidate_type", "contact")
            exist_id = match_item.get("existing_id", "")
            score = match_item.get("match_score", 0.0)
            reason = match_item.get("match_reason", "")

            # Look up existing record from database
            existing_info = "رکورد متناظر در دیتابیس یافت نشد (یا ممکن است قبلاً حذف شده باشد)."
            if c_type == "contact" and exist_id:
                existing_c = get_contact_by_id(exist_id, self.db_path)
                if existing_c:
                    existing_info = (
                        f"• شناسه: {existing_c.id}\n"
                        f"• نام: {existing_c.name} | شرکت: {existing_c.company}\n"
                        f"• نقش: {existing_c.role} | نوع: {existing_c.entity_type} | شهر: {existing_c.city}\n"
                        f"• شماره تماس: {existing_c.phone} | ایمیل: {existing_c.email}\n"
                        f"• شبکه‌های اجتماعی: {existing_c.social_handle}\n"
                        f"• لینک منبع: {existing_c.source_url}\n"
                        f"• درجه اطمینان: {existing_c.confidence} | آخرین بررسی: {existing_c.last_verified}"
                    )
            elif c_type == "project" and exist_id:
                existing_p = get_project_by_id(exist_id, self.db_path)
                if existing_p:
                    existing_info = (
                        f"• شناسه: {existing_p.id}\n"
                        f"• نام پروژه: {existing_p.project_name} | شهر: {existing_p.city}\n"
                        f"• مقیاس و مشخصات: {existing_p.scale_scope}\n"
                        f"• پیمانکار(ان): {existing_p.associated_contractors}\n"
                        f"• معمار(ان) / مشاور: {existing_p.associated_architects}\n"
                        f"• اطلاعات تماس: {existing_p.contact_info}\n"
                        f"• لینک منبع: {existing_p.source_url}"
                    )

            # Format candidate summary
            cand_name = parsed_json.get("name") or parsed_json.get("project_name", "-")
            cand_comp = parsed_json.get("company") or parsed_json.get("associated_contractors", "-")
            cand_role = parsed_json.get("role") or parsed_json.get("scale_scope", "-")
            cand_city = parsed_json.get("city", "-")
            cand_phone = parsed_json.get("phone") or parsed_json.get("contact_info", "-")
            cand_email = parsed_json.get("email", "-")
            cand_src = parsed_json.get("source_url", "-")

            candidate_info = (
                f"• نام / پروژه: {cand_name} | شرکت / پیمانکار: {cand_comp}\n"
                f"• نقش / مقیاس: {cand_role} | شهر: {cand_city}\n"
                f"• شماره تماس: {cand_phone} | ایمیل: {cand_email}\n"
                f"• لینک منبع: {cand_src}"
            )

            detail_text = (
                f"=== مشخصات رکورد موجود در دیتابیس (Existing Record in Database) ===\n"
                f"{existing_info}\n\n"
                f"=== کاندیدای کشف شده جدید (Candidate Discovered Record) ===\n"
                f"امتیاز شباهت فازی: {score:.1f}% | علت بازبینی: {reason}\n"
                f"{candidate_info}\n\n"
                f"=== محتوای خام JSON کاندید (Candidate Raw JSON Payload) ===\n"
                f"{pretty}"
            )

            self.txt_review_detail.delete("1.0", tk.END)
            self.txt_review_detail.insert("1.0", detail_text)

    # ========================== Interactive Actions ==========================

    def _copy_selected_contact_phone(self):
        sel = self.tree_contacts.selection()
        if sel:
            vals = self.tree_contacts.item(sel[0], "values")
            phone = vals[5]
            if phone:
                self.root.clipboard_clear()
                self.root.clipboard_append(phone)
                self._append_log(f"شماره تماس کپی شد: {phone}", tag="info")

    def _copy_selected_contact_email(self):
        sel = self.tree_contacts.selection()
        if sel:
            vals = self.tree_contacts.item(sel[0], "values")
            email = vals[6]
            if email:
                self.root.clipboard_clear()
                self.root.clipboard_append(email)
                self._append_log(f"ایمیل کپی شد: {email}", tag="info")

    def _open_selected_contact_url(self):
        sel = self.tree_contacts.selection()
        if sel:
            vals = self.tree_contacts.item(sel[0], "values")
            urls = vals[9].split(";")
            if urls and urls[0].strip():
                webbrowser.open(urls[0].strip())

    def _copy_selected_project_info(self):
        sel = self.tree_projects.selection()
        if sel:
            vals = self.tree_projects.item(sel[0], "values")
            text = f"پروژه: {vals[0]} | پیمانکار: {vals[3]} | معمار: {vals[4]} | تماس: {vals[5]}"
            self.root.clipboard_clear()
            self.root.clipboard_append(text)
            self._append_log("مشخصات پروژه در حافظه کپی شد.", tag="info")

    def _open_selected_project_url(self):
        sel = self.tree_projects.selection()
        if sel:
            vals = self.tree_projects.item(sel[0], "values")
            urls = vals[8].split(";")
            if urls and urls[0].strip():
                webbrowser.open(urls[0].strip())

    def _sort_tree(self, tree: ttk.Treeview, sort_state: dict, col: str):
        rev = sort_state.get(col, False)
        items = [(tree.set(k, col), k) for k in tree.get_children("")]

        def sort_key(t):
            val = (t[0] or "").replace("%", "").strip()
            try:
                return (0, float(val))
            except ValueError:
                return (1, (t[0] or "").lower())

        items.sort(key=sort_key, reverse=rev)

        for index, (_, k) in enumerate(items):
            tree.move(k, "", index)
        sort_state[col] = not rev

    # ========================== Background Task Execution ==========================

    def _set_busy_state(self, busy: bool, status_text: str = ""):
        self.is_busy = busy
        if busy:
            self.btn_run.config(state=tk.DISABLED, bg="#4a000a")
            self.btn_stop.config(state=tk.NORMAL, bg="#d1001c")
            self.btn_rebuild.config(state=tk.DISABLED)
            self.btn_benchmark.config(state=tk.DISABLED)
            self.lbl_status_left.config(text=status_text or "در حال اجرا...", fg="#f87171")
            self.crawl_status_lbl.config(text=status_text or "در حال اجرا...")
        else:
            self.btn_run.config(state=tk.NORMAL, bg="#ab0017")
            self.btn_stop.config(state=tk.DISABLED, bg="#4a000a")
            self.btn_rebuild.config(state=tk.NORMAL)
            self.btn_benchmark.config(state=tk.NORMAL)
            self.lbl_status_left.config(text="آماده به کار (Idle)", fg="#e3e4e6")
            self.crawl_status_lbl.config(text="آماده به کار (Idle)")
            self.progressbar["value"] = 0

    def _on_toggle_autorun(self):
        enable = self.var_autorun.get()
        auto_crawl = self.var_autorun_crawl.get()
        ok, msg = autorun.set_autorun(enable=enable, auto_crawl=auto_crawl)
        if ok:
            status_text = "وضعیت: فعال در استارت‌آپ ویندوز (Active)" if enable else "وضعیت: غیرفعال (Disabled)"
            status_color = "#16a34a" if enable else "#64748b"
            self.lbl_autorun_status.config(text=status_text, fg=status_color)
            self._append_log(f"⚙️ {msg}", tag="success" if enable else "dim")
        else:
            messagebox.showerror("خطای تغییر استارت‌آپ", msg)
            self.var_autorun.set(not enable)

    def _auto_start_crawl_on_launch(self):
        self._append_log("🚀 اجرای خودکار روزانه فعال شد: آغاز خودکار پویش سرنخ‌ها و پروژه‌های جدید...", tag="success")
        self._on_start_crawler()

    def _on_start_crawler(self):
        if self.is_busy:
            return

        try:
            passes = int(self.spn_passes.get())
            streak = int(self.spn_streak.get())
            budget = int(self.spn_budget.get())
            tg = int(self.spn_tg.get())
            r_per_q = int(self.spn_results.get())
            frontier_m = int(self.spn_frontier.get())
            if passes <= 0 or streak <= 0 or budget <= 0 or tg <= 0 or r_per_q <= 0 or frontier_m < 0:
                raise ValueError("Values must be positive")
        except ValueError:
            messagebox.showerror("خطای ورودی", "لطفاً مقادیر عددی معتبر و مثبت در تنظیمات وارد نمایید.")
            return

        self.stop_event.clear()
        self._set_busy_state(True, "در حال آغاز پویشگر...")
        self._append_log("\n" + "=" * 60, tag="dim")
        self._append_log("🚀 آغاز فرآیند پویش خودکار با تنظیمات مشخص شده...", tag="info")

        def target():
            try:
                crawler = LeadDiscoveryCrawler(self.db_path)
                summary = crawler.run(
                    max_passes=passes,
                    streak_limit=streak,
                    time_budget_sec=budget,
                    max_telegram_channels=tg,
                    max_results_per_query=r_per_q,
                    max_frontier_items=frontier_m,
                    stop_event=self.stop_event,
                    log_fn=lambda m: self.msg_queue.put(("log", m)),
                    progress_fn=lambda pct, st: self.msg_queue.put(("progress", (pct, st))),
                )
                self.msg_queue.put(("crawl_done", summary))
            except Exception as ex:
                self.msg_queue.put(("error", str(ex)))

        self.worker_thread = threading.Thread(target=target, daemon=True)
        self.worker_thread.start()

    def _on_stop_crawler(self):
        if not self.is_busy:
            return
        self.stop_event.set()
        self._append_log("⏹ درخواست توقف ثبت شد. در حال تکمیل گام جاری...", tag="warning")
        self.lbl_status_left.config(text="در حال توقف...", fg="#dc2626")

    def _on_rebuild_cache(self):
        if self.is_busy:
            return
        if not messagebox.askyesno("تأیید بازسازی کش", "آیا از بازپردازش تمام رکوردهای خام و بازسازی کش دیتابیس و فایل‌های CSV اطمینان دارید؟"):
            return

        self.stop_event.clear()
        self._set_busy_state(True, "در حال بازپردازش رکوردهای خام...")
        self._append_log("\n" + "=" * 60, tag="dim")
        self._append_log("🔄 بازپردازش دیتابیس بر اساس آخرین الگوریتم‌های نرمال‌سازی و ضریب فازی...", tag="info")

        def target():
            try:
                crawler = LeadDiscoveryCrawler(self.db_path)
                stats = crawler.rebuild_cache_from_raw(
                    stop_event=self.stop_event,
                    log_fn=lambda m: self.msg_queue.put(("log", m)),
                    progress_fn=lambda pct, st: self.msg_queue.put(("progress", (pct, st))),
                )
                self.msg_queue.put(("rebuild_done", stats))
            except Exception as ex:
                self.msg_queue.put(("error", str(ex)))

        self.worker_thread = threading.Thread(target=target, daemon=True)
        self.worker_thread.start()

    def _on_run_benchmark(self):
        if self.is_busy:
            return
        self._set_busy_state(True, "در حال اجرای اعتبارسنجی بنچ‌مارک...")
        self._append_log("\n" + "=" * 60, tag="dim")
        self._append_log("🔍 ارزیابی در برابر نمونه‌های شناخته‌شده دفاتر و پیمانکاران اصفهان...", tag="info")

        def target():
            try:
                report = run_benchmark_audit(self.db_path)
                self.msg_queue.put(("benchmark_done", report))
            except Exception as ex:
                self.msg_queue.put(("error", str(ex)))

        self.worker_thread = threading.Thread(target=target, daemon=True)
        self.worker_thread.start()

    def _poll_queue(self):
        if self.stop_event.is_set():
            return
        try:
            if not self.root.winfo_exists():
                return
        except Exception:
            return
        try:
            while True:
                msg_type, payload = self.msg_queue.get_nowait()

                if msg_type == "log":
                    self._append_log(payload)

                elif msg_type == "progress":
                    pct, status = payload
                    self.progressbar["value"] = int(pct * 100)
                    self.crawl_status_lbl.config(text=status)
                    self.lbl_status_left.config(text=status)

                elif msg_type == "crawl_done":
                    self._set_busy_state(False)
                    is_cancelled = payload.get("cancelled", False)
                    if is_cancelled:
                        self._append_log("⏹ عملیات پویش توسط کاربر متوقف شد.", tag="warning")
                    else:
                        self._append_log("✅ پویش با موفقیت به پایان رسید.", tag="success")
                    self._append_log(f"خلاصه: +{payload.get('new_entities_this_run', 0)} رکورد جدید در {payload.get('duration_sec', 0)} ثانیه.", tag="info")
                    self._refresh_stats()
                    self._load_contacts_from_db()
                    self._load_projects_from_db()
                    self._load_reviews_from_db()
                    self._load_crm_from_db()
                    title = "توقف عملیات" if is_cancelled else "پایان عملیات"
                    status_msg = "عملیات توسط کاربر متوقف شد." if is_cancelled else "پویش به اتمام رسید."
                    messagebox.showinfo(title, f"{status_msg}\nرکوردهای جدید: {payload.get('new_entities_this_run', 0)}\nمدت زمان: {payload.get('duration_sec', 0)}s")

                elif msg_type == "rebuild_done":
                    self._set_busy_state(False)
                    self._append_log("✅ بازسازی کش کامل شد.", tag="success")
                    self._refresh_stats()
                    self._load_contacts_from_db()
                    self._load_projects_from_db()
                    self._load_reviews_from_db()
                    self._load_crm_from_db()
                    messagebox.showinfo("تکمیل بازسازی", f"بازسازی کش کامل شد.\nرکوردهای خام پردازش شده: {payload.get('processed_raw_records', 0)}\nمخاطبین: {payload.get('contacts_exported', 0)}\nپروژه‌ها: {payload.get('projects_exported', 0)}")

                elif msg_type == "benchmark_done":
                    self._set_busy_state(False)
                    found = payload.get("discovered_benchmarks", 0)
                    total = payload.get("total_benchmarks", 0)
                    rate = payload.get("recall_rate_percent", 0.0)
                    self._append_log(f"نتایج بنچ‌مارک: کشف {found} از {total} مورد ({rate}% Recall)", tag="success")
                    messagebox.showinfo("نتیجه بنچ‌مارک", f"میزان بازیابی (Recall Rate): {rate}%\nتعداد کشف شده: {found} از {total}")

                elif msg_type == "error":
                    self._set_busy_state(False)
                    self._append_log(f"❌ خطا: {payload}", tag="error")
                    messagebox.showerror("خطا در عملیات", str(payload))

                elif msg_type == "update_check_result":
                    res, interactive = payload
                    if res and res.get("has_update"):
                        msg = (
                            f"نسخه جدید {res['latest_version']} نوآوران پنجره موجود است!\n"
                            f"(نسخه فعلی شما: {res['current_version']})\n\n"
                            f"توضیحات و تغییرات:\n{res.get('release_notes', '')[:350]}\n\n"
                            f"آیا مایلید نسخه جدید به صورت خودکار دانلود و نصب شود؟"
                        )
                        if messagebox.askyesno("به‌روزرسانی خودکار نوآوران پنجره", msg):
                            self._start_download_and_install(res["download_url"], res.get("asset_name"))
                    elif interactive:
                        messagebox.showinfo("برنامه به‌روز است", f"شما در حال حاضر از آخرین نسخه برنامه ({updater.CURRENT_VERSION}) استفاده می‌کنید.")

                elif msg_type == "update_download_progress":
                    pct, downloaded, total, pbar, lbl_status = payload
                    try:
                        pbar["value"] = pct
                        mb_down = downloaded / (1024 * 1024)
                        mb_tot = total / (1024 * 1024) if total > 0 else 0
                        lbl_status.config(text=f"{pct:.1f}% ({mb_down:.1f} MB / {mb_tot:.1f} MB)")
                    except Exception:
                        pass

                elif msg_type == "update_download_done":
                    file_path, dl_win = payload
                    try:
                        dl_win.destroy()
                    except Exception:
                        pass
                    self._append_log("✅ نسخه جدید با موفقیت دانلود شد.", tag="success")
                    if messagebox.askyesno(
                        "تکمیل دانلود به‌روزرسانی",
                        "دانلود نسخه جدید با موفقیت به پایان رسید.\nبرنامه جهت جایگزینی فایل اجرایی بسته و نسخه جدید راه‌اندازی خواهد شد.\nآیا مایل به راه‌اندازی نسخه جدید هستید؟"
                    ):
                        if getattr(sys, "frozen", False):
                            updater.apply_update_and_restart(file_path)
                        else:
                            messagebox.showinfo("محیط توسعه", f"فایل به‌روزرسانی در مسیر زیر ذخیره شد:\n{file_path}\n(در محیط کد منبع پایتون، جایگزینی خودکار مفسر انجام نمی‌شود)")

                elif msg_type == "update_error":
                    err_msg, dl_win = payload
                    try:
                        dl_win.destroy()
                    except Exception:
                        pass
                    self._append_log(f"خطا در دانلود به‌روزرسانی: {err_msg}", tag="error")
                    messagebox.showerror("خطا در به‌روزرسانی", f"امکان دریافت فایل به‌روزرسانی وجود نداشت:\n{err_msg}")

        except queue.Empty:
            pass
        finally:
            if not self.stop_event.is_set():
                try:
                    if self.root.winfo_exists():
                        self._poll_job = self.root.after(50, self._poll_queue)
                except Exception:
                    pass

    def _append_log(self, text: str, tag: Optional[str] = None):
        ts = datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}] {text}\n"

        if not tag:
            if "error" in text.lower() or "failed" in text.lower() or "خطا" in text:
                tag = "error"
            elif "discovered +" in text or "found" in text or "pass" in text.lower():
                tag = "info"
            elif "complete" in text.lower() or "success" in text.lower() or "✅" in text:
                tag = "success"
            elif "warning" in text.lower() or "streak" in text.lower():
                tag = "warning"

        self.txt_log.insert(tk.END, line, tag)
        if self.var_autoscroll.get():
            self.txt_log.see(tk.END)

    def _clear_log(self):
        self.txt_log.delete("1.0", tk.END)

    def _copy_log(self):
        content = self.txt_log.get("1.0", tk.END)
        self.root.clipboard_clear()
        self.root.clipboard_append(content)
        self._append_log("تمام لاگ‌ها در کلیپ‌بورد کپی شد.", tag="info")

    # ========================== Export Helpers ==========================

    def _export_contacts_quick(self):
        cnt = export_contacts_to_csv(CONTACTS_CSV_PATH, self.db_path)
        messagebox.showinfo("استخراج موفق", f"تعداد {cnt} مخاطب در فایل ذخیره شد:\n{CONTACTS_CSV_PATH}")
        self._append_log(f"استخراج {cnt} مخاطب در {CONTACTS_CSV_PATH}", tag="success")

    def _export_contacts_custom(self):
        f = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV Files", "*.csv"), ("All Files", "*.*")],
            initialfile="contacts.csv",
        )
        if f:
            cnt = export_contacts_to_csv(f, self.db_path)
            messagebox.showinfo("استخراج موفق", f"تعداد {cnt} مخاطب در مسیر انتخابی ذخیره شد:\n{f}")
            self._append_log(f"استخراج {cnt} مخاطب در {f}", tag="success")

    def _export_projects_quick(self):
        cnt = export_projects_to_csv(PROJECTS_CSV_PATH, self.db_path)
        messagebox.showinfo("استخراج موفق", f"تعداد {cnt} پروژه در فایل ذخیره شد:\n{PROJECTS_CSV_PATH}")
        self._append_log(f"استخراج {cnt} پروژه در {PROJECTS_CSV_PATH}", tag="success")

    def _export_projects_custom(self):
        f = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV Files", "*.csv"), ("All Files", "*.*")],
            initialfile="active_projects.csv",
        )
        if f:
            cnt = export_projects_to_csv(f, self.db_path)
            messagebox.showinfo("استخراج موفق", f"تعداد {cnt} پروژه در مسیر انتخابی ذخیره شد:\n{f}")
            self._append_log(f"استخراج {cnt} پروژه در {f}", tag="success")

    def _export_all_now(self):
        stats = export_all_csvs(self.db_path)
        msg = (
            f"استخراج هر دو فایل با موفقیت انجام شد:\n\n"
            f"• مخاطبین: {stats['contacts_exported']} مورد -> {stats['contacts_file']}\n"
            f"• پروژه‌ها: {stats['projects_exported']} مورد -> {stats['projects_file']}"
        )
        messagebox.showinfo("تکمیل استخراج", msg)
        self._append_log("استخراج کامل هر دو فایل CSV انجام شد.", tag="success")

    def _open_base_dir(self):
        d = get_base_dir()
        try:
            if sys.platform == "win32":
                os.startfile(d)
            else:
                subprocess.Popen(["xdg-open", d])
        except Exception as e:
            messagebox.showerror("خطا", f"امکان باز کردن پوشه وجود ندارد: {e}")

    def _open_file(self, path: str):
        if not os.path.exists(path):
            messagebox.showwarning("فایل موجود نیست", f"فایل مورد نظر هنوز ساخته نشده است:\n{path}\nابتدا روی دکمه استخراج کلیک کنید.")
            return
        try:
            if sys.platform == "win32":
                os.startfile(path)
            else:
                subprocess.Popen(["xdg-open", path])
        except Exception as e:
            messagebox.showerror("خطا", f"امکان باز کردن فایل وجود ندارد: {e}")

    def close(self):
        self.stop_event.set()
        if hasattr(self, "_poll_job") and self._poll_job:
            try:
                self.root.after_cancel(self._poll_job)
            except Exception:
                pass
            self._poll_job = None
        if hasattr(self, "_init_job") and self._init_job:
            try:
                self.root.after_cancel(self._init_job)
            except Exception:
                pass
            self._init_job = None
        if hasattr(self, "_update_check_job") and self._update_check_job:
            try:
                self.root.after_cancel(self._update_check_job)
            except Exception:
                pass
            self._update_check_job = None
        try:
            if self.root.winfo_exists():
                self.root.destroy()
        except Exception:
            pass

    def _on_close(self):
        if self.is_busy:
            if messagebox.askyesno("خروج از برنامه", "پویشگر در حال اجراست. آیا می‌خواهید عملیات متوقف و برنامه بسته شود؟"):
                self.close()
        else:
            self.close()


def launch_ui(db_path: Optional[str] = None, auto_start_crawl: bool = False):
    target_db = db_path or DEFAULT_DB_PATH
    init_db(target_db)
    root = tk.Tk()
    app = ScraperApp(root, db_path=target_db, auto_start_crawl=auto_start_crawl)
    root.mainloop()


if __name__ == "__main__":
    launch_ui()
