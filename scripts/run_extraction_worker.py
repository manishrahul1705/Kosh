#!/usr/bin/env python
"""Stage 3A extraction worker (CLI). Local parsing only - never contacts GeM.

    python scripts/run_extraction_worker.py --document-version-id 13      # ONE version (queue/reuse its job)
    python scripts/run_extraction_worker.py --document-version-id 13 --force   # controlled re-extraction
    python scripts/run_extraction_worker.py --once                        # at most 1 due job
    python scripts/run_extraction_worker.py --limit 5                     # at most 5 due jobs (max 100)
    python scripts/run_extraction_worker.py --job-id 7                    # one specific job, if due
    python scripts/run_extraction_worker.py --loop                        # keep polling; Ctrl+C to stop
    python scripts/run_extraction_worker.py --status                      # JSON status, no work
    python scripts/run_extraction_worker.py --recover-only

Exit codes: 0 ok (SUCCESS/PARTIAL/SKIPPED/nothing to do), 1 FAILED, 2 OCR_REQUIRED,
3 another extraction worker is running, 4 RETRY scheduled, 5 bad arguments / not found.
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
from app.database.models import DocumentExtraction, ExtractionJob  # noqa: E402
from app.database.session import build_engine, build_session_factory, run_migrations  # noqa: E402
from app.extraction.constants import ExtractionJobReason, ExtractionJobStatus  # noqa: E402
from app.extraction.job_queue import enqueue_extraction  # noqa: E402
from app.extraction.job_worker import SKIP_BUSY, ExtractionBatch, ExtractionJobWorker  # noqa: E402
from app.extraction.service import ExtractionService, current_extraction_id  # noqa: E402
from app.services.extraction_status import extraction_status  # noqa: E402
from app.utils.dates import utcnow  # noqa: E402

MAX_LIMIT = 100


def _print_batch(batch: ExtractionBatch, factory, service: ExtractionService) -> None:
    if batch.recovered_stale:
        print(f"Recovered orphaned RUNNING extraction job(s): {batch.recovered_stale}")
    if batch.skipped_reason == SKIP_BUSY:
        print("Another extraction worker run is in progress on this machine. Try again later.")
        return
    if not batch.jobs:
        print("No due extraction jobs.")
        return
    for r in batch.jobs:
        with factory() as s:
            info = service.load_version(s, r.document_version_id)
            e = s.get(DocumentExtraction, r.extraction_id) if r.extraction_id else None
        print()
        print(f"Job {r.job_id} (attempt {r.attempt}): RUNNING -> {r.status}   outcome={r.outcome}")
        if info:
            print(f"Tender:   {info.bid_number}")
            print(f"Document: {info.document_type} v{info.version_number}   (document_version_id {info.version_id})")
        if e is not None:
            print(f"Extraction: {e.status}   (extraction_id {e.id}, {e.extractor_version}, current={e.is_current})")
            print(f"Pages: {e.page_count}")
            print(f"Pages with text: {e.pages_with_text}")
            print(f"Words: {e.total_words}")
            print(f"Characters: {e.total_characters}")
            print(f"Tables: {e.tables_found}")
            print(f"Sections: {e.sections_found}")
            print(f"Quality: {e.quality_status}   text_class={e.text_class}   coverage={e.text_coverage_ratio}")
            print(f"Unmapped glyphs (Hindi without Unicode map): {e.unmapped_glyphs}")
            print(f"Duration: {e.duration_ms} ms")
        if r.error_code:
            print(f"Note: {r.error_code}: {(r.error_message or '')[:300]}")
        if r.next_retry_at:
            print(f"Next retry at: {r.next_retry_at.isoformat(timespec='seconds')}Z")


def _exit_code(batch: ExtractionBatch) -> int:
    if batch.skipped_reason == SKIP_BUSY:
        return 3
    statuses = {r.status for r in batch.jobs}
    if ExtractionJobStatus.FAILED.value in statuses:
        return 1
    if ExtractionJobStatus.OCR_REQUIRED.value in statuses:
        return 2
    if ExtractionJobStatus.RETRY.value in statuses:
        return 4
    return 0


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except Exception:
            pass
    p = argparse.ArgumentParser(description="Stage 3A extraction worker")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--once", action="store_true", help="process up to --limit due jobs (default 1)")
    mode.add_argument("--loop", action="store_true", help="poll until Ctrl+C")
    mode.add_argument("--document-version-id", type=int, help="queue/reuse a job for ONE version and process only it")
    mode.add_argument("--job-id", type=int, help="process only this job (if due)")
    mode.add_argument("--status", action="store_true")
    mode.add_argument("--recover-only", action="store_true")
    p.add_argument("--limit", type=int, help=f"jobs to process (max {MAX_LIMIT}); implies --once")
    p.add_argument("--force", action="store_true", help="with --document-version-id: re-extract even if extracted")
    p.add_argument("--verbose", "-v", action="store_true")
    args = p.parse_args(argv)
    if not any([args.once, args.loop, args.document_version_id, args.job_id, args.status, args.recover_only,
                args.limit]):
        p.print_help()
        return 5
    if args.limit is not None and not 1 <= args.limit <= MAX_LIMIT:
        print(f"--limit must be between 1 and {MAX_LIMIT}")
        return 5
    if args.force and not args.document_version_id:
        print("--force is only allowed together with --document-version-id")
        return 5

    settings = Settings()
    setup_logging("DEBUG" if args.verbose else settings.log_level, settings.log_format)
    if settings.auto_migrate:
        run_migrations(settings.resolved_database_url)
    engine = build_engine(settings.resolved_database_url)
    factory = build_session_factory(engine)
    service = ExtractionService(settings, factory)
    worker = ExtractionJobWorker(settings, factory, service)

    def _on_sigint(signum, frame):  # pragma: no cover - interactive
        print("\nStop requested: finishing the current document, then exiting...", flush=True)
        worker.request_stop()
        signal.signal(signal.SIGINT, signal.default_int_handler)

    signal.signal(signal.SIGINT, _on_sigint)
    try:
        if args.status:
            with factory() as s:
                print(json.dumps(extraction_status(s, worker), indent=2, default=str))
            return 0
        if args.recover_only:
            print(f"Recovered orphaned RUNNING extraction job(s): {worker.recover_stale_jobs()}")
            return 0
        if args.document_version_id or args.job_id:
            job_id = args.job_id
            if args.document_version_id:
                with factory() as s:
                    reason = ExtractionJobReason.REEXTRACT if args.force else ExtractionJobReason.MANUAL
                    res = enqueue_extraction(s, args.document_version_id, reason, force=args.force)
                    if res.skipped_reason == "not_eligible":
                        print(f"DocumentVersion {args.document_version_id} not found, not VALID or has no file.")
                        return 5
                    if res.skipped_reason == "already_extracted":
                        s.rollback()
                        ext_id = current_extraction_id(s, args.document_version_id)
                        print(f"DocumentVersion {args.document_version_id} is already extracted "
                              f"(extraction_id {ext_id}). Use --force to re-extract.")
                        return 0
                    if res.skipped_reason == "already_running":
                        print("An extraction of this version is RUNNING elsewhere.")
                        return 3
                    job = res.job
                    if job.next_retry_at is not None and job.next_retry_at > utcnow():
                        job.next_retry_at = utcnow()  # explicit human request for ONE version
                    s.commit()
                    job_id = job.id
                    print(f"{'Queued' if res.created else 'Reusing'} extraction job {job_id} "
                          f"for document_version_id {args.document_version_id} (force={args.force})")
            batch = worker.run_batch(max_jobs=1, job_id=job_id)
            if not batch.jobs and batch.skipped_reason is None:
                with factory() as s:
                    j = s.get(ExtractionJob, job_id)
                print(f"Job {job_id} not eligible now (status={getattr(j, 'status', 'missing')}).")
                return 0 if j else 5
            _print_batch(batch, factory, service)
            return _exit_code(batch)
        if args.once or args.limit:
            batch = worker.run_batch(max_jobs=args.limit or 1)
            _print_batch(batch, factory, service)
            return _exit_code(batch)
        # --loop
        print(f"Extraction worker loop (poll {settings.extraction_job_poll_seconds}s, "
              f"{settings.extraction_worker_max_jobs_per_run} job(s)/poll). Ctrl+C to stop.")
        total = 0
        while not worker.stop_requested:
            batch = worker.run_batch()
            if batch.jobs:
                _print_batch(batch, factory, service)
            total += batch.processed
            if not worker.pause(settings.extraction_job_poll_seconds):
                break
        print(f"Stopped. Jobs processed: {total}")
        return 0
    except KeyboardInterrupt:
        print("\nAborted. An interrupted job is recovered automatically on the next start.")
        return 130
    finally:
        engine.dispose()


if __name__ == "__main__":
    sys.exit(main())
