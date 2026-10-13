"""Read-only corpus visibility and explicit queue action (never downloads or calls AI)."""

import json
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from app.api.deps import get_db
from app.api.platform_authorization import require_ai_analysis_operator, require_tender_analysis_reader
from app.database.models import Tender, AIAnalysisRun
from app.corpus.service import build_corpus
from app.corpus.queue import enqueue_corpus

router = APIRouter(prefix="/api/corpus", tags=["corpus"])


@router.get("/{tender_id}")
def inspect_corpus(tender_id: int, db=Depends(get_db), _reader=Depends(require_tender_analysis_reader)):
    if db.get(Tender, tender_id) is None:
        raise HTTPException(404, "Tender not found")
    from app.corpus.analysis import CORPUS_PROMPT_VERSION
    corpus = build_corpus(db, tender_id)
    runs = list(
        db.scalars(
            select(AIAnalysisRun)
            .where(
                AIAnalysisRun.tender_id == tender_id,
                AIAnalysisRun.analysis_scope == "TENDER_CORPUS",
            )
            .order_by(AIAnalysisRun.id.desc())
        )
    )
    corpus["analyses"] = [
        {
            "id": r.id,
            "fingerprint": r.corpus_fingerprint,
            "current_for_corpus": r.is_current
            and r.corpus_fingerprint == corpus["fingerprint"]
            and r.prompt_version == CORPUS_PROMPT_VERSION,
            "status": r.status,
            "completeness": r.corpus_completeness,
            "provider": r.provider,
            "model": r.model,
        }
        for r in runs
    ]
    return corpus


@router.post("/{tender_id}/queue")
def queue_corpus(
    tender_id: int, request: Request, force: bool = False, db=Depends(get_db),
    _operator=Depends(require_ai_analysis_operator),
):
    if db.get(Tender, tender_id) is None:
        raise HTTPException(404, "Tender not found")
    result = enqueue_corpus(
        db, tender_id, request.app.state.settings, force=force, reason="MANUAL"
    )
    db.commit()
    return {
        "queued": result.created,
        "job_id": result.job_id,
        "reason": result.skipped_reason,
        "analysis_scope": "TENDER_CORPUS",
    }
