"""Startup recovery gate in scripts/run_collection.py.

Uses only a temporary database, the fixture collector, and zero delays.
Never reaches GeM. data/gem.db is never opened.
"""

import sys

import pytest

from app.core.config import PROJECT_ROOT
from app.services.discovery_service import CollectionRunner

SCRIPTS = PROJECT_ROOT / "scripts"
FIXTURE_DIR = PROJECT_ROOT / "tests" / "fixtures" / "gem" / "mock_abc" / "initial"
ARGS = ["--mode", "fixture", "--fixture-dir", str(FIXTURE_DIR)]
SKIP_LINE = "Startup recovery skipped (STARTUP_RECOVERY_ENABLED=false)."


@pytest.fixture
def collection_cli(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'cli.db'}")
    monkeypatch.setenv("AUTO_MIGRATE", "true")
    monkeypatch.setenv("APP_STARTUP_MODE", "normal")
    monkeypatch.setenv("SCHEDULER_ENABLED", "false")
    monkeypatch.setenv("LOCK_FILE", str(tmp_path / "collection.lock"))
    monkeypatch.setenv("DOCUMENT_STORAGE_PATH", str(tmp_path / "tenders"))
    monkeypatch.setenv("DEBUG_DIR", str(tmp_path / "debug"))
    monkeypatch.setenv("LOG_LEVEL", "WARNING")
    monkeypatch.setenv("REQUEST_DELAY_SECONDS", "0")
    monkeypatch.setenv("BACKOFF_BASE_SECONDS", "0")
    monkeypatch.syspath_prepend(str(SCRIPTS))
    sys.modules.pop("run_collection", None)
    import run_collection

    return run_collection


@pytest.fixture
def recovery_calls(monkeypatch):
    calls = []

    def spy(self):
        calls.append(self)
        return 0

    monkeypatch.setattr(CollectionRunner, "recover_interrupted_runs", spy)
    return calls


def test_recovery_runs_when_enabled(collection_cli, recovery_calls, monkeypatch, capsys):
    monkeypatch.setenv("STARTUP_RECOVERY_ENABLED", "true")

    rc = collection_cli.main(ARGS)
    out = capsys.readouterr().out

    assert rc == 0, out
    assert len(recovery_calls) == 1
    assert SKIP_LINE not in out


def test_recovery_skipped_when_disabled(collection_cli, recovery_calls, monkeypatch, capsys):
    monkeypatch.setenv("STARTUP_RECOVERY_ENABLED", "false")

    rc = collection_cli.main(ARGS)
    out = capsys.readouterr().out

    assert rc == 0, out
    assert recovery_calls == []
    assert SKIP_LINE in out