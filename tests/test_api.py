"""API: health, listing/pagination (11), search (12), manual collection (13),
409 on concurrent runs (14), stats, lookup routing, scheduler wiring."""

from __future__ import annotations

import threading

import pytest

from app.core.constants import TriggerType
from tests.conftest import FIXTURES



@pytest.fixture
def collection_client(client, session_factory):
    """Authorized collection client using the isolated test database."""
    from uuid import uuid4

    from app.api.auth import get_current_user
    from app.core.supabase_auth import AuthenticatedIdentity
    from app.database.auth_models import AppUser
    from app.database.platform_auth_models import PlatformOperatorGrant

    subject = str(uuid4())

    with session_factory() as db:
        operator = AppUser(supabase_user_id=subject)
        db.add(operator)
        db.flush()

        db.add(
            PlatformOperatorGrant(
                user_id=operator.id,
                granted_by_user_id=operator.id,
                permission="COLLECTION_RUN_MANAGE",
                status="ACTIVE",
            )
        )
        db.commit()

    identity = AuthenticatedIdentity(
        subject=subject,
        email="collection-test@example.com",
        claims={"sub": subject, "role": "authenticated"},
    )

    client.app.dependency_overrides[get_current_user] = lambda: identity

    try:
        yield client
    finally:
        client.app.dependency_overrides.pop(get_current_user, None)


def _collect(client, directory=None, source=None):
    if source is not None and directory is not None:
        source.directory = directory
    r = client.post("/api/collection/run")
    assert r.status_code == 200, r.text
    return r.json()


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "healthy"
    assert body["database"] == "connected"
    assert body["scheduler"] == "disabled"


def test_manual_collection_endpoint(collection_client):
    body = _collect(collection_client)
    assert body["status"] == "SUCCESS"
    assert (body["bids_seen"], body["new_bids"], body["updated_bids"]) == (3, 3, 0)
    assert body["trigger_type"] == "manual"
    runs = collection_client.get("/api/collection/runs").json()
    assert runs[0]["id"] == body["run_id"] and runs[0]["trigger_type"] == "manual"
    assert runs[0]["started_at"].endswith("+00:00")
    assert collection_client.get(f"/api/collection/runs/{body['run_id']}").status_code == 200


def test_tender_listing_pagination(collection_client, source):
    _collect(collection_client, FIXTURES / "default", source)
    p1 = collection_client.get("/api/tenders", params={"page": 1, "page_size": 5}).json()
    p3 = collection_client.get("/api/tenders", params={"page": 3, "page_size": 5}).json()
    assert (p1["total"], p1["pages"], len(p1["items"])) == (13, 3, 5)
    assert len(p3["items"]) == 3
    ids = {t["id"] for t in p1["items"]} | {t["id"] for t in p3["items"]}
    assert len(ids) == 8
    item = p1["items"][0]
    assert item["bid_end_at"].endswith("+00:00")
    assert item["estimated_value"] is None
    assert collection_client.get("/api/tenders", params={"page_size": 1000}).status_code == 422


def test_search_and_filters(collection_client, source):
    _collect(collection_client, FIXTURES / "default", source)

    def total(**params):
        r = collection_client.get("/api/tenders", params=params)
        assert r.status_code == 200, r.text
        return r.json()["total"]

    assert total(search="computer") == 1                 # title/category
    assert total(search="ministry of defence") == 3      # ministry, case-insensitive
    assert total(search="railway board") == 1            # department
    assert total(search="gem/2026/b/8100001") == 1       # bid number, any case
    assert total(search="100%") == 0                     # LIKE wildcards escaped
    assert total(bid_type="RA") == 1
    assert total(bid_type="bid") == 12
    assert total(category="air conditioner") == 1
    assert total(status="ONGOING") == 13
    assert total(status="CLOSED") == 0
    assert total(closing_before="2026-10-16T00:00:00Z") == total(closing_before="2026-10-16T05:30:00+05:30")
    assert total(closing_after="2030-01-01T00:00:00Z") == 0
    assert total(new_since="2000-01-01T00:00:00Z") == 13
    # Ambiguous (no offset) timestamps are rejected, not guessed.
    assert collection_client.get("/api/tenders", params={"closing_before": "2026-10-16T00:00:00"}).status_code == 422


def test_new_tenders_endpoint(collection_client):
    _collect(collection_client)
    body = collection_client.get("/api/tenders/new", params={"hours": 24}).json()
    assert body["total"] == 3


def test_lookup_by_bid_number_and_id(collection_client):
    _collect(collection_client)
    r = collection_client.get("/api/tenders/lookup", params={"bid_number": " gem/2026/b/8100102 "})
    assert r.status_code == 200
    tender = r.json()
    assert tender["bid_number"] == "GEM/2026/B/8100102"
    assert collection_client.get(f"/api/tenders/by-id/{tender['id']}").json()["bid_number"] == tender["bid_number"]
    assert collection_client.get("/api/tenders/lookup", params={"bid_number": "GEM/2026/B/1"}).status_code == 404
    assert collection_client.get("/api/tenders/lookup", params={"bid_number": "nonsense"}).status_code == 422
    assert collection_client.get("/api/tenders/by-id/999999").status_code == 404


def test_changes_endpoint(collection_client, source):
    _collect(collection_client)
    _collect(collection_client, FIXTURES / "mock_abc" / "b_closing_changed", source)
    tid = collection_client.get("/api/tenders/lookup", params={"bid_number": "GEM/2026/B/8100102"}).json()["id"]
    changes = collection_client.get(f"/api/tenders/by-id/{tid}/changes").json()
    assert [(c["field_name"], c["old_value"], c["new_value"]) for c in changes] == [
        ("bid_end_at", "2026-10-10T09:30:00Z", "2026-10-12T12:30:00Z")
    ]


def test_stats(collection_client):
    before = collection_client.get("/api/stats").json()
    assert before["total_tenders"] == 0 and before["last_collection"] is None
    _collect(collection_client)
    s = collection_client.get("/api/stats").json()
    assert (s["total_tenders"], s["ongoing"], s["new_last_24h"]) == (3, 3, 3)
    assert s["last_collection_status"] == "SUCCESS"
    assert s["collection_running"] is False


def test_manual_run_returns_409_while_running(collection_client):
    runner = collection_client.app.state.runner
    started, release = threading.Event(), threading.Event()

    class Slow:
        def discover_live_tenders(self):
            started.set()
            release.wait(10)
            from app.collectors.base import CollectorResult
            return CollectorResult()

    runner.collector_factory = Slow
    t = threading.Thread(target=runner.run, args=(TriggerType.SCHEDULED,))
    t.start()
    assert started.wait(5)
    r = collection_client.post("/api/collection/run")
    assert r.status_code == 409
    assert r.json() == {"detail": "A collection run is already in progress."}
    assert collection_client.post("/api/collection/run", params={"background": True}).status_code == 409
    assert collection_client.get("/api/stats").json()["collection_running"] is True
    release.set()
    t.join(10)


def test_scheduler_initialization(settings, session_factory, source):
    from fastapi.testclient import TestClient

    from app.main import create_app

    s = settings.model_copy(update={"scheduler_enabled": True, "collect_on_startup": False,
                                     "collection_interval_minutes": 30})
    app = create_app(s, session_factory=session_factory, collector_factory=source)
    with TestClient(app) as c:
        body = c.get("/health").json()
        assert body["scheduler"] == "running"
        assert body["next_scheduled_run"] is not None
        job = app.state.scheduler._scheduler.get_job("gem_discovery")
        assert job.trigger.interval.total_seconds() == 30 * 60
        assert job.max_instances == 1 and job.coalesce is True
    assert app.state.scheduler.running is False  # stopped on shutdown


def test_scheduled_job_skips_when_busy(runner):
    from app.scheduler.scheduler import scheduled_collection

    with runner.lock.acquire():
        scheduled_collection(runner)  # must not raise
    scheduled_collection(runner)
    assert not runner.is_running()


def test_swagger_available(client):
    assert client.get("/openapi.json").status_code == 200
    assert client.get("/docs").status_code == 200
