"""Stage 4: Eligibility Schemas.

Pydantic models for API request/response.
"""

from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field

from app.eligibility.constants import (
    EligibilityStatus,
    RequirementStatus,
    RequirementType,
    RelaxationRule,
    DocumentType,
    AttributeKey
)


class EligibilityEvaluationIn(BaseModel):
    """Input for eligibility evaluation."""
    tender_id: int = Field(..., description="ID of the tender to evaluate")
    seller_id: int = Field(..., description="ID of the seller to evaluate")


class EligibilityRunOut(BaseModel):
    """Eligibility run output."""
    id: int
    tender_id: int
    seller_id: int
    seller_revision_id: int
    corpus_fingerprint: str
    engine_version: str
    status: EligibilityStatus
    summary: Optional[str]
    passed_count: int
    failed_count: int
    review_count: int
    insufficient_count: int
    evaluated_at: datetime
    created_at: datetime

    class Config:
        from_attributes = True


class EligibilityRequirementResultOut(BaseModel):
    """Eligibility requirement result output."""
    id: int
    run_id: int
    requirement_name: str
    requirement_type: RequirementType
    status: RequirementStatus
    reason: Optional[str]
    relaxation_applied: Optional[RelaxationRule]
    stage3b_field_id: Optional[int]
    ai_requirement_id: Optional[int]
    created_at: datetime

    class Config:
        from_attributes = True


class EligibilityEvidenceOut(BaseModel):
    """Eligibility evidence output."""
    id: int
    result_id: int
    seller_attribute_id: Optional[int]
    seller_document_id: Optional[int]
    evidence_value: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


class SellerAttributeOut(BaseModel):
    """Seller attribute output."""
    id: int
    revision_id: int
    key: AttributeKey
    value_type: str
    value_text: Optional[str]
    value_number: Optional[float]
    value_json: Optional[str]
    context: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


class SellerDocumentOut(BaseModel):
    """Seller document output."""
    id: int
    revision_id: int
    document_type: DocumentType
    display_name: str
    filename: str
    sha256: Optional[str]
    storage_path: Optional[str]
    issue_date: Optional[datetime]
    expiry_date: Optional[datetime]
    status: str
    created_at: datetime

    class Config:
        from_attributes = True


class SellerRevisionOut(BaseModel):
    """Seller revision output."""
    id: int
    seller_id: int
    revision_number: int
    fingerprint: str
    comment: Optional[str]
    is_active: bool
    created_at: datetime
    attributes: List[SellerAttributeOut]
    documents: List[SellerDocumentOut]

    class Config:
        from_attributes = True
