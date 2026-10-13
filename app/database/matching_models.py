"""Seller <-> tender matching results (migration 0018).

One row per (seller, tender) pair that has ever been relevant. The row is
recomputed in place whenever the seller's active profile revision or the
tender's analysed state changes. The immutable per-evaluation history lives in
``eligibility_runs`` and ``eligibility_requirement_results``, which each row
references.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database.models import PK, Base
from app.utils.dates import utcnow


class SellerTenderMatch(Base):
    __tablename__ = "seller_tender_matches"
    __table_args__ = (
        Index("uq_seller_tender_matches_pair", "seller_id", "tender_id", unique=True),
        Index("ix_seller_tender_matches_seller_status", "seller_id", "match_status"),
    )

    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    seller_id: Mapped[int] = mapped_column(PK, ForeignKey("sellers.id", ondelete="CASCADE"), nullable=False)
    tender_id: Mapped[int] = mapped_column(PK, ForeignKey("tenders.id", ondelete="CASCADE"),
                                           nullable=False, index=True)
    seller_revision_id: Mapped[int] = mapped_column(
        PK, ForeignKey("seller_revisions.id", ondelete="CASCADE"), nullable=False)
    eligibility_run_id: Mapped[int | None] = mapped_column(
        PK, ForeignKey("eligibility_runs.id", ondelete="SET NULL"))

    # RELEVANT | NOT_RELEVANT  (deterministic product/service keyword relevance)
    relevance_status: Mapped[str] = mapped_column(String(20), nullable=False)
    # Overall eligibility from the deterministic engine (None when not evaluated)
    eligibility_status: Mapped[str | None] = mapped_column(String(40))
    # MATCHED | NOT_MATCHED | REVIEW_REQUIRED
    match_status: Mapped[str] = mapped_column(String(20), nullable=False)

    matched_terms_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    reasons_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    passed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    review_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    tender_state_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    matcher_version: Mapped[str] = mapped_column(String(20), nullable=False)
    computed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)
