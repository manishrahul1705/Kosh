"""Stage 3A extraction job queue (same invariants as the Stage 2B document queue).

* At most ONE queued (PENDING/RETRY) extraction job per DocumentVersion
  (application check + partial unique index uq_extraction_jobs_version_queued).
* A normal (non-force) request for a version that already has a current
  extraction for EXTRACTOR_VERSION is not queued ("already_extracted").
* A force request upgrades an already queued job to force=True instead of
  duplicating it.
Nothing here commits, except ``queue_after_version_commit`` (Stage 2 hook).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import and_, exists, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.constants import TenderStatus
from app.core.logging import log_event
from app.database.models import (
    DocumentExtraction,
    DocumentVersion,
    ExtractionJob,
    Tender,
    TenderDocument,
)
from app.extraction.constants import (
    EXTRACTOR_VERSION,
    QUEUED_EXTRACTION_STATUSES,
    ExtractionJobReason,
    ExtractionJobStatus,
)
from app.utils.dates import utcnow

logger = logging.getLogger("app.extraction.job_queue")


@dataclass
class ExtractionEnqueueResult:
    created: bool
    job: ExtractionJob | None = None
    skipped_reason: str | None = None  # already_queued | already_running | already_extracted | not_eligible

    @property
    def job_id(self) -> int | None:
        return self.job.id if self.job is not None else None


def _has_current_extraction(session: Session, version_id: int) -> bool:
    return session.scalar(select(DocumentExtraction.id).where(
        DocumentExtraction.document_version_id == version_id,
        DocumentExtraction.extractor_version == EXTRACTOR_VERSION,
        DocumentExtraction.is_current.is_(True)).limit(1)) is not None


def _find(session: Session, version_id: int, statuses: tuple[str, ...]) -> ExtractionJob | None:
    return session.scalar(select(ExtractionJob).where(
        ExtractionJob.document_version_id == version_id, ExtractionJob.status.in_(statuses))
        .order_by(ExtractionJob.id).limit(1))


def enqueue_extraction(
    session: Session,
    version_id: int,
    reason: ExtractionJobReason | str,
    *,
    force: bool = False,
    now: datetime | None = None,
) -> ExtractionEnqueueResult:
    reason_v = reason.value if isinstance(reason, ExtractionJobReason) else str(reason)
    now = now or utcnow()
    version = session.get(DocumentVersion, version_id)
    if version is None or version.validation_status != "VALID" or not version.storage_path:
        return ExtractionEnqueueResult(False, None, "not_eligible")

    queued = _find(session, version_id, QUEUED_EXTRACTION_STATUSES)
    if queued is not None:
        if force and not queued.force:
            queued.force = True
            queued.reason = ExtractionJobReason.REEXTRACT.value
            queued.updated_at = now
            session.flush()
        return ExtractionEnqueueResult(False, queued, "already_queued")
    if not force:
        if _find(session, version_id, (ExtractionJobStatus.RUNNING.value,)) is not None:
            return ExtractionEnqueueResult(False, None, "already_running")
        if _has_current_extraction(session, version_id):
            return ExtractionEnqueueResult(False, None, "already_extracted")

    job = ExtractionJob(document_version_id=version_id, status=ExtractionJobStatus.PENDING.value,
                        reason=reason_v, force=force, attempt_count=0, created_at=now, updated_at=now)
    try:
        with session.begin_nested():
            session.add(job)
            session.flush()
    except IntegrityError:
        return ExtractionEnqueueResult(False, _find(session, version_id, QUEUED_EXTRACTION_STATUSES),
                                       "already_queued")
    log_event(logger, logging.INFO, "extraction_job_queued", document_version_id=version_id,
              job_id=job.id, reason=reason_v, force=force)
    return ExtractionEnqueueResult(True, job)


def queue_after_version_commit(session: Session, version_id: int, settings: Settings) -> None:
    """Stage 2 hook: called right AFTER a new DocumentVersion was committed.

    Never raises. A failure is rolled back on its own, logged at ERROR
    (``extraction_job_queue_failed``) and visible in health/stats as
    ``document_versions_without_extraction``; backfill reconciles it later.
    """
    if not settings.extraction_auto_queue:
        return
    try:
        from app.database.session import reserve_sqlite_writer
        reserve_sqlite_writer(session)
        enqueue_extraction(session, version_id, ExtractionJobReason.NEW_VERSION)
        session.commit()
    except Exception as exc:
        try:
            session.rollback()
        except Exception:  # pragma: no cover
            pass
        log_event(logger, logging.ERROR, "extraction_job_queue_failed", document_version_id=version_id,
                  error=f"{type(exc).__name__}: {exc}"[:300])


def backfill_candidate_ids(session: Session, *, limit: int) -> list[int]:
    """VALID stored versions with no extraction job ever and no current extraction.

    Resumable: once queued, a version is no longer a candidate. ONGOING tenders
    first, then newest version first.
    """
    has_job = exists().where(ExtractionJob.document_version_id == DocumentVersion.id)
    has_extraction = exists().where(and_(
        DocumentExtraction.document_version_id == DocumentVersion.id,
        DocumentExtraction.extractor_version == EXTRACTOR_VERSION,
        DocumentExtraction.is_current.is_(True)))
    stmt = (
        select(DocumentVersion.id)
        .join(TenderDocument, TenderDocument.id == DocumentVersion.document_id)
        .join(Tender, Tender.id == TenderDocument.tender_id)
        .where(DocumentVersion.validation_status == "VALID", DocumentVersion.storage_path.is_not(None),
               ~has_job, ~has_extraction)
        .order_by(Tender.status != TenderStatus.ONGOING.value, DocumentVersion.id.desc())
        .limit(limit)
    )
    return list(session.scalars(stmt).all())


def backfill_extraction_jobs(session: Session, *, limit: int, dry_run: bool = False,
                             now: datetime | None = None) -> list[int]:
    """Queue BACKFILL jobs for at most ``limit`` versions (no commit)."""
    ids = backfill_candidate_ids(session, limit=limit)
    if dry_run:
        return ids
    done = []
    for vid in ids:
        if enqueue_extraction(session, vid, ExtractionJobReason.BACKFILL, now=now).created:
            done.append(vid)
    log_event(logger, logging.INFO, "extraction_backfill_completed", queued=len(done), limit=limit)
    return done
