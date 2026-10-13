"""Shared fixtures. Every test uses its own temporary SQLite DB built through
the real Alembic migration, and fixture transports — never live GeM."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Make importing app.main side-effect free for the test run.
os.environ.setdefault("SCHEDULER_ENABLED", "false")
os.environ.setdefault("COLLECTOR_MODE", "fixture")
os.environ.setdefault("DATABASE_URL", "sqlite:///./data/test-import.db")

from app.collectors.fixture_collector import FixtureTransport  # noqa: E402
from app.collectors.gem_collector import GemListingCollector, PaginationLimits  # noqa: E402
from app.core.config import Settings  # noqa: E402
from app.database.session import build_engine, build_session_factory, run_migrations  # noqa: E402
from app.services.discovery_service import CollectionRunner  # noqa: E402
from app.services.run_lock import CollectionLock  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures" / "gem"
ORIGIN = "https://bidplus.gem.gov.in"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        collector_mode="fixture",
        fixture_dir=str(FIXTURES / "mock_abc" / "initial"),
        scheduler_enabled=False,
        request_delay_seconds=0,
        backoff_base_seconds=0,
        lock_file=str(tmp_path / "collection.lock"),
        debug_dir=str(tmp_path / "debug"),
        log_level="WARNING",
    )


@pytest.fixture
def session_factory(settings: Settings):
    run_migrations(settings.resolved_database_url)
    engine = build_engine(settings.resolved_database_url)
    yield build_session_factory(engine)
    engine.dispose()


def fixture_collector(directory: Path, max_pages: int = 50) -> GemListingCollector:
    return GemListingCollector(
        FixtureTransport(directory),
        source_origin=ORIGIN,
        limits=PaginationLimits(max_pages=max_pages, delay_seconds=0),
    )


class SwitchableSource:
    """Lets a test change which fixture directory the next run reads."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory

    def __call__(self) -> GemListingCollector:
        return fixture_collector(self.directory)


@pytest.fixture
def source() -> SwitchableSource:
    return SwitchableSource(FIXTURES / "mock_abc" / "initial")


@pytest.fixture
def runner(settings, session_factory, source) -> CollectionRunner:
    return CollectionRunner(settings, session_factory, source, CollectionLock(settings.resolve_path(settings.lock_file)))


@pytest.fixture
def db(session_factory):
    """Database session for tests."""
    session = session_factory()
    yield session
    session.close()


@pytest.fixture
def client(settings, session_factory, source):
    from fastapi.testclient import TestClient

    from app.main import create_app

    app = create_app(settings, session_factory=session_factory, collector_factory=source)
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def offline_network():
    from tests.network_guard import install
    # Independent patch scope cannot be undone by a test restoring its own mocks.
    with pytest.MonkeyPatch.context() as guard:
        install(guard)
        yield


def sign_in(app, subject: str = "00000000-0000-0000-0000-00000000aaaa"):
    """Authenticate subsequent TestClient requests as a verified identity (routes that only
    need a signed-in user, e.g. /api/stats and /api/tenders)."""
    from app.api.auth import get_current_user
    from app.core.supabase_auth import AuthenticatedIdentity

    identity = AuthenticatedIdentity(subject=subject, email=None, claims={"sub": subject, "role": "authenticated"})
    app.dependency_overrides[get_current_user] = lambda: identity
    return identity


def make_head_db(path: Path) -> Path:
    """Build a disposable SQLite DB at the Alembic head with a little representative data.
    (Replaces tests that used to copy a real production database snapshot.)"""
    import sqlite3

    run_migrations(f"sqlite:///{path.as_posix()}")
    con = sqlite3.connect(path)
    try:
        now = "2026-10-01 00:00:00.000000"
        for i in range(1, 4):
            con.execute(
                "INSERT INTO tenders (id, bid_number, title, category, status, bid_end_at, first_seen_at, "
                "last_seen_at, source_fingerprint, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (i, f"GEM/2026/B/90000{i}", f"Sample tender {i}", "Laptop", "ONGOING", "2099-01-01 00:00:00.000000",
                 now, now, f"fp{i}", now, now))
            con.execute("INSERT INTO tender_status (tender_id, current_status, status_source, last_status_check_at) "
                        "VALUES (?, 'LIVE', 'SOURCE_LISTING', ?)", (i, now))
        con.commit()
    finally:
        con.close()
    return path
