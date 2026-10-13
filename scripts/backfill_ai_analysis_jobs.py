#!/usr/bin/env python
"""Stage 3C: bounded BACKFILL of AI-analysis jobs (QUEUES ONLY - no provider call).

Candidates: CURRENT, usable Stage 3B runs that never had a Stage 3C job and have no
current analysis. --limit is REQUIRED (max 50) so nothing large is queued by accident;
queued jobs are processed only by the AI worker (disabled by default) or the CLI.

    python scripts/backfill_ai_analysis_jobs.py --limit 5 --dry-run
    python scripts/backfill_ai_analysis_jobs.py --limit 5
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.ai.job_queue import backfill_ai_jobs, backfill_candidate_ids  # noqa: E402
from app.core.config import Settings  # noqa: E402
from app.core.logging import setup_logging  # noqa: E402
from app.database.models import TenderFieldExtraction  # noqa: E402
from app.database.session import build_engine, build_session_factory, run_migrations  # noqa: E402

MAX_LIMIT = 50


def main(argv: list[str] | None = None) -> int:
    settings = Settings()
    p = argparse.ArgumentParser(description="Queue BACKFILL Stage 3C jobs (bounded; queue only).")
    p.add_argument("--limit", type=int, required=True, help=f"1..{MAX_LIMIT}")
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
            remaining = len(backfill_candidate_ids(s, limit=10**9)) if settings.ai_analysis_scope == "DOCUMENT" else "corpus fingerprints checked during backfill"
            ids = backfill_ai_jobs(s, settings, limit=a.limit, dry_run=a.dry_run)
            labels = {r.id: f"{r.bid_number} {r.document_type} v{r.version_number}"
                      for r in s.query(TenderFieldExtraction).filter(TenderFieldExtraction.id.in_(ids or [0]))}
            s.rollback() if a.dry_run else s.commit()
        print(f"Backfill candidates before this run: {remaining}")
        for i in ids:
            kind = 'Tender corpus' if settings.ai_analysis_scope == 'TENDER_CORPUS' else 'Stage 3B extraction'
            print(f"  {'would queue' if a.dry_run else 'queued'} {kind} {i}")
        print(f"{'Would create' if a.dry_run else 'Created'} {len(ids)} job(s); "
              f"{remaining - (0 if a.dry_run else len(ids)) if isinstance(remaining,int) else remaining} candidate(s) remain. "
              "Queued jobs are NOT processed until you run the AI worker.")
        return 0
    finally:
        engine.dispose()


if __name__ == "__main__":
    sys.exit(main())
