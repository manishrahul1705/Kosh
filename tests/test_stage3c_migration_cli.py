"""Stage 3C: migration 0006 on a populated 0005 database, and the Stage 3C CLIs (mock provider, offline)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from alembic import command
from sqlalchemy.orm import sessionmaker

from app.core.config import Settings
from app.database.session import build_engine
from app.fields.service import FieldExtractionService
from tests.stage3a_rows import make_stage3a
from tests.test_stage2b_migration_cli import alembic_cfg, seed_0002
from tests.test_stage3a_migration_cli import _seed_version, cli_env  # noqa: F401  (fixture)

OLD_TABLES = ("tenders", "tender_documents", "document_versions", "document_events", "document_jobs",
              "document_extractions", "document_pages", "document_tables", "document_sections", "extraction_jobs",
              "tender_field_extractions", "tender_field_values", "tender_field_evidence", "field_extraction_jobs")
STAGE3C_TABLES = {"ai_analysis_runs", "ai_evidence_chunks", "ai_requirements", "ai_requirement_evidence",
                  "ai_analysis_flags", "ai_analysis_jobs"}


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


def test_0006_upgrade_downgrade_upgrade_preserves_all_earlier_data(tmp_path):
    db = tmp_path / "live.db"
    seed_0002(db)
    cfg = alembic_cfg(db)
    command.upgrade(cfg, "0005_stage3b_tender_fields")
    engine = build_engine(f"sqlite:///{db}")
    factory = sessionmaker(bind=engine)
    with factory() as s:                      # Stage 3A rows + a real Stage 3B run (no Stage 3C tables yet)
        e_id = make_stage3a(s, bid="GEM/2026/B/9100001").id
    settings = Settings(_env_file=None, database_url=f"sqlite:///{db}", ai_analysis_auto_queue=False,
                        lock_file=str(tmp_path / "c.lock"))
    assert FieldExtractionService(settings, factory).extract(e_id).field_extraction_id
    engine.dispose()
    before = snapshot(db)
    assert before["tender_field_values"] and not (STAGE3C_TABLES & tables(db))

    command.upgrade(cfg, "0006_stage3c_ai_analysis")                                               # 1
    c = sqlite3.connect(db)
    assert c.execute("SELECT version_num FROM alembic_version").fetchone()[0] == "0006_stage3c_ai_analysis"
    assert "uq_ai_analysis_runs_source_current" in {r[1] for r in c.execute("PRAGMA index_list(ai_analysis_runs)")}
    assert "uq_ai_analysis_jobs_source_queued" in {r[1] for r in c.execute("PRAGMA index_list(ai_analysis_jobs)")}
    c.close()
    assert STAGE3C_TABLES <= tables(db) and snapshot(db) == before                                 # 2

    command.downgrade(cfg, "0005_stage3b_tender_fields")
    assert not (STAGE3C_TABLES & tables(db)) and snapshot(db) == before
    command.upgrade(cfg, "head")
    assert STAGE3C_TABLES <= tables(db) and snapshot(db) == before


@pytest.fixture
def ai_cli_env(cli_env, monkeypatch):  # noqa: F811
    monkeypatch.setenv("AI_ANALYSIS_SCOPE", "DOCUMENT")  # Explicit legacy document-history compatibility
    monkeypatch.setenv("AI_PROVIDER", "mock")
    monkeypatch.setenv("AI_MODEL", "")
    monkeypatch.setenv("AI_API_KEY", "")
    monkeypatch.setenv("AI_ANALYSIS_WORKER_ENABLED", "false")
    return cli_env


def test_ai_cli_end_to_end_with_mock_provider(ai_cli_env, capsys, monkeypatch):
    """Stage 3A CLI -> Stage 3B CLI (hooks queue) -> Stage 3C CLIs with AI_PROVIDER=mock (no network)."""
    import backfill_ai_analysis_jobs
    import inspect_ai_analysis
    import run_ai_analysis_worker
    import run_extraction_worker
    import run_field_extraction_worker

    db_path, storage = ai_cli_env
    assert run_ai_analysis_worker.main(["--status"]) == 0                 # also migrates the fresh DB
    out = capsys.readouterr().out
    assert '"ai_analysis_worker_enabled": false' in out and '"ai_provider": "mock"' in out
    vid = _seed_version(db_path, storage)
    assert run_extraction_worker.main(["--document-version-id", str(vid)]) == 0
    assert run_field_extraction_worker.main(["--once"]) == 0            # processes the hooked Stage 3B job
    capsys.readouterr()

    assert run_ai_analysis_worker.main(["--limit", "500"]) == 5          # hard cap
    assert run_ai_analysis_worker.main(["--force"]) == 5                 # --force needs an id
    assert run_ai_analysis_worker.main([]) == 5
    with pytest.raises(SystemExit):
        backfill_ai_analysis_jobs.main(["--dry-run"])                   # --limit is required
    assert backfill_ai_analysis_jobs.main(["--limit", "5", "--dry-run"]) == 0
    assert "Would create 0 job(s)" in capsys.readouterr().out          # hook already queued it

    assert run_ai_analysis_worker.main(["--once"]) == 0
    out = capsys.readouterr().out
    for expected in ("RUNNING -> SUCCESS", "Stage 3B extraction: 1", "Tender:   GEM/2026/B/8124821",
                     "Provider: mock   Model: mock-deterministic-v1   Prompt: stage3c-prompt-v6",
                     "(analysis_id 1, current=True)"):
        assert expected in out, (expected, out)
    assert run_ai_analysis_worker.main(["--stage3b-extraction-id", "1"]) == 0
    assert "already analyzed with mock / mock-deterministic-v1 (analysis_id 1)" in capsys.readouterr().out
    assert run_ai_analysis_worker.main(["--stage3b-extraction-id", "999"]) == 5

    assert inspect_ai_analysis.main(["--list"]) == 0
    assert "analysis_id 1, mock/mock-deterministic-v1" in capsys.readouterr().out
    assert inspect_ai_analysis.main(["--stage3b-extraction-id", "1", "--requirements", "--evidence", "--flags",
                                     "--chunks", "--history"]) == 0
    out = capsys.readouterr().out
    for expected in ("----- Requirements", "----- Evidence", "----- Flags", "----- Chunks", "----- History (1)",
                     "Versions:    prompt=stage3c-prompt-v6 schema=stage3c-schema-v1", "quote:"):
        assert expected in out, expected
    assert inspect_ai_analysis.main(["--stage3b-extraction-id", "1", "--verify-sources"]) == 0
    first = capsys.readouterr().out
    assert "PDF MATCH:     YES" in first
    assert run_ai_analysis_worker.main(["--stage3b-extraction-id", "1", "--force"]) == 0       # keeps history
    assert "(analysis_id 2, current=True)" in capsys.readouterr().out
    assert inspect_ai_analysis.main(["--stage3b-extraction-id", "1", "--verify-sources"]) == 0
    second = capsys.readouterr().out
    assert [ln for ln in first.splitlines() if "digest" in ln] == [ln for ln in second.splitlines() if "digest" in ln]
    assert inspect_ai_analysis.main(["--analysis-id", "1"]) == 0
    assert "current=False" in capsys.readouterr().out
    # provider not configured: nothing is called, explicit exit code
    monkeypatch.setenv("AI_PROVIDER", "")
    assert run_ai_analysis_worker.main(["--stage3b-extraction-id", "1", "--force"]) == 5
    assert "ai_not_configured" in capsys.readouterr().out
    c = sqlite3.connect(db_path)
    assert c.execute("SELECT COUNT(*) FROM ai_analysis_runs").fetchone()[0] == 2
    c.close()
