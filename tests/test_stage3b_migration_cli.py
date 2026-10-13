"""Stage 3B: migration 0005 on a populated 0004 database, and the Stage 3B CLIs."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from alembic import command
from sqlalchemy.orm import sessionmaker

from app.database.session import build_engine
from tests.stage3a_rows import make_stage3a
from tests.test_stage2b_migration_cli import alembic_cfg, seed_0002
from tests.test_stage3a_migration_cli import SCRIPTS, _seed_version, cli_env  # noqa: F401  (fixture)

OLD_TABLES = ("tenders", "tender_documents", "document_versions", "document_events", "document_jobs",
              "document_extractions", "document_pages", "document_tables", "document_sections", "extraction_jobs")
STAGE3B_TABLES = {"tender_field_extractions", "tender_field_values", "tender_field_evidence", "field_extraction_jobs"}


def snapshot(db: Path) -> dict:
    c = sqlite3.connect(db)
    out = {t: c.execute(f"SELECT * FROM {t} ORDER BY id").fetchall() for t in OLD_TABLES}
    c.close()
    return out


def tables(db: Path) -> set[str]:
    c = sqlite3.connect(db)
    names = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    c.close()
    return names


def test_0005_upgrade_downgrade_upgrade_preserves_stage1_2_3a(tmp_path):
    db = tmp_path / "live.db"
    seed_0002(db)
    cfg = alembic_cfg(db)
    command.upgrade(cfg, "0004_stage3a_extraction")
    engine = build_engine(f"sqlite:///{db}")
    with sessionmaker(bind=engine)() as s:      # Stage 3A rows only (Stage 3B tables do not exist yet)
        make_stage3a(s, bid="GEM/2026/B/9000001")
    engine.dispose()
    before = snapshot(db)
    assert len(before["document_tables"]) > 0 and not (STAGE3B_TABLES & tables(db))

    command.upgrade(cfg, "0005_stage3b_tender_fields")
    c = sqlite3.connect(db)
    assert c.execute("SELECT version_num FROM alembic_version").fetchone()[0] == "0005_stage3b_tender_fields"
    assert "uq_tender_field_extractions_source_current" in {r[1] for r in c.execute(
        "PRAGMA index_list(tender_field_extractions)")}
    assert "uq_field_extraction_jobs_source_queued" in {r[1] for r in c.execute(
        "PRAGMA index_list(field_extraction_jobs)")}
    c.close()
    assert STAGE3B_TABLES <= tables(db) and snapshot(db) == before

    command.downgrade(cfg, "0004_stage3a_extraction")
    assert not (STAGE3B_TABLES & tables(db)) and snapshot(db) == before
    command.upgrade(cfg, "head")
    assert STAGE3B_TABLES <= tables(db) and snapshot(db) == before


def test_field_cli_end_to_end_from_stage3a_cli(cli_env, capsys):  # noqa: F811
    """Stage 3A CLI extracts ONE local PDF -> hook queues Stage 3B -> Stage 3B CLIs (local DB only)."""
    import backfill_field_extraction_jobs
    import inspect_tender_fields
    import run_extraction_worker
    import run_field_extraction_worker

    db_path, storage = cli_env
    assert run_field_extraction_worker.main(["--status"]) == 0       # also migrates the fresh DB
    assert '"field_extraction_worker_enabled": false' in capsys.readouterr().out
    vid = _seed_version(db_path, storage)
    assert run_extraction_worker.main(["--document-version-id", str(vid)]) == 0
    capsys.readouterr()

    assert run_field_extraction_worker.main(["--limit", "500"]) == 5   # hard cap
    assert run_field_extraction_worker.main(["--force"]) == 5          # --force needs an id
    assert run_field_extraction_worker.main([]) == 5
    assert backfill_field_extraction_jobs.main(["--limit", "5", "--dry-run"]) == 0
    assert "Would create 0 job(s)" in capsys.readouterr().out          # hook already queued it

    assert run_field_extraction_worker.main(["--once"]) == 0
    out = capsys.readouterr().out
    for expected in ("RUNNING -> SUCCESS", "Stage 3A extraction: 1", "Tender:   GEM/2026/B/8124821",
                     "Document: MAIN_BID v1", "field_extraction_id 1"):
        assert expected in out, expected
    assert run_field_extraction_worker.main(["--once"]) == 0
    assert "No due field-extraction jobs." in capsys.readouterr().out
    assert run_field_extraction_worker.main(["--stage3a-extraction-id", "1"]) == 0
    assert "already field-extracted (field_extraction_id 1)" in capsys.readouterr().out
    assert run_field_extraction_worker.main(["--stage3a-extraction-id", "999"]) == 5

    assert inspect_tender_fields.main(["--list"]) == 0
    assert "SUCCESS (field_extraction_id 1;" in capsys.readouterr().out
    assert inspect_tender_fields.main(["--stage3a-extraction-id", "1", "--resolved-only"]) == 0
    out = capsys.readouterr().out
    assert "emd_amount" in out and "25000" in out and "total_quantity" not in out   # UNKNOWN hidden
    assert inspect_tender_fields.main(["--stage3a-extraction-id", "1"]) == 0
    assert "<UNKNOWN: NOT_FOUND>" in capsys.readouterr().out
    assert inspect_tender_fields.main(["--stage3a-extraction-id", "1", "--evidence", "--field", "emd_amount"]) == 0
    out = capsys.readouterr().out
    assert "emd_amount [SELECTED]" in out and "Evidence (" in out
    assert inspect_tender_fields.main(["--stage3a-extraction-id", "1", "--conflicts"]) == 0
    assert "Conflicts (0)" in capsys.readouterr().out
    assert inspect_tender_fields.main(["--bid", "GEM/2026/B/8124821"]) == 0
    assert "Field extraction 1: SUCCESS" in capsys.readouterr().out

    assert inspect_tender_fields.main(["--stage3a-extraction-id", "1", "--verify-sources"]) == 0
    first = capsys.readouterr().out
    assert "PDF MATCH:     YES" in first
    # controlled re-run keeps history; Stage 3A rows and the PDF stay untouched
    assert run_field_extraction_worker.main(["--stage3a-extraction-id", "1", "--force"]) == 0
    assert "field_extraction_id 2" in capsys.readouterr().out
    assert inspect_tender_fields.main(["--stage3a-extraction-id", "1", "--verify-sources"]) == 0
    second = capsys.readouterr().out
    digest = [ln for ln in first.splitlines() if "row digest" in ln]
    assert digest and digest == [ln for ln in second.splitlines() if "row digest" in ln]
    assert "PDF MATCH:     YES" in second
    assert inspect_tender_fields.main(["--field-extraction-id", "1"]) == 0
    assert "current=False" in capsys.readouterr().out
    c = sqlite3.connect(db_path)
    assert c.execute("SELECT COUNT(*) FROM tender_field_extractions").fetchone()[0] == 2
    c.close()
