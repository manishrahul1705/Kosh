from __future__ import annotations

import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.database.session import check_database
from app.services.ai_status import ai_analysis_status
from app.services.extraction_status import extraction_status
from app.services.field_status import field_extraction_status
from app.services.job_status import document_worker_status

logger = logging.getLogger("app.api.health")
router = APIRouter(tags=["health"])

_HEALTH_WORKER_KEYS = (
    "document_worker_enabled",
    "document_worker_running",
    "document_scheduler_running",
    "next_document_worker_run",
    "pending_jobs",
    "running_jobs",
    "retry_jobs",
    "failed_jobs",
    "blocked_jobs",
    "stale_running_jobs",
    "oldest_pending_job_at",
    "last_successful_document_processing_at",
    "last_document_worker_run_at",
    "last_document_refresh_check_at",
    "last_document_refresh_at",
    "blocked_cooldown_until",
)


_HEALTH_EXTRACTION_KEYS = (
    "extraction_worker_enabled",
    "extraction_worker_running",
    "extraction_scheduler_running",
    "next_extraction_worker_run",
    "current_extraction_job_id",
    "last_extraction_outcome",
    "extraction_jobs_pending",
    "extraction_jobs_running",
    "extraction_jobs_retry",
    "extraction_jobs_failed",
    "document_versions_without_extraction",
    "document_versions_unqueued",
)


_HEALTH_FIELD_KEYS = (
    "field_extraction_worker_enabled",
    "field_extraction_worker_running",
    "field_extraction_scheduler_running",
    "current_field_extraction_job_id",
    "last_field_extraction_outcome",
    "stage3a_extractions_eligible",
    "stage3a_extractions_unqueued",
    "field_extraction_jobs_pending",
    "field_extraction_jobs_running",
    "field_extraction_jobs_retry",
    "field_extraction_jobs_failed",
    "fields_extracted",
    "fields_unknown",
    "fields_conflicted",
)


_HEALTH_AI_KEYS = (
    "ai_provider_configured",
    "ai_provider",
    "ai_model",
    "ai_analysis_worker_enabled",
    "ai_analysis_worker_running",
    "ai_analysis_scheduler_running",
    "current_ai_analysis_job_id",
    "last_ai_analysis_outcome",
    "ai_blocked_until",
    "stage3b_runs_unqueued",
    "ai_analysis_jobs_pending",
    "ai_analysis_jobs_running",
    "ai_analysis_jobs_success",
    "ai_analysis_jobs_partial",
    "ai_analysis_jobs_retry",
    "ai_analysis_jobs_failed",
    "ai_analysis_jobs_blocked",
    "ai_requirements_generated",
    "ai_ambiguities",
    "ai_conflict_flags",
    "ai_review_flags",
)


@router.get("/health")
def health(request: Request) -> JSONResponse:
    db_ok = check_database(request.app.state.session_factory)
    scheduler = request.app.state.scheduler
    if scheduler is None:
        sched_state = "disabled"
    elif getattr(scheduler, "standby", False):
        sched_state = "standby"  # another process on this host owns the scheduler
    else:
        sched_state = "running" if scheduler.running else "stopped"
    body = {
        "status": "healthy" if db_ok else "unhealthy",
        "database": "connected" if db_ok else "unavailable",
        "scheduler": sched_state,
        "next_scheduled_run": scheduler.next_run_time() if scheduler is not None else None,
    }
    worker = getattr(request.app.state, "document_worker", None)
    if db_ok and worker is not None:
        try:
            with request.app.state.session_factory() as s:
                full = document_worker_status(s, worker, scheduler)
            body["document_worker"] = {k: full[k] for k in _HEALTH_WORKER_KEYS}
        except Exception:  # health must never fail because of Stage 2B metrics
            logger.exception("document_worker_health_failed")
            body["document_worker"] = None
    extraction_worker = getattr(request.app.state, "extraction_worker", None)
    if db_ok and extraction_worker is not None:
        try:
            with request.app.state.session_factory() as s:
                ex = extraction_status(s, extraction_worker, scheduler)
            body["extraction_worker"] = {k: ex[k] for k in _HEALTH_EXTRACTION_KEYS}
        except Exception:  # health must never fail because of Stage 3A metrics
            logger.exception("extraction_worker_health_failed")
            body["extraction_worker"] = None
    field_worker = getattr(request.app.state, "field_extraction_worker", None)
    if db_ok and field_worker is not None:
        try:
            with request.app.state.session_factory() as s:
                fx = field_extraction_status(s, field_worker, scheduler)
            body["field_extraction_worker"] = {k: fx[k] for k in _HEALTH_FIELD_KEYS}
        except Exception:  # health must never fail because of Stage 3B metrics
            logger.exception("field_extraction_health_failed")
            body["field_extraction_worker"] = None
    ai_worker = getattr(request.app.state, "ai_analysis_worker", None)
    if db_ok and ai_worker is not None:
        try:
            with request.app.state.session_factory() as s:
                ai = ai_analysis_status(s, ai_worker, scheduler)
            body["ai_analysis_worker"] = {k: ai[k] for k in _HEALTH_AI_KEYS}
        except Exception:  # health must never fail because of Stage 3C metrics
            logger.exception("ai_analysis_health_failed")
            body["ai_analysis_worker"] = None
    return JSONResponse(body, status_code=200 if db_ok else 503)
