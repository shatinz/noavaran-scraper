import json
import os
import re
from typing import Optional, Tuple, Dict, Any, List
from rapidfuzz import fuzz

from normalizer import (
    normalize_persian_text,
    normalize_phone,
    normalize_email,
    clean_name_for_matching,
    clean_company_for_matching,
    normalize_city,
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

AUTO_MERGE_SCORE_THRESHOLD = 88.0
AMBIGUOUS_SCORE_THRESHOLD = 70.0


def merge_source_urls(url1: Optional[str], url2: Optional[str]) -> str:
    """Combine two semicolon-separated URL strings without duplicates or data loss."""
    urls = []
    seen = set()
    for part in (url1 or "").split(";"):
        u = part.strip()
        if u and u not in seen:
            seen.add(u)
            urls.append(u)
    for part in (url2 or "").split(";"):
        u = part.strip()
        if u and u not in seen:
            seen.add(u)
            urls.append(u)
    return "; ".join(urls)


def merge_two_contacts(existing: ContactEntity, candidate: ContactEntity, merge_reason: str = "fuzzy_match") -> ContactEntity:
    """Merge two contact entities, preserving all URLs and updating missing fields."""
    merged_urls = merge_source_urls(existing.source_url, candidate.source_url)

    # Name: pick longer/more descriptive name
    name = existing.name if len(existing.name.strip()) >= len(candidate.name.strip()) else candidate.name
    # Role: pick more specific role
    role = existing.role or candidate.role
    # Company: pick more descriptive company name
    company = existing.company if len(existing.company.strip()) >= len(candidate.company.strip()) else candidate.company
    city = existing.city or candidate.city
    phone = existing.phone or candidate.phone
    email = existing.email or candidate.email
    social_handle = existing.social_handle or candidate.social_handle

    confidence = existing.confidence
    if merge_reason == "exact_phone" or merge_reason == "exact_email":
        confidence = "verified"
    elif merge_reason == "high_fuzzy":
        confidence = "high_fuzzy" if existing.confidence not in ("verified", "high") else existing.confidence

    last_verified = max(existing.last_verified, candidate.last_verified)

    return ContactEntity(
        id=existing.id,
        entity_type=existing.entity_type or candidate.entity_type,
        name=name.strip(),
        role=role.strip(),
        company=company.strip(),
        city=city.strip(),
        phone=phone.strip(),
        email=email.strip(),
        social_handle=social_handle.strip(),
        source_url=merged_urls,
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
    contact_info = existing.contact_info or candidate.contact_info
    date_found = min(existing.date_found, candidate.date_found)

    return ActiveProject(
        id=existing.id,
        project_name=existing.project_name,
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

        norm_phone = normalize_phone(candidate.phone)
        norm_email = normalize_email(candidate.email)
        clean_name = clean_name_for_matching(candidate.name)
        clean_comp = clean_company_for_matching(candidate.company)

        conn = get_connection(self.db_path)
        cur = conn.cursor()

        # Step 1: Exact Phone Match
        if norm_phone:
            cur.execute("SELECT * FROM contacts WHERE normalized_phone = ? AND normalized_phone != ''", (norm_phone,))
            row = cur.fetchone()
            if row:
                existing = ContactEntity(**{k: row[k] for k in row.keys() if k in ContactEntity.model_fields})
                merged = merge_two_contacts(existing, candidate, merge_reason="exact_phone")
                upsert_contact_db(merged, self.db_path)
                conn.close()
                return merged.id, "merged_phone"

        # Step 2: Exact Email Match
        if norm_email:
            cur.execute("SELECT * FROM contacts WHERE normalized_email = ? AND normalized_email != ''", (norm_email,))
            row = cur.fetchone()
            if row:
                existing = ContactEntity(**{k: row[k] for k in row.keys() if k in ContactEntity.model_fields})
                merged = merge_two_contacts(existing, candidate, merge_reason="exact_email")
                upsert_contact_db(merged, self.db_path)
                conn.close()
                return merged.id, "merged_email"

        # Step 3: Fuzzy Composite Match on Name + Company
        cur.execute("SELECT * FROM contacts")
        all_rows = cur.fetchall()
        conn.close()

        cand_composite = f"{clean_name} {clean_comp}".strip()
        best_score = 0.0
        best_match_row = None
        best_reason = ""

        if len(cand_composite) >= 4:
            for r in all_rows:
                ex_name = r["clean_name"] or ""
                ex_comp = r["clean_company"] or ""
                ex_composite = f"{ex_name} {ex_comp}".strip()

                if not ex_composite:
                    continue

                # RapidFuzz token sorting ratio and set ratio
                sort_ratio = fuzz.token_sort_ratio(cand_composite, ex_composite)
                set_ratio = fuzz.token_set_ratio(cand_composite, ex_composite)
                composite_score = max(sort_ratio, set_ratio)

                # If name matches closely, boost confidence
                name_ratio = fuzz.token_sort_ratio(clean_name, ex_name) if clean_name and ex_name else 0.0
                comp_ratio = fuzz.token_sort_ratio(clean_comp, ex_comp) if clean_comp and ex_comp else 0.0

                score = composite_score
                if name_ratio >= 90.0 and comp_ratio >= 85.0:
                    score = max(score, (name_ratio + comp_ratio) / 2.0)

                if score > best_score:
                    best_score = score
                    best_match_row = r
                    best_reason = f"Composite score: {score:.1f} (sort: {sort_ratio}, set: {set_ratio}, name: {name_ratio}, comp: {comp_ratio})"

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
