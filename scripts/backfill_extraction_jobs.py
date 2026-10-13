#!/usr/bin/env python
"""Stage 3A: bounded, resumable BACKFILL of extraction jobs for already stored versions.

Only QUEUES jobs (reason BACKFILL); nothing is parsed here. Candidates: VALID
DocumentVersions with a stored file, no extraction job ever, and no current
extraction. ONGOING tenders first, newest versions first. Safe to stop/re-run.

    python scripts/backfill_extraction_jobs.py --limit 20 --dry-run
    python scripts/backfill_extraction_jobs.py --limit 20
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
from app.core.logging import setup_logging  # noqa: E402
from app.database.models import DocumentVersion, Tender, TenderDocument  # noqa: E402
from app.database.session import build_engine, build_session_factory, run_migrations  # noqa: E402
from app.extraction.job_queue import backfill_candidate_ids, backfill_extraction_jobs  # noqa: E402

MAX_LIMIT = 1000


def main(argv: list[str] | None = None) -> int:
    settings = Settings()
    p = argparse.ArgumentParser(description="Queue BACKFILL extraction jobs (bounded).")
    p.add_argument("--limit", type=int, default=settings.extraction_backfill_batch_size,
                   help=f"max jobs to create (default EXTRACTION_BACKFILL_BATCH_SIZE={settings.extraction_backfill_batch_size})")
    p.add_argument("--dry-run", action="store_true", help="show what would be queued; change nothing")
    args = p.parse_args(argv)
    if not 1 <= args.limit <= MAX_LIMIT:
        print(f"--limit must be between 1 and {MAX_LIMIT}")
        return 2
    setup_logging("WARNING", settings.log_format)
    if settings.auto_migrate:
        run_migrations(settings.resolved_database_url)
    engine = build_engine(settings.resolved_database_url)
    factory = build_session_factory(engine)
    try:
        with factory() as s:
            remaining = len(backfill_candidate_ids(s, limit=10**9))
            ids = backfill_extraction_jobs(s, limit=args.limit, dry_run=args.dry_run)
            labels = {}
            if ids:
                for vid, bid, dtype, vn in s.execute(
                        select(DocumentVersion.id, Tender.bid_number, TenderDocument.document_type,
                               DocumentVersion.version_number)
                        .join(TenderDocument, TenderDocument.id == DocumentVersion.document_id)
                        .join(Tender, Tender.id == TenderDocument.tender_id)
                        .where(DocumentVersion.id.in_(ids))).all():
                    labels[vid] = f"{bid} {dtype} v{vn}"
            if args.dry_run:
                s.rollback()
            else:
                s.commit()
        print(f"Backfill candidates before this run: {remaining}")
        for vid in ids:
            print(f"  {'would queue' if args.dry_run else 'queued'} document_version_id {vid}: {labels.get(vid)}")
        print(f"{'Would create' if args.dry_run else 'Created'} {len(ids)} job(s); "
              f"{remaining - (0 if args.dry_run else len(ids))} candidate(s) remain.")
        return 0
    finally:
        engine.dispose()


if __name__ == "__main__":
    sys.exit(main())
