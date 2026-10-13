"""Stage 3B field-extraction job queue (same invariants as Stage 2B / Stage 3A queues).

* At most ONE queued (PENDING/RETRY) job per Stage 3A extraction (app check +
  partial unique index uq_field_extraction_jobs_source_queued).
* Only CURRENT Stage 3A extractions with status SUCCESS / PARTIAL_SUCCESS are
  eligible; anything else is refused as "not_ready" (never faked as success).
* A non-force request for an already field-extracted Stage 3A extraction is not queued.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import and_, exists, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.logging import log_event
from app.database.models import DocumentExtraction, FieldExtractionJob, TenderFieldExtraction
from app.fields.constants import (
    FIELD_EXTRACTOR_VERSION,
    QUEUED_FIELD_JOB_STATUSES,
    USABLE_STAGE3A_STATUSES,
    FieldJobReason,
    FieldJobStatus,
)
from app.utils.dates import utcnow

logger = logging.getLogger("app.fields.job_queue")


@dataclass
class FieldEnqueueResult:
    created: bool
    job: FieldExtractionJob | None = None
    skipped_reason: str | None = None  # already_queued | already_running | already_extracted | not_ready

    @property
    def job_id(self) -> int | None:
        return self.job.id if self.job is not None else None


def _usable_stage3a(session: Session, stage3a_id: int) -> bool:
    e = session.get(DocumentExtraction, stage3a_id)
    return e is not None and bool(e.is_current) and e.status in USABLE_STAGE3A_STATUSES


def _find(session: Session, stage3a_id: int, statuses) -> FieldExtractionJob | None:
    return session.scalar(select(FieldExtractionJob).where(
        FieldExtractionJob.stage3a_extraction_id == stage3a_id, FieldExtractionJob.status.in_(statuses))
        .order_by(FieldExtractionJob.id).limit(1))


def enqueue_field_extraction(session: Session, stage3a_id: int, reason: FieldJobReason | str, *,
                             force: bool = False, now: datetime | None = None) -> FieldEnqueueResult:
    reason_v = reason.value if isinstance(reason, FieldJobReason) else str(reason)
    now = now or utcnow()
    if not _usable_stage3a(session, stage3a_id):
        return FieldEnqueueResult(False, None, "not_ready")
    queued = _find(session, stage3a_id, QUEUED_FIELD_JOB_STATUSES)
    if queued is not None:
        if force and not queued.force:
            queued.force, queued.reason, queued.updated_at = True, FieldJobReason.REEXTRACT.value, now
            session.flush()
        return FieldEnqueueResult(False, queued, "already_queued")
    if not force:
        if _find(session, stage3a_id, (FieldJobStatus.RUNNING.value,)) is not None:
            return FieldEnqueueResult(False, None, "already_running")
        if session.scalar(select(TenderFieldExtraction.id).where(
                TenderFieldExtraction.stage3a_extraction_id == stage3a_id,
                TenderFieldExtraction.extractor_version == FIELD_EXTRACTOR_VERSION,
                TenderFieldExtraction.is_current.is_(True)).limit(1)) is not None:
            return FieldEnqueueResult(False, None, "already_extracted")
    job = FieldExtractionJob(stage3a_extraction_id=stage3a_id, status=FieldJobStatus.PENDING.value,
                             reason=reason_v, force=force, attempt_count=0, created_at=now, updated_at=now)
    try:
        with session.begin_nested():
            session.add(job)
            session.flush()
    except IntegrityError:
        return FieldEnqueueResult(False, _find(session, stage3a_id, QUEUED_FIELD_JOB_STATUSES), "already_queued")
    log_event(logger, logging.INFO, "field_extraction_job_queued", stage3a_extraction_id=stage3a_id,
              job_id=job.id, reason=reason_v, force=force)
    return FieldEnqueueResult(True, job)


def queue_after_stage3a_commit(session: Session, stage3a_id: int | None, settings: Settings) -> None:
    """Stage 3A hook: called right AFTER a Stage 3A extraction was committed.

    Never raises; runs in its own commit. A failure is rolled back on its own, logged
    (``field_extraction_job_queue_failed``), visible in health as
    ``stage3a_extractions_unqueued`` and repaired by the Stage 3B backfill.
    """
    if not stage3a_id or not settings.field_extraction_auto_queue:
        return
    try:
        from app.database.session import reserve_sqlite_writer
        reserve_sqlite_writer(session)
        res = enqueue_field_extraction(session, stage3a_id, FieldJobReason.STAGE3A_COMPLETED)
        session.commit()
        if res.skipped_reason == "not_ready":
            log_event(logger, logging.INFO, "field_extraction_not_queued", stage3a_extraction_id=stage3a_id,
                      why="stage3a_not_usable")
    except Exception as exc:
        try:
            session.rollback()
        except Exception:  # pragma: no cover
            pass
        log_event(logger, logging.ERROR, "field_extraction_job_queue_failed", stage3a_extraction_id=stage3a_id,
                  error=f"{type(exc).__name__}: {exc}"[:300])


def eligible_stage3a_condition():
    return and_(DocumentExtraction.is_current.is_(True), DocumentExtraction.status.in_(USABLE_STAGE3A_STATUSES))


def backfill_candidate_ids(session: Session, *, limit: int) -> list[int]:
    """Usable current Stage 3A extractions with no Stage 3B job ever and no current run."""
    has_job = exists().where(FieldExtractionJob.stage3a_extraction_id == DocumentExtraction.id)
    has_run = exists().where(and_(TenderFieldExtraction.stage3a_extraction_id == DocumentExtraction.id,
                                  TenderFieldExtraction.extractor_version == FIELD_EXTRACTOR_VERSION,
                                  TenderFieldExtraction.is_current.is_(True)))
    return list(session.scalars(select(DocumentExtraction.id)
                                .where(eligible_stage3a_condition(), ~has_job, ~has_run)
                                .order_by(DocumentExtraction.id.desc()).limit(limit)).all())


def backfill_field_jobs(session: Session, *, limit: int, dry_run: bool = False) -> list[int]:
    ids = backfill_candidate_ids(session, limit=limit)
    if dry_run:
        return ids
    done = [i for i in ids if enqueue_field_extraction(session, i, FieldJobReason.BACKFILL).created]
    log_event(logger, logging.INFO, "field_extraction_backfill_completed", queued=len(done), limit=limit)
    return done
