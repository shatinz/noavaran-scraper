import re
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
    {"type": "search_web", "category": "contractor", "q": '"پرشین سازه" اصفهان "پیمانکار" OR "مجری"'},
    {"type": "search_web", "category": "office", "q": '"مهندسین مشاور شهر و اندیشه" اصفهان'},
    {"type": "search_web", "category": "office", "q": '"دفتر معماری فضا، رویداد، شهر" اصفهان OR "فضا رویداد شهر"'},
    {"type": "search_web", "category": "student", "q": 'دانشکده معماری دانشگاه هنر اصفهان'},
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
        max_frontier_items: int = 10,
    ) -> Dict[str, Any]:
        """
        Execute an autonomous crawler run with budget constraints and streak termination:
        - Step 1: Telegram Channel Harvest (fast previews + frontier links extraction)
        - Step 2: Search Engine Queries (snippets + queueing target websites to frontier)
        - Step 3: Frontier Queue Deep Crawl (visiting company websites & subpages via TargetedWebExtractor)
        - Terminate if no new entities discovered in `streak_limit` consecutive passes.
        - Terminate if elapsed time exceeds `time_budget_sec`.
        - Exports CSVs on completion.
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

                # Extract frontier links to queue new channels and company websites
                links = self.telegram_scraper.extract_frontier_links(p.get("text", ""))
                if links:
                    add_frontier_urls(links, self.db_path)

            print(f"  Channel @{ch}: found {len(posts)} messages -> +{ch_contacts} contacts, +{ch_projects} projects")

        # Step 2: Search Engine Queries Pass
        print(f"[{run_id}] Starting Search Engine Harvester Passes...")
        queries_to_run = SEED_QUERIES[:max_passes]

        for i, q_def in enumerate(queries_to_run):
            elapsed = time.time() - start_time
            if elapsed > time_budget_sec:
                print(f"Time budget reached ({elapsed:.1f}s > {time_budget_sec}s). Stopping search pass.")
                break

            if streak_zero_count >= streak_limit:
                print(f"Streak termination condition reached ({streak_zero_count} consecutive passes with 0 new entities).")
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

                self.dedup.log_raw_entry(run_id, q_type, discovered_url, item)

                # Queue target websites to frontier for deep crawl
                if "instagram.com" not in discovered_url and "linkedin.com" not in discovered_url:
                    add_frontier_urls([{
                        "url": discovered_url,
                        "source_type": "web",
                        "category": category,
                        "depth": 0,
                    }], self.db_path)

                if q_type in ("linkedin", "linkedin_company"):
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
                        from normalizer import clean_entity_name, GENERIC_TITLES
                        geo_tier = classify_geography(combined)
                        title_parts = [p.strip() for p in re.split(r'[-–—|؛:،]', title) if p.strip()]
                        valid_parts = [p for p in title_parts if clean_entity_name(p).lower() not in GENERIC_TITLES and p.lower() not in GENERIC_TITLES]
                        raw_c_name = valid_parts[0] if valid_parts else title
                        c_name = clean_entity_name(raw_c_name)
                        c = ContactEntity(
                            entity_type="office" if any(k in combined for k in ["معماری", "مشاور", "طراحی"]) else "contractor",
                            name=c_name or "دفتر معماری / پیمانکار",
                            role="دفتر معماری / پیمانکار",
                            company=c_name,
                            city="Isfahan" if geo_tier == "isfahan" else normalize_city(combined),
                            phone="; ".join(ph),
                            email="; ".join(em),
                            social_handle="; ".join(hd),
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

        # Step 3: Frontier Queue Deep Extraction Pass
        print(f"[{run_id}] Starting Frontier Queue Deep Extraction Pass...")
        pending_items = get_pending_frontier(limit=max_frontier_items, db_path=self.db_path)
        print(f"  Found {len(pending_items)} pending URLs in frontier queue...")

        frontier_new = 0
        for f_item in pending_items:
            if time.time() - start_time > time_budget_sec:
                print("Time budget reached during frontier pass.")
                break

            f_url = f_item["url"]
            f_type = f_item.get("source_type", "web")
            f_depth = f_item.get("depth", 0)

            if f_type == "web":
                try:
                    f_contacts, f_projects, f_sub_links = self.web_extractor.extract_from_website(f_url)
                    for c in f_contacts:
                        _, action = self.dedup.process_contact(c, run_id=run_id, source_type="web_frontier")
                        total_contacts_discovered += 1
                        if action in ("created_new", "merged_fuzzy"):
                            frontier_new += 1
                            new_entities_this_run += 1
                    for pr in f_projects:
                        _, action = self.dedup.process_project(pr, run_id=run_id, source_type="web_frontier")
                        total_projects_discovered += 1
                        if action in ("created_new", "merged_fuzzy"):
                            frontier_new += 1
                            new_entities_this_run += 1

                    # Queue high-value subpages (/contact, /about, /projects) to frontier at depth + 1
                    if f_depth < 2 and f_sub_links:
                        sub_items = [{
                            "url": sl,
                            "source_type": "web",
                            "category": f_item.get("category", "general"),
                            "depth": f_depth + 1,
                        } for sl in f_sub_links[:5]]
                        add_frontier_urls(sub_items, self.db_path)

                    update_frontier_status(f_url, "visited", self.db_path)
                except Exception:
                    update_frontier_status(f_url, "failed", self.db_path)

            elif f_type == "telegram":
                try:
                    posts, _ = self.telegram_scraper.fetch_channel_messages(f_url)
                    for p in posts:
                        f_contacts, f_projects = self.telegram_scraper.extract_entities_and_projects(p)
                        for c in f_contacts:
                            _, action = self.dedup.process_contact(c, run_id=run_id, source_type="tg_frontier")
                            total_contacts_discovered += 1
                            if action in ("created_new", "merged_fuzzy"):
                                frontier_new += 1
                                new_entities_this_run += 1
                        for pr in f_projects:
                            _, action = self.dedup.process_project(pr, run_id=run_id, source_type="tg_frontier")
                            total_projects_discovered += 1
                            if action in ("created_new", "merged_fuzzy"):
                                frontier_new += 1
                                new_entities_this_run += 1
                    update_frontier_status(f_url, "visited", self.db_path)
                except Exception:
                    update_frontier_status(f_url, "failed", self.db_path)

        print(f"  Frontier pass completed -> +{frontier_new} new entities discovered from deep crawl")

        # Step 4: Export CSVs
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

    def rebuild_cache_from_raw(self) -> Dict[str, Any]:
        """
        Re-process all pre-merge raw records using the latest normalization,
        extraction, and deduplication logic, then re-export CSVs.
        """
        import sqlite3
        import json
        import os
        from harvesters.text_parser import (
            extract_phones,
            extract_emails,
            extract_social_handles,
            clean_party_candidate,
        )
        from geo_filter import classify_geography
        from normalizer import clean_entity_name, normalize_city, GENERIC_TITLES

        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("SELECT id, run_id, source_type, source_url, raw_json FROM raw_records ORDER BY id ASC")
        raw_rows = cur.fetchall()

        # Clear active contacts and projects tables, preserving raw_records and frontier
        cur.execute("DELETE FROM contacts")
        cur.execute("DELETE FROM active_projects")
        cur.execute("DELETE FROM ambiguous_reviews")
        conn.commit()
        conn.close()

        # Reset raw_records.jsonl
        if os.path.exists(self.dedup.raw_log_path):
            try:
                os.remove(self.dedup.raw_log_path)
            except Exception:
                pass

        processed_contacts = 0
        processed_projects = 0

        for r_id, run_id, s_type, s_url, r_json in raw_rows:
            try:
                data = json.loads(r_json)
            except Exception:
                continue

            if s_type == "telegram":
                if "project_name" in data:
                    pr = ActiveProject(**data)
                    pr.associated_contractors = "; ".join([clean_party_candidate(c) for c in pr.associated_contractors.split(";") if clean_party_candidate(c)])
                    pr.associated_architects = "; ".join([clean_party_candidate(a) for a in pr.associated_architects.split(";") if clean_party_candidate(a)])
                    pr.city = normalize_city(pr.city)
                    self.dedup.process_project(pr, run_id, s_type)
                    processed_projects += 1
                else:
                    c = ContactEntity(**data)
                    c.name = clean_entity_name(c.name)
                    c.company = clean_entity_name(c.company)
                    c.city = normalize_city(c.city)
                    self.dedup.process_contact(c, run_id, s_type)
                    processed_contacts += 1

            elif s_type in ("linkedin", "linkedin_company"):
                if isinstance(data, dict) and "title" in data:
                    c_entity = self.search_harvester.parse_linkedin_snippet(data)
                    if c_entity:
                        self.dedup.process_contact(c_entity, run_id, s_type)
                        processed_contacts += 1

            elif s_type == "instagram":
                if isinstance(data, dict) and "title" in data:
                    c_entity = self.search_harvester.parse_instagram_snippet(data)
                    if c_entity:
                        self.dedup.process_contact(c_entity, run_id, s_type)
                        processed_contacts += 1

            elif s_type == "search_project":
                if isinstance(data, dict) and "title" in data:
                    p_entity = self.search_harvester.parse_web_project_snippet(data)
                    if p_entity:
                        self.dedup.process_project(p_entity, run_id, s_type)
                        processed_projects += 1

            elif s_type in ("web", "search_web"):
                if isinstance(data, dict) and "title" in data:
                    body = data.get("body", "")
                    title = data.get("title", "")
                    combined = f"{title} {body}"
                    ph = extract_phones(combined)
                    em = extract_emails(combined)
                    hd = extract_social_handles(combined)
                    if ph or em or hd:
                        geo_tier = classify_geography(combined)
                        title_parts = [p.strip() for p in re.split(r'[-–—|؛:،]', title) if p.strip()]
                        valid_parts = [p for p in title_parts if clean_entity_name(p).lower() not in GENERIC_TITLES and p.lower() not in GENERIC_TITLES]
                        raw_c_name = valid_parts[0] if valid_parts else title
                        c_name = clean_entity_name(raw_c_name)
                        c_entity = ContactEntity(
                            entity_type="office" if any(k in combined for k in ["معماری", "مشاور", "طراحی"]) else "contractor",
                            name=c_name or "دفتر معماری / پیمانکار",
                            role="دفتر معماری / پیمانکار",
                            company=c_name,
                            city="Isfahan" if geo_tier == "isfahan" else normalize_city(combined),
                            phone="; ".join(ph),
                            email="; ".join(em),
                            social_handle="; ".join(hd),
                            source_url=s_url,
                            confidence="verified" if ph else "high",
                        )
                        self.dedup.process_contact(c_entity, run_id, s_type)
                        processed_contacts += 1

        export_stats = export_all_csvs(self.db_path)
        return {
            "processed_raw_records": len(raw_rows),
            "processed_contacts": processed_contacts,
            "processed_projects": processed_projects,
            "contacts_exported": export_stats["contacts_exported"],
            "projects_exported": export_stats["projects_exported"],
        }

