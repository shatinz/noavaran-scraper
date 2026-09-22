import re
from typing import Tuple, Optional
from normalizer import normalize_persian_text

ISFAHAN_KEYWORDS = [
    'اصفهان', 'esfahan', 'isfahan', 'سپاهان', 'شاهین شهر', 'shahin shahr',
    'نجف آباد', 'najafabad', 'فولادشهر', 'foladshahr', 'بهارستان', 'baharestan',
    'خمینی شهر', 'khomeini shahr', 'مبارکه', 'mobarakeh', 'لنجان', 'lenjan',
    'زرین شهر', 'zarrin shahr', 'کاشان', 'kashan', 'شهرضا', 'shahreza',
]

IRANIAN_MAJOR_CITIES = [
    'تهران', 'tehran', 'مشهد', 'mashhad', 'شیراز', 'shiraz', 'تبریز', 'tabriz',
    'کرج', 'karaj', 'قم', 'qom', 'اهواز', 'ahvaz', 'کرمانشاه', 'kermanshah',
    'ارومیه', 'urmia', 'رشت', 'rasht', 'زاهدان', 'zahedan', 'همدان', 'hamedan',
    'کرمان', 'kerman', 'یزد', 'yazd', 'اردبیل', 'ardabil', 'بندرعباس', 'bandar abbas',
    'اراک', 'arak', 'زنجان', 'zanjan', 'سنندج', 'sanandaj', 'قزوین', 'qazvin',
    'خرم آباد', 'khorramabad', 'ساری', 'sari', 'گرگان', 'gorgan', 'بوشهر', 'bushehr',
    'کیش', 'kish', 'قشم', 'qeshm',
]

LARGE_SCALE_PROJECT_KEYWORDS = [
    r'برج',
    r'بیمارستان',
    r'مرکز\s+تجاری',
    r'مجتمع\s+تجاری',
    r'مال',
    r'مگامال',
    r'هتل\s+\d+\s+ستاره',
    r'هتل',
    r'مجتمع\s+مسکونی\s+بزرگ',
    r'شهرک\s+مسکونی',
    r'پروژه\s+ملی',
    r'ورزشگاه',
    r'فرودگاه',
    r'پایانه',
    r'ایستگاه\s+مترو',
    r'دهانه\s+بزرگ',
    r'اسپیس\s+فریم',
    r'سازه\s+فضاکار',
    r'نمای\s+کرتین\s+وال',
    r'اسکای\s+لایت',
    r'فریم\s+لس',
    r'ترمال\s+بریک',
    r'(?:[۷-۹]|[1-9]\d+)\s+طبقه',         # >= 7 floors
    r'(?:[3-9]\d{3}|\d{5,})\s+متر',       # >= 3000 square meters
]

TOP_TIER_STUDENT_UNIVERSITIES = [
    'دانشگاه تهران', 'دانشگاه هنر تهران', 'هنرهای زیبا', 'شهید بهشتی', 'علم و صنعت',
    'تربیت مدرس', 'امیرکبیر', 'شریف', 'tehran university', 'shahid beheshti',
    'iust', 'tarbiat modares', 'amirkabir', 'sharif', 'هنر تهران',
]

TOP_TIER_STUDENT_AWARDS = [
    'جایزه معمار', 'میرمیران', 'طرح برتر', 'رتبه اول', 'رتبه دوم', 'رتبه سوم',
    'برنده مسابقه', 'مسابقه معماری', 'بینال معماری', 'فینالیست', 'archdaily',
    'dezeen', '2a award', 'memar award', 'mirmiran', 'civilica', 'magiran',
    'انجمن علمی معماری', 'دبیر انجمن',
]

INTERNATIONAL_INDICATORS = [
    'dubai', 'uae', 'emirates', 'doha', 'qatar', 'muscat', 'oman',
    'istanbul', 'turkey', 'frankfurt', 'berlin', 'germany', 'milan',
    'italy', 'london', 'uk', 'دبی', 'امارات', 'عمان', 'قطر', 'ترکیه',
]


def classify_geography(text: str, city_field: Optional[str] = None) -> str:
    """
    Classify geographic scope into: 'isfahan', 'other_iran', 'international', or 'unknown'.
    """
    combined = f"{city_field or ''} {text or ''}".lower()
    combined_norm = normalize_persian_text(combined)

    # 1. Isfahan check
    for kw in ISFAHAN_KEYWORDS:
        if re.search(rf'\b{re.escape(kw)}\b', combined_norm):
            return "isfahan"

    # 2. International check
    for kw in INTERNATIONAL_INDICATORS:
        if re.search(rf'\b{re.escape(kw)}\b', combined_norm):
            return "international"

    # 3. Other Iranian major cities
    for kw in IRANIAN_MAJOR_CITIES:
        if re.search(rf'\b{re.escape(kw)}\b', combined_norm):
            return "other_iran"

    # Default to Isfahan if no explicit city indicator in Iran context
    return "isfahan"


def is_large_scale_project(text: str) -> bool:
    """Check whether a project meets the criteria for large-scale/big-span."""
    text_norm = normalize_persian_text(text)
    for pattern in LARGE_SCALE_PROJECT_KEYWORDS:
        if re.search(pattern, text_norm, re.IGNORECASE):
            return True
    return False


def is_top_tier_student(text: str) -> Tuple[bool, str]:
    """
    Evaluate student qualifications against concrete top-tier criteria:
    - University of Tehran, Beheshti, IUST, Tarbiat Modares, etc.
    - Competition awards (Memar Award, Mirmiran, 2A, etc.)
    - Peer-reviewed publications / scientific association leadership
    """
    text_norm = normalize_persian_text(text).lower()

    matched_unis = [u for u in TOP_TIER_STUDENT_UNIVERSITIES if u in text_norm]
    matched_awards = [a for a in TOP_TIER_STUDENT_AWARDS if a in text_norm]

    if matched_unis and matched_awards:
        return True, f"Top university ({matched_unis[0]}) & Award/Recognition ({matched_awards[0]})"
    elif matched_awards:
        return True, f"Competition/Award winner ({matched_awards[0]})"
    elif matched_unis:
        return True, f"Top tier architectural university ({matched_unis[0]})"

    return False, "Does not meet top-tier threshold"


def should_admit_entity(entity_type: str, geo_tier: str, context_text: str) -> Tuple[bool, str]:
    """
    Geographic admission filter:
    - Isfahan: admit all categories with no filtering.
    - Other Iranian cities:
      - office / contractor: admit all.
      - student: admit only if top-tier.
      - individual: admit if high intent.
    - International: admit only if high-probability target (offices / facade engineering).
    """
    if geo_tier == "isfahan":
        return True, "Isfahan exhaustive sweep (no filtering)"

    if geo_tier == "other_iran":
        if entity_type in ("office", "contractor"):
            return True, f"Admitted Iranian {entity_type}"
        elif entity_type == "student":
            is_top, reason = is_top_tier_student(context_text)
            if is_top:
                return True, f"Admitted top-tier student: {reason}"
            return False, f"Rejected non-Isfahan student: {reason}"
        else:
            return True, "Admitted Iranian individual"

    if geo_tier == "international":
        if entity_type in ("office", "contractor"):
            return True, "Admitted opportunistic international architecture/contracting firm"
        return False, "International non-firm excluded from v1 sweep"

    return True, "Default admission"


def should_admit_project(geo_tier: str, project_text: str) -> Tuple[bool, str]:
    """
    Geographic project filter:
    - Isfahan: admit all projects.
    - Other Iranian cities: admit ONLY if large-scale/big-span.
    - International: admit only if landmark/facade-relevant.
    """
    if geo_tier == "isfahan":
        return True, "Isfahan project (exhaustive)"

    if geo_tier in ("other_iran", "international"):
        if is_large_scale_project(project_text):
            return True, f"Large-scale / big-span project confirmed in {geo_tier}"
        return False, f"Excluded small/medium project outside Isfahan"

    return True, "Admitted project"
