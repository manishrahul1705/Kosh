"""Stage 3A operational status for /health, /api/stats and /api/extractions/worker."""

from __future__ import annotations

from sqlalchemy import and_, exists, func, select
from sqlalchemy.orm import Session

from app.database.models import (
    DocumentExtraction,
    DocumentPage,
    DocumentSection,
    DocumentTable,
    DocumentVersion,
    ExtractionJob,
)
from app.extraction.constants import EXTRACTOR_VERSION, ExtractionJobStatus, ExtractionStatus
from app.utils.dates import as_aware_utc


def _iso(dt):
    a = as_aware_utc(dt)
    return a.isoformat() if a else None


def extraction_status(db: Session, worker=None, scheduler=None) -> dict:
    settings = getattr(worker, "settings", None)
    current = and_(DocumentExtraction.is_current.is_(True), DocumentExtraction.extractor_version == EXTRACTOR_VERSION)

    ext_counts = {s.value: 0 for s in ExtractionStatus}
    for status, n in db.execute(select(DocumentExtraction.status, func.count())
                                .where(current).group_by(DocumentExtraction.status)).all():
        ext_counts[status] = n
    job_counts = {s.value: 0 for s in ExtractionJobStatus}
    for status, n in db.execute(select(ExtractionJob.status, func.count()).group_by(ExtractionJob.status)).all():
        job_counts[status] = n

    has_current = exists().where(and_(DocumentExtraction.document_version_id == DocumentVersion.id, current))
    has_job = exists().where(ExtractionJob.document_version_id == DocumentVersion.id)
    valid = DocumentVersion.validation_status == "VALID"
    without = db.scalar(select(func.count(DocumentVersion.id)).where(valid, ~has_current)) or 0
    unqueued = db.scalar(select(func.count(DocumentVersion.id)).where(valid, ~has_current, ~has_job)) or 0
    current_ids = select(DocumentExtraction.id).where(current)
    pages = db.scalar(select(func.count(DocumentPage.id)).where(DocumentPage.extraction_id.in_(current_ids))) or 0
    tables = db.scalar(select(func.count(DocumentTable.id)).where(DocumentTable.extraction_id.in_(current_ids))) or 0
    sections = db.scalar(select(func.count(DocumentSection.id))
                         .where(DocumentSection.extraction_id.in_(current_ids))) or 0
    last_completed = db.scalar(select(func.max(DocumentExtraction.completed_at)))
    last_job = db.execute(select(ExtractionJob.id, ExtractionJob.document_version_id, ExtractionJob.status,
                                 ExtractionJob.outcome, ExtractionJob.finished_at)
                          .where(ExtractionJob.finished_at.is_not(None))
                          .order_by(ExtractionJob.finished_at.desc(), ExtractionJob.id.desc()).limit(1)).first()
    last_outcome = getattr(worker, "last_outcome", None) or (
        {"job_id": last_job.id, "document_version_id": last_job.document_version_id, "status": last_job.status,
         "outcome": last_job.outcome, "finished_at": _iso(last_job.finished_at)} if last_job else None)
    sched_running = bool(scheduler is not None and scheduler.running
                         and getattr(scheduler, "extraction_jobs_enabled", False))
    return {
        "extraction_worker_enabled": bool(settings and settings.extraction_worker_enabled),
        "extraction_worker_running": bool(worker is not None and worker.is_busy()),
        "extraction_scheduler_running": sched_running,
        "next_extraction_worker_run": scheduler.next_run_time("extraction_worker") if sched_running else None,
        "current_extraction_job_id": getattr(worker, "current_job_id", None),
        "last_extraction_outcome": last_outcome,
        "last_extraction_worker_run_at": _iso(getattr(worker, "last_run_started_at", None)),
        "last_extraction_completed_at": _iso(last_completed),
        "extractor_version": EXTRACTOR_VERSION,
        "extractions_total": sum(ext_counts.values()),
        "extractions_success": ext_counts[ExtractionStatus.SUCCESS.value],
        "extractions_partial": ext_counts[ExtractionStatus.PARTIAL_SUCCESS.value],
        "extractions_failed": ext_counts[ExtractionStatus.FAILED.value],
        "extractions_ocr_required": ext_counts[ExtractionStatus.OCR_REQUIRED.value],
        "extractions_unsupported": ext_counts[ExtractionStatus.UNSUPPORTED.value],
        "extraction_jobs": job_counts,
        "extraction_jobs_pending": job_counts[ExtractionJobStatus.PENDING.value],
        "extraction_jobs_running": job_counts[ExtractionJobStatus.RUNNING.value],
        "extraction_jobs_retry": job_counts[ExtractionJobStatus.RETRY.value],
        "extraction_jobs_failed": job_counts[ExtractionJobStatus.FAILED.value],
        "extraction_jobs_ocr_required": job_counts[ExtractionJobStatus.OCR_REQUIRED.value],
        "document_versions_without_extraction": without,
        # VALID versions with neither an extraction nor any job: e.g. a failed auto-queue.
        "document_versions_unqueued": unqueued,
        "pages_extracted": pages,
        "tables_extracted": tables,
        "sections_extracted": sections,
    }
