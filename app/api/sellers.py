"""Stage 4: Sellers API.

Endpoints for managing sellers, revisions, attributes, and documents.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Form
from sqlalchemy.orm import Session
from typing import Optional, List, Dict, Any
from datetime import datetime
import json
import os
import re
from hashlib import sha256

from app.api.deps import get_db
from app.api.auth import get_current_user
from app.api.seller_authorization import (
    AuthorizedSeller,
    require_seller_read,
    require_seller_edit,
    resolve_app_user,
)
from app.core.supabase_auth import AuthenticatedIdentity
from app.database.auth_models import AppUser, SellerMembership
from app.database.models import (
    Seller,
    SellerRevision,
    SellerAttribute,
    SellerDocument
)
from app.schemas.eligibility import SellerRevisionOut
from app.eligibility.utils import calculate_seller_fingerprint

router = APIRouter(prefix="/api/sellers", tags=["sellers"])

_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_VALUE_TYPES = {"TEXT", "NUMBER", "BOOLEAN", "JSON"}
_MAX_TEXT = 5000
_MAX_JSON = 20000


def _validate_attribute(key, value_type, value_text, value_number, value_json, context, comment) -> None:
    if not _KEY_RE.match(key or ""):
        raise HTTPException(status_code=422, detail="key must be lower_snake_case (max 64 characters)")
    if value_type not in _VALUE_TYPES:
        raise HTTPException(status_code=422, detail=f"value_type must be one of {sorted(_VALUE_TYPES)}")
    for name, value, limit in (("value_text", value_text, _MAX_TEXT), ("context", context, _MAX_TEXT),
                               ("comment", comment, 500), ("value_json", value_json, _MAX_JSON)):
        if value is not None and len(value) > limit:
            raise HTTPException(status_code=422, detail=f"{name} is too long (max {limit} characters)")
    if value_type == "NUMBER" and (value_number is None or value_number != value_number
                                   or value_number in (float("inf"), float("-inf"))):
        raise HTTPException(status_code=422, detail="value_number must be a finite number for NUMBER attributes")
    if value_type == "BOOLEAN" and (value_text or "").upper() not in ("TRUE", "FALSE"):
        raise HTTPException(status_code=422, detail="value_text must be TRUE or FALSE for BOOLEAN attributes")
    if value_type == "JSON":
        try:
            json.loads(value_json or "")
        except ValueError:
            raise HTTPException(status_code=422, detail="value_json must be valid JSON") from None
    if value_type == "TEXT" and not (value_text or "").strip():
        raise HTTPException(status_code=422, detail="value_text is required for TEXT attributes")


@router.post("", response_model=Dict[str, Any])
def create_seller(
    name: str = Form(...),
    organization_id: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    identity: AuthenticatedIdentity = Depends(get_current_user),
) -> Dict[str, Any]:
    """Create a new seller for the authenticated application user."""
    app_user = resolve_app_user(identity, db)
    seller = Seller(
        name=name,
        organization_id=organization_id,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow()
    )
    db.add(seller)
    db.flush()

    # Create initial empty revision
    revision = SellerRevision(
        seller_id=seller.id,
        revision_number=1,
        fingerprint=calculate_seller_fingerprint({"created_at": datetime.utcnow().isoformat()}),
        comment="Initial revision",
        is_active=True,
        created_at=datetime.utcnow()
    )
    db.add(revision)
    db.add(SellerMembership(
        user_id=app_user.id,
        seller_id=seller.id,
        role="OWNER",
        status="ACTIVE",
    ))
    db.commit()

    return {
        "id": seller.id,
        "name": seller.name,
        "organization_id": seller.organization_id,
        "active_revision_id": revision.id,
        "revision_number": revision.revision_number,
        "fingerprint": revision.fingerprint,
        "created_at": seller.created_at.isoformat()
    }


@router.get("", response_model=List[Dict[str, Any]])
def list_sellers(
    organization_id: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    identity: AuthenticatedIdentity = Depends(get_current_user),
) -> List[Dict[str, Any]]:
    """List sellers accessible to the authenticated user."""
    app_user = resolve_app_user(identity, db)
    query = (
        db.query(Seller)
        .join(
            SellerMembership,
            SellerMembership.seller_id == Seller.id,
        )
        .filter(
            SellerMembership.user_id == app_user.id,
            SellerMembership.status == "ACTIVE",
        )
    )
    if organization_id:
        query = query.filter(Seller.organization_id == organization_id)

    sellers = (query.order_by(Seller.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all())

    result = []
    for s in sellers:
        active_rev = db.query(SellerRevision).filter(
            SellerRevision.seller_id == s.id,
            SellerRevision.is_active == True
        ).first()

        result.append({
            "id": s.id,
            "name": s.name,
            "organization_id": s.organization_id,
            "active_revision_id": active_rev.id if active_rev else None,
            "revision_number": active_rev.revision_number if active_rev else None,
            "fingerprint": active_rev.fingerprint if active_rev else None,
            "created_at": s.created_at.isoformat()
        })

    return result


@router.get("/{seller_id}", response_model=Dict[str, Any])
def get_seller(
    seller_id: int,
    db: Session = Depends(get_db),
    authorization: AuthorizedSeller = Depends(require_seller_read),
) -> Dict[str, Any]:
    """Get seller profile details including active revision."""
    seller = db.get(Seller, seller_id)
    if not seller:
        raise HTTPException(status_code=404, detail="Seller not found")

    active_rev = db.query(SellerRevision).filter(
        SellerRevision.seller_id == seller.id,
        SellerRevision.is_active == True
    ).first()

    return {
        "id": seller.id,
        "name": seller.name,
        "organization_id": seller.organization_id,
        "active_revision": {
            "id": active_rev.id,
            "revision_number": active_rev.revision_number,
            "fingerprint": active_rev.fingerprint,
            "comment": active_rev.comment,
            "created_at": active_rev.created_at.isoformat(),
            "attributes": [
                {
                    "key": a.key,
                    "value_type": a.value_type,
                    "value_text": a.value_text,
                    "value_number": a.value_number,
                    "value_json": a.value_json,
                    "context": a.context
                } for a in active_rev.attributes
            ],
            "documents": [
                {
                    "document_type": d.document_type,
                    "display_name": d.display_name,
                    "filename": d.filename,
                    "issue_date": d.issue_date.isoformat() if d.issue_date else None,
                    "expiry_date": d.expiry_date.isoformat() if d.expiry_date else None,
                    "status": d.status
                } for d in active_rev.documents
            ]
        } if active_rev else None
    }


@router.post("/{seller_id}/attributes", response_model=Dict[str, Any])
def add_seller_attribute(
    seller_id: int,
    key: str = Form(...),
    value_type: str = Form(...), # TEXT, NUMBER, JSON
    value_text: Optional[str] = Form(None),
    value_number: Optional[float] = Form(None),
    value_json: Optional[str] = Form(None),
    context: Optional[str] = Form(None),
    comment: Optional[str] = Form("Added attribute"),
    db: Session = Depends(get_db),
    authorization: AuthorizedSeller = Depends(require_seller_edit),
) -> Dict[str, Any]:
    """Add or update an attribute on a seller profile.

    This creates a new active revision for the seller. Inputs are validated so a profile
    cannot store oversized or malformed values. Matching picks up the new revision on its
    next run, or immediately via POST /api/portal/sellers/{id}/matches/refresh.
    """
    _validate_attribute(key, value_type, value_text, value_number, value_json, context, comment)
    seller = db.get(Seller, seller_id)
    if not seller:
        raise HTTPException(status_code=404, detail="Seller not found")

    # Get latest revision number
    latest_rev = db.query(SellerRevision).filter(
        SellerRevision.seller_id == seller_id
    ).order_by(SellerRevision.revision_number.desc()).first()

    next_rev_num = (latest_rev.revision_number + 1) if latest_rev else 1

    # Deactivate current revision
    if latest_rev:
        latest_rev.is_active = False

    # Copy attributes and documents from latest revision
    new_attrs = []
    if latest_rev:
        for a in latest_rev.attributes:
            if a.key != key: # Overwrite key if present
                new_attrs.append(a)

    # Add new/updated attribute
    new_attr_data = {
        "key": key,
        "value_type": value_type,
        "value_text": value_text,
        "value_number": value_number,
        "value_json": value_json,
        "context": context
    }

    # Calculate fingerprint
    rev_payload = {
        "attributes": [
            {
                "key": a.key,
                "value_type": a.value_type,
                "value_text": a.value_text,
                "value_number": a.value_number,
                "value_json": a.value_json
            } for a in new_attrs
        ] + [new_attr_data],
        "documents": [
            {
                "document_type": d.document_type,
                "filename": d.filename
            } for d in (latest_rev.documents if latest_rev else [])
        ],
        "created_at": datetime.utcnow().isoformat()
    }
    fingerprint = calculate_seller_fingerprint(rev_payload)

    # Create new revision
    new_rev = SellerRevision(
        seller_id=seller_id,
        revision_number=next_rev_num,
        fingerprint=fingerprint,
        comment=comment,
        is_active=True,
        created_at=datetime.utcnow()
    )
    db.add(new_rev)
    db.flush()

    # Copy old attributes
    for a in new_attrs:
        db.add(SellerAttribute(
            revision_id=new_rev.id,
            key=a.key,
            value_type=a.value_type,
            value_text=a.value_text,
            value_number=a.value_number,
            value_json=a.value_json,
            context=a.context,
            created_at=datetime.utcnow()
        ))

    # Add the new attribute
    db.add(SellerAttribute(
        revision_id=new_rev.id,
        key=key,
        value_type=value_type,
        value_text=value_text,
        value_number=value_number,
        value_json=value_json,
        context=context,
        created_at=datetime.utcnow()
    ))

    # Copy documents
    if latest_rev:
        for d in latest_rev.documents:
            db.add(SellerDocument(
                revision_id=new_rev.id,
                document_type=d.document_type,
                display_name=d.display_name,
                filename=d.filename,
                sha256=d.sha256,
                storage_path=d.storage_path,
                issue_date=d.issue_date,
                expiry_date=d.expiry_date,
                status=d.status,
                created_at=datetime.utcnow()
            ))

    db.commit()

    return {
        "seller_id": seller_id,
        "revision_id": new_rev.id,
        "revision_number": new_rev.revision_number,
        "fingerprint": new_rev.fingerprint,
        "key": key,
        "status": "updated"
    }
