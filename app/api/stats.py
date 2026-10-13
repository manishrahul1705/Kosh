from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.api.deps import (
    get_db,
    get_document_worker,
    get_ai_analysis_worker,
    get_extraction_worker,
    get_field_extraction_worker,
    get_runner,
    get_scheduler,
)
from app.core.constants import TenderStatus
from app.database.models import DocumentJob, DocumentVersion, Tender, TenderDocument
from app.schemas.collection import StatsOut
from app.services.discovery_service import CollectionRunner, latest_run
from app.services.ai_status import ai_analysis_status
from app.services.extraction_status import extraction_status
from app.services.field_status import field_extraction_status
from app.services.job_status import document_worker_status
from app.utils.dates import as_aware_utc, utcnow

router = APIRouter(prefix="/api", tags=["stats"], dependencies=[Depends(get_current_user)])


@router.get("/stats", response_model=StatsOut)
def stats(
    request: Request,
    db: Session = Depends(get_db),
    runner: CollectionRunner = Depends(get_runner),
    worker=Depends(get_document_worker),
    scheduler=Depends(get_scheduler),
    extraction_worker=Depends(get_extraction_worker),
    field_worker=Depends(get_field_extraction_worker),
    ai_worker=Depends(get_ai_analysis_worker),
) -> StatsOut:
    def count_tender(*where) -> int:
        return db.scalar(select(func.count(Tender.id)).where(*where)) or 0

    def count_other(model, *where) -> int:
        return db.scalar(select(func.count()).select_from(model).where(*where)) or 0

    # Stage 1 metrics
    last = latest_run(db)
    last_ts = None
    if last is not None:
        ts = as_aware_utc(last.finished_at or last.started_at)
        last_ts = ts.isoformat() if ts else None

    # Stage 2 metrics
    documents_total = count_other(TenderDocument)
    document_versions_total = count_other(DocumentVersion)
    failed_jobs = count_other(DocumentJob, DocumentJob.status == "FAILED")
    pending_jobs = count_other(DocumentJob, DocumentJob.status == "PENDING")

    # Tenders without documents (no TenderDocument records)
    tenders_with_docs = db.scalars(
        select(Tender.id).join(TenderDocument, Tender.id == TenderDocument.tender_id, isouter=False)
    ).all()
    total_tenders = count_tender()
    tenders_without_docs = total_tenders - len(set(tenders_with_docs))

    # Documents with versions (successfully downloaded)
    docs_with_versions = count_other(
        TenderDocument,
        TenderDocument.current_version_id.isnot(None)
    )

    worker_status = document_worker_status(db, worker, scheduler)
    ex = extraction_status(db, extraction_worker, scheduler)
    fx = field_extraction_status(db, field_worker, scheduler)
    ai = ai_analysis_status(db, ai_worker, scheduler,
                            settings=getattr(ai_worker, "settings", None) or request.app.state.settings)

    return StatsOut(
        total_tenders=count_tender(),
        ongoing=count_tender(Tender.status == TenderStatus.ONGOING.value),
        closed=count_tender(Tender.status == TenderStatus.CLOSED.value),
        new_last_24h=count_tender(Tender.first_seen_at >= utcnow() - timedelta(hours=24)),
        last_collection=last_ts,
        last_collection_status=last.status if last else None,
        collection_running=runner.is_running(),
        # Stage 2 metrics
        documents_total=documents_total,
        documents_downloaded=docs_with_versions,
        document_versions_total=document_versions_total,
        failed_document_jobs=failed_jobs,
        pending_document_jobs=pending_jobs,
        tenders_without_documents=tenders_without_docs,
        # Stage 2B
        running_document_jobs=worker_status["running_jobs"],
        retry_document_jobs=worker_status["retry_jobs"],
        blocked_document_jobs=worker_status["blocked_jobs"],
        stale_running_document_jobs=worker_status["stale_running_jobs"],
        oldest_pending_document_job_at=worker_status["oldest_pending_job_at"],
        last_successful_document_processing_at=worker_status["last_successful_document_processing_at"],
        document_worker=worker_status,
        # Stage 3A
        extractions_total=ex["extractions_total"],
        extractions_success=ex["extractions_success"],
        extractions_partial=ex["extractions_partial"],
        extractions_failed=ex["extractions_failed"],
        extractions_ocr_required=ex["extractions_ocr_required"],
        extraction_jobs_pending=ex["extraction_jobs_pending"],
        extraction_jobs_running=ex["extraction_jobs_running"],
        extraction_jobs_retry=ex["extraction_jobs_retry"],
        extraction_jobs_failed=ex["extraction_jobs_failed"],
        document_versions_without_extraction=ex["document_versions_without_extraction"],
        pages_extracted=ex["pages_extracted"],
        tables_extracted=ex["tables_extracted"],
        extraction=ex,
        # Stage 3B
        stage3a_extractions_eligible_for_fields=fx["stage3a_extractions_eligible"],
        field_extractions_total=fx["field_extractions_total"],
        field_extractions_success=fx["field_extractions_success"],
        field_extractions_partial=fx["field_extractions_partial"],
        field_extractions_failed=fx["field_extractions_failed"],
        field_extraction_jobs_pending=fx["field_extraction_jobs_pending"],
        field_extraction_jobs_running=fx["field_extraction_jobs_running"],
        stage3a_extractions_unqueued_for_fields=fx["stage3a_extractions_unqueued"],
        fields_extracted=fx["fields_extracted"],
        fields_unknown=fx["fields_unknown"],
        fields_conflicted=fx["fields_conflicted"],
        field_extraction=fx,
        # Stage 3C
        ai_provider_configured=ai["ai_provider_configured"],
        ai_analyses_total=ai["ai_analyses_total"],
        ai_analyses_success=ai["ai_analyses_success"],
        ai_analyses_partial=ai["ai_analyses_partial"],
        ai_analysis_jobs_pending=ai["ai_analysis_jobs_pending"],
        ai_analysis_jobs_running=ai["ai_analysis_jobs_running"],
        ai_analysis_jobs_retry=ai["ai_analysis_jobs_retry"],
        ai_analysis_jobs_failed=ai["ai_analysis_jobs_failed"],
        ai_analysis_jobs_blocked=ai["ai_analysis_jobs_blocked"],
        stage3b_runs_unqueued_for_ai=ai["stage3b_runs_unqueued"],
        ai_requirements_generated=ai["ai_requirements_generated"],
        ai_ambiguities=ai["ai_ambiguities"],
        ai_conflict_flags=ai["ai_conflict_flags"],
        ai_review_flags=ai["ai_review_flags"],
        ai_analysis=ai,
    )
