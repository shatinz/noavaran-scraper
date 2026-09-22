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


def normalize_phone(phone: Optional[str]) -> str:
    """
    Standardize Iranian phone numbers to standard format (09xxxxxxxxx for mobile,
    031xxxxxxxx / 021xxxxxxxx for landline).
    """
    if not phone:
        return ""
    digits = normalize_digits(phone)
    # Extract only digits and leading plus
    has_plus = digits.startswith('+')
    clean_digits = re.sub(r'[^\d]', '', digits)

    if not clean_digits:
        return ""

    # Iranian Mobile Standard: 09xxxxxxxxx (11 digits)
    # Cases: +98913..., 0098913..., 98913..., 913..., 0913...
    if clean_digits.startswith('0098'):
        clean_digits = clean_digits[4:]
    elif clean_digits.startswith('98') and len(clean_digits) in (12, 11):
        clean_digits = clean_digits[2:]

    # Now if mobile starts with 9 and has 10 digits -> prepend 0
    if len(clean_digits) == 10 and clean_digits.startswith('9'):
        return f"0{clean_digits}"

    # If mobile starts with 09 and has 11 digits -> valid mobile
    if len(clean_digits) == 11 and clean_digits.startswith('09'):
        return clean_digits

    # Landline: e.g. 031xxxxxxx (Isfahan, 11 digits)
    if clean_digits.startswith('31') and len(clean_digits) == 10:
        return f"0{clean_digits}"
    if len(clean_digits) == 11 and clean_digits.startswith('031'):
        return clean_digits

    # General 8-digit landline without area code in Isfahan context -> prepend 031
    if len(clean_digits) == 8 and clean_digits.startswith(('3', '4')):
        return f"031{clean_digits}"

    # Tehran landline: 021xxxxxxx
    if clean_digits.startswith('21') and len(clean_digits) == 10:
        return f"0{clean_digits}"
    if len(clean_digits) == 11 and clean_digits.startswith('021'):
        return clean_digits

    # If international with +
    if has_plus:
        return f"+{clean_digits}"

    # Fallback to cleaned digits if length >= 7
    return clean_digits if len(clean_digits) >= 7 else ""


def normalize_email(email: Optional[str]) -> str:
    """Normalize email addresses to lowercase stripped string."""
    if not email:
        return ""
    email = email.strip().lower()
    match = re.search(r'[\w\.-]+@[\w\.-]+\.\w+', email)
    return match.group(0) if match else ""


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
