"""Discovery orchestration: lock -> run row -> collect -> upsert -> finalize."""

from __future__ import annotations

import logging
from collections.abc import Callable
from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from app.collectors.base import Collector, CollectorResult
from app.core.config import Settings
from app.core.constants import RunStatus, TriggerType
from app.core.logging import log_event
from app.database.models import CollectionRun
from app.schemas.collection import RunSummary
from app.services.run_lock import CollectionAlreadyRunning, CollectionLock
from app.services.tender_service import JobQueuePolicy, close_expired_unseen, upsert_records
from app.utils.dates import utcnow
from app.database.session import reserve_sqlite_writer

logger = logging.getLogger("app.services.discovery")

__all__ = ["CollectionRunner", "CollectionAlreadyRunning", "decide_status"]


def decide_status(result: CollectorResult, failed_items: int) -> RunStatus:
    if result.blocked:
        return RunStatus.BLOCKED_BY_HUMAN_VERIFICATION
    if result.error and not result.records:
        return RunStatus.FAILED
    if result.error or failed_items:
        return RunStatus.PARTIAL_SUCCESS
    return RunStatus.SUCCESS


def _error_text(result: CollectorResult, persist_failures: list[dict]) -> str | None:
    parts: list[str] = []
    if result.blocked:
        parts.append(f"BLOCKED_BY_HUMAN_VERIFICATION: {result.block_reason}")
    if result.error:
        parts.append(f"collector: {result.error}")
    for f in result.failures[:5]:
        parts.append(f"item p{f.page}#{f.index} bid={f.hint}: {f.reason}")
    if len(result.failures) > 5:
        parts.append(f"... {len(result.failures) - 5} more item failures")
    for f in persist_failures[:5]:
        parts.append(f"persist bid={f['bid']}: {f['reason']}")
    return " | ".join(parts)[:4000] if parts else None


class CollectionRunner:
    """Owns the lock; safe to call from the scheduler, API and CLI."""

    def __init__(
        self,
        settings: Settings,
        session_factory: sessionmaker[Session],
        collector_factory: Callable[[], Collector],
        lock: CollectionLock | None = None,
    ) -> None:
        self.settings = settings
        self.session_factory = session_factory
        self.collector_factory = collector_factory
        self.lock = lock or CollectionLock(settings.resolve_path(settings.lock_file))

    def is_running(self) -> bool:
        return self.lock.is_locked()

    def recover_interrupted_runs(self) -> int:
        """Mark RUNNING rows left by a crashed process as FAILED (lock must be free)."""
        if self.lock.is_locked():
            return 0
        with self.session_factory() as s:
            res = s.execute(
                update(CollectionRun)
                .where(CollectionRun.status == RunStatus.RUNNING.value)
                .values(status=RunStatus.FAILED.value, finished_at=utcnow(),
                        error_message="interrupted: process stopped before the run finished")
            )
            s.commit()
            count = res.rowcount or 0
        if count:
            log_event(logger, logging.WARNING, "interrupted_runs_recovered", count=count)
        return count

    def run(self, trigger: TriggerType) -> RunSummary:
        """Execute one discovery run. Raises CollectionAlreadyRunning if busy."""
        with self.lock.acquire():
            return self._run_locked(trigger)

    def _run_locked(self, trigger: TriggerType) -> RunSummary:
        started = utcnow()
        with self.session_factory() as s:
            run = CollectionRun(started_at=started, status=RunStatus.RUNNING.value, trigger_type=trigger.value)
            s.add(run)
            s.commit()
            run_id = run.id
        log_event(logger, logging.INFO, "collection_started", run_id=run_id, trigger=trigger.value)

        summary = RunSummary(run_id=run_id, status=RunStatus.FAILED.value, trigger_type=trigger.value)
        try:
            collector = self.collector_factory()
            result = collector.discover_live_tenders()

            with self.session_factory() as s:
                reserve_sqlite_writer(s)
                now = utcnow()
                policy = JobQueuePolicy.from_settings(self.settings)
                stats = upsert_records(s, result.records, now=now, run_id=run_id, queue_policy=policy)
                closed = 0
                # Only trust "not seen" after a complete, unblocked listing walk.
                complete_walk = (not result.blocked and not result.error and not result.truncated
                                 and result.pages_checked > 0)
                if self.settings.mark_expired_as_closed and complete_walk:
                    closed = close_expired_unseen(s, now=now, run_started_at=started, run_id=run_id,
                                                  queue_policy=policy)
                failed_items = len(result.failures) + stats.failed
                status = decide_status(result, failed_items)
                run = s.get(CollectionRun, run_id)
                run.finished_at = utcnow()
                run.status = status.value
                run.pages_checked = result.pages_checked
                run.bids_seen = stats.seen
                run.new_bids = stats.new
                run.updated_bids = stats.updated
                run.unchanged_bids = stats.unchanged
                run.failed_items = failed_items
                run.error_message = _error_text(result, stats.failures)
                s.commit()

            summary = RunSummary(
                run_id=run_id, status=status.value, trigger_type=trigger.value,
                pages_checked=result.pages_checked, bids_seen=stats.seen, new_bids=stats.new,
                updated_bids=stats.updated, unchanged_bids=stats.unchanged, failed_items=failed_items,
                closed_by_deadline=closed, error_message=run.error_message,
            )
            log_event(logger, logging.INFO if status != RunStatus.FAILED else logging.ERROR,
                      "collection_completed", run_id=run_id, status=status.value,
                      pages=result.pages_checked, seen=stats.seen, new=stats.new,
                      updated=stats.updated, unchanged=stats.unchanged, failed=failed_items,
                      collector=result.collector_name)
            return summary
        except Exception as exc:
            logger.exception("collection_crashed run_id=%s", run_id)
            with self.session_factory() as s:
                reserve_sqlite_writer(s)
                run = s.get(CollectionRun, run_id)
                if run is not None:
                    run.finished_at = utcnow()
                    run.status = RunStatus.FAILED.value
                    run.error_message = f"{type(exc).__name__}: {exc}"[:4000]
                    s.commit()
            summary.error_message = f"{type(exc).__name__}: {exc}"
            return summary


def latest_run(session: Session) -> CollectionRun | None:
    return session.scalar(select(CollectionRun).order_by(CollectionRun.id.desc()).limit(1))

