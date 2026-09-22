import os
import tempfile
import pytest
from normalizer import (
    normalize_persian_text,
    normalize_phone,
    normalize_email,
    clean_name_for_matching,
    clean_company_for_matching,
)
from models import ContactEntity, ActiveProject
from database import init_db, get_all_contacts, get_all_projects, get_connection
from dedup import DeduplicationEngine, merge_source_urls


@pytest.fixture
def test_db():
    temp_dir = tempfile.mkdtemp()
    db_path = os.path.join(temp_dir, "test_cache.db")
    init_db(db_path)
    yield db_path
    if os.path.exists(db_path):
        os.remove(db_path)


def test_normalizer_persian_and_phone():
    assert normalize_phone("+989131234567") == "09131234567"
    assert normalize_phone("00989131234567") == "09131234567"
    assert normalize_phone("۰۹۱۳۱۲۳۴۵۶۷") == "09131234567"
    assert normalize_phone("031-31313160") == "03131313160"
    assert normalize_phone("۳۱۳۱۳۱۶۰") == "03131313160"

    persian_text = "شركت مهندسين مشاور آروين پنجره"
    cleaned_comp = clean_company_for_matching(persian_text)
    assert "آروین پنجره" in cleaned_comp

    persian_name = "مهندس عليرضا محمدي"
    cleaned_name = clean_name_for_matching(persian_name)
    assert cleaned_name == "علیرضا محمدی"


def test_merge_source_urls():
    u1 = "https://instagram.com/arch1; https://t.me/arch1"
    u2 = "https://t.me/arch1; https://linkedin.com/in/arch1"
    merged = merge_source_urls(u1, u2)
    urls = [u.strip() for u in merged.split(";")]
    assert len(urls) == 3
    assert "https://instagram.com/arch1" in urls
    assert "https://t.me/arch1" in urls
    assert "https://linkedin.com/in/arch1" in urls


def test_exact_phone_dedup(test_db):
    engine = DeduplicationEngine(db_path=test_db)
    
    # First contact from Telegram
    c1 = ContactEntity(
        entity_type="office",
        name="مهندس علیرضا رضایی",
        role="مدیرعامل",
        company="گروه معماری پادیاو",
        city="اصفهان",
        phone="09131112233",
        email="",
        social_handle="@padiav_arch",
        source_url="https://t.me/s/padiav_arch",
        confidence="medium"
    )
    id1, action1 = engine.process_contact(c1, run_id="run-1", source_type="telegram")
    assert action1 == "created_new"

    # Second contact from Instagram with same phone but additional email & instagram link
    c2 = ContactEntity(
        entity_type="office",
        name="علیرضا رضایی",
        role="معمار ارشد",
        company="استودیو پادیاو",
        city="اصفهان",
        phone="+989131112233",
        email="info@padiav.ir",
        social_handle="@padiav_studio",
        source_url="https://instagram.com/padiav_studio",
        confidence="high"
    )
    id2, action2 = engine.process_contact(c2, run_id="run-2", source_type="instagram")
    assert action2 == "merged_phone"
    assert id1 == id2

    contacts = get_all_contacts(test_db)
    assert len(contacts) == 1
    merged = contacts[0]
    assert merged.phone == "09131112233"
    assert merged.email == "info@padiav.ir"
    assert "https://t.me/s/padiav_arch" in merged.source_url
    assert "https://instagram.com/padiav_studio" in merged.source_url
    assert merged.confidence == "verified"


def test_exact_email_dedup(test_db):
    engine = DeduplicationEngine(db_path=test_db)

    c1 = ContactEntity(
        entity_type="office",
        name="شرکت طرح و ساخت اصفهان",
        role="مدیر پروژه",
        company="طرح و ساخت اسپادانا",
        city="اصفهان",
        phone="",
        email="contact@espadana-design.com",
        source_url="https://espadana-design.com",
        confidence="medium"
    )
    id1, action1 = engine.process_contact(c1, run_id="run-1", source_type="web")
    assert action1 == "created_new"

    c2 = ContactEntity(
        entity_type="office",
        name="مهندس بهرامی",
        role="سرپرست کارگاه",
        company="اسپادانا دیزاین",
        city="اصفهان",
        phone="09132223344",
        email="CONTACT@ESPADANA-DESIGN.COM",
        source_url="https://linkedin.com/in/bahrami-espadana",
        confidence="high"
    )
    id2, action2 = engine.process_contact(c2, run_id="run-2", source_type="linkedin")
    assert action2 == "merged_email"
    assert id1 == id2

    contacts = get_all_contacts(test_db)
    assert len(contacts) == 1
    assert contacts[0].phone == "09132223344"
    assert "https://espadana-design.com" in contacts[0].source_url
    assert "https://linkedin.com/in/bahrami-espadana" in contacts[0].source_url


def test_fuzzy_name_company_dedup(test_db):
    engine = DeduplicationEngine(db_path=test_db)

    c1 = ContactEntity(
        entity_type="office",
        name="مهندس کوروش کبیری",
        company="دفتر معماری کبیری و همکاران",
        city="اصفهان",
        source_url="https://kabiri-arch.ir",
        confidence="medium"
    )
    id1, action1 = engine.process_contact(c1, run_id="run-1", source_type="web")
    assert action1 == "created_new"

    # Very close match: کوروش کبیری / دفتر معماری کبیری و همکاران
    c2 = ContactEntity(
        entity_type="office",
        name="کوروش کبیری",
        company="گروه معماری کبیری و همکاران",
        city="اصفهان",
        phone="09139998877",
        source_url="https://instagram.com/kabiri_arch",
        confidence="high"
    )
    id2, action2 = engine.process_contact(c2, run_id="run-2", source_type="instagram")
    assert action2 == "merged_fuzzy"
    assert id1 == id2

    contacts = get_all_contacts(test_db)
    assert len(contacts) == 1
    assert contacts[0].phone == "09139998877"
    assert "https://kabiri-arch.ir" in contacts[0].source_url
    assert "https://instagram.com/kabiri_arch" in contacts[0].source_url


def test_ambiguous_review_quarantine(test_db):
    engine = DeduplicationEngine(db_path=test_db)

    c1 = ContactEntity(
        entity_type="contractor",
        name="احمد میرزایی",
        company="سازه پایدار اصفهان",
        city="اصفهان",
        source_url="https://saze-paydar.ir",
        confidence="medium"
    )
    id1, _ = engine.process_contact(c1, run_id="run-1", source_type="web")

    # Ambiguous match: same first name or partial company (سازه گستر اصفهان vs سازه پایدار اصفهان)
    c2 = ContactEntity(
        entity_type="contractor",
        name="احمد میرزایی",
        company="سازه گستر نوین اصفهان",
        city="اصفهان",
        source_url="https://saze-gostar.ir",
        confidence="medium"
    )
    id2, action2 = engine.process_contact(c2, run_id="run-2", source_type="web")
    assert action2 == "ambiguous_review"
    assert id1 != id2

    # Verify recorded in ambiguous_reviews table
    conn = get_connection(test_db)
    cur = conn.cursor()
    cur.execute("SELECT * FROM ambiguous_reviews")
    reviews = cur.fetchall()
    conn.close()
    assert len(reviews) == 1
    assert reviews[0]["existing_id"] == id1


def test_active_projects_dedup(test_db):
    engine = DeduplicationEngine(db_path=test_db)

    p1 = ActiveProject(
        project_name="برج مسکونی آسمان زاینده‌رود",
        city="اصفهان",
        scale_scope="۱۵ طبقه، ۱۲۰۰۰ مترمربع، نمای کرتین وال",
        associated_contractors="شرکت ساختمانی پرشین",
        associated_architects="مهندسین مشاور نقش جهان",
        source_url="https://persian-const.com/aseman",
        confidence="high"
    )
    id1, action1 = engine.process_project(p1, run_id="run-1", source_type="web")
    assert action1 == "created_new"

    p2 = ActiveProject(
        project_name="برج مسکونی آسمان زاینده رود",
        city="اصفهان",
        scale_scope="۱۵ طبقه مسکونی لوکس",
        associated_contractors="گروه سازه پایدار",
        associated_architects="مهندسین مشاور نقش جهان",
        contact_info="09133334455",
        source_url="https://instagram.com/aseman_tower_esfahan",
        confidence="high"
    )
    id2, action2 = engine.process_project(p2, run_id="run-2", source_type="instagram")
    assert action2 in ("merged_exact", "merged_fuzzy")
    assert id1 == id2

    projects = get_all_projects(test_db)
    assert len(projects) == 1
    merged = projects[0]
    assert "شرکت ساختمانی پرشین" in merged.associated_contractors
    assert "گروه سازه پایدار" in merged.associated_contractors
    assert "https://persian-const.com/aseman" in merged.source_url
    assert "https://instagram.com/aseman_tower_esfahan" in merged.source_url


def test_multi_phone_lossless_merge(test_db):
    engine = DeduplicationEngine(db_path=test_db)

    c1 = ContactEntity(
        entity_type="office",
        name="دفتر معماری رازان",
        company="رازان",
        city="اصفهان",
        phone="03131313160",
        source_url="https://razan.ir",
    )
    id1, action1 = engine.process_contact(c1, run_id="r1", source_type="web")
    assert action1 == "created_new"

    # Candidate has landline + mobile number
    c2 = ContactEntity(
        entity_type="office",
        name="دفتر معماری رازان",
        company="رازان",
        city="اصفهان",
        phone="03131313160; 09131234567",
        source_url="https://instagram.com/razan",
    )
    id2, action2 = engine.process_contact(c2, run_id="r2", source_type="instagram")
    assert action2 == "merged_phone"
    assert id1 == id2

    contacts = get_all_contacts(test_db)
    assert len(contacts) == 1
    # Both numbers must be preserved without corruption
    assert "03131313160" in contacts[0].phone
    assert "09131234567" in contacts[0].phone
    assert "21" not in str(len(contacts[0].phone))  # not concatenated to 21 digits


def test_multi_email_lossless_merge(test_db):
    engine = DeduplicationEngine(db_path=test_db)

    c1 = ContactEntity(
        entity_type="office",
        name="شرکت مهندسی بافت شهر",
        company="بافت شهر",
        email="info@baftshahr.ir",
        source_url="https://baftshahr.ir",
    )
    id1, _ = engine.process_contact(c1, run_id="r1", source_type="web")

    c2 = ContactEntity(
        entity_type="office",
        name="شرکت مهندسی بافت شهر",
        company="بافت شهر",
        email="info@baftshahr.ir; support@baftshahr.ir",
        source_url="https://linkedin.com/company/baftshahr",
    )
    id2, action2 = engine.process_contact(c2, run_id="r2", source_type="linkedin")
    assert action2 == "merged_email"
    assert id1 == id2

    contacts = get_all_contacts(test_db)
    assert len(contacts) == 1
    assert "info@baftshahr.ir" in contacts[0].email
    assert "support@baftshahr.ir" in contacts[0].email


def test_phone_punctuation_and_provinces():
    # Slashes
    assert normalize_phone("۰۹۱۳/۱۲۳-۴۵۶۷") == "09131234567"
    # Dots
    assert normalize_phone("0913.123.4567") == "09131234567"
    # Parentheses
    assert normalize_phone("(031) 31313160") == "03131313160"
    # Shiraz landline with +98
    assert normalize_phone("+987136280000") == "07136280000"
    # Mashhad landline
    assert normalize_phone("05138400000") == "05138400000"
    # Delimited multiple phones
    multi = normalize_phone("09131234567 / 03131313160")
    assert "09131234567" in multi
    assert "03131313160" in multi


def test_clean_entity_name_emojis_and_announcements():
    from normalizer import clean_entity_name
    # Strip pointing emojis and headline prefixes
    t1 = "☝️ ☝️ ☝️ همایش رایگان اسکیس حضوری در اصفهان 🔵 نحوه"
    cleaned1 = clean_entity_name(t1)
    assert "☝️" not in cleaned1
    assert "🔵" not in cleaned1

    t2 = "✅ گزارش جلسات هیات رئیسه گروه تخصصی معماری سازمان"
    cleaned2 = clean_entity_name(t2)
    assert "✅" not in cleaned2

    t3 = "⚜️معرفی پروژه مهستان (عتیق ۲۰) از هلدینگ ساختمانی عقیق⚜️"
    cleaned3 = clean_entity_name(t3)
    assert "⚜️" not in cleaned3
    assert "مهستان (عتیق ۲۰)" in cleaned3

    t4 = "تماس با ما – پرلیت ماهان اصفهان"
    cleaned4 = clean_entity_name(t4)
    assert "تماس با ما" not in cleaned4
    assert cleaned4 == "پرلیت ماهان اصفهان"


def test_no_fuzzy_false_merge_on_generic_names(test_db):
    engine = DeduplicationEngine(db_path=test_db)

    c1 = ContactEntity(
        entity_type="office",
        name="متخصص معماری / ساختمان",
        company="متخصص معماری / ساختمان",
        source_url="https://site1.com",
    )
    id1, action1 = engine.process_contact(c1, run_id="r1", source_type="web")
    assert action1 == "created_new"

    # Completely different person with placeholder name
    c2 = ContactEntity(
        entity_type="contractor",
        name="متخصص معماری / ساختمان",
        company="متخصص معماری / ساختمان",
        source_url="https://site2.com",
    )
    id2, action2 = engine.process_contact(c2, run_id="r2", source_type="web")
    # Must NOT auto-merge generic placeholder names
    assert action2 != "merged_fuzzy"
    assert id1 != id2

