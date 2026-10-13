#!/usr/bin/env python
"""Stage 2B: bounded, resumable BACKFILL of DocumentJobs for existing tenders.

This only QUEUES jobs (reason BACKFILL); it never contacts GeM. The worker
(`scripts/run_document_worker.py`, or the API scheduler when
DOCUMENT_WORKER_ENABLED=true) processes them later at a conservative pace.

Candidates: tenders that have never had a DocumentJob AND have no stored
document yet (e.g. a tender acquired manually with download_tender_documents.py
is skipped). ONGOING tenders first, newest first. Safe to stop and re-run:
once a tender has a job it is no longer a candidate, and duplicates are
impossible (one queued job per tender).

Usage:
    python scripts/backfill_document_jobs.py                 # DOCUMENT_BACKFILL_BATCH_SIZE (10)
    python scripts/backfill_document_jobs.py --limit 50
    python scripts/backfill_document_jobs.py --ongoing-only --dry-run
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import select  # noqa: E402

from app.core.config import Settings  # noqa: E402
from app.core.constants import TenderStatus  # noqa: E402
from app.core.logging import setup_logging  # noqa: E402
from app.database.models import Tender  # noqa: E402
from app.database.session import build_engine, build_session_factory, run_migrations  # noqa: E402
from app.documents.job_queue import backfill_candidate_ids, backfill_jobs  # noqa: E402

MAX_LIMIT = 5000


def main(argv: list[str] | None = None) -> int:
    settings = Settings()
    p = argparse.ArgumentParser(description="Queue BACKFILL document jobs for existing tenders (bounded).")
    p.add_argument("--limit", type=int, default=settings.document_backfill_batch_size,
                   help=f"max jobs to create (default DOCUMENT_BACKFILL_BATCH_SIZE={settings.document_backfill_batch_size})")
    p.add_argument("--ongoing-only", action="store_true", help="only ONGOING tenders")
    p.add_argument("--dry-run", action="store_true", help="show what would be queued, change nothing")
    args = p.parse_args(argv)
    if not 1 <= args.limit <= MAX_LIMIT:
        print(f"--limit must be between 1 and {MAX_LIMIT}")
        return 2

    setup_logging("WARNING", settings.log_format)
    db_url = settings.resolved_database_url
    if settings.auto_migrate:
        run_migrations(db_url)
    engine = build_engine(db_url)
    factory = build_session_factory(engine)
    statuses = (TenderStatus.ONGOING.value,) if args.ongoing_only else None
    try:
        with factory() as s:
            remaining = len(backfill_candidate_ids(s, limit=10**9, statuses=statuses))
            ids = backfill_jobs(s, limit=args.limit, statuses=statuses, dry_run=args.dry_run)
            bids = dict(s.execute(select(Tender.id, Tender.bid_number).where(Tender.id.in_(ids))).all()) if ids else {}
            if args.dry_run:
                s.rollback()
            else:
                s.commit()
        print(f"Backfill candidates before this run: {remaining}")
        for tid in ids:
            print(f"  {'would queue' if args.dry_run else 'queued'} BACKFILL job for {bids.get(tid)} (tender id {tid})")
        print(f"{'Would create' if args.dry_run else 'Created'} {len(ids)} job(s); "
              f"{max(0, remaining - (0 if args.dry_run else len(ids)))} candidate(s) remain.")
        return 0
    finally:
        engine.dispose()


if __name__ == "__main__":
    sys.exit(main())
