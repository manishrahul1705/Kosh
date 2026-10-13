"""Stage 3A: migration 0004 on a populated 0003 database, and the Stage 3A CLIs."""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import pytest
from alembic import command

from app.core.config import PROJECT_ROOT
from tests.pdf_factory import gem_like_pdf
from tests.test_stage2b_migration_cli import NOW, alembic_cfg, seed_0002

SCRIPTS = PROJECT_ROOT / "scripts"
STAGE12_TABLES = ("tenders", "tender_documents", "document_versions", "document_events", "document_jobs")
STAGE3A_TABLES = {"document_extractions", "document_pages", "document_tables", "document_sections", "extraction_jobs"}


def snapshot(db: Path) -> dict:
    c = sqlite3.connect(db)
    out = {t: c.execute(f"SELECT * FROM {t} ORDER BY id").fetchall() for t in STAGE12_TABLES}
    c.close()
    return out


def tables(db: Path) -> set[str]:
    c = sqlite3.connect(db)
    names = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    c.close()
    return names


def test_0004_upgrade_downgrade_upgrade_preserves_stage1_and_stage2(tmp_path):
    db = tmp_path / "live.db"
    seed_0002(db)
    cfg = alembic_cfg(db)
    command.upgrade(cfg, "0003_stage2b")
    before = snapshot(db)

    # Target 0004 explicitly (this test is about the 0003 -> 0004 step; later
    # migrations such as 0005_stage3b_tender_fields move "head" forward).
    command.upgrade(cfg, "0004_stage3a_extraction")
    c = sqlite3.connect(db)
    assert c.execute("SELECT version_num FROM alembic_version").fetchone()[0] == "0004_stage3a_extraction"
    idx = {r[1] for r in c.execute("PRAGMA index_list(document_extractions)")}
    assert "uq_document_extractions_version_current" in idx
    assert "uq_extraction_jobs_version_queued" in {r[1] for r in c.execute("PRAGMA index_list(extraction_jobs)")}
    c.close()
    assert STAGE3A_TABLES <= tables(db) and snapshot(db) == before

    command.downgrade(cfg, "0003_stage2b")
    assert not (STAGE3A_TABLES & tables(db)) and snapshot(db) == before
    command.upgrade(cfg, "0004_stage3a_extraction")
    assert STAGE3A_TABLES <= tables(db) and snapshot(db) == before


# ---------------------------------------------------------------------------
# CLIs (local files only)
# ---------------------------------------------------------------------------
@pytest.fixture
def cli_env(tmp_path, monkeypatch):
    storage = tmp_path / "tenders"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'cli.db'}")
    monkeypatch.setenv("LOCK_FILE", str(tmp_path / "collection.lock"))
    monkeypatch.setenv("DOCUMENT_STORAGE_PATH", str(storage))
    monkeypatch.setenv("LOG_LEVEL", "WARNING")
    monkeypatch.setenv("OCR_ENABLED", "false")
    monkeypatch.syspath_prepend(str(SCRIPTS))
    # Explicit schema setup: CLIs no longer depend on AUTO_MIGRATE.
    command.upgrade(alembic_cfg(tmp_path / "cli.db"), "head")
    return tmp_path / "cli.db", storage


def _seed_version(db_path: Path, storage: Path) -> int:
    data = gem_like_pdf()
    sha = hashlib.sha256(data).hexdigest()
    rel = f"GEM_2026_B_8124821/documents/main_bid/v1_{sha[:12]}_GeM-Bidding-1.pdf"
    (storage / rel).parent.mkdir(parents=True, exist_ok=True)
    (storage / rel).write_bytes(data)
    c = sqlite3.connect(db_path)
    c.execute("INSERT INTO tenders (id, bid_number, status, first_seen_at, last_seen_at, source_fingerprint, "
              "created_at, updated_at) VALUES (1, 'GEM/2026/B/8124821', 'ONGOING', ?, ?, 'fp', ?, ?)",
              (NOW, NOW, NOW, NOW))
    c.execute("INSERT INTO tender_documents (id, tender_id, document_key, document_type, discovered_at, last_seen_at, "
              "is_active, created_at, updated_at) VALUES (1, 1, 'main_bid', 'MAIN_BID', ?, ?, 1, ?, ?)",
              (NOW, NOW, NOW, NOW))
    c.execute("INSERT INTO document_versions (id, document_id, version_number, sha256, file_size, storage_path, "
              "validation_status, created_at) VALUES (13, 1, 1, ?, ?, ?, 'VALID', ?)", (sha, len(data), rel, NOW))
    c.commit()
    c.close()
    return 13


def test_extraction_cli_end_to_end_on_one_version(cli_env, capsys):
    import backfill_extraction_jobs
    import inspect_extraction
    import run_extraction_worker

    db_path, storage = cli_env
    assert run_extraction_worker.main(["--status"]) == 0           # also migrates the fresh DB
    vid = _seed_version(db_path, storage)
    capsys.readouterr()

    assert backfill_extraction_jobs.main(["--limit", "5", "--dry-run"]) == 0
    assert "would queue document_version_id 13" in capsys.readouterr().out
    assert run_extraction_worker.main(["--limit", "500"]) == 5      # hard cap
    assert run_extraction_worker.main(["--force"]) == 5             # --force needs a version

    assert run_extraction_worker.main(["--document-version-id", str(vid)]) == 0
    out = capsys.readouterr().out
    for expected in ("Tender:   GEM/2026/B/8124821", "Document: MAIN_BID v1", "Extraction: SUCCESS",
                     "Pages: 3", "Pages with text: 3", "Tables: 4", "Quality: GOOD"):
        assert expected in out, expected
    assert run_extraction_worker.main(["--document-version-id", str(vid)]) == 0
    assert "already extracted" in capsys.readouterr().out
    assert backfill_extraction_jobs.main(["--limit", "5"]) == 0
    assert "Created 0 job(s)" in capsys.readouterr().out            # extracted versions are skipped

    assert inspect_extraction.main(["--document-version-id", str(vid), "--page", "1", "--tables",
                                    "--sections", "--verify-source"]) == 0
    out = capsys.readouterr().out
    assert "MATCH:          YES" in out and "----- Page 1" in out and "EMD Amount | Rs. 25,000" in out
    assert "bid details" in out
    assert inspect_extraction.main(["--list-versions"]) == 0
    assert "SUCCESS (id 1)" in capsys.readouterr().out
    assert run_extraction_worker.main(["--document-version-id", "999"]) == 5
