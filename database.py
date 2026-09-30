import json
import sqlite3
import os
import uuid
from typing import List, Optional, Dict, Any, Tuple
from datetime import datetime

from normalizer import (
    normalize_persian_text,
    normalize_phone,
    normalize_email,
    clean_name_for_matching,
    clean_company_for_matching,
    normalize_city,
)
import sys
from models import ContactEntity, ActiveProject


def get_base_dir() -> str:
    """
    Returns the writable directory for database and exports.
    If running as a frozen executable:
      - Uses the folder containing the .exe if writable (e.g. portable mode).
      - If read-only (e.g. installed in Program Files), safely falls back to %LOCALAPPDATA%/NoavaranScraper.
    """
    if getattr(sys, "frozen", False):
        exe_dir = os.path.dirname(sys.executable)
        try:
            test_path = os.path.join(exe_dir, f".perm_check_{os.getpid()}.tmp")
            with open(test_path, "w") as f:
                f.write("ok")
            os.remove(test_path)
            return exe_dir
        except (PermissionError, OSError):
            appdata = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or os.path.expanduser("~")
            fallback_dir = os.path.join(appdata, "NoavaranScraper")
            os.makedirs(fallback_dir, exist_ok=True)
            return fallback_dir
    return os.path.dirname(os.path.abspath(__file__))


DEFAULT_DB_PATH = os.path.join(get_base_dir(), "data", "scraper_cache.db")


def get_connection(db_path: str = DEFAULT_DB_PATH) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=30.0)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA busy_timeout=30000;")
    except Exception:
        pass
    return conn


def init_db(db_path: str = DEFAULT_DB_PATH) -> None:
    conn = get_connection(db_path)
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS contacts (
        id TEXT PRIMARY KEY,
        entity_type TEXT NOT NULL,
        name TEXT,
        role TEXT,
        company TEXT,
        city TEXT,
        phone TEXT,
        email TEXT,
        social_handle TEXT,
        source_url TEXT,
        confidence TEXT,
        last_verified TEXT,
        normalized_phone TEXT,
        normalized_email TEXT,
        clean_name TEXT,
        clean_company TEXT
    );
    """)

    cur.execute("CREATE INDEX IF NOT EXISTS idx_contacts_phone ON contacts(normalized_phone);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_contacts_email ON contacts(normalized_email);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_contacts_clean_name ON contacts(clean_name);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_contacts_clean_company ON contacts(clean_company);")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS active_projects (
        id TEXT PRIMARY KEY,
        project_name TEXT NOT NULL,
        city TEXT,
        scale_scope TEXT,
        associated_contractors TEXT,
        associated_architects TEXT,
        contact_info TEXT,
        source_url TEXT,
        confidence TEXT,
        date_found TEXT,
        clean_project_name TEXT,
        clean_city TEXT
    );
    """)

    cur.execute("CREATE INDEX IF NOT EXISTS idx_projects_name_city ON active_projects(clean_project_name, clean_city);")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS raw_records (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id TEXT NOT NULL,
        source_type TEXT NOT NULL,
        source_url TEXT,
        raw_json TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS frontier (
        url TEXT PRIMARY KEY,
        source_type TEXT NOT NULL,
        category TEXT,
        depth INTEGER DEFAULT 0,
        status TEXT DEFAULT 'pending',
        discovered_at TEXT,
        visited_at TEXT
    );
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS ambiguous_reviews (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        candidate_type TEXT NOT NULL,
        existing_id TEXT NOT NULL,
        candidate_json TEXT NOT NULL,
        match_score REAL NOT NULL,
        match_reason TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS crm_lead_status (
        lead_id TEXT PRIMARY KEY,
        lead_type TEXT NOT NULL DEFAULT 'contact',
        stage TEXT NOT NULL DEFAULT 'new',
        assigned_to TEXT DEFAULT 'واحد مهندسی فروش',
        deal_value INTEGER DEFAULT 0,
        follow_up_date TEXT,
        notes TEXT,
        updated_at TEXT NOT NULL
    );
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_crm_stage ON crm_lead_status(stage);")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS crm_activities (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        lead_id TEXT NOT NULL,
        activity_type TEXT NOT NULL,
        summary TEXT NOT NULL,
        details TEXT,
        created_at TEXT NOT NULL
    );
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_crm_act_lead ON crm_activities(lead_id);")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS crm_templates (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        channel TEXT NOT NULL,
        stage TEXT NOT NULL,
        subject TEXT,
        content TEXT NOT NULL,
        is_default INTEGER DEFAULT 1
    );
    """)

    # Seed default templates if empty
    cur.execute("SELECT count(*) FROM crm_templates")
    if cur.fetchone()[0] == 0:
        default_templates = [
            (
                "معرفی اولیه و ارسال کاتالوگ مهندسی (پیامک)",
                "sms",
                "new",
                "",
                "جناب مهندس {name} گرامی، وقت بخیر. شرکت نوآوران پنجره، مجری تخصصی درب و پنجره‌های آلومینیوم ترمال‌بریک و نمای کرتین‌وال در پروژه‌های لوکس کشور. کاتالوگ و نمونه‌کارها: https://noavaranpanjereh.com/catalog - تماس: 03133333333",
                1
            ),
            (
                "درخواست ارسال نقشه‌های فاز ۲ جهت برآورد مهندسی (پیامک)",
                "sms",
                "qualified",
                "",
                "مهندس {name} عزیز، پیرو مذاکره در خصوص پروژه {project}، جهت ارسال نقشه فاز ۲ تیپ‌بندی بازشوها برای برآورد دقیق متریال ترمال‌بریک و شیشه لطفا فایل‌ها را به این شماره یا تلگرام ارسال فرمایید. نوآوران پنجره",
                1
            ),
            (
                "پیگیری پیش‌فاکتور مهندسی ارسالی (پیامک)",
                "sms",
                "quoted",
                "",
                "جناب مهندس {name} با سلام، پیش‌فاکتور تفکیکی به همراه آنالیز پروفیل و یراق‌آلات پروژه {project} ارسال گردید. در صورت نیاز به جلسه فنی یا بهینه‌سازی بازشوها در خدمتیم. نوآوران پنجره",
                1
            ),
            (
                "دعوت به بازدید از شوروم و کارخانه نوآوران پنجره (پیامک)",
                "sms",
                "negotiation",
                "",
                "مهندس {name} گرامی، با افتخار از شما دعوت می‌گردد جهت بررسی مقاطع اختصاصی، سیستم‌های لیفت‌اند‌اسلاید و بازدید از خط تولید مدرن نوآوران پنجره مهمان ما باشید. هماهنگی: 03133333333",
                1
            ),
            (
                "پیشنهاد همکاری جامع با دفاتر معماری و مهندسان مشاور (ایمیل)",
                "email",
                "new",
                "پیشنهاد همکاری تخصصی نوآوران پنجره در زمینه سیستم‌های درب، پنجره ترمال‌بریک و نمای کرتین‌وال",
                "جناب آقای/سرکار خانم مهندس {name}\nمدیریت محترم مجموعه {company}\n\nبا سلام و احترام،\nشرکت نوآوران پنجره با بهره‌گیری از خطوط تولید پیشرفته CNC و برترین برندهای پروفیل آلومینیوم اختصاصی و ترمال‌بریک (Akpa، Reynaers، Alumax)، افتخار دارد در زمینه مشاوره، طراحی مهندسی (شاپ‌دراوینگ)، تولید و اجرای سیستم‌های نما و پنجره‌های خاص در کنار شما باشد.\n\nخدمات واحد مهندسی نوآوران پنجره به دفاتر معماری:\n۱. مشاوره فنی و مدلسازی جزییات شاپ دراوینگ پیش از شروع اجرای نما\n۲. محاسبات دقیق استاتیکی، بار باد و لنگر اینرسی مقاطع\n۳. ساخت ماک‌آپ و ارائه دیتیل‌های اجرایی برای سیستم‌های اسلیم و لیفت‌اند‌اسلاید\n۴. بالاترین ضرایب عایق‌بندی صوت و حرارت با تیغه‌های پلی‌آمید استاندارد\n\nخواهشمند است جهت دریافت کاتالوگ جامع و هماهنگی جلسه در دفتر حضرتعالی با واحد مهندسی فروش تماس حاصل فرمایید.\n\nبا تجدید احترام،\nدپارتمان فروش مهندسی نوآوران پنجره\nتلفن: 03133333333 | وب‌سایت: noavaranpanjereh.com",
                1
            ),
            (
                "ارسال پیش‌فاکتور و دفترچه مشخصات فنی (ایمیل)",
                "email",
                "quoted",
                "ارسال پیش‌فاکتور مهندسی و مشخصات فنی بازشوها - پروژه {project}",
                "جناب مهندس {name} گرامی،\nبا سلام و احترام،\n\nپیرو نقشه‌ها و مشخصات دریافتی از پروژه {project}، پیش‌فاکتور تفکیکی به همراه مشخصات فنی مقاطع پروفیل، نوارهای آب‌بندی EPDM، شیشه‌های دوجداره لمینت/گاز آرگون و یراق‌آلات اروپایی به پیوست تقدیم می‌گردد.\n\nتیم مهندسی نوآوران پنجره آماده اعمال هرگونه اصلاحیه، بهینه‌سازی اقتصادی مقاطع و برگزاری جلسه فنی در کارخانه یا کارگاه پروژه می‌باشد.\n\nبا احترام،\nمدیریت مهندسی فروش نوآوران پنجره",
                1
            )
        ]
        cur.executemany("""
            INSERT INTO crm_templates (title, channel, stage, subject, content, is_default)
            VALUES (?, ?, ?, ?, ?, ?)
        """, default_templates)

    conn.commit()
    conn.close()


def log_raw_record(run_id: str, source_type: str, source_url: str, payload: Dict[str, Any], db_path: str = DEFAULT_DB_PATH) -> int:
    conn = get_connection(db_path)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO raw_records (run_id, source_type, source_url, raw_json, created_at)
        VALUES (?, ?, ?, ?, ?)
    """, (
        run_id,
        source_type,
        source_url,
        json.dumps(payload, ensure_ascii=False),
        datetime.now().isoformat()
    ))
    record_id = cur.lastrowid
    conn.commit()
    conn.close()
    return record_id


def save_ambiguous_review(candidate_type: str, existing_id: str, candidate_dict: Dict[str, Any], score: float, reason: str, db_path: str = DEFAULT_DB_PATH) -> int:
    conn = get_connection(db_path)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO ambiguous_reviews (candidate_type, existing_id, candidate_json, match_score, match_reason, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        candidate_type,
        existing_id,
        json.dumps(candidate_dict, ensure_ascii=False),
        float(score),
        reason,
        datetime.now().isoformat()
    ))
    rev_id = cur.lastrowid
    conn.commit()
    conn.close()
    return rev_id


def get_all_contacts(db_path: str = DEFAULT_DB_PATH) -> List[ContactEntity]:
    init_db(db_path)
    conn = get_connection(db_path)
    cur = conn.cursor()
    cur.execute("SELECT * FROM contacts")
    rows = cur.fetchall()
    contacts = []
    for r in rows:
        contacts.append(ContactEntity(
            id=r["id"],
            entity_type=r["entity_type"],
            name=r["name"] or "",
            role=r["role"] or "",
            company=r["company"] or "",
            city=r["city"] or "Isfahan",
            phone=r["phone"] or "",
            email=r["email"] or "",
            social_handle=r["social_handle"] or "",
            source_url=r["source_url"] or "",
            confidence=r["confidence"] or "medium",
            last_verified=r["last_verified"] or datetime.now().strftime("%Y-%m-%d")
        ))
    conn.close()
    return contacts


def get_contact_by_id(contact_id: str, db_path: str = DEFAULT_DB_PATH) -> Optional[ContactEntity]:
    init_db(db_path)
    conn = get_connection(db_path)
    cur = conn.cursor()
    cur.execute("SELECT * FROM contacts WHERE id = ?", (contact_id,))
    r = cur.fetchone()
    conn.close()
    if not r:
        return None
    return ContactEntity(
        id=r["id"],
        entity_type=r["entity_type"],
        name=r["name"] or "",
        role=r["role"] or "",
        company=r["company"] or "",
        city=r["city"] or "Isfahan",
        phone=r["phone"] or "",
        email=r["email"] or "",
        social_handle=r["social_handle"] or "",
        source_url=r["source_url"] or "",
        confidence=r["confidence"] or "medium",
        last_verified=r["last_verified"] or datetime.now().strftime("%Y-%m-%d")
    )


def get_all_projects(db_path: str = DEFAULT_DB_PATH) -> List[ActiveProject]:
    init_db(db_path)
    conn = get_connection(db_path)
    cur = conn.cursor()
    cur.execute("SELECT * FROM active_projects")
    rows = cur.fetchall()
    projects = []
    for r in rows:
        projects.append(ActiveProject(
            id=r["id"],
            project_name=r["project_name"],
            city=r["city"] or "Isfahan",
            scale_scope=r["scale_scope"] or "",
            associated_contractors=r["associated_contractors"] or "",
            associated_architects=r["associated_architects"] or "",
            contact_info=r["contact_info"] or "",
            source_url=r["source_url"] or "",
            confidence=r["confidence"] or "medium",
            date_found=r["date_found"] or datetime.now().strftime("%Y-%m-%d")
        ))
    conn.close()
    return projects


def get_project_by_id(project_id: str, db_path: str = DEFAULT_DB_PATH) -> Optional[ActiveProject]:
    init_db(db_path)
    conn = get_connection(db_path)
    cur = conn.cursor()
    cur.execute("SELECT * FROM active_projects WHERE id = ?", (project_id,))
    r = cur.fetchone()
    conn.close()
    if not r:
        return None
    return ActiveProject(
        id=r["id"],
        project_name=r["project_name"],
        city=r["city"] or "Isfahan",
        scale_scope=r["scale_scope"] or "",
        associated_contractors=r["associated_contractors"] or "",
        associated_architects=r["associated_architects"] or "",
        contact_info=r["contact_info"] or "",
        source_url=r["source_url"] or "",
        confidence=r["confidence"] or "medium",
        date_found=r["date_found"] or datetime.now().strftime("%Y-%m-%d")
    )


def upsert_contact_db(contact: ContactEntity, db_path: str = DEFAULT_DB_PATH) -> str:
    if not contact.id:
        contact.id = str(uuid.uuid4())
    norm_phone = normalize_phone(contact.phone)
    norm_email = normalize_email(contact.email)
    clean_name = clean_name_for_matching(contact.name)
    clean_comp = clean_company_for_matching(contact.company)
    norm_city = normalize_city(contact.city)

    conn = get_connection(db_path)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO contacts (
            id, entity_type, name, role, company, city, phone, email,
            social_handle, source_url, confidence, last_verified,
            normalized_phone, normalized_email, clean_name, clean_company
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            entity_type=excluded.entity_type,
            name=excluded.name,
            role=excluded.role,
            company=excluded.company,
            city=excluded.city,
            phone=excluded.phone,
            email=excluded.email,
            social_handle=excluded.social_handle,
            source_url=excluded.source_url,
            confidence=excluded.confidence,
            last_verified=excluded.last_verified,
            normalized_phone=excluded.normalized_phone,
            normalized_email=excluded.normalized_email,
            clean_name=excluded.clean_name,
            clean_company=excluded.clean_company
    """, (
        contact.id, contact.entity_type, contact.name, contact.role,
        contact.company, norm_city, norm_phone, norm_email,
        contact.social_handle, contact.source_url, contact.confidence,
        contact.last_verified, norm_phone, norm_email, clean_name, clean_comp
    ))
    conn.commit()
    conn.close()
    return contact.id


def upsert_project_db(project: ActiveProject, db_path: str = DEFAULT_DB_PATH) -> str:
    if not project.id:
        project.id = str(uuid.uuid4())
    clean_name = clean_name_for_matching(project.project_name)
    clean_city = normalize_city(project.city).lower()

    conn = get_connection(db_path)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO active_projects (
            id, project_name, city, scale_scope, associated_contractors,
            associated_architects, contact_info, source_url, confidence,
            date_found, clean_project_name, clean_city
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            project_name=excluded.project_name,
            city=excluded.city,
            scale_scope=excluded.scale_scope,
            associated_contractors=excluded.associated_contractors,
            associated_architects=excluded.associated_architects,
            contact_info=excluded.contact_info,
            source_url=excluded.source_url,
            confidence=excluded.confidence,
            date_found=excluded.date_found,
            clean_project_name=excluded.clean_project_name,
            clean_city=excluded.clean_city
    """, (
        project.id, project.project_name, project.city, project.scale_scope,
        project.associated_contractors, project.associated_architects,
        project.contact_info, project.source_url, project.confidence,
        project.date_found, clean_name, clean_city
    ))
    conn.commit()
    conn.close()
    return project.id


def add_frontier_urls(urls: List[Dict[str, Any]], db_path: str = DEFAULT_DB_PATH) -> int:
    conn = get_connection(db_path)
    cur = conn.cursor()
    added = 0
    for item in urls:
        url = item.get("url", "").strip()
        if not url:
            continue
        try:
            cur.execute("""
                INSERT OR IGNORE INTO frontier (url, source_type, category, depth, status, discovered_at)
                VALUES (?, ?, ?, ?, 'pending', ?)
            """, (
                url,
                item.get("source_type", "web"),
                item.get("category", "general"),
                item.get("depth", 0),
                datetime.now().isoformat()
            ))
            if cur.rowcount > 0:
                added += 1
        except Exception:
            pass
    conn.commit()
    conn.close()
    return added


def get_pending_frontier(limit: int = 10, db_path: str = DEFAULT_DB_PATH) -> List[Dict[str, Any]]:
    conn = get_connection(db_path)
    cur = conn.cursor()
    cur.execute("SELECT * FROM frontier WHERE status = 'pending' ORDER BY depth ASC LIMIT ?", (limit,))
    rows = cur.fetchall()
    results = [dict(r) for r in rows]
    conn.close()
    return results


def update_frontier_status(url: str, status: str, db_path: str = DEFAULT_DB_PATH) -> None:
    conn = get_connection(db_path)
    cur = conn.cursor()
    cur.execute("""
        UPDATE frontier SET status = ?, visited_at = ? WHERE url = ?
    """, (status, datetime.now().isoformat(), url))
    conn.commit()
    conn.close()


def get_ambiguous_reviews(db_path: str = DEFAULT_DB_PATH) -> List[Dict[str, Any]]:
    init_db(db_path)
    conn = get_connection(db_path)
    cur = conn.cursor()
    cur.execute("SELECT id, candidate_type, existing_id, candidate_json, match_score, match_reason, created_at FROM ambiguous_reviews ORDER BY id DESC")
    rows = cur.fetchall()
    results = [dict(r) for r in rows]
    conn.close()
    return results


def get_cache_stats(db_path: str = DEFAULT_DB_PATH) -> Dict[str, int]:
    init_db(db_path)
    conn = get_connection(db_path)
    cur = conn.cursor()
    cur.execute("SELECT count(*) FROM contacts")
    c_count = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM active_projects")
    p_count = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM raw_records")
    raw_count = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM ambiguous_reviews")
    amb_count = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM frontier")
    front_count = cur.fetchone()[0]
    conn.close()
    return {
        "contacts": c_count,
        "projects": p_count,
        "raw_records": raw_count,
        "ambiguous_reviews": amb_count,
        "frontier": front_count,
    }


def get_lead_crm_status(lead_id: str, db_path: str = DEFAULT_DB_PATH) -> Optional[Dict[str, Any]]:
    init_db(db_path)
    conn = get_connection(db_path)
    cur = conn.cursor()
    cur.execute("SELECT * FROM crm_lead_status WHERE lead_id = ?", (lead_id,))
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def save_lead_crm_status(
    lead_id: str,
    stage: str,
    lead_type: str = "contact",
    assigned_to: str = "واحد مهندسی فروش",
    deal_value: int = 0,
    follow_up_date: str = "",
    notes: str = "",
    db_path: str = DEFAULT_DB_PATH
) -> None:
    init_db(db_path)
    conn = get_connection(db_path)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO crm_lead_status (lead_id, lead_type, stage, assigned_to, deal_value, follow_up_date, notes, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(lead_id) DO UPDATE SET
            stage = excluded.stage,
            lead_type = excluded.lead_type,
            assigned_to = excluded.assigned_to,
            deal_value = excluded.deal_value,
            follow_up_date = excluded.follow_up_date,
            notes = excluded.notes,
            updated_at = excluded.updated_at
    """, (
        lead_id,
        lead_type,
        stage,
        assigned_to,
        int(deal_value or 0),
        follow_up_date or "",
        notes or "",
        datetime.now().isoformat()
    ))
    conn.commit()
    conn.close()


def add_crm_activity(
    lead_id: str,
    activity_type: str,
    summary: str,
    details: str = "",
    db_path: str = DEFAULT_DB_PATH
) -> int:
    init_db(db_path)
    conn = get_connection(db_path)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO crm_activities (lead_id, activity_type, summary, details, created_at)
        VALUES (?, ?, ?, ?, ?)
    """, (
        lead_id,
        activity_type,
        summary,
        details or "",
        datetime.now().isoformat()
    ))
    act_id = cur.lastrowid
    conn.commit()
    conn.close()
    return act_id


def get_crm_activities(lead_id: str, db_path: str = DEFAULT_DB_PATH) -> List[Dict[str, Any]]:
    init_db(db_path)
    conn = get_connection(db_path)
    cur = conn.cursor()
    cur.execute("""
        SELECT * FROM crm_activities
        WHERE lead_id = ?
        ORDER BY id DESC
    """, (lead_id,))
    rows = cur.fetchall()
    results = [dict(r) for r in rows]
    conn.close()
    return results


def get_crm_templates(
    channel: Optional[str] = None,
    stage: Optional[str] = None,
    db_path: str = DEFAULT_DB_PATH
) -> List[Dict[str, Any]]:
    init_db(db_path)
    conn = get_connection(db_path)
    cur = conn.cursor()
    query = "SELECT * FROM crm_templates WHERE 1=1"
    params: List[Any] = []
    if channel:
        query += " AND channel = ?"
        params.append(channel)
    if stage:
        query += " AND (stage = ? OR stage = 'all')"
        params.append(stage)
    query += " ORDER BY id ASC"
    cur.execute(query, tuple(params))
    rows = cur.fetchall()
    results = [dict(r) for r in rows]
    conn.close()
    return results


def save_crm_template(
    title: str,
    channel: str,
    stage: str,
    content: str,
    subject: str = "",
    is_default: int = 0,
    db_path: str = DEFAULT_DB_PATH
) -> int:
    init_db(db_path)
    conn = get_connection(db_path)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO crm_templates (title, channel, stage, subject, content, is_default)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (title, channel, stage, subject or "", content, is_default))
    tid = cur.lastrowid
    conn.commit()
    conn.close()
    return tid


def get_crm_pipeline_items(
    stage_filter: Optional[str] = None,
    db_path: str = DEFAULT_DB_PATH
) -> List[Dict[str, Any]]:
    """
    Returns unified list of leads (contacts and projects) merged with their CRM pipeline status.
    """
    init_db(db_path)
    conn = get_connection(db_path)
    cur = conn.cursor()

    cur.execute("""
        SELECT 
            c.id AS lead_id,
            'contact' AS lead_type,
            COALESCE(c.name, c.company, 'نامشخص') AS title,
            c.entity_type AS subtitle,
            c.company,
            c.city,
            c.phone,
            c.email,
            c.source_url,
            COALESCE(s.stage, 'new') AS stage,
            COALESCE(s.assigned_to, 'واحد مهندسی فروش') AS assigned_to,
            COALESCE(s.deal_value, 0) AS deal_value,
            COALESCE(s.follow_up_date, '') AS follow_up_date,
            COALESCE(s.notes, '') AS notes,
            COALESCE(s.updated_at, c.last_verified) AS updated_at
        FROM contacts c
        LEFT JOIN crm_lead_status s ON c.id = s.lead_id
        
        UNION ALL
        
        SELECT 
            p.id AS lead_id,
            'project' AS lead_type,
            p.project_name AS title,
            'پروژه ساختمانی' AS subtitle,
            COALESCE(p.associated_contractors, p.associated_architects, '') AS company,
            p.city,
            p.contact_info AS phone,
            '' AS email,
            p.source_url,
            COALESCE(s.stage, 'new') AS stage,
            COALESCE(s.assigned_to, 'واحد مهندسی فروش') AS assigned_to,
            COALESCE(s.deal_value, 0) AS deal_value,
            COALESCE(s.follow_up_date, '') AS follow_up_date,
            COALESCE(s.notes, '') AS notes,
            COALESCE(s.updated_at, p.date_found) AS updated_at
        FROM active_projects p
        LEFT JOIN crm_lead_status s ON p.id = s.lead_id
    """)

    rows = cur.fetchall()
    all_items = [dict(r) for r in rows]
    conn.close()

    if stage_filter and stage_filter != "all":
        all_items = [item for item in all_items if item["stage"] == stage_filter]

    return all_items

