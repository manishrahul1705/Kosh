"""Stage 2B: automated DocumentJob processing around the Stage 2A service.

No live GeM: HTTP is served by httpx.MockTransport (FakeGem from the Stage 2A
regression suite) or Stage 2A is replaced by a scripted fake that returns its
documented result contract. Time is controlled through an injectable clock.
"""

from __future__ import annotations

import hashlib
import json
import socket
import threading
from datetime import datetime, timedelta
from pathlib import Path

import httpx
import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError

from app.core.config import Settings
from app.core.constants import TenderStatus, TriggerType
from app.database.models import DocumentJob, DocumentVersion, Tender, TenderDocument
from app.documents import job_queue
from app.documents.documents_service import DocumentsService
from app.documents.job_queue import (
    backfill_jobs,
    enqueue_due_refreshes,
    enqueue_job,
    queue_final_refresh,
)
from app.documents.job_worker import (
    SKIP_BUSY,
    SKIP_COOLDOWN,
    DocumentJobWorker,
    DocumentWorkerBusy,
    compute_job_backoff,
    decide,
)
from app.schemas.documents import DocumentJobReason as R
from app.schemas.tender import TenderRecord
from app.services.tender_service import JobQueuePolicy, close_expired_unseen, upsert_record
from app.utils.dates import utcnow
from tests.conftest import FIXTURES
from tests.test_stage2a_idempotency import PDF_V1, PDF_V2, SOURCE_URL, FakeGem

BID = "GEM/2026/B/8122868"


# ---------------------------------------------------------------------------
# fixtures / helpers
# ---------------------------------------------------------------------------
class Clock:
    def __init__(self) -> None:
        self.now = utcnow()

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kw) -> None:
        self.now += timedelta(**kw)


class FakeService:
    """Stands in for DocumentsService; returns scripted Stage 2A summaries."""

    def __init__(self, *summaries: dict, on_call=None) -> None:
        self.summaries = list(summaries)
        self.calls: list[int] = []
        self.on_call = on_call

    def discover_and_download_tender_documents(self, db, tender_id, page_html=None):
        self.calls.append(tender_id)
        if self.on_call:
            self.on_call(db, tender_id)
        item = self.summaries.pop(0) if len(self.summaries) > 1 else self.summaries[0]
        if isinstance(item, Exception):
            raise item
        return {"tender_id": tender_id, "errors": [], "error": None, **item}


def summary(outcome: str, status: str = "SUCCESS", d=0, dl=0, u=0, f=0, retryable=False, error=None) -> dict:
    return {"outcome": outcome, "status": status, "discovered": d, "downloaded": dl, "unchanged": u,
            "failed": f, "retryable": retryable, "error": error, "errors": [error] if error else []}


OK_DOCS = summary("SUCCESS_WITH_DOCUMENTS", d=1, dl=1)
OK_NONE = summary("SUCCESS_NO_DOCUMENTS")
PARTIAL = summary("SUCCESS_WITH_DOCUMENTS", "PARTIAL_SUCCESS", d=2, dl=1, f=1, retryable=True, error="atc_1: TIMEOUT")
TRANSIENT = summary("TRANSIENT_FAILURE", "FAILED", f=1, retryable=True,
                    error="Document discovery failed after 3 transient attempt(s): reset")
PERMANENT = summary("PERMANENT_FAILURE", "FAILED", f=1, error="HTTP_404")
BLOCKED = summary("BLOCKED_BY_HUMAN_VERIFICATION", "BLOCKED", f=1, error="CAPTCHA")


@pytest.fixture
def wsettings(settings: Settings, tmp_path: Path) -> Settings:
    return settings.model_copy(update={
        "document_storage_path": str(tmp_path / "tenders"),
        "document_max_retries": 3,
        "backoff_base_seconds": 1.0,
        "document_max_attempts": 3,
        "document_retry_backoff_minutes": 15.0,
        "document_retry_max_backoff_minutes": 360.0,
        "document_stale_running_minutes": 30,
        "document_block_cooldown_minutes": 60,
        "document_inter_job_delay_seconds": 0,
        "document_refresh_interval_minutes": 60,
        "document_refresh_batch_size": 10,
        "document_worker_max_jobs_per_run": 1,
    })


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def gem() -> FakeGem:
    return FakeGem()


@pytest.fixture
def stage2a_sleeps() -> list[float]:
    return []


@pytest.fixture
def real_service_factory(wsettings, gem, stage2a_sleeps):
    return lambda: DocumentsService(wsettings, transport=httpx.MockTransport(gem), sleep=stage2a_sleeps.append)


def make_worker(wsettings, session_factory, service, clock, **kw) -> DocumentJobWorker:
    factory = service if callable(service) and not isinstance(service, FakeService) else (lambda: service)
    return DocumentJobWorker(wsettings, session_factory, factory, clock=clock, sleep=lambda s: None, **kw)


def add_tender(db, bid=BID, status="ONGOING", source_url=SOURCE_URL, internal="9988704", **kw) -> Tender:
    t = Tender(bid_number=bid, title="t", status=status, source_fingerprint="fp", first_seen_at=utcnow(),
               last_seen_at=utcnow(), source_internal_id=internal, source_url=source_url, **kw)
    db.add(t)
    db.commit()
    return t


def add_job(db, tender, status="PENDING", reason=R.NEW_TENDER.value, **kw) -> DocumentJob:
    now = utcnow()
    kw.setdefault("created_at", now)
    j = DocumentJob(tender_id=tender.id, status=status, reason=reason, updated_at=now, **kw)
    db.add(j)
    db.commit()
    return j


def fresh(db) -> None:
    """End the session's read transaction so it sees other connections' commits (WAL snapshot)."""
    db.commit()
    db.expire_all()


def job(db, job_id) -> DocumentJob:
    fresh(db)
    return db.get(DocumentJob, job_id)


def jobs_for(db, tender_id) -> list[DocumentJob]:
    fresh(db)
    return list(db.scalars(select(DocumentJob).where(DocumentJob.tender_id == tender_id).order_by(DocumentJob.id)))


def versions(db) -> list[int]:
    fresh(db)
    return sorted(v.version_number for v in db.scalars(select(DocumentVersion)))


def record(bid=BID, status=TenderStatus.ONGOING, title="Title", end=None) -> TenderRecord:
    return TenderRecord(bid_number=bid, title=title, status=status, bid_type="BID",
                        bid_end_at=end or utcnow() + timedelta(days=5), source_internal_id="9988704",
                        source_url=SOURCE_URL)


# ===========================================================================
# 1-2. Stage 1 -> queue
# ===========================================================================
def test_new_tender_creates_exactly_one_job_with_reason_and_id(db, caplog):
    caplog.set_level("INFO")
    upsert_record(db, record(), now=utcnow(), run_id=None)
    db.commit()
    tender = db.scalar(select(Tender))
    js = jobs_for(db, tender.id)
    assert len(js) == 1
    assert (js[0].status, js[0].reason, js[0].attempt_count) == ("PENDING", "NEW_TENDER", 0)
    created = [r.getMessage() for r in caplog.records if r.getMessage().startswith("document_job_created")]
    assert created and "job_id=None" not in created[0] and f"job_id={js[0].id}" in created[0]


def test_repeated_discovery_does_not_duplicate_active_jobs(runner, session_factory, source):
    runner.run(TriggerType.CLI)
    runner.run(TriggerType.CLI)
    source.directory = FIXTURES / "mock_abc" / "b_closing_changed"
    runner.run(TriggerType.CLI)
    with session_factory() as s:
        n_tenders = s.scalar(select(func.count(Tender.id)))
        per_tender = s.execute(select(DocumentJob.tender_id, func.count()).group_by(DocumentJob.tender_id)).all()
        reasons = set(s.scalars(select(DocumentJob.reason)))
    assert n_tenders == 3 and len(per_tender) == 3 and all(n == 1 for _, n in per_tender)
    assert reasons == {"NEW_TENDER"}


def test_auto_download_disabled_queues_nothing(db):
    upsert_record(db, record(), now=utcnow(), run_id=None,
                  queue_policy=JobQueuePolicy(queue_new_tenders=False, queue_final_refresh=False))
    db.commit()
    assert db.scalar(select(func.count(DocumentJob.id))) == 0


def test_queue_failure_never_breaks_stage1(db, monkeypatch, caplog):
    def boom(*a, **k):
        raise RuntimeError("queue down")

    monkeypatch.setattr(job_queue, "enqueue_job", boom)
    caplog.set_level("ERROR")
    result = upsert_record(db, record(), now=utcnow(), run_id=None)
    db.commit()
    assert result.value == "NEW"
    assert db.scalar(select(func.count(Tender.id))) == 1          # tender persisted
    assert db.scalar(select(func.count(DocumentJob.id))) == 0     # no job ...
    assert any("document_job_queue_failed" in r.getMessage() for r in caplog.records)  # ... but visible


# ===========================================================================
# 3-5. claim and success
# ===========================================================================
def test_worker_claims_pending_job_and_commits_running_before_network(db, session_factory, wsettings, clock):
    t = add_tender(db)
    j = add_job(db, t)
    seen = {}

    def inspect(_db, tender_id):
        with session_factory() as other:  # a different connection sees the committed claim
            row = other.get(DocumentJob, j.id)
            seen.update(status=row.status, locked_by=row.locked_by, attempt=row.attempt_count,
                        started=row.started_at)

    svc = FakeService(OK_DOCS, on_call=inspect)
    w = make_worker(wsettings, session_factory, svc, clock)
    batch = w.run_batch()

    assert batch.processed == 1 and svc.calls == [t.id]
    assert seen["status"] == "RUNNING" and seen["locked_by"] == w.worker_id and seen["attempt"] == 1
    assert seen["started"] == clock.now
    final = job(db, j.id)
    assert (final.status, final.attempt_count, final.locked_by) == ("SUCCESS", 1, None)
    assert final.finished_at == clock.now and final.outcome == "SUCCESS_WITH_DOCUMENTS"
    assert json.loads(final.result_summary)["downloaded"] == 1


def test_worker_does_not_hold_sqlite_write_lock_during_stage2a(db, session_factory, wsettings, clock):
    t = add_tender(db)
    add_job(db, t)
    wrote = {}

    def write_elsewhere(_db, tender_id):
        with session_factory() as other:
            other.execute(text("PRAGMA busy_timeout=200"))
            other.add(Tender(bid_number="GEM/2026/B/1", status="ONGOING", source_fingerprint="x",
                             first_seen_at=utcnow(), last_seen_at=utcnow()))
            other.commit()  # would raise "database is locked" if the worker held a write txn
            wrote["ok"] = True

    make_worker(wsettings, session_factory, FakeService(OK_NONE, on_call=write_elsewhere), clock).run_batch()
    assert wrote == {"ok": True}


def test_real_stage2a_success_marks_job_success_and_stores_v1(db, session_factory, wsettings, clock,
                                                              real_service_factory, gem):
    t = add_tender(db)
    j = add_job(db, t)
    batch = make_worker(wsettings, session_factory, real_service_factory, clock).run_batch()
    r = batch.jobs[0]
    assert r.status == "SUCCESS" and r.outcome == "SUCCESS_WITH_DOCUMENTS"
    assert (r.summary["discovered"], r.summary["downloaded"], r.summary["unchanged"], r.summary["failed"]) == (1, 1, 0, 0)
    assert job(db, j.id).status == "SUCCESS" and versions(db) == [1] and gem.calls == 1


# ===========================================================================
# 6-11. result mapping and retry lifecycle
# ===========================================================================
def test_success_no_documents_maps_to_success(db, session_factory, wsettings, clock):
    j = add_job(db, add_tender(db))
    make_worker(wsettings, session_factory, FakeService(OK_NONE), clock).run_batch()
    assert (job(db, j.id).status, job(db, j.id).outcome) == ("SUCCESS", "SUCCESS_NO_DOCUMENTS")


def test_partial_result_maps_to_partial_success(db, session_factory, wsettings, clock):
    j = add_job(db, add_tender(db))
    make_worker(wsettings, session_factory, FakeService(PARTIAL), clock).run_batch()
    final = job(db, j.id)
    assert final.status == "PARTIAL_SUCCESS" and final.error_code == "PARTIAL_TRANSIENT"
    assert "TIMEOUT" in final.error_message and final.next_retry_at is None and final.finished_at


def test_transient_failure_schedules_retry_with_backoff(db, session_factory, wsettings, clock):
    j = add_job(db, add_tender(db))
    make_worker(wsettings, session_factory, FakeService(TRANSIENT), clock).run_batch()
    final = job(db, j.id)
    assert final.status == "RETRY" and final.attempt_count == 1
    assert final.next_retry_at == clock.now + timedelta(minutes=15)
    assert final.finished_at is None and final.locked_by is None and final.error_code == "TRANSIENT_FAILURE"


def test_next_retry_at_is_respected_and_backoff_grows_until_failed(db, session_factory, wsettings, clock):
    j = add_job(db, add_tender(db))
    svc = FakeService(TRANSIENT)
    w = make_worker(wsettings, session_factory, svc, clock)

    w.run_batch()                                   # attempt 1 -> RETRY +15m
    assert w.run_batch().processed == 0             # not due: nothing claimed
    clock.advance(minutes=14)
    assert w.run_batch().processed == 0 and len(svc.calls) == 1
    clock.advance(minutes=2)
    w.run_batch()                                   # attempt 2 -> RETRY +30m
    second = job(db, j.id)
    assert (second.status, second.attempt_count) == ("RETRY", 2)
    assert second.next_retry_at == clock.now + timedelta(minutes=30)
    clock.advance(minutes=29)
    assert w.run_batch().processed == 0
    clock.advance(minutes=2)
    w.run_batch()                                   # attempt 3 -> exhausted -> FAILED
    final = job(db, j.id)
    assert (final.status, final.attempt_count, final.error_code) == ("FAILED", 3, "RETRIES_EXHAUSTED")
    assert final.next_retry_at is None and final.finished_at is not None
    clock.advance(days=1)
    assert w.run_batch().processed == 0 and len(svc.calls) == 3   # FAILED is never auto-retried


def test_backoff_is_capped():
    s = Settings(_env_file=None, document_retry_backoff_minutes=60, document_retry_max_backoff_minutes=90)
    assert compute_job_backoff(1, s) == timedelta(minutes=60)
    assert compute_job_backoff(5, s) == timedelta(minutes=90)


def test_permanent_failure_maps_to_failed(db, session_factory, wsettings, clock):
    j = add_job(db, add_tender(db))
    make_worker(wsettings, session_factory, FakeService(PERMANENT), clock).run_batch()
    final = job(db, j.id)
    assert (final.status, final.error_code, final.attempt_count) == ("FAILED", "PERMANENT_FAILURE", 1)


def test_unexpected_exception_is_retried_not_lost(db, session_factory, wsettings, clock):
    j = add_job(db, add_tender(db))
    make_worker(wsettings, session_factory, FakeService(RuntimeError("bug")), clock).run_batch()
    final = job(db, j.id)
    assert final.status == "RETRY" and final.error_code == "WORKER_EXCEPTION" and "bug" in final.error_message


def test_tender_without_source_url_is_skipped_without_network(db, session_factory, wsettings, clock):
    j = add_job(db, add_tender(db, source_url=None))
    svc = FakeService(OK_DOCS)
    make_worker(wsettings, session_factory, svc, clock).run_batch()
    assert job(db, j.id).status == "SKIPPED" and job(db, j.id).error_code == "NO_SOURCE_URL" and svc.calls == []


def test_decide_unknown_outcome_fails_safely(wsettings):
    d = decide({"outcome": "SOMETHING_NEW", "status": "?"}, 1, wsettings, utcnow())
    assert d.status == "FAILED" and d.error_code == "UNKNOWN_OUTCOME"


# ===========================================================================
# 12-13. CAPTCHA / human verification
# ===========================================================================
@pytest.mark.parametrize("response", [
    httpx.Response(403),
    httpx.Response(200, content=b"<html>Please verify you are human (captcha)</html>",
                   headers={"content-type": "text/html"}),
])
def test_captcha_or_403_maps_to_blocked(db, session_factory, wsettings, clock, real_service_factory, gem,
                                         stage2a_sleeps, response):
    j = add_job(db, add_tender(db))
    gem.script = [response]
    make_worker(wsettings, session_factory, real_service_factory, clock).run_batch()
    final = job(db, j.id)
    assert (final.status, final.outcome) == ("BLOCKED", "BLOCKED_BY_HUMAN_VERIFICATION")
    assert final.next_retry_at is None and gem.calls == 1 and stage2a_sleeps == []


def test_blocked_does_not_retry_and_pauses_all_processing(db, session_factory, wsettings, clock):
    a = add_job(db, add_tender(db, bid="GEM/2026/B/1000001"))
    b = add_job(db, add_tender(db, bid="GEM/2026/B/1000002"))
    svc = FakeService(BLOCKED, OK_DOCS)
    w = make_worker(wsettings, session_factory, svc, clock)

    first = w.run_batch(max_jobs=5)            # blocked -> batch stops immediately
    assert [r.status for r in first.jobs] == ["BLOCKED"] and len(svc.calls) == 1
    clock.advance(minutes=5)
    paused = w.run_batch(max_jobs=5)
    assert paused.skipped_reason == SKIP_COOLDOWN and paused.processed == 0 and len(svc.calls) == 1
    clock.advance(minutes=61)                  # cooldown over: other work resumes...
    resumed = w.run_batch(max_jobs=5)
    assert [r.job_id for r in resumed.jobs] == [b.id]
    assert job(db, a.id).status == "BLOCKED"   # ...but the BLOCKED job itself is never auto-retried
    assert job(db, a.id).attempt_count == 1


# ===========================================================================
# 15-16, 22. stale RUNNING recovery / restart
# ===========================================================================
def test_stale_running_job_from_other_host_is_recovered(db, session_factory, wsettings, clock):
    j = add_job(db, add_tender(db), status="RUNNING", attempt_count=1,
                started_at=clock.now - timedelta(minutes=45), locked_by="other-host:1:abc")
    w = make_worker(wsettings, session_factory, FakeService(OK_DOCS), clock)
    assert w.recover_stale_jobs() == 1
    rec = job(db, j.id)
    assert (rec.status, rec.error_code, rec.locked_by) == ("RETRY", "STALE_RUNNING", None)
    w.run_batch()
    assert (job(db, j.id).status, job(db, j.id).attempt_count) == ("SUCCESS", 2)


def test_stale_running_with_exhausted_attempts_becomes_failed(db, session_factory, wsettings, clock):
    j = add_job(db, add_tender(db), status="RUNNING", attempt_count=3,
                started_at=clock.now - timedelta(hours=2), locked_by=None)
    make_worker(wsettings, session_factory, FakeService(OK_DOCS), clock).recover_stale_jobs()
    assert (job(db, j.id).status, job(db, j.id).error_code) == ("FAILED", "STALE_RUNNING")


def test_non_stale_running_job_is_not_stolen(db, session_factory, wsettings, clock):
    t = add_tender(db)
    running = add_job(db, t, status="RUNNING", attempt_count=1,
                      started_at=clock.now - timedelta(minutes=5), locked_by="other-host:9:live")
    queued = add_job(db, t, status="PENDING", reason=R.FINAL_REFRESH.value)
    svc = FakeService(OK_DOCS)
    w = make_worker(wsettings, session_factory, svc, clock)
    batch = w.run_batch(max_jobs=3)
    assert batch.recovered_stale == 0 and batch.processed == 0 and svc.calls == []
    assert job(db, running.id).status == "RUNNING" and job(db, running.id).locked_by == "other-host:9:live"
    assert job(db, queued.id).status == "PENDING"   # never runs concurrently with the live job


def test_worker_restart_recovers_job_orphaned_on_this_host(db, session_factory, wsettings, clock):
    """Simulate a crash: a previous process on this host claimed the job and died."""
    j = add_job(db, add_tender(db), status="RUNNING", attempt_count=1, started_at=clock.now,
                locked_by=f"{socket.gethostname()}:4242:dead")
    w = make_worker(wsettings, session_factory, FakeService(OK_DOCS), clock)  # "restarted" worker
    batch = w.run_batch()
    assert batch.recovered_stale == 1 and batch.jobs[0].job_id == j.id
    assert (job(db, j.id).status, job(db, j.id).attempt_count) == ("SUCCESS", 2)


def test_app_startup_runs_stale_recovery(settings, session_factory, source, db):
    from fastapi.testclient import TestClient

    from app.main import create_app

    j = add_job(db, add_tender(db), status="RUNNING", attempt_count=1, started_at=utcnow(),
                locked_by=f"{socket.gethostname()}:1:old")
    app = create_app(settings, session_factory=session_factory, collector_factory=source)
    with TestClient(app):
        pass
    assert job(db, j.id).status == "RETRY"


def test_finalize_never_clobbers_a_recovered_job(db, session_factory, wsettings, clock):
    j = add_job(db, add_tender(db))

    def steal(_db, tender_id):
        with session_factory() as other:
            other.execute(text("UPDATE document_jobs SET locked_by='someone-else' WHERE id=:i"), {"i": j.id})
            other.commit()

    batch = make_worker(wsettings, session_factory, FakeService(OK_DOCS, on_call=steal), clock).run_batch()
    assert batch.jobs[0].lease_lost is True
    assert job(db, j.id).status == "RUNNING" and job(db, j.id).locked_by == "someone-else"


# ===========================================================================
# 17. backfill
# ===========================================================================
def test_backfill_is_bounded_resumable_and_never_duplicates(db):
    tenders = [add_tender(db, bid=f"GEM/2026/B/20000{i}") for i in range(5)]
    add_job(db, tenders[0], status="SUCCESS")                       # already has a job
    stored = tenders[1]                                              # already has a stored document
    doc = TenderDocument(tender_id=stored.id, document_key="main_bid", document_type="MAIN_BID",
                         discovered_at=utcnow(), last_seen_at=utcnow())
    db.add(doc)
    db.flush()
    v = DocumentVersion(document_id=doc.id, version_number=1, sha256="a" * 64)
    db.add(v)
    db.flush()
    doc.current_version_id = v.id
    db.commit()

    first = backfill_jobs(db, limit=2)
    db.commit()
    second = backfill_jobs(db, limit=2)
    db.commit()
    third = backfill_jobs(db, limit=2)
    db.commit()
    assert len(first) == 2 and len(second) == 1 and third == []
    queued = {j.tender_id for j in db.scalars(select(DocumentJob).where(DocumentJob.reason == "BACKFILL"))}
    assert queued == {tenders[2].id, tenders[3].id, tenders[4].id}
    assert db.scalar(select(func.count(DocumentJob.id))) == 4


def test_enqueue_is_idempotent_for_same_tender(db):
    t = add_tender(db)
    a = enqueue_job(db, t.id, R.MANUAL)
    b = enqueue_job(db, t.id, R.MANUAL)
    c = enqueue_job(db, t.id, R.PERIODIC_REFRESH)
    db.commit()
    assert a.created and not b.created and not c.created and a.job_id == b.job_id == c.job_id
    assert len(jobs_for(db, t.id)) == 1


# ===========================================================================
# 18-19. periodic refresh
# ===========================================================================
def test_periodic_refresh_queues_only_due_ongoing_tenders(db, wsettings):
    now = utcnow()
    due = add_tender(db, bid="GEM/2026/B/3000001")
    fresh = add_tender(db, bid="GEM/2026/B/3000002")
    closed = add_tender(db, bid="GEM/2026/B/3000003", status="CLOSED")
    never = add_tender(db, bid="GEM/2026/B/3000004")       # no job yet -> backfill, not refresh
    busy = add_tender(db, bid="GEM/2026/B/3000005")
    add_job(db, due, status="SUCCESS", finished_at=now - timedelta(minutes=61))
    add_job(db, fresh, status="SUCCESS", finished_at=now - timedelta(minutes=10))
    add_job(db, closed, status="SUCCESS", finished_at=now - timedelta(days=1))
    add_job(db, busy, status="SUCCESS", finished_at=now - timedelta(days=1))
    add_job(db, busy, status="PENDING", reason="MANUAL")

    assert enqueue_due_refreshes(db, wsettings, now=now) == 1
    db.commit()
    periodic = db.scalars(select(DocumentJob).where(DocumentJob.reason == "PERIODIC_REFRESH")).all()
    assert [j.tender_id for j in periodic] == [due.id]
    assert not jobs_for(db, never.id)


def test_periodic_refresh_does_not_duplicate_and_respects_batch_cap(db, wsettings):
    now = utcnow()
    for i in range(5):
        add_job(db, add_tender(db, bid=f"GEM/2026/B/40000{i}"), status="SUCCESS",
                finished_at=now - timedelta(hours=2 + i))
    capped = wsettings.model_copy(update={"document_refresh_batch_size": 3})
    assert enqueue_due_refreshes(db, capped, now=now) == 3
    db.commit()
    assert enqueue_due_refreshes(db, capped, now=now) == 0      # cap reached, no duplicates
    db.commit()
    assert db.scalar(select(func.count()).select_from(DocumentJob).where(
        DocumentJob.reason == "PERIODIC_REFRESH")) == 3


def test_worker_queue_due_refreshes_records_state(db, session_factory, wsettings, clock):
    add_job(db, add_tender(db), status="SUCCESS", finished_at=clock.now - timedelta(hours=3))
    w = make_worker(wsettings, session_factory, FakeService(OK_DOCS), clock)
    assert w.queue_due_refreshes() == 1 and w.queue_due_refreshes() == 0
    assert w.last_refresh_check_at == clock.now


# ===========================================================================
# 20-21. final refresh on close
# ===========================================================================
def _finish_all(db):
    db.execute(text("UPDATE document_jobs SET status='SUCCESS', finished_at=:n"), {"n": utcnow()})
    db.commit()


def test_ongoing_to_closed_queues_one_final_refresh(db):
    upsert_record(db, record(), now=utcnow(), run_id=None)
    db.commit()
    _finish_all(db)
    upsert_record(db, record(status=TenderStatus.CLOSED), now=utcnow(), run_id=None)
    db.commit()
    tender = db.scalar(select(Tender))
    final = [j for j in jobs_for(db, tender.id) if j.reason == "FINAL_REFRESH"]
    assert len(final) == 1 and final[0].status == "PENDING"


def test_repeated_closed_state_never_queues_more_final_refreshes(db):
    upsert_record(db, record(), now=utcnow(), run_id=None)
    db.commit()
    _finish_all(db)
    for i in range(4):
        upsert_record(db, record(status=TenderStatus.CLOSED, title=f"changed {i}"), now=utcnow(), run_id=None)
        db.commit()
        _finish_all(db)                     # even after the final refresh completed
    tender = db.scalar(select(Tender))
    assert [j.reason for j in jobs_for(db, tender.id)].count("FINAL_REFRESH") == 1
    assert not queue_final_refresh(db, tender.id).created


def test_close_by_deadline_queues_final_refresh_once(db):
    past = utcnow() - timedelta(days=1)
    t = add_tender(db, bid_end_at=past)
    t.last_seen_at = past
    db.commit()
    run_started = utcnow()
    assert close_expired_unseen(db, now=utcnow(), run_started_at=run_started, run_id=None) == 1
    db.commit()
    assert close_expired_unseen(db, now=utcnow(), run_started_at=run_started, run_id=None) == 0
    db.commit()
    assert [j.reason for j in jobs_for(db, t.id)] == ["FINAL_REFRESH"]


def test_final_refresh_upgrades_existing_queued_job_instead_of_duplicating(db):
    t = add_tender(db)
    queued = add_job(db, t, status="PENDING", reason="PERIODIC_REFRESH")
    res = queue_final_refresh(db, t.id)
    db.commit()
    assert not res.created and res.job_id == queued.id
    assert [j.reason for j in jobs_for(db, t.id)] == ["FINAL_REFRESH"]


def test_final_refresh_queues_behind_a_running_job(db, session_factory, wsettings, clock):
    t = add_tender(db)
    add_job(db, t, status="RUNNING", started_at=clock.now, locked_by="other-host:1:x", attempt_count=1)
    assert queue_final_refresh(db, t.id).created
    assert not enqueue_job(db, t.id, R.PERIODIC_REFRESH).created     # periodic does not stack
    db.commit()
    assert sorted(j.status for j in jobs_for(db, t.id)) == ["PENDING", "RUNNING"]


def test_final_refresh_on_close_can_be_disabled(db):
    upsert_record(db, record(), now=utcnow(), run_id=None)
    db.commit()
    _finish_all(db)
    upsert_record(db, record(status=TenderStatus.CLOSED), now=utcnow(), run_id=None,
                  queue_policy=JobQueuePolicy(queue_final_refresh=False))
    db.commit()
    assert db.scalar(select(func.count()).select_from(DocumentJob).where(
        DocumentJob.reason == "FINAL_REFRESH")) == 0


# ===========================================================================
# 23. scheduler / overlap
# ===========================================================================
def test_document_worker_runs_never_overlap(db, session_factory, wsettings, clock):
    from app.scheduler.scheduler import scheduled_document_worker

    j = add_job(db, add_tender(db))
    svc = FakeService(OK_DOCS)
    w = make_worker(wsettings, session_factory, svc, clock)
    other = make_worker(wsettings, session_factory, svc, clock)   # e.g. CLI process on same host

    with w.lock.acquire():
        scheduled_document_worker(w)                 # must not raise, must not process
        assert other.run_batch().skipped_reason == SKIP_BUSY
        with pytest.raises(DocumentWorkerBusy):
            other.run_batch(raise_if_busy=True)
        assert w.is_busy() and other.is_busy()
    assert svc.calls == [] and job(db, j.id).status == "PENDING"
    scheduled_document_worker(w)
    assert job(db, j.id).status == "SUCCESS"


def test_concurrent_batches_process_each_job_once(db, session_factory, wsettings, clock):
    ids = [add_job(db, add_tender(db, bid=f"GEM/2026/B/50000{i}")).id for i in range(4)]
    lock = threading.Lock()
    calls: list[int] = []

    def slow(_db, tender_id):
        with lock:
            calls.append(tender_id)

    workers = [make_worker(wsettings, session_factory, FakeService(OK_DOCS, on_call=slow), clock) for _ in range(3)]
    threads = [threading.Thread(target=w.run_batch, kwargs={"max_jobs": 4}) for w in workers]
    for th in threads:
        th.start()
    for th in threads:
        th.join(30)
    assert len(calls) == len(set(calls)) == 4
    assert all(job(db, i).status == "SUCCESS" and job(db, i).attempt_count == 1 for i in ids)


def test_scheduler_registers_document_jobs_only_when_enabled(settings, session_factory, source):
    from fastapi.testclient import TestClient

    from app.main import create_app
    from app.scheduler.scheduler import DOCUMENT_REFRESH_JOB_ID, DOCUMENT_WORKER_JOB_ID

    base = {"scheduler_enabled": True, "collect_on_startup": False}
    app = create_app(settings.model_copy(update=base), session_factory=session_factory, collector_factory=source)
    with TestClient(app) as c:
        assert app.state.scheduler._scheduler.get_job(DOCUMENT_WORKER_JOB_ID) is None
        assert c.get("/health").json()["document_worker"]["document_scheduler_running"] is False

    enabled = settings.model_copy(update={**base, "document_worker_enabled": True, "document_job_poll_seconds": 30})
    app = create_app(enabled, session_factory=session_factory, collector_factory=source)
    with TestClient(app) as c:
        sched = app.state.scheduler._scheduler
        wjob = sched.get_job(DOCUMENT_WORKER_JOB_ID)
        assert wjob.trigger.interval.total_seconds() == 30 and wjob.max_instances == 1 and wjob.coalesce
        assert sched.get_job(DOCUMENT_REFRESH_JOB_ID).max_instances == 1
        body = c.get("/health").json()["document_worker"]
        assert body["document_worker_enabled"] is True and body["document_scheduler_running"] is True
    assert app.state.document_worker.stop_requested  # shutdown asks the worker to stop


def test_second_scheduler_on_same_host_stays_in_standby(settings, session_factory, source):
    from app.scheduler.scheduler import CollectionScheduler

    s = settings.model_copy(update={"scheduler_enabled": True, "collect_on_startup": False})
    first = CollectionScheduler(s, runner=None)
    second = CollectionScheduler(s, runner=None)
    first.start()
    try:
        second.start()
        assert first.running and not second.running and second.standby
    finally:
        first.shutdown()
        second.shutdown()
    third = CollectionScheduler(s, runner=None)
    third.start()                                   # lock released on shutdown
    assert third.running
    third.shutdown()


# ===========================================================================
# 24-26. API + health/stats
# ===========================================================================
def test_api_documents_jobs_route_is_not_swallowed(client, db):
    from app.api.auth import get_current_user
    from app.core.supabase_auth import AuthenticatedIdentity
    from uuid import uuid4
    subject = str(uuid4())
    identity = AuthenticatedIdentity(
        subject=subject,
        email="document-test@example.com",
        claims={"sub": subject, "role": "authenticated"},
    )
    client.app.dependency_overrides[get_current_user] = lambda: identity

    t = add_tender(db)
    add_job(db, t, reason="NEW_TENDER")
    r = client.get("/api/documents/jobs", params={"page": 1, "page_size": 20})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 1 and body["items"][0]["reason"] == "NEW_TENDER"
    jid = body["items"][0]["id"]
    assert client.get(f"/api/documents/jobs/{jid}").json()["id"] == jid
    assert client.get("/api/documents/jobs/999999").status_code == 404
    assert client.get("/api/documents/jobs", params={"status": "PENDING"}).json()["total"] == 1
    assert client.get("/api/documents/worker").status_code == 200


def test_api_document_by_integer_id_still_works(client, db):
    from app.api.auth import get_current_user
    from app.core.supabase_auth import AuthenticatedIdentity
    from uuid import uuid4
    subject = str(uuid4())
    identity = AuthenticatedIdentity(
        subject=subject,
        email="document-test@example.com",
        claims={"sub": subject, "role": "authenticated"},
    )
    client.app.dependency_overrides[get_current_user] = lambda: identity

    t = add_tender(db)
    d = TenderDocument(tender_id=t.id, document_key="main_bid", document_type="MAIN_BID",
                       discovered_at=utcnow(), last_seen_at=utcnow())
    db.add(d)
    db.commit()
    assert client.get(f"/api/documents/{d.id}").json()["document_key"] == "main_bid"
    assert client.get(f"/api/documents/{d.id}/versions").status_code == 200
    assert client.get("/api/documents/424242").status_code == 404
    assert client.get("/api/documents/not-a-number").status_code == 422


def test_no_static_route_is_shadowed_by_a_dynamic_route(client):
    """Every static path must be matched by its own route, not an earlier {param} route."""
    from starlette.routing import Match

    app = client.app
    routes = [r for r in app.router.routes if hasattr(r, "path_regex")]
    checked = 0
    for route in routes:
        if "{" in route.path:
            continue
        for method in getattr(route, "methods", None) or {"GET"}:
            scope = {"type": "http", "path": route.path, "method": method}
            first = next(r for r in routes if r.matches(scope)[0] == Match.FULL)
            assert first is route, f"{method} {route.path} is shadowed by {first.path}"
            checked += 1
    assert checked >= 5



@pytest.fixture
def authorized_document_client(client, session_factory):
    """Document operator authorized only in the temporary test database."""
    from uuid import uuid4
    from app.api.auth import get_current_user
    from app.core.supabase_auth import AuthenticatedIdentity
    from app.database.auth_models import AppUser
    from app.database.platform_auth_models import PlatformOperatorGrant

    subject = str(uuid4())

    with session_factory() as db:
        user = AppUser(supabase_user_id=subject)
        db.add(user)
        db.flush()

        db.add(
            PlatformOperatorGrant(
                user_id=user.id,
                granted_by_user_id=user.id,
                permission="DOCUMENT_JOBS_MANAGE",
                status="ACTIVE",
            )
        )
        db.commit()

    identity = AuthenticatedIdentity(
        subject=subject,
        email="document-operator-test@example.com",
        claims={"sub": subject, "role": "authenticated"},
    )

    client.app.dependency_overrides[get_current_user] = lambda: identity

    try:
        yield client
    finally:
        client.app.dependency_overrides.pop(get_current_user, None)


def test_refresh_endpoint_is_idempotent(authorized_document_client, db):
    t = add_tender(db)
    a = authorized_document_client.post(f"/api/documents/tenders/{t.id}/documents/refresh").json()
    b = authorized_document_client.post(f"/api/documents/tenders/{t.id}/documents/refresh").json()
    assert a["message"] == "Document refresh queued" and b["message"] == "Document job already in progress"
    assert a["job_id"] == b["job_id"] and len(jobs_for(db, t.id)) == 1
    assert jobs_for(db, t.id)[0].reason == "MANUAL"


def test_retry_failed_requeues_latest_failures_once(authorized_document_client, db):
    failed = add_tender(db, bid="GEM/2026/B/6000001")
    recovered = add_tender(db, bid="GEM/2026/B/6000002")
    blocked = add_tender(db, bid="GEM/2026/B/6000003")
    old = add_job(db, failed, status="FAILED", attempt_count=3)
    add_job(db, recovered, status="FAILED")
    add_job(db, recovered, status="SUCCESS")          # latest is SUCCESS -> not retried
    add_job(db, blocked, status="BLOCKED")
    assert authorized_document_client.post("/api/documents/retry-failed").json() == {"retried": 1}
    assert authorized_document_client.post("/api/documents/retry-failed").json() == {"retried": 0}   # already queued
    js = jobs_for(db, failed.id)
    assert [(j.status, j.reason) for j in js] == [("FAILED", "NEW_TENDER"), ("PENDING", "RETRY")]
    assert js[0].id == old.id and js[0].attempt_count == 3       # history untouched
    assert len(jobs_for(db, blocked.id)) == 1                     # BLOCKED needs explicit opt-in


def test_health_and_stats_report_worker_and_job_states(client, db, settings):
    now = utcnow()
    t = [add_tender(db, bid=f"GEM/2026/B/70000{i}") for i in range(6)]
    add_job(db, t[0], status="PENDING", created_at=now - timedelta(hours=3))
    add_job(db, t[1], status="RUNNING", started_at=now - timedelta(hours=2), locked_by="h:1:x")
    add_job(db, t[2], status="RETRY", next_retry_at=now - timedelta(minutes=1))
    add_job(db, t[3], status="FAILED", finished_at=now)
    add_job(db, t[4], status="BLOCKED", finished_at=now - timedelta(days=2))
    add_job(db, t[5], status="SUCCESS", finished_at=now - timedelta(minutes=5))

    from tests.conftest import sign_in
    sign_in(client.app)
    s = client.get("/api/stats").json()
    client.app.dependency_overrides.clear()
    assert (s["pending_document_jobs"], s["running_document_jobs"], s["retry_document_jobs"],
            s["failed_document_jobs"], s["blocked_document_jobs"], s["stale_running_document_jobs"]) == (1, 1, 1, 1, 1, 1)
    assert s["oldest_pending_document_job_at"].endswith("+00:00")
    assert s["last_successful_document_processing_at"] is not None
    w = s["document_worker"]
    assert w["document_worker_enabled"] is False and w["document_worker_running"] is False
    assert w["retry_jobs_due"] == 1 and w["jobs"]["SUCCESS"] == 1 and w["blocked_cooldown_until"] is None

    h = client.get("/health").json()
    assert h["status"] == "healthy" and h["document_worker"]["stale_running_jobs"] == 1
    assert h["document_worker"]["pending_jobs"] == 1

    worker = client.app.state.document_worker
    with worker.lock.acquire():
        assert client.get("/health").json()["document_worker"]["document_worker_running"] is True


# ===========================================================================
# 27-31. Stage 2A regressions through the worker
# ===========================================================================
def test_worker_repeated_same_pdf_stays_v1_and_reports_unchanged(db, session_factory, wsettings, clock,
                                                                 real_service_factory, gem):
    t = add_tender(db)
    w = make_worker(wsettings, session_factory, real_service_factory, clock)
    add_job(db, t)
    w.run_batch()
    for _ in range(3):
        enqueue_job(db, t.id, R.PERIODIC_REFRESH)
        db.commit()
        r = w.run_batch().jobs[0]
        assert r.status == "SUCCESS"
        assert (r.summary["discovered"], r.summary["downloaded"], r.summary["unchanged"], r.summary["failed"]) == (1, 0, 1, 0)
    assert versions(db) == [1] and gem.calls == 4


def test_worker_changed_bytes_create_next_version_exactly_once(db, session_factory, wsettings, clock,
                                                               real_service_factory, gem):
    t = add_tender(db)
    w = make_worker(wsettings, session_factory, real_service_factory, clock)
    add_job(db, t)
    w.run_batch()
    gem.body = PDF_V2
    for expected_downloaded in (1, 0, 0):
        enqueue_job(db, t.id, R.PERIODIC_REFRESH)
        db.commit()
        assert w.run_batch().jobs[0].summary["downloaded"] == expected_downloaded
    assert versions(db) == [1, 2]
    fresh(db)
    doc = db.scalar(select(TenderDocument))
    assert db.get(DocumentVersion, doc.current_version_id).sha256 == hashlib.sha256(PDF_V2).hexdigest()


def test_worker_network_failure_is_truthful_and_existing_v1_survives(db, session_factory, wsettings, clock,
                                                                    real_service_factory, gem, stage2a_sleeps):
    t = add_tender(db)
    w = make_worker(wsettings, session_factory, real_service_factory, clock)
    add_job(db, t)
    w.run_batch()
    stored = list((Path(wsettings.document_storage_path)).rglob("v1_*"))
    assert len(stored) == 1

    gem.script = [httpx.ConnectError("[WinError 10054] reset")] * 3
    refresh = enqueue_job(db, t.id, R.PERIODIC_REFRESH).job_id
    db.commit()
    r = w.run_batch().jobs[0]
    assert r.status == "RETRY" and r.outcome == "TRANSIENT_FAILURE"
    assert (r.summary["discovered"], r.summary["downloaded"], r.summary["unchanged"], r.summary["failed"]) == (0, 0, 0, 1)
    assert stage2a_sleeps[-2:] == [1.0, 2.0]          # Stage 2A per-request retries unchanged (3 attempts)
    assert versions(db) == [1] and stored[0].read_bytes() == PDF_V1
    assert job(db, refresh).next_retry_at == clock.now + timedelta(minutes=15)

    clock.advance(minutes=16)                          # internet back
    r2 = w.run_batch().jobs[0]
    assert r2.job_id == refresh and r2.status == "SUCCESS" and r2.summary["unchanged"] == 1
    assert versions(db) == [1]


# ===========================================================================
# 32. SQLite-safe constraints
# ===========================================================================
def test_db_rejects_second_queued_job_for_same_tender(session_factory, db):
    t = add_tender(db)
    add_job(db, t, status="PENDING")
    with session_factory() as s:
        s.add(DocumentJob(tender_id=t.id, status="RETRY", created_at=utcnow(), updated_at=utcnow()))
        with pytest.raises(IntegrityError):
            s.commit()
    with session_factory() as s:                      # terminal/running rows are unrestricted
        for st in ("SUCCESS", "FAILED", "RUNNING"):
            s.add(DocumentJob(tender_id=t.id, status=st, created_at=utcnow(), updated_at=utcnow()))
        s.commit()


def test_db_rejects_duplicate_version_number_and_hash(session_factory, db):
    t = add_tender(db)
    with session_factory() as s:
        d = TenderDocument(tender_id=t.id, document_key="main_bid", document_type="MAIN_BID",
                           discovered_at=utcnow(), last_seen_at=utcnow())
        s.add(d)
        s.flush()
        s.add(DocumentVersion(document_id=d.id, version_number=1, sha256="a" * 64))
        s.commit()
        doc_id = d.id
    for vn, sha in ((1, "b" * 64), (2, "a" * 64)):
        with session_factory() as s:
            s.add(DocumentVersion(document_id=doc_id, version_number=vn, sha256=sha))
            with pytest.raises(IntegrityError):
                s.commit()


def test_stage2a_linked_document_fetch_does_not_hold_sqlite_write_lock(db, session_factory, wsettings):
    """Non-direct-PDF path: DocumentsService must not keep a write txn open during the HTTP fetch."""
    t = add_tender(db, source_url="https://bidplus.gem.gov.in/showbidDocument/1", internal="1")
    observed = {}

    def handler(request):
        try:
            with session_factory() as other:
                other.execute(text("PRAGMA busy_timeout=200"))
                other.add(Tender(bid_number="GEM/2026/B/2", status="ONGOING", source_fingerprint="x",
                                 first_seen_at=utcnow(), last_seen_at=utcnow()))
                other.commit()
            observed["write"] = "ok"
        except Exception as exc:  # pragma: no cover - this is the regression
            observed["write"] = repr(exc)
        return httpx.Response(200, content=PDF_V1, headers={"content-type": "application/pdf"})

    svc = DocumentsService(wsettings, transport=httpx.MockTransport(handler), sleep=lambda s: None)
    with session_factory() as s:
        r = svc.discover_and_download_tender_documents(s, t.id, '<a href="/files/atc_doc.pdf">Buyer Added ATC</a>')
    assert observed == {"write": "ok"}
    assert (r["status"], r["downloaded"], r["failed"]) == ("SUCCESS", 1, 0) and versions(db) == [1]


def test_scheduled_worker_yields_while_stage1_collection_runs(db, session_factory, wsettings, clock, runner):
    from app.scheduler.scheduler import scheduled_document_worker

    j = add_job(db, add_tender(db))
    svc = FakeService(OK_DOCS)
    w = make_worker(wsettings, session_factory, svc, clock)
    with runner.lock.acquire():
        scheduled_document_worker(w, runner)
    assert svc.calls == [] and job(db, j.id).status == "PENDING"
    scheduled_document_worker(w, runner)
    assert job(db, j.id).status == "SUCCESS"
