#!/usr/bin/env python3
"""Manually QUEUE document refresh jobs (reason MANUAL). Does not contact GeM.

The worker processes them (scripts/run_document_worker.py or the API scheduler).
Automatic, due-time based refreshes (PERIODIC_REFRESH) are handled by the
scheduler when DOCUMENT_WORKER_ENABLED=true; this script is for operators.

A tender that already has a queued (PENDING/RETRY) or RUNNING job is skipped.

Usage:
    python scripts/refresh_documents.py [--ongoing] [--limit 10] [--due-only]
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import select

from app.core.config import get_settings
from app.database.models import Tender
from app.database.session import build_engine, build_session_factory
from app.documents.job_queue import due_refresh_tender_ids, enqueue_job
from app.schemas.documents import DocumentJobReason
from app.utils.dates import utcnow

logger = logging.getLogger("refresh_documents")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)


def main():
    parser = argparse.ArgumentParser(
        description="Queue document refresh jobs for tenders"
    )
    parser.add_argument(
        "--ongoing",
        action="store_true",
        help="Only refresh ongoing tenders (default: all)",
    )
    parser.add_argument(
        "--due-only",
        action="store_true",
        help="Only ONGOING tenders whose last job is older than DOCUMENT_REFRESH_INTERVAL_MINUTES",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Maximum number of tenders to queue (default: 10)",
    )
    args = parser.parse_args()

    settings = get_settings()
    engine = build_engine(settings.resolved_database_url)
    session_factory = build_session_factory(engine)
    db = session_factory()

    try:
        now = utcnow()
        if args.due_only:
            tender_ids = due_refresh_tender_ids(
                db, now=now, interval_minutes=settings.document_refresh_interval_minutes, limit=args.limit
            )
            tenders = db.scalars(select(Tender).where(Tender.id.in_(tender_ids))).all() if tender_ids else []
        else:
            stmt = select(Tender)
            if args.ongoing:
                stmt = stmt.where(Tender.status == "ONGOING")
            tenders = db.scalars(stmt.order_by(Tender.last_seen_at.desc()).limit(args.limit)).all()

        logger.info(f"Considering {len(tenders)} tenders")

        refreshed = 0
        for tender in tenders:
            res = enqueue_job(db, tender.id, DocumentJobReason.MANUAL, now=now)
            if not res.created:
                logger.info(f"Skipping {tender.bid_number}: {res.skipped_reason} (job {res.job_id})")
                continue
            refreshed += 1
            logger.info(f"Queued refresh for {tender.bid_number} (job {res.job_id})")

        db.commit()
        logger.info(f"Successfully queued {refreshed} document refresh jobs")

    except Exception as e:
        logger.exception(f"Error refreshing documents: {e}")
        sys.exit(1)

    finally:
        db.close()
        engine.dispose()


if __name__ == "__main__":
    main()
