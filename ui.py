import os
import sys
import json
import time
import queue
import threading
import webbrowser
import subprocess
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
)
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

        # Sort order trackers
        self.contacts_sort_state = {}
        self.projects_sort_state = {}
        self.reviews_sort_state = {}

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

    def _configure_styles(self):
        style = ttk.Style()
        try:
            style.theme_use("vista")
        except Exception:
            try:
                style.theme_use("clam")
            except Exception:
                pass

        # Configure fonts & colors based on Noavaran website redblack theme
        # Ink: #0a0002 | Blood: #6b000e | Signal: #ab0017, #d1001c | Steel: #fefefe | Copper: #cca699
        default_font = ("Segoe UI", 9)
        header_font = ("Segoe UI", 11, "bold")
        title_font = ("Segoe UI", 14, "bold")

        style.configure(".", font=default_font)
        style.configure("Header.TLabel", font=header_font)
        style.configure("Title.TLabel", font=title_font)
        style.configure("StatValue.TLabel", font=("Segoe UI", 13, "bold"), foreground="#ab0017")
        style.configure("StatTitle.TLabel", font=("Segoe UI", 8), foreground="#6b7280")

        # Treeview styling
        style.configure("Treeview.Heading", font=("Segoe UI", 9, "bold"))
        style.configure("Treeview", rowheight=26, font=("Segoe UI", 9))

    def _build_header(self):
        # Red-Black brand header from Noavaran website (Ink 950: #0a0002, Signal: #ab0017 / #d1001c)
        header_outer = tk.Frame(self.root, bg="#ab0017", height=82)
        header_outer.pack(side=tk.TOP, fill=tk.X)
        header_outer.pack_propagate(False)

        header_frame = tk.Frame(header_outer, bg="#0a0002")
        header_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True, pady=(0, 2))

        # Brand box with Logo
        brand_box = tk.Frame(header_frame, bg="#0a0002")
        brand_box.pack(side=tk.LEFT, fill=tk.Y, padx=16, pady=8)

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
            logo_lbl = tk.Label(brand_box, image=self._logo_photo, bg="#0a0002")
            logo_lbl.pack(side=tk.LEFT, padx=(0, 14))

        # Title text container
        text_box = tk.Frame(brand_box, bg="#0a0002")
        text_box.pack(side=tk.LEFT, fill=tk.Y)

        title_lbl = tk.Label(
            text_box,
            text="نوآوران پنجره | Noavaran Panjereh",
            font=("Segoe UI", 13, "bold"),
            fg="#fefefe",
            bg="#0a0002",
        )
        title_lbl.pack(anchor="w")

        subtitle_lbl = tk.Label(
            text_box,
            text="سامانه هوشمند استخراج سرنخ‌ها، معماران و پروژه‌های ساختمانی سراسر کشور",
            font=("Segoe UI", 8),
            fg="#cca699",
            bg="#0a0002",
        )
        subtitle_lbl.pack(anchor="w")

        # Right quick stats badges
        stats_box = tk.Frame(header_frame, bg="#0a0002")
        stats_box.pack(side=tk.RIGHT, fill=tk.Y, padx=16, pady=8)

        def make_stat_card(parent, title_text, var_name):
            card = tk.Frame(parent, bg="#1a0004", padx=12, pady=3, relief=tk.SOLID, bd=1, highlightbackground="#4a000a", highlightthickness=1)
            card.pack(side=tk.LEFT, padx=4)
            val_lbl = tk.Label(card, text="0", font=("Segoe UI", 11, "bold"), fg="#fefefe", bg="#1a0004")
            val_lbl.pack()
            setattr(self, var_name, val_lbl)
            lbl = tk.Label(card, text=title_text, font=("Segoe UI", 7), fg="#cca699", bg="#1a0004")
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
        self.notebook.add(self.tab_projects, text=" 🏗️ پروژه‌های فعال (Active Projects) ")
        self._setup_projects_tab()

        # Tab 4: Ambiguous Reviews
        self.tab_reviews = ttk.Frame(self.notebook, padding=8)
        self.notebook.add(self.tab_reviews, text=" ⚖️ بررسی برخوردهای مبهم (Ambiguous Reviews) ")
        self._setup_reviews_tab()

        # Tab 5: Export & Files
        self.tab_export = ttk.Frame(self.notebook, padding=8)
        self.notebook.add(self.tab_export, text=" 📁 خروجی‌ها و فایل‌ها (Export & Files) ")
        self._setup_export_tab()

    def _setup_crawl_tab(self):
        # Top Config & Action Pane
        paned = ttk.PanedWindow(self.tab_crawl, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True)

        left_frame = ttk.LabelFrame(paned, text="تنظیمات و دستورات پویش (Configuration & Execution)", padding=10)
        paned.add(left_frame, weight=1)

        # Config fields in grid
        ttk.Label(left_frame, text="حداکثر دفعات جستجو (Max Passes):").grid(row=0, column=0, sticky="w", pady=4)
        self.spn_passes = ttk.Spinbox(left_frame, from_=1, to=100, width=8)
        self.spn_passes.set(12)
        self.spn_passes.grid(row=0, column=1, sticky="e", pady=4)

        ttk.Label(left_frame, text="محدودیت توقف توالی صفر (Streak Limit):").grid(row=1, column=0, sticky="w", pady=4)
        self.spn_streak = ttk.Spinbox(left_frame, from_=1, to=20, width=8)
        self.spn_streak.set(4)
        self.spn_streak.grid(row=1, column=1, sticky="e", pady=4)

        ttk.Label(left_frame, text="بودجه زمانی (ثانیه) (Budget Sec):").grid(row=2, column=0, sticky="w", pady=4)
        self.spn_budget = ttk.Spinbox(left_frame, from_=30, to=3600, width=8)
        self.spn_budget.set(180)
        self.spn_budget.grid(row=2, column=1, sticky="e", pady=4)

        ttk.Label(left_frame, text="کانال‌های تلگرام (Telegram Channels):").grid(row=3, column=0, sticky="w", pady=4)
        self.spn_tg = ttk.Spinbox(left_frame, from_=1, to=10, width=8)
        self.spn_tg.set(4)
        self.spn_tg.grid(row=3, column=1, sticky="e", pady=4)

        ttk.Label(left_frame, text="نتایج به ازای جستجو (Results/Query):").grid(row=4, column=0, sticky="w", pady=4)
        self.spn_results = ttk.Spinbox(left_frame, from_=1, to=30, width=8)
        self.spn_results.set(5)
        self.spn_results.grid(row=4, column=1, sticky="e", pady=4)

        ttk.Label(left_frame, text="کاوش عمیق وب‌سایت‌ها (Max Frontier):").grid(row=5, column=0, sticky="w", pady=4)
        self.spn_frontier = ttk.Spinbox(left_frame, from_=1, to=50, width=8)
        self.spn_frontier.set(10)
        self.spn_frontier.grid(row=5, column=1, sticky="e", pady=4)

        # Action Buttons
        btn_frame = ttk.Frame(left_frame, padding=(0, 10, 0, 0))
        btn_frame.grid(row=6, column=0, columnspan=2, sticky="ew")

        self.btn_run = tk.Button(
            btn_frame,
            text="▶ شروع پویش خودکار (Start Scraper)",
            bg="#ab0017",
            activebackground="#d1001c",
            fg="#fefefe",
            font=("Segoe UI", 9, "bold"),
            relief=tk.RAISED,
            padx=8,
            pady=6,
            command=self._on_start_crawler,
        )
        self.btn_run.pack(fill=tk.X, pady=3)

        self.btn_stop = tk.Button(
            btn_frame,
            text="⏹ توقف عملیات (Stop Scraper)",
            bg="#4a000a",
            activebackground="#6b000e",
            fg="#fefefe",
            font=("Segoe UI", 9, "bold"),
            state=tk.DISABLED,
            relief=tk.RAISED,
            padx=8,
            pady=4,
            command=self._on_stop_crawler,
        )
        self.btn_stop.pack(fill=tk.X, pady=3)

        ttk.Separator(btn_frame, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=6)

        self.btn_rebuild = ttk.Button(
            btn_frame,
            text="🔄 بازسازی و بازپردازش کش (Rebuild Cache)",
            command=self._on_rebuild_cache,
        )
        self.btn_rebuild.pack(fill=tk.X, pady=2)

        self.btn_benchmark = ttk.Button(
            btn_frame,
            text="🧪 ارزیابی بنچ‌مارک اصفهان (Run Benchmark)",
            command=self._on_run_benchmark,
        )
        self.btn_benchmark.pack(fill=tk.X, pady=2)

        # Progress bar & status
        self.crawl_status_lbl = ttk.Label(left_frame, text="آماده به کار (Idle)", font=("Segoe UI", 8, "italic"))
        self.crawl_status_lbl.grid(row=7, column=0, columnspan=2, sticky="w", pady=(10, 2))

        self.progressbar = ttk.Progressbar(left_frame, orient=tk.HORIZONTAL, mode="determinate")
        self.progressbar.grid(row=8, column=0, columnspan=2, sticky="ew", pady=(0, 4))

        # Daily Autorun on Windows Startup
        autorun_card = ttk.LabelFrame(left_frame, text="⏱️ اجرای خودکار روزانه (Daily Startup Autorun)", padding=8)
        autorun_card.grid(row=9, column=0, columnspan=2, sticky="ew", pady=(8, 2))

        self.var_autorun = tk.BooleanVar(value=autorun.is_autorun_enabled())
        self.var_autorun_crawl = tk.BooleanVar(value=True)

        chk_autorun = ttk.Checkbutton(
            autorun_card,
            text="اجرای خودکار با روشن شدن سیستم (Run on Startup)",
            variable=self.var_autorun,
            command=self._on_toggle_autorun,
        )
        chk_autorun.pack(anchor="w", pady=2)

        chk_crawl = ttk.Checkbutton(
            autorun_card,
            text="شروع خودکار پویش سرنخ‌ها هنگام بالا آمدن ویندوز",
            variable=self.var_autorun_crawl,
            command=self._on_toggle_autorun,
        )
        chk_crawl.pack(anchor="w", pady=2)

        is_act = self.var_autorun.get()
        self.lbl_autorun_status = tk.Label(
            autorun_card,
            text="وضعیت: فعال در استارت‌آپ ویندوز (Active)" if is_act else "وضعیت: غیرفعال (Disabled)",
            font=("Segoe UI", 8, "bold"),
            fg="#16a34a" if is_act else "#64748b",
        )
        self.lbl_autorun_status.pack(anchor="w", pady=(2, 0))

        # Right: Live Console Output
        right_frame = ttk.LabelFrame(paned, text="لاگ زنده و خروجی کنسول (Live Execution Logs)", padding=6)
        paned.add(right_frame, weight=3)

        # Log toolbar
        log_tools = ttk.Frame(right_frame)
        log_tools.pack(fill=tk.X, pady=(0, 4))

        self.var_autoscroll = tk.BooleanVar(value=True)
        chk_scroll = ttk.Checkbutton(log_tools, text="اسکرول خودکار (Auto-scroll)", variable=self.var_autoscroll)
        chk_scroll.pack(side=tk.LEFT)

        btn_copy_log = ttk.Button(log_tools, text="کپی لاگ (Copy)", command=self._copy_log)
        btn_copy_log.pack(side=tk.RIGHT, padx=2)

        btn_clear_log = ttk.Button(log_tools, text="پاکسازی لاگ (Clear)", command=self._clear_log)
        btn_clear_log.pack(side=tk.RIGHT, padx=2)

        # Log text area
        self.txt_log = scrolledtext.ScrolledText(
            right_frame,
            wrap=tk.WORD,
            bg="#0f172a",
            fg="#e2e8f0",
            insertbackground="white",
            font=("Consolas", 9),
        )
        self.txt_log.pack(fill=tk.BOTH, expand=True)

        # Tag configuration for colored logs
        self.txt_log.tag_configure("info", foreground="#38bdf8")
        self.txt_log.tag_configure("success", foreground="#4ade80")
        self.txt_log.tag_configure("warning", foreground="#fbbf24")
        self.txt_log.tag_configure("error", foreground="#f87171")
        self.txt_log.tag_configure("dim", foreground="#64748b")

    def _setup_contacts_tab(self):
        # Filter Frame
        filter_frame = ttk.Frame(self.tab_contacts)
        filter_frame.pack(fill=tk.X, pady=(0, 6))

        ttk.Label(filter_frame, text="جستجو:").pack(side=tk.LEFT, padx=(0, 4))
        self.ent_search_contacts = ttk.Entry(filter_frame, width=28)
        self.ent_search_contacts.pack(side=tk.LEFT, padx=(0, 8))
        self.ent_search_contacts.bind("<KeyRelease>", lambda e: self._filter_contacts())

        ttk.Label(filter_frame, text="دسته‌بندی:").pack(side=tk.LEFT, padx=(0, 4))
        self.cmb_filter_type = ttk.Combobox(
            filter_frame,
            values=["همه (All)", "office", "contractor", "student", "individual"],
            state="readonly",
            width=14,
        )
        self.cmb_filter_type.set("همه (All)")
        self.cmb_filter_type.pack(side=tk.LEFT, padx=(0, 8))
        self.cmb_filter_type.bind("<<ComboboxSelected>>", lambda e: self._filter_contacts())

        ttk.Label(filter_frame, text="شهر:").pack(side=tk.LEFT, padx=(0, 4))
        self.cmb_filter_city = ttk.Combobox(
            filter_frame,
            values=["همه (All)", "Isfahan", "Tehran", "Other"],
            state="readonly",
            width=12,
        )
        self.cmb_filter_city.set("همه (All)")
        self.cmb_filter_city.pack(side=tk.LEFT, padx=(0, 8))
        self.cmb_filter_city.bind("<<ComboboxSelected>>", lambda e: self._filter_contacts())

        btn_refresh = ttk.Button(filter_frame, text="🔄 بازخوانی (Refresh)", command=self._load_contacts_from_db)
        btn_refresh.pack(side=tk.LEFT, padx=4)

        self.lbl_contacts_count = ttk.Label(filter_frame, text="در حال بارگذاری...", font=("Segoe UI", 9, "bold"))
        self.lbl_contacts_count.pack(side=tk.RIGHT, padx=4)

        # Paned Window for Table + Detail View
        paned = ttk.PanedWindow(self.tab_contacts, orient=tk.VERTICAL)
        paned.pack(fill=tk.BOTH, expand=True)

        # Treeview Frame
        tree_frame = ttk.Frame(paned)
        paned.add(tree_frame, weight=3)

        cols = ("type", "name", "role", "company", "city", "phone", "email", "confidence", "social", "source")
        self.tree_contacts = ttk.Treeview(tree_frame, columns=cols, show="headings", selectmode="browse")

        col_defs = [
            ("type", "دسته (Type)", 80),
            ("name", "نام / عنوان (Name)", 150),
            ("role", "نقش (Role)", 110),
            ("company", "شرکت / دفتر (Company)", 150),
            ("city", "شهر (City)", 75),
            ("phone", "تلفن (Phone)", 115),
            ("email", "ایمیل (Email)", 140),
            ("confidence", "اطمینان", 75),
            ("social", "سوشال / هندل", 95),
            ("source", "منبع (Source URL)", 180),
        ]

        for col_id, col_name, col_w in col_defs:
            self.tree_contacts.heading(col_id, text=col_name, command=lambda c=col_id: self._sort_tree(self.tree_contacts, self.contacts_sort_state, c))
            self.tree_contacts.column(col_id, width=col_w, minwidth=60)

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

        self.txt_contact_detail = tk.Text(detail_frame, height=4, font=("Segoe UI", 9), wrap=tk.WORD, bg="#f8fafc")
        self.txt_contact_detail.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        detail_actions = ttk.Frame(detail_frame)
        detail_actions.pack(side=tk.RIGHT, fill=tk.Y, padx=(8, 0))

        self.btn_copy_phone = ttk.Button(detail_actions, text="📋 کپی تلفن", command=self._copy_selected_contact_phone)
        self.btn_copy_phone.pack(fill=tk.X, pady=2)

        self.btn_copy_email = ttk.Button(detail_actions, text="📋 کپی ایمیل", command=self._copy_selected_contact_email)
        self.btn_copy_email.pack(fill=tk.X, pady=2)

        self.btn_open_contact_url = ttk.Button(detail_actions, text="🌐 باز کردن لینک منبع", command=self._open_selected_contact_url)
        self.btn_open_contact_url.pack(fill=tk.X, pady=2)

    def _setup_projects_tab(self):
        # Filter Frame
        filter_frame = ttk.Frame(self.tab_projects)
        filter_frame.pack(fill=tk.X, pady=(0, 6))

        ttk.Label(filter_frame, text="جستجو:").pack(side=tk.LEFT, padx=(0, 4))
        self.ent_search_projects = ttk.Entry(filter_frame, width=30)
        self.ent_search_projects.pack(side=tk.LEFT, padx=(0, 8))
        self.ent_search_projects.bind("<KeyRelease>", lambda e: self._filter_projects())

        ttk.Label(filter_frame, text="شهر:").pack(side=tk.LEFT, padx=(0, 4))
        self.cmb_proj_city = ttk.Combobox(
            filter_frame,
            values=["همه (All)", "Isfahan", "Tehran", "Other"],
            state="readonly",
            width=12,
        )
        self.cmb_proj_city.set("همه (All)")
        self.cmb_proj_city.pack(side=tk.LEFT, padx=(0, 8))
        self.cmb_proj_city.bind("<<ComboboxSelected>>", lambda e: self._filter_projects())

        btn_refresh = ttk.Button(filter_frame, text="🔄 بازخوانی (Refresh)", command=self._load_projects_from_db)
        btn_refresh.pack(side=tk.LEFT, padx=4)

        self.lbl_projects_count = ttk.Label(filter_frame, text="در حال بارگذاری...", font=("Segoe UI", 9, "bold"))
        self.lbl_projects_count.pack(side=tk.RIGHT, padx=4)

        # Paned Window for Table + Detail View
        paned = ttk.PanedWindow(self.tab_projects, orient=tk.VERTICAL)
        paned.pack(fill=tk.BOTH, expand=True)

        tree_frame = ttk.Frame(paned)
        paned.add(tree_frame, weight=3)

        cols = ("name", "city", "scope", "contractors", "architects", "contact", "confidence", "date", "source")
        self.tree_projects = ttk.Treeview(tree_frame, columns=cols, show="headings", selectmode="browse")

        col_defs = [
            ("name", "نام پروژه (Project Name)", 180),
            ("city", "شهر", 75),
            ("scope", "مقیاس و مشخصات (Scale/Scope)", 140),
            ("contractors", "پیمانکار(ان) مرتبط", 140),
            ("architects", "معمار(ان) / مشاور", 140),
            ("contact", "اطلاعات تماس", 110),
            ("confidence", "اطمینان", 75),
            ("date", "تاریخ کشف", 85),
            ("source", "منبع (Source URL)", 180),
        ]

        for col_id, col_name, col_w in col_defs:
            self.tree_projects.heading(col_id, text=col_name, command=lambda c=col_id: self._sort_tree(self.tree_projects, self.projects_sort_state, c))
            self.tree_projects.column(col_id, width=col_w, minwidth=60)

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

        self.txt_project_detail = tk.Text(detail_frame, height=4, font=("Segoe UI", 9), wrap=tk.WORD, bg="#f8fafc")
        self.txt_project_detail.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        detail_actions = ttk.Frame(detail_frame)
        detail_actions.pack(side=tk.RIGHT, fill=tk.Y, padx=(8, 0))

        self.btn_copy_proj = ttk.Button(detail_actions, text="📋 کپی مشخصات", command=self._copy_selected_project_info)
        self.btn_copy_proj.pack(fill=tk.X, pady=2)

        self.btn_open_proj_url = ttk.Button(detail_actions, text="🌐 باز کردن لینک منبع", command=self._open_selected_project_url)
        self.btn_open_proj_url.pack(fill=tk.X, pady=2)

    def _setup_reviews_tab(self):
        top_frame = ttk.Frame(self.tab_reviews)
        top_frame.pack(fill=tk.X, pady=(0, 6))

        info_lbl = ttk.Label(
            top_frame,
            text="برخوردهای مبهم در قرنطینه (امتیاز شباهت فازی ۷۰ الی ۸۷ درصد جهت بازبینی کاربر):",
            font=("Segoe UI", 9, "bold"),
        )
        info_lbl.pack(side=tk.LEFT)

        btn_refresh = ttk.Button(top_frame, text="🔄 بازخوانی لاگ بازبینی (Refresh)", command=self._load_reviews_from_db)
        btn_refresh.pack(side=tk.RIGHT)

        paned = ttk.PanedWindow(self.tab_reviews, orient=tk.VERTICAL)
        paned.pack(fill=tk.BOTH, expand=True)

        tree_frame = ttk.Frame(paned)
        paned.add(tree_frame, weight=2)

        cols = ("id", "type", "score", "reason", "existing_id", "date")
        self.tree_reviews = ttk.Treeview(tree_frame, columns=cols, show="headings", selectmode="browse")

        col_defs = [
            ("id", "شناسه", 50),
            ("type", "نوع کاندید", 80),
            ("score", "امتیاز شباهت", 90),
            ("reason", "دلیل برخورد فازی / بازبینی", 220),
            ("existing_id", "شناسه موجود در دیتابیس", 160),
            ("date", "تاریخ لاگ", 140),
        ]

        for col_id, col_name, col_w in col_defs:
            self.tree_reviews.heading(col_id, text=col_name, command=lambda c=col_id: self._sort_tree(self.tree_reviews, self.reviews_sort_state, c))
            self.tree_reviews.column(col_id, width=col_w)

        vsb = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.tree_reviews.yview)
        self.tree_reviews.configure(yscrollcommand=vsb.set)
        self.tree_reviews.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)

        self.tree_reviews.bind("<<TreeviewSelect>>", self._on_review_selected)

        detail_frame = ttk.LabelFrame(paned, text="محتوای خام کاندید مورد بررسی (Candidate Payload JSON)", padding=8)
        paned.add(detail_frame, weight=2)

        self.txt_review_detail = tk.Text(detail_frame, height=8, font=("Consolas", 9), wrap=tk.WORD, bg="#f8fafc")
        self.txt_review_detail.pack(fill=tk.BOTH, expand=True)

    def _setup_export_tab(self):
        main_frame = ttk.Frame(self.tab_export, padding=16)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Card 1: Contacts CSV
        c_card = ttk.LabelFrame(main_frame, text="خروجی سرنخ‌ها و مخاطبین (contacts.csv)", padding=12)
        c_card.pack(fill=tk.X, pady=8)

        self.lbl_contacts_file_status = ttk.Label(c_card, text=f"مسیر فایل: {CONTACTS_CSV_PATH}", font=("Segoe UI", 9))
        self.lbl_contacts_file_status.pack(anchor="w", pady=2)

        btn_box1 = ttk.Frame(c_card)
        btn_box1.pack(anchor="w", pady=6)

        ttk.Button(btn_box1, text="⚡ استخراج سریع (Export Now)", command=self._export_contacts_quick).pack(side=tk.LEFT, padx=4)
        ttk.Button(btn_box1, text="💾 ذخیره در مسیر دلخواه... (Save As)", command=self._export_contacts_custom).pack(side=tk.LEFT, padx=4)
        ttk.Button(btn_box1, text="📊 باز کردن فایل با اکسل (Open CSV)", command=lambda: self._open_file(CONTACTS_CSV_PATH)).pack(side=tk.LEFT, padx=4)

        # Card 2: Projects CSV
        p_card = ttk.LabelFrame(main_frame, text="خروجی پروژه‌های فعال ساختمانی (active_projects.csv)", padding=12)
        p_card.pack(fill=tk.X, pady=8)

        self.lbl_projects_file_status = ttk.Label(p_card, text=f"مسیر فایل: {PROJECTS_CSV_PATH}", font=("Segoe UI", 9))
        self.lbl_projects_file_status.pack(anchor="w", pady=2)

        btn_box2 = ttk.Frame(p_card)
        btn_box2.pack(anchor="w", pady=6)

        ttk.Button(btn_box2, text="⚡ استخراج سریع (Export Now)", command=self._export_projects_quick).pack(side=tk.LEFT, padx=4)
        ttk.Button(btn_box2, text="💾 ذخیره در مسیر دلخواه... (Save As)", command=self._export_projects_custom).pack(side=tk.LEFT, padx=4)
        ttk.Button(btn_box2, text="📊 باز کردن فایل با اکسل (Open CSV)", command=lambda: self._open_file(PROJECTS_CSV_PATH)).pack(side=tk.LEFT, padx=4)

        # Card 3: Directory & DB Actions
        d_card = ttk.LabelFrame(main_frame, text="پایگاه داده و پوشه پروژه (Database & Explorer)", padding=12)
        d_card.pack(fill=tk.X, pady=8)

        base_d = get_base_dir()
        self.lbl_db_path = ttk.Label(d_card, text=f"پایگاه داده SQLite: {self.db_path}\nپوشه برنامه: {base_d}", font=("Segoe UI", 9))
        self.lbl_db_path.pack(anchor="w", pady=2)

        btn_box3 = ttk.Frame(d_card)
        btn_box3.pack(anchor="w", pady=6)

        ttk.Button(btn_box3, text="📂 باز کردن پوشه فایل‌ها (Open Output Folder)", command=self._open_base_dir).pack(side=tk.LEFT, padx=4)
        ttk.Button(btn_box3, text="🔄 استخراج هر دو فایل هم‌زمان (Export All CSVs)", command=self._export_all_now).pack(side=tk.LEFT, padx=4)

    def _build_statusbar(self):
        status_frame = tk.Frame(self.root, bg="#0a0002", height=26, relief=tk.FLAT, bd=0)
        status_frame.pack(side=tk.BOTTOM, fill=tk.X)

        # Subtle top accent line
        top_line = tk.Frame(status_frame, bg="#4a000a", height=1)
        top_line.pack(side=tk.TOP, fill=tk.X)

        inner_status = tk.Frame(status_frame, bg="#0a0002")
        inner_status.pack(side=tk.TOP, fill=tk.X, expand=True)

        self.lbl_status_left = tk.Label(inner_status, text="آماده به کار (Ready)", font=("Segoe UI", 8), bg="#0a0002", fg="#e3e4e6")
        self.lbl_status_left.pack(side=tk.LEFT, padx=12, pady=2)

        self.lbl_status_right = tk.Label(inner_status, text=f"Noavaran Scraper | DB: {os.path.basename(self.db_path)}", font=("Segoe UI", 8), bg="#0a0002", fg="#cca699")
        self.lbl_status_right.pack(side=tk.RIGHT, padx=12, pady=2)

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
