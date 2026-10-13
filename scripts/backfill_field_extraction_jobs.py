#!/usr/bin/env python
"""Stage 3B: bounded, resumable BACKFILL of field-extraction jobs (queues only).

Candidates: CURRENT Stage 3A extractions with status SUCCESS / PARTIAL_SUCCESS that
have never had a Stage 3B job and have no current Stage 3B run. Safe to stop/re-run.

    python scripts/backfill_field_extraction_jobs.py --limit 20 --dry-run
    python scripts/backfill_field_extraction_jobs.py --limit 20
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
from app.database.models import DocumentExtraction, DocumentVersion, Tender, TenderDocument  # noqa: E402
from app.database.session import build_engine, build_session_factory, run_migrations  # noqa: E402
from app.fields.job_queue import backfill_candidate_ids, backfill_field_jobs  # noqa: E402

MAX_LIMIT = 1000


def main(argv: list[str] | None = None) -> int:
    settings = Settings()
    p = argparse.ArgumentParser(description="Queue BACKFILL Stage 3B jobs (bounded).")
    p.add_argument("--limit", type=int, default=settings.field_extraction_backfill_batch_size)
    p.add_argument("--dry-run", action="store_true")
    a = p.parse_args(argv)
    if not 1 <= a.limit <= MAX_LIMIT:
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
            ids = backfill_field_jobs(s, limit=a.limit, dry_run=a.dry_run)
            labels = {}
            if ids:
                for eid, bid, dtype, vn in s.execute(
                        select(DocumentExtraction.id, Tender.bid_number, TenderDocument.document_type,
                               DocumentVersion.version_number)
                        .join(DocumentVersion, DocumentVersion.id == DocumentExtraction.document_version_id)
                        .join(TenderDocument, TenderDocument.id == DocumentVersion.document_id)
                        .join(Tender, Tender.id == TenderDocument.tender_id)
                        .where(DocumentExtraction.id.in_(ids))).all():
                    labels[eid] = f"{bid} {dtype} v{vn}"
            s.rollback() if a.dry_run else s.commit()
        print(f"Backfill candidates before this run: {remaining}")
        for eid in ids:
            print(f"  {'would queue' if a.dry_run else 'queued'} Stage 3A extraction {eid}: {labels.get(eid)}")
        print(f"{'Would create' if a.dry_run else 'Created'} {len(ids)} job(s); "
              f"{remaining - (0 if a.dry_run else len(ids))} candidate(s) remain.")
        return 0
    finally:
        engine.dispose()


if __name__ == "__main__":
    sys.exit(main())
