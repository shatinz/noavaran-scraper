import re
from typing import Optional, Tuple

PERSIAN_ARABIC_DIGITS_MAP = {
    '۰': '0', '۱': '1', '۲': '2', '۳': '3', '۴': '4',
    '۵': '5', '۶': '6', '۷': '7', '۸': '8', '۹': '9',
    '٠': '0', '١': '1', '٢': '2', '٣': '3', '٤': '4',
    '٥': '5', '٦': '6', '٧': '7', '٨': '8', '٩': '9',
}

PERSIAN_CHAR_MAP = {
    'ي': 'ی',
    'ك': 'ک',
    'ة': 'ه',
    'ؤ': 'و',
    'إ': 'ا',
    'أ': 'ا',
    'ء': '',
    '\u200c': ' ',  # Zero-width non-joiner to space for robust matching
    '\xa0': ' ',     # Non-breaking space
}

COMPANY_PREFIXES = [
    r'^شرکت\s+مهندسی\s+و\s+ساختمانی',
    r'^شرکت\s+مهندسین\s+مشاور',
    r'^مهندسین\s+مشاور',
    r'^شرکت\s+معماری',
    r'^گروه\s+معماری',
    r'^استودیو\s+معماری',
    r'^دفتر\s+معماری',
    r'^آتلیه\s+معماری',
    r'^دفتر\s+طراحی\s+و\s+اجرا',
    r'^دفتر\s+طراحی',
    r'^شرکت\s+پیمانکاری',
    r'^شرکت\s+ساختمانی',
    r'^گروه\s+ساختمانی',
    r'^گروه\s+صنعتی',
    r'^شرکت',
    r'^استودیو',
    r'^دفتر',
    r'^کارگاه',
]

HONORIFICS = [
    r'^مهندس\s+',
    r'^دکتر\s+',
    r'^آقای\s+',
    r'^خانم\s+',
    r'^مهندسان\s+',
]


def normalize_digits(text: Optional[str]) -> str:
    """Convert Persian and Arabic numerals to ASCII standard digits."""
    if not text:
        return ""
    res = []
    for ch in str(text):
        res.append(PERSIAN_ARABIC_DIGITS_MAP.get(ch, ch))
    return "".join(res)


def normalize_persian_text(text: Optional[str]) -> str:
    """Canonicalize Persian characters, unify digits, and trim spaces."""
    if not text:
        return ""
    text = normalize_digits(text)
    for k, v in PERSIAN_CHAR_MAP.items():
        text = text.replace(k, v)
    # Remove control characters and multiple spaces
    text = re.sub(r'[\r\n\t]+', ' ', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def normalize_single_phone(phone: str) -> str:
    """Normalize a single Iranian or international phone number."""
    if not phone:
        return ""
    digits = normalize_digits(phone).strip()
    has_plus = digits.startswith('+')
    clean_digits = re.sub(r'[^\d]', '', digits)

    if not clean_digits:
        return ""

    # Iranian country code handling: 0098... or 98...
    if clean_digits.startswith('0098'):
        clean_digits = clean_digits[4:]
    elif clean_digits.startswith('98') and len(clean_digits) in (12, 11):
        clean_digits = clean_digits[2:]

    # 1. 10-digit number starting with 1-9 (e.g. 9131234567 or 3131313160 or 7136280000 or 2188888888)
    # In Iran, domestic dialing prefixes this with '0' -> 11 digits
    if len(clean_digits) == 10 and clean_digits[0] in '123456789':
        return f"0{clean_digits}"

    # 2. 11-digit Iranian number starting with 0
    if len(clean_digits) == 11 and clean_digits.startswith('0'):
        return clean_digits

    # 3. 8-digit landline without area code in Isfahan context -> prepend 031
    if len(clean_digits) == 8 and clean_digits.startswith(('3', '4')):
        return f"031{clean_digits}"

    # 4. International number
    if has_plus:
        return f"+{clean_digits}"

    return clean_digits if len(clean_digits) >= 7 else ""


def normalize_phone(phone: Optional[str]) -> str:
    """
    Standardize Iranian phone numbers to standard format (09xxxxxxxxx for mobile,
    031xxxxxxxx / 021xxxxxxxx / 071xxxxxxxx for landline).
    Handles multiple semicolon/comma/slash separated numbers without concatenation corruption.
    """
    if not phone:
        return ""
    parts = re.split(r'[;\n,\|]+', str(phone))
    norm_list = []
    seen = set()
    for part in parts:
        subparts = re.split(r'\s+[\/|یا]\s+', part.strip())
        for sp in subparts:
            sp = sp.strip()
            if not sp:
                continue
            norm = normalize_single_phone(sp)
            if norm and norm not in seen:
                seen.add(norm)
                norm_list.append(norm)
    return "; ".join(norm_list)


def normalize_email(email: Optional[str]) -> str:
    """Normalize email addresses to lowercase stripped string. Handles multiple emails."""
    if not email:
        return ""
    matches = re.findall(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+', str(email))
    emails = []
    seen = set()
    for m in matches:
        clean = m.strip().lower()
        if clean and clean not in seen:
            seen.add(clean)
            emails.append(clean)
    return "; ".join(emails)


EMOJI_PATTERN = re.compile(
    r"[\U00010000-\U0010FFFF\u2600-\u26FF\u2700-\u27BF\uFE00-\uFE0F]",
    flags=re.UNICODE
)

ANNOUNCEMENT_PREFIXES = [
    r'^[#*•\-\s]+',
    r'^(?:🔺|👇|☝️|✅|💠|▫️|🔹|⚜️|⭕️|📢|📌|🎯)\s*',
    r'^(?:#News|#news|خبر|گزارش|اطلاعیه|فراخوان|همایش|ثبت\s+نام|کلاس|دوره|جلسات|نتایج|معرفی\s+پروژه)\s*[:\-–—]?\s*',
    r'^(?:تماس\s+با\s+ما|درباره\s+ما|صفحه\s+اصلی|صفحه\s+نخست|contact\s+us|about\s+us|home)\s*[:\-–—|/]\s*',
]

ANNOUNCEMENT_SUFFIXES = [
    r'\s*[:\-–—|/]\s*(?:تماس\s+با\s+ما|درباره\s+ما|صفحه\s+اصلی|صفحه\s+نخست|contact\s+us|about\s+us|home)$',
]

GENERIC_TITLES = {
    'contact us', 'about us', 'home', 'main', 'صفحه اصلی', 'درباره ما', 'تماس با ما',
    'صفحه نخست', 'وب سایت رسمی', 'وب‌سایت رسمی', 'پروژه ها', 'پروژه‌ها', 'نمونه کار',
    'متخصص معماری / ساختمان', 'متخصص معماری ساختمان'
}


def clean_entity_name(name: Optional[str]) -> str:
    """Sanitize entity names by removing emojis, hashtags, and announcement headlines."""
    if not name:
        return ""
    cleaned = EMOJI_PATTERN.sub('', str(name))
    for p in ANNOUNCEMENT_PREFIXES:
        cleaned = re.sub(p, '', cleaned, flags=re.IGNORECASE)
    for s in ANNOUNCEMENT_SUFFIXES:
        cleaned = re.sub(s, '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'[\r\n\t]+', ' ', cleaned)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    cleaned = re.sub(r'[\:\-–—\.\,]+$', '', cleaned).strip()
    return cleaned


def clean_name_for_matching(name: Optional[str]) -> str:
    """Strip honorifics and punctuation for fuzzy name comparison."""
    if not name:
        return ""
    norm = normalize_persian_text(name).lower()
    for h in HONORIFICS:
        norm = re.sub(h, '', norm, flags=re.IGNORECASE)
    # Remove punctuation
    norm = re.sub(r'[^\w\s]', '', norm)
    return re.sub(r'\s+', ' ', norm).strip()


def clean_company_for_matching(company: Optional[str]) -> str:
    """Strip organizational noise prefixes for fuzzy company comparison."""
    if not company:
        return ""
    norm = normalize_persian_text(company).lower()
    for p in COMPANY_PREFIXES:
        norm = re.sub(p, '', norm, flags=re.IGNORECASE)
    norm = re.sub(r'[^\w\s]', '', norm)
    return re.sub(r'\s+', ' ', norm).strip()


def normalize_city(city: Optional[str]) -> str:
    """Canonicalize Iranian city names."""
    if not city:
        return "Isfahan"  # Default geographic priority
    c = normalize_persian_text(city).strip()
    if any(alias in c for alias in ['اصفهان', 'esfahan', 'isfahan', 'سپاهان']):
        return "Isfahan"
    if any(alias in c for alias in ['شاهین شهر', 'shahin shahr']):
        return "Shahin Shahr"
    if any(alias in c for alias in ['نجف آباد', 'najafabad']):
        return "Najafabad"
    if any(alias in c for alias in ['تهران', 'tehran']):
        return "Tehran"
    if any(alias in c for alias in ['مشهد', 'mashhad']):
        return "Mashhad"
    if any(alias in c for alias in ['شیراز', 'shiraz']):
        return "Shiraz"
    if any(alias in c for alias in ['تبریز', 'tabriz']):
        return "Tabriz"
    return c.title() if c.isascii() else c
