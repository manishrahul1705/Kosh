#!/usr/bin/env python
"""Apply database migrations explicitly (required when AUTO_MIGRATE=false, e.g. APP_ENV=production).

    python scripts/migrate.py            # back up (SQLite) then upgrade to head
    python scripts/migrate.py --check    # print current and head revision, change nothing

For SQLite a consistent backup is written to data/backups/ (online backup API) before
anything changes. Migrations are additive; nothing is downgraded here.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from alembic.config import Config  # noqa: E402
from alembic.runtime.migration import MigrationContext  # noqa: E402
from alembic.script import ScriptDirectory  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.database.session import build_engine, run_migrations  # noqa: E402


def _revisions(url: str) -> tuple[str | None, str]:
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "migrations"))
    head = ScriptDirectory.from_config(cfg).get_current_head()
    engine = build_engine(url, read_only=True)
    try:
        with engine.connect() as conn:
            return MigrationContext.configure(conn).get_current_revision(), head
    finally:
        engine.dispose()


def _backup_sqlite(url: str) -> Path | None:
    path = Path(url.split("sqlite:///", 1)[-1])
    if not path.exists():
        return None
    target = ROOT / "data" / "backups" / f"{path.stem}_{datetime.now(timezone.utc):%Y%m%d_%H%M%S}_pre_migrate.db"
    target.parent.mkdir(parents=True, exist_ok=True)
    src, dst = sqlite3.connect(path), sqlite3.connect(target)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Apply Alembic migrations safely.")
    parser.add_argument("--check", action="store_true", help="report revisions only")
    args = parser.parse_args(argv)
    url = get_settings().resolved_database_url
    if args.check:
        if url.startswith("sqlite") and not Path(url.split("sqlite:///", 1)[-1]).exists():
            print("database file does not exist yet (run without --check to create it)")
            return 1
        current, head = _revisions(url)
        print(f"current={current} head={head} up_to_date={current == head}")
        return 0 if current == head else 1
    if url.startswith("sqlite"):
        backup = _backup_sqlite(url)
        if backup:
            print(f"backup written: {backup}")
    run_migrations(url)
    current, head = _revisions(url)
    print(f"migrated: current={current} head={head}")
    return 0 if current == head else 1


if __name__ == "__main__":
    raise SystemExit(main())
