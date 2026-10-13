"""Fingerprinting (9), change audit (8), and unchanged/updated classification."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import select

from app.core.constants import Classification, TenderStatus
from app.database.models import Tender, TenderChange
from app.schemas.tender import TenderRecord
from app.services.change_detector import canonical_value, compute_fingerprint, diff_fields
from app.services.tender_service import upsert_record, upsert_records


def rec(**kw) -> TenderRecord:
    base = dict(
        bid_number="GEM/2026/B/700001",
        title="Desktop Computers",
        category="Desktop Computers",
        quantity=11,
        ministry="Ministry of Defence",
        bid_end_at=datetime(2026, 10, 10, 9, 30),
        status=TenderStatus.ONGOING,
        source_url="https://bidplus.gem.gov.in/showbidDocument/1",
    )
    base.update(kw)
    return TenderRecord(**base)


def test_fingerprint_is_stable_sha256():
    fp = compute_fingerprint(rec())
    assert fp == compute_fingerprint(rec())
    assert len(fp) == 64 and all(c in "0123456789abcdef" for c in fp)


def test_fingerprint_changes_with_tracked_fields_only():
    assert compute_fingerprint(rec()) != compute_fingerprint(rec(bid_end_at=datetime(2026, 10, 12, 12, 30)))
    assert compute_fingerprint(rec()) != compute_fingerprint(rec(quantity=12))
    # Identity/bookkeeping fields are not part of the fingerprint.
    assert compute_fingerprint(rec()) == compute_fingerprint(rec(source_internal_id="999"))
    assert compute_fingerprint(rec()) == compute_fingerprint(rec(bid_number="gem/2026/b/700002"))


def test_fingerprint_matches_between_record_and_orm_row(session_factory):
    now = datetime(2026, 10, 4, 5, 0)
    with session_factory() as s:
        upsert_record(s, rec(estimated_value=Decimal("1500.50")), now=now, run_id=None)
        s.commit()
    with session_factory() as s:
        row = s.scalar(select(Tender))
        # Volatile fields excluded: fingerprint of the stored row == record's.
        assert compute_fingerprint(row) == compute_fingerprint(rec(estimated_value=Decimal("1500.5")))
        assert row.source_fingerprint == compute_fingerprint(row)


def test_canonical_values():
    assert canonical_value(None) is None
    assert canonical_value(datetime(2026, 10, 10, 9, 30)) == "2026-10-10T09:30:00Z"
    assert canonical_value(Decimal("100.00")) == "100"
    assert canonical_value(TenderStatus.CLOSED) == "CLOSED"


def test_diff_fields_reports_old_and_new():
    changes = diff_fields(rec(), rec(bid_end_at=datetime(2026, 10, 12, 12, 30), quantity=15))
    assert ("quantity", "11", "15") in changes
    assert ("bid_end_at", "2026-10-10T09:30:00Z", "2026-10-12T12:30:00Z") in changes
    assert len(changes) == 2


def test_new_unchanged_updated_classification_and_audit(session_factory):
    t0, t1, t2 = datetime(2026, 10, 4, 5), datetime(2026, 10, 4, 5, 30), datetime(2026, 10, 4, 6)
    with session_factory() as s:
        assert upsert_record(s, rec(), now=t0, run_id=None) is Classification.NEW
        s.commit()
    with session_factory() as s:
        assert upsert_record(s, rec(bid_number=" gem/2026/b/700001"), now=t1, run_id=None) is Classification.UNCHANGED
        s.commit()
        row = s.scalar(select(Tender))
        assert (row.first_seen_at, row.last_seen_at, row.last_changed_at) == (t0, t1, None)
    with session_factory() as s:
        result = upsert_record(s, rec(title="Desktop Computers (Revised)"), now=t2, run_id=None)
        s.commit()
        assert result is Classification.UPDATED
        row = s.scalar(select(Tender))
        assert row.title == "Desktop Computers (Revised)"
        assert row.last_changed_at == t2 and row.last_seen_at == t2
        ch = s.scalar(select(TenderChange))
        assert (ch.field_name, ch.old_value, ch.new_value, ch.detected_at) == (
            "title", "Desktop Computers", "Desktop Computers (Revised)", t2)
        assert s.scalar(select(Tender.id).where(Tender.bid_number == "GEM/2026/B/700001")) == row.id


def test_upsert_records_summary(session_factory):
    now = datetime(2026, 10, 4, 5)
    with session_factory() as s:
        stats = upsert_records(s, [rec(), rec(bid_number="GEM/2026/B/700002")], now=now, run_id=None)
        s.commit()
    assert stats.as_summary() == {"seen": 2, "new": 2, "updated": 0, "unchanged": 0, "failed": 0}
