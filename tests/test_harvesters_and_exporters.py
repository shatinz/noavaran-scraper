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
