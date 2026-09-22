import csv
import os
from typing import List, Optional
from database import get_all_contacts, get_all_projects, DEFAULT_DB_PATH
from models import ContactEntity, ActiveProject

PROJECTS_CSV_PATH = os.path.join(os.path.dirname(__file__), "active_projects.csv")
CONTACTS_CSV_PATH = os.path.join(os.path.dirname(__file__), "contacts.csv")

PROJECTS_CSV_HEADERS = [
    "project name",
    "city",
    "scale/scope",
    "associated contractor(s)",
    "associated architect(s)/office",
    "contact info",
    "source URL",
    "confidence",
    "date found",
]

CONTACTS_CSV_HEADERS = [
    "entity_type (office/contractor/student/individual)",
    "name",
    "role",
    "company",
    "city",
    "phone",
    "email",
    "social handle",
    "source_url",
    "confidence",
    "last_verified",
]


def export_projects_to_csv(csv_path: str = PROJECTS_CSV_PATH, db_path: str = DEFAULT_DB_PATH) -> int:
    """Export all active projects from database to active_projects.csv with UTF-8 BOM."""
    projects: List[ActiveProject] = get_all_projects(db_path)
    os.makedirs(os.path.dirname(os.path.abspath(csv_path)), exist_ok=True)
    with open(csv_path, mode="w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=PROJECTS_CSV_HEADERS)
        writer.writeheader()
        for p in projects:
            row = {
                "project name": p.project_name,
                "city": p.city,
                "scale/scope": p.scale_scope,
                "associated contractor(s)": p.associated_contractors,
                "associated architect(s)/office": p.associated_architects,
                "contact info": p.contact_info,
                "source URL": p.source_url,
                "confidence": p.confidence,
                "date found": p.date_found,
            }
            writer.writerow(row)
    return len(projects)


def export_contacts_to_csv(csv_path: str = CONTACTS_CSV_PATH, db_path: str = DEFAULT_DB_PATH) -> int:
    """Export all contacts from database to contacts.csv with UTF-8 BOM."""
    contacts: List[ContactEntity] = get_all_contacts(db_path)
    os.makedirs(os.path.dirname(os.path.abspath(csv_path)), exist_ok=True)
    with open(csv_path, mode="w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=CONTACTS_CSV_HEADERS)
        writer.writeheader()
        for c in contacts:
            row = {
                "entity_type (office/contractor/student/individual)": c.entity_type,
                "name": c.name,
                "role": c.role,
                "company": c.company,
                "city": c.city,
                "phone": c.phone,
                "email": c.email,
                "social handle": c.social_handle,
                "source_url": c.source_url,
                "confidence": c.confidence,
                "last_verified": c.last_verified,
            }
            writer.writerow(row)
    return len(contacts)


def export_all_csvs(db_path: str = DEFAULT_DB_PATH) -> dict:
    """Export both active_projects.csv and contacts.csv."""
    proj_count = export_projects_to_csv(PROJECTS_CSV_PATH, db_path)
    cont_count = export_contacts_to_csv(CONTACTS_CSV_PATH, db_path)
    return {
        "projects_exported": proj_count,
        "contacts_exported": cont_count,
        "projects_file": PROJECTS_CSV_PATH,
        "contacts_file": CONTACTS_CSV_PATH,
    }
