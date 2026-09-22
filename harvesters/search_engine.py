import os
import time
import random
import re
from typing import List, Dict, Any, Optional
from ddgs import DDGS

from normalizer import normalize_persian_text, normalize_city, clean_entity_name
from models import ContactEntity, ActiveProject
from geo_filter import classify_geography, should_admit_entity, should_admit_project
from harvesters.text_parser import (
    extract_phones,
    extract_emails,
    extract_social_handles,
    detect_entity_type,
    extract_architects,
    extract_contractors,
)


class SearchHarvester:
    def __init__(self, max_retries: int = 3, delay_range: tuple = (1.0, 2.5)):
        self.max_retries = max_retries
        self.delay_range = delay_range
        self.proxy_url = os.environ.get("HTTP_PROXY") or "http://127.0.0.1:10808"

    def search_query(self, query: str, max_results: int = 10) -> List[Dict[str, Any]]:
        """Run search query via DDGS with proxy resilience and randomized jitter."""
        for attempt in range(self.max_retries):
            try:
                time.sleep(random.uniform(*self.delay_range))
                ddgs = DDGS(timeout=10, proxy=self.proxy_url)
                results = list(ddgs.text(query, max_results=max_results))
                return results
            except Exception:
                try:
                    ddgs = DDGS(timeout=10)
                    results = list(ddgs.text(query, max_results=max_results))
                    return results
                except Exception:
                    time.sleep(1.5 * (attempt + 1))
        return []

    def parse_linkedin_snippet(self, item: Dict[str, Any]) -> Optional[ContactEntity]:
        """
        Extract ContactEntity from indexed LinkedIn search result.
        Title format typically: "Full Name - Title at Company | LinkedIn"
        or "نام نام خانوادگی - مدیرعامل در شرکت فلان | LinkedIn"
        """
        title = item.get("title", "")
        body = item.get("body", "")
        url = item.get("href", "")

        clean_title = re.sub(r'\s*\|\s*LinkedIn.*$', '', title, flags=re.IGNORECASE)
        clean_title = re.sub(r'\s*-\s*LinkedIn.*$', '', clean_title, flags=re.IGNORECASE)

        name = ""
        role = ""
        company = ""

        # Delimiter parsing
        parts = re.split(r'\s*[-–—|]\s*', clean_title)
        if len(parts) >= 2:
            name = parts[0].strip()
            rest = " - ".join(parts[1:]).strip()
            # Check for "at" or "در"
            at_split = re.split(r'\s+(?:at|در|@)\s+', rest, flags=re.IGNORECASE)
            if len(at_split) >= 2:
                role = at_split[0].strip()
                company = at_split[1].strip()
            else:
                role = rest
        elif len(parts) == 1:
            name = parts[0].strip()
            role = "معمار / مهندس"

        combined_text = f"{title} {body}"
        geo_tier = classify_geography(combined_text)
        city = "Isfahan" if geo_tier == "isfahan" else normalize_city(combined_text)

        entity_type = detect_entity_type(combined_text)
        if "student" in role.lower() or "دانشجو" in combined_text:
            entity_type = "student"

        admit, _ = should_admit_entity(entity_type, geo_tier, combined_text)
        if not admit:
            return None

        phones = extract_phones(body)
        emails = extract_emails(body)
        handles = extract_social_handles(body)

        clean_pname = clean_entity_name(name)
        clean_cname = clean_entity_name(company)

        return ContactEntity(
            entity_type=entity_type,
            name=clean_pname or "متخصص معماری / ساختمان",
            role=role or "معمار / مهندس سازه",
            company=clean_cname or clean_pname,
            city=city,
            phone="; ".join(phones),
            email="; ".join(emails),
            social_handle="; ".join(handles),
            source_url=url,
            confidence="verified" if phones else "high",
        )

    def parse_instagram_snippet(self, item: Dict[str, Any]) -> Optional[ContactEntity]:
        """
        Extract ContactEntity from indexed Instagram bio search result.
        URL format: instagram.com/<handle>/
        Body typically contains: bio text, phone number, address, business title.
        """
        url = item.get("href", "")
        body = item.get("body", "")
        title = item.get("title", "")

        handle_match = re.search(r'instagram\.com/([a-zA-Z0-9_\.]+)', url)
        handle = f"@{handle_match.group(1)}" if handle_match else ""
        if handle.lower() in ("@p", "@explore", "@reels", "@stories", "@direct"):
            return None

        combined_text = f"{title} {body}"
        geo_tier = classify_geography(combined_text)
        city = "Isfahan" if geo_tier == "isfahan" else normalize_city(combined_text)

        entity_type = detect_entity_type(combined_text)
        admit, _ = should_admit_entity(entity_type, geo_tier, combined_text)
        if not admit:
            return None

        phones = extract_phones(body)
        emails = extract_emails(body)

        comp_title = re.sub(r'\(?@[a-zA-Z0-9_\.]+\)?.*$', '', title).strip()
        comp_title = re.sub(r'\s*•\s*Instagram.*$', '', comp_title, flags=re.IGNORECASE).strip()
        comp_title = re.sub(r'\s*\|\s*.*$', '', comp_title).strip()
        comp_title = clean_entity_name(comp_title)

        return ContactEntity(
            entity_type=entity_type,
            name=comp_title or handle,
            role="دفتر معماری / پیمانکار اجرایی",
            company=comp_title or handle,
            city=city,
            phone="; ".join(phones),
            email="; ".join(emails),
            social_handle=handle,
            source_url=url,
            confidence="verified" if phones else "high",
        )

    def parse_web_project_snippet(self, item: Dict[str, Any]) -> Optional[ActiveProject]:
        """Extract ActiveProject from general web search snippet."""
        title = item.get("title", "")
        body = item.get("body", "")
        url = item.get("href", "")
        combined = f"{title} {body}"

        geo_tier = classify_geography(combined)
        city = "Isfahan" if geo_tier == "isfahan" else normalize_city(combined)

        admit, _ = should_admit_project(geo_tier, combined)
        if not admit:
            return None

        EXCLUDED_PROJECT_DOMAINS = [
            'wikipedia.org', 'facebook.com', 'twitter.com', 'youtube.com', 'instagram.com',
            'aparat.com', 'virgool.io', 'civilica.com', 'magiran.com',
            'jobinja.ir', 'e-estekhdam.com', 'divar.ir', 'sheypoor.com',
            'goldensaze.com', 'ketabeavval.ir', 'behtarino.com', 'isoarch.ir',
            'balad.ir', 'neshan.org', 'nshn.ir', 'map.ir', 'snapp.ir', 'tapsi.ir',
            'pinwork.ir', 'achareh.ir', 'khedmatazma.com', 'ostadkar.ir'
        ]
        if any(d in url.lower() for d in EXCLUDED_PROJECT_DOMAINS):
            return None

        phones = extract_phones(combined)

        parts = [p.strip() for p in re.split(r'[-–—|؛:،]', title) if p.strip()]
        GENERIC_TITLES = {
            'خانه', 'صفحه اصلی', 'درباره ما', 'تماس با ما', 'صفحه نخست',
            'وب‌سایت رسمی', 'home', 'main', 'پروژه‌ها', 'پروژه ها', 'پروژه'
        }
        meaningful_parts = [p for p in parts if p.lower() not in GENERIC_TITLES]

        clean_title = ""
        for p in meaningful_parts:
            if any(k in p for k in ['مجتمع', 'برج', 'ساختمان', 'مرکز', 'بیمارستان', 'ویلا', 'مهستان', 'سیتی سنتر', 'پروژه']):
                clean_title = p
                break
        if not clean_title and meaningful_parts:
            clean_title = max(meaningful_parts, key=len)
        if not clean_title:
            clean_title = title.strip()

        clean_title = clean_entity_name(clean_title)

        EXCLUDED_TITLES = [
            'ویکی پدیا', 'ویکیپدیا', 'دانشنامه', 'بانک اطلاعات', 'لیست شرکت',
            'پروژه ها', 'پروژه‌ها', 'نمونه کار', 'گالری', 'درباره ما',
            'تماس با ما', 'جامعه معماران', 'استخدام', 'روی نقشه', 'نظرات مردم',
            'ساعت کاری', 'آدرس و تلفن', 'آدرس، تلفن', 'تصاویر و'
        ]
        if any(et in clean_title for et in EXCLUDED_TITLES) or len(clean_title.strip()) < 4:
            return None

        archs = extract_architects(combined)
        conts = extract_contractors(combined)

        arch_str = "; ".join(archs)
        contractor_str = "; ".join(conts)

        scale_matches = re.findall(r'(\d+\s+طبقه|\d+\s+مترمربع|کرتین وال|ترمال بریک|لوکس|تجاری|مسکونی)', combined)
        unique_scale = list(dict.fromkeys(scale_matches))
        scale_str = ", ".join(unique_scale) if unique_scale else "پروژه ساختمانی"

        return ActiveProject(
            project_name=clean_title or "پروژه ساختمانی",
            city=city,
            scale_scope=scale_str,
            associated_contractors=contractor_str,
            associated_architects=arch_str,
            contact_info="; ".join(phones),
            source_url=url,
            confidence="high" if phones or arch_str else "medium",
        )
