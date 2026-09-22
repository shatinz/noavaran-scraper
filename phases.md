# Roadmap & Execution Blueprint (`phases.md`)
## Lead-Discovery Scraper Engine for Noavaran Panjereh (نوآوران پنجره)

> **North Star & Ultimate Goal:**
> Build, validate, and operationalize a production-grade, highly resilient lead-discovery and project-tracking scraper engine for **Noavaran Panjereh** (leading Isfahan door, window, and architectural facade manufacturer). The engine autonomously harvests high-intent leads across 4 target categories (architectural offices, construction contractors, architecture students, and active building projects), enforcing strict geographic filtering, multi-source coverage (Search Engines, Telegram public previews, LinkedIn snippets, Instagram public bios, and target websites), zero-token-waste heuristic extraction, continuous deduplication with phone/email exact-matching, fuzzy composite matching, ambiguous review flagging, lossless source URL retention, and exports cleanly to `active_projects.csv` and `contacts.csv`.

---

## 📌 Phase Overview & Status Matrix

| Phase | Title | Status | Primary Deliverable |
| :---: | :--- | :---: | :--- |
| **0** | Research Comparison & Technical Specification | `[x] Completed` | Written research document (`research_and_spec.md`) comparing methods, token minimization, dedup strategy, and student filter |
| **1** | Architecture, Data Models & Persistent Storage | `[x] Completed` | Pydantic data schemas, SQLite cache database, Persian text normalizer, and dual CSV exporters |
| **2** | Deduplication & Entity Resolution Engine | `[x] Completed` | Exact-match (phone/email), RapidFuzz composite name+company resolver, ambiguous match review logger, lossless URL merger, and comprehensive test suite |
| **3** | Multi-Source Harvester Engine | `[x] Completed` | Search engine extractor (DuckDuckGo/Bing/Google dorks), Telegram `t.me/s/` HTTP parser, LinkedIn snippet extractor, Instagram bio harvester, and zero-LLM web DOM pruner |
| **4** | Geographic Priority & Tier-Gating Engine | `[x] Completed` | Exhaustive Isfahan sweep, large-scale project filter, top-tier student gatekeeper (awards/universities), and opportunistic international firm finder |
| **5** | Crawler Orchestrator & Benchmark Validation | `[x] Completed` | Persistent frontier crawl queue, budget stop conditions (streak/timeout), and small-batch validation against 10-20 known Isfahan benchmark entities |
| **6** | Iteration Loop, Precision Tuning & Git Sync | `[x] Completed` | Iterative gap analysis, pattern tuning, Security Sentinel scan, and remote repository push |
| **7** | Desktop GUI & Windows Standalone Executable | `[x] Completed` | Modern multi-tab Tkinter/TTK desktop UI (`ui.py`), real-time console streaming & controls, search/sort filters, and standalone Windows `.exe` (`dist/NoavaranScraper.exe`) |

---

## 🎯 Phase 0: Research Comparison & Technical Specification
- **Boundaries**:
  - Inside: Rigorous technical comparison of Telegram scraping, search-engine-based LinkedIn & Instagram discovery, token-minimization patterns, deduplication logic, and concrete qualification filters for architecture students outside Isfahan.
  - Outside: Writing crawler implementation code.
- **Tasks**:
  - `[x]` Research Telegram public channels/groups methods (`t.me/s/` vs. Telethon)
  - `[x]` Research search-engine dorking for LinkedIn and Instagram public pages avoiding platform bans
  - `[x]` Design zero-LLM token-efficient extraction pipeline (Regex + DOM pruning + heuristic schemas)
  - `[x]` Specify exact vs. fuzzy deduplication rules with human-review quarantine for ambiguous matches
  - `[x]` Define concrete "top-tier" architecture student criteria outside Isfahan
  - `[x]` Produce `research_and_spec.md` deliverable

---

## 🎯 Phase 1: Architecture, Data Models & Persistent Storage
- **Boundaries**:
  - Inside: Normalization library (`normalizer.py`), Pydantic models (`models.py`), SQLite storage backend (`database.py`), CSV writers (`exporters.py`).
  - Outside: Live scraping logic.
- **Tasks**:
  - `[x]` Persian Unicode canonicalization (`ي`->`ی`, `ك`->`ک`, Persian/Arabic digits to ASCII, zero-width space normalization)
  - `[x]` Iranian phone number standardizer (E.164 and local 09xx/031xx normalization)
  - `[x]` Email and URL normalizer
  - `[x]` Data schemas for `ActiveProject` and `ContactEntity` matching exact CSV column specs
  - `[x]` Persistent SQLite cache schema (`entities`, `projects`, `raw_records`, `frontier`, `reviews`)
  - `[x]` Clean CSV exporters ensuring two separate files (`active_projects.csv` and `contacts.csv`)

---

## 🎯 Phase 2: Deduplication & Entity Resolution Engine
- **Boundaries**:
  - Inside: Real-time deduplication engine (`dedup.py`), fuzzy matching using RapidFuzz, ambiguous record logging, unit tests (`tests/test_dedup.py`).
  - Outside: Network harvesting.
- **Tasks**:
  - `[x]` Primary exact-match engine on normalized phone and email
  - `[x]` Secondary composite fuzzy-match engine on `normalized_name + normalized_company`
  - `[x]` Confidence score calculation (Auto-merge >= 88%, Ambiguous 70-87%, Distinct < 70%)
  - `[x]` Lossless merge logic: aggregate all discovered `source_urls` with delimiter, merge non-empty attributes
  - `[x]` Raw record preservation: append raw incoming record to `raw_records` table on every operation
  - `[x]` Ambiguous review quarantine queue for human inspection
  - `[x]` Unit test suite verifying exact merge, fuzzy merge, ambiguity flagging, and URL retention

---

## 🎯 Phase 3: Multi-Source Harvester Engine
- **Boundaries**:
  - Inside: Scraping adapters for Search Engines, Telegram public web views, LinkedIn snippets, Instagram bios, and corporate websites.
  - Outside: Geographic routing and crawl loops.
- **Tasks**:
  - `[x]` Search engine runner using `ddgs` with resilient fallback and rate-limit backoff
  - `[x]` Telegram public channel web preview parser (`https://t.me/s/<channel>`) extracting posts, forwards, and contacts
  - `[x]` LinkedIn indexed snippet parser extracting names, titles, companies, locations without visiting LinkedIn
  - `[x]` Instagram indexed bio parser extracting handles, bio text, phone numbers, and portfolio links without visiting Instagram
  - `[x]` Targeted website DOM pruner: zero-token extraction of contact pages, projects, and about pages

---

## 🎯 Phase 4: Geographic Priority & Tier-Gating Engine
- **Boundaries**:
  - Inside: Geographic router and classifier (`geo_filter.py`).
  - Outside: Database storage.
- **Tasks**:
  - `[x]` Isfahan exhaustive pass router: accept all categories with no filtering
  - `[x]` Non-Isfahan active project scale analyzer: accept only large-scale/big-span projects
  - `[x]` Non-Isfahan student gatekeeper: evaluate against top universities, competition awards, and published papers
  - `[x]` Opportunistic international firm discovery: target GCC/regional and European facade/architectural consultants

---

## 🎯 Phase 5: Crawler Orchestrator & Benchmark Validation
- **Boundaries**:
  - Inside: Orchestration loop (`crawler.py`), CLI runner (`main.py`), persistent frontier queue, stop condition evaluator.
  - Outside: Final audit report.
- **Tasks**:
  - `[x]` Multi-pass frontier crawler with recursive seed discovery
  - `[x]` Stop conditions: max entities, max time budget, and streak termination (`N` consecutive empty passes)
  - `[x]` Small-batch initial run execution
  - `[x]` Validation against benchmark of 10-20 known Isfahan architectural and construction entities

---

## 🎯 Phase 6: Iteration Loop, Precision Tuning & Git Sync
- **Boundaries**:
  - Inside: Comparison of crawler results vs. manual deep-search, heuristic refinement, security audit, and remote push.
  - Outside: N/A.
- **Tasks**:
  - `[x]` Compare crawler output with manual domain search
  - `[x]` Tune extraction patterns and fuzzy thresholds based on findings
  - `[x]` Re-run full pipeline and verify both `active_projects.csv` and `contacts.csv`
  - `[x]` Run security scan via `security-sentinel`
  - `[x]` Commit all files and push repository to GitHub

---

## 🎯 Phase 7: Desktop GUI & Windows Standalone Executable
- **Boundaries**:
  - Inside: Graphical User Interface (`ui.py`), real-time multithreaded crawler execution, live console stream, entity inspection tables with sorting/filtering, ambiguous review viewer, CSV export dialogs, automated UI tests (`tests/test_ui.py`), and standalone Windows `.exe` packaging (`dist/NoavaranScraper.exe`).
  - Outside: Modifying core network harvester protocols.
- **Tasks**:
  - `[x]` Build modern multi-tab desktop UI (`ui.py`) using `tkinter` + `ttk` with Windows high-DPI scaling
  - `[x]` Implement thread-safe execution (`threading.Thread`, `queue.Queue`) for non-blocking crawler runs, cache rebuilds, and benchmark validation
  - `[x]` Implement graceful scraper cancellation (`stop_event`)
  - `[x]` Build searchable & sortable Treeviews for Contacts and Active Projects with live details viewer
  - `[x]` Add Ambiguous Matches review tab for inspecting 70-87% confidence entity clashes
  - `[x]` Add CSV Export & Directory Explorer tab with 1-click and custom file dialog export
  - `[x]` Create automated test suite for UI (`tests/test_ui.py`) verifying tab initialization, search, filtering, and sorting
  - `[x]` Package standalone Windows executable with PyInstaller (`dist/NoavaranScraper.exe`)
  - `[x]` Verify `--noconsole` and frozen base directory resolution for seamless double-click execution
  - `[x]` Harden UI & executable against uninitialized databases, enable SQLite WAL mode, attach parent console and redirected pipes for CLI commands, cancel pending Tk timer jobs on shutdown, and normalize Persian/Arabic queries in live search
  - `[x]` Deep test suite expansion for UI (`tests/test_ui.py`) covering 10 isolated test cases (session Tk fixture, CSV export isolation, clipboard actions, Persian search, ambiguous reviews, and graceful shutdown)

