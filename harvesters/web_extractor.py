import os
import re
import requests
from bs4 import BeautifulSoup
from typing import List, Dict, Any, Optional, Tuple
from urllib.parse import urljoin, urlparse

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

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

GENERIC_PAGE_TITLES = {
    'contact us', 'about us', 'home', 'main', 'صفحه اصلی', 'درباره ما', 'تماس با ما',
    'صفحه نخست', 'وب سایت رسمی', 'وب‌سایت رسمی', 'پروژه ها', 'پروژه‌ها', 'نمونه کار'
}


class TargetedWebExtractor:
    def __init__(self, timeout: int = 10):
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        self.timeout = timeout
        proxy_url = os.environ.get("HTTP_PROXY") or "http://127.0.0.1:10808"
        try:
            r = requests.get(proxy_url, timeout=0.5)
            self.session.proxies.update({"http": proxy_url, "https": proxy_url})
        except Exception:
            pass

    def fetch_and_prune(self, url: str) -> Optional[str]:
        """Fetch web page and strip scripts, styles, and navigational chrome."""
        try:
            resp = self.session.get(url, timeout=self.timeout)
            if resp.status_code != 200 or "text/html" not in resp.headers.get("Content-Type", ""):
                return None
            soup = BeautifulSoup(resp.text, "html.parser")
            for tag in soup(["script", "style", "nav", "footer", "svg", "noscript", "iframe"]):
                tag.decompose()
            return soup.get_text(separator=" ", strip=True)
        except Exception:
            return None

    def extract_from_website(self, base_url: str) -> Tuple[List[ContactEntity], List[ActiveProject], List[str]]:
        """
        Deep extract contacts and projects from a target office or contractor website.
        Discovers internal links to /contact, /about, /projects.
        """
        contacts: List[ContactEntity] = []
        projects: List[ActiveProject] = []
        discovered_urls: List[str] = []

        text = self.fetch_and_prune(base_url)
        if not text:
            return [], [], []

        geo_tier = classify_geography(text)
        city = "Isfahan" if geo_tier == "isfahan" else normalize_city(text)

        phones = extract_phones(text)
        emails = extract_emails(text)
        handles = extract_social_handles(text)

        domain = urlparse(base_url).netloc
        comp_name = domain.replace("www.", "").split(".")[0].title()

        try:
            r = self.session.get(base_url, timeout=self.timeout)
            s = BeautifulSoup(r.text, "html.parser")
            t_tag = s.find("title")
            if t_tag:
                title_clean = clean_entity_name(t_tag.get_text(strip=True))
                title_parts = [p.strip() for p in re.split(r'[-–|]', title_clean) if p.strip()]
                valid_parts = [p for p in title_parts if p.lower() not in GENERIC_PAGE_TITLES]
                if valid_parts:
                    comp_name = valid_parts[0]

            for a in s.find_all("a", href=True):
                href = a["href"].lower()
                if any(k in href for k in ["contact", "about", "project", "portfolio", "تماس", "درباره", "پروژه"]):
                    full_link = urljoin(base_url, a["href"])
                    if full_link not in discovered_urls and urlparse(full_link).netloc == domain:
                        discovered_urls.append(full_link)
        except Exception:
            pass

        entity_type = detect_entity_type(text)
        admit_contact, _ = should_admit_entity(entity_type, geo_tier, text)

        if admit_contact and (phones or emails or handles):
            contacts.append(ContactEntity(
                entity_type=entity_type,
                name=comp_name,
                role="مدیرعامل / دفتر معماری و مهندسی",
                company=comp_name,
                city=city,
                phone="; ".join(phones),
                email="; ".join(emails),
                social_handle="; ".join(handles),
                source_url=base_url,
                confidence="verified" if phones else "high",
            ))

        return contacts, projects, discovered_urls
