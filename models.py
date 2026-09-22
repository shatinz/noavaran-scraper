from datetime import datetime
from enum import Enum
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field

class EntityType(str, Enum):
    OFFICE = "office"
    CONTRACTOR = "contractor"
    STUDENT = "student"
    INDIVIDUAL = "individual"

class ContactEntity(BaseModel):
    id: Optional[str] = None
    entity_type: str = Field(default=EntityType.OFFICE.value, description="office/contractor/student/individual")
    name: str = Field(default="", description="Full person name or lead contact")
    role: str = Field(default="", description="Professional role/title (e.g. Lead Architect, CEO, Student)")
    company: str = Field(default="", description="Office or company name")
    city: str = Field(default="Isfahan", description="City location")
    phone: str = Field(default="", description="Normalized phone number (09xx / 031xx)")
    email: str = Field(default="", description="Normalized email address")
    social_handle: str = Field(default="", description="Telegram / Instagram handle (e.g. @handle)")
    source_url: str = Field(default="", description="Semicolon-separated list of all source URLs discovered")
    confidence: str = Field(default="medium", description="Confidence level (verified, high, medium, high_fuzzy)")
    last_verified: str = Field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d"))

    def to_csv_dict(self) -> Dict[str, str]:
        """Format matching exact contacts.csv specification."""
        return {
            "entity_type (office/contractor/student/individual)": self.entity_type,
            "name": self.name,
            "role": self.role,
            "company": self.company,
            "city": self.city,
            "phone": self.phone,
            "email": self.email,
            "social handle": self.social_handle,
            "source_url": self.source_url,
            "confidence": self.confidence,
            "last_verified": self.last_verified,
        }

class ActiveProject(BaseModel):
    id: Optional[str] = None
    project_name: str = Field(description="Name or title of the active construction project")
    city: str = Field(default="Isfahan", description="Project city")
    scale_scope: str = Field(default="", description="Scale or scope (e.g. 12 floors, 8000 sqm, luxury residential, commercial mall)")
    associated_contractors: str = Field(default="", description="Associated contractor(s) or construction group")
    associated_architects: str = Field(default="", description="Associated architect(s) or design office")
    contact_info: str = Field(default="", description="Phone, email or contact point tied to project")
    source_url: str = Field(default="", description="Semicolon-separated list of source URLs")
    confidence: str = Field(default="medium", description="Confidence level (verified, high, medium)")
    date_found: str = Field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d"))

    def to_csv_dict(self) -> Dict[str, str]:
        """Format matching exact active_projects.csv specification."""
        return {
            "project name": self.project_name,
            "city": self.city,
            "scale/scope": self.scale_scope,
            "associated contractor(s)": self.associated_contractors,
            "associated architect(s)/office": self.associated_architects,
            "contact info": self.contact_info,
            "source URL": self.source_url,
            "confidence": self.confidence,
            "date found": self.date_found,
        }

class RawRecord(BaseModel):
    id: Optional[int] = None
    run_id: str
    source_type: str
    source_url: str
    raw_payload: Dict[str, Any]
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())

class AmbiguousMatchReview(BaseModel):
    id: Optional[int] = None
    candidate_type: str
    existing_id: str
    candidate_data: Dict[str, Any]
    match_score: float
    match_reason: str
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())
