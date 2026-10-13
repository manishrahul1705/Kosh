"""Persistence of TenderRecords: insert / update-with-audit / touch."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.constants import TRACKED_FIELDS, Classification, TenderStatus
from app.core.logging import log_event
from app.database.models import Tender, TenderChange
from app.documents.job_queue import safe_enqueue
from app.schemas.documents import DocumentJobReason
from app.schemas.tender import TenderRecord
from app.services.change_detector import canonical_value, compute_fingerprint, diff_fields
from app.services.status_service import apply_current_status
from app.utils.dates import utcnow

logger = logging.getLogger("app.services.tender")


@dataclass(frozen=True)
class JobQueuePolicy:
    """Which Stage 2B document jobs Stage 1 queues as a side effect."""

    queue_new_tenders: bool = True
    queue_final_refresh: bool = True

    @classmethod
    def from_settings(cls, settings) -> "JobQueuePolicy":
        return cls(queue_new_tenders=settings.auto_download_new_tenders,
                   queue_final_refresh=settings.final_refresh_on_close)


DEFAULT_QUEUE_POLICY = JobQueuePolicy()


def _queue_job(session: Session, tender: Tender, reason: DocumentJobReason, now: datetime) -> None:
    """Queue a document job without ever failing the tender upsert.

    Runs in its own SAVEPOINT *after* the tender has a database id (flushed).
    A failure is logged at ERROR (``document_job_queue_failed``) and swallowed.
    """
    res = safe_enqueue(session, tender.id, reason, now=now)
    if res is not None and not res.created:
        log_event(logger, logging.DEBUG, "document_job_not_created", tender_id=tender.id,
                  reason=reason.value, why=res.skipped_reason, existing_job_id=res.job_id)


@dataclass
class UpsertStats:
    seen: int = 0
    new: int = 0
    updated: int = 0
    unchanged: int = 0
    failed: int = 0
    failures: list[dict] = field(default_factory=list)

    def as_summary(self) -> dict[str, int]:
        return {"seen": self.seen, "new": self.new, "updated": self.updated,
                "unchanged": self.unchanged, "failed": self.failed}


def _apply_record(tender: Tender, record: TenderRecord) -> None:
    for name in TRACKED_FIELDS:
        value = getattr(record, name)
        if name == "status":
            value = record.status.value
        setattr(tender, name, value)
    tender.source_internal_id = record.source_internal_id


def upsert_record(
    session: Session,
    record: TenderRecord,
    *,
    now: datetime,
    run_id: int | None,
    queue_policy: JobQueuePolicy = DEFAULT_QUEUE_POLICY,
) -> Classification:
    """Classify and persist one record. Caller controls the transaction."""
    fingerprint = compute_fingerprint(record)
    tender = session.scalar(select(Tender).where(Tender.bid_number == record.bid_number))

    if tender is None:
        tender = Tender(bid_number=record.bid_number, first_seen_at=now, last_seen_at=now,
                        source_fingerprint=fingerprint, created_at=now, updated_at=now)
        _apply_record(tender, record)
        apply_current_status(session, tender, now=now, run_id=run_id)  # no history row for a new tender
        session.add(tender)
        session.flush()  # tender.id is now reliable
        log_event(logger, logging.INFO, "new_tender", bid=record.bid_number, tender_id=tender.id)

        # Stage 2B: queue the NEW_TENDER document job (own savepoint, never fatal).
        # (Previously the job was logged before flush, hence "job_id=None".)
        if queue_policy.queue_new_tenders:
            _queue_job(session, tender, DocumentJobReason.NEW_TENDER, now)

        return Classification.NEW

    tender.last_seen_at = now
    if tender.source_internal_id is None and record.source_internal_id:
        tender.source_internal_id = record.source_internal_id

    if tender.source_fingerprint == fingerprint:
        apply_current_status(session, tender, now=now, run_id=run_id)  # deadline may have passed
        return Classification.UNCHANGED

    changes = diff_fields(tender, record)
    if not changes:
        # Fingerprint drift without a field difference (e.g. algorithm change).
        tender.source_fingerprint = fingerprint
        apply_current_status(session, tender, now=now, run_id=run_id)
        return Classification.UNCHANGED

    for field_name, old, new in changes:
        session.add(TenderChange(tender_id=tender.id, field_name=field_name, old_value=old,
                                 new_value=new, detected_at=now, collection_run_id=run_id))
    _apply_record(tender, record)
    tender.source_fingerprint = fingerprint
    tender.last_changed_at = now
    tender.updated_at = now
    apply_current_status(session, tender, now=now, run_id=run_id)  # e.g. deadline extension -> LIVE again
    session.flush()
    log_event(logger, logging.INFO, "tender_updated", bid=record.bid_number,
              fields=",".join(c[0] for c in changes))

    # Stage 2B: ONGOING -> CLOSED observed -> one FINAL_REFRESH (idempotent).
    if queue_policy.queue_final_refresh and _is_closing(changes):
        _queue_job(session, tender, DocumentJobReason.FINAL_REFRESH, now)
    return Classification.UPDATED


def _is_closing(changes: list[tuple[str, str | None, str | None]]) -> bool:
    return any(f == "status" and old == TenderStatus.ONGOING.value and new == TenderStatus.CLOSED.value
               for f, old, new in changes)


def upsert_records(
    session: Session,
    records: list[TenderRecord],
    *,
    now: datetime,
    run_id: int | None,
    queue_policy: JobQueuePolicy = DEFAULT_QUEUE_POLICY,
) -> UpsertStats:
    """Persist many records; one bad record never aborts the batch."""
    stats = UpsertStats()
    for record in records:
        stats.seen += 1
        try:
            with session.begin_nested():
                result = upsert_record(session, record, now=now, run_id=run_id, queue_policy=queue_policy)
        except Exception as exc:
            stats.failed += 1
            stats.failures.append({"bid": record.bid_number, "reason": f"{type(exc).__name__}: {exc}"[:300]})
            log_event(logger, logging.ERROR, "tender_persist_failed", bid=record.bid_number,
                      error=type(exc).__name__)
            continue
        if result is Classification.NEW:
            stats.new += 1
        elif result is Classification.UPDATED:
            stats.updated += 1
        else:
            stats.unchanged += 1
    return stats


def close_expired_unseen(
    session: Session,
    *,
    now: datetime,
    run_started_at: datetime,
    run_id: int | None,
    queue_policy: JobQueuePolicy = DEFAULT_QUEUE_POLICY,
) -> int:
    """Mark ONGOING tenders CLOSED when their deadline has passed *and* the live
    listing no longer shows them. The passed deadline is the evidence; a merely
    missing tender is left untouched (never CANCELLED by inference)."""
    rows = session.scalars(
        select(Tender).where(
            Tender.status == TenderStatus.ONGOING.value,
            Tender.bid_end_at.is_not(None),
            Tender.bid_end_at < now,
            Tender.last_seen_at < run_started_at,
        )
    ).all()
    for tender in rows:
        session.add(TenderChange(tender_id=tender.id, field_name="status",
                                 old_value=canonical_value(tender.status),
                                 new_value=TenderStatus.CLOSED.value, detected_at=now,
                                 collection_run_id=run_id))
        tender.status = TenderStatus.CLOSED.value
        tender.last_changed_at = now
        tender.updated_at = now
        tender.source_fingerprint = compute_fingerprint(tender)
        apply_current_status(session, tender, now=now, run_id=run_id)
        log_event(logger, logging.INFO, "tender_closed_by_deadline", bid=tender.bid_number)
    session.flush()
    if queue_policy.queue_final_refresh:
        for tender in rows:
            _queue_job(session, tender, DocumentJobReason.FINAL_REFRESH, now)
    return len(rows)
