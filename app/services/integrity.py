"""Read-only source fingerprints used to prove later stages never modify earlier ones."""

from __future__ import annotations

import hashlib

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import (
    DocumentExtraction,
    DocumentPage,
    DocumentSection,
    DocumentTable,
    TenderFieldEvidence,
    TenderFieldExtraction,
    TenderFieldValue,
)


def _row(h, row) -> None:
    h.update(repr([getattr(row, c.name) for c in row.__table__.columns]).encode())


def stage3a_digest(s: Session, extraction_id: int) -> str:
    """SHA-256 over a Stage 3A extraction row and all its pages/tables/sections
    (same algorithm as scripts/inspect_tender_fields.py --verify-sources)."""
    h = hashlib.sha256()
    _row(h, s.get(DocumentExtraction, extraction_id))
    for model in (DocumentPage, DocumentTable, DocumentSection):
        for row in s.scalars(select(model).where(model.extraction_id == extraction_id).order_by(model.id)):
            _row(h, row)
    return h.hexdigest()


def stage3b_digest(s: Session, field_extraction_id: int) -> str:
    """SHA-256 over a Stage 3B run row and all its values/evidence."""
    h = hashlib.sha256()
    _row(h, s.get(TenderFieldExtraction, field_extraction_id))
    for model in (TenderFieldValue, TenderFieldEvidence):
        for row in s.scalars(select(model).where(model.field_extraction_id == field_extraction_id).order_by(model.id)):
            _row(h, row)
    return h.hexdigest()
