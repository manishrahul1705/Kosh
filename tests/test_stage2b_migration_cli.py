"""Stage 2B: migration 0003 against an existing 0002 database, and the CLIs.

The migration test builds a real 0002-era SQLite database (like the live one:
many PENDING jobs, one MAIN_BID v1) and upgrades it in place.
CLI tests never reach GeM: they use an empty queue or a tender without a URL.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

from app.core.config import PROJECT_ROOT

SCRIPTS = PROJECT_ROOT / "scripts"


def alembic_cfg(db_path: Path) -> Config:
    cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    cfg.attributes["configure_logger"] = False
    return cfg


NOW = "2026-10-05 10:00:00.000000"


def seed_0002(db_path: Path, *, duplicate_versions: bool = False) -> None:
    command.upgrade(alembic_cfg(db_path), "0002_stage2")
    c = sqlite3.connect(db_path)
    for i in range(1, 6):
        c.execute(
            "INSERT INTO tenders (id, bid_number, status, first_seen_at, last_seen_at, source_fingerprint, "
            "created_at, updated_at, source_url) VALUES (?,?,?,?,?,?,?,?,?)",
            (i, f"GEM/2026/B/812286{i}", "ONGOING", NOW, NOW, "fp", NOW, NOW, f"https://bidplus.gem.gov.in/showbidDocument/{i}"),
        )
    jobs = [  # (tender_id, status)
        (1, "PENDING"), (2, "PENDING"), (3, "PENDING"), (3, "PENDING"), (3, "RETRY"),  # tender 3: duplicates
        (4, "RUNNING"), (5, "SUCCESS"), (5, "PENDING"),
    ]
    for tid, st in jobs:
        c.execute("INSERT INTO document_jobs (tender_id, status, attempt_count, created_at, updated_at) "
                  "VALUES (?,?,0,?,?)", (tid, st, NOW, NOW))
    c.execute("INSERT INTO tender_documents (id, tender_id, document_key, document_type, discovered_at, "
              "last_seen_at, is_active, created_at, updated_at) VALUES (1, 1, 'main_bid', 'MAIN_BID', ?, ?, 1, ?, ?)",
              (NOW, NOW, NOW, NOW))
    c.execute("INSERT INTO document_versions (id, document_id, version_number, sha256, storage_path, "
              "validation_status, created_at) VALUES (1, 1, 1, ?, 'GEM_2026_B_8122861/documents/main_bid/v1.pdf', "
              "'VALID', ?)", ("a" * 64, NOW))
    if duplicate_versions:
        c.execute("INSERT INTO document_versions (id, document_id, version_number, sha256, validation_status, "
                  "created_at) VALUES (2, 1, 1, ?, 'VALID', ?)", ("a" * 64, NOW))
    c.execute("UPDATE tender_documents SET current_version_id = 1 WHERE id = 1")
    c.commit()
    c.close()


def indexes(c: sqlite3.Connection, table: str) -> set[str]:
    return {r[1] for r in c.execute(f"PRAGMA index_list({table})")}


def test_upgrade_existing_0002_database_preserves_data(tmp_path):
    db = tmp_path / "live.db"
    seed_0002(db)
    # Target 0003 explicitly (this test is about the 0002 -> 0003 step; later
    # migrations such as 0004_stage3a_extraction move "head" forward).
    command.upgrade(alembic_cfg(db), "0003_stage2b")

    c = sqlite3.connect(db)
    assert c.execute("SELECT version_num FROM alembic_version").fetchone()[0] == "0003_stage2b"
    assert c.execute("SELECT COUNT(*) FROM tenders").fetchone()[0] == 5
    assert c.execute("SELECT COUNT(*) FROM document_jobs").fetchone()[0] == 8          # nothing deleted
    rows = c.execute("SELECT id, tender_id, status, error_code, reason FROM document_jobs ORDER BY id").fetchall()
    by_tender3 = [r for r in rows if r[1] == 3]
    assert [r[2] for r in by_tender3] == ["PENDING", "SKIPPED", "SKIPPED"]           # oldest kept
    assert {r[3] for r in by_tender3[1:]} == {"DUPLICATE_QUEUED"}
    assert all(r[4] is None for r in rows)                                             # legacy reason = NULL
    assert [r[2] for r in rows if r[1] in (1, 2)] == ["PENDING", "PENDING"]
    assert [r[2] for r in rows if r[1] == 4] == ["RUNNING"]
    # live-tested v1 untouched
    assert c.execute("SELECT version_number, sha256, storage_path FROM document_versions").fetchall() == [
        (1, "a" * 64, "GEM_2026_B_8122861/documents/main_bid/v1.pdf")]
    assert {"uq_document_jobs_tender_queued", "ix_document_jobs_status_next_retry"} <= indexes(c, "document_jobs")
    assert {"uq_document_versions_document_version", "uq_document_versions_document_sha256"} <= indexes(c, "document_versions")
    cols = {r[1] for r in c.execute("PRAGMA table_info(document_jobs)")}
    assert {"reason", "locked_by", "outcome", "result_summary"} <= cols
    c.close()


def test_upgrade_with_duplicate_versions_skips_unique_index_and_keeps_history(tmp_path):
    db = tmp_path / "dups.db"
    seed_0002(db, duplicate_versions=True)
    command.upgrade(alembic_cfg(db), "head")
    c = sqlite3.connect(db)
    assert c.execute("SELECT COUNT(*) FROM document_versions").fetchone()[0] == 2     # nothing destroyed
    idx = indexes(c, "document_versions")
    assert "uq_document_versions_document_version" not in idx
    assert "uq_document_versions_document_sha256" not in idx
    c.close()


def test_downgrade_and_reupgrade(tmp_path):
    db = tmp_path / "round.db"
    seed_0002(db)
    cfg = alembic_cfg(db)
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "0002_stage2")
    c = sqlite3.connect(db)
    assert "reason" not in {r[1] for r in c.execute("PRAGMA table_info(document_jobs)")}
    assert c.execute("SELECT COUNT(*) FROM document_jobs").fetchone()[0] == 8
    c.close()
    command.upgrade(cfg, "head")


# ---------------------------------------------------------------------------
# CLIs (no network)
# ---------------------------------------------------------------------------
@pytest.fixture
def cli_env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'cli.db'}")
    monkeypatch.setenv("LOCK_FILE", str(tmp_path / "collection.lock"))
    monkeypatch.setenv("DOCUMENT_STORAGE_PATH", str(tmp_path / "tenders"))
    monkeypatch.setenv("LOG_LEVEL", "WARNING")
    monkeypatch.setenv("DOCUMENT_INTER_JOB_DELAY_SECONDS", "0")
    monkeypatch.syspath_prepend(str(SCRIPTS))
    # Explicit schema setup: CLIs no longer depend on AUTO_MIGRATE.
    command.upgrade(alembic_cfg(tmp_path / "cli.db"), "head")
    return tmp_path / "cli.db"


def _seed_cli_tenders(db_path: Path) -> None:
    c = sqlite3.connect(db_path)
    c.execute("INSERT INTO tenders (id, bid_number, status, first_seen_at, last_seen_at, source_fingerprint, "
              "created_at, updated_at) VALUES (1, 'GEM/2026/B/8122868', 'ONGOING', ?, ?, 'fp', ?, ?)",
              (NOW, NOW, NOW, NOW))
    c.execute("INSERT INTO tenders (id, bid_number, status, first_seen_at, last_seen_at, source_fingerprint, "
              "created_at, updated_at) VALUES (2, 'GEM/2026/B/8122869', 'ONGOING', ?, ?, 'fp', ?, ?)",
              (NOW, NOW, NOW, NOW))
    c.commit()
    c.close()


def test_worker_cli_once_on_empty_queue_and_status(cli_env, capsys):
    import run_document_worker

    assert run_document_worker.main(["--once"]) == 0
    assert "No due document jobs." in capsys.readouterr().out
    assert run_document_worker.main(["--status"]) == 0
    assert '"pending_jobs": 0' in capsys.readouterr().out
    assert run_document_worker.main(["--once", "--limit", "500"]) == 5      # hard cap protects GeM
    assert run_document_worker.main(["--recover-only"]) == 0


def test_backfill_cli_then_worker_cli_bid(cli_env, capsys):
    import backfill_document_jobs
    import run_document_worker

    assert backfill_document_jobs.main(["--dry-run"]) == 0       # also migrates the fresh DB
    _seed_cli_tenders(cli_env)
    assert backfill_document_jobs.main(["--limit", "1"]) == 0
    assert backfill_document_jobs.main(["--limit", "5"]) == 0
    assert backfill_document_jobs.main(["--limit", "5"]) == 0
    c = sqlite3.connect(cli_env)
    assert c.execute("SELECT COUNT(*), COUNT(DISTINCT tender_id) FROM document_jobs").fetchone() == (2, 2)
    c.close()
    capsys.readouterr()

    # tender has no source_url -> processed WITHOUT any request -> SKIPPED
    assert run_document_worker.main(["--bid", "GEM/2026/B/8122868"]) == 0
    out = capsys.readouterr().out
    assert "Reusing existing job" in out and "RUNNING -> SKIPPED" in out
    assert run_document_worker.main(["--bid", "GEM/2026/B/0000001"]) == 5   # unknown tender


def test_process_pending_documents_is_backfill_compatible(cli_env, monkeypatch, capsys):
    import runpy

    monkeypatch.setattr(sys, "argv", ["process_pending_documents.py", "--limit", "3"])
    with pytest.raises(SystemExit) as exc:
        runpy.run_path(str(SCRIPTS / "process_pending_documents.py"), run_name="__main__")
    assert exc.value.code == 0
    assert "Created 0 job(s)" in capsys.readouterr().out
