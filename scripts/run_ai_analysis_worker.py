#!/usr/bin/env python
"""Stage 3C AI-analysis worker (CLI). Calls the CONFIGURED AI provider (AI_PROVIDER /
AI_MODEL / AI_API_KEY from the environment or .env). Never contacts GeM, never opens PDFs.

    python scripts/run_ai_analysis_worker.py --status
    python scripts/run_ai_analysis_worker.py --stage3b-extraction-id 1           # ONE analysis
    python scripts/run_ai_analysis_worker.py --stage3b-extraction-id 1 --force   # controlled re-analysis (keeps history)
    python scripts/run_ai_analysis_worker.py --once                              # at most 1 due job
    python scripts/run_ai_analysis_worker.py --limit 3                           # at most 3 due jobs (max 20)
    python scripts/run_ai_analysis_worker.py --job-id 4
    python scripts/run_ai_analysis_worker.py --recover-only
    python scripts/run_ai_analysis_worker.py --loop                              # Ctrl+C to stop

Offline check without any paid provider:  set AI_PROVIDER=mock for the command.

Exit codes: 0 ok (SUCCESS / PARTIAL_SUCCESS / SKIPPED / nothing to do), 1 FAILED,
2 BLOCKED (provider auth/config), 3 another AI worker is running, 4 RETRY scheduled,
5 bad arguments / not ready / provider not configured / daily limit reached.
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

from app.ai.constants import AIJobReason, AIJobStatus  # noqa: E402
from app.ai.job_queue import enqueue_ai_analysis  # noqa: E402
from app.ai.job_worker import (  # noqa: E402
    SKIP_BLOCKED,
    SKIP_BUSY,
    SKIP_DAILY_LIMIT,
    SKIP_NOT_CONFIGURED,
    AIAnalysisJobWorker,
    AIBatch,
)
from app.ai.providers import effective_model, effective_provider  # noqa: E402
from app.ai.service import current_analysis_id  # noqa: E402
from app.core.config import Settings  # noqa: E402
from app.core.logging import setup_logging  # noqa: E402
from app.database.models import AIAnalysisJob, AIAnalysisRun  # noqa: E402
from app.database.session import build_engine, build_session_factory, run_migrations  # noqa: E402
from app.services.ai_status import ai_analysis_status  # noqa: E402

MAX_LIMIT = 20


def _print(batch: AIBatch, factory) -> None:
    if batch.recovered_stale:
        print(f"Recovered orphaned RUNNING AI-analysis job(s): {batch.recovered_stale}")
    if batch.skipped_reason == SKIP_BUSY:
        print("Another AI-analysis worker run is in progress on this machine. Try again later.")
        return
    if batch.skipped_reason in (SKIP_NOT_CONFIGURED, SKIP_BLOCKED, SKIP_DAILY_LIMIT):
        print(f"No provider call made: {batch.skipped_reason}: {batch.skipped_detail}")
    if not batch.jobs:
        if not batch.skipped_reason:
            print("No due AI-analysis jobs.")
        return
    for r in batch.jobs:
        print()
        print(f"Job {r.job_id} (attempt {r.attempt}): RUNNING -> {r.status}   outcome={r.outcome}")
        print(f"Stage 3B extraction: {r.stage3b_extraction_id}")
        if r.analysis_run_id:
            with factory() as s:
                run = s.get(AIAnalysisRun, r.analysis_run_id)
            print(f"Tender:   {run.bid_number}")
            print(f"Document: {run.document_type} v{run.version_number}   (document_version_id "
                  f"{run.document_version_id}, Stage 3A extraction {run.stage3a_extraction_id})")
            print(f"AI analysis: {run.status}{' (' + run.status_code + ')' if run.status_code else ''}   "
                  f"(analysis_id {run.id}, current={run.is_current})")
            print(f"Provider: {run.provider}   Model: {run.model}   Prompt: {run.prompt_version}   "
                  f"Schema: {run.schema_version}")
            print(f"Evidence: {run.chunks_sent}/{run.chunks_total} chunks sent, {run.input_characters} characters")
            print(f"Result:   {run.requirements_count} requirements | {run.rejected_count} rejected | "
                  f"{run.flags_count} flags | {run.ambiguities_count} ambiguities | {run.conflicts_count} conflicts")
            print(f"Usage:    tokens in={run.input_tokens} out={run.output_tokens}  latency={run.latency_ms} ms  "
                  f"provider attempts={run.provider_attempts}")
        if r.error_code:
            print(f"Note: {r.error_code}: {(r.error_message or '')[:300]}")
        if r.next_retry_at:
            print(f"Next retry at: {r.next_retry_at.isoformat(timespec='seconds')}Z")


def _exit(batch: AIBatch) -> int:
    if batch.skipped_reason == SKIP_BUSY:
        return 3
    st = {r.status for r in batch.jobs}
    if AIJobStatus.BLOCKED.value in st:
        return 2
    if AIJobStatus.FAILED.value in st:
        return 1
    if AIJobStatus.RETRY.value in st:
        return 4
    if not batch.jobs and batch.skipped_reason in (SKIP_NOT_CONFIGURED, SKIP_BLOCKED, SKIP_DAILY_LIMIT):
        return 5
    return 0


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except Exception:
            pass
    p = argparse.ArgumentParser(description="Stage 3C AI-analysis worker")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--once", action="store_true")
    mode.add_argument("--loop", action="store_true")
    mode.add_argument("--stage3b-extraction-id", type=int, help="queue/reuse a job for ONE Stage 3B run")
    mode.add_argument("--job-id", type=int)
    mode.add_argument("--status", action="store_true")
    mode.add_argument("--recover-only", action="store_true")
    p.add_argument("--limit", type=int, help=f"jobs to process (max {MAX_LIMIT}); implies --once")
    p.add_argument("--force", action="store_true", help="with --stage3b-extraction-id: re-analyze even if analyzed")
    p.add_argument("--verbose", "-v", action="store_true")
    a = p.parse_args(argv)
    if not any([a.once, a.loop, a.stage3b_extraction_id, a.job_id, a.status, a.recover_only, a.limit]):
        p.print_help()
        return 5
    if a.limit is not None and not 1 <= a.limit <= MAX_LIMIT:
        print(f"--limit must be between 1 and {MAX_LIMIT}")
        return 5
    if a.force and not a.stage3b_extraction_id:
        print("--force is only allowed together with --stage3b-extraction-id")
        return 5

    settings = Settings()
    setup_logging("DEBUG" if a.verbose else settings.log_level, settings.log_format)
    if settings.auto_migrate:
        run_migrations(settings.resolved_database_url)
    engine = build_engine(settings.resolved_database_url)
    factory = build_session_factory(engine)
    worker = AIAnalysisJobWorker(settings, factory)

    def _sig(signum, frame):  # pragma: no cover - interactive
        print("\nStop requested: finishing the current job, then exiting...", flush=True)
        worker.request_stop()
        signal.signal(signal.SIGINT, signal.default_int_handler)

    signal.signal(signal.SIGINT, _sig)
    try:
        if a.status:
            with factory() as s:
                print(json.dumps(ai_analysis_status(s, worker), indent=2, default=str))
            return 0
        if a.recover_only:
            print(f"Recovered orphaned RUNNING AI-analysis job(s): {worker.recover_stale_jobs()}")
            return 0
        if a.stage3b_extraction_id or a.job_id:
            job_id = a.job_id
            if a.stage3b_extraction_id:
                with factory() as s:
                    res = enqueue_ai_analysis(s, a.stage3b_extraction_id,
                                              AIJobReason.REANALYZE if a.force else AIJobReason.MANUAL, settings,
                                              force=a.force)
                    if res.skipped_reason == "not_ready":
                        s.rollback()
                        print(f"Stage 3B extraction {a.stage3b_extraction_id} not found, not current, or not usable "
                              "(needs SUCCESS / PARTIAL_SUCCESS on a current, usable Stage 3A extraction). "
                              "Nothing done.")
                        return 5
                    if res.skipped_reason == "already_analyzed":
                        s.rollback()
                        rid = current_analysis_id(s, a.stage3b_extraction_id, effective_provider(settings),
                                                  effective_model(settings))
                        print(f"Stage 3B extraction {a.stage3b_extraction_id} is already analyzed with "
                              f"{effective_provider(settings)} / {effective_model(settings)} (analysis_id {rid}). "
                              "Use --force to re-analyze.")
                        return 0
                    if res.skipped_reason == "already_running":
                        print("An AI analysis of this Stage 3B run is RUNNING elsewhere.")
                        return 3
                    s.commit()
                    job_id = res.job_id
                    print(f"{'Queued' if res.created else 'Reusing'} AI-analysis job {job_id} "
                          f"for Stage 3B extraction {a.stage3b_extraction_id} (force={a.force})")
            batch = worker.run_batch(max_jobs=1, job_id=job_id)
            if not batch.jobs and batch.skipped_reason is None:
                with factory() as s:
                    j = s.get(AIAnalysisJob, job_id)
                print(f"Job {job_id} not eligible now (status={getattr(j, 'status', 'missing')}).")
                return 0 if j else 5
            _print(batch, factory)
            return _exit(batch)
        if a.once or a.limit:
            batch = worker.run_batch(max_jobs=a.limit or 1)
            _print(batch, factory)
            return _exit(batch)
        print(f"AI-analysis worker loop (poll {settings.ai_analysis_job_poll_seconds}s). Ctrl+C to stop.")
        while not worker.stop_requested:
            batch = worker.run_batch()
            if batch.jobs:
                _print(batch, factory)
            if not worker.pause(settings.ai_analysis_job_poll_seconds):
                break
        return 0
    except KeyboardInterrupt:
        print("\nAborted. An interrupted job is recovered automatically on the next start.")
        return 130
    finally:
        engine.dispose()


if __name__ == "__main__":
    sys.exit(main())
