"""Builders for analysed tenders and seller profiles (matching + portal tests).

A tender built here has one processed main document (Stage 2), a current
Stage 3A extraction, a COMPLETE reference scan and a current Stage 3B field
extraction with deterministic requirement fields. That is exactly what the
eligibility engine consumes, with no AI and no network involved.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from app.database.models import (
    DocumentExtraction,
    DocumentReferenceScan,
    DocumentVersion,
    Seller,
    SellerAttribute,
    SellerDocument,
    SellerRevision,
    Tender,
    TenderDocument,
    TenderFieldExtraction,
    TenderFieldValue,
)
from app.database.auth_models import AppUser, SellerMembership
from app.documents.references import RULES_VERSION
from app.services.status_service import apply_current_status
from app.utils.dates import utcnow

DEFAULT_FIELDS = {
    # field_name: (tri_state, value_number)
    "turnover_required": ("TRUE", 20_000_000.0),   # Rs 2 crore
    "experience_required": ("TRUE", 3.0),          # 3 years
    "iso_9001_required": ("TRUE", None),
}


def make_tender(db, *, bid: str, title: str = "Supply of Laptop", category: str = "Laptop - Notebook",
                fields: dict | None = None, deadline_days: float = 7, source_status: str = "ONGOING",
                buyer: str = "Ministry of Education", storage_path: str | None = None) -> Tender:
    now = utcnow()
    tender = Tender(bid_number=bid, title=title, category=category, buyer_name=buyer, status=source_status,
                    bid_end_at=now + timedelta(days=deadline_days), published_at=now - timedelta(days=1),
                    source_fingerprint=f"fp-{bid}", first_seen_at=now, last_seen_at=now)
    db.add(tender)
    db.flush()
    apply_current_status(db, tender, now=now)
    doc = TenderDocument(tender_id=tender.id, document_key="main_bid", document_type="MAIN_BID",
                         display_name="Bid Document", original_filename="GeM-Bidding.pdf", is_active=True)
    db.add(doc)
    db.flush()
    ver = DocumentVersion(document_id=doc.id, version_number=1, sha256=f"{tender.id:064d}",
                          validation_status="VALID", extension="pdf", storage_path=storage_path,
                          mime_type="application/pdf", file_size=1234)
    db.add(ver)
    db.flush()
    doc.current_version_id = ver.id
    ext = DocumentExtraction(document_version_id=ver.id, document_id=doc.id, tender_id=tender.id,
                             extractor_name="stage3a-v1", extractor_version="1.0.0", parser_version="1.0.0",
                             status="SUCCESS", quality_status="GOOD", is_current=True)
    db.add(ext)
    db.flush()
    db.add(DocumentReferenceScan(document_version_id=ver.id, status="COMPLETE", rules_version=RULES_VERSION,
                                 scanned_at=now))
    fx = TenderFieldExtraction(stage3a_extraction_id=ext.id, document_version_id=ver.id, document_id=doc.id,
                               tender_id=tender.id, bid_number=bid, document_type="MAIN_BID", version_number=1,
                               extractor_name="stage3b-v1", extractor_version="1.0.0", status="SUCCESS",
                               is_current=True)
    db.add(fx)
    db.flush()
    for name, (tri, number) in (DEFAULT_FIELDS if fields is None else fields).items():
        db.add(TenderFieldValue(field_extraction_id=fx.id, tender_id=tender.id, field_name=name,
                                field_group="ELIGIBILITY", value_type="BOOLEAN", status="RESOLVED",
                                tri_state=tri, value_number=number))
    db.commit()
    return tender


def make_seller(db, *, name: str, terms: str | None = "Laptop", turnover: float | None = 30_000_000.0,
                years: float | None = 5.0, iso: bool = True, oem: bool | None = None,
                owner_subject: str | None = None, role: str = "OWNER") -> Seller:
    seller = Seller(name=name)
    db.add(seller)
    db.flush()
    rev = SellerRevision(seller_id=seller.id, revision_number=1, fingerprint=f"rev-{name}", is_active=True,
                         created_at=datetime.utcnow())
    db.add(rev)
    db.flush()
    attrs = []
    if terms is not None:
        attrs.append(("product_category", "TEXT", terms, None))
    if turnover is not None:
        attrs.append(("annual_turnover", "NUMBER", None, turnover))
    if years is not None:
        attrs.append(("years_of_experience", "NUMBER", None, years))
    if oem is not None:
        attrs.append(("oem_authorized", "BOOLEAN", "TRUE" if oem else "FALSE", None))
    for key, vtype, text, number in attrs:
        db.add(SellerAttribute(revision_id=rev.id, key=key, value_type=vtype, value_text=text, value_number=number))
    if iso:
        db.add(SellerDocument(revision_id=rev.id, document_type="ISO", display_name="ISO 9001", filename="iso.pdf",
                              expiry_date=datetime.utcnow() + timedelta(days=365), status="VERIFIED"))
    if owner_subject:
        user = AppUser(supabase_user_id=owner_subject)
        db.add(user)
        db.flush()
        db.add(SellerMembership(user_id=user.id, seller_id=seller.id, role=role, status="ACTIVE"))
    db.commit()
    return seller


def new_revision(db, seller: Seller, *, changes: dict[str, tuple[str, str | None, float | None]]) -> SellerRevision:
    """Copy the active revision, apply attribute changes, activate it (a profile edit)."""
    old = db.query(SellerRevision).filter_by(seller_id=seller.id, is_active=True).one()
    old.is_active = False
    rev = SellerRevision(seller_id=seller.id, revision_number=old.revision_number + 1,
                         fingerprint=f"{old.fingerprint}+", is_active=True, created_at=datetime.utcnow())
    db.add(rev)
    db.flush()
    for a in old.attributes:
        if a.key not in changes:
            db.add(SellerAttribute(revision_id=rev.id, key=a.key, value_type=a.value_type, value_text=a.value_text,
                                   value_number=a.value_number, value_json=a.value_json))
    for key, (vtype, text, number) in changes.items():
        db.add(SellerAttribute(revision_id=rev.id, key=key, value_type=vtype, value_text=text, value_number=number))
    for d in old.documents:
        db.add(SellerDocument(revision_id=rev.id, document_type=d.document_type, display_name=d.display_name,
                              filename=d.filename, expiry_date=d.expiry_date, status=d.status))
    db.commit()
    return rev
