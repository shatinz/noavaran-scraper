import os
import sys
import json
import csv
from typing import List, Dict, Any
from rapidfuzz import fuzz

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from models import ContactEntity, ActiveProject
from database import get_all_contacts, get_all_projects, DEFAULT_DB_PATH
from normalizer import clean_name_for_matching, clean_company_for_matching

# Hand-picked benchmark of 15 known Isfahan architectural and construction entities
KNOWN_ISFAHAN_BENCHMARK = [
    {
        "name": "آروین پنجره پارتاک (نوآوران پنجره)",
        "type": "contractor",
        "keywords": ["آروین پنجره", "نوآوران پنجره", "پارتاک", "arvinpanjereh"],
        "category": "door_window_facade"
    },
    {
        "name": "دفتر معماری رازان",
        "type": "office",
        "keywords": ["رازان", "razan", "razanarchitects"],
        "category": "architecture_office"
    },
    {
        "name": "مهندسین مشاور نقش جهان",
        "type": "office",
        "keywords": ["نقش جهان", "naghsh jahan"],
        "category": "consulting_engineers"
    },
    {
        "name": "گروه معماری پادیاو",
        "type": "office",
        "keywords": ["پادیاو", "padiav"],
        "category": "architecture_office"
    },
    {
        "name": "استودیو معماری شارستان اصفهان",
        "type": "office",
        "keywords": ["شارستان", "sharestan"],
        "category": "architecture_office"
    },
    {
        "name": "شرکت مهندسی بافت شهر اصفهان",
        "type": "office",
        "keywords": ["بافت شهر", "baft shahr"],
        "category": "consulting_engineers"
    },
    {
        "name": "گروه تخصصی معماری سازمان نظام مهندسی اصفهان",
        "type": "office",
        "keywords": ["نظام مهندسی", "esfahan_architects", "گروه تخصصی معماری"],
        "category": "professional_organization"
    },
    {
        "name": "آکادمی معماری اصفهان",
        "type": "student",
        "keywords": ["آکادمی معماری", "esfarch_ac", "academyesf"],
        "category": "education_students"
    },
    {
        "name": "شرکت نما گستران اصفهان",
        "type": "contractor",
        "keywords": ["نما گستران", "نماگستران", "namagostaran"],
        "category": "facade_contractor"
    },
    {
        "name": "گروه ساختمانی پرشین سازه اصفهان",
        "type": "contractor",
        "keywords": ["پرشین سازه", "persian sazeh", "persiansazeh"],
        "category": "building_contractor"
    },
    {
        "name": "استودیو طراحی ارگ اصفهان",
        "type": "office",
        "keywords": ["استودیو ارگ", "طراحی ارگ", "arg design studio", "معماری ارگ"],
        "category": "design_studio"
    },
    {
        "name": "مهندسین مشاور شهر و اندیشه",
        "type": "office",
        "keywords": ["شهر و اندیشه", "shahr andisheh"],
        "category": "consulting_engineers"
    },
    {
        "name": "شرکت پنجره دوجداره پرشیا اصفهان",
        "type": "contractor",
        "keywords": ["پرشیا پنجره", "persiapanjereh", "persia window"],
        "category": "door_window_facade"
    },
    {
        "name": "دفتر معماری فضا، رویداد، شهر",
        "type": "office",
        "keywords": ["فضا رویداد شهر", "فضا، رویداد، شهر", "رویداد شهر"],
        "category": "architecture_office"
    },
    {
        "name": "دانشکده معماری دانشگاه هنر اصفهان",
        "type": "student",
        "keywords": ["هنر اصفهان", "دانشکده معماری", "دانشگاه هنر"],
        "category": "education_students"
    },
]


def run_benchmark_audit(db_path: str = DEFAULT_DB_PATH) -> Dict[str, Any]:
    """Audit harvested cache against the hand-picked Isfahan benchmark."""
    contacts = get_all_contacts(db_path)
    projects = get_all_projects(db_path)

    total_contacts = len(contacts)
    total_projects = len(projects)

    # 1. Check duplicate violations
    phones = [c.phone for c in contacts if c.phone]
    emails = [c.email for c in contacts if c.email]
    unique_phones = len(set(phones))
    unique_emails = len(set(emails))
    duplicate_phones = len(phones) - unique_phones
    duplicate_emails = len(emails) - unique_emails

    # 2. Check category representation
    categories = {}
    for c in contacts:
        categories[c.entity_type] = categories.get(c.entity_type, 0) + 1

    # 3. Benchmark entity recall matching
    matched_benchmark_entities = []
    unmatched_benchmark_entities = []

    for bench in KNOWN_ISFAHAN_BENCHMARK:
        matched = False
        matched_item = None
        for c in contacts:
            c_text = f"{c.name} {c.company} {c.role} {c.social_handle} {c.source_url}".lower()
            if any(k.lower() in c_text for k in bench["keywords"]):
                matched = True
                matched_item = c
                break
        if not matched:
            for p in projects:
                p_text = f"{p.project_name} {p.associated_architects} {p.associated_contractors} {p.source_url}".lower()
                if any(k.lower() in p_text for k in bench["keywords"]):
                    matched = True
                    matched_item = p
                    break

        if matched:
            matched_benchmark_entities.append({
                "benchmark_name": bench["name"],
                "category": bench["category"],
                "matched_record": matched_item.name if hasattr(matched_item, "name") else matched_item.project_name,
            })
        else:
            unmatched_benchmark_entities.append(bench["name"])

    recall_rate = (len(matched_benchmark_entities) / len(KNOWN_ISFAHAN_BENCHMARK)) * 100.0

    # 4. Precision check: percentage of contacts with verified phone, email, or social handle
    valid_contact_points = sum(1 for c in contacts if c.phone or c.email or c.social_handle)
    precision_rate = (valid_contact_points / total_contacts * 100.0) if total_contacts > 0 else 0.0

    report = {
        "total_contacts": total_contacts,
        "total_projects": total_projects,
        "duplicate_phone_violations": duplicate_phones,
        "duplicate_email_violations": duplicate_emails,
        "category_distribution": categories,
        "benchmark_total": len(KNOWN_ISFAHAN_BENCHMARK),
        "benchmark_matched_count": len(matched_benchmark_entities),
        "benchmark_recall_percent": round(recall_rate, 1),
        "contact_precision_percent": round(precision_rate, 1),
        "matched_benchmark_entities": matched_benchmark_entities,
        "unmatched_benchmark_entities": unmatched_benchmark_entities,
    }
    return report


if __name__ == "__main__":
    rep = run_benchmark_audit()
    print("=== BENCHMARK AUDIT REPORT ===")
    print(json.dumps(rep, indent=2, ensure_ascii=False))
