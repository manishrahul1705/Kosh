"""Idempotent corpus queue. Terminal failure requires explicit retry; no queue loop."""

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from app.database.models import AIAnalysisJob, TenderFieldExtraction
from app.ai.job_queue import AIEnqueueResult
from app.ai.constants import SCHEMA_VERSION
from app.ai.providers import effective_model, effective_provider
from app.corpus.analysis import CORPUS_PROMPT_VERSION, current_corpus_analysis
from app.corpus.service import build_corpus, canonical


def enqueue_corpus(
    s, tender_id, settings, *, force=False, reason="CORPUS_CHANGED", dry_run=False
):
    corpus = build_corpus(s, tender_id)
    usable = [d for d in corpus["documents"] if d["usable"]]
    if not usable:
        return AIEnqueueResult(False, None, "not_ready")
    provider, model = effective_provider(settings), effective_model(settings)
    conditions = (
        AIAnalysisJob.analysis_scope == "TENDER_CORPUS",
        AIAnalysisJob.tender_id == tender_id,
        AIAnalysisJob.corpus_fingerprint == corpus["fingerprint"],
        AIAnalysisJob.provider == provider,
        AIAnalysisJob.model == model,
        AIAnalysisJob.prompt_version == CORPUS_PROMPT_VERSION,
        AIAnalysisJob.schema_version == SCHEMA_VERSION,
    )
    existing = s.scalar(
        select(AIAnalysisJob)
        .where(*conditions)
        .order_by(AIAnalysisJob.id.desc())
        .limit(1)
    )
    if existing and (not force or existing.status in {"PENDING", "RETRY", "RUNNING"}):
        return AIEnqueueResult(
            False,
            existing,
            "already_queued"
            if existing.status in {"PENDING", "RETRY", "RUNNING"}
            else "already_attempted",
        )
    if not force and current_corpus_analysis(
        s, tender_id, corpus["fingerprint"], provider, model
    ):
        return AIEnqueueResult(False, None, "already_analyzed")
    if dry_run:
        return AIEnqueueResult(True, None, None)
    job = AIAnalysisJob(
        stage3b_extraction_id=usable[0]["stage3b_extraction_id"],
        tender_id=tender_id,
        analysis_scope="TENDER_CORPUS",
        corpus_fingerprint=corpus["fingerprint"],
        corpus_snapshot_json=canonical(corpus),
        provider=provider,
        model=model,
        prompt_version=CORPUS_PROMPT_VERSION,
        schema_version=SCHEMA_VERSION,
        status="PENDING",
        reason=reason,
        force=force,
        attempt_count=0,
    )
    try:
        with s.begin_nested():
            s.add(job)
            s.flush()
    except IntegrityError:
        return AIEnqueueResult(
            False,
            s.scalar(
                select(AIAnalysisJob)
                .where(*conditions)
                .order_by(AIAnalysisJob.id.desc())
                .limit(1)
            ),
            "already_queued",
        )
    return AIEnqueueResult(True, job)


def queue_tender_after_commit(s, tender_id, settings):
    if not settings.ai_analysis_auto_queue:
        return
    try:
        from app.database.session import reserve_sqlite_writer
        reserve_sqlite_writer(s)
        enqueue_corpus(s, tender_id, settings)
        s.commit()
    except Exception:
        s.rollback()
        import logging

        logging.getLogger(__name__).exception(
            "corpus_queue_failed tender_id=%s", tender_id
        )
