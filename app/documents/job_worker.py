"""Stage 2B: persistent DocumentJob worker around the proven Stage 2A service.

Lifecycle of one job::

    PENDING / RETRY (due) --claim--> RUNNING --Stage 2A--> SUCCESS
                                                       +-> PARTIAL_SUCCESS
                                                       +-> RETRY (next_retry_at persisted)
                                                       +-> FAILED
                                                       +-> BLOCKED
                                                       +-> SKIPPED (no source URL / superseded)

Design rules
------------
* Concurrency 1. A process-wide lock (thread lock + cross-process file lock,
  same mechanism as Stage 1's CollectionLock) guarantees one worker batch at a
  time on this host: scheduler vs. API vs. CLI can never overlap.
* Transactions are short. The claim is committed *before* any network work;
  Stage 2A runs in its own session; the final state is written in a fresh
  session with a conditional UPDATE (``status='RUNNING' AND locked_by=me``) so a
  recovered/stolen job is never clobbered. No DB write lock is held by the
  worker across GeM HTTP requests.
* Claiming is an atomic conditional UPDATE (``WHERE status IN queued``), which
  is safe on SQLite and portable to PostgreSQL (where ``FOR UPDATE SKIP LOCKED``
  can later replace the candidate scan).
* Job-level retries are persisted in ``next_retry_at`` (exponential backoff);
  the worker never sleeps for a retry period. Stage 2A's per-request retries
  are untouched and separate.
* BLOCKED (CAPTCHA / 401 / 403) is terminal for the job, stops the current batch
  and pauses ALL processing for DOCUMENT_BLOCK_COOLDOWN_MINUTES. No bypass.
"""

from __future__ import annotations

import json
import logging
import os
import socket
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import case, func, or_, select, update
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.core.logging import log_event
from app.database.models import DocumentJob, Tender
from app.documents.documents_service import (
    OUTCOME_BLOCKED,
    OUTCOME_NO_DOCUMENTS,
    OUTCOME_PERMANENT,
    OUTCOME_TRANSIENT,
    OUTCOME_WITH_DOCUMENTS,
    DocumentsService,
)
from app.documents.job_queue import enqueue_due_refreshes
from app.schemas.documents import QUEUED_JOB_STATUSES, DocumentJobReason, DocumentJobStatus
from app.services.run_lock import CollectionAlreadyRunning, CollectionLock
from app.utils.dates import utcnow

logger = logging.getLogger("app.documents.job_worker")

S = DocumentJobStatus

# Lower number = claimed first. Fresh tenders and closing tenders beat backlog.
_PRIORITY = case(
    (DocumentJob.reason.in_([DocumentJobReason.FINAL_REFRESH.value, DocumentJobReason.MANUAL.value]), 0),
    (DocumentJob.reason.in_([DocumentJobReason.NEW_TENDER.value, DocumentJobReason.RETRY.value]), 1),
    (DocumentJob.reason == DocumentJobReason.PERIODIC_REFRESH.value, 3),
    else_=2,  # BACKFILL and legacy (reason NULL, created before Stage 2B)
)

SKIP_BUSY = "worker_busy"
SKIP_COOLDOWN = "blocked_cooldown"
SKIP_STOPPED = "stop_requested"


@dataclass
class JobDecision:
    status: str
    error_code: str | None = None
    error_message: str | None = None
    next_retry_at: datetime | None = None


@dataclass
class JobRunResult:
    job_id: int
    tender_id: int
    bid_number: str | None
    reason: str | None
    attempt: int
    status: str
    outcome: str | None
    summary: dict | None = None
    next_retry_at: datetime | None = None
    error_code: str | None = None
    error_message: str | None = None
    lease_lost: bool = False


@dataclass
class BatchResult:
    started_at: datetime
    finished_at: datetime | None = None
    recovered_stale: int = 0
    skipped_reason: str | None = None
    jobs: list[JobRunResult] = field(default_factory=list)

    @property
    def processed(self) -> int:
        return len(self.jobs)


@dataclass
class _Claimed:
    job_id: int
    tender_id: int
    bid_number: str | None
    source_url: str | None
    reason: str | None
    attempt: int


class DocumentWorkerBusy(RuntimeError):
    pass


def compute_job_backoff(attempt: int, settings: Settings) -> timedelta:
    """attempt 1 -> base, attempt 2 -> 2*base, ... capped."""
    minutes = settings.document_retry_backoff_minutes * (2 ** max(0, attempt - 1))
    return timedelta(minutes=min(minutes, settings.document_retry_max_backoff_minutes))


def decide(summary: dict | None, attempt: int, settings: Settings, now: datetime,
           exc: BaseException | None = None) -> JobDecision:
    """Map a Stage 2A result (or an unexpected exception) onto a job state."""
    max_attempts = settings.document_max_attempts

    def retry_or_fail(code: str, message: str) -> JobDecision:
        if attempt < max_attempts:
            return JobDecision(S.RETRY.value, code, message, now + compute_job_backoff(attempt, settings))
        return JobDecision(S.FAILED.value, "RETRIES_EXHAUSTED",
                           f"{code} after {attempt}/{max_attempts} attempt(s): {message}"[:4000])

    if exc is not None:
        return retry_or_fail("WORKER_EXCEPTION", f"{type(exc).__name__}: {exc}"[:4000])
    if not summary:
        return JobDecision(S.FAILED.value, "NO_RESULT", "Stage 2A returned no result")

    outcome = summary.get("outcome")
    error = summary.get("error") or "; ".join(summary.get("errors") or []) or None
    if outcome in (OUTCOME_WITH_DOCUMENTS, OUTCOME_NO_DOCUMENTS):
        if summary.get("status") == "PARTIAL_SUCCESS" or (summary.get("failed") or 0) > 0:
            code = "PARTIAL_TRANSIENT" if summary.get("retryable") else "PARTIAL_PERMANENT"
            return JobDecision(S.PARTIAL_SUCCESS.value, code, error)
        return JobDecision(S.SUCCESS.value)
    if outcome == OUTCOME_BLOCKED:
        return JobDecision(S.BLOCKED.value, OUTCOME_BLOCKED, error)
    if outcome == OUTCOME_TRANSIENT:
        return retry_or_fail(OUTCOME_TRANSIENT, error or "transient failure")
    if outcome == OUTCOME_PERMANENT:
        return JobDecision(S.FAILED.value, OUTCOME_PERMANENT, error)
    return JobDecision(S.FAILED.value, "UNKNOWN_OUTCOME", f"Unrecognised Stage 2A outcome: {outcome!r}")


def _counters(summary: dict | None) -> str | None:
    if not summary:
        return None
    keys = ("status", "outcome", "retryable", "discovered", "downloaded", "unchanged", "failed")
    return json.dumps({k: summary.get(k) for k in keys}, sort_keys=True)


class DocumentJobWorker:
    """One instance per process. Thread-safe entry points: run_batch / recover / refresh."""

    def __init__(
        self,
        settings: Settings,
        session_factory: sessionmaker[Session],
        service_factory: Callable[[], DocumentsService] | None = None,
        *,
        lock: CollectionLock | None = None,
        sleep: Callable[[float], None] | None = None,
        clock: Callable[[], datetime] = utcnow,
        worker_id: str | None = None,
    ) -> None:
        self.settings = settings
        self.session_factory = session_factory
        self.service_factory = service_factory or (lambda: DocumentsService(settings))
        self.lock = lock or CollectionLock(settings.resolved_document_worker_lock_file)
        self.clock = clock
        self.host = socket.gethostname()
        self.worker_id = worker_id or f"{self.host}:{os.getpid()}:{uuid.uuid4().hex[:8]}"
        self._sleep = sleep
        self._stop = threading.Event()
        self._state_lock = threading.Lock()
        # In-process observability (health/stats)
        self.last_run_started_at: datetime | None = None
        self.last_run_finished_at: datetime | None = None
        self.last_run_processed: int = 0
        self.last_run_skipped_reason: str | None = None
        self.last_refresh_check_at: datetime | None = None
        self.last_refresh_queued: int = 0
        self.current_job_id: int | None = None
        if settings.document_worker_concurrency > 1:
            log_event(logger, logging.WARNING, "document_worker_concurrency_clamped",
                      requested=settings.document_worker_concurrency, used=1,
                      reason="SQLite MVP processes one job at a time")

    # ------------------------------------------------------------------
    # control
    # ------------------------------------------------------------------
    def request_stop(self) -> None:
        self._stop.set()

    def reset_stop(self) -> None:
        self._stop.clear()

    @property
    def stop_requested(self) -> bool:
        return self._stop.is_set()

    def is_busy(self) -> bool:
        return self.lock.is_locked()

    def pause(self, seconds: float) -> bool:
        """Pause between jobs. Returns False if a stop was requested."""
        if seconds <= 0:
            return not self._stop.is_set()
        if self._sleep is not None:
            self._sleep(seconds)
            return not self._stop.is_set()
        return not self._stop.wait(seconds)

    # ------------------------------------------------------------------
    # public entry points
    # ------------------------------------------------------------------
    def run_batch(self, max_jobs: int | None = None, *, job_id: int | None = None,
                  raise_if_busy: bool = False) -> BatchResult:
        """Recover stale jobs, then process up to ``max_jobs`` due jobs (or one specific job)."""
        max_jobs = max_jobs if max_jobs is not None else self.settings.document_worker_max_jobs_per_run
        batch = BatchResult(started_at=self.clock())
        try:
            with self.lock.acquire():
                self._mark_run_start(batch)
                try:
                    self._run_locked(batch, max(1, max_jobs), job_id)
                finally:
                    batch.finished_at = self.clock()
                    self._mark_run_end(batch)
        except CollectionAlreadyRunning as exc:
            if raise_if_busy:
                raise DocumentWorkerBusy("Another document worker run is in progress.") from exc
            batch.skipped_reason = SKIP_BUSY
            batch.finished_at = self.clock()
            log_event(logger, logging.INFO, "document_worker_skipped", reason=SKIP_BUSY)
        return batch

    def recover_stale_jobs(self) -> int:
        """Return orphaned RUNNING jobs to an eligible state. No-op if a worker is active."""
        try:
            with self.lock.acquire():
                return self._recover_stale_locked()
        except CollectionAlreadyRunning:
            return 0

    def queue_due_refreshes(self) -> int:
        """Scheduler tick: enqueue PERIODIC_REFRESH jobs for due ONGOING tenders."""
        now = self.clock()
        with self.session_factory() as s:
            from app.database.session import reserve_sqlite_writer
            reserve_sqlite_writer(s)
            created = enqueue_due_refreshes(s, self.settings, now=now)
            s.commit()
        with self._state_lock:
            self.last_refresh_check_at = now
            self.last_refresh_queued = created
        return created

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------
    def _mark_run_start(self, batch: BatchResult) -> None:
        with self._state_lock:
            self.last_run_started_at = batch.started_at

    def _mark_run_end(self, batch: BatchResult) -> None:
        with self._state_lock:
            self.last_run_finished_at = batch.finished_at
            self.last_run_processed = batch.processed
            self.last_run_skipped_reason = batch.skipped_reason
            self.current_job_id = None

    def block_cooldown_until(self, session: Session | None = None) -> datetime | None:
        """When the post-BLOCKED pause ends (None = not in cooldown)."""
        minutes = self.settings.document_block_cooldown_minutes
        if minutes <= 0:
            return None

        def _q(s: Session):
            return s.scalar(select(func.max(DocumentJob.finished_at)).where(
                DocumentJob.status == S.BLOCKED.value))

        last_blocked = _q(session) if session is not None else self._with_session(_q)
        if last_blocked is None:
            return None
        until = last_blocked + timedelta(minutes=minutes)
        return until if until > self.clock() else None

    def _with_session(self, fn):
        with self.session_factory() as s:
            return fn(s)

    def _run_locked(self, batch: BatchResult, max_jobs: int, job_id: int | None) -> None:
        batch.recovered_stale = self._recover_stale_locked()
        until = self.block_cooldown_until()
        if until is not None:
            batch.skipped_reason = SKIP_COOLDOWN
            log_event(logger, logging.WARNING, "document_worker_paused", reason=SKIP_COOLDOWN,
                      until=until.isoformat(timespec="seconds") + "Z")
            return
        for i in range(max_jobs):
            if self._stop.is_set():
                batch.skipped_reason = batch.skipped_reason or SKIP_STOPPED
                return
            if i > 0 and not self.pause(self.settings.document_inter_job_delay_seconds):
                batch.skipped_reason = SKIP_STOPPED
                return
            claimed = self._claim(job_id)
            if claimed is None:
                return
            result = self._process(claimed)
            batch.jobs.append(result)
            if result.status == S.BLOCKED.value:
                log_event(logger, logging.WARNING, "document_worker_paused", reason="job_blocked",
                          job_id=result.job_id, cooldown_minutes=self.settings.document_block_cooldown_minutes)
                return
            if job_id is not None:
                return

    # -- stale recovery ---------------------------------------------------
    def _recover_stale_locked(self) -> int:
        """Caller holds the worker lock, so no job on THIS host is genuinely running.

        A RUNNING job is orphaned when it was claimed on this host (its worker is
        provably gone) or when it is older than DOCUMENT_STALE_RUNNING_MINUTES
        (covers other hosts / legacy rows without locked_by).
        """
        now = self.clock()
        cutoff = now - timedelta(minutes=self.settings.document_stale_running_minutes)
        recovered = 0
        with self.session_factory() as s:
            rows = s.scalars(select(DocumentJob).where(DocumentJob.status == S.RUNNING.value)).all()
            for job in rows:
                same_host = bool(job.locked_by) and job.locked_by.split(":", 1)[0] == self.host
                too_old = job.started_at is None or job.started_at < cutoff
                if not (same_host or too_old):
                    continue
                attempts = job.attempt_count or 0
                msg = (f"Recovered orphaned RUNNING job (claimed by {job.locked_by or 'unknown'} "
                       f"at {job.started_at}); worker stopped before finishing")
                if attempts >= self.settings.document_max_attempts:
                    values = dict(status=S.FAILED.value, error_code="STALE_RUNNING",
                                  error_message=msg + f"; attempts exhausted ({attempts})",
                                  finished_at=now, next_retry_at=None)
                elif self._other_queued_job(s, job.tender_id, job.id):
                    values = dict(status=S.SKIPPED.value, error_code="SUPERSEDED",
                                  error_message=msg + "; another queued job covers this tender",
                                  finished_at=now, next_retry_at=None)
                else:
                    values = dict(status=S.RETRY.value, error_code="STALE_RUNNING", error_message=msg,
                                  finished_at=None, next_retry_at=now)
                res = s.execute(
                    update(DocumentJob)
                    .where(DocumentJob.id == job.id, DocumentJob.status == S.RUNNING.value,
                           (DocumentJob.locked_by == job.locked_by) if job.locked_by is not None
                           else DocumentJob.locked_by.is_(None))
                    .values(locked_by=None, updated_at=now, **values)
                    .execution_options(synchronize_session=False)
                )
                if res.rowcount:
                    recovered += 1
                    log_event(logger, logging.WARNING, "document_job_recovered", job_id=job.id,
                              tender_id=job.tender_id, new_status=values["status"],
                              same_host=same_host, attempts=attempts)
            s.commit()
        return recovered

    @staticmethod
    def _other_queued_job(s: Session, tender_id: int, job_id: int) -> bool:
        return s.scalar(select(DocumentJob.id).where(
            DocumentJob.tender_id == tender_id, DocumentJob.id != job_id,
            DocumentJob.status.in_(QUEUED_JOB_STATUSES)).limit(1)) is not None

    # -- claim -----------------------------------------------------------
    def _claim(self, job_id: int | None = None) -> _Claimed | None:
        now = self.clock()
        running_tenders = select(DocumentJob.tender_id).where(DocumentJob.status == S.RUNNING.value)
        # Prefer ordinary BID tenders over RA records within the existing
        # job-reason priority. GeM may expose RA document URLs before their
        # PDF body is populated, so RA work must not starve actionable bids.
        bid_type_priority = case(
            (Tender.bid_type == "BID", 0),
            else_=1,
        )

        stmt = (
            select(DocumentJob.id)
            .join(Tender, Tender.id == DocumentJob.tender_id)
            .where(
                DocumentJob.status.in_(QUEUED_JOB_STATUSES),
                or_(DocumentJob.next_retry_at.is_(None), DocumentJob.next_retry_at <= now),
                DocumentJob.tender_id.not_in(running_tenders),
            )
            .order_by(
                _PRIORITY,
                bid_type_priority,
                func.coalesce(DocumentJob.next_retry_at, DocumentJob.created_at),
                DocumentJob.id,
            )
            .limit(5)
        )
        if job_id is not None:
            stmt = stmt.where(DocumentJob.id == job_id)
        with self.session_factory() as s:
            from app.database.session import reserve_sqlite_writer
            reserve_sqlite_writer(s)
            for candidate in s.scalars(stmt).all():
                res = s.execute(
                    update(DocumentJob)
                    .where(DocumentJob.id == candidate, DocumentJob.status.in_(QUEUED_JOB_STATUSES))
                    .values(status=S.RUNNING.value, locked_by=self.worker_id, started_at=now,
                            finished_at=None, next_retry_at=None, updated_at=now,
                            attempt_count=DocumentJob.attempt_count + 1)
                    .execution_options(synchronize_session=False)
                )
                if res.rowcount != 1:
                    s.rollback()
                    continue  # someone else took it
                s.commit()  # claim is durable BEFORE any network work
                row = s.execute(
                    select(DocumentJob.attempt_count, DocumentJob.reason, DocumentJob.tender_id,
                           Tender.bid_number, Tender.source_url)
                    .join(Tender, Tender.id == DocumentJob.tender_id)
                    .where(DocumentJob.id == candidate)
                ).one()
                s.commit()
                with self._state_lock:
                    self.current_job_id = candidate
                log_event(logger, logging.INFO, "document_job_claimed", job_id=candidate,
                          tender_id=row.tender_id, bid=row.bid_number, reason=row.reason,
                          attempt=row.attempt_count, worker=self.worker_id)
                return _Claimed(candidate, row.tender_id, row.bid_number, row.source_url,
                                row.reason, row.attempt_count)
        return None

    # -- process -----------------------------------------------------------
    def _process(self, c: _Claimed) -> JobRunResult:
        if not c.source_url:
            decision = JobDecision(S.SKIPPED.value, "NO_SOURCE_URL",
                                   "Tender has no source_url; nothing to fetch")
            return self._finalize(c, decision, outcome=None, summary=None)

        summary: dict | None = None
        exc: BaseException | None = None
        try:
            service = self.service_factory()
            with self.session_factory() as s:
                summary = service.discover_and_download_tender_documents(s, c.tender_id)
        except Exception as e:  # Stage 2A normally never raises; be defensive
            logger.exception("document_job_exception job_id=%s", c.job_id)
            exc = e
        decision = decide(summary, c.attempt, self.settings, self.clock(), exc)
        return self._finalize(c, decision, outcome=(summary or {}).get("outcome"), summary=summary)

    def _finalize(self, c: _Claimed, d: JobDecision, *, outcome: str | None, summary: dict | None) -> JobRunResult:
        now = self.clock()
        with self.session_factory() as s:
            if d.status == S.RETRY.value and self._other_queued_job(s, c.tender_id, c.job_id):
                # A newer queued job (e.g. FINAL_REFRESH queued while we ran) will
                # do the same work; keep exactly one queued job per tender.
                d = JobDecision(S.SKIPPED.value, "SUPERSEDED",
                                f"Retry superseded by another queued job; last error: {d.error_message}")
            terminal = d.status != S.RETRY.value
            res = s.execute(
                update(DocumentJob)
                .where(DocumentJob.id == c.job_id, DocumentJob.status == S.RUNNING.value,
                       DocumentJob.locked_by == self.worker_id)
                .values(status=d.status, error_code=d.error_code,
                        error_message=(d.error_message[:4000] if d.error_message else None),
                        next_retry_at=d.next_retry_at, finished_at=now if terminal else None,
                        locked_by=None, updated_at=now, outcome=outcome,
                        result_summary=_counters(summary))
                .execution_options(synchronize_session=False)
            )
            lease_lost = res.rowcount != 1
            s.commit()
        with self._state_lock:
            self.current_job_id = None
        result = JobRunResult(
            job_id=c.job_id, tender_id=c.tender_id, bid_number=c.bid_number, reason=c.reason,
            attempt=c.attempt, status=d.status, outcome=outcome, summary=summary,
            next_retry_at=d.next_retry_at, error_code=d.error_code, error_message=d.error_message,
            lease_lost=lease_lost,
        )
        level = logging.INFO if d.status in (S.SUCCESS.value, S.PARTIAL_SUCCESS.value, S.SKIPPED.value) else logging.WARNING
        log_event(logger, level, "document_job_finished", job_id=c.job_id, tender_id=c.tender_id,
                  bid=c.bid_number, status=d.status, outcome=outcome, attempt=c.attempt,
                  discovered=(summary or {}).get("discovered"), downloaded=(summary or {}).get("downloaded"),
                  unchanged=(summary or {}).get("unchanged"), failed=(summary or {}).get("failed"),
                  next_retry_at=(d.next_retry_at.isoformat(timespec="seconds") + "Z") if d.next_retry_at else None,
                  error_code=d.error_code)
        if lease_lost:
            log_event(logger, logging.ERROR, "document_job_lease_lost", job_id=c.job_id,
                      detail="job was no longer RUNNING/owned by this worker; final state not written")
        return result

