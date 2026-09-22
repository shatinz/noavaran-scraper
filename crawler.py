import time
import uuid
from typing import List, Dict, Any, Optional
from datetime import datetime

from models import ContactEntity, ActiveProject
from database import (
    init_db,
    add_frontier_urls,
    get_pending_frontier,
    update_frontier_status,
    DEFAULT_DB_PATH,
)
from dedup import DeduplicationEngine
from harvesters.search_engine import SearchHarvester
from harvesters.telegram_scraper import TelegramScraper, DEFAULT_TELEGRAM_CHANNELS
from harvesters.web_extractor import TargetedWebExtractor
from exporters import export_all_csvs

# Balanced interleaved queries across all 4 target categories and geographic tiers
SEED_QUERIES = [
    # 1. Active Projects in Isfahan (Commercial & Luxury)
    {"type": "search_project", "category": "project", "q": 'پروژه مجتمع اداری تجاری مهستان نقش جهان اصفهان'},
    {"type": "search_project", "category": "project", "q": 'پروژه در حال ساخت اصفهان "مجری" OR "کارفرما" OR "معمار"'},
    
    # 2. Isfahan Architecture & Design Offices
    {"type": "search_web", "category": "office", "q": 'شرکت معماری اصفهان "تلفن" "0913"'},
    {"type": "instagram", "category": "office", "q": 'site:instagram.com "razanarchitects" OR "دفتر معماری رازان"'},
    {"type": "linkedin_company", "category": "office", "q": 'site:linkedin.com/company ("معماری" OR "مهندسین مشاور") "اصفهان"'},

    # 3. Facade & Window Construction Contractors
    {"type": "search_web", "category": "contractor", "q": 'پیمانکار نما اصفهان "کرتین وال" OR "ترمال بریک" "تلفن"'},
    {"type": "search_web", "category": "contractor", "q": '"شرکت آروین پنجره پارتاک" OR "نوآوران پنجره" اصفهان'},
    {"type": "instagram", "category": "contractor", "q": 'site:instagram.com ("مجری نما" OR "نصاب پنجره" OR "پیمانکار ساختمان") "اصفهان"'},

    # 4. Active Large-Scale Projects (Isfahan & National Towers)
    {"type": "search_project", "category": "project", "q": 'برج مسکونی تجاری اصفهان "در حال اجرا" OR "پیش فروش"'},
    {"type": "search_project", "category": "project", "q": 'سیتی سنتر شاهین شهر "پروژه" OR "کارفرما"'},
    {"type": "search_project", "category": "project", "q": 'پروژه برج مجتمع تجاری بزرگ در حال ساخت تهران OR شیراز "نمای کرتین وال"'},

    # 5. Architecture Students (Isfahan & Top-Tier Universities)
    {"type": "linkedin", "category": "student", "q": 'site:linkedin.com/in ("دانشجوی معماری" OR "architecture student") ("اصفهان" OR "هنر اصفهان")'},
    {"type": "linkedin", "category": "student", "q": 'site:linkedin.com/in "دانشجوی معماری" ("دانشگاه تهران" OR "شهید بهشتی") "مسابقه"'},

    # 6. Benchmark Known Architecture Offices
    {"type": "search_web", "category": "office", "q": '"مهندسین مشاور نقش جهان" اصفهان "معماری"'},
    {"type": "search_web", "category": "office", "q": '"گروه معماری پادیاو" اصفهان'},
    {"type": "search_web", "category": "office", "q": '"استودیو معماری شارستان" اصفهان'},
    {"type": "search_web", "category": "office", "q": '"شرکت مهندسی بافت شهر" اصفهان'},

    # 7. Contractors & Specialized Facade Installers
    {"type": "search_web", "category": "contractor", "q": '"نما گستران" OR "پرشیا پنجره" اصفهان "پنجره"'},
    {"type": "linkedin_company", "category": "contractor", "q": 'site:linkedin.com/company "پیمانکار ساختمان" تهران'},

    # 8. International Opportunistic (High Intent Facade Consultants)
    {"type": "search_web", "category": "office", "q": 'architectural facade engineering consultancy Dubai UAE contact email'},
]


class LeadDiscoveryCrawler:
    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        self.db_path = db_path
        init_db(db_path)
        self.dedup = DeduplicationEngine(db_path=db_path)
        self.search_harvester = SearchHarvester()
        self.telegram_scraper = TelegramScraper()
        self.web_extractor = TargetedWebExtractor()

    def run(
        self,
        run_id: Optional[str] = None,
        max_passes: int = 15,
        streak_limit: int = 4,
        time_budget_sec: int = 180,
        max_telegram_channels: int = 4,
        max_results_per_query: int = 5,
    ) -> Dict[str, Any]:
        """
        Execute an autonomous crawler run with budget constraints and streak termination:
        - Terminate if no new entities discovered in `streak_limit` consecutive passes.
        - Terminate if elapsed time exceeds `time_budget_sec`.
        - Updates persistent frontier queue and exports CSVs on every pass.
        """
        run_id = run_id or f"run-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
        start_time = time.time()

        total_contacts_discovered = 0
        total_projects_discovered = 0
        new_entities_this_run = 0
        streak_zero_count = 0

        # Step 1: Telegram Channel Harvest (Fast direct HTTP previews)
        print(f"[{run_id}] Starting Telegram Harvester Pass...")
        tg_channels = DEFAULT_TELEGRAM_CHANNELS[:max_telegram_channels]
        for ch in tg_channels:
            if time.time() - start_time > time_budget_sec:
                print("Time budget reached during Telegram pass.")
                break

            posts, _ = self.telegram_scraper.fetch_channel_messages(ch)
            ch_contacts = 0
            ch_projects = 0

            for p in posts:
                contacts, projects = self.telegram_scraper.extract_entities_and_projects(p)
                for c in contacts:
                    _, action = self.dedup.process_contact(c, run_id=run_id, source_type="telegram")
                    total_contacts_discovered += 1
                    if action in ("created_new", "merged_fuzzy"):
                        ch_contacts += 1
                        new_entities_this_run += 1
                for pr in projects:
                    _, action = self.dedup.process_project(pr, run_id=run_id, source_type="telegram")
                    total_projects_discovered += 1
                    if action in ("created_new", "merged_fuzzy"):
                        ch_projects += 1
                        new_entities_this_run += 1

            print(f"  Channel @{ch}: found {len(posts)} messages -> +{ch_contacts} contacts, +{ch_projects} projects")

        # Step 2: Search Engine Queries Pass
        print(f"[{run_id}] Starting Search Engine Harvester Passes...")
        queries_to_run = SEED_QUERIES[:max_passes]

        for i, q_def in enumerate(queries_to_run):
            # Check Stop Conditions
            elapsed = time.time() - start_time
            if elapsed > time_budget_sec:
                print(f"Time budget reached ({elapsed:.1f}s > {time_budget_sec}s). Stopping run.")
                break

            if streak_zero_count >= streak_limit:
                print(f"Streak termination condition reached ({streak_zero_count} consecutive passes with 0 new entities). Stopping run.")
                break

            q_type = q_def["type"]
            query_str = q_def["q"]
            category = q_def["category"]

            print(f"  Pass {i+1}/{len(queries_to_run)} [{q_type}] '{query_str[:40]}...'")
            results = self.search_harvester.search_query(query_str, max_results=max_results_per_query)

            pass_new_entities = 0

            for item in results:
                discovered_url = item.get("href", "")
                if not discovered_url:
                    continue

                # Add to frontier
                self.dedup.log_raw_entry(run_id, q_type, discovered_url, item)

                if q_type == "linkedin" or q_type == "linkedin_company":
                    contact = self.search_harvester.parse_linkedin_snippet(item)
                    if contact:
                        _, action = self.dedup.process_contact(contact, run_id, q_type)
                        total_contacts_discovered += 1
                        if action in ("created_new", "merged_fuzzy"):
                            pass_new_entities += 1

                elif q_type == "instagram":
                    contact = self.search_harvester.parse_instagram_snippet(item)
                    if contact:
                        _, action = self.dedup.process_contact(contact, run_id, q_type)
                        total_contacts_discovered += 1
                        if action in ("created_new", "merged_fuzzy"):
                            pass_new_entities += 1

                elif q_type == "search_project":
                    project = self.search_harvester.parse_web_project_snippet(item)
                    if project:
                        _, action = self.dedup.process_project(project, run_id, q_type)
                        total_projects_discovered += 1
                        if action in ("created_new", "merged_fuzzy"):
                            pass_new_entities += 1

                elif q_type == "search_web":
                    # General search snippet + optional shallow web extract
                    body = item.get("body", "")
                    title = item.get("title", "")
                    combined = f"{title} {body}"
                    from harvesters.text_parser import extract_phones, extract_emails, extract_social_handles
                    ph = extract_phones(combined)
                    em = extract_emails(combined)
                    hd = extract_social_handles(combined)
                    if ph or em or hd:
                        from models import ContactEntity
                        from geo_filter import classify_geography
                        geo_tier = classify_geography(combined)
                        c = ContactEntity(
                            entity_type="office" if "شرکت" in combined else "contractor",
                            name=title.split("-")[0].split("|")[0].strip(),
                            role="دفتر معماری / پیمانکار",
                            company=title.split("-")[0].split("|")[0].strip(),
                            city="Isfahan" if geo_tier == "isfahan" else "Tehran",
                            phone=ph[0] if ph else "",
                            email=em[0] if em else "",
                            social_handle=hd[0] if hd else "",
                            source_url=discovered_url,
                            confidence="verified" if ph else "high",
                        )
                        _, action = self.dedup.process_contact(c, run_id, q_type)
                        total_contacts_discovered += 1
                        if action in ("created_new", "merged_fuzzy"):
                            pass_new_entities += 1

            if pass_new_entities == 0:
                streak_zero_count += 1
            else:
                streak_zero_count = 0
                new_entities_this_run += pass_new_entities

            print(f"    -> Discovered +{pass_new_entities} new entities (zero-streak: {streak_zero_count})")

        # Step 3: Export CSVs
        export_stats = export_all_csvs(self.db_path)

        summary = {
            "run_id": run_id,
            "duration_sec": round(time.time() - start_time, 2),
            "new_entities_this_run": new_entities_this_run,
            "total_contacts_discovered": total_contacts_discovered,
            "total_projects_discovered": total_projects_discovered,
            "total_contacts_in_cache": export_stats["contacts_exported"],
            "total_projects_in_cache": export_stats["projects_exported"],
            "contacts_csv": export_stats["contacts_file"],
            "projects_csv": export_stats["projects_file"],
        }
        return summary
