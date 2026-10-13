"""Stage 2B operational status: is the document worker actually working?

Used by /health, /api/stats and /api/documents/worker. Exposes no secrets
(no URLs, paths or credentials) - only switches, counts and timestamps.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import exists, func, select
from sqlalchemy.orm import Session

from app.core.constants import TenderStatus
from app.database.models import DocumentJob, Tender
from app.schemas.documents import DocumentJobReason, DocumentJobStatus
from app.utils.dates import as_aware_utc, utcnow

S = DocumentJobStatus


def _iso(dt: datetime | None) -> str | None:
    aware = as_aware_utc(dt)
    return aware.isoformat() if aware else None


def job_counts(db: Session) -> dict[str, int]:
    rows = db.execute(select(DocumentJob.status, func.count()).group_by(DocumentJob.status)).all()
    counts = {s.value: 0 for s in DocumentJobStatus}
    for status, n in rows:
        counts[status] = n
    return counts


def document_worker_status(db: Session, worker, scheduler=None) -> dict:
    settings = worker.settings if worker is not None else None
    now = utcnow()
    counts = job_counts(db)
    stale_minutes = settings.document_stale_running_minutes if settings else 30
    stale_cutoff = now - timedelta(minutes=stale_minutes)

    def scalar(stmt):
        return db.scalar(stmt)

    oldest_pending = scalar(select(func.min(DocumentJob.created_at)).where(
        DocumentJob.status == S.PENDING.value))
    retry_due = scalar(select(func.count()).select_from(DocumentJob).where(
        DocumentJob.status == S.RETRY.value, DocumentJob.next_retry_at <= now)) or 0
    stale_running = scalar(select(func.count()).select_from(DocumentJob).where(
        DocumentJob.status == S.RUNNING.value,
        (DocumentJob.started_at.is_(None)) | (DocumentJob.started_at < stale_cutoff))) or 0
    last_success = scalar(select(func.max(DocumentJob.finished_at)).where(
        DocumentJob.status.in_([S.SUCCESS.value, S.PARTIAL_SUCCESS.value])))
    last_job_finished = scalar(select(func.max(DocumentJob.finished_at)))
    last_periodic = scalar(select(func.max(DocumentJob.finished_at)).where(
        DocumentJob.reason == DocumentJobReason.PERIODIC_REFRESH.value,
        DocumentJob.status.in_([S.SUCCESS.value, S.PARTIAL_SUCCESS.value])))
    has_job = exists().where(DocumentJob.tender_id == Tender.id)
    ongoing_without_jobs = scalar(select(func.count(Tender.id)).where(
        Tender.status == TenderStatus.ONGOING.value, ~has_job)) or 0

    sched_running = bool(scheduler is not None and scheduler.running
                         and getattr(scheduler, "document_jobs_enabled", False))
    cooldown_until = worker.block_cooldown_until(db) if worker is not None else None

    return {
        "document_worker_enabled": bool(settings and settings.document_worker_enabled),
        "document_worker_running": bool(worker is not None and worker.is_busy()),
        "document_scheduler_running": sched_running,
        "next_document_worker_run": scheduler.next_run_time("document_worker") if sched_running else None,
        "current_job_id": getattr(worker, "current_job_id", None),
        "jobs": counts,
        "pending_jobs": counts[S.PENDING.value],
        "running_jobs": counts[S.RUNNING.value],
        "retry_jobs": counts[S.RETRY.value],
        "retry_jobs_due": retry_due,
        "failed_jobs": counts[S.FAILED.value],
        "blocked_jobs": counts[S.BLOCKED.value],
        "stale_running_jobs": stale_running,
        "oldest_pending_job_at": _iso(oldest_pending),
        "last_successful_document_processing_at": _iso(last_success),
        "last_document_job_finished_at": _iso(last_job_finished),
        "last_document_worker_run_at": _iso(getattr(worker, "last_run_started_at", None)),
        "last_document_worker_run_finished_at": _iso(getattr(worker, "last_run_finished_at", None)),
        "last_document_worker_run_processed": getattr(worker, "last_run_processed", 0),
        "last_document_worker_skip_reason": getattr(worker, "last_run_skipped_reason", None),
        "last_document_refresh_check_at": _iso(getattr(worker, "last_refresh_check_at", None)),
        "last_document_refresh_at": _iso(last_periodic),
        "blocked_cooldown_until": _iso(cooldown_until),
        "ongoing_tenders_without_document_jobs": ongoing_without_jobs,
    }
