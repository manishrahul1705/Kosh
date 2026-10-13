#!/usr/bin/env python
"""Run one GeM discovery collection from the command line.

    python scripts/run_collection.py              # uses .env settings
    python scripts/run_collection.py --verbose    # also list new/updated bids
    python scripts/run_collection.py --mode fixture --fixture-dir tests/fixtures/gem/default

Exit codes: 0 success/partial, 1 failed, 2 blocked by human verification,
3 another run in progress.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import select  # noqa: E402

from app.collectors.gem_collector import build_collector  # noqa: E402
from app.core.config import Settings  # noqa: E402
from app.core.constants import CollectorMode, RunStatus, TriggerType  # noqa: E402
from app.core.logging import setup_logging  # noqa: E402
from app.database.models import Tender, TenderChange  # noqa: E402
from app.database.session import build_engine, build_session_factory, run_migrations  # noqa: E402
from app.services.discovery_service import CollectionAlreadyRunning, CollectionRunner  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run one GeM bid discovery collection.")
    parser.add_argument("--verbose", "-v", action="store_true", help="debug logs + list new/updated bids")
    parser.add_argument("--mode", choices=[m.value for m in CollectorMode], help="override COLLECTOR_MODE")
    parser.add_argument("--fixture-dir", help="fixture directory (fixture mode)")
    parser.add_argument("--max-pages", type=int, help="override MAX_PAGES_PER_RUN")
    args = parser.parse_args(argv)

    overrides: dict = {}
    if args.mode:
        overrides["collector_mode"] = args.mode
    if args.fixture_dir:
        overrides["fixture_dir"] = args.fixture_dir
    if args.max_pages:
        overrides["max_pages_per_run"] = args.max_pages
    if args.verbose:
        overrides["log_level"] = "DEBUG"
    settings = Settings(**overrides)
    setup_logging(settings.log_level if args.verbose else "WARNING", settings.log_format)

    db_url = settings.resolved_database_url
    if settings.auto_migrate:
        run_migrations(db_url)
    engine = build_engine(db_url)
    factory = build_session_factory(engine)
    runner = CollectionRunner(settings, factory, lambda: build_collector(settings))
    if settings.startup_recovery_enabled:
        runner.recover_interrupted_runs()
    else:
        print("Startup recovery skipped (STARTUP_RECOVERY_ENABLED=false).")

    print("Starting GeM collection...")
    print(f"Collector mode: {settings.collector_mode.value}")
    print()
    try:
        summary = runner.run(TriggerType.CLI)
    except CollectionAlreadyRunning:
        print("A collection run is already in progress. Try again later.")
        return 3

    print(f"Pages checked: {summary.pages_checked}")
    print(f"Bids seen: {summary.bids_seen}")
    print()
    print(f"New: {summary.new_bids}")
    print(f"Updated: {summary.updated_bids}")
    print(f"Unchanged: {summary.unchanged_bids}")
    print(f"Failed: {summary.failed_items}")
    if summary.closed_by_deadline:
        print(f"Closed (deadline passed, no longer listed): {summary.closed_by_deadline}")
    print()
    print(f"Status: {summary.status}")
    print(f"Run ID: {summary.run_id}")
    if summary.error_message:
        print(f"Details: {summary.error_message}")

    if args.verbose:
        with factory() as s:
            changes = s.scalars(select(TenderChange).where(TenderChange.collection_run_id == summary.run_id)).all()
            new = s.scalars(select(Tender).where(Tender.first_seen_at >= _run_started(s, summary.run_id))).all()
            if new:
                print("\nNew bids:")
                for t in new:
                    print(f"  {t.bid_number}  {t.title or '-'}  closes={t.bid_end_at or '-'}Z")
            if changes:
                print("\nChanges:")
                for c in changes:
                    print(f"  tender#{c.tender_id} {c.field_name}: {c.old_value} -> {c.new_value}")
    engine.dispose()

    if summary.status == RunStatus.BLOCKED_BY_HUMAN_VERIFICATION.value:
        return 2
    if summary.status == RunStatus.FAILED.value:
        return 1
    return 0


def _run_started(session, run_id: int):
    from app.database.models import CollectionRun

    return session.get(CollectionRun, run_id).started_at


if __name__ == "__main__":
    sys.exit(main())
