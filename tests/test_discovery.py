"""Discovery runs end-to-end against fixtures: pagination, dedup, the mock
A/B/C scenario, failed items, blocking, locking and HTTP retry behaviour."""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest
from sqlalchemy import func, select

from app.collectors.base import BlockedError, CollectorError
from app.collectors.gem_collector import GemListingCollector, PaginationLimits
from app.collectors.http_collector import HttpTransport, backoff_delay, parse_retry_after
from app.core.constants import RunStatus, TriggerType
from app.database.models import CollectionRun, Tender, TenderChange
from app.services.discovery_service import CollectionAlreadyRunning
from tests.conftest import FIXTURES, ORIGIN, fixture_collector


def _count(factory, model) -> int:
    with factory() as s:
        return s.scalar(select(func.count()).select_from(model))


def _write_pages(directory: Path, pages: list[list[str]], total: int | None = None) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    template = json.loads((FIXTURES / "mock_abc" / "initial" / "page_1.json").read_text())
    base_doc = template["response"]["response"]["docs"][0]
    n_total = total if total is not None else sum(len(p) for p in pages)
    for i, bids in enumerate(pages, start=1):
        docs = []
        for bid in bids:
            d = json.loads(json.dumps(base_doc))
            d["b_bid_number"] = [bid]
            d["b_id"] = [int(bid.rsplit("/", 1)[1])]
            docs.append(d)
        page = {"code": 200, "response": {"response": {"numFound": n_total, "docs": docs}}}
        (directory / f"page_{i}.json").write_text(json.dumps(page))
    return directory


# --- 3. Pagination -----------------------------------------------------------
def test_pagination_walks_all_pages(tmp_path):
    pages = [[f"GEM/2026/B/{1000 + p * 10 + i}" for i in range(10)] for p in range(3)]
    pages[2] = pages[2][:5]
    d = _write_pages(tmp_path / "pg", pages)
    result = fixture_collector(d).discover_live_tenders()
    assert result.pages_checked == 3
    assert len(result.records) == 25
    assert result.reported_total == 25
    assert not result.truncated


def test_pagination_stops_on_empty_page_without_total(tmp_path):
    pages = [[f"GEM/2026/B/{2000 + p * 10 + i}" for i in range(10)] for p in range(2)]
    d = _write_pages(tmp_path / "pg", pages, total=0)  # total unknown/unhelpful
    for f in d.glob("*.json"):
        data = json.loads(f.read_text())
        data["response"]["response"].pop("numFound")
        f.write_text(json.dumps(data))
    result = fixture_collector(d).discover_live_tenders()
    assert len(result.records) == 20
    assert result.pages_checked == 3  # third request returned no docs


def test_default_fixture_two_pages():
    result = fixture_collector(FIXTURES / "default").discover_live_tenders()
    assert result.pages_checked == 2
    assert len(result.records) == 13
    assert any(r.bid_type == "RA" for r in result.records)


def test_max_pages_safety_limit(tmp_path):
    pages = [[f"GEM/2026/B/{3000 + p * 10 + i}" for i in range(10)] for p in range(5)]
    d = _write_pages(tmp_path / "pg", pages)
    result = fixture_collector(d, max_pages=2).discover_live_tenders()
    assert result.pages_checked == 2 and len(result.records) == 20 and result.truncated


def test_delay_applied_between_pages(tmp_path):
    pages = [[f"GEM/2026/B/{4000 + p * 10 + i}" for i in range(10)] for p in range(3)]
    d = _write_pages(tmp_path / "pg", pages)
    from app.collectors.fixture_collector import FixtureTransport

    sleeps: list[float] = []
    col = GemListingCollector(FixtureTransport(d), source_origin=ORIGIN,
                              limits=PaginationLimits(max_pages=10, delay_seconds=2.0), sleep=sleeps.append)
    col.discover_live_tenders()
    assert sleeps == [2.0, 2.0]


# --- 4. Duplicate detection ---------------------------------------------------
def test_duplicates_across_pages_and_casing_collapse(tmp_path):
    d = _write_pages(tmp_path / "dup", [["GEM/2026/B/5001", "gem/2026/b/5002"], [" GEM/2026/B/5002", "GEM/2026/B/5003"]], total=4)
    result = fixture_collector(d).discover_live_tenders()
    assert [r.bid_number for r in result.records] == ["GEM/2026/B/5001", "GEM/2026/B/5002", "GEM/2026/B/5003"]
    assert result.duplicates_skipped == 1


# --- 24. Mock test: A/B/C over three runs (also 5, 6, 7, 8) ------------------
def test_mock_abc_three_runs(runner, source, session_factory):
    r1 = runner.run(TriggerType.CLI)
    assert (r1.new_bids, r1.updated_bids, r1.unchanged_bids, r1.failed_items) == (3, 0, 0, 0)
    assert r1.status == RunStatus.SUCCESS.value
    assert _count(session_factory, Tender) == 3

    r2 = runner.run(TriggerType.CLI)
    assert (r2.new_bids, r2.updated_bids, r2.unchanged_bids) == (0, 0, 3)
    assert _count(session_factory, Tender) == 3  # no duplicates

    source.directory = FIXTURES / "mock_abc" / "b_closing_changed"
    r3 = runner.run(TriggerType.CLI)
    assert (r3.new_bids, r3.updated_bids, r3.unchanged_bids) == (0, 1, 2)

    with session_factory() as s:
        changes = s.scalars(select(TenderChange)).all()
        assert len(changes) == 1
        ch = changes[0]
        assert ch.field_name == "bid_end_at"
        assert ch.old_value == "2026-10-10T09:30:00Z"   # 15:00 IST
        assert ch.new_value == "2026-10-12T12:30:00Z"   # 18:00 IST
        assert ch.collection_run_id == r3.run_id
        b = s.scalar(select(Tender).where(Tender.bid_number == "GEM/2026/B/8100102"))
        assert b.bid_end_at == datetime(2026, 10, 12, 12, 30)
        assert b.last_changed_at is not None
        assert b.first_seen_at < b.last_seen_at
        a = s.scalar(select(Tender).where(Tender.bid_number == "GEM/2026/B/8100101"))
        assert a.last_changed_at is None
        runs = s.scalars(select(CollectionRun).order_by(CollectionRun.id)).all()
        assert [r.status for r in runs] == ["SUCCESS"] * 3
        assert [r.trigger_type for r in runs] == ["cli"] * 3


# --- 15. Failed-item handling --------------------------------------------------
def test_failed_items_do_not_abort_run(runner, source, session_factory):
    source.directory = FIXTURES / "malformed"
    r = runner.run(TriggerType.CLI)
    assert r.new_bids == 3 and r.failed_items == 2
    assert r.status == RunStatus.PARTIAL_SUCCESS.value
    assert "invalid bid number" in (r.error_message or "")
    assert _count(session_factory, Tender) == 3


def test_persist_failure_isolated_per_record(runner, session_factory, monkeypatch):
    import app.services.tender_service as ts

    original = ts.upsert_record

    def flaky(session, record, **kw):
        if record.bid_number.endswith("8100102"):
            raise RuntimeError("simulated DB problem")
        return original(session, record, **kw)

    monkeypatch.setattr(ts, "upsert_record", flaky)
    r = runner.run(TriggerType.CLI)
    assert (r.new_bids, r.failed_items) == (2, 1)
    assert _count(session_factory, Tender) == 2


# --- Blocking ---------------------------------------------------------------------
def test_captcha_stops_run_with_blocked_status(runner, source, session_factory):
    source.directory = FIXTURES / "blocked"
    r = runner.run(TriggerType.CLI)
    assert r.status == RunStatus.BLOCKED_BY_HUMAN_VERIFICATION.value
    assert r.pages_checked == 1
    assert r.new_bids == 10  # page 1 data kept
    assert "BLOCKED_BY_HUMAN_VERIFICATION" in r.error_message


def test_collector_crash_marks_run_failed(settings, session_factory):
    from app.services.discovery_service import CollectionRunner

    def boom():
        raise RuntimeError("cannot build collector")

    r = CollectionRunner(settings, session_factory, boom).run(TriggerType.CLI)
    assert r.status == RunStatus.FAILED.value
    with session_factory() as s:
        run = s.get(CollectionRun, r.run_id)
        assert run.status == "FAILED" and "cannot build collector" in run.error_message


def test_interrupted_runs_recovered(runner, session_factory):
    with session_factory() as s:
        s.add(CollectionRun(status="RUNNING", trigger_type="scheduled"))
        s.commit()
    assert runner.recover_interrupted_runs() == 1
    with session_factory() as s:
        assert s.scalar(select(CollectionRun.status)) == "FAILED"


# --- Status: deadline-based closing --------------------------------------------
def test_expired_unseen_tender_closed_but_never_cancelled(runner, source, session_factory, tmp_path):
    runner.run(TriggerType.CLI)
    with session_factory() as s:
        a = s.scalar(select(Tender).where(Tender.bid_number == "GEM/2026/B/8100101"))
        a.bid_end_at = datetime(2020, 1, 1)
        s.commit()
    # A disappears from the listing; B and C still listed.
    data = json.loads((FIXTURES / "mock_abc" / "initial" / "page_1.json").read_text())
    data["response"]["response"]["docs"] = data["response"]["response"]["docs"][1:]
    data["response"]["response"]["numFound"] = 2
    d = tmp_path / "bc"
    d.mkdir()
    (d / "page_1.json").write_text(json.dumps(data))
    source.directory = d
    r = runner.run(TriggerType.CLI)
    assert r.closed_by_deadline == 1
    with session_factory() as s:
        statuses = dict(s.execute(select(Tender.bid_number, Tender.status)).all())
    assert statuses["GEM/2026/B/8100101"] == "CLOSED"
    assert "CANCELLED" not in statuses.values()


def test_missing_but_not_expired_is_untouched(runner, source, session_factory, tmp_path):
    runner.run(TriggerType.CLI)
    with session_factory() as s:  # keep the test independent of today's date
        for t in s.scalars(select(Tender)).all():
            t.bid_end_at = datetime(2099, 1, 1)
        s.commit()
    d = tmp_path / "empty"
    d.mkdir()
    source.directory = d  # listing returns nothing
    runner.run(TriggerType.CLI)
    with session_factory() as s:
        assert set(s.scalars(select(Tender.status)).all()) == {"ONGOING"}


# --- 14. Concurrent run protection ----------------------------------------------
def test_concurrent_runs_rejected(runner, settings, session_factory):
    started, release = threading.Event(), threading.Event()

    class SlowCollector:
        def discover_live_tenders(self):
            started.set()
            release.wait(10)
            from app.collectors.base import CollectorResult
            return CollectorResult()

    runner.collector_factory = SlowCollector
    t = threading.Thread(target=runner.run, args=(TriggerType.SCHEDULED,))
    t.start()
    assert started.wait(5)
    with pytest.raises(CollectionAlreadyRunning):
        runner.run(TriggerType.MANUAL)
    # A second runner (e.g. the CLI process) sharing the lock file is refused too.
    from app.services.discovery_service import CollectionRunner
    from app.services.run_lock import CollectionLock

    other = CollectionRunner(settings, session_factory, SlowCollector, CollectionLock(settings.resolve_path(settings.lock_file)))
    with pytest.raises(CollectionAlreadyRunning):
        other.run(TriggerType.CLI)
    release.set()
    t.join(10)
    assert not runner.is_running()


# --- 19/20. HTTP transport: retries, Retry-After, blocking ---------------------------
LISTING_HTML = (FIXTURES / "listing_shell.html").read_text()
GOOD_PAGE = (FIXTURES / "mock_abc" / "initial" / "page_1.json").read_text()


def _http_transport(settings, handler, sleeps):
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return HttpTransport(settings, client=client, sleep=sleeps.append)


def test_http_transport_happy_path_sends_token_and_ongoing_filter(settings):
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        if req.method == "GET":
            return httpx.Response(200, text=LISTING_HTML)
        return httpx.Response(200, text=GOOD_PAGE)

    t = _http_transport(settings, handler, [])
    data = t.fetch_page(1)
    assert data["response"]["response"]["numFound"] == 3
    body = seen[1].content.decode()
    assert "csrf_bd_gem_nk=a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6" in body
    assert "ongoing_bids" in httpx.QueryParams(body)["payload"]
    assert seen[1].url == httpx.URL(settings.resolved_data_url)


def test_http_retries_5xx_with_exponential_backoff(settings):
    settings = settings.model_copy(update={"backoff_base_seconds": 2.0, "max_retries": 3})
    calls = {"post": 0}

    def handler(req):
        if req.method == "GET":
            return httpx.Response(200, text=LISTING_HTML)
        calls["post"] += 1
        if calls["post"] <= 3:
            return httpx.Response(503)
        return httpx.Response(200, text=GOOD_PAGE)

    sleeps: list[float] = []
    t = _http_transport(settings, handler, sleeps)
    assert t.fetch_page(1)["code"] == 200
    assert sleeps == [2.0, 4.0, 8.0]


def test_http_respects_retry_after(settings):
    settings = settings.model_copy(update={"backoff_base_seconds": 2.0})
    calls = {"post": 0}

    def handler(req):
        if req.method == "GET":
            return httpx.Response(200, text=LISTING_HTML)
        calls["post"] += 1
        if calls["post"] == 1:
            return httpx.Response(429, headers={"Retry-After": "30"})
        return httpx.Response(200, text=GOOD_PAGE)

    sleeps: list[float] = []
    _http_transport(settings, handler, sleeps).fetch_page(1)
    assert sleeps == [30.0]


def test_http_gives_up_after_max_retries(settings):
    settings = settings.model_copy(update={"max_retries": 2})

    def handler(req):
        if req.method == "GET":
            return httpx.Response(200, text=LISTING_HTML)
        return httpx.Response(502)

    sleeps: list[float] = []
    with pytest.raises(CollectorError):
        _http_transport(settings, handler, sleeps).fetch_page(1)
    assert len(sleeps) == 2


def test_http_403_is_blocked_and_never_retried(settings):
    calls = {"n": 0}

    def handler(req):
        calls["n"] += 1
        if req.method == "GET":
            return httpx.Response(200, text=LISTING_HTML)
        return httpx.Response(403, text="Forbidden")

    sleeps: list[float] = []
    with pytest.raises(BlockedError):
        _http_transport(settings, handler, sleeps).fetch_page(1)
    assert calls["n"] == 2 and sleeps == []


def test_http_captcha_page_is_blocked(settings):
    def handler(req):
        if req.method == "GET":
            return httpx.Response(200, text=LISTING_HTML)
        return httpx.Response(200, text=(FIXTURES / "blocked" / "page_2.html").read_text())

    with pytest.raises(BlockedError):
        _http_transport(settings, handler, []).fetch_page(1)


def test_http_listing_without_token_but_with_captcha_is_blocked(settings):
    def handler(req):
        return httpx.Response(200, text="<html>Please complete the CAPTCHA</html>")

    with pytest.raises(BlockedError):
        _http_transport(settings, handler, []).open()


def test_http_404_means_empty_page(settings):
    def handler(req):
        if req.method == "GET":
            return httpx.Response(200, text=LISTING_HTML)
        return httpx.Response(404)

    assert _http_transport(settings, handler, []).fetch_page(7) == {}


def test_backoff_and_retry_after_helpers():
    assert [backoff_delay(i, 2.0) for i in range(3)] == [2.0, 4.0, 8.0]
    assert parse_retry_after("12") == 12.0
    assert parse_retry_after(None) is None
    now = datetime(2026, 10, 4, 10, 0, 0)
    later = "Sun, 04 Oct 2026 10:00:20 GMT"
    assert parse_retry_after(later, now=now.replace(tzinfo=timezone.utc)) == pytest.approx(20.0)
