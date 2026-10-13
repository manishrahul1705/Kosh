"""Stage 3C analysis job queue (same invariants as the Stage 2B / 3A / 3B queues).

* At most ONE queued (PENDING/RETRY) job per Stage 3B run (app check + partial
  unique index uq_ai_analysis_jobs_source_queued).
* Only CURRENT Stage 3B runs with status SUCCESS / PARTIAL_SUCCESS are eligible.
* A non-force request for a run already analyzed with the configured
  provider/model/prompt/schema is not queued.
* Queueing never calls a provider. Processing needs the worker (disabled by default).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import and_, exists, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.ai.constants import (
    PROMPT_VERSION,
    QUEUED_AI_JOB_STATUSES,
    SCHEMA_VERSION,
    USABLE_STAGE3B_STATUSES,
    AIJobReason,
    AIJobStatus,
)
from app.ai.providers import effective_model, effective_provider
from app.core.config import Settings
from app.core.logging import log_event
from app.database.models import AIAnalysisJob, AIAnalysisRun, DocumentExtraction, TenderFieldExtraction
from app.fields.constants import USABLE_STAGE3A_STATUSES
from app.utils.dates import utcnow

logger = logging.getLogger("app.ai.job_queue")


@dataclass
class AIEnqueueResult:
    created: bool
    job: AIAnalysisJob | None = None
    skipped_reason: str | None = None  # already_queued | already_running | already_analyzed | not_ready

    @property
    def job_id(self) -> int | None:
        return self.job.id if self.job is not None else None


def eligible_stage3b_condition():
    usable_3a = exists().where(and_(DocumentExtraction.id == TenderFieldExtraction.stage3a_extraction_id,
                                    DocumentExtraction.is_current.is_(True),
                                    DocumentExtraction.status.in_(USABLE_STAGE3A_STATUSES)))
    return and_(TenderFieldExtraction.is_current.is_(True),
                TenderFieldExtraction.status.in_(USABLE_STAGE3B_STATUSES), usable_3a)


def analysis_source_current():
    """An analysis is "current" for display/stats only while its Stage 3B run is current
    (a re-extracted Stage 3B run supersedes the analyses of the old run)."""
    return and_(AIAnalysisRun.analysis_scope == "DOCUMENT", AIAnalysisRun.is_current.is_(True),
                exists().where(and_(TenderFieldExtraction.id == AIAnalysisRun.stage3b_extraction_id,
                                    TenderFieldExtraction.is_current.is_(True))))


def _usable(session: Session, stage3b_id: int) -> bool:
    return session.scalar(select(TenderFieldExtraction.id).where(TenderFieldExtraction.id == stage3b_id,
                                                                 eligible_stage3b_condition())) is not None


def _find(session: Session, stage3b_id: int, statuses) -> AIAnalysisJob | None:
    return session.scalar(select(AIAnalysisJob).where(AIAnalysisJob.stage3b_extraction_id == stage3b_id,
                                                      AIAnalysisJob.status.in_(statuses))
                          .order_by(AIAnalysisJob.id).limit(1))


def enqueue_ai_analysis(session: Session, stage3b_id: int, reason: AIJobReason | str, settings: Settings, *,
                        force: bool = False, now: datetime | None = None) -> AIEnqueueResult:
    if settings.ai_analysis_scope == 'TENDER_CORPUS':
        from app.corpus.queue import enqueue_corpus
        source=session.get(TenderFieldExtraction,stage3b_id)
        if source is None:return AIEnqueueResult(False,None,'not_ready')
        return enqueue_corpus(session,source.tender_id,settings,force=force,reason=reason.value if isinstance(reason,AIJobReason) else str(reason))
    reason_v = reason.value if isinstance(reason, AIJobReason) else str(reason)
    now = now or utcnow()
    if not _usable(session, stage3b_id):
        return AIEnqueueResult(False, None, "not_ready")
    queued = _find(session, stage3b_id, QUEUED_AI_JOB_STATUSES)
    if queued is not None:
        if force and not queued.force:
            queued.force, queued.reason, queued.updated_at = True, AIJobReason.REANALYZE.value, now
            session.flush()
        return AIEnqueueResult(False, queued, "already_queued")
    if not force:
        if _find(session, stage3b_id, (AIJobStatus.RUNNING.value,)) is not None:
            return AIEnqueueResult(False, None, "already_running")
        if session.scalar(select(AIAnalysisRun.id).where(
                AIAnalysisRun.stage3b_extraction_id == stage3b_id,
                AIAnalysisRun.provider == effective_provider(settings),
                AIAnalysisRun.model == effective_model(settings),
                AIAnalysisRun.prompt_version == PROMPT_VERSION, AIAnalysisRun.schema_version == SCHEMA_VERSION,
                AIAnalysisRun.is_current.is_(True)).limit(1)) is not None:
            return AIEnqueueResult(False, None, "already_analyzed")
    job = AIAnalysisJob(stage3b_extraction_id=stage3b_id, status=AIJobStatus.PENDING.value, reason=reason_v,
                        force=force, attempt_count=0, created_at=now, updated_at=now)
    try:
        with session.begin_nested():
            session.add(job)
            session.flush()
    except IntegrityError:
        return AIEnqueueResult(False, _find(session, stage3b_id, QUEUED_AI_JOB_STATUSES), "already_queued")
    log_event(logger, logging.INFO, "ai_analysis_job_queued", stage3b_extraction_id=stage3b_id, job_id=job.id,
              reason=reason_v, force=force)
    return AIEnqueueResult(True, job)


def queue_after_stage3b_commit(session: Session, stage3b_id: int | None, settings: Settings) -> None:
    """Stage 3B hook: called right AFTER a Stage 3B run was committed.

    Never raises and never rolls Stage 3B back: runs in its own commit. A failure is
    rolled back on its own, logged (``ai_analysis_job_queue_failed``), visible in
    health as ``stage3b_runs_unqueued`` and repaired by the (bounded) backfill.
    Only queues - nothing is sent to any AI provider here.
    """
    if not stage3b_id or not settings.ai_analysis_auto_queue:
        return
    try:
        from app.database.session import reserve_sqlite_writer
        reserve_sqlite_writer(session)
        if settings.ai_analysis_scope == 'DOCUMENT':
            res = enqueue_ai_analysis(session, stage3b_id, AIJobReason.STAGE3B_COMPLETED, settings)
        else:
            from app.corpus.queue import enqueue_corpus
            source = session.get(TenderFieldExtraction, stage3b_id)
            res = enqueue_corpus(session, source.tender_id, settings, reason='STAGE3B_COMPLETED') if source else AIEnqueueResult(False,None,'not_ready')
        session.commit()
        if res.skipped_reason == "not_ready":
            log_event(logger, logging.INFO, "ai_analysis_not_queued", stage3b_extraction_id=stage3b_id,
                      why="stage3b_not_usable")
    except Exception as exc:
        try:
            session.rollback()
        except Exception:  # pragma: no cover
            pass
        log_event(logger, logging.ERROR, "ai_analysis_job_queue_failed", stage3b_extraction_id=stage3b_id,
                  error=f"{type(exc).__name__}: {exc}"[:300])


def backfill_candidate_ids(session: Session, *, limit: int) -> list[int]:
    """Eligible current Stage 3B runs with no Stage 3C job ever and no current analysis."""
    has_job = exists().where(AIAnalysisJob.stage3b_extraction_id == TenderFieldExtraction.id)
    has_run = exists().where(and_(AIAnalysisRun.stage3b_extraction_id == TenderFieldExtraction.id,
                                  AIAnalysisRun.is_current.is_(True)))
    return list(session.scalars(select(TenderFieldExtraction.id)
                                .where(eligible_stage3b_condition(), ~has_job, ~has_run)
                                .order_by(TenderFieldExtraction.id.desc()).limit(limit)).all())


def backfill_ai_jobs(session: Session, settings: Settings, *, limit: int, dry_run: bool = False) -> list[int]:
    if settings.ai_analysis_scope == 'TENDER_CORPUS':
        from app.corpus.queue import enqueue_corpus
        ids=[]
        # Stream current tender IDs; unchanged/terminal fingerprints are skipped.
        for tid in session.scalars(select(TenderFieldExtraction.tender_id).where(eligible_stage3b_condition()).distinct().order_by(TenderFieldExtraction.tender_id)):
            result=enqueue_corpus(session,tid,settings,reason='BACKFILL',dry_run=dry_run)
            if result.created:
                ids.append(tid)
                if len(ids)>=limit:break
        return ids
    ids = backfill_candidate_ids(session, limit=limit)
    if dry_run:
        return ids
    done = [i for i in ids if enqueue_ai_analysis(session, i, AIJobReason.BACKFILL, settings).created]
    log_event(logger, logging.INFO, "ai_analysis_backfill_completed", queued=len(done), limit=limit)
    return done
