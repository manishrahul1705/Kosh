"""Stage 2 documents API endpoints.

ROUTE ORDER MATTERS: Starlette matches routes in declaration order, so every
static path (``/jobs``, ``/worker``, ``/retry-failed``, ``/tenders/...``) is
declared BEFORE the dynamic ``/{document_id}`` routes. Otherwise
``GET /api/documents/jobs`` is captured by ``/{document_id}`` and fails with
"Input should be a valid integer" (Stage 2B regression test guards this).
"""

from __future__ import annotations

import logging
import math
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.api.deps import get_db, get_document_worker, get_scheduler
from app.api.file_access import stored_file_response
from app.api.platform_authorization import require_document_jobs_operator
from app.core.config import get_settings
from app.database.models import DocumentJob, DocumentVersion, Tender, TenderDocument
from app.documents.job_queue import enqueue_job
from app.schemas.documents import DocumentJobOut, DocumentJobReason, DocumentJobStatus, DocumentOut
from app.services.job_status import document_worker_status
from app.utils.dates import utcnow

logger = logging.getLogger("app.api.documents")
router = APIRouter(prefix="/api/documents", tags=["documents"])


# ===========================================================================
# Static routes (must stay above /{document_id})
# ===========================================================================
@router.get("/", response_model=dict)
def list_documents(
    tender_id: Optional[int] = Query(None, description="Filter by tender ID"),
    document_type: Optional[str] = Query(None, description="Filter by document type"),
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    db: Session = Depends(get_db),
    _identity=Depends(get_current_user),
) -> dict:
    """List all documents with optional filtering."""
    stmt = select(TenderDocument)

    if tender_id is not None:
        stmt = stmt.where(TenderDocument.tender_id == tender_id)
    if document_type is not None:
        stmt = stmt.where(TenderDocument.document_type == document_type)
    if is_active is not None:
        stmt = stmt.where(TenderDocument.is_active == is_active)

    # Count total
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0

    # Paginate
    rows = db.scalars(
        stmt.order_by(TenderDocument.discovered_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()

    items = [DocumentOut.model_validate(r) for r in rows]

    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": math.ceil(total / page_size) if total else 0,
    }


@router.get("/jobs", response_model=dict)
def list_document_jobs(
    tender_id: Optional[int] = Query(None, description="Filter by tender ID"),
    status: Optional[str] = Query(None, description="Filter by job status"),
    reason: Optional[str] = Query(None, description="Filter by job reason (NEW_TENDER, PERIODIC_REFRESH, ...)"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    _identity=Depends(get_current_user),
) -> dict:
    """List document processing jobs."""
    stmt = select(DocumentJob)

    if tender_id is not None:
        stmt = stmt.where(DocumentJob.tender_id == tender_id)
    if status is not None:
        stmt = stmt.where(DocumentJob.status == status)
    if reason is not None:
        stmt = stmt.where(DocumentJob.reason == reason)

    # Count total
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0

    # Paginate
    rows = db.scalars(
        stmt.order_by(DocumentJob.updated_at.desc(), DocumentJob.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()

    items = [DocumentJobOut.model_validate(r) for r in rows]

    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": math.ceil(total / page_size) if total else 0,
    }


@router.get("/jobs/{job_id}", response_model=DocumentJobOut)
def get_document_job(
    job_id: int,
    db: Session = Depends(get_db),
    _identity=Depends(get_current_user),
) -> DocumentJobOut:
    """Get a specific document job."""
    job = db.scalar(select(DocumentJob).where(DocumentJob.id == job_id))
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return DocumentJobOut.model_validate(job)


@router.get("/worker", response_model=dict)
def get_document_worker_status(
    db: Session = Depends(get_db),
    worker=Depends(get_document_worker),
    scheduler=Depends(get_scheduler),
    _identity=Depends(get_current_user),
) -> dict:
    """Stage 2B worker / queue health (same data as /api/stats document_worker block)."""
    return document_worker_status(db, worker, scheduler)


@router.post("/retry-failed")
def retry_failed_downloads(
    include_blocked: bool = Query(False, description="Also re-queue tenders whose latest job is BLOCKED"),
    db: Session = Depends(get_db),
    _operator = Depends(require_document_jobs_operator),
) -> dict:
    """Re-queue tenders whose LATEST job ended FAILED or PARTIAL_SUCCESS.

    A new job (reason RETRY) is queued per tender; old job rows are kept as
    history. Tenders that already have a queued/running job are not duplicated.
    BLOCKED tenders are only included when explicitly requested.
    """
    statuses = [DocumentJobStatus.FAILED.value, DocumentJobStatus.PARTIAL_SUCCESS.value]
    if include_blocked:
        statuses.append(DocumentJobStatus.BLOCKED.value)
    latest = (
        select(DocumentJob.tender_id, func.max(DocumentJob.id).label("job_id"))
        .group_by(DocumentJob.tender_id)
        .subquery()
    )
    tender_ids = db.scalars(
        select(DocumentJob.tender_id)
        .join(latest, latest.c.job_id == DocumentJob.id)
        .where(DocumentJob.status.in_(statuses))
    ).all()

    count = 0
    now = utcnow()
    for tender_id in tender_ids:
        if enqueue_job(db, tender_id, DocumentJobReason.RETRY, now=now).created:
            count += 1
    db.commit()
    return {"retried": count}


@router.post("/tenders/{tender_id}/documents/refresh")
def refresh_tender_documents(
    tender_id: int,
    db: Session = Depends(get_db),
    _operator = Depends(require_document_jobs_operator),
) -> dict:
    """Manually queue a document refresh (reason MANUAL) for a tender.

    Idempotent: if a job is already queued for the tender, it is returned.
    """
    tender = db.scalar(select(Tender).where(Tender.id == tender_id))
    if not tender:
        raise HTTPException(status_code=404, detail="Tender not found")

    result = enqueue_job(db, tender_id, DocumentJobReason.MANUAL)
    db.commit()

    if not result.created:
        return {
            "message": "Document job already in progress",
            "job_id": result.job_id,
            "status": result.job.status if result.job is not None else None,
        }

    return {
        "message": "Document refresh queued",
        "job_id": result.job_id,
        "status": result.job.status,
    }


@router.get("/tenders/{tender_id}/documents")
def list_tender_documents(
    tender_id: int,
    db: Session = Depends(get_db),
    _identity=Depends(get_current_user),
) -> dict:
    """Get all documents for a tender."""
    tender = db.scalar(select(Tender).where(Tender.id == tender_id))
    if not tender:
        raise HTTPException(status_code=404, detail="Tender not found")

    docs = db.scalars(
        select(TenderDocument)
        .where(TenderDocument.tender_id == tender_id)
        .order_by(TenderDocument.document_type)
    ).all()

    return {
        "tender_id": tender_id,
        "bid_number": tender.bid_number,
        "documents": [DocumentOut.model_validate(d) for d in docs],
        "count": len(docs),
    }


# ===========================================================================
# Dynamic /{document_id} routes (keep LAST)
# ===========================================================================
@router.get("/{document_id}", response_model=DocumentOut)
def get_document(
    document_id: int,
    db: Session = Depends(get_db),
    _identity=Depends(get_current_user),
) -> DocumentOut:
    """Get a specific document with all versions and events."""
    doc = db.scalar(select(TenderDocument).where(TenderDocument.id == document_id))
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return DocumentOut.model_validate(doc)


@router.get("/{document_id}/versions", response_model=dict)
def list_document_versions(
    document_id: int,
    db: Session = Depends(get_db),
    _identity=Depends(get_current_user),
) -> dict:
    """List all versions of a document."""
    doc = db.scalar(select(TenderDocument).where(TenderDocument.id == document_id))
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    versions = db.scalars(
        select(DocumentVersion)
        .where(DocumentVersion.document_id == document_id)
        .order_by(DocumentVersion.version_number)
    ).all()

    return {
        "document_id": document_id,
        "versions": [
            {
                "id": v.id,
                "version_number": v.version_number,
                "sha256": v.sha256,
                "file_size": v.file_size,
                "mime_type": v.mime_type,
                "downloaded_at": v.downloaded_at,
                "validation_status": v.validation_status,
            }
            for v in versions
        ],
    }


@router.get("/{document_id}/download-version/{version_id}")
def download_document_version(
    document_id: int,
    version_id: int,
    db: Session = Depends(get_db),
    settings = Depends(get_settings),
    _identity=Depends(get_current_user),
):
    """Safely download a specific document version.

    Security: Uses database ID lookup to prevent path traversal.
    """
    # Verify document exists
    doc = db.scalar(select(TenderDocument).where(TenderDocument.id == document_id))
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    # Verify version exists and belongs to document
    version = db.scalar(
        select(DocumentVersion).where(
            (DocumentVersion.id == version_id)
            & (DocumentVersion.document_id == document_id)
        )
    )
    if not version:
        raise HTTPException(status_code=404, detail="Version not found")

    return stored_file_response(settings.resolved_document_storage_path, version)
