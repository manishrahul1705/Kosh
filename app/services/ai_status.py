"""Stage 3C operational status for /health, /api/stats and /api/ai-analysis/worker.

Never returns credentials: only whether a provider is configured, its name and model.
"""

from __future__ import annotations

from sqlalchemy import and_, exists, func, select
from sqlalchemy.orm import Session

from app.ai.constants import PROMPT_VERSION, SCHEMA_VERSION, AIJobStatus, FlagType, RunStatus
from app.ai.job_queue import analysis_source_current, eligible_stage3b_condition
from app.ai.providers import effective_model, effective_provider, provider_configured
from app.database.models import AIAnalysisFlag, AIAnalysisJob, AIAnalysisRun, AIRequirement, TenderFieldExtraction
from app.ai.service import provider_calls_last_24h
from app.utils.dates import as_aware_utc, utcnow


def _iso(dt):
    a = as_aware_utc(dt)
    return a.isoformat() if a else None


def ai_analysis_status(db: Session, worker=None, scheduler=None, settings=None) -> dict:
    settings = settings or getattr(worker, "settings", None)
    runs = {s.value: 0 for s in RunStatus}
    current = analysis_source_current()
    for st, n in db.execute(select(AIAnalysisRun.status, func.count()).where(current)
                            .group_by(AIAnalysisRun.status)).all():
        runs[st] = n
    jobs = {s.value: 0 for s in AIJobStatus}
    for st, n in db.execute(select(AIAnalysisJob.status, func.count()).group_by(AIAnalysisJob.status)).all():
        jobs[st] = n
    eligible = eligible_stage3b_condition()
    has_run = exists().where(and_(AIAnalysisRun.stage3b_extraction_id == TenderFieldExtraction.id, current))
    has_job = exists().where(AIAnalysisJob.stage3b_extraction_id == TenderFieldExtraction.id)
    n_eligible = db.scalar(select(func.count(TenderFieldExtraction.id)).where(eligible)) or 0
    without = db.scalar(select(func.count(TenderFieldExtraction.id)).where(eligible, ~has_run)) or 0
    unqueued = db.scalar(select(func.count(TenderFieldExtraction.id)).where(eligible, ~has_run, ~has_job)) or 0
    current_ids = select(AIAnalysisRun.id).where(current)
    n_req = db.scalar(select(func.count(AIRequirement.id)).where(AIRequirement.analysis_run_id.in_(current_ids))) or 0
    flag_counts: dict[str, int] = {}
    for ft, n in db.execute(select(AIAnalysisFlag.flag_type, func.count())
                            .where(AIAnalysisFlag.analysis_run_id.in_(current_ids))
                            .group_by(AIAnalysisFlag.flag_type)).all():
        flag_counts[ft] = n
    ambiguities = db.scalar(select(func.coalesce(func.sum(AIAnalysisRun.ambiguities_count), 0)).where(current)) or 0
    last = db.execute(select(AIAnalysisJob.id, AIAnalysisJob.stage3b_extraction_id, AIAnalysisJob.status,
                             AIAnalysisJob.outcome, AIAnalysisJob.error_code, AIAnalysisJob.finished_at)
                      .where(AIAnalysisJob.finished_at.is_not(None))
                      .order_by(AIAnalysisJob.finished_at.desc(), AIAnalysisJob.id.desc()).limit(1)).first()
    last_outcome = getattr(worker, "last_outcome", None) or (
        {"job_id": last.id, "stage3b_extraction_id": last.stage3b_extraction_id, "status": last.status,
         "outcome": last.outcome, "error_code": last.error_code, "finished_at": _iso(last.finished_at)}
        if last else None)
    sched = bool(scheduler is not None and scheduler.running and getattr(scheduler, "ai_analysis_jobs_enabled", False))
    configured = provider_configured(settings) if settings is not None else False
    blocked_until = getattr(worker, "blocked_until", None)
    return {
        "analysis_scope":getattr(settings,'ai_analysis_scope','DOCUMENT'),
        "corpus_status_endpoint":"/api/corpus/{tender_id}",
        "count_scope":"Legacy current-document metrics; corpus currentness uses live fingerprint",
        "ai_provider_configured": configured,
        "ai_provider": (effective_provider(settings) or None) if settings is not None else None,
        "ai_model": (effective_model(settings) or None) if settings is not None else None,
        "ai_prompt_version": PROMPT_VERSION,
        "ai_schema_version": SCHEMA_VERSION,
        "ai_analysis_worker_enabled": bool(settings and settings.ai_analysis_worker_enabled),
        "ai_analysis_worker_running": bool(worker is not None and worker.is_busy()),
        "ai_analysis_scheduler_running": sched,
        "next_ai_analysis_worker_run": scheduler.next_run_time("ai_analysis_worker") if sched else None,
        "current_ai_analysis_job_id": getattr(worker, "current_job_id", None),
        "last_ai_analysis_outcome": last_outcome,
        "ai_blocked_until": _iso(blocked_until) if blocked_until else None,
        "ai_max_analyses_per_day": settings.ai_max_analyses_per_day if settings is not None else None,
        "ai_provider_calls_last_24h": provider_calls_last_24h(db, utcnow()),
        "stage3b_runs_eligible": n_eligible,
        "stage3b_runs_without_analysis": without,
        # eligible Stage 3B runs with neither an analysis nor any job (e.g. a failed auto-queue)
        "stage3b_runs_unqueued": unqueued,
        "ai_analyses_total": sum(runs.values()),
        "ai_analyses_success": runs[RunStatus.SUCCESS.value],
        "ai_analyses_partial": runs[RunStatus.PARTIAL_SUCCESS.value],
        "ai_analysis_jobs": jobs,
        "ai_analysis_jobs_pending": jobs[AIJobStatus.PENDING.value],
        "ai_analysis_jobs_running": jobs[AIJobStatus.RUNNING.value],
        "ai_analysis_jobs_success": jobs[AIJobStatus.SUCCESS.value],
        "ai_analysis_jobs_partial": jobs[AIJobStatus.PARTIAL_SUCCESS.value],
        "ai_analysis_jobs_retry": jobs[AIJobStatus.RETRY.value],
        "ai_analysis_jobs_failed": jobs[AIJobStatus.FAILED.value],
        "ai_analysis_jobs_blocked": jobs[AIJobStatus.BLOCKED.value],
        "ai_requirements_generated": n_req,
        "ai_ambiguities": int(ambiguities),
        "ai_conflict_flags": flag_counts.get(FlagType.AI_DETERMINISTIC_CONFLICT.value, 0)
        + flag_counts.get(FlagType.CONTRADICTORY_REQUIREMENT.value, 0),
        "ai_review_flags": sum(flag_counts.values()),
        "ai_flags_by_type": flag_counts,
    }
