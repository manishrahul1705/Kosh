"""Stage 2B: DocumentJob queue operations (enqueue / dedupe / refresh scheduling).

Queue invariants
----------------
* At most ONE *queued* job (PENDING or RETRY) per tender. Enforced in the
  application (checked here) and by the partial unique index
  ``uq_document_jobs_tender_queued`` (migration 0003) for races.
* A tender with a RUNNING job only gets a new queued job for reasons that must
  observe a *later* state (FINAL_REFRESH, MANUAL). The worker never claims a
  job for a tender that already has a RUNNING job, so they never overlap.
* At most one FINAL_REFRESH job per tender, ever (idempotent close handling).

Nothing here commits: callers own the transaction. Inserts happen inside a
SAVEPOINT so a failed enqueue never rolls back the caller's other work.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import and_, exists, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.constants import TenderStatus
from app.core.logging import log_event
from app.database.models import DocumentJob, Tender, TenderDocument
from app.schemas.documents import (
    ACTIVE_JOB_STATUSES,
    QUEUED_JOB_STATUSES,
    TERMINAL_JOB_STATUSES,
    DocumentJobReason,
    DocumentJobStatus,
)
from app.utils.dates import utcnow

logger = logging.getLogger("app.documents.job_queue")

# Reasons allowed to queue behind a RUNNING job (they must see a later state).
_QUEUE_BEHIND_RUNNING = {DocumentJobReason.FINAL_REFRESH.value, DocumentJobReason.MANUAL.value}


@dataclass
class EnqueueResult:
    created: bool
    job: DocumentJob | None = None
    skipped_reason: str | None = None  # already_queued | already_running | final_refresh_exists | ...

    @property
    def job_id(self) -> int | None:
        return self.job.id if self.job is not None else None


def _reason_value(reason: DocumentJobReason | str) -> str:
    return reason.value if isinstance(reason, DocumentJobReason) else str(reason)


def find_queued_job(session: Session, tender_id: int) -> DocumentJob | None:
    return session.scalar(
        select(DocumentJob)
        .where(DocumentJob.tender_id == tender_id, DocumentJob.status.in_(QUEUED_JOB_STATUSES))
        .order_by(DocumentJob.id)
        .limit(1)
    )


def find_running_job(session: Session, tender_id: int) -> DocumentJob | None:
    return session.scalar(
        select(DocumentJob)
        .where(DocumentJob.tender_id == tender_id, DocumentJob.status == DocumentJobStatus.RUNNING.value)
        .order_by(DocumentJob.id)
        .limit(1)
    )


def enqueue_job(
    session: Session,
    tender_id: int,
    reason: DocumentJobReason | str,
    *,
    now: datetime | None = None,
) -> EnqueueResult:
    """Queue a PENDING job for ``tender_id`` unless an equivalent one exists.

    Does not commit. Safe to call repeatedly (idempotent).
    """
    reason_v = _reason_value(reason)
    now = now or utcnow()

    queued = find_queued_job(session, tender_id)
    if queued is not None:
        if reason_v == DocumentJobReason.FINAL_REFRESH.value and queued.reason != reason_v:
            # The queued job will run after the close was observed: it *is* the
            # final refresh. Record that so no second FINAL_REFRESH is created.
            queued.reason = reason_v
            queued.updated_at = now
            session.flush()
            log_event(logger, logging.INFO, "document_job_reason_upgraded", tender_id=tender_id,
                      job_id=queued.id, reason=reason_v)
        return EnqueueResult(created=False, job=queued, skipped_reason="already_queued")

    if reason_v not in _QUEUE_BEHIND_RUNNING:
        running = find_running_job(session, tender_id)
        if running is not None:
            return EnqueueResult(created=False, job=running, skipped_reason="already_running")

    job = DocumentJob(
        tender_id=tender_id,
        status=DocumentJobStatus.PENDING.value,
        reason=reason_v,
        attempt_count=0,
        created_at=now,
        updated_at=now,
    )
    try:
        with session.begin_nested():
            session.add(job)
            session.flush()
    except IntegrityError:
        # Lost a race with another writer: the unique index kept us at one queued job.
        existing = find_queued_job(session, tender_id)
        return EnqueueResult(created=False, job=existing, skipped_reason="already_queued")

    log_event(logger, logging.INFO, "document_job_created", tender_id=tender_id, job_id=job.id,
              reason=reason_v)
    return EnqueueResult(created=True, job=job)


def queue_final_refresh(session: Session, tender_id: int, *, now: datetime | None = None) -> EnqueueResult:
    """Queue the single FINAL_REFRESH for a tender that just closed (idempotent)."""
    already = session.scalar(
        select(DocumentJob.id).where(
            DocumentJob.tender_id == tender_id,
            DocumentJob.reason == DocumentJobReason.FINAL_REFRESH.value,
        ).limit(1)
    )
    if already is not None:
        return EnqueueResult(created=False, job=session.get(DocumentJob, already),
                             skipped_reason="final_refresh_exists")
    return enqueue_job(session, tender_id, DocumentJobReason.FINAL_REFRESH, now=now)


def safe_enqueue(
    session: Session,
    tender_id: int,
    reason: DocumentJobReason,
    *,
    now: datetime | None = None,
) -> EnqueueResult | None:
    """Enqueue without ever raising into the caller (Stage 1 must not fail).

    Failures are logged at ERROR (``document_job_queue_failed``) and return None.
    """
    try:
        with session.begin_nested():
            if reason is DocumentJobReason.FINAL_REFRESH:
                return queue_final_refresh(session, tender_id, now=now)
            return enqueue_job(session, tender_id, reason, now=now)
    except Exception as exc:  # pragma: no cover - defensive; exercised via monkeypatch in tests
        log_event(logger, logging.ERROR, "document_job_queue_failed", tender_id=tender_id,
                  reason=reason.value, error=f"{type(exc).__name__}: {exc}"[:300])
        return None


# ---------------------------------------------------------------------------
# Periodic refresh (due-time based)
# ---------------------------------------------------------------------------
def due_refresh_tender_ids(session: Session, *, now: datetime, interval_minutes: int, limit: int) -> list[int]:
    """ONGOING tenders whose last finished job is older than the interval and
    that have no active (queued/running) job. Oldest refresh first.

    Tenders that never had a job are NOT refreshed here (that is backfill).
    """
    if limit <= 0:
        return []
    cutoff = now - timedelta(minutes=interval_minutes)
    last_done = (
        select(DocumentJob.tender_id.label("tender_id"), func.max(DocumentJob.finished_at).label("last_done"))
        .where(DocumentJob.status.in_(TERMINAL_JOB_STATUSES), DocumentJob.finished_at.is_not(None))
        .group_by(DocumentJob.tender_id)
        .subquery()
    )
    active = exists().where(
        and_(DocumentJob.tender_id == Tender.id, DocumentJob.status.in_(ACTIVE_JOB_STATUSES))
    )
    stmt = (
        select(Tender.id)
        .join(last_done, last_done.c.tender_id == Tender.id)
        .where(Tender.status == TenderStatus.ONGOING.value, last_done.c.last_done <= cutoff, ~active)
        .order_by(last_done.c.last_done.asc(), Tender.id.asc())
        .limit(limit)
    )
    return list(session.scalars(stmt).all())


def enqueue_due_refreshes(session: Session, settings: Settings, *, now: datetime | None = None) -> int:
    """Queue PERIODIC_REFRESH jobs for due tenders, keeping at most
    ``document_refresh_batch_size`` periodic jobs queued at once. Does not commit."""
    now = now or utcnow()
    queued_periodic = session.scalar(
        select(func.count()).select_from(DocumentJob).where(
            DocumentJob.status.in_(QUEUED_JOB_STATUSES),
            DocumentJob.reason == DocumentJobReason.PERIODIC_REFRESH.value,
        )
    ) or 0
    room = settings.document_refresh_batch_size - queued_periodic
    created = 0
    for tender_id in due_refresh_tender_ids(
        session, now=now, interval_minutes=settings.document_refresh_interval_minutes, limit=room
    ):
        res = enqueue_job(session, tender_id, DocumentJobReason.PERIODIC_REFRESH, now=now)
        created += int(res.created)
    if created:
        log_event(logger, logging.INFO, "periodic_refresh_queued", count=created)
    return created


# ---------------------------------------------------------------------------
# Backfill
# ---------------------------------------------------------------------------
def backfill_candidate_ids(
    session: Session,
    *,
    limit: int,
    statuses: tuple[str, ...] | None = None,
) -> list[int]:
    """Tenders that have never had a DocumentJob and have no stored document.

    Resumable by construction: once a job exists the tender is no longer a
    candidate. ONGOING first, then newest first.
    """
    has_job = exists().where(DocumentJob.tender_id == Tender.id)
    has_doc = exists().where(
        and_(TenderDocument.tender_id == Tender.id, TenderDocument.current_version_id.is_not(None))
    )
    ongoing_first = (Tender.status != TenderStatus.ONGOING.value)
    stmt = select(Tender.id).where(~has_job, ~has_doc)
    if statuses:
        stmt = stmt.where(Tender.status.in_(statuses))
    stmt = stmt.order_by(ongoing_first, Tender.first_seen_at.desc(), Tender.id.desc()).limit(limit)
    return list(session.scalars(stmt).all())


def backfill_jobs(
    session: Session,
    *,
    limit: int,
    statuses: tuple[str, ...] | None = None,
    now: datetime | None = None,
    dry_run: bool = False,
) -> list[int]:
    """Create BACKFILL jobs for up to ``limit`` candidates. Does not commit.

    Returns the tender ids that got (or, with dry_run, would get) a job.
    """
    now = now or utcnow()
    ids = backfill_candidate_ids(session, limit=limit, statuses=statuses)
    if dry_run:
        return ids
    done: list[int] = []
    for tender_id in ids:
        res = enqueue_job(session, tender_id, DocumentJobReason.BACKFILL, now=now)
        if res.created:
            done.append(tender_id)
    return done
