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


TRADEMARK_PATTERN = re.compile(r'[®™©\u00ae\u2122\u00a9]')

SITE_SUFFIXES = [
    r'\s*[-–—|•/]\s*(?:Memar|memar\.io|IranArchitects|LinkedIn|Facebook|Instagram|Twitter|Pinterest|Aparat|یوتیوب|اینستاگرام|لینکدین|فیسبوک|معمار|هومانو|ایران\s*معمار).*$',
    r'\s*[-–—|/]\s*(?:Official\s+Page|Page|Group|Channel|کانال\s+رسمی|صفحه\s+رسمی)$',
]

ENGLISH_COMPANY_KEYWORDS = [
    r'\barchitects\b',
    r'\barchitecture\b',
    r'\bstudio\b',
    r'\bdesign\b',
    r'\bconsulting\b',
    r'\bconsultant\b',
    r'\bengineers\b',
    r'\bengineering\b',
    r'\bgroup\b',
    r'\boffice\b',
    r'\bcompany\b',
    r'\bco\b',
    r'\bltd\b',
    r'\binc\b',
    r'\bconstruction\b',
    r'\bcontractor\b',
]

PERSIAN_TO_LATIN_MAP = {
    'آ': 'a', 'ا': 'a', 'ب': 'b', 'پ': 'p', 'ت': 't', 'ث': 's',
    'ج': 'j', 'چ': 'ch', 'ح': 'h', 'خ': 'kh', 'د': 'd', 'ذ': 'z',
    'ر': 'r', 'ز': 'z', 'ژ': 'zh', 'س': 's', 'ش': 'sh', 'ص': 's',
    'ض': 'z', 'ط': 't', 'ظ': 'z', 'ع': 'a', 'غ': 'gh', 'ف': 'f',
    'ق': 'gh', 'ک': 'k', 'گ': 'g', 'ل': 'l', 'م': 'm', 'ن': 'n',
    'و': 'v', 'ه': 'h', 'ی': 'y', 'ئ': 'y',
}


def split_pascal_case(text: str) -> str:
    """Split CamelCase and PascalCase into space-separated words (e.g. RazanArchitects -> Razan Architects)."""
    if not text:
        return ""
    s = re.sub(r'([a-z0-9])([A-Z])', r'\1 \2', str(text))
    s = re.sub(r'([A-Z]+)([A-Z][a-z])', r'\1 \2', s)
    return s


def transliterate_persian_to_latin(text: Optional[str]) -> str:
    """Phonetic transliteration of Persian characters to Latin for cross-lingual matching."""
    if not text:
        return ""
    norm = normalize_persian_text(text).lower()
    res = []
    for ch in norm:
        if ch in PERSIAN_TO_LATIN_MAP:
            res.append(PERSIAN_TO_LATIN_MAP[ch])
        elif ch.isascii() and ch.isalnum():
            res.append(ch)
        elif ch.isspace():
            res.append(' ')
    trans = "".join(res)
    return re.sub(r'\s+', ' ', trans).strip()


def clean_entity_name(name: Optional[str]) -> str:
    """
    Sanitize entity names by removing emojis, hashtags, announcement headlines,
    trademark symbols, site suffixes, and splitting PascalCase.
    """
    if not name:
        return ""
    cleaned = str(name)
    # Strip trademark symbols
    cleaned = TRADEMARK_PATTERN.sub('', cleaned)
    # Split PascalCase in English tokens
    cleaned = split_pascal_case(cleaned)
    # Strip emojis
    cleaned = EMOJI_PATTERN.sub('', cleaned)
    for p in ANNOUNCEMENT_PREFIXES:
        cleaned = re.sub(p, '', cleaned, flags=re.IGNORECASE)
    for s in ANNOUNCEMENT_SUFFIXES:
        cleaned = re.sub(s, '', cleaned, flags=re.IGNORECASE)
    for ss in SITE_SUFFIXES:
        cleaned = re.sub(ss, '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'[\r\n\t]+', ' ', cleaned)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    cleaned = re.sub(r'[\:\-–—\.\,،؛|/]+$', '', cleaned).strip()
    cleaned = re.sub(r'^[\:\-–—\.\,،؛|/]+', '', cleaned).strip()
    return cleaned


def clean_name_for_matching(name: Optional[str]) -> str:
    """Strip honorifics, trademarks, and punctuation for fuzzy name comparison."""
    if not name:
        return ""
    cleaned = clean_entity_name(name)
    norm = normalize_persian_text(cleaned).lower()
    for h in HONORIFICS:
        norm = re.sub(h, '', norm, flags=re.IGNORECASE)
    # Remove punctuation
    norm = re.sub(r'[^\w\s]', '', norm)
    return re.sub(r'\s+', ' ', norm).strip()


def clean_company_for_matching(company: Optional[str]) -> str:
    """Strip organizational noise prefixes and English architecture keywords for fuzzy company comparison."""
    if not company:
        return ""
    cleaned = clean_entity_name(company)
    norm = normalize_persian_text(cleaned).lower()
    for p in COMPANY_PREFIXES:
        norm = re.sub(p, '', norm, flags=re.IGNORECASE)
    for ek in ENGLISH_COMPANY_KEYWORDS:
        norm = re.sub(ek, '', norm, flags=re.IGNORECASE)
    norm = re.sub(r'[^\w\s]', '', norm)
    return re.sub(r'\s+', ' ', norm).strip()


CITY_MAPPINGS = [
    # Isfahan & provincial towns (checked first)
    ("Isfahan", ['اصفهان', 'esfahan', 'isfahan', 'سپاهان']),
    ("Shahin Shahr", ['شاهین شهر', 'شاهین‌شهر', 'shahin shahr', 'shahinshahr']),
    ("Najafabad", ['نجف آباد', 'نجف‌آباد', 'najafabad', 'najaf abad']),
    ("Fooladshahr", ['فولادشهر', 'فولاد شهر', 'foladshahr', 'fooladshahr']),
    ("Baharestan", ['بهارستان', 'baharestan']),
    ("Khomeini Shahr", ['خمینی شهر', 'خمینی‌شهر', 'khomeini shahr', 'khomeinishahr']),
    ("Mobarakeh", ['مبارکه', 'mobarakeh']),
    ("Lenjan", ['لنجان', 'lenjan']),
    ("Zarrin Shahr", ['زرین شهر', 'زرین‌شهر', 'zarrin shahr']),
    ("Kashan", ['کاشان', 'kashan']),
    ("Shahreza", ['شهرضا', 'shahreza']),
    # Other Iranian major cities (multi-word / longer before single words)
    ("Kermanshah", ['کرمانشاه', 'kermanshah']),
    ("Bandar Abbas", ['بندرعباس', 'بندر عباس', 'bandar abbas']),
    ("Khorramabad", ['خرم آباد', 'خرم‌آباد', 'khorramabad']),
    ("Tehran", ['تهران', 'tehran']),
    ("Mashhad", ['مشهد', 'mashhad']),
    ("Shiraz", ['شیراز', 'shiraz']),
    ("Tabriz", ['تبریز', 'tabriz']),
    ("Karaj", ['کرج', 'karaj']),
    ("Qom", ['قم', 'qom']),
    ("Ahvaz", ['اهواز', 'ahvaz']),
    ("Urmia", ['ارومیه', 'urmia', 'orumiyeh']),
    ("Rasht", ['رشت', 'rasht']),
    ("Zahedan", ['زاهدان', 'zahedan']),
    ("Hamedan", ['همدان', 'hamedan']),
    ("Kerman", ['کرمان', 'kerman']),
    ("Yazd", ['یزد', 'yazd']),
    ("Ardabil", ['اردبیل', 'ardabil']),
    ("Arak", ['اراک', 'arak']),
    ("Zanjan", ['زنجان', 'zanjan']),
    ("Sanandaj", ['سنندج', 'sanandaj']),
    ("Qazvin", ['قزوین', 'qazvin']),
    ("Sari", ['ساری', 'sari']),
    ("Gorgan", ['گرگان', 'gorgan']),
    ("Bushehr", ['بوشهر', 'bushehr']),
    ("Kish", ['کیش', 'kish']),
    ("Qeshm", ['قشم', 'qeshm']),
    # International cities
    ("Dubai", ['دبی', 'دوبی', 'dubai', 'uae', 'emirates']),
    ("Istanbul", ['استانبول', 'istanbul', 'turkey']),
    ("Doha", ['دوحه', 'doha', 'qatar']),
    ("Muscat", ['مسقط', 'muscat', 'oman']),
]


def normalize_city(city: Optional[str]) -> str:
    """
    Canonicalize Iranian city names.
    - Case-insensitive
    - Extracts actual city name from text snippets (e.g. from "... Tehran, Iran" -> "Tehran")
    - NEVER returns a multi-word paragraph or string longer than a typical city name.
    """
    if not city:
        return "Isfahan"  # Default geographic priority
    c = normalize_persian_text(city).strip()
    if not c:
        return "Isfahan"
    c_lower = c.lower()

    for canon_name, aliases in CITY_MAPPINGS:
        for alias in aliases:
            if alias.isascii():
                if re.search(rf'\b{re.escape(alias)}\b', c_lower):
                    return canon_name
            else:
                if alias in c_lower or alias in c:
                    return canon_name

    # If no alias matched, check if input was already a clean short city name
    # e.g., <= 25 characters, <= 2 words, no sentence punctuation
    has_sentence_noise = any(ch in c for ch in ['|', '@', ':', ';', '/', '\\', '\n', '\t', 'http', '...', '"', "'", '!', '?', '،'])
    if len(c) <= 25 and len(c.split()) <= 2 and not has_sentence_noise:
        return c.title() if c.isascii() else c

    # Never return multi-word snippet/paragraph - fallback to Isfahan
    return "Isfahan"

