"""Stage 4: Seller Profile Inspector.

Inspect seller profiles, revisions, attributes, and documents.
"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from datetime import datetime
import json
import os
from typing import Optional, List, Dict, Any

from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.database.models import (
    Seller,
    SellerRevision,
    SellerAttribute,
    SellerDocument,
    EligibilityRun,
    EligibilityRequirementResult,
    EligibilityEvidence
)
from app.database.session import build_engine, build_session_factory
from app.core.config import get_settings
from app.eligibility.utils import calculate_seller_fingerprint


def list_sellers(db: Session, organization_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """List sellers with their active revisions."""
    query = db.query(Seller)
    if organization_id:
        query = query.filter(Seller.organization_id == organization_id)

    sellers = query.order_by(Seller.id.desc()).all()
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


def get_seller(db: Session, seller_id: int) -> Dict[str, Any]:
    """Get detailed seller profile including all revisions."""
    seller = db.get(Seller, seller_id)
    if not seller:
        raise ValueError(f"Seller {seller_id} not found")

    revisions = db.query(SellerRevision).filter(
        SellerRevision.seller_id == seller_id
    ).order_by(SellerRevision.revision_number.desc()).all()

    result = {
        "id": seller.id,
        "name": seller.name,
        "organization_id": seller.organization_id,
        "created_at": seller.created_at.isoformat(),
        "updated_at": seller.updated_at.isoformat(),
        "revisions": []
    }

    for rev in revisions:
        rev_data = {
            "id": rev.id,
            "revision_number": rev.revision_number,
            "fingerprint": rev.fingerprint,
            "comment": rev.comment,
            "is_active": rev.is_active,
            "created_at": rev.created_at.isoformat(),
            "attributes": [],
            "documents": []
        }

        # Get attributes
        for attr in rev.attributes:
            rev_data["attributes"].append({
                "key": attr.key,
                "value_type": attr.value_type,
                "value_text": attr.value_text,
                "value_number": attr.value_number,
                "value_json": attr.value_json,
                "context": attr.context,
                "created_at": attr.created_at.isoformat()
            })

        # Get documents
        for doc in rev.documents:
            rev_data["documents"].append({
                "id": doc.id,
                "document_type": doc.document_type,
                "display_name": doc.display_name,
                "filename": doc.filename,
                "sha256": doc.sha256,
                "storage_path": doc.storage_path,
                "issue_date": doc.issue_date.isoformat() if doc.issue_date else None,
                "expiry_date": doc.expiry_date.isoformat() if doc.expiry_date else None,
                "status": doc.status,
                "created_at": doc.created_at.isoformat()
            })

        result["revisions"].append(rev_data)

    return result


def get_revision(db: Session, revision_id: int) -> Dict[str, Any]:
    """Get detailed revision with attributes and documents."""
    revision = db.get(SellerRevision, revision_id)
    if not revision:
        raise ValueError(f"Revision {revision_id} not found")

    result = {
        "id": revision.id,
        "seller_id": revision.seller_id,
        "revision_number": revision.revision_number,
        "fingerprint": revision.fingerprint,
        "comment": revision.comment,
        "is_active": revision.is_active,
        "created_at": revision.created_at.isoformat(),
        "attributes": [],
        "documents": []
    }

    # Get attributes
    for attr in revision.attributes:
        result["attributes"].append({
            "key": attr.key,
            "value_type": attr.value_type,
            "value_text": attr.value_text,
            "value_number": attr.value_number,
            "value_json": attr.value_json,
            "context": attr.context,
            "created_at": attr.created_at.isoformat()
        })

    # Get documents
    for doc in revision.documents:
        result["documents"].append({
            "id": doc.id,
            "document_type": doc.document_type,
            "display_name": doc.display_name,
            "filename": doc.filename,
            "sha256": doc.sha256,
            "storage_path": doc.storage_path,
            "issue_date": doc.issue_date.isoformat() if doc.issue_date else None,
            "expiry_date": doc.expiry_date.isoformat() if doc.expiry_date else None,
            "status": doc.status,
            "created_at": doc.created_at.isoformat()
        })

    return result


def verify_fingerprint(db: Session, revision_id: int) -> Dict[str, Any]:
    """Verify that the stored fingerprint matches the calculated one."""
    revision = db.get(SellerRevision, revision_id)
    if not revision:
        raise ValueError(f"Revision {revision_id} not found")

    # Build the revision payload
    rev_payload = {
        "attributes": [
            {
                "key": a.key,
                "value_type": a.value_type,
                "value_text": a.value_text,
                "value_number": a.value_number,
                "value_json": a.value_json
            } for a in revision.attributes
        ],
        "documents": [
            {
                "document_type": d.document_type,
                "filename": d.filename
            } for d in revision.documents
        ],
        "created_at": revision.created_at.isoformat()
    }

    calculated_fingerprint = calculate_seller_fingerprint(rev_payload)

    return {
        "revision_id": revision_id,
        "stored_fingerprint": revision.fingerprint,
        "calculated_fingerprint": calculated_fingerprint,
        "match": revision.fingerprint == calculated_fingerprint
    }


def main():
    parser = argparse.ArgumentParser(description="Inspect seller profiles")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # List sellers
    list_parser = subparsers.add_parser("list", help="List sellers")
    list_parser.add_argument("--organization-id", help="Filter by organization ID")

    # Get seller details
    get_parser = subparsers.add_parser("get", help="Get seller details")
    get_parser.add_argument("seller_id", type=int, help="Seller ID")

    # Get revision details
    rev_parser = subparsers.add_parser("revision", help="Get revision details")
    rev_parser.add_argument("revision_id", type=int, help="Revision ID")

    # Verify fingerprint
    verify_parser = subparsers.add_parser("verify", help="Verify revision fingerprint")
    verify_parser.add_argument("revision_id", type=int, help="Revision ID")

    args = parser.parse_args()

    settings = get_settings()
    engine = build_engine(settings.resolved_database_url)
    session_factory = build_session_factory(engine)

    with session_factory() as db:
        if args.command == "list":
            sellers = list_sellers(db, args.organization_id)
            print(json.dumps(sellers, indent=2))
        elif args.command == "get":
            seller = get_seller(db, args.seller_id)
            print(json.dumps(seller, indent=2))
        elif args.command == "revision":
            revision = get_revision(db, args.revision_id)
            print(json.dumps(revision, indent=2))
        elif args.command == "verify":
            result = verify_fingerprint(db, args.revision_id)
            print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
