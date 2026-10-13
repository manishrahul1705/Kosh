"""Stage 3C AI-analysis API (interpretation of tender requirements - never seller eligibility).

ROUTE ORDER: all static paths (/jobs, /worker, /bid/..., /stage3b/...) are declared
before the dynamic /{analysis_id} routes; a behavioural test checks every static GET path.
Queue endpoints only queue: no request ever calls an AI provider synchronously.
No endpoint returns credentials.
"""

from __future__ import annotations

import json
import math
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import exists, func, select
from sqlalchemy.orm import Session

from app.ai.constants import CATEGORIES, OBLIGATION_LEVELS, AIJobReason
from app.ai.job_queue import analysis_source_current, enqueue_ai_analysis
from app.api.platform_authorization import require_ai_analysis_operator, require_tender_analysis_reader
from app.api.deps import get_ai_analysis_worker, get_db, get_scheduler
from app.database.models import (
    AIAnalysisFlag,
    AIAnalysisJob,
    AIAnalysisRun,
    AIAnalysisRunSource,
    AIEvidenceChunk,
    AIRequirement,
    AIRequirementEvidence,
    Tender,
    TenderFieldExtraction,
)
from app.services.ai_status import ai_analysis_status
from app.utils.bid_number import InvalidBidNumber, normalize_bid_number
from app.utils.dates import as_aware_utc

router = APIRouter(prefix="/api/ai-analysis", tags=["ai-analysis"])

NOTICE = ("AI-assisted interpretation of the tender text only. Stage 3B deterministic values remain "
          "authoritative; disagreements are flagged, never applied. No seller eligibility is assessed.")


def _iso(dt):
    a = as_aware_utc(dt)
    return a.isoformat() if a else None


def _page(total, page, size):
    return {"total": total, "page": page, "page_size": size, "pages": math.ceil(total / size) if total else 0}


def _source(r: AIAnalysisRun) -> dict:
    return {"tender_id": r.tender_id, "bid_number": r.bid_number, "document_id": r.document_id,
            "document_type": r.document_type, "version_number": r.version_number,
            "document_version_id": r.document_version_id, "stage3a_extraction_id": r.stage3a_extraction_id,
            "stage3b_extraction_id": r.stage3b_extraction_id}


def _run_out(r: AIAnalysisRun) -> dict:
    return {"analysis_scope":r.analysis_scope,"corpus_fingerprint":r.corpus_fingerprint,
            "corpus_completeness":r.corpus_completeness,
            "source_semantics":"legacy anchor only; see corpus sources" if r.analysis_scope=='TENDER_CORPUS' else "document",
            "id": r.id, "status": r.status, "status_code": r.status_code, "is_current": r.is_current,
            "summary": r.summary, "provider": r.provider, "model": r.model, "prompt_version": r.prompt_version,
            "schema_version": r.schema_version, "chunker_version": r.chunker_version,
            "chunks_total": r.chunks_total, "chunks_sent": r.chunks_sent, "input_characters": r.input_characters,
            "requirements_count": r.requirements_count, "rejected_count": r.rejected_count,
            "flags_count": r.flags_count, "ambiguities_count": r.ambiguities_count,
            "conflicts_count": r.conflicts_count,
            "usage": {"input_tokens": r.input_tokens, "output_tokens": r.output_tokens,
                      "total_tokens": r.total_tokens, "finish_reason": r.finish_reason,
                      "provider_attempts": r.provider_attempts, "latency_ms": r.latency_ms},
            "request_sha256": r.request_sha256, "response_sha256": r.response_sha256,
            "started_at": _iso(r.started_at), "completed_at": _iso(r.completed_at), "created_at": _iso(r.created_at),
            "source": _source(r)}


def _mandatory(level: str) -> bool | None:
    return True if level == "MANDATORY" else False if level in ("OPTIONAL", "INFORMATIONAL") else None


def _evidence_out(e: AIRequirementEvidence, chunk: AIEvidenceChunk | None, run: AIAnalysisRun) -> dict:
    return {"id": e.id, "requirement_id": e.requirement_id, "chunk_id": e.chunk_key, "evidence_chunk_db_id": e.chunk_id,
            "quote": e.quote, "page_number": e.page_number, "section_id": e.section_id,
            "section_heading": e.section_heading, "chunk_kind": chunk.kind if chunk else None,
            "source_type": chunk.source_type if chunk else None, "table_id": chunk.table_id if chunk else None,
            "source_text": chunk.text if chunk else None, "document_version_id": chunk.document_version_id if chunk else None,
            "stage3a_extraction_id": chunk.stage3a_extraction_id if chunk else None,
            "stage3b_extraction_id": getattr(chunk,'corpus_stage3b_id',None) if run.analysis_scope=='TENDER_CORPUS' else run.stage3b_extraction_id,
            "document_id":getattr(chunk,'corpus_document_id',run.document_id),
            "document_type":getattr(chunk,'corpus_document_type',run.document_type)}


def _req_out(q: AIRequirement, evidence: list[dict] | None = None) -> dict:
    out = {"id": q.id, "sequence": q.sequence, "requirement_type": q.requirement_type,
           "model_requirement_type": q.model_requirement_type, "category": q.category, "title": q.title,
           "summary": q.summary, "obligation": q.obligation, "obligation_level": q.obligation_level,
           "mandatory": _mandatory(q.obligation_level), "model_obligation_level": q.model_obligation_level,
           "level_adjustment": q.level_adjustment, "condition": q.condition_text, "value": q.value_text,
           "value_number": q.value_number, "unit": q.unit, "applies_to": q.applies_to,
           "risk_flags": json.loads(q.risk_flags_json) if q.risk_flags_json else [], "ambiguity": q.ambiguity,
           "is_buyer_atc": q.is_buyer_atc}
    if evidence is not None:
        out["evidence"] = evidence
    return out


def _flag_out(f: AIAnalysisFlag) -> dict:
    return {"id": f.id, "flag_type": f.flag_type, "severity": f.severity, "message": f.message,
            "requirement_id": f.requirement_id, "stage3b_field_name": f.stage3b_field_name,
            "stage3b_value": f.stage3b_value, "stage3b_evidence_strength": f.stage3b_evidence_strength,
            "ai_value": f.ai_value, "chunk_ids": json.loads(f.chunk_keys_json) if f.chunk_keys_json else []}


def _job_out(j: AIAnalysisJob) -> dict:
    return {"analysis_scope":j.analysis_scope,"tender_id":j.tender_id,"corpus_fingerprint":j.corpus_fingerprint,"id": j.id, "stage3b_extraction_id": j.stage3b_extraction_id, "status": j.status, "reason": j.reason,
            "force": j.force, "attempt_count": j.attempt_count, "next_retry_at": _iso(j.next_retry_at),
            "started_at": _iso(j.started_at), "finished_at": _iso(j.finished_at), "locked_by": j.locked_by,
            "provider": j.provider, "model": j.model, "outcome": j.outcome, "error_code": j.error_code,
            "error_message": j.error_message, "analysis_run_id": j.analysis_run_id, "created_at": _iso(j.created_at)}


def _attach_provenance(db,run,chunks):
    sources={x.document_version_id:x for x in db.scalars(select(AIAnalysisRunSource).where(AIAnalysisRunSource.analysis_run_id==run.id))}
    for c in chunks:
        source=sources.get(c.document_version_id)
        if source:
            c.corpus_stage3b_id=source.stage3b_extraction_id
            c.corpus_document_id=source.document_id
            c.corpus_document_type=source.document_type


def _requirements_with_evidence(db: Session, run: AIAnalysisRun) -> list[dict]:
    reqs = db.scalars(select(AIRequirement).where(AIRequirement.analysis_run_id == run.id)
                      .order_by(AIRequirement.sequence)).all()
    chunks = {c.id: c for c in db.scalars(select(AIEvidenceChunk).where(AIEvidenceChunk.analysis_run_id == run.id))}
    _attach_provenance(db,run,chunks.values())
    ev: dict[int, list[dict]] = {}
    for e in db.scalars(select(AIRequirementEvidence).where(AIRequirementEvidence.analysis_run_id == run.id)
                        .order_by(AIRequirementEvidence.id)):
        ev.setdefault(e.requirement_id, []).append(_evidence_out(e, chunks.get(e.chunk_id), run))
    return [_req_out(q, ev.get(q.id, [])) for q in reqs]


def _flags(db: Session, run_id: int) -> list[AIAnalysisFlag]:
    return list(db.scalars(select(AIAnalysisFlag).where(AIAnalysisFlag.analysis_run_id == run_id)
                           .order_by(AIAnalysisFlag.id)).all())


def _outputs(reqs: list[dict], flags: list[AIAnalysisFlag]) -> dict:
    """The 13 requested views, all derived from validated rows (every item carries evidence)."""
    by_cat = {c: [r for r in reqs if r["category"] == c] for c in CATEGORIES}
    fl = [_flag_out(f) for f in flags]
    return {
        "important_atc_clauses": [r for r in reqs if r["is_buyer_atc"]],
        "mandatory_requirements": [r for r in reqs if r["obligation_level"] == "MANDATORY"],
        "conditional_requirements": [r for r in reqs if r["obligation_level"] == "CONDITIONAL"],
        "document_certificate_obligations": by_cat["DOCUMENTS"],
        "eligibility_criteria_stated": by_cat["ELIGIBILITY"],
        "technical_obligations": by_cat["TECHNICAL"],
        "commercial_obligations": by_cat["COMMERCIAL"],
        "delivery_warranty_obligations": by_cat["DELIVERY_WARRANTY"],
        "compliance_obligations": by_cat["COMPLIANCE"],
        "unusual_restrictive_clauses": [r for r in reqs if r["risk_flags"]],
        "ambiguities": [r for r in reqs if r["ambiguity"] or r["obligation_level"] == "UNKNOWN"]
        + [f for f in fl if f["flag_type"] in ("AMBIGUOUS_ATC", "REVIEW_REQUIRED") and f["requirement_id"] is None],
        "deterministic_disagreements": [f for f in fl if f["flag_type"] in ("AI_DETERMINISTIC_CONFLICT",
                                                                           "CONTRADICTORY_REQUIREMENT")],
    }


# ===========================================================================
# Static routes (keep above /{analysis_id})
# ===========================================================================
@router.get("", response_model=dict, dependencies=[Depends(require_tender_analysis_reader)])
def list_analyses(
    bid_number: Optional[str] = Query(None),
    tender_id: Optional[int] = Query(None),
    stage3b_extraction_id: Optional[int] = Query(None),
    status: Optional[str] = Query(None, description="SUCCESS | PARTIAL_SUCCESS"),
    provider: Optional[str] = Query(None),
    model: Optional[str] = Query(None),
    current_only: bool = Query(True, description="current DOCUMENT analyses only; use /api/corpus/{tender_id} for live corpus currentness"),
    flag_type: Optional[str] = Query(None, description="only runs having this flag (e.g. AI_DETERMINISTIC_CONFLICT)"),
    requirement_type: Optional[str] = Query(None, description="only runs having this requirement type"),
    obligation_level: Optional[str] = Query(None, description="with requirement_type: its level"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> dict:
    stmt = select(AIAnalysisRun)
    if bid_number:
        try:
            stmt = stmt.where(AIAnalysisRun.bid_number == normalize_bid_number(bid_number))
        except InvalidBidNumber as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    if tender_id is not None:
        stmt = stmt.where(AIAnalysisRun.tender_id == tender_id)
    if stage3b_extraction_id is not None:
        stmt = stmt.where(AIAnalysisRun.stage3b_extraction_id == stage3b_extraction_id)
    if status:
        stmt = stmt.where(AIAnalysisRun.status == status)
    if provider:
        stmt = stmt.where(AIAnalysisRun.provider == provider)
    if model:
        stmt = stmt.where(AIAnalysisRun.model == model)
    if current_only:
        stmt = stmt.where(analysis_source_current())
    if flag_type:
        stmt = stmt.where(exists().where(AIAnalysisFlag.analysis_run_id == AIAnalysisRun.id,
                                         AIAnalysisFlag.flag_type == flag_type.upper()))
    if obligation_level and obligation_level.upper() not in OBLIGATION_LEVELS:
        raise HTTPException(status_code=422, detail=f"obligation_level must be one of {', '.join(OBLIGATION_LEVELS)}")
    if requirement_type or obligation_level:
        conds = [AIRequirement.analysis_run_id == AIAnalysisRun.id]
        if requirement_type:
            conds.append(AIRequirement.requirement_type == requirement_type.upper())
        if obligation_level:
            conds.append(AIRequirement.obligation_level == obligation_level.upper())
        stmt = stmt.where(exists().where(*conds))
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    rows = db.scalars(stmt.order_by(AIAnalysisRun.id.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    return {"items": [_run_out(r) for r in rows], **_page(total, page, page_size), "notice": NOTICE}


@router.get("/jobs", response_model=dict, dependencies=[Depends(require_ai_analysis_operator)])
def list_jobs(status: Optional[str] = Query(None), stage3b_extraction_id: Optional[int] = Query(None),
              page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
              db: Session = Depends(get_db)) -> dict:
    stmt = select(AIAnalysisJob)
    if status:
        stmt = stmt.where(AIAnalysisJob.status == status)
    if stage3b_extraction_id is not None:
        stmt = stmt.where(AIAnalysisJob.stage3b_extraction_id == stage3b_extraction_id)
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    rows = db.scalars(stmt.order_by(AIAnalysisJob.updated_at.desc(), AIAnalysisJob.id.desc())
                      .offset((page - 1) * page_size).limit(page_size)).all()
    return {"items": [_job_out(j) for j in rows], **_page(total, page, page_size)}


@router.get("/jobs/{job_id}", response_model=dict, dependencies=[Depends(require_ai_analysis_operator)])
def get_job(job_id: int, db: Session = Depends(get_db)) -> dict:
    j = db.get(AIAnalysisJob, job_id)
    if j is None:
        raise HTTPException(status_code=404, detail="AI analysis job not found")
    return _job_out(j)


@router.get("/worker", response_model=dict, dependencies=[Depends(require_ai_analysis_operator)])
def worker_status(request: Request, db: Session = Depends(get_db), worker=Depends(get_ai_analysis_worker),
                  scheduler=Depends(get_scheduler)) -> dict:
    return ai_analysis_status(db, worker, scheduler, settings=getattr(worker, "settings", None)
                              or request.app.state.settings)


@router.get("/bid/{bid_number:path}", response_model=dict, dependencies=[Depends(require_tender_analysis_reader)])
def by_bid(bid_number: str, db: Session = Depends(get_db)) -> dict:
    """Current analyses of every document version of a bid (documents are not merged)."""
    try:
        bid = normalize_bid_number(bid_number)
    except InvalidBidNumber as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if db.scalar(select(Tender.id).where(Tender.bid_number == bid)) is None:
        raise HTTPException(status_code=404, detail="Tender not found")
    runs = db.scalars(select(AIAnalysisRun).where(AIAnalysisRun.bid_number == bid, analysis_source_current())
                      .order_by(AIAnalysisRun.document_id, AIAnalysisRun.version_number.desc(),
                                AIAnalysisRun.id.desc())).all()
    seen: set[int] = set()
    items = []
    for r in runs:
        item = _run_out(r)
        item["is_latest_version"] = r.document_id not in seen
        seen.add(r.document_id)
        items.append(item)
    return {"bid_number": bid, "precedence": "per document: newest version first; documents are not merged",
            "items": items, "notice": NOTICE}


@router.get("/stage3b/{stage3b_extraction_id}", response_model=dict, dependencies=[Depends(require_tender_analysis_reader)])
def by_stage3b(stage3b_extraction_id: int, db: Session = Depends(get_db)) -> dict:
    if db.get(TenderFieldExtraction, stage3b_extraction_id) is None:
        raise HTTPException(status_code=404, detail="Stage 3B field extraction not found")
    runs = db.scalars(select(AIAnalysisRun).where(AIAnalysisRun.stage3b_extraction_id == stage3b_extraction_id)
                      .order_by(AIAnalysisRun.id.desc())).all()
    current = [_run_out(r) for r in runs if r.is_current]
    if not runs:
        raise HTTPException(status_code=404, detail="No AI analysis for this Stage 3B run")
    return {"current": current, "history": [{"id": r.id, "status": r.status, "is_current": r.is_current,
                                             "provider": r.provider, "model": r.model,
                                             "prompt_version": r.prompt_version, "schema_version": r.schema_version,
                                             "created_at": _iso(r.created_at)} for r in runs],
            "notice": NOTICE}


def _queue(request: Request, db: Session, stage3b_extraction_id: int, force: bool) -> dict:
    if db.get(TenderFieldExtraction, stage3b_extraction_id) is None:
        raise HTTPException(status_code=404, detail="Stage 3B field extraction not found")
    res = enqueue_ai_analysis(db, stage3b_extraction_id, AIJobReason.REANALYZE if force else AIJobReason.MANUAL,
                              request.app.state.settings, force=force)
    db.commit()
    if res.skipped_reason == "not_ready":
        raise HTTPException(status_code=409, detail="Stage 3B run is not current/usable or its Stage 3A "
                                                    "extraction is not usable")
    return {"queued": res.created, "job_id": res.job_id, "reason": res.skipped_reason,
            "status": res.job.status if res.job is not None else None, "force": force,
            "note": "Queued only. Processing needs the AI worker (AI_ANALYSIS_WORKER_ENABLED) or the CLI."}


@router.post("/stage3b/{stage3b_extraction_id}/queue", response_model=dict, dependencies=[Depends(require_ai_analysis_operator)])
def queue(stage3b_extraction_id: int, request: Request, db: Session = Depends(get_db)) -> dict:
    return _queue(request, db, stage3b_extraction_id, False)


@router.post("/stage3b/{stage3b_extraction_id}/reanalyze", response_model=dict, dependencies=[Depends(require_ai_analysis_operator)])
def reanalyze(stage3b_extraction_id: int, request: Request, db: Session = Depends(get_db)) -> dict:
    return _queue(request, db, stage3b_extraction_id, True)


# ===========================================================================
# Dynamic /{analysis_id} routes (keep LAST)
# ===========================================================================
def _run(db: Session, analysis_id: int) -> AIAnalysisRun:
    r = db.get(AIAnalysisRun, analysis_id)
    if r is None:
        raise HTTPException(status_code=404, detail="AI analysis not found")
    return r


@router.get("/{analysis_id}", response_model=dict, dependencies=[Depends(require_tender_analysis_reader)])
def get_analysis(analysis_id: int, db: Session = Depends(get_db)) -> dict:
    r = _run(db, analysis_id)
    reqs = _requirements_with_evidence(db, r)
    flags = _flags(db, r.id)
    current_for_corpus=None
    if r.analysis_scope=='TENDER_CORPUS':
        from app.corpus.service import build_corpus
        from app.corpus.analysis import CORPUS_PROMPT_VERSION
        current_for_corpus=r.is_current and r.prompt_version==CORPUS_PROMPT_VERSION and r.corpus_fingerprint==build_corpus(db,r.tender_id)['fingerprint']
    return {**_run_out(r), "current_for_corpus":current_for_corpus, "corpus_snapshot":json.loads(r.corpus_snapshot_json) if r.corpus_snapshot_json else None,
            "requirements": reqs, "flags": [_flag_out(f) for f in flags],
            "outputs": _outputs(reqs, flags),
            "rejected": json.loads(r.rejected_json) if r.rejected_json else [], "notice": NOTICE}


@router.get("/{analysis_id}/requirements", response_model=dict, dependencies=[Depends(require_tender_analysis_reader)])
def get_requirements(analysis_id: int, requirement_type: Optional[str] = Query(None),
                     obligation_level: Optional[str] = Query(None), category: Optional[str] = Query(None),
                     atc_only: bool = Query(False), db: Session = Depends(get_db)) -> dict:
    r = _run(db, analysis_id)
    reqs = [q for q in _requirements_with_evidence(db, r)
            if (requirement_type is None or q["requirement_type"] == requirement_type.upper())
            and (obligation_level is None or q["obligation_level"] == obligation_level.upper())
            and (category is None or q["category"] == category.upper())
            and (not atc_only or q["is_buyer_atc"])]
    return {"analysis_id": r.id, "source": _source(r), "items": reqs, "notice": NOTICE}


@router.get("/{analysis_id}/evidence", response_model=dict, dependencies=[Depends(require_tender_analysis_reader)])
def get_evidence(analysis_id: int, requirement_id: Optional[int] = Query(None),
                 include_chunks: bool = Query(False, description="also list every chunk built (sent or excluded)"),
                 db: Session = Depends(get_db)) -> dict:
    r = _run(db, analysis_id)
    chunks = list(db.scalars(select(AIEvidenceChunk).where(AIEvidenceChunk.analysis_run_id == r.id)
                             .order_by(AIEvidenceChunk.sequence)).all())
    _attach_provenance(db,r,chunks)
    by_id = {c.id: c for c in chunks}
    stmt = select(AIRequirementEvidence).where(AIRequirementEvidence.analysis_run_id == r.id)
    if requirement_id is not None:
        stmt = stmt.where(AIRequirementEvidence.requirement_id == requirement_id)
    items = [_evidence_out(e, by_id.get(e.chunk_id), r) for e in db.scalars(stmt.order_by(AIRequirementEvidence.id))]
    out = {"analysis_id": r.id, "source": _source(r), "items": items}
    if include_chunks:
        out["chunks"] = [{"chunk_id": c.chunk_key, "kind": c.kind, "source_type": c.source_type,
                          "page_number": c.page_number, "page_end": c.page_end, "section_id": c.section_id,
                          "section_heading": c.section_heading, "table_id": c.table_id, "char_count": c.char_count,
                          "sent": c.sent, "exclusion_reason": c.exclusion_reason, "text": c.text} for c in chunks]
    return out


@router.get("/{analysis_id}/flags", response_model=dict, dependencies=[Depends(require_tender_analysis_reader)])
def get_flags(analysis_id: int, flag_type: Optional[str] = Query(None), severity: Optional[str] = Query(None),
              db: Session = Depends(get_db)) -> dict:
    r = _run(db, analysis_id)
    flags = [f for f in _flags(db, r.id) if (flag_type is None or f.flag_type == flag_type.upper())
             and (severity is None or f.severity == severity.upper())]
    return {"analysis_id": r.id, "source": _source(r), "items": [_flag_out(f) for f in flags],
            "note": "Stage 3B values are never changed by Stage 3C; flags are for human review."}
