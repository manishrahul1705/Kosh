"""Stage 3B field-extraction worker (same safety design as Stage 2B / Stage 3A workers).

    PENDING / due RETRY --claim (commit)--> RUNNING --rules (no DB txn)--> ONE transaction:
        persist run + values + evidence  AND  finish the job -> commit

Job result mapping:
    run SUCCESS / PARTIAL_SUCCESS          -> SUCCESS / PARTIAL_SUCCESS
    already extracted (no force)           -> SKIPPED (ALREADY_EXTRACTED)
    Stage 3A missing / not usable / superseded -> SKIPPED (STAGE3A_* code; never faked as success)
    DATABASE_ERROR / unexpected exception  -> RETRY (backoff), FAILED after FIELD_EXTRACTION_MAX_ATTEMPTS
Concurrency 1 per host (thread lock + file lock data/field_extraction_worker.lock).
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

from app.ai.job_queue import queue_after_stage3b_commit
from app.core.config import Settings
from app.core.logging import log_event
from app.database.models import FieldExtractionJob
from app.fields.constants import QUEUED_FIELD_JOB_STATUSES, FieldErrorCode, FieldJobReason, FieldJobStatus
from app.fields.service import FieldExtractionService, PreparedFields, current_field_extraction_id
from app.services.run_lock import CollectionAlreadyRunning, CollectionLock
from app.utils.dates import utcnow

logger = logging.getLogger("app.fields.job_worker")
J = FieldJobStatus
SKIP_BUSY = "worker_busy"
SKIP_STOPPED = "stop_requested"

_PRIORITY = case(
    (FieldExtractionJob.reason.in_([FieldJobReason.MANUAL.value, FieldJobReason.REEXTRACT.value]), 0),
    (FieldExtractionJob.reason == FieldJobReason.STAGE3A_COMPLETED.value, 1),
    else_=2,
)


@dataclass
class Decision:
    status: str
    error_code: str | None = None
    error_message: str | None = None
    next_retry_at: datetime | None = None


@dataclass
class FieldJobResult:
    job_id: int
    stage3a_extraction_id: int
    attempt: int
    status: str
    outcome: str | None
    field_extraction_id: int | None = None
    error_code: str | None = None
    error_message: str | None = None
    next_retry_at: datetime | None = None
    lease_lost: bool = False


@dataclass
class FieldBatch:
    started_at: datetime
    finished_at: datetime | None = None
    recovered_stale: int = 0
    skipped_reason: str | None = None
    jobs: list[FieldJobResult] = field(default_factory=list)

    @property
    def processed(self) -> int:
        return len(self.jobs)


@dataclass
class _Claimed:
    job_id: int
    stage3a_extraction_id: int
    force: bool
    attempt: int


def retry_or_fail(code: str, message: str, attempt: int, settings: Settings, now: datetime) -> Decision:
    if attempt < settings.field_extraction_max_attempts:
        delay = timedelta(minutes=settings.field_extraction_retry_backoff_minutes * (2 ** max(0, attempt - 1)))
        return Decision(J.RETRY.value, code, message, now + delay)
    return Decision(J.FAILED.value, "RETRIES_EXHAUSTED",
                    f"{code} after {attempt}/{settings.field_extraction_max_attempts} attempt(s): {message}"[:4000])


class FieldExtractionJobWorker:
    def __init__(self, settings: Settings, session_factory: sessionmaker[Session],
                 service: FieldExtractionService | None = None, *, lock: CollectionLock | None = None,
                 clock: Callable[[], datetime] = utcnow, worker_id: str | None = None) -> None:
        self.settings = settings
        self.session_factory = session_factory
        self.clock = clock
        self.service = service or FieldExtractionService(settings, session_factory, clock=clock)
        self.lock = lock or CollectionLock(settings.resolved_field_extraction_worker_lock_file)
        self.host = socket.gethostname()
        self.worker_id = worker_id or f"{self.host}:{os.getpid()}:{uuid.uuid4().hex[:8]}"
        self._stop = threading.Event()
        self._state = threading.Lock()
        self.current_job_id: int | None = None
        self.last_run_started_at: datetime | None = None
        self.last_run_finished_at: datetime | None = None
        self.last_outcome: dict | None = None

    def request_stop(self) -> None:
        self._stop.set()

    @property
    def stop_requested(self) -> bool:
        return self._stop.is_set()

    def is_busy(self) -> bool:
        return self.lock.is_locked()

    def pause(self, seconds: float) -> bool:
        return not self._stop.wait(seconds) if seconds > 0 else not self._stop.is_set()

    # ------------------------------------------------------------------
    def run_batch(self, max_jobs: int | None = None, *, job_id: int | None = None) -> FieldBatch:
        max_jobs = max(1, max_jobs or self.settings.field_extraction_worker_max_jobs_per_run)
        batch = FieldBatch(started_at=self.clock())
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

    def _recover_locked(self) -> int:
        """Lock held => nothing runs on THIS host. Orphans: claimed here, or older than the stale limit."""
        now = self.clock()
        cutoff = now - timedelta(minutes=self.settings.field_extraction_stale_running_minutes)
        n = 0
        with self.session_factory() as s:
            for job in s.scalars(select(FieldExtractionJob).where(FieldExtractionJob.status == J.RUNNING.value)).all():
                same_host = bool(job.locked_by) and job.locked_by.split(":", 1)[0] == self.host
                if not (same_host or job.started_at is None or job.started_at < cutoff):
                    continue
                other = s.scalar(select(FieldExtractionJob.id).where(
                    FieldExtractionJob.stage3a_extraction_id == job.stage3a_extraction_id,
                    FieldExtractionJob.id != job.id,
                    FieldExtractionJob.status.in_(QUEUED_FIELD_JOB_STATUSES)).limit(1)) is not None
                if job.attempt_count >= self.settings.field_extraction_max_attempts:
                    values = dict(status=J.FAILED.value, error_code="STALE_RUNNING", finished_at=now,
                                  error_message="Worker stopped during field extraction; attempts exhausted")
                elif other:
                    values = dict(status=J.SKIPPED.value, error_code="SUPERSEDED", finished_at=now,
                                  error_message="Worker stopped; another job is queued")
                else:
                    values = dict(status=J.RETRY.value, error_code="STALE_RUNNING", next_retry_at=now,
                                  error_message="Worker stopped during field extraction; retrying")
                res = s.execute(update(FieldExtractionJob)
                                .where(FieldExtractionJob.id == job.id, FieldExtractionJob.status == J.RUNNING.value)
                                .values(locked_by=None, updated_at=now, **values)
                                .execution_options(synchronize_session=False))
                if res.rowcount:
                    n += 1
                    log_event(logger, logging.WARNING, "field_extraction_job_recovered", job_id=job.id,
                              new_status=values["status"])
            s.commit()
        return n

    def _claim(self, job_id: int | None) -> _Claimed | None:
        now = self.clock()
        running = select(FieldExtractionJob.stage3a_extraction_id).where(FieldExtractionJob.status == J.RUNNING.value)
        stmt = (select(FieldExtractionJob.id)
                .where(FieldExtractionJob.status.in_(QUEUED_FIELD_JOB_STATUSES),
                       or_(FieldExtractionJob.next_retry_at.is_(None), FieldExtractionJob.next_retry_at <= now),
                       FieldExtractionJob.stage3a_extraction_id.not_in(running))
                .order_by(_PRIORITY, func.coalesce(FieldExtractionJob.next_retry_at, FieldExtractionJob.created_at),
                          FieldExtractionJob.id)
                .limit(5))
        if job_id is not None:
            stmt = stmt.where(FieldExtractionJob.id == job_id)
        with self.session_factory() as s:
            from app.database.session import reserve_sqlite_writer
            reserve_sqlite_writer(s)
            for cand in s.scalars(stmt).all():
                res = s.execute(update(FieldExtractionJob)
                                .where(FieldExtractionJob.id == cand,
                                       FieldExtractionJob.status.in_(QUEUED_FIELD_JOB_STATUSES))
                                .values(status=J.RUNNING.value, locked_by=self.worker_id, started_at=now,
                                        finished_at=None, next_retry_at=None, updated_at=now,
                                        attempt_count=FieldExtractionJob.attempt_count + 1)
                                .execution_options(synchronize_session=False))
                if res.rowcount != 1:
                    s.rollback()
                    continue
                s.commit()  # claim durable before any work
                job = s.get(FieldExtractionJob, cand)
                c = _Claimed(job.id, job.stage3a_extraction_id, bool(job.force), job.attempt_count)
                s.commit()
                with self._state:
                    self.current_job_id = cand
                log_event(logger, logging.INFO, "field_extraction_job_claimed", job_id=cand,
                          stage3a_extraction_id=c.stage3a_extraction_id, attempt=c.attempt, force=c.force)
                return c
        return None

    def _process(self, c: _Claimed) -> FieldJobResult:
        try:
            p = self.service.prepare(c.stage3a_extraction_id, force=c.force)
        except Exception as exc:
            logger.exception("field_extraction_job_exception job_id=%s", c.job_id)
            return self._finish(c, retry_or_fail(FieldErrorCode.ENGINE_ERROR.value, f"{type(exc).__name__}: {exc}",
                                                 c.attempt, self.settings, self.clock()), "ERROR")
        if p.not_ready_code:
            return self._finish(c, Decision(J.SKIPPED.value, p.not_ready_code, p.not_ready_message), "NOT_READY")
        if p.already_id is not None:
            return self._finish(c, Decision(J.SKIPPED.value, FieldErrorCode.ALREADY_EXTRACTED.value,
                                            "Already field-extracted (use force/re-extract)"),
                                "ALREADY_EXTRACTED", run_id=p.already_id)
        return self._finish(c, Decision(p.status, p.status_code), p.status, prepared=p)

    def _finish(self, c: _Claimed, d: Decision, outcome: str | None, *, run_id: int | None = None,
                prepared: PreparedFields | None = None) -> FieldJobResult:
        now = self.clock()
        lease_lost = False
        with self.session_factory() as s:
            try:
                lease = s.execute(update(FieldExtractionJob)
                                  .where(FieldExtractionJob.id == c.job_id,
                                         FieldExtractionJob.status == J.RUNNING.value,
                                         FieldExtractionJob.locked_by == self.worker_id)
                                  .values(updated_at=now).execution_options(synchronize_session=False))
                if lease.rowcount != 1:
                    lease_lost = True
                    s.rollback()
                else:
                    if prepared is not None:
                        run_id = self.service.persist(s, prepared)
                    self._write(s, c, d, outcome, run_id, now)
                    s.commit()
                    if prepared is not None:
                        # Stage 3C: queue only, in its own commit; never rolls back Stage 3B
                        queue_after_stage3b_commit(s, run_id, self.settings)
            except IntegrityError:
                s.rollback()
                run_id = current_field_extraction_id(s, c.stage3a_extraction_id)
                d, outcome = Decision(J.SKIPPED.value, FieldErrorCode.ALREADY_EXTRACTED.value,
                                      "Concurrent field extraction exists"), "ALREADY_EXTRACTED"
                self._write(s, c, d, outcome, run_id, now)
                s.commit()
            except OperationalError as exc:
                s.rollback()
                d, outcome, run_id = retry_or_fail(FieldErrorCode.DATABASE_ERROR.value, str(exc)[:500], c.attempt,
                                                   self.settings, now), "ERROR", None
                self._write(s, c, d, outcome, None, now)
                s.commit()
        with self._state:
            self.current_job_id = None
            self.last_outcome = {"job_id": c.job_id, "stage3a_extraction_id": c.stage3a_extraction_id,
                                 "status": d.status, "outcome": outcome, "field_extraction_id": run_id,
                                 "finished_at": now.isoformat(timespec="seconds") + "Z"}
        log_event(logger, logging.INFO if d.status in (J.SUCCESS.value, J.SKIPPED.value) else logging.WARNING,
                  "field_extraction_job_finished", job_id=c.job_id, stage3a_extraction_id=c.stage3a_extraction_id,
                  status=d.status, outcome=outcome, field_extraction_id=run_id, error_code=d.error_code,
                  lease_lost=lease_lost)
        return FieldJobResult(c.job_id, c.stage3a_extraction_id, c.attempt, d.status, outcome, run_id,
                              d.error_code, d.error_message, d.next_retry_at, lease_lost)

    def _write(self, s: Session, c: _Claimed, d: Decision, outcome, run_id, now) -> None:
        if d.status == J.RETRY.value and s.scalar(select(FieldExtractionJob.id).where(
                FieldExtractionJob.stage3a_extraction_id == c.stage3a_extraction_id,
                FieldExtractionJob.id != c.job_id,
                FieldExtractionJob.status.in_(QUEUED_FIELD_JOB_STATUSES)).limit(1)) is not None:
            d.status, d.error_code, d.next_retry_at = J.SKIPPED.value, "SUPERSEDED", None
        s.execute(update(FieldExtractionJob)
                  .where(FieldExtractionJob.id == c.job_id, FieldExtractionJob.locked_by == self.worker_id)
                  .values(status=d.status, error_code=d.error_code,
                          error_message=d.error_message[:4000] if d.error_message else None,
                          next_retry_at=d.next_retry_at, finished_at=None if d.status == J.RETRY.value else now,
                          locked_by=None, outcome=(outcome or "")[:40] or None, field_extraction_id=run_id,
                          updated_at=now)
                  .execution_options(synchronize_session=False))
