import os
import sys
import tempfile
import pytest
from unittest.mock import MagicMock, patch

import updater
from database import (
    init_db,
    save_lead_crm_status,
    get_lead_crm_status,
    add_crm_activity,
    get_crm_activities,
    get_crm_templates,
    save_crm_template,
    get_crm_pipeline_items,
    upsert_contact_db,
    upsert_project_db,
)
from models import ContactEntity, ActiveProject


def test_updater_parse_version():
    assert updater.parse_version("v2.1.0") == (2, 1, 0)
    assert updater.parse_version("2.1.0") == (2, 1, 0)
    assert updater.parse_version("v2.2") == (2, 2, 0)
    assert updater.parse_version("v3.0.0-beta") == (3, 0, 0)

    assert updater.parse_version("v2.2.0") > updater.parse_version("v2.1.0")
    assert updater.parse_version("v2.1.1") > updater.parse_version("2.1.0")
    assert updater.parse_version("v2.1.0") <= updater.parse_version("v2.1.0")


def test_updater_check_for_updates_newer_release():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "tag_name": "v2.5.0",
        "name": "Release 2.5.0",
        "body": "New feature improvements",
        "assets": [
            {
                "name": "NoavaranScraper.exe",
                "browser_download_url": "https://github.com/shatinz/noavaran-scraper/releases/download/v2.5.0/NoavaranScraper.exe",
                "size": 55000000,
            }
        ],
        "published_at": "2026-10-01T10:00:00Z",
    }

    with patch("requests.get", return_value=mock_resp):
        info = updater.check_for_updates(current_version="2.1.0")
        assert info is not None
        assert info["has_update"] is True
        assert info["latest_version"] == "v2.5.0"
        assert info["download_url"] == "https://github.com/shatinz/noavaran-scraper/releases/download/v2.5.0/NoavaranScraper.exe"
        assert info["asset_name"] == "NoavaranScraper.exe"


def test_updater_check_for_updates_already_latest():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "tag_name": "v2.1.0",
        "name": "Current Release",
        "assets": [],
    }

    with patch("requests.get", return_value=mock_resp):
        info = updater.check_for_updates(current_version="2.1.0")
        assert info is None


def test_crm_database_workflow():
    with tempfile.TemporaryDirectory() as tmp_dir:
        test_db = os.path.join(tmp_dir, "test_crm.db")
        init_db(test_db)

        # 1. Verify default templates seeded
        templates = get_crm_templates(db_path=test_db)
        assert len(templates) >= 6
        sms_tpls = get_crm_templates(channel="sms", db_path=test_db)
        assert any("کاتالوگ" in t["title"] for t in sms_tpls)
        email_tpls = get_crm_templates(channel="email", db_path=test_db)
        assert any("پیشنهاد همکاری" in t["title"] for t in email_tpls)

        # 2. Add sample contact and project
        contact = ContactEntity(
            entity_type="architectural_office",
            name="مهندس علیرضا رضایی",
            company="دفتر معماری فراز اصفهان",
            city="isfahan",
            phone="09131112233",
            email="info@faraz-arch.com",
            source_url="https://example.com/faraz",
        )
        cid = upsert_contact_db(contact, db_path=test_db)

        project = ActiveProject(
            project_name="برج تجاری نگین زاینده‌رود",
            city="isfahan",
            scale_scope="۱۲ طبقه، نمای کرتین‌وال",
            associated_contractors="شرکت عمران اسپادانا",
            contact_info="09139998877",
            source_url="https://example.com/negin",
        )
        pid = upsert_project_db(project, db_path=test_db)

        # 3. Test get_crm_pipeline_items default stage 'new'
        pipeline = get_crm_pipeline_items(db_path=test_db)
        assert len(pipeline) == 2
        contact_lead = next(item for item in pipeline if item["lead_id"] == cid)
        assert contact_lead["stage"] == "new"
        assert contact_lead["title"] == "مهندس علیرضا رضایی"

        # 4. Save lead status update
        save_lead_crm_status(
            lead_id=cid,
            stage="quoted",
            lead_type="contact",
            assigned_to="مهندس محمدی",
            deal_value=850000000,
            follow_up_date="1403/07/20",
            notes="ارسال پیش‌فاکتور مقاطع ترمال‌بریک آکپا سری ۷۵",
            db_path=test_db,
        )

        status = get_lead_crm_status(cid, db_path=test_db)
        assert status is not None
        assert status["stage"] == "quoted"
        assert status["assigned_to"] == "مهندس محمدی"
        assert status["deal_value"] == 850000000
        assert status["follow_up_date"] == "1403/07/20"

        # 5. Add activities and query them
        add_crm_activity(
            lead_id=cid,
            activity_type="تماس تلفنی",
            summary="مذاکره در مورد ضخامت پلی‌آمید و شیشه دوجداره",
            details="کارفرما درخواست تخفیف ۵ درصدی روی متراژ بالای ۵۰۰ متر دارد.",
            db_path=test_db,
        )
        add_crm_activity(
            lead_id=cid,
            activity_type="پیامک",
            summary="ارسال لینک پیش‌فاکتور",
            details="کپی پیامک و ارسال از پنل",
            db_path=test_db,
        )

        activities = get_crm_activities(cid, db_path=test_db)
        assert len(activities) == 2
        assert activities[0]["activity_type"] == "پیامک"  # newest first
        assert "مذاکره" in activities[1]["summary"]

        # 6. Filter pipeline by stage
        quoted_items = get_crm_pipeline_items(stage_filter="quoted", db_path=test_db)
        assert len(quoted_items) == 1
        assert quoted_items[0]["lead_id"] == cid

        new_items = get_crm_pipeline_items(stage_filter="new", db_path=test_db)
        assert len(new_items) == 1
        assert new_items[0]["lead_id"] == pid
