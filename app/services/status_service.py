"""Deterministic tender status verification.

``Tender.status`` is what the GeM source last reported. A tender listed as
ONGOING stays ONGOING in that column until a collection run sees it again, even
when its deadline has passed in the meantime. ``tender_status.current_status``
(exposed as ``Tender.current_status``) is the trustworthy state shown to
clients. It is derived here from facts only
(source status, bid end date, publication date and the current time), never by
an LLM.

Rules, applied in order:

1. source CANCELLED                        -> CANCELLED   (SOURCE_CANCELLED)
2. bid_end_at <= now                       -> CLOSED      (DEADLINE_PASSED)
3. source CLOSED                           -> CLOSED      (SOURCE_CLOSED)
4. published_at > now                      -> UPCOMING    (PUBLICATION_PENDING)
5. source ONGOING, deadline in the future  -> LIVE        (SOURCE_LISTING)
6. source ONGOING, no deadline known       -> LIVE        (SOURCE_LISTING_NO_DEADLINE)
7. anything else                           -> UNKNOWN     (SOURCE_STATUS_UNKNOWN)

A deadline extension (corrigendum) reaches the database through the next
collection upsert. That upsert writes the new ``bid_end_at`` and recomputes
``current_status``, so a CLOSED tender whose deadline was extended returns to
LIVE. Every transition is recorded in ``tender_status_events`` (old, new,
reason, time). ``tender_changes`` stays a pure log of source-field changes.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.constants import TenderStatus
from app.core.logging import log_event
from app.database.models import Tender, TenderStatusEvent, TenderStatusRecord

logger = logging.getLogger("app.services.status")


class CurrentStatus(str, Enum):
    LIVE = "LIVE"
    UPCOMING = "UPCOMING"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"
    UNKNOWN = "UNKNOWN"


# States that may still change without new source data (a deadline can pass).
OPEN_STATES = (CurrentStatus.LIVE.value, CurrentStatus.UPCOMING.value, CurrentStatus.UNKNOWN.value)

# Tracked tender fields whose change means the tender was amended.
AMENDMENT_FIELDS = ("bid_end_at", "bid_opening_at", "quantity", "title", "category", "estimated_value")


def derive_current_status(
    source_status: str | None,
    bid_end_at: datetime | None,
    published_at: datetime | None,
    now: datetime,
) -> tuple[CurrentStatus, str]:
    """Pure function: (current_status, status_source). All datetimes are naive UTC."""
    if source_status == TenderStatus.CANCELLED.value:
        return CurrentStatus.CANCELLED, "SOURCE_CANCELLED"
    if bid_end_at is not None and bid_end_at <= now:
        return CurrentStatus.CLOSED, "DEADLINE_PASSED"
    if source_status == TenderStatus.CLOSED.value:
        return CurrentStatus.CLOSED, "SOURCE_CLOSED"
    if published_at is not None and published_at > now:
        return CurrentStatus.UPCOMING, "PUBLICATION_PENDING"
    if source_status == TenderStatus.ONGOING.value:
        if bid_end_at is None:
            return CurrentStatus.LIVE, "SOURCE_LISTING_NO_DEADLINE"
        return CurrentStatus.LIVE, "SOURCE_LISTING"
    return CurrentStatus.UNKNOWN, "SOURCE_STATUS_UNKNOWN"


def apply_current_status(session: Session, tender: Tender, *, now: datetime,
                         run_id: int | None = None) -> bool:
    """Recompute one tender's current status. Returns True when it changed.

    ``run_id`` is accepted for call-site symmetry with the collection pipeline (unused)."""
    status, source = derive_current_status(tender.status, tender.bid_end_at, tender.published_at, now)
    record = tender.status_record
    old = record.current_status if record is not None else None
    changed = old != status.value
    if record is None:
        record = TenderStatusRecord(current_status=status.value, status_source=source,
                                    last_status_check_at=now, changed_at=now)
        tender.status_record = record
    if changed:
        session.add(TenderStatusEvent(tender=tender, old_status=old, new_status=status.value,
                                      status_source=source, detected_at=now))
        record.changed_at = now
        if old is not None:
            log_event(logger, logging.INFO, "tender_status_changed", tender_id=tender.id,
                      old=old, new=status.value, source=source)
    record.current_status = status.value
    record.status_source = source
    record.last_status_check_at = now
    return changed


@dataclass
class StatusCheckResult:
    checked: int = 0
    changed: int = 0


def verify_statuses(session: Session, *, now: datetime, batch_size: int = 1000) -> StatusCheckResult:
    """Re-derive the status of every tender whose state can change with time
    (LIVE / UPCOMING / UNKNOWN) or that has never been checked. Idempotent: a
    second run at the same instant changes nothing. The caller commits."""
    from app.database.session import reserve_sqlite_writer
    reserve_sqlite_writer(session)
    result = StatusCheckResult()
    last_id = 0
    while True:
        rows = session.scalars(
            select(Tender)
            .outerjoin(TenderStatusRecord, TenderStatusRecord.tender_id == Tender.id)
            .where(
                Tender.id > last_id,
                or_(TenderStatusRecord.current_status.in_(OPEN_STATES), TenderStatusRecord.tender_id.is_(None)),
            )
            .order_by(Tender.id)
            .limit(batch_size)
        ).all()
        if not rows:
            break
        for tender in rows:
            result.checked += 1
            if apply_current_status(session, tender, now=now):
                result.changed += 1
        last_id = rows[-1].id
        session.flush()
    log_event(logger, logging.INFO, "status_verification_done", checked=result.checked, changed=result.changed)
    return result
