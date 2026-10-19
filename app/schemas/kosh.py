"""Typed empty responses for the Stage 0 business API."""

from typing import Literal

from pydantic import BaseModel, Field


class BusinessDocumentPlaceholder(BaseModel):
    """Future private document response; no records exist in Stage 0."""

    id: int
    filename: str


class KoshPlaceholder(BaseModel):
    """Explicitly empty data, not a computed business result."""

    seller_id: int
    status: Literal["NOT_IMPLEMENTED"] = "NOT_IMPLEMENTED"
    items: list[dict[str, object]] = Field(default_factory=list)


class LedgerResponse(KoshPlaceholder):
    """Reserved ledger response."""


class ForecastResponse(KoshPlaceholder):
    """Reserved forecast response."""


class AlertsResponse(KoshPlaceholder):
    """Reserved alerts response."""


class PlanResponse(KoshPlaceholder):
    """Reserved plan response."""


class ApprovalsResponse(KoshPlaceholder):
    """Reserved approvals response."""


class AuditResponse(KoshPlaceholder):
    """Reserved audit response."""
