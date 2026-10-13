"""Database-enforced platform operator authorization."""

from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.api.deps import get_db
from app.api.seller_authorization import resolve_app_user
from app.core.supabase_auth import AuthenticatedIdentity
from app.database.platform_auth_models import PlatformOperatorGrant


DOCUMENT_JOBS_MANAGE = "DOCUMENT_JOBS_MANAGE"


def authorize_platform_operator(
    identity: AuthenticatedIdentity,
    db: Session,
    permission: str,
) -> PlatformOperatorGrant:
    """Require an explicitly granted, active platform permission."""

    user = resolve_app_user(identity, db)

    grant = (
        db.query(PlatformOperatorGrant)
        .filter(
            PlatformOperatorGrant.user_id == user.id,
            PlatformOperatorGrant.permission == permission,
            PlatformOperatorGrant.status == "ACTIVE",
        )
        .one_or_none()
    )

    if grant is None:
        raise HTTPException(
            status_code=403,
            detail="Platform operator access denied",
        )

    return grant


def require_document_jobs_operator(
    db: Session = Depends(get_db),
    identity: AuthenticatedIdentity = Depends(get_current_user),
) -> PlatformOperatorGrant:
    """Authorize management of shared document-processing jobs."""

    return authorize_platform_operator(
        identity=identity,
        db=db,
        permission=DOCUMENT_JOBS_MANAGE,
    )


TENDER_FIELDS_MANAGE = "TENDER_FIELDS_MANAGE"
AI_ANALYSIS_MANAGE = "AI_ANALYSIS_MANAGE"
COLLECTION_RUN_MANAGE = "COLLECTION_RUN_MANAGE"


def require_tender_fields_operator(
    db: Session = Depends(get_db),
    identity: AuthenticatedIdentity = Depends(get_current_user),
) -> PlatformOperatorGrant:
    """Require explicit permission to manage tender-field extraction."""
    return authorize_platform_operator(
        identity=identity,
        db=db,
        permission=TENDER_FIELDS_MANAGE,
    )


def require_ai_analysis_operator(
    db: Session = Depends(get_db),
    identity: AuthenticatedIdentity = Depends(get_current_user),
) -> PlatformOperatorGrant:
    """Require explicit permission to manage AI-analysis jobs."""
    return authorize_platform_operator(
        identity=identity,
        db=db,
        permission=AI_ANALYSIS_MANAGE,
    )


def require_collection_operator(
    db: Session = Depends(get_db),
    identity: AuthenticatedIdentity = Depends(get_current_user),
) -> PlatformOperatorGrant:
    """Require explicit permission to trigger manual collection."""
    return authorize_platform_operator(
        identity=identity,
        db=db,
        permission=COLLECTION_RUN_MANAGE,
    )

TENDER_ANALYSIS_READ = "TENDER_ANALYSIS_READ"


def require_tender_analysis_reader(
    db: Session = Depends(get_db),
    identity: AuthenticatedIdentity = Depends(get_current_user),
) -> PlatformOperatorGrant:
    """Require explicit read-only permission for tender analysis results."""
    return authorize_platform_operator(
        identity=identity,
        db=db,
        permission=TENDER_ANALYSIS_READ,
    )
