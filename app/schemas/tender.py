"""Tender schemas: the normalized internal TenderRecord and API models."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator

from app.core.constants import TenderStatus
from app.utils.bid_number import normalize_bid_number
from app.utils.dates import as_aware_utc


class TenderRecord(BaseModel):
    """Source-independent tender representation produced by every collector.

    All datetimes are naive UTC. Unknown values stay None — never invented.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    bid_number: str
    title: str | None = None
    bid_type: str | None = None
    buyer_name: str | None = None
    ministry: str | None = None
    department: str | None = None
    organisation: str | None = None
    category: str | None = None
    quantity: int | None = Field(default=None, ge=0)
    estimated_value: Decimal | None = None
    published_at: datetime | None = None
    bid_end_at: datetime | None = None
    bid_opening_at: datetime | None = None
    source_url: str | None = None
    status: TenderStatus = TenderStatus.UNKNOWN
    # Source-side identifier (GeM internal b_id). Not part of change tracking;
    # useful for Stage 2 document retrieval.
    source_internal_id: str | None = None

    @field_validator("bid_number", mode="before")
    @classmethod
    def _canonical_bid(cls, v: object) -> str:
        return normalize_bid_number(v)

    @field_validator(
        "title", "bid_type", "buyer_name", "ministry", "department",
        "organisation", "category", "source_url", "source_internal_id",
        mode="before",
    )
    @classmethod
    def _clean_text(cls, v: object) -> str | None:
        if v is None:
            return None
        text = " ".join(str(v).split())
        return text or None

    @field_validator("published_at", "bid_end_at", "bid_opening_at")
    @classmethod
    def _naive_utc(cls, v: datetime | None) -> datetime | None:
        if v is not None and v.tzinfo is not None:
            raise ValueError("TenderRecord datetimes must be naive UTC")
        return v


class TenderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    bid_number: str
    title: str | None
    bid_type: str | None
    buyer_name: str | None
    ministry: str | None
    department: str | None
    organisation: str | None
    category: str | None
    quantity: int | None
    estimated_value: Decimal | None
    published_at: datetime | None
    bid_end_at: datetime | None
    bid_opening_at: datetime | None
    source_url: str | None
    source_internal_id: str | None
    status: str
    current_status: str = "UNKNOWN"
    status_source: str | None = None
    last_status_check_at: datetime | None = None
    first_seen_at: datetime
    last_seen_at: datetime
    last_changed_at: datetime | None
    created_at: datetime
    updated_at: datetime

    @field_serializer(
        "published_at", "bid_end_at", "bid_opening_at", "first_seen_at",
        "last_seen_at", "last_changed_at", "created_at", "updated_at", "last_status_check_at",
    )
    def _ser_dt(self, v: datetime | None) -> str | None:
        aware = as_aware_utc(v)
        return aware.isoformat() if aware else None


class TenderPage(BaseModel):
    items: list[TenderOut]
    total: int
    page: int
    page_size: int
    pages: int


class TenderChangeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tender_id: int
    field_name: str
    old_value: str | None
    new_value: str | None
    detected_at: datetime
    collection_run_id: int | None

    @field_serializer("detected_at")
    def _ser_dt(self, v: datetime) -> str:
        return as_aware_utc(v).isoformat()  # type: ignore[union-attr]
