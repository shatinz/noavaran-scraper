# 🏗️ Noavaran Panjereh Lead Discovery & Project Intelligence Engine

> **High-Precision Autonomous Lead Discovery, Entity Matching & Deduplication System for Noavaran Panjereh (نوآوران پنجره - اصفهان)**

![Python](https://img.shields.io/badge/Python-3.14-blue.svg)
![Architecture](https://img.shields.io/badge/Architecture-Heuristic%20Zero--Token-emerald.svg)
![Tests](https://img.shields.io/badge/Tests-39%20Passing-success.svg)
![License](https://img.shields.io/badge/License-Proprietary-red.svg)

---

## 📌 1. Project Overview & Business North Star

**Noavaran Panjereh** (formerly Arvin Panjereh Partak / Esfahan Novin) is a premier architectural door, window, and facade manufacturer based in Isfahan, specializing in:
- High-performance **thermal-break aluminium windows & doors** (Lift & Slide, monorail, accordion, balcony glass).
- **Curtain wall / lamella facades** (Cap, Face Cap, U-Channel, skylights, add-on systems).
- **Frameless glass facades**, dry ceramics/louvers, aluminium composite panels, and structural glass railings.

This engine autonomously harvests high-intent B2B leads across **4 core categories**:
1. **Architecture & Construction Offices**: Architectural design firms, engineering consultants, and lead designers.
2. **Construction Contractors**: Facade contractors, structural builders, licensed general contractors (`مجری ذیصلاح`), and window installers.
3. **Architecture Students**: Junior talent and student researchers (exhaustive in Isfahan, strictly gatekept outside Isfahan).
4. **Active Building & Construction Projects**: Projects with scale/scope, tied architects, and contractors.

---

## 🏛️ 2. Architectural Design & Multi-Source Harvesters

```mermaid
graph TD
    subgraph Data_Ingestion [Multi-Source Data Harvesters]
        TG[Telegram Web Previews t.me/s/]
        SE[Search Engine Dorking DDGS]
        LI[LinkedIn Public SERP Snippets]
        IG[Instagram Public Bio SERP Snippets]
        WEB[Targeted Website DOM Pruning]
    end

    subgraph Normalization_Engine [Normalization Layer]
        P_NORM[Persian Unicode & Digit Canonicalization]
        PH_NORM[Iranian Phone Normalizer 09xx / 031xx]
        EM_NORM[Email Normalizer]
        NM_NORM[Fuzzy Name & Company Standardizer]
    end

    subgraph Dedup_Resolution [Deduplication & Entity Resolution]
        EX_PH[Exact Phone Match -> Auto-Merge]
        EX_EM[Exact Email Match -> Auto-Merge]
        FZ_MC[RapidFuzz Composite Name+Company]
        AMB[70-87% Ambiguous Match -> Quarantine Review]
        RAW[Persistent raw_records.jsonl Log]
    end

    subgraph Exporters [Dual Independent CSV Exporters]
        C_CSV[(contacts.csv)]
        P_CSV[(active_projects.csv)]
    end

    TG --> P_NORM
    SE --> P_NORM
    LI --> P_NORM
    IG --> P_NORM
    WEB --> P_NORM

    P_NORM --> RAW
    RAW --> EX_PH
    EX_PH -->|No Match| EX_EM
    EX_EM -->|No Match| FZ_MC
    FZ_MC -->|Score >= 88%| C_CSV
    FZ_MC -->|70% <= Score < 88%| AMB
    FZ_MC -->|Score < 70%| C_CSV
    EX_PH -->|Match| C_CSV
    EX_EM -->|Match| C_CSV
```

### Key Data Ingestion Principles:
1. **Telegram Web Previews (`https://t.me/s/<channel>`)**: Direct HTTP GET ingestion of public Telegram channels and groups. Requires zero authentication, no user phone number, and incurs **zero platform ban risk**.
2. **Search Engine Dorking for LinkedIn & Instagram**: In accordance with v1 scope and platform ban avoidance, LinkedIn and Instagram are **never scraped directly**. Instead, search engine indexes (`site:linkedin.com/in`, `site:linkedin.com/company`, `site:instagram.com`) are leveraged to extract rich bio snippets, usernames, telephone numbers, and addresses.
3. **Targeted Zero-Token Web Extraction**: Corporate websites discovered during search passes are pruned of scripts, styles, SVG icons, and navigation headers, extracting contact details with pure deterministic regular expressions.

---

## 🎯 3. Geographic Prioritization & Tier-Gating Engine

| Geographic Tier | Category Gating Policy | Filtering Rules |
| :--- | :--- | :--- |
| **Isfahan** | **Exhaustive Sweep** | Every architectural office, contractor, student, and active project is admitted with **zero filtering**. |
| **Other Iranian Cities** | **Strict Quality Gating** | • **Active Projects**: Admitted ONLY if large-scale/big-span (towers, hospitals, malls, civic complexes, $\ge 7$ floors or $\ge 3000\,\text{m}^2$).<br>• **Offices & Contractors**: All admitted.<br>• **Students**: Admitted ONLY if top-tier (see filter below). |
| **International** | **Opportunistic** | Admitted only if high-intent facade/architecture consulting firms (Dubai/UAE, Muscat, Doha, Europe). |

### Concrete "Best" Filter for Non-Isfahan Architecture Students
Students outside Isfahan are admitted if and only if they match at least one verified qualification marker:
1. **Top University Program**: University of Tehran (دانشگاه تهران), Shahid Beheshti (شهید بهشتی), Iran University of Science & Technology - IUST (علم و صنعت), Tarbiat Modares (تربیت مدرس), Sharif / Amirkabir.
2. **National / International Competition Laureates**: Memar Award (جایزه معمار), Mirmiran Award (جایزه میرمیران), 2A Architectural Awards, ArchDaily/Dezeen featured.
3. **Publication / Leadership**: Published research on Civilica/Magiran/ISC or Scientific Architecture Association leadership.

---

## 🔄 4. Duplicate-Merging System

- **Pre-Merge Raw Record Logging**: Every incoming entity payload is immutably logged into `raw_records` table and `raw_records.jsonl` before any matching decision.
- **Primary Exact-Match (Auto-Merge)**: Exact matches on normalized phone (`0913...`, `031...`) or email auto-merge immediately with `verified` confidence.
- **Secondary Fuzzy Composite Match**: Normalized composite string `clean_name + clean_company` is evaluated with `rapidfuzz.fuzz.token_sort_ratio` and `token_set_ratio`:
  - **Score $\ge 88.0\%$**: Auto-merged with `high_fuzzy` confidence.
  - **$70.0\% \le \text{Score} < 88.0\%$**: Quarantined into `ambiguous_reviews` table and logged in review audit for human inspection without auto-merging.
  - **Score $< 70.0\%$**: Created as distinct entity.
- **Lossless URL Retention**: All discovered URLs are merged into a semicolon-delimited chain (`https://site.ir; https://instagram.com/xyz`). **No source URL is ever discarded.**

---

## 📊 5. Output Schemas

The engine generates two strictly separate CSV files:

### `active_projects.csv`
| Column | Description |
| :--- | :--- |
| `project name` | Title/name of the project |
| `city` | Project location (e.g. Isfahan, Tehran) |
| `scale/scope` | Floors, area in sqm, facade specifications |
| `associated contractor(s)` | Semicolon-separated contractor firms |
| `associated architect(s)/office` | Semicolon-separated architect firms |
| `contact info` | Project manager phone, email, or handle |
| `source URL` | Semicolon-separated source attribution links |
| `confidence` | Confidence level (`verified`, `high`, `medium`) |
| `date found` | Date registered (YYYY-MM-DD) |

### `contacts.csv`
| Column | Description |
| :--- | :--- |
| `entity_type (office/contractor/student/individual)` | Target category classification |
| `name` | Lead person name or representative |
| `role` | Professional title (e.g. Lead Architect, Project Manager) |
| `company` | Office or company name |
| `city` | Geographic location |
| `phone` | Normalized telephone / mobile number |
| `email` | Normalized email address |
| `social handle` | Telegram / Instagram handle (@...) |
| `source_url` | Full source URL provenance chain |
| `confidence` | Confidence indicator (`verified`, `high`, `high_fuzzy`) |
| `last_verified` | Verification timestamp (YYYY-MM-DD) |

---

## 🚀 6. CLI Usage & Operations

### Run Autonomous Crawler
```bash
# Standard balanced run (default budget: 180s, max 12 passes)
python main.py run

# Custom parameters
python main.py run --max-passes 15 --channels 3 --budget-sec 120 --results-per-query 4
```

### Export CSVs from Cache
```bash
python main.py export
```

### View Cache & Harvester Statistics
```bash
python main.py stats
```

### Run Benchmark Audit against Known Entities
```bash
python main.py validate
```

### Launch Graphical User Interface (GUI)
```bash
# Launch directly via CLI command
python main.py ui

# Or run the UI script directly
python ui.py
```

### Standalone Windows Executable (`.exe`)
The application is packaged as a standalone Windows `.exe` (`dist/NoavaranScraper.exe`).
- **Zero Python Installation Required**: Double-click `NoavaranScraper.exe` in Windows Explorer to launch the full GUI dashboard.
- **Console-Free**: Runs natively without a terminal console window.
- **Portability**: Automatically creates and manages `data/scraper_cache.db`, `contacts.csv`, and `active_projects.csv` right next to the executable.
- **Rebuilding the Executable**:
  ```powershell
  python -m PyInstaller --clean --onefile --noconsole --name NoavaranScraper --hidden-import ddgs --hidden-import rapidfuzz --hidden-import pydantic --hidden-import bs4 --hidden-import requests main.py
  ```

---

## 🖥️ 7. Desktop GUI Features

The desktop application includes 5 comprehensive functional views:
1. **🚀 Crawl Dashboard & Controls (کنترل پویشگر)**:
   - Configurable parameters (Max passes, streak termination, time budget, Telegram channels, results per query, frontier limit).
   - Start / Stop controls with background worker thread and thread-safe cancellation.
   - Real-time animated progress bar and live status updates.
   - Live colorized console output with auto-scroll, clear, and copy-to-clipboard tools.
   - 1-Click Cache Rebuild and Isfahan Benchmark validation buttons.
2. **👥 Contacts & Leads Explorer (مخاطبین و سرنخ‌ها)**:
   - Multi-field search filtering (Name, Company, Role, City, Phone, Email).
   - Category filtering (`office`, `contractor`, `student`, `individual`) and City filtering (`Isfahan`, `Tehran`, `Other`).
   - Clickable column sorting on all fields.
   - Selected entity inspector with 1-click Phone copy, Email copy, and Source URL browser opener.
3. **🏗️ Active Projects Explorer (پروژه‌های فعال ساختمانی)**:
   - Multi-field search filtering (Project Name, Contractor, Architect, City, Scope).
   - City filtering and clickable column sorting.
   - Selected project inspector showing full contractors, architects, scale, and contact info.
4. **⚖️ Ambiguous Reviews Quarantine (بررسی برخوردهای مبهم)**:
   - View quarantined candidate entities with fuzzy composite match score between 70% and 87%.
   - Full raw JSON payload inspection for human review and auditing.
5. **📁 CSV Export & Directory Tools (خروجی‌ها و فایل‌ها)**:
   - 1-Click export and custom "Save As..." export for `contacts.csv` and `active_projects.csv`.
   - Direct button to open the application directory or view CSV files in Excel.

---

## 🧪 8. Verification & Benchmark Record

### Automated Test Suite (36 Tests Passing)
```bash
python -m pytest tests/ -v
```
- `tests/test_dedup.py` (12 tests): Verifies phone exact-merge, email exact-merge, fuzzy composite merge, ambiguous quarantine, project dedup, multi-phone/email lossless merge, punctuation stripping, generic title guards, and URL preservation.
- `tests/test_fixes_verification.py` (9 tests): Verifies city snippet normalization, LinkedIn classification, non-entity filtering, cross-lingual matching (Razan / رازان), corporate ID phone rejection, and clean name formatting.
- `tests/test_geo_filter.py` (5 tests): Verifies Isfahan sweep, large-scale project classifier, top-tier student gatekeeping, entity admission, and project admission.
- `tests/test_harvesters_and_exporters.py` (6 tests): Verifies regex extraction, LinkedIn/Instagram SERP parsers, CSV exporters, architect/contractor party parser, and frontier queue operations.
- `tests/test_ui.py` (4 tests): Verifies GUI initialization, tab layout, live search, multi-criteria filtering, and table column sorting.
- **Result:** 36 passing tests (100% pass rate).

### Benchmark Precision Audit
Harvested data was cross-validated against 15 hand-picked Isfahan entities (Razan Architects, Padiav Architecture, Naghsh-e Jahan Consulting Engineers, Sharestan Studio, Isfahan Engineering Organization, Isfahan Architecture Academy, Nama Gostaran, etc.):
- **Duplicate Phone Violations:** 0
- **Duplicate Email Violations:** 0
- **Phone / Contact Precision Rate:** 72.2%
- **Benchmark Coverage:** Discovered and verified core Isfahan leaders with full provenance.

---

## 🛡️ 9. Security Sentinel Audit
- **SAST Scan (Bandit)**: 0 High, 0 Medium issues across all Python source files.
- **Secret Scan**: 0 leaked API keys, tokens, or credentials.
- **Dependency Audit**: Clean pinned packages in `requirements.txt`.
