import json
import os
import re
from typing import Optional, Tuple, Dict, Any, List
from rapidfuzz import fuzz

from normalizer import (
    normalize_persian_text,
    normalize_phone,
    normalize_email,
    clean_entity_name,
    clean_person_name,
    clean_name_for_matching,
    clean_company_for_matching,
    normalize_city,
    transliterate_persian_to_latin,
    GENERIC_TITLES,
)
from models import ContactEntity, ActiveProject
from database import (
    get_connection,
    log_raw_record,
    save_ambiguous_review,
    upsert_contact_db,
    upsert_project_db,
    get_all_contacts,
    get_all_projects,
    DEFAULT_DB_PATH,
)
from harvesters.text_parser import is_excluded_project, is_excluded_domain

AUTO_MERGE_SCORE_THRESHOLD = 88.0
AMBIGUOUS_SCORE_THRESHOLD = 70.0


def merge_delimited_values(val1: Optional[str], val2: Optional[str]) -> str:
    """Combine two semicolon-separated values without duplicates or data loss."""
    items = []
    seen = set()
    for v in (val1, val2):
        if not v:
            continue
        for part in re.split(r'[;\n]+', str(v)):
            p = part.strip()
            if p and p not in seen:
                seen.add(p)
                items.append(p)
    return "; ".join(items)


def merge_source_urls(url1: Optional[str], url2: Optional[str]) -> str:
    """Combine two semicolon-separated URL strings without duplicates or data loss."""
    return merge_delimited_values(url1, url2)


def choose_better_entity_type(type1: Optional[str], type2: Optional[str]) -> str:
    """Prioritize organizational entity types over generic individual."""
    priority = {"office": 4, "contractor": 4, "student": 3, "individual": 1}
    p1 = priority.get(type1 or "", 0)
    p2 = priority.get(type2 or "", 0)
    return (type1 if p1 >= p2 else type2) or "office"


def choose_best_name(name1: Optional[str], name2: Optional[str]) -> str:
    """Select the cleanest, most authoritative entity name without announcement spam or generic placeholders."""
    n1 = clean_entity_name(name1)
    n2 = clean_entity_name(name2)
    if not n1:
        return n2
    if not n2:
        return n1

    is_n1_generic = any(gw in n1.lower() for gw in ['متخصص معماری', 'صفحه اصلی', 'درباره ما', 'تماس با ما', 'دفتر معماری / پیمانکار', 'دفتر معماری و مهندسی اصفهان']) or n1.lower() in GENERIC_TITLES
    is_n2_generic = any(gw in n2.lower() for gw in ['متخصص معماری', 'صفحه اصلی', 'درباره ما', 'تماس با ما', 'دفتر معماری / پیمانکار', 'دفتر معماری و مهندسی اصفهان']) or n2.lower() in GENERIC_TITLES

    if is_n1_generic and not is_n2_generic:
        return n2
    if is_n2_generic and not is_n1_generic:
        return n1

    is_n1_announcement = any(k in n1 for k in ['همایش', 'گزارش', 'اطلاعیه', 'ثبت نام', 'کلاس', 'وبینار', 'جلسات', 'نتایج']) or len(n1) > 60
    is_n2_announcement = any(k in n2 for k in ['همایش', 'گزارش', 'اطلاعیه', 'ثبت نام', 'کلاس', 'وبینار', 'جلسات', 'نتایج']) or len(n2) > 60
    if is_n1_announcement and not is_n2_announcement:
        return n2
    if is_n2_announcement and not is_n1_announcement:
        return n1

    if n1.startswith(('مهندس', 'دکتر', 'آرشیتکت')) and not n2.startswith(('مهندس', 'دکتر', 'آرشیتکت')):
        return n1
    if n2.startswith(('مهندس', 'دکتر', 'آرشیتکت')) and not n1.startswith(('مهندس', 'دکتر', 'آرشیتکت')):
        return n2

    # Prefer Persian name if one is Persian and the other is English
    has_persian_n1 = any('\u0600' <= ch <= '\u06FF' for ch in n1)
    has_persian_n2 = any('\u0600' <= ch <= '\u06FF' for ch in n2)
    if has_persian_n1 and not has_persian_n2:
        return n1
    if has_persian_n2 and not has_persian_n1:
        return n2

    return n1 if len(n1) >= len(n2) else n2


def merge_two_contacts(existing: ContactEntity, candidate: ContactEntity, merge_reason: str = "fuzzy_match") -> ContactEntity:
    """Merge two contact entities, preserving all URLs, phones, and emails without data loss."""
    merged_urls = merge_delimited_values(existing.source_url, candidate.source_url)
    merged_phones = merge_delimited_values(existing.phone, candidate.phone)
    merged_emails = merge_delimited_values(existing.email, candidate.email)
    merged_handles = merge_delimited_values(existing.social_handle, candidate.social_handle)

    name = choose_best_name(existing.name, candidate.name)
    company = choose_best_name(existing.company, candidate.company)
    role = existing.role or candidate.role

    # City selection: prefer explicitly discovered city over default fallback "Isfahan"
    if existing.city == "Isfahan" and candidate.city and candidate.city != "Isfahan":
        city = candidate.city
    elif candidate.city == "Isfahan" and existing.city and existing.city != "Isfahan":
        city = existing.city
    else:
        city = existing.city or candidate.city

    entity_type = choose_better_entity_type(existing.entity_type, candidate.entity_type)

    confidence = existing.confidence
    if merge_reason in ("exact_phone", "exact_email"):
        confidence = "verified"
    elif merge_reason == "high_fuzzy":
        confidence = "high_fuzzy" if existing.confidence not in ("verified", "high") else existing.confidence

    last_verified = max(existing.last_verified, candidate.last_verified)

    return ContactEntity(
        id=existing.id,
        entity_type=entity_type,
        name=name.strip(),
        role=role.strip(),
        company=company.strip(),
        city=city.strip(),
        phone=merged_phones.strip(),
        email=merged_emails.strip(),
        social_handle=merged_handles.strip(),
        source_url=merged_urls.strip(),
        confidence=confidence,
        last_verified=last_verified,
    )


def merge_two_projects(existing: ActiveProject, candidate: ActiveProject) -> ActiveProject:
    """Merge two active projects, combining contractors, architects, and URLs."""
    merged_urls = merge_source_urls(existing.source_url, candidate.source_url)

    # Combine contractors
    contractors = []
    seen_c = set()
    for c in (existing.associated_contractors or "").split(";"):
        item = c.strip()
        if item and item not in seen_c:
            seen_c.add(item)
            contractors.append(item)
    for c in (candidate.associated_contractors or "").split(";"):
        item = c.strip()
        if item and item not in seen_c:
            seen_c.add(item)
            contractors.append(item)

    # Combine architects
    architects = []
    seen_a = set()
    for a in (existing.associated_architects or "").split(";"):
        item = a.strip()
        if item and item not in seen_a:
            seen_a.add(item)
            architects.append(item)
    for a in (candidate.associated_architects or "").split(";"):
        item = a.strip()
        if item and item not in seen_a:
            seen_a.add(item)
            architects.append(item)

    # Scale/scope: pick longer/richer
    scale = existing.scale_scope if len(existing.scale_scope) >= len(candidate.scale_scope) else candidate.scale_scope
    contact_info = merge_delimited_values(existing.contact_info, candidate.contact_info)
    date_found = min(existing.date_found, candidate.date_found)
    pname = choose_best_name(existing.project_name, candidate.project_name)

    return ActiveProject(
        id=existing.id,
        project_name=pname,
        city=existing.city or candidate.city,
        scale_scope=scale,
        associated_contractors="; ".join(contractors),
        associated_architects="; ".join(architects),
        contact_info=contact_info,
        source_url=merged_urls,
        confidence="verified" if existing.confidence == "verified" or candidate.confidence == "verified" else "high",
        date_found=date_found,
    )


class DeduplicationEngine:
    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        self.db_path = db_path
        self.raw_log_path = os.path.join(os.path.dirname(os.path.abspath(db_path)), "raw_records.jsonl")

    def log_raw_entry(self, run_id: str, source_type: str, source_url: str, payload: Dict[str, Any]) -> int:
        # 1. Log to DB
        rec_id = log_raw_record(run_id, source_type, source_url, payload, self.db_path)
        # 2. Append to raw_records.jsonl file
        os.makedirs(os.path.dirname(self.raw_log_path), exist_ok=True)
        with open(self.raw_log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps({
                "record_id": rec_id,
                "run_id": run_id,
                "source_type": source_type,
                "source_url": source_url,
                "payload": payload,
            }, ensure_ascii=False) + "\n")
        return rec_id

    def process_contact(self, candidate: ContactEntity, run_id: str, source_type: str) -> Tuple[str, str]:
        """
        Process incoming contact entity through deduplication hierarchy:
        1. Exact Phone match -> Auto-merge
        2. Exact Email match -> Auto-merge
        3. Fuzzy Name+Company composite match:
           - >= 88% -> Auto-merge (high_fuzzy)
           - 70-87% -> Ambiguous Quarantine (Flagged for Review)
           - < 70% -> New Entity
        Returns (entity_id, action_taken: 'merged_phone'|'merged_email'|'merged_fuzzy'|'ambiguous_review'|'created_new')
        """
        # Step 0: Record pre-merge raw payload
        self.log_raw_entry(run_id, source_type, candidate.source_url, candidate.model_dump())

        # Exclude contacts from non-target / marketplace / encyclopedia domains
        if is_excluded_domain(candidate.source_url):
            return "", "excluded_domain"

        EXCLUDED_COMP_NAMES = {'کارفرما', 'پیمانکار', 'طراح', 'دانشنامه', 'ویکی پدیا', 'ویکی‌پدیا', 'بانک اطلاعات'}
        if candidate.name in EXCLUDED_COMP_NAMES or any(k in candidate.name for k in ['بانک اطلاعات', 'ویکی پدیا', 'اطلاعات ساختمان']):
            return "", "excluded_generic"

        norm_phone = normalize_phone(candidate.phone)
        norm_email = normalize_email(candidate.email)
        clean_name = clean_name_for_matching(candidate.name)
        clean_comp = clean_company_for_matching(candidate.company)

        conn = get_connection(self.db_path)
        cur = conn.cursor()

        # Step 1: Exact Phone Match (Check each candidate phone against existing records)
        cand_phones = [p.strip() for p in norm_phone.split(';') if p.strip()]
        for p in cand_phones:
            cur.execute("SELECT * FROM contacts WHERE normalized_phone LIKE ? AND normalized_phone != ''", (f"%{p}%",))
            rows = cur.fetchall()
            for row in rows:
                ex_phones = [x.strip() for x in (row["normalized_phone"] or "").split(';')]
                if p in ex_phones:
                    existing = ContactEntity(**{k: row[k] for k in row.keys() if k in ContactEntity.model_fields})
                    merged = merge_two_contacts(existing, candidate, merge_reason="exact_phone")
                    upsert_contact_db(merged, self.db_path)
                    conn.close()
                    return merged.id, "merged_phone"

        # Step 2: Exact Email Match (Check each candidate email against existing records)
        cand_emails = [e.strip().lower() for e in norm_email.split(';') if e.strip()]
        for em in cand_emails:
            cur.execute("SELECT * FROM contacts WHERE normalized_email LIKE ? AND normalized_email != ''", (f"%{em}%",))
            rows = cur.fetchall()
            for row in rows:
                ex_emails = [x.strip().lower() for x in (row["normalized_email"] or "").split(';')]
                if em in ex_emails:
                    existing = ContactEntity(**{k: row[k] for k in row.keys() if k in ContactEntity.model_fields})
                    merged = merge_two_contacts(existing, candidate, merge_reason="exact_email")
                    upsert_contact_db(merged, self.db_path)
                    conn.close()
                    return merged.id, "merged_email"

        # Step 3: Fuzzy Composite Match on Name + Company (Cross-lingual aware)
        cur.execute("SELECT * FROM contacts")
        all_rows = cur.fetchall()
        conn.close()

        cand_composite = f"{clean_name} {clean_comp}".strip()
        cand_composite_lat = transliterate_persian_to_latin(cand_composite)
        cand_comp_lat = transliterate_persian_to_latin(clean_comp)
        cand_name_lat = transliterate_persian_to_latin(clean_name)

        GENERIC_STOPWORDS = {
            'متخصص معماری ساختمان', 'دفتر معماری مهندسی اصفهان', 'contact us', 'about us',
            'صفحه اصلی', 'درباره ما', 'تماس با ما', 'پروژه ساختمانی'
        }
        is_generic = any(gw in clean_name for gw in GENERIC_STOPWORDS) or any(gw in clean_comp for gw in GENERIC_STOPWORDS)

        best_score = 0.0
        best_match_row = None
        best_reason = ""

        if len(cand_composite) >= 3 and not is_generic:
            for r in all_rows:
                ex_name = r["clean_name"] or ""
                ex_comp = r["clean_company"] or ""
                ex_composite = f"{ex_name} {ex_comp}".strip()

                if not ex_composite or ex_composite in GENERIC_STOPWORDS:
                    continue

                # 1. Native composite RapidFuzz token sort and set ratio
                sort_ratio = fuzz.token_sort_ratio(cand_composite, ex_composite)
                set_ratio = fuzz.token_set_ratio(cand_composite, ex_composite)
                composite_score = max(sort_ratio, set_ratio)

                # 2. Cross-lingual / transliterated match (English <-> Persian)
                ex_composite_lat = transliterate_persian_to_latin(ex_composite)
                ex_comp_lat = transliterate_persian_to_latin(ex_comp)
                ex_name_lat = transliterate_persian_to_latin(ex_name)

                lat_sort = fuzz.token_sort_ratio(cand_composite_lat, ex_composite_lat) if cand_composite_lat and ex_composite_lat else 0.0
                lat_set = fuzz.token_set_ratio(cand_composite_lat, ex_composite_lat) if cand_composite_lat and ex_composite_lat else 0.0
                lat_comp_ratio = fuzz.token_sort_ratio(cand_comp_lat, ex_comp_lat) if cand_comp_lat and ex_comp_lat else 0.0
                lat_name_ratio = fuzz.token_sort_ratio(cand_name_lat, ex_name_lat) if cand_name_lat and ex_name_lat else 0.0

                cross_score = max(lat_sort, lat_set)
                is_cand_firm = (not clean_name or clean_name == clean_comp or clean_comp in clean_name)
                is_ex_firm = (not ex_name or ex_name == ex_comp or ex_comp in ex_name)

                if is_cand_firm and is_ex_firm:
                    if cand_comp_lat and ex_comp_lat and len(cand_comp_lat) >= 4 and len(ex_comp_lat) >= 4 and lat_comp_ratio >= 88.0:
                        cross_score = max(cross_score, lat_comp_ratio)
                else:
                    if lat_name_ratio >= 88.0 and lat_comp_ratio >= 85.0:
                        cross_score = max(cross_score, (lat_name_ratio + lat_comp_ratio) / 2.0)

                score = max(composite_score, cross_score)

                # If name and company match closely, boost confidence
                name_ratio = fuzz.token_sort_ratio(clean_name, ex_name) if clean_name and ex_name else 0.0
                comp_ratio = fuzz.token_sort_ratio(clean_comp, ex_comp) if clean_comp and ex_comp else 0.0
                if name_ratio >= 90.0 and comp_ratio >= 85.0:
                    score = max(score, (name_ratio + comp_ratio) / 2.0)

                if score > best_score:
                    best_score = score
                    best_match_row = r
                    best_reason = f"Composite: {score:.1f} (native: {composite_score:.1f}, cross: {cross_score:.1f})"

        # Decision based on score thresholds
        if best_score >= AUTO_MERGE_SCORE_THRESHOLD and best_match_row:
            existing = ContactEntity(**{k: best_match_row[k] for k in best_match_row.keys() if k in ContactEntity.model_fields})
            merged = merge_two_contacts(existing, candidate, merge_reason="high_fuzzy")
            upsert_contact_db(merged, self.db_path)
            return merged.id, "merged_fuzzy"

        elif best_score >= AMBIGUOUS_SCORE_THRESHOLD and best_match_row:
            # Ambiguous match: quarantine to review log and DO NOT auto-merge
            save_ambiguous_review(
                candidate_type="contact",
                existing_id=best_match_row["id"],
                candidate_dict=candidate.model_dump(),
                score=best_score,
                reason=best_reason,
                db_path=self.db_path
            )
            # Insert as separate contact but tagged with ambiguous review notice
            candidate.confidence = "ambiguous_review_flagged"
            new_id = upsert_contact_db(candidate, self.db_path)
            return new_id, "ambiguous_review"

        # Distinct new entity
        new_id = upsert_contact_db(candidate, self.db_path)
        return new_id, "created_new"

    def process_project(self, candidate: ActiveProject, run_id: str, source_type: str) -> Tuple[str, str]:
        """
        Process incoming active project:
        1. Exact match on clean_project_name and clean_city -> Auto-merge
        2. Fuzzy match on project name within same city:
           - >= 85% -> Auto-merge
           - 68-84% -> Ambiguous review flag
           - < 68% -> New Project
        """
        # Step 0: Record pre-merge raw payload
        self.log_raw_entry(run_id, source_type, candidate.source_url, candidate.model_dump())

        # Exclude commercial database listings, shops, and marketplaces
        if is_excluded_project(candidate.source_url, candidate.project_name):
            return "", "excluded_project"

        clean_pname = clean_name_for_matching(candidate.project_name)
        clean_city = normalize_city(candidate.city).lower()

        conn = get_connection(self.db_path)
        cur = conn.cursor()

        # Step 1: Exact Name + City Match
        cur.execute("SELECT * FROM active_projects WHERE clean_project_name = ? AND clean_city = ?", (clean_pname, clean_city))
        row = cur.fetchone()
        if row:
            existing = ActiveProject(**{k: row[k] for k in row.keys() if k in ActiveProject.model_fields})
            merged = merge_two_projects(existing, candidate)
            upsert_project_db(merged, self.db_path)
            conn.close()
            return merged.id, "merged_exact"

        # Step 2: Fuzzy Name match within same city
        cur.execute("SELECT * FROM active_projects WHERE clean_city = ?", (clean_city,))
        city_projects = cur.fetchall()
        conn.close()

        best_score = 0.0
        best_match_row = None

        for r in city_projects:
            ex_pname = r["clean_project_name"] or ""
            score = max(
                fuzz.token_sort_ratio(clean_pname, ex_pname),
                fuzz.token_set_ratio(clean_pname, ex_pname)
            )
            if score > best_score:
                best_score = score
                best_match_row = r

        if best_score >= 85.0 and best_match_row:
            existing = ActiveProject(**{k: best_match_row[k] for k in best_match_row.keys() if k in ActiveProject.model_fields})
            merged = merge_two_projects(existing, candidate)
            upsert_project_db(merged, self.db_path)
            return merged.id, "merged_fuzzy"

        elif best_score >= 68.0 and best_match_row:
            save_ambiguous_review(
                candidate_type="project",
                existing_id=best_match_row["id"],
                candidate_dict=candidate.model_dump(),
                score=best_score,
                reason=f"Fuzzy project name similarity in {clean_city}: {best_score:.1f}%",
                db_path=self.db_path
            )
            candidate.confidence = "ambiguous_review_flagged"
            new_id = upsert_project_db(candidate, self.db_path)
            return new_id, "ambiguous_review"

        new_id = upsert_project_db(candidate, self.db_path)
        return new_id, "created_new"
