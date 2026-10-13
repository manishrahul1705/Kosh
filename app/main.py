"""FastAPI application factory.

Run:  uvicorn app.main:app --reload   ->  http://localhost:8000/docs
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session, sessionmaker

from app.ai.job_worker import AIAnalysisJobWorker
from app.api import business_documents, cash, consents, ai_analysis, collection, corpus, dev_login, documents, eligibility, extractions, health, portal, sellers, stats, tender_fields, tenders, user_provisioning
import app.database.auth_models  # noqa: F401  (register ORM tables)
import app.database.matching_models  # noqa: F401
import app.database.kosh_models  # noqa: F401
import app.database.platform_auth_models  # noqa: F401
from app.collectors.base import Collector
from app.collectors.gem_collector import build_collector
from app.core.config import Settings, get_settings
from app.core.logging import log_event, setup_logging
from app.database.session import build_engine, build_session_factory, check_schema_revision, run_migrations
from app.documents.job_worker import DocumentJobWorker
from app.extraction.job_worker import ExtractionJobWorker
from app.fields.job_worker import FieldExtractionJobWorker
from app.scheduler.scheduler import CollectionScheduler
from app.services.discovery_service import CollectionRunner

logger = logging.getLogger("app.main")


def create_app(
    settings: Settings | None = None,
    *,
    session_factory: sessionmaker[Session] | None = None,
    collector_factory: Callable[[], Collector] | None = None,
    document_worker: DocumentJobWorker | None = None,
    extraction_worker: ExtractionJobWorker | None = None,
    field_extraction_worker: FieldExtractionJobWorker | None = None,
    ai_analysis_worker: AIAnalysisJobWorker | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    settings.assert_startup_safe()  # model_copy() skips validators, so enforce here too
    setup_logging(settings.log_level, settings.log_format)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        db_url = settings.resolved_database_url
        if not settings.auto_migrate and app.state.owns_engine:
            check_schema_revision(db_url)
        if settings.auto_migrate and app.state.owns_engine:
            run_migrations(db_url)
            log_event(logger, logging.INFO, "database_migrated", url=_safe_url(db_url))
        runner: CollectionRunner = app.state.runner
        worker: DocumentJobWorker = app.state.document_worker
        if settings.startup_recovery_enabled:
            runner.recover_interrupted_runs()
            try:
                # Restart recovery: RUNNING jobs orphaned by a crash become eligible again.
                worker.recover_stale_jobs()
            except Exception:  # never block startup on recovery
                logger.exception("document_job_recovery_failed")
            try:
                app.state.extraction_worker.recover_stale_jobs()  # Stage 3A restart recovery
            except Exception:
                logger.exception("extraction_job_recovery_failed")
            try:
                app.state.field_extraction_worker.recover_stale_jobs()  # Stage 3B restart recovery
            except Exception:
                logger.exception("field_extraction_job_recovery_failed")
            try:
                app.state.ai_analysis_worker.recover_stale_jobs()  # Stage 3C restart recovery (no provider call)
            except Exception:
                logger.exception("ai_analysis_job_recovery_failed")
        else:
            log_event(logger, logging.INFO, "startup_recovery_skipped", scope="all")
        if settings.scheduler_enabled:
            app.state.scheduler = CollectionScheduler(settings, runner, document_worker=worker,
                                                      extraction_worker=app.state.extraction_worker,
                                                      field_extraction_worker=app.state.field_extraction_worker,
                                                      ai_analysis_worker=app.state.ai_analysis_worker)
            app.state.scheduler.start()
        log_event(logger, logging.INFO, "app_started", env=settings.app_env,
                  collector_mode=settings.collector_mode.value,
                  scheduler="enabled" if settings.scheduler_enabled else "disabled",
                  document_worker="enabled" if settings.document_worker_enabled else "disabled",
                  extraction_worker="enabled" if settings.extraction_worker_enabled else "disabled",
                  field_extraction_worker="enabled" if settings.field_extraction_worker_enabled else "disabled",
                  ai_analysis_worker="enabled" if settings.ai_analysis_worker_enabled else "disabled")
        try:
            yield
        finally:
            if app.state.scheduler is not None:
                app.state.scheduler.shutdown()
            if app.state.owns_engine:
                app.state.engine.dispose()
            log_event(logger, logging.INFO, "app_stopped")

    app = FastAPI(
        title="GeM Tender Intelligence",
        version="1.0.0",
        description=("GeM tender discovery, document collection, evidence-grounded tender understanding, "
                     "deterministic status tracking, automatic seller matching and a per-client portal."),
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.scheduler = None
    if session_factory is None:
        engine = build_engine(settings.resolved_database_url,
                              read_only=settings.app_startup_mode == "verify")
        session_factory = build_session_factory(engine)
        app.state.engine = engine
        app.state.owns_engine = True
    else:
        app.state.engine = session_factory.kw.get("bind")
        app.state.owns_engine = False
    app.state.session_factory = session_factory
    app.state.runner = CollectionRunner(
        settings, session_factory, collector_factory or (lambda: build_collector(settings))
    )
    app.state.document_worker = document_worker or DocumentJobWorker(settings, session_factory)
    app.state.extraction_worker = extraction_worker or ExtractionJobWorker(settings, session_factory)
    app.state.field_extraction_worker = field_extraction_worker or FieldExtractionJobWorker(settings, session_factory)
    # Stage 3C: built without contacting any provider; processing only if AI_ANALYSIS_WORKER_ENABLED=true
    app.state.ai_analysis_worker = ai_analysis_worker or AIAnalysisJobWorker(settings, session_factory)

    app.include_router(health.router)
    app.include_router(tenders.router)
    app.include_router(collection.router)
    app.include_router(stats.router)
    app.include_router(documents.router)
    app.include_router(extractions.router)
    app.include_router(tender_fields.router)
    app.include_router(ai_analysis.router)
    app.include_router(eligibility.router)
    app.include_router(sellers.router)
    app.include_router(user_provisioning.router)
    app.include_router(corpus.router)
    app.include_router(portal.router)
    app.include_router(business_documents.router)
    app.include_router(cash.router)
    from app.api import financing
    app.include_router(financing.router)
    from app.api import policy
    app.include_router(policy.router)
    from app.api import actions
    app.include_router(actions.router)
    app.include_router(consents.router)
    dev_login.install(app, settings)  # no-op unless DEV_LOGIN_ENABLED=true (never in production)

    @app.get("/", include_in_schema=False)
    def root() -> RedirectResponse:
        return RedirectResponse("/docs")

    return app


def _safe_url(url: str) -> str:
    """Hide credentials when logging a database URL."""
    if "@" in url and "://" in url:
        scheme, rest = url.split("://", 1)
        return f"{scheme}://***@{rest.split('@', 1)[1]}"
    return url


app = create_app()

