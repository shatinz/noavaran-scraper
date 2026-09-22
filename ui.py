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

# Enable high DPI awareness on Windows if possible
try:
    import ctypes
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    pass

from database import (
    DEFAULT_DB_PATH,
    get_connection,
    get_all_contacts,
    get_all_projects,
    get_ambiguous_reviews,
    get_cache_stats,
    get_base_dir,
)
from models import ContactEntity, ActiveProject
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
    def __init__(self, root: tk.Tk, db_path: str = DEFAULT_DB_PATH):
        self.root = root
        self.db_path = db_path
        self.root.title("Noavaran Panjereh - Lead & Project Discovery Scraper | نوآوران پنجره")
        self.root.geometry("1120x760")
        self.root.minsize(960, 620)

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

        self._configure_styles()
        self._build_header()
        self._build_notebook()
        self._build_statusbar()

        # Start queue polling loop
        self.root.after(50, self._poll_queue)

        # Protocol for graceful window closing
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        # Initial load of stats & tables
        self.root.after(200, self._initial_load)

    def _configure_styles(self):
        style = ttk.Style()
        try:
            style.theme_use("vista")
        except Exception:
            try:
                style.theme_use("clam")
            except Exception:
                pass

        # Configure generic fonts & colors
        default_font = ("Segoe UI", 9)
        header_font = ("Segoe UI", 11, "bold")
        title_font = ("Segoe UI", 14, "bold")

        style.configure(".", font=default_font)
        style.configure("Header.TLabel", font=header_font)
        style.configure("Title.TLabel", font=title_font)
        style.configure("StatValue.TLabel", font=("Segoe UI", 13, "bold"), foreground="#0f766e")
        style.configure("StatTitle.TLabel", font=("Segoe UI", 8), foreground="#64748b")

        # Treeview styling
        style.configure("Treeview.Heading", font=("Segoe UI", 9, "bold"))
        style.configure("Treeview", rowheight=26, font=("Segoe UI", 9))

    def _build_header(self):
        header_frame = tk.Frame(self.root, bg="#0f172a", height=70)
        header_frame.pack(side=tk.TOP, fill=tk.X)
        header_frame.pack_propagate(False)

        # Left title info
        title_box = tk.Frame(header_frame, bg="#0f172a")
        title_box.pack(side=tk.LEFT, fill=tk.Y, padx=16, pady=10)

        title_lbl = tk.Label(
            title_box,
            text="نوآوران پنجره | Noavaran Lead & Project Scraper",
            font=("Segoe UI", 13, "bold"),
            fg="#f8fafc",
            bg="#0f172a",
        )
        title_lbl.pack(anchor="w")

        subtitle_lbl = tk.Label(
            title_box,
            text="Autonomous Lead Discovery & Active Construction Project Intelligence (Isfahan & National)",
            font=("Segoe UI", 8),
            fg="#94a3b8",
            bg="#0f172a",
        )
        subtitle_lbl.pack(anchor="w")

        # Right quick stats badges
        stats_box = tk.Frame(header_frame, bg="#0f172a")
        stats_box.pack(side=tk.RIGHT, fill=tk.Y, padx=16, pady=6)

        def make_stat_card(parent, title_text, var_name):
            card = tk.Frame(parent, bg="#1e293b", padx=10, pady=4, relief=tk.RIDGE, bd=1)
            card.pack(side=tk.LEFT, padx=5)
            val_lbl = tk.Label(card, text="0", font=("Segoe UI", 11, "bold"), fg="#38bdf8", bg="#1e293b")
            val_lbl.pack()
            setattr(self, var_name, val_lbl)
            lbl = tk.Label(card, text=title_text, font=("Segoe UI", 7), fg="#94a3b8", bg="#1e293b")
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
            bg="#16a34a",
            fg="white",
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
            bg="#dc2626",
            fg="white",
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
            self.tree_reviews.heading(col_id, text=col_name)
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
        status_frame = tk.Frame(self.root, bg="#f1f5f9", height=24, relief=tk.SUNKEN, bd=1)
        status_frame.pack(side=tk.BOTTOM, fill=tk.X)

        self.lbl_status_left = tk.Label(status_frame, text="آماده به کار", font=("Segoe UI", 8), bg="#f1f5f9", fg="#334155")
        self.lbl_status_left.pack(side=tk.LEFT, padx=8)

        self.lbl_status_right = tk.Label(status_frame, text=f"Database: {os.path.basename(self.db_path)}", font=("Segoe UI", 8), bg="#f1f5f9", fg="#64748b")
        self.lbl_status_right.pack(side=tk.RIGHT, padx=8)

    # ========================== Data Loading & Stats ==========================

    def _initial_load(self):
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
        query = self.ent_search_contacts.get().strip().lower()
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
                if filter_city == "Other" and c.city in ("Isfahan", "Tehran"):
                    continue
                elif filter_city in ("Isfahan", "Tehran") and c.city != filter_city:
                    continue

            # Text query match across multiple fields
            if query:
                search_blob = f"{c.name} {c.role} {c.company} {c.city} {c.phone} {c.email} {c.social_handle}".lower()
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
        query = self.ent_search_projects.get().strip().lower()
        filter_city = self.cmb_proj_city.get()

        self.tree_projects.delete(*self.tree_projects.get_children())
        shown = 0

        for p in self.projects_cache:
            if filter_city != "همه (All)":
                if filter_city == "Other" and p.city in ("Isfahan", "Tehran"):
                    continue
                elif filter_city in ("Isfahan", "Tehran") and p.city != filter_city:
                    continue

            if query:
                search_blob = f"{p.project_name} {p.associated_contractors} {p.associated_architects} {p.city} {p.scale_scope} {p.contact_info}".lower()
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
                pretty = match_item["candidate_json"]
            self.txt_review_detail.delete("1.0", tk.END)
            self.txt_review_detail.insert("1.0", f"Existing ID: {match_item['existing_id']}\nScore: {match_item['match_score']}%\nReason: {match_item['match_reason']}\n\nCandidate Raw JSON:\n{pretty}")

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
        try:
            items.sort(key=lambda t: float(t[0].replace("%", "").strip()), reverse=rev)
        except ValueError:
            items.sort(key=lambda t: t[0].lower(), reverse=rev)

        for index, (_, k) in enumerate(items):
            tree.move(k, "", index)
        sort_state[col] = not rev

    # ========================== Background Task Execution ==========================

    def _set_busy_state(self, busy: bool, status_text: str = ""):
        self.is_busy = busy
        if busy:
            self.btn_run.config(state=tk.DISABLED, bg="#9ca3af")
            self.btn_stop.config(state=tk.NORMAL)
            self.btn_rebuild.config(state=tk.DISABLED)
            self.btn_benchmark.config(state=tk.DISABLED)
            self.lbl_status_left.config(text=status_text or "در حال اجرا...", fg="#0284c7")
            self.crawl_status_lbl.config(text=status_text or "در حال اجرا...")
        else:
            self.btn_run.config(state=tk.NORMAL, bg="#16a34a")
            self.btn_stop.config(state=tk.DISABLED)
            self.btn_rebuild.config(state=tk.NORMAL)
            self.btn_benchmark.config(state=tk.NORMAL)
            self.lbl_status_left.config(text="آماده به کار (Idle)", fg="#334155")
            self.crawl_status_lbl.config(text="آماده به کار (Idle)")
            self.progressbar["value"] = 0

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
        except ValueError:
            messagebox.showerror("خطای ورودی", "لطفاً مقادیر عددی معتبر در تنظیمات وارد نمایید.")
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
                    self._append_log("✅ پویش با موفقیت به پایان رسید.", tag="success")
                    self._append_log(f"خلاصه: +{payload.get('new_entities_this_run', 0)} رکورد جدید در {payload.get('duration_sec', 0)} ثانیه.", tag="info")
                    self._refresh_stats()
                    self._load_contacts_from_db()
                    self._load_projects_from_db()
                    self._load_reviews_from_db()
                    messagebox.showinfo("پایان عملیات", f"پویش به اتمام رسید.\nرکوردهای جدید: {payload.get('new_entities_this_run', 0)}\nمدت زمان: {payload.get('duration_sec', 0)}s")

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
            self.root.after(50, self._poll_queue)

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

    def _on_close(self):
        if self.is_busy:
            if messagebox.askyesno("خروج از برنامه", "پویشگر در حال اجراست. آیا می‌خواهید عملیات متوقف و برنامه بسته شود؟"):
                self.stop_event.set()
                self.root.destroy()
        else:
            self.root.destroy()


def launch_ui(db_path: Optional[str] = None):
    root = tk.Tk()
    target_db = db_path or DEFAULT_DB_PATH
    app = ScraperApp(root, db_path=target_db)
    root.mainloop()


if __name__ == "__main__":
    launch_ui()
