import re
from typing import Dict, Any, List, Optional
from normalizer import (
    normalize_persian_text,
    normalize_phone,
    normalize_email,
    normalize_digits,
)

PHONE_REGEX = re.compile(
    r'(?:(?:\+?98|0098|0)?(?:9[\d\s\-]{9,13}|31[\d\s\-]{8,12}|21[\d\s\-]{8,12}))'
)
EMAIL_REGEX = re.compile(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+')
HANDLE_REGEX = re.compile(r'(?:^|\s)@([a-zA-Z0-9_]{3,30})')
URL_REGEX = re.compile(r'https?://[^\s<>"\')]+')

PROJECT_KEYWORDS = [
    'پروژه', 'احداث', 'عملیات ساخت', 'مجتمع مسکونی', 'مجتمع تجاری',
    'برج', 'ویلا', 'کارفرما', 'دستور نقشه', 'پروانه ساخت', 'اجرای نما',
    'سفت کاری', 'نازک کاری', 'اسکلت بتنی', 'اسکلت فلزی', 'کرتین وال'
]

ROLE_KEYWORDS = {
    'office': ['دفتر معماری', 'مهندسین مشاور', 'استودیو معماری', 'آتلیه معماری', 'شرکت معماری', 'طراحی نما'],
    'contractor': ['پیمانکار', 'مجری ذیصلاح', 'اجرای ساختمان', 'پیمانکاری', 'سازه', 'نصاب نما', 'پیمانکار نما'],
    'student': ['دانشجو', 'دانشجوی معماری', 'دانشجوی کارشناسی', 'دانشجوی ارشد', 'دانشکده معماری', 'انجمن علمی معماری'],
}


def extract_phones(text: str) -> List[str]:
    """Extract and normalize all Iranian phone numbers from raw text."""
    if not text:
        return []
    clean_text = normalize_digits(text)
    candidates = PHONE_REGEX.findall(clean_text)
    results = []
    seen = set()
    for c in candidates:
        norm = normalize_phone(c)
        if norm and len(norm) in (11, 12, 13) and norm not in seen:
            seen.add(norm)
            results.append(norm)
    return results


def extract_emails(text: str) -> List[str]:
    """Extract and normalize all email addresses from raw text."""
    if not text:
        return []
    matches = EMAIL_REGEX.findall(text)
    results = []
    seen = set()
    for m in matches:
        clean = normalize_email(m)
        if clean and clean not in seen:
            seen.add(clean)
            results.append(clean)
    return results


def extract_social_handles(text: str) -> List[str]:
    """Extract @handles from raw text."""
    if not text:
        return []
    matches = HANDLE_REGEX.findall(text)
    results = []
    seen = set()
    for m in matches:
        handle = f"@{m.strip()}"
        if handle not in seen:
            seen.add(handle)
            results.append(handle)
    return results


def detect_entity_type(text: str) -> str:
    """Classify text into office, contractor, student, or individual."""
    norm = normalize_persian_text(text).lower()
    for cat, keywords in ROLE_KEYWORDS.items():
        for kw in keywords:
            if kw in norm:
                return cat
    return "individual"
