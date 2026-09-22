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
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
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

