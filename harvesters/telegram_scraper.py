import re
import requests
from bs4 import BeautifulSoup
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime

from normalizer import normalize_persian_text, normalize_city
from models import ContactEntity, ActiveProject
from geo_filter import classify_geography, should_admit_entity, should_admit_project
from harvesters.text_parser import (
    extract_phones,
    extract_emails,
    extract_social_handles,
    detect_entity_type,
)

DEFAULT_TELEGRAM_CHANNELS = [
    "esfahan_architects",    # گروه تخصصی معماری سازمان نظام مهندسی ساختمان استان اصفهان
    "esfarch_ac",            # آکادمی معماری اصفهان
    "memarigardi",           # رویدادها و پروژه‌های معماری
    "memari_iran",           # پروژه‌های معماری و معماران شاخص
    "civil_esfahan",         # مهندسین عمران و مجریان اصفهان
    "isfahan_civil_engineers",
    "isfahan_arch",
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "fa,en-US;q=0.9,en;q=0.8",
}


class TelegramScraper:
    def __init__(self, timeout: int = 10):
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        self.timeout = timeout

    def fetch_channel_messages(self, channel: str, before_id: Optional[int] = None) -> Tuple[List[Dict[str, Any]], Optional[int]]:
        channel = channel.strip().lstrip('@').replace('https://t.me/s/', '').replace('https://t.me/', '').split('/')[0]
        url = f"https://t.me/s/{channel}"
        if before_id:
            url += f"?before={before_id}"

        try:
            resp = self.session.get(url, timeout=self.timeout)
            if resp.status_code != 200:
                return [], None
        except Exception:
            return [], None

        soup = BeautifulSoup(resp.text, "html.parser")
        msg_divs = soup.find_all("div", class_="tgme_widget_message_wrap")

        channel_title = ""
        title_tag = soup.find("div", class_="tgme_channel_info_header_title")
        if title_tag:
            channel_title = title_tag.get_text(strip=True)

        extracted = []
        oldest_id = None

        for wrap in msg_divs:
            msg = wrap.find("div", class_="tgme_widget_message")
            if not msg:
                continue

            # Extract message ID
            data_post = msg.get("data-post", "")  # format: channel/123
            msg_id = None
            if "/" in data_post:
                try:
                    msg_id = int(data_post.split("/")[-1])
                    if oldest_id is None or msg_id < oldest_id:
                        oldest_id = msg_id
                except ValueError:
                    pass

            text_div = wrap.find("div", class_="tgme_widget_message_text")
            text = text_div.get_text(separator=" ", strip=True) if text_div else ""

            # Forwarded from
            fwd_div = wrap.find("a", class_="tgme_widget_message_forwarded_from_name")
            fwd_from = fwd_div.get_text(strip=True) if fwd_div else ""

            # Date
            time_tag = wrap.find("time")
            date_str = time_tag.get("datetime", "") if time_tag else ""

            post_url = f"https://t.me/{data_post}" if data_post else url

            extracted.append({
                "channel": channel,
                "channel_title": channel_title,
                "message_id": msg_id,
                "text": text,
                "forwarded_from": fwd_from,
                "date": date_str,
                "post_url": post_url,
            })

        return extracted, oldest_id

    def extract_entities_and_projects(self, raw_post: Dict[str, Any]) -> Tuple[List[ContactEntity], List[ActiveProject]]:
        text = raw_post.get("text", "")
        if not text or len(text.strip()) < 10:
            return [], []

        post_url = raw_post.get("post_url", "")
        date_found = datetime.now().strftime("%Y-%m-%d")
        geo_tier = classify_geography(text)
        city = "Isfahan" if geo_tier == "isfahan" else normalize_city(text)

        phones = extract_phones(text)
        emails = extract_emails(text)
        handles = extract_social_handles(text)
        channel_handle = f"@{raw_post.get('channel', '')}"
        if channel_handle not in handles:
            handles.append(channel_handle)

        contacts: List[ContactEntity] = []
        projects: List[ActiveProject] = []

        # 1. Project Detection Heuristics
        NON_PROJECT_KEYWORDS = [
            'همایش', 'کنکور', 'انتخاب رشته', 'ابلاغیه', 'دیوان عدالت', 'ثبت نام آزمون',
            'کلاس آموزشی', 'اسکیس حضوری', 'کارگاه آنلاین', 'وبینار', 'تسلیت', 'فقدان',
            'رای شعبه', 'حقوق پایمال', 'تعرفه نظارت', 'مبحث چهارم', 'پروانه اشتغال',
            'آزمون نظام', 'دوره آموزشی'
        ]
        GENUINE_PROJECT_INDICATORS = [
            'برج', 'مجتمع مسکونی', 'مجتمع تجاری', 'مرکز تجاری', 'مرکز پزشکی',
            'بیمارستان', 'ویلای', 'ساختمان مسکونی', 'پروژه اداری', 'پروژه احداث',
            'عملیات اجرای نما', 'اسکلت بتنی', 'اسکلت فلزی', 'کرتین وال', 'ترمال بریک',
            'مراحل ساخت', 'سفت کاری', 'نازک کاری', 'متراژ زیربنا', 'مساحت زیربنا'
        ]
        is_non_project = any(nk in text for nk in NON_PROJECT_KEYWORDS)
        has_project_indicator = any(pk in text for pk in GENUINE_PROJECT_INDICATORS)
        is_project_blurb = (not is_non_project) and has_project_indicator and any(k in text for k in ['پروژه', 'احداث', 'عملیات ساخت', 'مجتمع', 'برج', 'ساختمان', 'کارفرما', 'کارگاه'])

        if is_project_blurb and len(text) > 40:
            admit, _ = should_admit_project(geo_tier, text)
            if admit:
                # Extract project name from lines containing project keywords
                lines = [l.strip() for l in text.split("\n") if l.strip()]
                pname = ""
                for l in lines:
                    if any(k in l for k in ['پروژه', 'برج', 'مجتمع', 'ساختمان', 'ویلا']) and not any(nk in l for nk in NON_PROJECT_KEYWORDS):
                        pname = re.sub(r'^[#*•\-\s]+', '', l)[:70].strip()
                        break
                if not pname:
                    pname = re.sub(r'^[#*•\-\s]+', '', lines[0])[:70].strip()

                # Extract scale/scope cues
                scale_matches = re.findall(r'(\d+\s+طبقه|\d+\s+مترمربع|\d+\s+واحد|اسکلت\s+\w+|نمای\s+\w+)', text)
                scale_scope = ", ".join(scale_matches) if scale_matches else "پروژه ساختمانی"

                # Extract architects/contractors
                arch_matches = re.findall(r'(?:طراح|آرشیتکت|مهندسین مشاور|معمار)\s*:\s*([^,\n\.]+)', text)
                contractor_matches = re.findall(r'(?:مجری|پیمانکار|سازه|سازنده)\s*:\s*([^,\n\.]+)', text)

                arch_str = "; ".join([a.strip() for a in arch_matches]) if arch_matches else raw_post.get("forwarded_from", "")
                contractor_str = "; ".join([c.strip() for c in contractor_matches]) if contractor_matches else ""

                contact_info = phones[0] if phones else (handles[0] if handles else post_url)

                projects.append(ActiveProject(
                    project_name=pname,
                    city=city,
                    scale_scope=scale_scope,
                    associated_contractors=contractor_str,
                    associated_architects=arch_str,
                    contact_info=contact_info,
                    source_url=post_url,
                    confidence="high" if phones else "medium",
                    date_found=date_found,
                ))

        # 2. Contact / Lead Detection
        channel_name = raw_post.get("channel", "")
        channel_title = raw_post.get("channel_title") or raw_post.get("forwarded_from") or ""

        # Classification heuristics based on channel and content
        if "esfarch" in channel_name or any(k in text for k in ["اسکیس", "کنکور ارشد", "دانشجو", "آموزش معماری", "آکادمی"]):
            entity_type = "student"
        elif any(k in text for k in ["پیمانکار", "مجری", "اجرای نما", "نصاب", "پنجره", "کارگاه"]):
            entity_type = "contractor"
        elif any(k in text for k in ["دفتر معماری", "مهندسین مشاور", "نظام مهندسی", "طراحی", "انجمن صنفی"]):
            entity_type = "office"
        else:
            entity_type = detect_entity_type(text)

        admit_contact, reason = should_admit_entity(entity_type, geo_tier, text)
        if admit_contact:
            # Detect personal name
            person_match = re.search(r'(?:مهندس|دکتر|آرشیتکت)\s+([\u0600-\u06FF\s]{4,30})', text)
            clean_name = ""
            if person_match:
                clean_name = f"مهندس {person_match.group(1).strip()}"
                # Clean trailing punctuation
                clean_name = re.sub(r'[\r\n\t]+', ' ', clean_name).strip()

            if not clean_name:
                # Use clean channel title or organization name
                clean_name = channel_title or "دفتر معماری و مهندسی اصفهان"

            clean_comp = channel_title or clean_name

            # Create contact record if phone or handle or email exists
            if phones or emails or handles:
                primary_phone = phones[0] if phones else ""
                primary_email = emails[0] if emails else ""
                primary_handle = handles[0] if handles else f"@{channel_name}"

                contacts.append(ContactEntity(
                    entity_type=entity_type,
                    name=clean_name,
                    role="طراح / مجری معماری و ساختمان",
                    company=clean_comp,
                    city=city,
                    phone=primary_phone,
                    email=primary_email,
                    social_handle=primary_handle,
                    source_url=post_url,
                    confidence="verified" if primary_phone else "high",
                    last_verified=date_found,
                ))

        return contacts, projects
