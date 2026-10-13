"""Deterministic tender status: LIVE / UPCOMING / CLOSED / CANCELLED / UNKNOWN.

No LLM is involved. The status is derived from the source status, the
deadline and the clock."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from app.core.constants import TenderStatus
from app.database.models import Tender, TenderChange, TenderStatusEvent, TenderStatusRecord
from app.schemas.tender import TenderRecord
from app.services.status_service import CurrentStatus, derive_current_status, verify_statuses
from app.services.tender_service import upsert_record

NOW = datetime(2026, 10, 10, 12, 0, 0)


@pytest.mark.parametrize("source,end,published,expected,reason", [
    ("ONGOING", NOW + timedelta(days=2), None, CurrentStatus.LIVE, "SOURCE_LISTING"),
    ("ONGOING", NOW - timedelta(minutes=1), None, CurrentStatus.CLOSED, "DEADLINE_PASSED"),   # expired
    ("ONGOING", NOW, None, CurrentStatus.CLOSED, "DEADLINE_PASSED"),                           # boundary
    ("CANCELLED", NOW + timedelta(days=2), None, CurrentStatus.CANCELLED, "SOURCE_CANCELLED"),
    ("CANCELLED", NOW - timedelta(days=2), None, CurrentStatus.CANCELLED, "SOURCE_CANCELLED"),
    ("CLOSED", NOW + timedelta(days=2), None, CurrentStatus.CLOSED, "SOURCE_CLOSED"),
    ("ONGOING", NOW + timedelta(days=5), NOW + timedelta(days=1), CurrentStatus.UPCOMING, "PUBLICATION_PENDING"),
    ("ONGOING", None, None, CurrentStatus.LIVE, "SOURCE_LISTING_NO_DEADLINE"),
    ("UNKNOWN", NOW + timedelta(days=2), None, CurrentStatus.UNKNOWN, "SOURCE_STATUS_UNKNOWN"),
    ("UNKNOWN", None, None, CurrentStatus.UNKNOWN, "SOURCE_STATUS_UNKNOWN"),
])
def test_derive_current_status(source, end, published, expected, reason):
    assert derive_current_status(source, end, published, NOW) == (expected, reason)


def _record(bid: str, end: datetime | None, status: TenderStatus = TenderStatus.ONGOING) -> TenderRecord:
    return TenderRecord(bid_number=bid, title="Laptop supply", category="Laptop", bid_end_at=end, status=status)


def _status(db, tender_id: int) -> TenderStatusRecord:
    return db.get(TenderStatusRecord, tender_id)


def test_new_tender_gets_status_and_initial_history(db):
    upsert_record(db, _record("GEM/2026/B/7100001", NOW + timedelta(days=3)), now=NOW, run_id=None)
    db.commit()
    t = db.scalar(select(Tender).where(Tender.bid_number == "GEM/2026/B/7100001"))
    rec = _status(db, t.id)
    assert (rec.current_status, rec.status_source, rec.last_status_check_at) == ("LIVE", "SOURCE_LISTING", NOW)
    events = db.scalars(select(TenderStatusEvent).where(TenderStatusEvent.tender_id == t.id)).all()
    assert [(e.old_status, e.new_status) for e in events] == [(None, "LIVE")]
    # Source-field history is untouched by derived-status bookkeeping
    assert db.scalars(select(TenderChange).where(TenderChange.tender_id == t.id)).all() == []


def test_expiry_detected_between_collections_without_llm_or_source(db):
    """A tender still listed ONGOING at source but past its deadline is CLOSED by the periodic check."""
    upsert_record(db, _record("GEM/2026/B/7100002", NOW + timedelta(hours=1)), now=NOW, run_id=None)
    db.commit()
    later = NOW + timedelta(hours=2)
    result = verify_statuses(db, now=later)
    db.commit()
    t = db.scalar(select(Tender).where(Tender.bid_number == "GEM/2026/B/7100002"))
    assert t.status == "ONGOING"                       # raw source value is not rewritten
    assert t.current_status == "CLOSED" and t.status_source == "DEADLINE_PASSED"
    assert result.changed == 1
    again = verify_statuses(db, now=later)             # idempotent; CLOSED is final until new source data
    assert again.changed == 0 and again.checked == 0


def test_extended_deadline_reopens_tender_and_records_history(db):
    bid = "GEM/2026/B/7100003"
    upsert_record(db, _record(bid, NOW - timedelta(hours=1)), now=NOW, run_id=None)
    db.commit()
    t = db.scalar(select(Tender).where(Tender.bid_number == bid))
    assert t.current_status == "CLOSED"
    # Corrigendum: GeM lists the bid again with an extended deadline
    upsert_record(db, _record(bid, NOW + timedelta(days=4)), now=NOW + timedelta(minutes=5), run_id=None)
    db.commit()
    db.refresh(t)
    assert t.current_status == "LIVE" and t.bid_end_at == NOW + timedelta(days=4)
    events = db.scalars(select(TenderStatusEvent).where(TenderStatusEvent.tender_id == t.id)
                        .order_by(TenderStatusEvent.id)).all()
    assert [(e.old_status, e.new_status, e.status_source) for e in events] == [
        (None, "CLOSED", "DEADLINE_PASSED"), ("CLOSED", "LIVE", "SOURCE_LISTING")]
    changes = db.scalars(select(TenderChange).where(TenderChange.tender_id == t.id)).all()
    assert [c.field_name for c in changes] == ["bid_end_at"]   # what changed at the source, and when


def test_cancelled_tender(db):
    upsert_record(db, _record("GEM/2026/B/7100004", NOW + timedelta(days=3), TenderStatus.CANCELLED),
                  now=NOW, run_id=None)
    db.commit()
    t = db.scalar(select(Tender).where(Tender.bid_number == "GEM/2026/B/7100004"))
    assert t.current_status == "CANCELLED"
    assert verify_statuses(db, now=NOW + timedelta(days=10)).checked == 0   # final state, not rechecked


def test_unknown_source_status_stays_unknown_and_is_rechecked(db):
    upsert_record(db, _record("GEM/2026/B/7100005", None, TenderStatus.UNKNOWN), now=NOW, run_id=None)
    db.commit()
    t = db.scalar(select(Tender).where(Tender.bid_number == "GEM/2026/B/7100005"))
    assert t.current_status == "UNKNOWN"
    r = verify_statuses(db, now=NOW + timedelta(hours=1))
    assert r.checked == 1 and r.changed == 0


def test_tender_without_status_row_is_backfilled_by_check(db):
    """Rows written by older code (no tender_status row yet) are picked up."""
    db.add(Tender(bid_number="GEM/2026/B/7100006", status="ONGOING", bid_end_at=NOW + timedelta(days=1),
                  source_fingerprint="x", first_seen_at=NOW, last_seen_at=NOW))
    db.commit()
    r = verify_statuses(db, now=NOW)
    db.commit()
    t = db.scalar(select(Tender).where(Tender.bid_number == "GEM/2026/B/7100006"))
    assert r.checked == 1 and t.current_status == "LIVE"


def test_migration_backfill_matches_service_rules(tmp_path):
    """Existing tenders get a status row from migration 0018 using the same precedence."""
    import sqlite3

    from alembic import command
    from tests.test_stage2b_migration_cli import alembic_cfg

    db = tmp_path / "m.db"
    cfg = alembic_cfg(db)
    command.upgrade(cfg, "0017_tender_analysis_read_permission")
    con = sqlite3.connect(db)
    rows = [  # (bid, status, bid_end_at, expected)
        ("GEM/2026/B/1", "ONGOING", "2099-01-01 00:00:00.000000", "LIVE"),
        ("GEM/2026/B/2", "ONGOING", "2000-01-01 00:00:00.000000", "CLOSED"),
        ("GEM/2026/B/3", "CANCELLED", "2099-01-01 00:00:00.000000", "CANCELLED"),
        ("GEM/2026/B/4", "UNKNOWN", None, "UNKNOWN"),
    ]
    for i, (bid, st, end, _) in enumerate(rows, start=1):
        con.execute("INSERT INTO tenders (id, bid_number, status, bid_end_at, first_seen_at, last_seen_at, "
                    "source_fingerprint, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
                    (i, bid, st, end, "2026-01-01", "2026-01-01", "fp", "2026-01-01", "2026-01-01"))
    con.commit()
    con.close()
    command.upgrade(cfg, "head")
    con = sqlite3.connect(db)
    got = dict(con.execute("SELECT tender_id, current_status FROM tender_status").fetchall())
    assert got == {i: r[3] for i, r in enumerate(rows, start=1)}
    assert con.execute("SELECT COUNT(*) FROM tender_status_events").fetchone()[0] == 4
    con.close()
    command.downgrade(cfg, "0017_tender_analysis_read_permission")   # additive migration is reversible
    con = sqlite3.connect(db)
    assert con.execute("SELECT COUNT(*) FROM tenders").fetchone()[0] == 4
    con.close()


def test_scheduler_registers_status_and_matching_jobs(settings, session_factory, source):
    from fastapi.testclient import TestClient

    from app.main import create_app
    from app.scheduler.scheduler import MATCHING_JOB_ID, STATUS_VERIFICATION_JOB_ID

    base = {"scheduler_enabled": True, "collect_on_startup": False}
    app = create_app(settings.model_copy(update=base), session_factory=session_factory, collector_factory=source)
    with TestClient(app):
        sched = app.state.scheduler._scheduler
        status_job, match_job = sched.get_job(STATUS_VERIFICATION_JOB_ID), sched.get_job(MATCHING_JOB_ID)
        assert status_job.trigger.interval.total_seconds() == 15 * 60 and status_job.max_instances == 1
        assert match_job.trigger.interval.total_seconds() == 15 * 60 and match_job.coalesce
    off = settings.model_copy(update={**base, "matching_enabled": False})
    app = create_app(off, session_factory=session_factory, collector_factory=source)
    with TestClient(app):
        assert app.state.scheduler._scheduler.get_job(MATCHING_JOB_ID) is None


def test_scheduled_job_bodies_never_raise(session_factory):
    from app.scheduler.scheduler import scheduled_matching, scheduled_status_verification

    def broken():
        raise RuntimeError("db down")

    scheduled_status_verification(broken)      # logged, not raised
    scheduled_matching(broken, 10)
    scheduled_status_verification(session_factory)
    scheduled_matching(session_factory, 10)
