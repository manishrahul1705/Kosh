"""Stage 3C analysis worker (Stage 2B / 3A / 3B safety design + cost controls).

    PENDING / due RETRY --claim (commit)--> RUNNING --prepare + provider call (no DB txn)-->
        ONE transaction: persist run + chunks + requirements + evidence + flags AND finish the job

Job result mapping:
    run SUCCESS / PARTIAL_SUCCESS                 -> SUCCESS / PARTIAL_SUCCESS
    already analyzed (no force) / source not ready -> SKIPPED (never faked as success)
    timeout / 429 / 5xx / network (after the bounded in-call retries)
                                                  -> RETRY (backoff), FAILED after AI_ANALYSIS_MAX_ATTEMPTS
    auth failure / invalid model / bad config     -> BLOCKED (never retried automatically) and the
                                                     worker pauses AI_BLOCKED_COOLDOWN_MINUTES
    empty / truncated / blocked / malformed / schema-invalid response -> FAILED (no automatic retry)

Cost controls: provider not configured -> nothing is claimed; at most
AI_MAX_JOBS_PER_RUN per batch; at most AI_MAX_ANALYSES_PER_DAY attempts per rolling 24 h.
Concurrency 1 per host (thread lock + file lock data/ai_analysis_worker.lock).
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

from app.ai.constants import QUEUED_AI_JOB_STATUSES, AIErrorCode, AIJobReason, AIJobStatus
from app.ai.providers.base import ProviderError
from app.ai.schema import ResponseInvalid
from app.ai.service import (
    AnalysisService,
    CallResult,
    Interpretation,
    PreparedAnalysis,
    current_analysis_id,
    provider_calls_last_24h,
)
from app.core.config import Settings
from app.core.logging import log_event
from app.database.models import AIAnalysisJob
from app.services.run_lock import CollectionAlreadyRunning, CollectionLock
from app.utils.dates import utcnow

logger = logging.getLogger("app.ai.job_worker")
J = AIJobStatus
SKIP_BUSY = "worker_busy"
SKIP_STOPPED = "stop_requested"
SKIP_NOT_CONFIGURED = "ai_not_configured"
SKIP_BLOCKED = "provider_blocked"
SKIP_DAILY_LIMIT = "daily_limit_reached"

_PRIORITY = case(
    (AIAnalysisJob.reason.in_([AIJobReason.MANUAL.value, AIJobReason.REANALYZE.value]), 0),
    (AIAnalysisJob.reason == AIJobReason.STAGE3B_COMPLETED.value, 1),
    else_=2,
)


@dataclass
class Decision:
    status: str
    error_code: str | None = None
    error_message: str | None = None
    next_retry_at: datetime | None = None


@dataclass
class AIJobResult:
    job_id: int
    stage3b_extraction_id: int
    attempt: int
    status: str
    outcome: str | None
    analysis_run_id: int | None = None
    error_code: str | None = None
    error_message: str | None = None
    next_retry_at: datetime | None = None
    lease_lost: bool = False


@dataclass
class AIBatch:
    started_at: datetime
    finished_at: datetime | None = None
    recovered_stale: int = 0
    skipped_reason: str | None = None
    skipped_detail: str | None = None
    jobs: list[AIJobResult] = field(default_factory=list)

    @property
    def processed(self) -> int:
        return len(self.jobs)


@dataclass
class _Claimed:
    job_id: int
    stage3b_extraction_id: int
    force: bool
    attempt: int
    analysis_scope: str = 'DOCUMENT'
    tender_id: int | None = None
    corpus_fingerprint: str | None = None


def retry_or_fail(code: str, message: str, attempt: int, settings: Settings, now: datetime) -> Decision:
    if attempt < settings.ai_analysis_max_attempts:
        delay = timedelta(minutes=settings.ai_analysis_retry_backoff_minutes * (2 ** max(0, attempt - 1)))
        return Decision(J.RETRY.value, code, message, now + delay)
    return Decision(J.FAILED.value, "RETRIES_EXHAUSTED",
                    f"{code} after {attempt}/{settings.ai_analysis_max_attempts} attempt(s): {message}"[:4000])


class AIAnalysisJobWorker:
    def __init__(self, settings: Settings, session_factory: sessionmaker[Session],
                 service: AnalysisService | None = None, *, lock: CollectionLock | None = None,
                 clock: Callable[[], datetime] = utcnow, worker_id: str | None = None) -> None:
        self.settings = settings
        self.session_factory = session_factory
        self.clock = clock
        self.service = service or AnalysisService(settings, session_factory, clock=clock)
        self.lock = lock or CollectionLock(settings.resolved_ai_analysis_worker_lock_file)
        self.host = socket.gethostname()
        self.worker_id = worker_id or f"{self.host}:{os.getpid()}:{uuid.uuid4().hex[:8]}"
        self._stop = threading.Event()
        self._state = threading.Lock()
        self.current_job_id: int | None = None
        self.last_run_started_at: datetime | None = None
        self.last_run_finished_at: datetime | None = None
        self.last_outcome: dict | None = None
        self.blocked_until: datetime | None = None
        self.blocked_reason: str | None = None

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
    def _persistent_block(self, s: Session, now: datetime) -> AIAnalysisJob | None:
        """Latest BLOCKED job for the configured provider/model inside the cool-down window
        (survives process restarts, e.g. repeated CLI --once runs with a revoked key)."""
        provider, model = self.service.identity()
        cutoff = now - timedelta(minutes=self.settings.ai_blocked_cooldown_minutes)
        return s.scalar(select(AIAnalysisJob).where(
            AIAnalysisJob.status == J.BLOCKED.value, AIAnalysisJob.provider == provider,
            AIAnalysisJob.model == model, AIAnalysisJob.finished_at.is_not(None),
            AIAnalysisJob.finished_at >= cutoff).order_by(AIAnalysisJob.finished_at.desc()).limit(1))

    def _gate(self, explicit: bool = False) -> tuple[str, str] | None:
        """Reasons not to call any provider right now (checked before every claim).

        ``explicit`` (a specific job / Stage 3B run requested by a person) skips only the
        persisted BLOCKED cool-down, so a fixed key can be tried at once; the in-process
        cool-down, configuration check and daily cap always apply.
        """
        now = self.clock()
        if self.blocked_until is not None and now < self.blocked_until:
            return SKIP_BLOCKED, f"{self.blocked_reason} (paused until {self.blocked_until.isoformat()}Z)"
        try:
            self.service.provider()
        except ProviderError as exc:
            return SKIP_NOT_CONFIGURED, f"{exc.code}: {self.service.safe_message(exc)}"
        with self.session_factory() as s:
            used = provider_calls_last_24h(s, now)
            blocked = None if explicit else self._persistent_block(s, now)
            if blocked is not None:
                until = blocked.finished_at + timedelta(minutes=self.settings.ai_blocked_cooldown_minutes)
                detail = (f"job {blocked.id} was BLOCKED ({blocked.error_code}); automatic processing paused "
                          f"until {until.isoformat(timespec='seconds')}Z - fix the key/model, then run one "
                          "analysis explicitly (--stage3b-extraction-id)")
        if blocked is not None:
            return SKIP_BLOCKED, detail
        if used >= self.settings.ai_max_analyses_per_day:
            return SKIP_DAILY_LIMIT, f"{used} provider call(s) in the last 24 h (AI_MAX_ANALYSES_PER_DAY=" \
                                     f"{self.settings.ai_max_analyses_per_day})"
        return None

    def run_batch(self, max_jobs: int | None = None, *, job_id: int | None = None) -> AIBatch:
        max_jobs = max(1, min(max_jobs or self.settings.ai_max_jobs_per_run, 100))
        batch = AIBatch(started_at=self.clock())
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
                        gate = self._gate(explicit=job_id is not None)
                        if gate is not None:
                            batch.skipped_reason, batch.skipped_detail = gate
                            log_event(logger, logging.WARNING, "ai_analysis_worker_paused", reason=gate[0],
                                      detail=gate[1][:200])
                            break
                        claimed = self._claim(job_id)
                        if claimed is None:
                            break
                        res = self._process(claimed)
                        batch.jobs.append(res)
                        if res.status == J.BLOCKED.value or job_id is not None:
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
        cutoff = now - timedelta(minutes=self.settings.ai_analysis_stale_running_minutes)
        n = 0
        with self.session_factory() as s:
            for job in s.scalars(select(AIAnalysisJob).where(AIAnalysisJob.status == J.RUNNING.value)).all():
                same_host = bool(job.locked_by) and job.locked_by.split(":", 1)[0] == self.host
                if not (same_host or job.started_at is None or job.started_at < cutoff):
                    continue
                other = s.scalar(select(AIAnalysisJob.id).where(
                    AIAnalysisJob.stage3b_extraction_id == job.stage3b_extraction_id, AIAnalysisJob.id != job.id,
                    AIAnalysisJob.status.in_(QUEUED_AI_JOB_STATUSES)).limit(1)) is not None
                if job.attempt_count >= self.settings.ai_analysis_max_attempts:
                    values = dict(status=J.FAILED.value, error_code="STALE_RUNNING", finished_at=now,
                                  error_message="Worker stopped during AI analysis; attempts exhausted")
                elif other:
                    values = dict(status=J.SKIPPED.value, error_code="SUPERSEDED", finished_at=now,
                                  error_message="Worker stopped; another job is queued")
                else:
                    values = dict(status=J.RETRY.value, error_code="STALE_RUNNING", next_retry_at=now,
                                  error_message="Worker stopped during AI analysis; retrying")
                res = s.execute(update(AIAnalysisJob)
                                .where(AIAnalysisJob.id == job.id, AIAnalysisJob.status == J.RUNNING.value)
                                .values(locked_by=None, updated_at=now, **values)
                                .execution_options(synchronize_session=False))
                if res.rowcount:
                    n += 1
                    log_event(logger, logging.WARNING, "ai_analysis_job_recovered", job_id=job.id,
                              new_status=values["status"])
            s.commit()
        return n

    def _claim(self, job_id: int | None) -> _Claimed | None:
        now = self.clock()
        provider, model = self.service.identity()
        running = select(AIAnalysisJob.stage3b_extraction_id).where(AIAnalysisJob.status == J.RUNNING.value)
        stmt = (select(AIAnalysisJob.id)
                .where(or_(AIAnalysisJob.analysis_scope == 'DOCUMENT',
                           (AIAnalysisJob.provider == provider) & (AIAnalysisJob.model == model)),
                       AIAnalysisJob.status.in_(QUEUED_AI_JOB_STATUSES),
                       or_(AIAnalysisJob.next_retry_at.is_(None), AIAnalysisJob.next_retry_at <= now),
                       AIAnalysisJob.stage3b_extraction_id.not_in(running))
                .order_by(_PRIORITY, func.coalesce(AIAnalysisJob.next_retry_at, AIAnalysisJob.created_at),
                          AIAnalysisJob.id)
                .limit(5))
        if job_id is not None:
            stmt = stmt.where(AIAnalysisJob.id == job_id)
        with self.session_factory() as s:
            from app.database.session import reserve_sqlite_writer
            reserve_sqlite_writer(s)
            for cand in s.scalars(stmt).all():
                res = s.execute(update(AIAnalysisJob)
                                .where(AIAnalysisJob.id == cand, AIAnalysisJob.status.in_(QUEUED_AI_JOB_STATUSES))
                                .values(status=J.RUNNING.value, locked_by=self.worker_id, started_at=now,
                                        finished_at=None, next_retry_at=None, updated_at=now,
                                        provider=provider[:40], model=model[:120],
                                        attempt_count=AIAnalysisJob.attempt_count + 1)
                                .execution_options(synchronize_session=False))
                if res.rowcount != 1:
                    s.rollback()
                    continue
                s.commit()  # claim durable before any provider call
                job = s.get(AIAnalysisJob, cand)
                c = _Claimed(job.id, job.stage3b_extraction_id, bool(job.force), job.attempt_count, job.analysis_scope, job.tender_id, job.corpus_fingerprint)
                s.commit()
                with self._state:
                    self.current_job_id = cand
                log_event(logger, logging.INFO, "ai_analysis_job_claimed", job_id=cand,
                          stage3b_extraction_id=c.stage3b_extraction_id, attempt=c.attempt, force=c.force,
                          provider=provider, model=model)
                return c
        return None

    def _process(self, c: _Claimed) -> AIJobResult:
        now = self.clock
        try:
            if c.analysis_scope == 'TENDER_CORPUS':
                from app.corpus.analysis import prepare_corpus
                p = prepare_corpus(self.service,c.tender_id,c.force,c.corpus_fingerprint)
                if p.not_ready_code == 'CORPUS_SUPERSEDED':
                    from app.corpus.queue import enqueue_corpus
                    with self.session_factory() as s:
                        enqueue_corpus(s,c.tender_id,self.settings)
                        s.commit()
            else:
                p = self.service.prepare(c.stage3b_extraction_id, force=c.force)
        except Exception as exc:
            logger.exception("ai_analysis_job_exception job_id=%s", c.job_id)
            return self._finish(c, retry_or_fail(AIErrorCode.ENGINE_ERROR.value, f"{type(exc).__name__}: {exc}",
                                                 c.attempt, self.settings, now()), "ERROR")
        if p.not_ready_code:
            return self._finish(c, Decision(J.SKIPPED.value, p.not_ready_code, p.not_ready_message), "NOT_READY")
        if p.already_id is not None:
            return self._finish(c, Decision(J.SKIPPED.value, AIErrorCode.ALREADY_ANALYZED.value,
                                            "Already analyzed with this provider/model/prompt (use reanalyze)"),
                                "ALREADY_ANALYZED", run_id=p.already_id)
        call = self.service.call(p, job_id=c.job_id)
        if call.error is not None:
            e = call.error
            msg = self.service.safe_message(e)
            if e.blocking:
                self.blocked_until = now() + timedelta(minutes=self.settings.ai_blocked_cooldown_minutes)
                self.blocked_reason = e.code
                return self._finish(c, Decision(J.BLOCKED.value, e.code, msg), "BLOCKED")
            if e.transient:
                return self._finish(c, retry_or_fail(e.code, msg, c.attempt, self.settings, now()), "PROVIDER_ERROR")
            return self._finish(c, Decision(J.FAILED.value, e.code, msg), "INVALID_RESPONSE")
        try:
            it = self.service.interpret(p, call.response)
        except ResponseInvalid as exc:
            return self._finish(c, Decision(J.FAILED.value, exc.code, str(exc)[:500]), "INVALID_RESPONSE")
        except Exception as exc:
            logger.exception("ai_analysis_interpret_exception job_id=%s", c.job_id)
            return self._finish(c, retry_or_fail(AIErrorCode.ENGINE_ERROR.value, f"{type(exc).__name__}: {exc}",
                                                 c.attempt, self.settings, now()), "ERROR")
        return self._finish(c, Decision(it.status, it.status_code), it.status, prepared=(p, call, it))

    def _finish(self, c: _Claimed, d: Decision, outcome: str | None, *, run_id: int | None = None,
                prepared: tuple[PreparedAnalysis, CallResult, Interpretation] | None = None) -> AIJobResult:
        now = self.clock()
        lease_lost = False
        with self.session_factory() as s:
            try:
                lease = s.execute(update(AIAnalysisJob)
                                  .where(AIAnalysisJob.id == c.job_id, AIAnalysisJob.status == J.RUNNING.value,
                                         AIAnalysisJob.locked_by == self.worker_id)
                                  .values(updated_at=now).execution_options(synchronize_session=False))
                if lease.rowcount != 1:
                    lease_lost = True
                    s.rollback()
                else:
                    if prepared is not None:
                        run_id = self.service.persist(s, *prepared)
                    self._write(s, c, d, outcome, run_id, now)
                    s.commit()
            except IntegrityError:
                s.rollback()
                p = prepared[0] if prepared else None
                run_id = current_analysis_id(s, c.stage3b_extraction_id, p.provider, p.model) if p else None
                d, outcome = Decision(J.SKIPPED.value, AIErrorCode.ALREADY_ANALYZED.value,
                                      "Concurrent analysis exists"), "ALREADY_ANALYZED"
                self._write(s, c, d, outcome, run_id, now)
                s.commit()
            except OperationalError as exc:
                s.rollback()
                d, outcome, run_id = retry_or_fail(AIErrorCode.DATABASE_ERROR.value, str(exc)[:500], c.attempt,
                                                   self.settings, now), "ERROR", None
                self._write(s, c, d, outcome, None, now)
                s.commit()
            except Exception as exc:  # never leave the job RUNNING because persisting failed
                s.rollback()
                logger.exception("ai_analysis_persist_failed job_id=%s", c.job_id)
                d, outcome, run_id = retry_or_fail(AIErrorCode.ENGINE_ERROR.value, f"{type(exc).__name__}: {exc}"[:500],
                                                   c.attempt, self.settings, now), "ERROR", None
                self._write(s, c, d, outcome, None, now)
                s.commit()
        with self._state:
            self.current_job_id = None
            self.last_outcome = {"job_id": c.job_id, "stage3b_extraction_id": c.stage3b_extraction_id,
                                 "status": d.status, "outcome": outcome, "analysis_run_id": run_id,
                                 "error_code": d.error_code, "finished_at": now.isoformat(timespec="seconds") + "Z"}
        log_event(logger, logging.INFO if d.status in (J.SUCCESS.value, J.SKIPPED.value) else logging.WARNING,
                  "ai_analysis_job_finished", job_id=c.job_id, stage3b_extraction_id=c.stage3b_extraction_id,
                  status=d.status, outcome=outcome, analysis_run_id=run_id, error_code=d.error_code,
                  lease_lost=lease_lost)
        return AIJobResult(c.job_id, c.stage3b_extraction_id, c.attempt, d.status, outcome, run_id,
                           d.error_code, d.error_message, d.next_retry_at, lease_lost)

    def _write(self, s: Session, c: _Claimed, d: Decision, outcome, run_id, now) -> None:
        if d.status == J.RETRY.value and s.scalar(select(AIAnalysisJob.id).where(
                AIAnalysisJob.stage3b_extraction_id == c.stage3b_extraction_id, AIAnalysisJob.id != c.job_id,
                AIAnalysisJob.status.in_(QUEUED_AI_JOB_STATUSES)).limit(1)) is not None:
            d.status, d.error_code, d.next_retry_at = J.SKIPPED.value, "SUPERSEDED", None
        s.execute(update(AIAnalysisJob)
                  .where(AIAnalysisJob.id == c.job_id, AIAnalysisJob.locked_by == self.worker_id)
                  .values(status=d.status, error_code=d.error_code,
                          error_message=d.error_message[:4000] if d.error_message else None,
                          next_retry_at=d.next_retry_at, finished_at=None if d.status == J.RETRY.value else now,
                          locked_by=None, outcome=(outcome or "")[:40] or None, analysis_run_id=run_id,
                          updated_at=now)
                  .execution_options(synchronize_session=False))
