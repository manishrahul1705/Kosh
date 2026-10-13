"""Migration chain + 0018 (tender status, status history, seller matches) on disposable SQLite only."""

from __future__ import annotations

import sqlite3
import warnings

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine

import app.database.auth_models  # noqa: F401
import app.database.matching_models  # noqa: F401
import app.database.platform_auth_models  # noqa: F401
from app.database.models import Base
from tests.test_stage2b_migration_cli import alembic_cfg

NEW_TABLES = {"tender_status", "tender_status_events", "seller_tender_matches"}
RETIRED_TABLES = {  # kept in migration history, intentionally not mapped by the application
    "opportunity_score_runs", "opportunity_score_dimensions", "opportunity_evidence", "scoring_configurations",
    "seller_cost_profiles", "tender_financial_scenarios", "tender_cash_flow_events",
    "tender_financial_evaluation_snapshots", "financial_change_audit",
}


def test_chain_is_linear_with_single_head(tmp_path):
    script = ScriptDirectory.from_config(alembic_cfg(tmp_path / "x.db"))
    assert script.get_heads() == ["0020_kosh_private_intake"]
    revs = list(script.walk_revisions())
    assert revs[-1].down_revision is None and len(revs) == 20
    for newer, older in zip(revs, revs[1:]):
        assert newer.down_revision == older.revision


def _diffs(db):
    engine = create_engine(f"sqlite:///{db}")
    try:
        with engine.connect() as conn, warnings.catch_warnings():
            warnings.simplefilter("ignore")
            return compare_metadata(MigrationContext.configure(conn, opts={"compare_type": True}), Base.metadata)
    finally:
        engine.dispose()


def _table(d):
    if isinstance(d, list):
        return d[0][2]
    op, obj = d[0], d[1]
    if op in ("add_index", "remove_index"):
        return obj.table.name
    if op in ("add_table", "remove_table"):
        return obj.name
    if op in ("add_column", "remove_column"):
        return d[2]
    if op in ("add_fk", "remove_fk"):
        return obj.parent.name
    return None


def test_upgrade_downgrade_reupgrade_and_orm_matches(tmp_path):
    db = tmp_path / "m.db"
    cfg = alembic_cfg(db)
    command.upgrade(cfg, "head")
    diffs = _diffs(db)
    assert [d for d in diffs if _table(d) in NEW_TABLES] == []                 # ORM == migration for new tables
    removed = {d[1].name for d in diffs if not isinstance(d, list) and d[0] == "remove_table"}
    assert removed == RETIRED_TABLES                                           # only the documented retired tables
    con = sqlite3.connect(db)
    con.execute("INSERT INTO tenders (id, bid_number, status, first_seen_at, last_seen_at, source_fingerprint, "
                "created_at, updated_at) VALUES (1, 'GEM/2026/B/1', 'ONGOING', '2026-01-01', '2026-01-01', 'fp', "
                "'2026-01-01', '2026-01-01')")
    con.commit()
    con.close()
    command.downgrade(cfg, "0017_tender_analysis_read_permission")
    con = sqlite3.connect(db)
    names = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert not (NEW_TABLES & names) and con.execute("SELECT COUNT(*) FROM tenders").fetchone()[0] == 1
    con.close()
    command.upgrade(cfg, "head")
    con = sqlite3.connect(db)
    assert con.execute("SELECT current_status FROM tender_status WHERE tender_id = 1").fetchone() is not None
    con.close()
