import os
import tempfile
import csv
import pytest
from harvesters.text_parser import (
    extract_phones,
    extract_emails,
    extract_social_handles,
    detect_entity_type,
)
from harvesters.search_engine import SearchHarvester
from models import ContactEntity, ActiveProject
from database import init_db, upsert_contact_db, upsert_project_db
from exporters import export_contacts_to_csv, export_projects_to_csv, export_all_csvs


def test_text_parser():
    sample_text = """
    دفتر معماری رازان در اصفهان
    تلفن همراه: ۰۹۱۳۱۲۳۴۵۶۷ و تلفن دفتر: ۰۳۱-۳۱۳۱۳۱۶۰
    ایمیل: info@razanarchitects.ir
    پیج اینستاگرام: @razanarchitects و کانال تلگرام @razan_channel
    پروژه در حال ساخت مجتمع تجاری با نمای کرتین وال
    """
    phones = extract_phones(sample_text)
    assert "09131234567" in phones
    assert "03131313160" in phones

    emails = extract_emails(sample_text)
    assert "info@razanarchitects.ir" in emails

    handles = extract_social_handles(sample_text)
    assert "@razanarchitects" in handles
    assert "@razan_channel" in handles

    assert detect_entity_type(sample_text) == "office"


def test_search_engine_parsers():
    sh = SearchHarvester()

    # LinkedIn snippet
    li_item = {
        "title": "علیرضا احمدی - مدیرعامل در شرکت مهندسین مشاور اسپادانا | LinkedIn",
        "body": "طراح و ناظر ارشد پروژه‌های ساختمانی و معماری در اصفهان. تلفن: 09132223344",
        "href": "https://ir.linkedin.com/in/alireza-ahmadi",
    }
    c_li = sh.parse_linkedin_snippet(li_item)
    assert c_li is not None
    assert "علیرضا احمدی" in c_li.name
    assert "اسپادانا" in c_li.company
    assert c_li.phone == "09132223344"
    assert c_li.city == "Isfahan"

    # Instagram snippet
    ig_item = {
        "title": "دفتر معماری پادیاو (@padiav_studio) • Instagram photos and videos",
        "body": "طراحی و نظارت پروژه‌های ویلایی و نما در اصفهان. تماس: ۰۹۱۳۳۳۳۴۴۵۵ info@padiav.com",
        "href": "https://www.instagram.com/padiav_studio/",
    }
    c_ig = sh.parse_instagram_snippet(ig_item)
    assert c_ig is not None
    assert c_ig.social_handle == "@padiav_studio"
    assert "09133334455" in c_ig.phone
    assert c_ig.email == "info@padiav.com"

    # Project snippet
    proj_item = {
        "title": "برج مسکونی آسمان زاینده رود اصفهان | مهندسین مشاور",
        "body": "پروژه احداث برج ۲۰ طبقه مسکونی لوکس با نمای مدرن ترمال بریک و کرتین وال در اصفهان. کارفرما: تعاونی مسکن. مجری: گروه ساختمانی پرشیا. تلفن: 03133331122",
        "href": "https://aseman-tower-isfahan.ir/",
    }
    p = sh.parse_web_project_snippet(proj_item)
    assert p is not None
    assert "آسمان" in p.project_name
    assert p.city == "Isfahan"
    assert "20 طبقه" in p.scale_scope or "ترمال بریک" in p.scale_scope

    # Directory/map listing should be rejected
    map_item = {
        "title": "مجتمع تجاری نقش جهان اصفهان؛ آدرس، تلفن، ساعت کاری روی نقشه",
        "body": "لیست مجتمعهای تجاری اداری اصفهان روی نقشه",
        "href": "https://balad.ir/p/مجتمع-تجاری-نقش-جهان",
    }
    p_map = sh.parse_web_project_snippet(map_item)
    assert p_map is None


def test_exporters():
    temp_dir = tempfile.mkdtemp()
    db_path = os.path.join(temp_dir, "test_export.db")
    init_db(db_path)

    c = ContactEntity(
        entity_type="office",
        name="دفتر مهندسی آزمایشی",
        role="معمار",
        company="گروه آزمایشی",
        city="Isfahan",
        phone="09130001122",
        email="test@office.ir",
        social_handle="@test_arch",
        source_url="https://test.ir",
        confidence="verified",
    )
    upsert_contact_db(c, db_path)

    p = ActiveProject(
        project_name="پروژه تست اصفهان",
        city="Isfahan",
        scale_scope="۱۰ طبقه",
        associated_contractors="پیمانکار تست",
        associated_architects="معمار تست",
        contact_info="09130001122",
        source_url="https://test-project.ir",
        confidence="high",
    )
    upsert_project_db(p, db_path)

    contacts_csv = os.path.join(temp_dir, "contacts.csv")
    projects_csv = os.path.join(temp_dir, "active_projects.csv")

    export_contacts_to_csv(contacts_csv, db_path)
    export_projects_to_csv(projects_csv, db_path)

    assert os.path.exists(contacts_csv)
    assert os.path.exists(projects_csv)

    with open(contacts_csv, mode="r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        assert len(rows) == 1
        assert rows[0]["phone"] == "09130001122"
        assert rows[0]["company"] == "گروه آزمایشی"

    with open(projects_csv, mode="r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        assert len(rows) == 1
        assert rows[0]["project name"] == "پروژه تست اصفهان"
        assert rows[0]["associated contractor(s)"] == "پیمانکار تست"


def test_extract_architects_and_contractors():
    from harvesters.text_parser import extract_architects, extract_contractors

    text1 = "پروژه احداث مجتمع تجاری مهستان. طراح: مهندسین مشاور نقش جهان. مجری: گروه ساختمانی پرشیا"
    arch1 = extract_architects(text1)
    cont1 = extract_contractors(text1)
    assert any("نقش جهان" in a for a in arch1)
    assert any("پرشیا" in c for c in cont1)

    text2 = "معرفی پروژه مهستان از هلدینگ ساختمانی عقیق با نمای مدرن کرتین وال"
    cont2 = extract_contractors(text2)
    assert any("هلدینگ ساختمانی عقیق" in c for c in cont2)

    text3 = "طراحی توسط دفتر معماری رازان و اجرای سازه توسط شرکت ساختمانی پرشین"
    arch3 = extract_architects(text3)
    cont3 = extract_contractors(text3)
    assert any("دفتر معماری رازان" in a for a in arch3)
    assert any("شرکت ساختمانی پرشین" in c for c in cont3)


def test_contact_entity_csv_dict_keys():
    from exporters import CONTACTS_CSV_HEADERS, PROJECTS_CSV_HEADERS
    c = ContactEntity(entity_type="office", name="تست")
    c_dict = c.to_csv_dict()
    assert set(c_dict.keys()) == set(CONTACTS_CSV_HEADERS)

    p = ActiveProject(project_name="پروژه تست")
    p_dict = p.to_csv_dict()
    assert set(p_dict.keys()) == set(PROJECTS_CSV_HEADERS)


def test_frontier_queue_operations():
    from database import init_db, add_frontier_urls, get_pending_frontier, update_frontier_status
    temp_dir = tempfile.mkdtemp()
    db_path = os.path.join(temp_dir, "test_frontier.db")
    init_db(db_path)

    urls = [
        {"url": "https://padiav.com", "source_type": "web", "category": "office", "depth": 0},
        {"url": "https://t.me/s/esfarch_ac", "source_type": "telegram", "category": "student", "depth": 0},
    ]
    added = add_frontier_urls(urls, db_path)
    assert added == 2

    # Duplicate url should be ignored
    added_dup = add_frontier_urls([{"url": "https://padiav.com"}], db_path)
    assert added_dup == 0

    pending = get_pending_frontier(limit=10, db_path=db_path)
    assert len(pending) == 2

    # Mark first as visited
    update_frontier_status("https://padiav.com", "visited", db_path)
    pending_after = get_pending_frontier(limit=10, db_path=db_path)
    assert len(pending_after) == 1
    assert pending_after[0]["url"] == "https://t.me/s/esfarch_ac"

