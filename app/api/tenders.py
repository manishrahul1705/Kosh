"""Tender read API.

Bid numbers contain "/", so lookups use either the database id
(/api/tenders/by-id/{id}) or a query parameter
(/api/tenders/lookup?bid_number=GEM/2026/B/123) — no fragile path routing.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.api.deps import get_db
from app.core.constants import TenderStatus
from app.database.models import Tender, TenderChange
from app.schemas.tender import TenderChangeOut, TenderOut, TenderPage
from app.utils.bid_number import InvalidBidNumber, normalize_bid_number
from app.utils.dates import to_utc_naive, utcnow

# Central tender database browsing: requires a verified, signed-in user.
router = APIRouter(prefix="/api/tenders", tags=["tenders"], dependencies=[Depends(get_current_user)])

SEARCH_COLUMNS = (
    Tender.bid_number, Tender.title, Tender.category, Tender.buyer_name,
    Tender.ministry, Tender.department, Tender.organisation,
)


def _utc_param(value: datetime | None, name: str) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        raise HTTPException(
            status_code=422,
            detail=f"{name} must include a timezone offset, e.g. 2026-10-04T10:00:00+05:30 or ...Z",
        )
    return to_utc_naive(value)


def _escape_like(term: str) -> str:
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _paginate(db: Session, stmt: Select, page: int, page_size: int) -> TenderPage:
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    rows = db.scalars(stmt.offset((page - 1) * page_size).limit(page_size)).all()
    return TenderPage(
        items=[TenderOut.model_validate(r) for r in rows],
        total=total,
        page=page,
        page_size=page_size,
        pages=math.ceil(total / page_size) if total else 0,
    )


@router.get("", response_model=TenderPage)
def list_tenders(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    status: TenderStatus | None = None,
    bid_type: str | None = Query(None, description="BID or RA"),
    category: str | None = Query(None, description="Case-insensitive substring match"),
    search: str | None = Query(None, min_length=2, max_length=200),
    closing_before: datetime | None = Query(None, description="ISO-8601 with offset"),
    closing_after: datetime | None = Query(None, description="ISO-8601 with offset"),
    new_since: datetime | None = Query(None, description="first_seen_at >= value (ISO-8601 with offset)"),
    db: Session = Depends(get_db),
) -> TenderPage:
    stmt = select(Tender)
    if status is not None:
        stmt = stmt.where(Tender.status == status.value)
    if bid_type:
        stmt = stmt.where(func.upper(Tender.bid_type) == bid_type.strip().upper())
    if category:
        stmt = stmt.where(func.lower(Tender.category).like(f"%{_escape_like(category.lower())}%", escape="\\"))
    if search:
        term = search.strip()
        try:
            canonical = normalize_bid_number(term)
        except InvalidBidNumber:
            canonical = None
        pattern = f"%{_escape_like(term.lower())}%"
        clauses = [func.lower(col).like(pattern, escape="\\") for col in SEARCH_COLUMNS]
        if canonical:
            clauses.append(Tender.bid_number == canonical)
        stmt = stmt.where(or_(*clauses))
    if (cb := _utc_param(closing_before, "closing_before")) is not None:
        stmt = stmt.where(Tender.bid_end_at < cb)
    if (ca := _utc_param(closing_after, "closing_after")) is not None:
        stmt = stmt.where(Tender.bid_end_at > ca)
    if (ns := _utc_param(new_since, "new_since")) is not None:
        stmt = stmt.where(Tender.first_seen_at >= ns)
    stmt = stmt.order_by(Tender.first_seen_at.desc(), Tender.id.desc())
    return _paginate(db, stmt, page, page_size)


@router.get("/new", response_model=TenderPage)
def new_tenders(
    hours: int = Query(24, ge=1, le=24 * 90),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
) -> TenderPage:
    since = utcnow() - timedelta(hours=hours)
    stmt = (
        select(Tender)
        .where(Tender.first_seen_at >= since)
        .order_by(Tender.first_seen_at.desc(), Tender.id.desc())
    )
    return _paginate(db, stmt, page, page_size)


@router.get("/lookup", response_model=TenderOut)
def lookup_by_bid_number(
    bid_number: str = Query(..., description="e.g. GEM/2026/B/8014206 (case/whitespace-insensitive)"),
    db: Session = Depends(get_db),
) -> TenderOut:
    try:
        canonical = normalize_bid_number(bid_number)
    except InvalidBidNumber as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    tender = db.scalar(select(Tender).where(Tender.bid_number == canonical))
    if tender is None:
        raise HTTPException(status_code=404, detail=f"Tender {canonical} not found")
    return TenderOut.model_validate(tender)


@router.get("/by-id/{tender_id}", response_model=TenderOut)
def get_by_id(tender_id: int, db: Session = Depends(get_db)) -> TenderOut:
    tender = db.get(Tender, tender_id)
    if tender is None:
        raise HTTPException(status_code=404, detail="Tender not found")
    return TenderOut.model_validate(tender)


@router.get("/by-id/{tender_id}/changes", response_model=list[TenderChangeOut])
def get_changes(tender_id: int, db: Session = Depends(get_db)) -> list[TenderChangeOut]:
    if db.get(Tender, tender_id) is None:
        raise HTTPException(status_code=404, detail="Tender not found")
    rows = db.scalars(
        select(TenderChange).where(TenderChange.tender_id == tender_id).order_by(TenderChange.id)
    ).all()
    return [TenderChangeOut.model_validate(r) for r in rows]
