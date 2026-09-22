import os
import tempfile
import pytest

from normalizer import (
    normalize_city,
    normalize_phone,
    clean_entity_name,
    clean_person_name,
    clean_company_for_matching,
    transliterate_persian_to_latin,
)
from models import ContactEntity
from database import init_db, get_all_contacts
from dedup import DeduplicationEngine, choose_best_name
from harvesters.search_engine import SearchHarvester
from harvesters.text_parser import extract_architects, extract_contractors
from geo_filter import classify_geography


@pytest.fixture
def test_db():
    temp_dir = tempfile.mkdtemp()
    db_path = os.path.join(temp_dir, "test_fixes.db")
    init_db(db_path)
    yield db_path
    if os.path.exists(db_path):
        os.remove(db_path)


def test_normalize_city_snippets():
    """Verify normalize_city extracts city from snippets, handles case-insensitivity, and never returns paragraphs."""
    ig_bio = (
        'RazanArchitects | دفتر معماری رازان (@razanarchitects ... 18K Followers, 1 Following, '
        '154 Posts - RazanArchitects | دفتر معماری رازان (@razanarchitects) on Instagram: '
        '""Design & Build Office Since 2001 Founder:@navid_emami_s Tehran, Iran""'
    )
    assert normalize_city(ig_bio) == "Tehran"

    fb_snippet = (
        "Razan Architects | Tehran - Facebook Sep 14, 2020 · Razan Architects, Tehran. "
        "40 likes. Razan Text & Context | Design and construction studio www.RazanArchitects.com"
    )
    assert normalize_city(fb_snippet) == "Tehran"

    # Case insensitivity
    assert normalize_city("tehran") == "Tehran"
    assert normalize_city("TEHRAN") == "Tehran"
    assert normalize_city("isfahan") == "Isfahan"
    assert normalize_city("ISFAHAN") == "Isfahan"
    assert normalize_city("shiraz") == "Shiraz"

    # Paragraph with no city indicator must NEVER return the multi-word paragraph
    long_noisy_text = "شرکت طراحی و دکوراسیون داخلی با بهترین متریال و گارانتی ۵ ساله و کادر مجرب اجرایی"
    city = normalize_city(long_noisy_text)
    assert city == "Isfahan"
    assert len(city) <= 25
    assert len(city.split()) <= 2


def test_linkedin_company_classification_and_trademarks():
    """Verify LinkedIn /company/ URLs are classified as office/contractor, and trademark symbols are stripped."""
    sh = SearchHarvester()

    # 1. IRISA
    irisa_item = {
        "title": "IRISA | LinkedIn",
        "body": "شرکت بین المللی مهندسی سیستم ها و اتوماسیون ایریسا در اصفهان",
        "href": "https://ir.linkedin.com/company/irisa",
    }
    c_irisa = sh.parse_linkedin_snippet(irisa_item)
    assert c_irisa is not None
    assert c_irisa.entity_type in ("office", "contractor")
    assert c_irisa.entity_type != "individual"
    assert "IRISA" in c_irisa.name

    # 2. Palaz Group® - must strip ®
    palaz_item = {
        "title": "Palaz Group® | LinkedIn",
        "body": "تولید و اجرای پوشش های کف و طراحی ساختمانی در اصفهان",
        "href": "https://www.linkedin.com/company/palaz®",
    }
    c_palaz = sh.parse_linkedin_snippet(palaz_item)
    assert c_palaz is not None
    assert c_palaz.entity_type in ("office", "contractor")
    assert c_palaz.entity_type != "individual"
    assert "®" not in c_palaz.name
    assert "®" not in c_palaz.company
    assert c_palaz.name == "Palaz Group"

    # 3. IMPASCO
    impasco_item = {
        "title": "IMPASCO | LinkedIn",
        "body": "شرکت تهیه و تولید مواد معدنی و پروژه های عمرانی",
        "href": "https://www.linkedin.com/company/impasco",
    }
    c_impasco = sh.parse_linkedin_snippet(impasco_item)
    assert c_impasco is not None
    assert c_impasco.entity_type in ("office", "contractor")
    assert c_impasco.entity_type != "individual"

    # Name cleaning standalone check
    assert clean_entity_name("Palaz Group®") == "Palaz Group"
    assert clean_entity_name("AwesomeArch™") == "Awesome Arch"


def test_project_exclusions_and_non_entity_filtering():
    """Verify commercial marketplace project listings are excluded, and non-entity phrases are filtered."""
    sh = SearchHarvester()

    # Commercial lead database /product/ URL
    artaparsian_item = {
        "title": "اطلاعات ساختمان های در حال ساخت اصفهان | آرتا پارسیان",
        "body": "خرید و دانلود پکیج شماره تماس سازندگان و اطلاعات ساختمان های در حال ساخت اصفهان. صحت اطلاعات تضمین شده است.",
        "href": "https://artaparsian.com/product/اصلاعات-ساختمان-های-در-حال-ساخت-اصفهان/",
    }
    proj = sh.parse_web_project_snippet(artaparsian_item)
    assert proj is None

    # Hallucinated contractor / architect filtering
    noisy_snippet = (
        "پروژه مرکز خرید مهستان نقش جهان. "
        "در طراحی معماری مرکز خرید مهستان ضمن انجام مطالعات گسترده بر روی میراث معماری ایران، "
        "بسیاری از مراکز خرید معروف دنیا نیز مورد بررسی قرار گرفت؛ ، اجرا. "
        "کارفرما و مجری: صحت اطلاعات. "
        "طراح معماری: مهندسین مشاور نقش جهان. "
        "پیمانکار: شرکت ساختمانی کیسون."
    )
    archs = extract_architects(noisy_snippet)
    conts = extract_contractors(noisy_snippet)

    # Must NOT contain hallucinations
    assert not any("صحت اطلاعات" in c for c in conts)
    assert not any("صحت اطلاعات" in a for a in archs)
    assert not any("بسیاری از مراکز خرید" in a for a in archs)
    assert not any("بسیاری از مراکز خرید" in c for c in conts)
    assert not any(c == "اجرا" or c == "، اجرا" for c in conts)
    assert not any(a == "اجرا" or a == "، اجرا" for a in archs)

    # Must extract real entities
    assert any("نقش جهان" in a for a in archs)
    assert any("کیسون" in c for c in conts)


def test_cross_lingual_dedup_razan(test_db):
    """Verify RazanArchitects, Razan Architects, and دفتر معماری رازان — Memar are merged into one entity."""
    engine = DeduplicationEngine(db_path=test_db)

    # 1. Instagram record
    c_ig = ContactEntity(
        entity_type="office",
        name="RazanArchitects",
        role="دفتر معماری / پیمانکار اجرایی",
        company="RazanArchitects",
        city="Tehran",
        social_handle="@razanarchitects",
        source_url="https://www.instagram.com/razanarchitects/",
        confidence="high",
    )
    id1, action1 = engine.process_contact(c_ig, run_id="r1", source_type="instagram")
    assert action1 == "created_new"

    # 2. Iranian Architecture directory record
    c_memar = ContactEntity(
        entity_type="office",
        name="دفتر معماری رازان — Memar",
        role="دفتر معماری / پیمانکار اجرایی",
        company="دفتر معماری رازان — Memar",
        city="Isfahan",
        source_url="https://iranarchitects.com/architecturaloffice/115/razanarchitects; https://www.memar.io/fa/firms/razan-architecture-office",
        confidence="high",
    )
    id2, action2 = engine.process_contact(c_memar, run_id="r2", source_type="web")
    assert action2 in ("merged_fuzzy", "merged_exact")
    assert id2 == id1

    # 3. Facebook record
    c_fb = ContactEntity(
        entity_type="individual",
        name="Razan Architects",
        role="دفتر معماری / پیمانکار اجرایی",
        company="Razan Architects",
        city="Tehran",
        source_url="https://www.facebook.com/razantextandcontext/",
        confidence="high",
    )
    id3, action3 = engine.process_contact(c_fb, run_id="r3", source_type="web")
    assert action3 in ("merged_fuzzy", "merged_exact")
    assert id3 == id1

    # Final DB verification
    contacts = get_all_contacts(test_db)
    assert len(contacts) == 1
    merged = contacts[0]

    # Check properties
    assert merged.entity_type == "office"
    assert merged.city == "Tehran"
    assert "https://www.instagram.com/razanarchitects/" in merged.source_url
    assert "https://iranarchitects.com/architecturaloffice/115/razanarchitects" in merged.source_url
    assert "https://www.facebook.com/razantextandcontext/" in merged.source_url
    assert "@razanarchitects" in merged.social_handle


def test_no_false_channel_slug_merge(test_db):
    """Verify different entities posted in the same Telegram channel are NOT falsely merged."""
    engine = DeduplicationEngine(db_path=test_db)

    c1 = ContactEntity(
        entity_type="office",
        name="مهندس رضا رضایی",
        role="طراح معماری",
        company="مهندسین مشاور رضایی",
        city="Isfahan",
        source_url="https://t.me/s/esfahan_architects/100",
    )
    id1, action1 = engine.process_contact(c1, run_id="r1", source_type="telegram")
    assert action1 == "created_new"

    c2 = ContactEntity(
        entity_type="office",
        name="مهندس حسن حسنی",
        role="طراح سازه",
        company="شرکت ساختمانی حسنی",
        city="Isfahan",
        source_url="https://t.me/s/esfahan_architects/200",
    )
    id2, action2 = engine.process_contact(c2, run_id="r2", source_type="telegram")
    assert action2 == "created_new"
    assert id1 != id2

    contacts = get_all_contacts(test_db)
    assert len(contacts) == 2


def test_nisba_city_names_not_misclassified():
    """Verify surnames ending with nisba suffixes (e.g. Yazdani, Kashani) do not trigger false city classification."""
    assert normalize_city("مهندس علی یزدانی مدیر پروژه") == "Isfahan"
    assert normalize_city("مهندس حسین کاشانی طراح نما") == "Isfahan"
    assert normalize_city("استودیو تهرانی و شرکا") == "Isfahan"

    # Actual city mention MUST still work
    assert normalize_city("دفتر معماری در یزد خیابان کاشانی") == "Yazd"
    assert normalize_city("پروژه ساختمانی در کاشان") == "Kashan"

    # Geographic classification check
    assert classify_geography("مهندس علی یزدانی - طراح معماری") == "isfahan"
    assert classify_geography("دفتر معماری در شهر یزد") == "other_iran"


def test_corporate_registration_id_rejected_as_phone():
    """Verify 11-digit company national IDs starting with 140... are rejected and not treated as phones."""
    assert normalize_phone("14050628125") == ""
    assert normalize_phone("14050611072") == ""
    # Combined with real phone: only real phone is preserved
    assert normalize_phone("14050628125; 03130003220") == "03130003220"


def test_choose_best_name_never_chooses_generic_placeholder():
    """Verify choose_best_name rejects generic placeholder titles in favor of actual entity names."""
    assert choose_best_name("Palaz Group", "متخصص معماری / ساختمان") == "Palaz Group"
    assert choose_best_name("متخصص معماری / ساختمان", "IRISA") == "IRISA"
    assert choose_best_name("دفتر معماری رازان", "Razan Architects") == "دفتر معماری رازان"


def test_clean_person_name_strips_trailing_clauses():
    """Verify clean_person_name cuts off trailing conjunctions, prepositions, and narrative phrases."""
    assert clean_person_name("مهندس دزفولی و استاد سرتیپی اساتید آ") == "مهندس دزفولی"
    assert clean_person_name("مهندس بهزاد نوید نیا را به ایشان و خ") == "مهندس بهزاد نوید نیا"
    assert clean_person_name("مهندس علی محجوب رئیس و اعضای هیئت رئ") == "مهندس علی محجوب"

