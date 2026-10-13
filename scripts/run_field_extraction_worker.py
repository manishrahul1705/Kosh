#!/usr/bin/env python
"""Stage 3B field-extraction worker (CLI). Pure database work - no GeM, no PDF access.

    python scripts/run_field_extraction_worker.py --stage3a-extraction-id 1           # ONE extraction
    python scripts/run_field_extraction_worker.py --stage3a-extraction-id 1 --force   # controlled re-run (keeps history)
    python scripts/run_field_extraction_worker.py --once                              # at most 1 due job
    python scripts/run_field_extraction_worker.py --limit 5                           # at most 5 due jobs (max 100)
    python scripts/run_field_extraction_worker.py --job-id 3
    python scripts/run_field_extraction_worker.py --status
    python scripts/run_field_extraction_worker.py --recover-only
    python scripts/run_field_extraction_worker.py --loop                              # Ctrl+C to stop

Exit codes: 0 ok (SUCCESS / PARTIAL_SUCCESS / SKIPPED / nothing to do), 1 FAILED,
3 another field-extraction worker is running, 4 RETRY scheduled, 5 bad arguments / not ready.
"""

from __future__ import annotations

import argparse
import json
import signal
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.config import Settings  # noqa: E402
from app.core.logging import setup_logging  # noqa: E402
from app.database.models import FieldExtractionJob, TenderFieldExtraction  # noqa: E402
from app.database.session import build_engine, build_session_factory, run_migrations  # noqa: E402
from app.fields.constants import FieldJobReason, FieldJobStatus  # noqa: E402
from app.fields.job_queue import enqueue_field_extraction  # noqa: E402
from app.fields.job_worker import SKIP_BUSY, FieldBatch, FieldExtractionJobWorker  # noqa: E402
from app.fields.service import current_field_extraction_id  # noqa: E402
from app.services.field_status import field_extraction_status  # noqa: E402

MAX_LIMIT = 100


def _print(batch: FieldBatch, factory) -> None:
    if batch.recovered_stale:
        print(f"Recovered orphaned RUNNING field-extraction job(s): {batch.recovered_stale}")
    if batch.skipped_reason == SKIP_BUSY:
        print("Another field-extraction worker run is in progress on this machine. Try again later.")
        return
    if not batch.jobs:
        print("No due field-extraction jobs.")
        return
    for r in batch.jobs:
        print()
        print(f"Job {r.job_id} (attempt {r.attempt}): RUNNING -> {r.status}   outcome={r.outcome}")
        print(f"Stage 3A extraction: {r.stage3a_extraction_id}")
        if r.field_extraction_id:
            with factory() as s:
                run = s.get(TenderFieldExtraction, r.field_extraction_id)
            print(f"Tender:   {run.bid_number}")
            print(f"Document: {run.document_type} v{run.version_number}   (document_version_id {run.document_version_id})")
            print(f"Field extraction: {run.status}   (field_extraction_id {run.id}, {run.extractor_version}, "
                  f"current={run.is_current})")
            print(f"Fields: {run.fields_total} total | {run.fields_resolved} resolved | {run.fields_unknown} unknown | "
                  f"{run.fields_conflict} conflict | {run.candidates_total} evidence candidates")
        if r.error_code:
            print(f"Note: {r.error_code}: {(r.error_message or '')[:300]}")
        if r.next_retry_at:
            print(f"Next retry at: {r.next_retry_at.isoformat(timespec='seconds')}Z")


def _exit(batch: FieldBatch) -> int:
    if batch.skipped_reason == SKIP_BUSY:
        return 3
    st = {r.status for r in batch.jobs}
    if FieldJobStatus.FAILED.value in st:
        return 1
    if FieldJobStatus.RETRY.value in st:
        return 4
    return 0


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except Exception:
            pass
    p = argparse.ArgumentParser(description="Stage 3B field-extraction worker")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--once", action="store_true")
    mode.add_argument("--loop", action="store_true")
    mode.add_argument("--stage3a-extraction-id", type=int, help="queue/reuse a job for ONE Stage 3A extraction")
    mode.add_argument("--job-id", type=int)
    mode.add_argument("--status", action="store_true")
    mode.add_argument("--recover-only", action="store_true")
    p.add_argument("--limit", type=int, help=f"jobs to process (max {MAX_LIMIT}); implies --once")
    p.add_argument("--force", action="store_true", help="with --stage3a-extraction-id: re-run even if extracted")
    p.add_argument("--verbose", "-v", action="store_true")
    a = p.parse_args(argv)
    if not any([a.once, a.loop, a.stage3a_extraction_id, a.job_id, a.status, a.recover_only, a.limit]):
        p.print_help()
        return 5
    if a.limit is not None and not 1 <= a.limit <= MAX_LIMIT:
        print(f"--limit must be between 1 and {MAX_LIMIT}")
        return 5
    if a.force and not a.stage3a_extraction_id:
        print("--force is only allowed together with --stage3a-extraction-id")
        return 5

    settings = Settings()
    setup_logging("DEBUG" if a.verbose else settings.log_level, settings.log_format)
    if settings.auto_migrate:
        run_migrations(settings.resolved_database_url)
    engine = build_engine(settings.resolved_database_url)
    factory = build_session_factory(engine)
    worker = FieldExtractionJobWorker(settings, factory)

    def _sig(signum, frame):  # pragma: no cover - interactive
        print("\nStop requested: finishing the current job, then exiting...", flush=True)
        worker.request_stop()
        signal.signal(signal.SIGINT, signal.default_int_handler)

    signal.signal(signal.SIGINT, _sig)
    try:
        if a.status:
            with factory() as s:
                print(json.dumps(field_extraction_status(s, worker), indent=2, default=str))
            return 0
        if a.recover_only:
            print(f"Recovered orphaned RUNNING field-extraction job(s): {worker.recover_stale_jobs()}")
            return 0
        if a.stage3a_extraction_id or a.job_id:
            job_id = a.job_id
            if a.stage3a_extraction_id:
                with factory() as s:
                    res = enqueue_field_extraction(s, a.stage3a_extraction_id,
                                                   FieldJobReason.REEXTRACT if a.force else FieldJobReason.MANUAL,
                                                   force=a.force)
                    if res.skipped_reason == "not_ready":
                        s.rollback()
                        print(f"Stage 3A extraction {a.stage3a_extraction_id} not found, not current, or not usable "
                              "(needs SUCCESS / PARTIAL_SUCCESS). Nothing done.")
                        return 5
                    if res.skipped_reason == "already_extracted":
                        s.rollback()
                        print(f"Stage 3A extraction {a.stage3a_extraction_id} is already field-extracted "
                              f"(field_extraction_id {current_field_extraction_id(s, a.stage3a_extraction_id)}). "
                              "Use --force to re-run.")
                        return 0
                    if res.skipped_reason == "already_running":
                        print("A field extraction of this Stage 3A extraction is RUNNING elsewhere.")
                        return 3
                    s.commit()
                    job_id = res.job_id
                    print(f"{'Queued' if res.created else 'Reusing'} field-extraction job {job_id} "
                          f"for Stage 3A extraction {a.stage3a_extraction_id} (force={a.force})")
            batch = worker.run_batch(max_jobs=1, job_id=job_id)
            if not batch.jobs and batch.skipped_reason is None:
                with factory() as s:
                    j = s.get(FieldExtractionJob, job_id)
                print(f"Job {job_id} not eligible now (status={getattr(j, 'status', 'missing')}).")
                return 0 if j else 5
            _print(batch, factory)
            return _exit(batch)
        if a.once or a.limit:
            batch = worker.run_batch(max_jobs=a.limit or 1)
            _print(batch, factory)
            return _exit(batch)
        print(f"Field-extraction worker loop (poll {settings.field_extraction_job_poll_seconds}s). Ctrl+C to stop.")
        while not worker.stop_requested:
            batch = worker.run_batch()
            if batch.jobs:
                _print(batch, factory)
            if not worker.pause(settings.field_extraction_job_poll_seconds):
                break
        return 0
    except KeyboardInterrupt:
        print("\nAborted. An interrupted job is recovered automatically on the next start.")
        return 130
    finally:
        engine.dispose()


if __name__ == "__main__":
    sys.exit(main())
