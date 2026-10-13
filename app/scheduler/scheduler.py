"""APScheduler wiring: interval jobs, never overlapping.

Jobs
----
* ``gem_discovery``            Stage 1 discovery (unchanged).
* ``document_worker``          Stage 2B: stale-job recovery + up to
                               DOCUMENT_WORKER_MAX_JOBS_PER_RUN due jobs per poll.
* ``document_refresh_queue``   Stage 2B: queue PERIODIC_REFRESH jobs for due tenders.

The two document jobs are only registered when DOCUMENT_WORKER_ENABLED=true.

Overlap protection: every job has ``max_instances=1`` + ``coalesce``; the
document worker additionally holds a cross-process file lock, so the scheduler,
the API and ``scripts/run_document_worker.py`` can never process concurrently.

Single scheduler per host: ``start()`` takes a process-lifetime file lock
(SCHEDULER_LOCK_FILE). If another process (e.g. a second Uvicorn worker)
already owns it, this process stays in *standby* and schedules nothing. This is
host-local only; with SQLite that is the supported deployment.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from filelock import FileLock, Timeout

from app.core.config import Settings
from app.core.constants import TriggerType
from app.core.logging import log_event
from app.services.discovery_service import CollectionAlreadyRunning, CollectionRunner

logger = logging.getLogger("app.scheduler")

JOB_ID = "gem_discovery"
DOCUMENT_WORKER_JOB_ID = "document_worker"
DOCUMENT_REFRESH_JOB_ID = "document_refresh_queue"
EXTRACTION_WORKER_JOB_ID = "extraction_worker"
FIELD_EXTRACTION_WORKER_JOB_ID = "field_extraction_worker"
AI_ANALYSIS_WORKER_JOB_ID = "ai_analysis_worker"
STATUS_VERIFICATION_JOB_ID = "status_verification"
MATCHING_JOB_ID = "seller_matching"


def scheduled_collection(runner: CollectionRunner) -> None:
    """Job body. Never raises: a failed run must not kill the scheduler."""
    log_event(logger, logging.INFO, "scheduled_collection_triggered")
    try:
        summary = runner.run(TriggerType.SCHEDULED)
        log_event(logger, logging.INFO, "scheduled_collection_done", run_id=summary.run_id,
                  status=summary.status)
    except CollectionAlreadyRunning:
        log_event(logger, logging.WARNING, "scheduled_collection_skipped", reason="already_running")
    except Exception:
        logger.exception("scheduled_collection_error")


def scheduled_document_worker(worker, runner: CollectionRunner | None = None) -> None:
    """Stage 2B job body. Never raises. Skips (does not queue up) when busy.

    Also yields while a Stage 1 collection is running, so GeM never sees
    listing and document traffic from this system at the same time.
    """
    try:
        if runner is not None and runner.is_running():
            log_event(logger, logging.INFO, "scheduled_document_worker_skipped", reason="collection_running")
            return
        batch = worker.run_batch()
        if batch.processed or batch.recovered_stale or batch.skipped_reason not in (None, "worker_busy"):
            log_event(logger, logging.INFO, "scheduled_document_worker_done", processed=batch.processed,
                      recovered=batch.recovered_stale, skipped=batch.skipped_reason)
    except Exception:
        logger.exception("scheduled_document_worker_error")


def scheduled_extraction_worker(worker) -> None:
    """Stage 3A job body. Never raises; skips when another extraction batch runs.
    Stage 3A never contacts GeM, so it does not wait for collection/document work."""
    try:
        batch = worker.run_batch()
        if batch.processed or batch.recovered_stale:
            log_event(logger, logging.INFO, "scheduled_extraction_worker_done", processed=batch.processed,
                      recovered=batch.recovered_stale)
    except Exception:
        logger.exception("scheduled_extraction_worker_error")


def scheduled_field_extraction_worker(worker) -> None:
    """Stage 3B job body. Never raises; skips when another field-extraction batch runs.
    Pure database work (no GeM, no PDF access)."""
    try:
        batch = worker.run_batch()
        if batch.processed or batch.recovered_stale:
            log_event(logger, logging.INFO, "scheduled_field_extraction_worker_done", processed=batch.processed,
                      recovered=batch.recovered_stale)
    except Exception:
        logger.exception("scheduled_field_extraction_worker_error")


def scheduled_ai_analysis_worker(worker) -> None:
    """Stage 3C job body (only registered when AI_ANALYSIS_WORKER_ENABLED=true). Never raises.
    Calls the configured AI provider for at most AI_MAX_JOBS_PER_RUN jobs per tick."""
    try:
        batch = worker.run_batch()
        if batch.processed or batch.recovered_stale:
            log_event(logger, logging.INFO, "scheduled_ai_analysis_worker_done", processed=batch.processed,
                      recovered=batch.recovered_stale, skipped=batch.skipped_reason)
    except Exception:
        logger.exception("scheduled_ai_analysis_worker_error")


def scheduled_status_verification(session_factory) -> None:
    """Re-derive tender current_status from deadlines. Deterministic, never raises."""
    from app.services.status_service import verify_statuses
    from app.utils.dates import utcnow
    try:
        with session_factory() as session:
            verify_statuses(session, now=utcnow())
            session.commit()
    except Exception:
        logger.exception("scheduled_status_verification_error")


def scheduled_matching(session_factory, max_evaluations: int, runner: CollectionRunner | None = None) -> None:
    """Recompute seller-tender matches whose inputs changed. No AI calls. Never raises."""
    from app.matching.service import MatchingService
    from app.utils.dates import utcnow
    try:
        if runner is not None and runner.is_running():
            log_event(logger, logging.INFO, "scheduled_matching_skipped", reason="collection_running")
            return
        with session_factory() as session:
            MatchingService(session).recalculate(now=utcnow(), max_evaluations=max_evaluations)
    except Exception:
        logger.exception("scheduled_matching_error")


def scheduled_document_refresh(worker) -> None:
    """Stage 2B periodic-refresh queueing. Never raises."""
    try:
        worker.queue_due_refreshes()
    except Exception:
        logger.exception("scheduled_document_refresh_error")


class CollectionScheduler:
    def __init__(self, settings: Settings, runner: CollectionRunner, document_worker=None,
                 extraction_worker=None, field_extraction_worker=None, ai_analysis_worker=None) -> None:
        self.settings = settings
        self.runner = runner
        self.document_worker = document_worker
        self.extraction_worker = extraction_worker
        self.field_extraction_worker = field_extraction_worker
        self.ai_analysis_worker = ai_analysis_worker
        self.standby = False
        self._process_lock = FileLock(str(settings.resolved_scheduler_lock_file))
        self._scheduler = BackgroundScheduler(
            timezone="UTC",
            job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": 300},
        )

    @property
    def running(self) -> bool:
        return bool(self._scheduler.running)

    @property
    def field_extraction_jobs_enabled(self) -> bool:
        return self.field_extraction_worker is not None and self.settings.field_extraction_worker_enabled

    @property
    def ai_analysis_jobs_enabled(self) -> bool:
        return self.ai_analysis_worker is not None and self.settings.ai_analysis_worker_enabled

    @property
    def extraction_jobs_enabled(self) -> bool:
        return self.extraction_worker is not None and self.settings.extraction_worker_enabled

    @property
    def document_jobs_enabled(self) -> bool:
        return self.document_worker is not None and self.settings.document_worker_enabled

    def start(self) -> None:
        if self._scheduler.running:
            return
        self.settings.resolved_scheduler_lock_file.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._process_lock.acquire(timeout=0)
        except Timeout:
            self.standby = True
            log_event(logger, logging.WARNING, "scheduler_standby",
                      reason="another process on this host owns the scheduler lock",
                      lock=str(self.settings.resolved_scheduler_lock_file))
            return
        self.standby = False
        now = datetime.now(timezone.utc)
        first_run = now + (
            timedelta(seconds=5) if self.settings.collect_on_startup
            else timedelta(minutes=self.settings.collection_interval_minutes)
        )
        self._scheduler.add_job(
            scheduled_collection,
            trigger=IntervalTrigger(minutes=self.settings.collection_interval_minutes, timezone="UTC"),
            args=[self.runner],
            id=JOB_ID,
            name="GeM live bid discovery",
            replace_existing=True,
            next_run_time=first_run,
        )
        if self.document_jobs_enabled:
            self._scheduler.add_job(
                scheduled_document_worker,
                trigger=IntervalTrigger(seconds=self.settings.document_job_poll_seconds, timezone="UTC"),
                args=[self.document_worker, self.runner],
                id=DOCUMENT_WORKER_JOB_ID,
                name="Stage 2B document job worker",
                replace_existing=True,
                next_run_time=now + timedelta(seconds=min(60, self.settings.document_job_poll_seconds)),
            )
            if self.settings.periodic_document_refresh_enabled:
                self._scheduler.add_job(
                    scheduled_document_refresh,
                    trigger=IntervalTrigger(minutes=self.settings.document_refresh_check_minutes, timezone="UTC"),
                    args=[self.document_worker],
                    id=DOCUMENT_REFRESH_JOB_ID,
                    name="Stage 2B periodic document refresh queueing",
                    replace_existing=True,
                    next_run_time=now + timedelta(minutes=1),
                )
        if self.extraction_jobs_enabled:
            self._scheduler.add_job(
                scheduled_extraction_worker,
                trigger=IntervalTrigger(seconds=self.settings.extraction_job_poll_seconds, timezone="UTC"),
                args=[self.extraction_worker],
                id=EXTRACTION_WORKER_JOB_ID,
                name="Stage 3A extraction job worker",
                replace_existing=True,
                next_run_time=now + timedelta(seconds=min(60, self.settings.extraction_job_poll_seconds)),
            )
        if self.field_extraction_jobs_enabled:
            self._scheduler.add_job(
                scheduled_field_extraction_worker,
                trigger=IntervalTrigger(seconds=self.settings.field_extraction_job_poll_seconds, timezone="UTC"),
                args=[self.field_extraction_worker],
                id=FIELD_EXTRACTION_WORKER_JOB_ID,
                name="Stage 3B field extraction job worker",
                replace_existing=True,
                next_run_time=now + timedelta(seconds=min(60, self.settings.field_extraction_job_poll_seconds)),
            )
        if self.ai_analysis_jobs_enabled:
            self._scheduler.add_job(
                scheduled_ai_analysis_worker,
                trigger=IntervalTrigger(seconds=self.settings.ai_analysis_job_poll_seconds, timezone="UTC"),
                args=[self.ai_analysis_worker],
                id=AI_ANALYSIS_WORKER_JOB_ID,
                name="Stage 3C AI analysis job worker",
                replace_existing=True,
                next_run_time=now + timedelta(seconds=min(60, self.settings.ai_analysis_job_poll_seconds)),
            )
        session_factory = getattr(self.runner, "session_factory", None)
        if session_factory is not None:
            self._scheduler.add_job(
                scheduled_status_verification,
                trigger=IntervalTrigger(minutes=self.settings.status_check_interval_minutes, timezone="UTC"),
                args=[session_factory],
                id=STATUS_VERIFICATION_JOB_ID,
                name="Tender status verification (deadline-based)",
                replace_existing=True,
                next_run_time=now + timedelta(seconds=30),
            )
            if self.settings.matching_enabled:
                self._scheduler.add_job(
                    scheduled_matching,
                    trigger=IntervalTrigger(minutes=self.settings.matching_interval_minutes, timezone="UTC"),
                    args=[session_factory, self.settings.matching_max_evaluations_per_run, self.runner],
                    id=MATCHING_JOB_ID,
                    name="Seller-tender matching recalculation",
                    replace_existing=True,
                    next_run_time=now + timedelta(minutes=1),
                )
        self._scheduler.start()
        log_event(logger, logging.INFO, "scheduler_started",
                  interval_minutes=self.settings.collection_interval_minutes,
                  first_run=first_run.isoformat(timespec="seconds"),
                  document_worker="enabled" if self.document_jobs_enabled else "disabled",
                  extraction_worker="enabled" if self.extraction_jobs_enabled else "disabled",
                  field_extraction_worker="enabled" if self.field_extraction_jobs_enabled else "disabled",
                  ai_analysis_worker="enabled" if self.ai_analysis_jobs_enabled else "disabled")

    def next_run_time(self, job_id: str = JOB_ID) -> str | None:
        job = self._scheduler.get_job(job_id) if self._scheduler.running else None
        return job.next_run_time.isoformat() if job and job.next_run_time else None

    def shutdown(self) -> None:
        if self.document_worker is not None:
            self.document_worker.request_stop()  # let an in-flight job finish, take no new ones
        if self.extraction_worker is not None:
            self.extraction_worker.request_stop()
        if self.field_extraction_worker is not None:
            self.field_extraction_worker.request_stop()
        if self.ai_analysis_worker is not None:
            self.ai_analysis_worker.request_stop()
        if self._scheduler.running:
            # wait=False: don't block shutdown on a long run; the run lock and
            # interrupted-run recovery keep the database consistent.
            self._scheduler.shutdown(wait=False)
            log_event(logger, logging.INFO, "scheduler_stopped")
        if self._process_lock.is_locked:
            self._process_lock.release(force=True)
