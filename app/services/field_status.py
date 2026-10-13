"""Stage 3B operational status for /health, /api/stats and /api/tender-fields/worker."""

from __future__ import annotations

from sqlalchemy import and_, exists, func, select
from sqlalchemy.orm import Session

from app.database.models import DocumentExtraction, FieldExtractionJob, TenderFieldExtraction, TenderFieldValue
from app.fields.constants import FIELD_EXTRACTOR_VERSION, FieldJobStatus, FieldStatus, RunStatus
from app.fields.job_queue import eligible_stage3a_condition
from app.utils.dates import as_aware_utc


def _iso(dt):
    a = as_aware_utc(dt)
    return a.isoformat() if a else None


def field_extraction_status(db: Session, worker=None, scheduler=None) -> dict:
    settings = getattr(worker, "settings", None)
    current = and_(TenderFieldExtraction.is_current.is_(True),
                   TenderFieldExtraction.extractor_version == FIELD_EXTRACTOR_VERSION)
    runs = {s.value: 0 for s in RunStatus}
    for st, n in db.execute(select(TenderFieldExtraction.status, func.count()).where(current)
                            .group_by(TenderFieldExtraction.status)).all():
        runs[st] = n
    jobs = {s.value: 0 for s in FieldJobStatus}
    for st, n in db.execute(select(FieldExtractionJob.status, func.count()).group_by(FieldExtractionJob.status)).all():
        jobs[st] = n
    eligible = eligible_stage3a_condition()
    has_run = exists().where(and_(TenderFieldExtraction.stage3a_extraction_id == DocumentExtraction.id, current))
    has_job = exists().where(FieldExtractionJob.stage3a_extraction_id == DocumentExtraction.id)
    n_eligible = db.scalar(select(func.count(DocumentExtraction.id)).where(eligible)) or 0
    without = db.scalar(select(func.count(DocumentExtraction.id)).where(eligible, ~has_run)) or 0
    unqueued = db.scalar(select(func.count(DocumentExtraction.id)).where(eligible, ~has_run, ~has_job)) or 0
    current_ids = select(TenderFieldExtraction.id).where(current)
    value_counts = {s.value: 0 for s in FieldStatus}
    for st, n in db.execute(select(TenderFieldValue.status, func.count())
                            .where(TenderFieldValue.field_extraction_id.in_(current_ids))
                            .group_by(TenderFieldValue.status)).all():
        value_counts[st] = n
    last = db.execute(select(FieldExtractionJob.id, FieldExtractionJob.stage3a_extraction_id, FieldExtractionJob.status,
                             FieldExtractionJob.outcome, FieldExtractionJob.finished_at)
                      .where(FieldExtractionJob.finished_at.is_not(None))
                      .order_by(FieldExtractionJob.finished_at.desc(), FieldExtractionJob.id.desc()).limit(1)).first()
    last_outcome = getattr(worker, "last_outcome", None) or (
        {"job_id": last.id, "stage3a_extraction_id": last.stage3a_extraction_id, "status": last.status,
         "outcome": last.outcome, "finished_at": _iso(last.finished_at)} if last else None)
    sched = bool(scheduler is not None and scheduler.running
                 and getattr(scheduler, "field_extraction_jobs_enabled", False))
    return {
        "field_extraction_worker_enabled": bool(settings and settings.field_extraction_worker_enabled),
        "field_extraction_worker_running": bool(worker is not None and worker.is_busy()),
        "field_extraction_scheduler_running": sched,
        "next_field_extraction_worker_run": scheduler.next_run_time("field_extraction_worker") if sched else None,
        "current_field_extraction_job_id": getattr(worker, "current_job_id", None),
        "last_field_extraction_outcome": last_outcome,
        "field_extractor_version": FIELD_EXTRACTOR_VERSION,
        "stage3a_extractions_eligible": n_eligible,
        "stage3a_extractions_without_fields": without,
        # eligible Stage 3A extractions with neither a run nor any job (e.g. a failed auto-queue)
        "stage3a_extractions_unqueued": unqueued,
        "field_extractions_total": sum(runs.values()),
        "field_extractions_success": runs[RunStatus.SUCCESS.value],
        "field_extractions_partial": runs[RunStatus.PARTIAL_SUCCESS.value],
        "field_extractions_failed": runs[RunStatus.FAILED.value],
        "field_extraction_jobs": jobs,
        "field_extraction_jobs_pending": jobs[FieldJobStatus.PENDING.value],
        "field_extraction_jobs_running": jobs[FieldJobStatus.RUNNING.value],
        "field_extraction_jobs_retry": jobs[FieldJobStatus.RETRY.value],
        "field_extraction_jobs_failed": jobs[FieldJobStatus.FAILED.value],
        "fields_extracted": value_counts[FieldStatus.RESOLVED.value],
        "fields_unknown": value_counts[FieldStatus.UNKNOWN.value],
        "fields_conflicted": value_counts[FieldStatus.CONFLICT.value],
    }
