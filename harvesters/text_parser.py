import re
from typing import Dict, Any, List, Optional
from normalizer import (
    normalize_persian_text,
    normalize_phone,
    normalize_email,
    normalize_digits,
)

PHONE_REGEX = re.compile(
    r'(?:'
    r'(?:\+?98|0098|0)?[\s\.\-]*(?:\(?[1-9]\d{1,2}\)?|\(?9\d{2}\)?)[\s\.\-\/]*\d{3,4}[\s\.\-\/]*\d{3,4}'
    r'|'
    r'(?:(?:\+?98|0098|0)?(?:9[\d\s\-\.\/\(\)]{8,15}|[1-8]\d[\d\s\-\.\/\(\)]{7,14}))'
    r')'
)
EMAIL_REGEX = re.compile(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+')
HANDLE_REGEX = re.compile(r'(?:^|\s)@([a-zA-Z0-9_]{3,30})')
URL_REGEX = re.compile(r'https?://[^\s<>"\')]+')

ARCHITECT_PATTERNS = [
    r'(?:طراح(?:ی)?\s+معماری|طراح\s+پروژه|آرشیتکت|مهندسین\s+مشاور|معمار\s+پروژه|دفتر\s+معماری|گروه\s+معماری)\s*[:\-–—]\s*([^,\n\.\;\|]+)',
    r'(?:^|[\n\.؛])\s*(?:طراح|معمار|آرشیتکت)\s*[:\-–—]\s*([^,\n\.\;\|]+)',
    r'توسط\s+(مهندسین\s+مشاور\s+[^,\n\.\;\|]+)',
    r'توسط\s+(گروه\s+معماری\s+[^,\n\.\;\|]+)',
    r'توسط\s+(استودیو\s+معماری\s+[^,\n\.\;\|]+)',
    r'توسط\s+(دفتر\s+معماری\s+[^,\n\.\;\|]+)',
    r'توسط\s+(مهندس\s+[\u0600-\u06FF\s]{4,30})',
]

CONTRACTOR_PATTERNS = [
    r'(?:مجری\s+پروژه|پیمانکار\s+پروژه|پیمانکار\s+اصلی|مجری\s+ذیصلاح|کارفرما\s+و\s+مجری|اجرای\s+سازه|اجرای\s+نما)\s*[:\-–—]\s*([^,\n\.\;\|]+)',
    r'(?:^|[\n\.؛])\s*(?:مجری|پیمانکار|سازنده)\s*[:\-–—]\s*([^,\n\.\;\|]+)',
    r'توسط\s+(شرکت\s+ساختمانی\s+[^,\n\.\;\|]+)',
    r'توسط\s+(گروه\s+ساختمانی\s+[^,\n\.\;\|]+)',
    r'توسط\s+(شرکت\s+پیمانکاری\s+[^,\n\.\;\|]+)',
    r'از\s+(هلدینگ\s+ساختمانی\s+[^,\n\.\;\|]+)',
    r'از\s+(شرکت\s+ساختمانی\s+[^,\n\.\;\|]+)',
]

SUBSTRING_NON_ENTITIES = [
    'صحت اطلاعات',
    'بسیاری از مراکز خرید',
    'مراکز خرید',
    'مراکز تجاری',
    'انجام مطالعات',
    'مطالعات گسترده',
    'مورد بررسی',
    'قرار گرفت',
    'تضمین شده',
    'اطلاعات تماس',
    'در حال ساخت',
    'اطلاعات ساختمان',
    'پروژه ساختمانی',
    'مشاهده پروژه',
    'ثبت نام',
    'اطلاعات بیشتر',
    'ارائه می گردد',
    'می باشد',
    'می شود',
    'پروژه های دیگر',
    'پروژه ها',
]

EXACT_NON_ENTITIES = {
    'اجرا',
    'طراحی',
    'معماری',
    'ساختمان',
    'نظارت',
    'طراحی و اجرا',
    'اجرای نما',
    'اجرای سازه',
    'پیمانکار',
    'مجری',
    'سازنده',
    'طراح',
}


def clean_party_candidate(cand: str) -> Optional[str]:
    """Clean and validate an extracted architect or contractor candidate string."""
    if not cand:
        return None
    # 1. Stop at common prepositions/conjunctions
    cand = re.split(r'\s+(?:و|با|در|برای|به|از|بر|ضمن|جهت)\s+', cand.strip())[0].strip()
    # 2. Strip leading/trailing punctuation & symbols
    cand = re.sub(r'^[\s\:\-–—\.\,،؛\(\)\[\]"\'«»]+', '', cand).strip()
    cand = re.sub(r'[\s\:\-–—\.\,،؛\(\)\[\]"\'«»]+$', '', cand).strip()
    # 3. Strip trademark symbols
    cand = re.sub(r'[®™©\u00ae\u2122\u00a9]', '', cand).strip()

    # 4. Filter out short or single-word fragments like '، اجرا' or 'اجرا' or 'طراحی'
    words = cand.split()
    if len(words) < 2 and cand not in ('کیسون', 'مپنا', 'استراتوس'):
        return None
    if len(words) > 5 or len(cand) > 40 or len(cand) < 3:
        return None

    # 5. Check against non-entity phrases
    cand_norm = normalize_persian_text(cand).lower()
    if cand_norm in EXACT_NON_ENTITIES:
        return None
    for ne in SUBSTRING_NON_ENTITIES:
        if ne in cand_norm:
            return None

    # 6. Filter narrative verb phrases
    VERB_ENDINGS = ['است', 'شد', 'گردید', 'دارد', 'گرفت', 'شود', 'باشد']
    if any(cand.endswith(f" {v}") for v in VERB_ENDINGS):
        return None

    return cand


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
        for sub_n in norm.split('; '):
            sub_n = sub_n.strip()
            if sub_n and len(sub_n) in (11, 12, 13) and sub_n not in seen:
                seen.add(sub_n)
                results.append(sub_n)
    return results


def extract_architects(text: str) -> List[str]:
    """Extract associated architects and design offices from text."""
    if not text:
        return []
    results = []
    seen = set()
    for pat in ARCHITECT_PATTERNS:
        for m in re.findall(pat, text):
            cand = clean_party_candidate(m)
            if cand and cand not in seen and not any(k in cand for k in ['پروژه', 'احداث', 'مترمربع']):
                seen.add(cand)
                results.append(cand)
    return results


def extract_contractors(text: str) -> List[str]:
    """Extract associated contractors and builders from text."""
    if not text:
        return []
    results = []
    seen = set()
    for pat in CONTRACTOR_PATTERNS:
        for m in re.findall(pat, text):
            cand = clean_party_candidate(m)
            if cand and cand not in seen and not any(k in cand for k in ['پروژه', 'احداث', 'مترمربع']):
                seen.add(cand)
                results.append(cand)
    return results

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
