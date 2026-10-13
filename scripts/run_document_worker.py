#!/usr/bin/env python
"""Stage 2B document job worker (CLI).

Processes queued DocumentJobs with the proven Stage 2A DocumentsService,
one job at a time, with conservative pacing. Never processes the whole queue
unless you explicitly ask for a long-running loop.

Examples
--------
    # Controlled live test: queue (or reuse) a MANUAL job for ONE tender and process only it
    python scripts/run_document_worker.py --bid GEM/2026/B/8122868

    # Process at most 1 due job, then exit (default --limit 1, max 100)
    python scripts/run_document_worker.py --once
    python scripts/run_document_worker.py --once --limit 5

    # Long-running worker (polls every DOCUMENT_JOB_POLL_SECONDS); Ctrl+C to stop
    python scripts/run_document_worker.py --loop
    python scripts/run_document_worker.py --loop --limit 20      # stop after 20 jobs
    python scripts/run_document_worker.py --loop --with-refresh  # also queue periodic refreshes

    # Process one specific job id (only if it is due)
    python scripts/run_document_worker.py --job-id 1540

    # Housekeeping / visibility (no GeM requests)
    python scripts/run_document_worker.py --recover-only
    python scripts/run_document_worker.py --status

Ctrl+C: the first press lets the in-flight job finish and then exits; a second
press aborts immediately (the job is recovered on the next start).

Exit codes: 0 ok (success / partial / nothing to do), 1 a job FAILED,
2 BLOCKED or block cool-down active, 3 another worker is running,
4 a job was scheduled for RETRY, 5 bad arguments / tender not found.
"""

from __future__ import annotations

import argparse
import json
import signal
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import select  # noqa: E402

from app.core.config import Settings  # noqa: E402
from app.core.logging import setup_logging  # noqa: E402
from app.database.models import DocumentJob, DocumentVersion, Tender, TenderDocument  # noqa: E402
from app.database.session import build_engine, build_session_factory, run_migrations  # noqa: E402
from app.documents.job_queue import enqueue_job  # noqa: E402
from app.documents.job_worker import (  # noqa: E402
    SKIP_BUSY,
    SKIP_COOLDOWN,
    BatchResult,
    DocumentJobWorker,
)
from app.schemas.documents import DocumentJobReason, DocumentJobStatus  # noqa: E402
from app.services.job_status import document_worker_status  # noqa: E402
from app.utils.bid_number import InvalidBidNumber, normalize_bid_number  # noqa: E402
from app.utils.dates import utcnow  # noqa: E402

MAX_ONCE_LIMIT = 100


def _install_signal_handlers(worker: DocumentJobWorker) -> None:
    state = {"pressed": 0}

    def handler(signum, frame):  # pragma: no cover - interactive
        state["pressed"] += 1
        if state["pressed"] == 1:
            print("\nStop requested: finishing the current job, then exiting "
                  "(press Ctrl+C again to abort immediately)...", flush=True)
            worker.request_stop()
        else:
            signal.signal(signal.SIGINT, signal.default_int_handler)
            raise KeyboardInterrupt

    signal.signal(signal.SIGINT, handler)
    if hasattr(signal, "SIGBREAK"):  # Windows Ctrl+Break
        signal.signal(signal.SIGBREAK, handler)


def _documents_line(factory, tender_id: int) -> list[str]:
    with factory() as s:
        docs = s.scalars(select(TenderDocument).where(TenderDocument.tender_id == tender_id)
                         .order_by(TenderDocument.id)).all()
        lines = []
        for d in docs:
            cur = s.get(DocumentVersion, d.current_version_id) if d.current_version_id else None
            n_versions = len(d.versions)
            lines.append(f"{d.document_type} v{cur.version_number if cur else '-'}"
                         f"  ({n_versions} version(s) stored, key={d.document_key})")
        return lines


def _print_batch(batch: BatchResult, factory) -> None:
    if batch.recovered_stale:
        print(f"Recovered orphaned RUNNING job(s): {batch.recovered_stale}")
    if batch.skipped_reason == SKIP_BUSY:
        print("Another document worker run is in progress on this machine. Try again later.")
        return
    if batch.skipped_reason == SKIP_COOLDOWN:
        print("Paused: a recent job was BLOCKED by GeM human verification / access control.")
        print("Processing resumes automatically after DOCUMENT_BLOCK_COOLDOWN_MINUTES. No bypass is attempted.")
        return
    if not batch.jobs:
        print("No due document jobs.")
        return
    for r in batch.jobs:
        s = r.summary or {}
        print()
        print(f"Job {r.job_id}  tender {r.bid_number} (id {r.tender_id})  reason={r.reason or 'LEGACY'}  "
              f"attempt={r.attempt}")
        print(f"Lifecycle: PENDING/RETRY -> RUNNING -> {r.status}")
        print(f"Stage 2A result: {s.get('outcome') or '-'}")
        print(f"Documents discovered: {s.get('discovered', 0)}")
        print(f"Documents downloaded: {s.get('downloaded', 0)}")
        print(f"Unchanged: {s.get('unchanged', 0)}")
        print(f"Failed: {s.get('failed', 0)}")
        if r.next_retry_at:
            print(f"Next retry at: {r.next_retry_at.isoformat(timespec='seconds')}Z")
        if r.error_code or r.error_message:
            print(f"Error: {r.error_code}: {(r.error_message or '')[:500]}")
        if r.lease_lost:
            print("WARNING: job lease lost (recovered elsewhere); final state not written.")
        docs = _documents_line(factory, r.tender_id)
        if docs:
            print("Stored documents:")
            for line in docs:
                print(f"  {line}")
    if batch.skipped_reason:
        print(f"\nStopped early: {batch.skipped_reason}")


def _exit_code(batch: BatchResult) -> int:
    if batch.skipped_reason == SKIP_BUSY:
        return 3
    if batch.skipped_reason == SKIP_COOLDOWN:
        return 2
    statuses = {r.status for r in batch.jobs}
    if DocumentJobStatus.BLOCKED.value in statuses:
        return 2
    if DocumentJobStatus.FAILED.value in statuses:
        return 1
    if DocumentJobStatus.RETRY.value in statuses:
        return 4
    return 0


def _prepare_bid_job(factory, bid: str) -> tuple[int | None, str]:
    """Queue (or reuse) the job for one tender. Returns (job_id, message)."""
    try:
        bid_number = normalize_bid_number(bid)
    except InvalidBidNumber as e:
        return None, f"Invalid bid number: {e}"
    with factory() as s:
        tender = s.scalar(select(Tender).where(Tender.bid_number == bid_number))
        if tender is None:
            return None, f"Tender {bid_number} not found in database (run Stage 1 collection first)."
        res = enqueue_job(s, tender.id, DocumentJobReason.MANUAL)
        job = res.job
        if job is None:
            s.rollback()
            return None, f"Could not queue a job for {bid_number}."
        if job.status == DocumentJobStatus.RUNNING.value:
            s.rollback()
            return None, f"Job {job.id} for {bid_number} is already RUNNING elsewhere."
        if job.next_retry_at is not None and job.next_retry_at > utcnow():
            # Explicit human request for ONE tender: make its queued job due now.
            job.next_retry_at = utcnow()
        s.commit()
        verb = "Queued new" if res.created else "Reusing existing"
        return job.id, f"{verb} job {job.id} ({job.status}, reason={job.reason or 'LEGACY'}) for {bid_number}"


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except Exception:
            pass
    p = argparse.ArgumentParser(description="Stage 2B document job worker.")
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--once", action="store_true", help="process up to --limit due jobs (default 1), then exit")
    mode.add_argument("--loop", action="store_true", help="keep polling the queue until Ctrl+C (or --limit jobs)")
    mode.add_argument("--bid", help="queue/reuse a MANUAL job for this bid number and process only that job")
    mode.add_argument("--job-id", type=int, help="process only this job id (if it is due)")
    mode.add_argument("--recover-only", action="store_true", help="only recover orphaned RUNNING jobs")
    mode.add_argument("--status", action="store_true", help="print queue/worker status as JSON")
    p.add_argument("--limit", type=int, help="--once: jobs to process (default 1, max 100); --loop: stop after N jobs")
    p.add_argument("--with-refresh", action="store_true", help="--loop: also queue due PERIODIC_REFRESH jobs")
    p.add_argument("--verbose", "-v", action="store_true")
    args = p.parse_args(argv)

    settings = Settings()
    setup_logging("DEBUG" if args.verbose else settings.log_level, settings.log_format)
    if args.limit is not None and args.limit < 1:
        print("--limit must be >= 1")
        return 5
    if args.once and (args.limit or 1) > MAX_ONCE_LIMIT:
        print(f"--once --limit is capped at {MAX_ONCE_LIMIT} to keep GeM traffic conservative.")
        return 5

    db_url = settings.resolved_database_url
    if settings.auto_migrate:
        run_migrations(db_url)
    engine = build_engine(db_url)
    factory = build_session_factory(engine)
    worker = DocumentJobWorker(settings, factory)
    _install_signal_handlers(worker)

    try:
        if args.status:
            with factory() as s:
                print(json.dumps(document_worker_status(s, worker), indent=2, default=str))
            return 0

        if args.recover_only:
            n = worker.recover_stale_jobs()
            print(f"Recovered orphaned RUNNING job(s): {n}")
            return 0

        if args.bid or args.job_id:
            job_id = args.job_id
            if args.bid:
                job_id, msg = _prepare_bid_job(factory, args.bid)
                print(msg)
                if job_id is None:
                    return 5
            batch = worker.run_batch(max_jobs=1, job_id=job_id)
            if not batch.jobs and batch.skipped_reason is None:
                with factory() as s:
                    job = s.get(DocumentJob, job_id)
                if job is None:
                    print(f"Job {job_id} not found.")
                    return 5
                print(f"Job {job_id} is not eligible now (status={job.status}, "
                      f"next_retry_at={job.next_retry_at}). Nothing processed.")
                return 0
            _print_batch(batch, factory)
            return _exit_code(batch)

        if args.once:
            batch = worker.run_batch(max_jobs=args.limit or 1)
            _print_batch(batch, factory)
            return _exit_code(batch)

        # --loop
        total = 0
        worst = 0
        last_refresh = 0.0
        print(f"Document worker loop started (poll {settings.document_job_poll_seconds}s, "
              f"{settings.document_worker_max_jobs_per_run} job(s)/poll, "
              f"{settings.document_inter_job_delay_seconds}s between jobs). Ctrl+C to stop.")
        while not worker.stop_requested:
            if args.with_refresh and settings.periodic_document_refresh_enabled and \
                    time.monotonic() - last_refresh >= settings.document_refresh_check_minutes * 60:
                queued = worker.queue_due_refreshes()
                last_refresh = time.monotonic()
                if queued:
                    print(f"Queued {queued} periodic refresh job(s).")
            per_run = settings.document_worker_max_jobs_per_run
            if args.limit:
                per_run = min(per_run, args.limit - total)
            batch = worker.run_batch(max_jobs=per_run)
            if batch.jobs or batch.skipped_reason not in (None, SKIP_BUSY):
                _print_batch(batch, factory)
            total += batch.processed
            worst = max(worst, _exit_code(batch) if batch.jobs else 0)
            if args.limit and total >= args.limit:
                print(f"\nReached --limit {args.limit}.")
                break
            # Poll pause (interruptible); inter-job pacing happens inside run_batch.
            if not worker.pause(settings.document_job_poll_seconds):
                break
        print(f"Worker stopped. Jobs processed: {total}")
        return 0
    except KeyboardInterrupt:  # second Ctrl+C
        print("\nAborted. Any job left RUNNING is recovered automatically on the next start.")
        return 130
    finally:
        engine.dispose()


if __name__ == "__main__":
    sys.exit(main())
