#!/usr/bin/env python3
"""DEPRECATED NAME - kept for compatibility.

Despite its name this script never processed jobs: it only QUEUES document
jobs for tenders that have none (a backfill). It now delegates to
``scripts/backfill_document_jobs.py`` (bounded, resumable, deduplicated,
reason=BACKFILL).

To actually PROCESS jobs use:
    python scripts/run_document_worker.py --once            # one job
    python scripts/run_document_worker.py --bid <BID>       # one specific tender

Usage (unchanged):
    python scripts/process_pending_documents.py [--limit 10]
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from backfill_document_jobs import main  # noqa: E402

if __name__ == "__main__":
    print("NOTE: process_pending_documents.py only queues jobs (backfill). "
          "Use scripts/run_document_worker.py to process them.", file=sys.stderr)
    sys.exit(main())
