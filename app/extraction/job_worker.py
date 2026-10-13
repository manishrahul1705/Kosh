"""Stage 3A extraction worker (same safety design as the Stage 2B document worker).

    PENDING / due RETRY --claim (commit)--> RUNNING --parse (no DB txn)--> one transaction:
        persist extraction + pages/tables/sections  AND  finish the job  -> commit

Job result mapping:
    extraction SUCCESS          -> SUCCESS
    extraction PARTIAL_SUCCESS  -> PARTIAL_SUCCESS
    extraction OCR_REQUIRED     -> OCR_REQUIRED   (terminal, not a failure; re-extract after OCR is enabled)
    extraction UNSUPPORTED      -> SKIPPED (UNSUPPORTED_FILE_TYPE)
    extraction FAILED           -> FAILED  (permanent: PDF_CORRUPT, PASSWORD_PROTECTED, FILE_HASH_MISMATCH, ...)
    already extracted (no force)-> SKIPPED (ALREADY_EXTRACTED)
    version missing / not VALID -> SKIPPED
    FILE_MISSING / FILE_UNREADABLE / DATABASE_ERROR / unexpected exception
                                -> RETRY with backoff, FAILED after EXTRACTION_MAX_ATTEMPTS

Concurrency 1 per host: a thread lock + file lock (data/extraction_worker.lock),
separate from the Stage 2 document worker (Stage 3A never contacts GeM, so the
two may run side by side; each holds only short write transactions).
"""

from __future__ import annotations

import logging
import os
import socket
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import case, func, or_, select, update
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.core.logging import log_event
from app.database.models import ExtractionJob
from app.extraction.constants import (
    QUEUED_EXTRACTION_STATUSES,
    ErrorCode,
    ExtractionJobReason,
    ExtractionJobStatus,
    ExtractionStatus,
)
from app.extraction.service import ExtractionService, Prepared, current_extraction_id
from app.fields.job_queue import queue_after_stage3a_commit
from app.services.run_lock import CollectionAlreadyRunning, CollectionLock
from app.utils.dates import utcnow

logger = logging.getLogger("app.extraction.job_worker")
J = ExtractionJobStatus
SKIP_BUSY = "worker_busy"
SKIP_STOPPED = "stop_requested"

_PRIORITY = case(
    (ExtractionJob.reason.in_([ExtractionJobReason.MANUAL.value, ExtractionJobReason.REEXTRACT.value]), 0),
    (ExtractionJob.reason == ExtractionJobReason.NEW_VERSION.value, 1),
    else_=2,
)

_EXTRACTION_TO_JOB = {
    ExtractionStatus.SUCCESS.value: J.SUCCESS.value,
    ExtractionStatus.PARTIAL_SUCCESS.value: J.PARTIAL_SUCCESS.value,
    ExtractionStatus.OCR_REQUIRED.value: J.OCR_REQUIRED.value,
    ExtractionStatus.UNSUPPORTED.value: J.SKIPPED.value,
    ExtractionStatus.FAILED.value: J.FAILED.value,
}


@dataclass
class JobDecision:
    status: str
    error_code: str | None = None
    error_message: str | None = None
    next_retry_at: datetime | None = None


@dataclass
class ExtractionJobResult:
    job_id: int
    document_version_id: int
    attempt: int
    status: str
    outcome: str | None
    extraction_id: int | None = None
    error_code: str | None = None
    error_message: str | None = None
    next_retry_at: datetime | None = None
    lease_lost: bool = False


@dataclass
class ExtractionBatch:
    started_at: datetime
    finished_at: datetime | None = None
    recovered_stale: int = 0
    skipped_reason: str | None = None
    jobs: list[ExtractionJobResult] = field(default_factory=list)

    @property
    def processed(self) -> int:
        return len(self.jobs)


@dataclass
class _Claimed:
    job_id: int
    document_version_id: int
    force: bool
    attempt: int
    reason: str | None


def compute_backoff(attempt: int, settings: Settings) -> timedelta:
    minutes = settings.extraction_retry_backoff_minutes * (2 ** max(0, attempt - 1))
    return timedelta(minutes=min(minutes, settings.extraction_retry_max_backoff_minutes))


def retry_or_fail(code: str, message: str, attempt: int, settings: Settings, now: datetime) -> JobDecision:
    if attempt < settings.extraction_max_attempts:
        return JobDecision(J.RETRY.value, code, message, now + compute_backoff(attempt, settings))
    return JobDecision(J.FAILED.value, "RETRIES_EXHAUSTED",
                       f"{code} after {attempt}/{settings.extraction_max_attempts} attempt(s): {message}"[:4000])


class ExtractionJobWorker:
    def __init__(self, settings: Settings, session_factory: sessionmaker[Session],
                 service: ExtractionService | None = None, *, lock: CollectionLock | None = None,
                 clock: Callable[[], datetime] = utcnow, sleep: Callable[[float], None] | None = None,
                 worker_id: str | None = None) -> None:
        self.settings = settings
        self.session_factory = session_factory
        self.clock = clock
        self._service = service
        self.lock = lock or CollectionLock(settings.resolved_extraction_worker_lock_file)
        self.host = socket.gethostname()
        self.worker_id = worker_id or f"{self.host}:{os.getpid()}:{uuid.uuid4().hex[:8]}"
        self._sleep = sleep
        self._stop = threading.Event()
        self._state = threading.Lock()
        self.current_job_id: int | None = None
        self.last_run_started_at: datetime | None = None
        self.last_run_finished_at: datetime | None = None
        self.last_run_processed = 0
        self.last_outcome: dict | None = None

    @property
    def service(self) -> ExtractionService:
        if self._service is None:  # built lazily: OCR provider probing only when work happens
            self._service = ExtractionService(self.settings, self.session_factory, clock=self.clock)
        return self._service

    # -- control ---------------------------------------------------------
    def request_stop(self) -> None:
        self._stop.set()

    @property
    def stop_requested(self) -> bool:
        return self._stop.is_set()

    def is_busy(self) -> bool:
        return self.lock.is_locked()

    def pause(self, seconds: float) -> bool:
        if seconds <= 0:
            return not self._stop.is_set()
        if self._sleep is not None:
            self._sleep(seconds)
            return not self._stop.is_set()
        return not self._stop.wait(seconds)

    # -- entry points ----------------------------------------------------
    def run_batch(self, max_jobs: int | None = None, *, job_id: int | None = None) -> ExtractionBatch:
        max_jobs = max(1, max_jobs or self.settings.extraction_worker_max_jobs_per_run)
        batch = ExtractionBatch(started_at=self.clock())
        try:
            with self.lock.acquire():
                with self._state:
                    self.last_run_started_at = batch.started_at
                try:
                    batch.recovered_stale = self._recover_locked()
                    for _ in range(max_jobs):
                        if self._stop.is_set():
                            batch.skipped_reason = SKIP_STOPPED
                            break
                        claimed = self._claim(job_id)
                        if claimed is None:
                            break
                        batch.jobs.append(self._process(claimed))
                        if job_id is not None:
                            break
                finally:
                    batch.finished_at = self.clock()
                    with self._state:
                        self.last_run_finished_at = batch.finished_at
                        self.last_run_processed = batch.processed
                        self.current_job_id = None
        except CollectionAlreadyRunning:
            batch.skipped_reason = SKIP_BUSY
            batch.finished_at = self.clock()
        return batch

    def recover_stale_jobs(self) -> int:
        try:
            with self.lock.acquire():
                return self._recover_locked()
        except CollectionAlreadyRunning:
            return 0

    # -- internals -------------------------------------------------------
    def _recover_locked(self) -> int:
        """Holding the lock => no extraction is running on THIS host. Orphans: claimed on
        this host, or older than EXTRACTION_STALE_RUNNING_MINUTES (other hosts / no owner)."""
        now = self.clock()
        cutoff = now - timedelta(minutes=self.settings.extraction_stale_running_minutes)
        n = 0
        with self.session_factory() as s:
            for job in s.scalars(select(ExtractionJob).where(ExtractionJob.status == J.RUNNING.value)).all():
                same_host = bool(job.locked_by) and job.locked_by.split(":", 1)[0] == self.host
                if not (same_host or job.started_at is None or job.started_at < cutoff):
                    continue
                other_queued = s.scalar(select(ExtractionJob.id).where(
                    ExtractionJob.document_version_id == job.document_version_id, ExtractionJob.id != job.id,
                    ExtractionJob.status.in_(QUEUED_EXTRACTION_STATUSES)).limit(1)) is not None
                if job.attempt_count >= self.settings.extraction_max_attempts:
                    values = dict(status=J.FAILED.value, error_code="STALE_RUNNING", finished_at=now,
                                  error_message="Worker stopped during extraction; attempts exhausted")
                elif other_queued:
                    values = dict(status=J.SKIPPED.value, error_code="SUPERSEDED", finished_at=now,
                                  error_message="Worker stopped during extraction; another job is queued")
                else:
                    values = dict(status=J.RETRY.value, error_code="STALE_RUNNING", next_retry_at=now,
                                  error_message="Worker stopped during extraction; retrying")
                res = s.execute(update(ExtractionJob).where(
                    ExtractionJob.id == job.id, ExtractionJob.status == J.RUNNING.value)
                    .values(locked_by=None, updated_at=now, **values).execution_options(synchronize_session=False))
                if res.rowcount:
                    n += 1
                    log_event(logger, logging.WARNING, "extraction_job_recovered", job_id=job.id,
                              new_status=values["status"])
            s.commit()
        return n

    def _claim(self, job_id: int | None) -> _Claimed | None:
        now = self.clock()
        running_versions = select(ExtractionJob.document_version_id).where(ExtractionJob.status == J.RUNNING.value)
        stmt = (select(ExtractionJob.id)
                .where(ExtractionJob.status.in_(QUEUED_EXTRACTION_STATUSES),
                       or_(ExtractionJob.next_retry_at.is_(None), ExtractionJob.next_retry_at <= now),
                       ExtractionJob.document_version_id.not_in(running_versions))
                .order_by(_PRIORITY, func.coalesce(ExtractionJob.next_retry_at, ExtractionJob.created_at),
                          ExtractionJob.id)
                .limit(5))
        if job_id is not None:
            stmt = stmt.where(ExtractionJob.id == job_id)
        with self.session_factory() as s:
            from app.database.session import reserve_sqlite_writer
            reserve_sqlite_writer(s)
            for cand in s.scalars(stmt).all():
                res = s.execute(update(ExtractionJob)
                                .where(ExtractionJob.id == cand, ExtractionJob.status.in_(QUEUED_EXTRACTION_STATUSES))
                                .values(status=J.RUNNING.value, locked_by=self.worker_id, started_at=now,
                                        finished_at=None, next_retry_at=None, updated_at=now,
                                        attempt_count=ExtractionJob.attempt_count + 1)
                                .execution_options(synchronize_session=False))
                if res.rowcount != 1:
                    s.rollback()
                    continue
                s.commit()  # claim durable before parsing
                job = s.get(ExtractionJob, cand)
                claimed = _Claimed(job.id, job.document_version_id, bool(job.force), job.attempt_count, job.reason)
                s.commit()
                with self._state:
                    self.current_job_id = cand
                log_event(logger, logging.INFO, "extraction_job_claimed", job_id=cand,
                          document_version_id=claimed.document_version_id, attempt=claimed.attempt,
                          force=claimed.force, worker=self.worker_id)
                return claimed
        return None

    def _process(self, c: _Claimed) -> ExtractionJobResult:
        now_fn = self.clock
        try:
            prepared = self.service.prepare(c.document_version_id, force=c.force)
        except Exception as exc:  # defensive: the service classifies known failures itself
            logger.exception("extraction_job_exception job_id=%s", c.job_id)
            d = retry_or_fail("WORKER_EXCEPTION", f"{type(exc).__name__}: {exc}", c.attempt, self.settings, now_fn())
            return self._finish(c, d, outcome="ERROR")

        if prepared.already_extraction_id is not None:
            return self._finish(c, JobDecision(J.SKIPPED.value, ErrorCode.ALREADY_EXTRACTED.value,
                                               "Version already extracted (use force/re-extract)"),
                                outcome="ALREADY_EXTRACTED", extraction_id=prepared.already_extraction_id)
        if prepared.error is not None:
            e = prepared.error
            if e.retryable:
                d = retry_or_fail(e.code, e.message, c.attempt, self.settings, now_fn())
            else:  # VERSION_NOT_FOUND / VERSION_NOT_ELIGIBLE
                d = JobDecision(J.SKIPPED.value, e.code, e.message)
            return self._finish(c, d, outcome="ERROR")
        return self._finish(c, None, outcome=prepared.record.status, prepared=prepared)

    def _finish(self, c: _Claimed, d: JobDecision | None, *, outcome: str | None,
                extraction_id: int | None = None, prepared: Prepared | None = None) -> ExtractionJobResult:
        now = self.clock()
        lease_lost = False
        with self.session_factory() as s:
            try:
                if prepared is not None:
                    r = prepared.record
                    d = JobDecision(_EXTRACTION_TO_JOB.get(r.status, J.FAILED.value), r.error_code, r.error_message)
                if d.status == J.RETRY.value and s.scalar(select(ExtractionJob.id).where(
                        ExtractionJob.document_version_id == c.document_version_id, ExtractionJob.id != c.job_id,
                        ExtractionJob.status.in_(QUEUED_EXTRACTION_STATUSES)).limit(1)) is not None:
                    d = JobDecision(J.SKIPPED.value, "SUPERSEDED",
                                    f"Retry superseded by another queued job; last error: {d.error_message}")
                lease = s.execute(update(ExtractionJob)
                                  .where(ExtractionJob.id == c.job_id, ExtractionJob.status == J.RUNNING.value,
                                         ExtractionJob.locked_by == self.worker_id)
                                  .values(updated_at=now).execution_options(synchronize_session=False))
                if lease.rowcount != 1:
                    lease_lost = True
                    s.rollback()
                else:
                    if prepared is not None:
                        extraction_id = self.service.persist(s, prepared)
                    self._write_job(s, c, d, outcome, extraction_id, now)
                    s.commit()
                    if prepared is not None:
                        # Stage 3B: queue field extraction AFTER the Stage 3A commit, in its
                        # own transaction. Never raises; never undoes the Stage 3A result.
                        queue_after_stage3a_commit(s, extraction_id, self.settings)
            except IntegrityError:
                s.rollback()  # another current extraction appeared: keep it, do not duplicate
                extraction_id = current_extraction_id(s, c.document_version_id)
                d = JobDecision(J.SKIPPED.value, ErrorCode.ALREADY_EXTRACTED.value, "Concurrent extraction exists")
                outcome = "ALREADY_EXTRACTED"
                self._write_job(s, c, d, outcome, extraction_id, now)
                s.commit()
            except OperationalError as exc:
                s.rollback()
                d = retry_or_fail(ErrorCode.DATABASE_ERROR.value, str(exc)[:500], c.attempt, self.settings, now)
                outcome = "ERROR"
                extraction_id = None
                self._write_job(s, c, d, outcome, None, now)
                s.commit()
        result = ExtractionJobResult(c.job_id, c.document_version_id, c.attempt, d.status, outcome, extraction_id,
                                     d.error_code, d.error_message, d.next_retry_at, lease_lost)
        with self._state:
            self.current_job_id = None
            self.last_outcome = {"job_id": c.job_id, "document_version_id": c.document_version_id,
                                 "status": d.status, "outcome": outcome, "extraction_id": extraction_id,
                                 "finished_at": now.isoformat(timespec="seconds") + "Z"}
        event = "extraction_job_retry" if d.status == J.RETRY.value else "extraction_job_finished"
        log_event(logger, logging.INFO if d.status in (J.SUCCESS.value, J.SKIPPED.value) else logging.WARNING,
                  event, job_id=c.job_id, document_version_id=c.document_version_id, status=d.status,
                  outcome=outcome, extraction_id=extraction_id, attempt=c.attempt, error_code=d.error_code,
                  lease_lost=lease_lost)
        return result

    def _write_job(self, s: Session, c: _Claimed, d: JobDecision, outcome: str | None,
                   extraction_id: int | None, now: datetime) -> None:
        terminal = d.status != J.RETRY.value
        s.execute(update(ExtractionJob)
                  .where(ExtractionJob.id == c.job_id, ExtractionJob.locked_by == self.worker_id)
                  .values(status=d.status, error_code=d.error_code,
                          error_message=d.error_message[:4000] if d.error_message else None,
                          next_retry_at=d.next_retry_at, finished_at=now if terminal else None, locked_by=None,
                          outcome=(outcome or "")[:40] or None, extraction_id=extraction_id, updated_at=now)
                  .execution_options(synchronize_session=False))

