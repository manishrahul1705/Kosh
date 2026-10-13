"""Stage 3B tender-field API (structured retrieval only - no ranking/recommendation).

ROUTE ORDER: all static paths (/jobs, /worker, /bid/..., /extraction/...) are
declared before the dynamic /{field_extraction_id} routes; a behavioural test
checks every static GET path.
"""

from __future__ import annotations

import json
import math
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, exists, func, select
from sqlalchemy.orm import Session

from app.api.platform_authorization import require_tender_fields_operator, require_tender_analysis_reader
from app.api.deps import get_db, get_field_extraction_worker, get_scheduler
from app.database.models import (
    DocumentExtraction,
    FieldExtractionJob,
    Tender,
    TenderFieldEvidence,
    TenderFieldExtraction,
    TenderFieldValue,
)
from app.fields.constants import FIELD_EXTRACTOR_VERSION, FieldJobReason, FieldStatus
from app.fields.job_queue import enqueue_field_extraction
from app.fields.registry import BY_NAME
from app.services.field_status import field_extraction_status
from app.utils.bid_number import InvalidBidNumber, normalize_bid_number
from app.utils.dates import as_aware_utc

router = APIRouter(prefix="/api/tender-fields", tags=["tender-fields"])

TRI = ("TRUE", "FALSE", "UNKNOWN")
# Convenience tri-state filters -> registry field names
TRI_FILTERS = {
    "emd_required": "emd_required",
    "mse_relaxation": "mse_experience_turnover_relaxation",
    "startup_relaxation": "startup_experience_turnover_relaxation",
    "oem_authorization_required": "oem_authorization_required",
    "inspection_required": "inspection_required",
}


def _iso(dt):
    a = as_aware_utc(dt)
    return a.isoformat() if a else None


def _page(total, page, size):
    return {"total": total, "page": page, "page_size": size, "pages": math.ceil(total / size) if total else 0}


def _value_out(v: TenderFieldValue) -> dict:
    return {"field_name": v.field_name, "field_group": v.field_group, "value_type": v.value_type,
            "status": v.status, "reason": v.reason, "tri_state": v.tri_state, "value_text": v.value_text,
            "value_number": v.value_number, "value": json.loads(v.value_json) if v.value_json else None,
            "unit": v.unit, "evidence_strength": v.evidence_strength, "candidate_count": v.candidate_count}


def _evidence_out(e: TenderFieldEvidence) -> dict:
    return {"id": e.id, "field_name": e.field_name, "disposition": e.disposition, "evidence_type": e.evidence_type,
            "strength": e.strength, "rule": e.rule, "page_number": e.page_number, "table_id": e.table_id,
            "table_index": e.table_index, "row_index": e.row_index, "section_id": e.section_id,
            "section_heading": e.section_heading, "source_label": e.source_label, "raw_value": e.raw_value,
            "source_text": e.source_text,
            "normalized": json.loads(e.normalized_json) if e.normalized_json else None,
            "stage3a_extraction_id": e.stage3a_extraction_id, "document_version_id": e.document_version_id}


def _run_out(r: TenderFieldExtraction, values: list[TenderFieldValue] | None = None) -> dict:
    out = {"id": r.id, "status": r.status, "is_current": r.is_current, "extractor_name": r.extractor_name,
           "extractor_version": r.extractor_version, "fields_total": r.fields_total,
           "fields_resolved": r.fields_resolved, "fields_unknown": r.fields_unknown,
           "fields_conflict": r.fields_conflict, "candidates_total": r.candidates_total,
           "error_code": r.error_code, "duration_ms": r.duration_ms, "completed_at": _iso(r.completed_at),
           "created_at": _iso(r.created_at),
           "source": {"tender_id": r.tender_id, "bid_number": r.bid_number, "document_id": r.document_id,
                      "document_type": r.document_type, "version_number": r.version_number,
                      "document_version_id": r.document_version_id,
                      "stage3a_extraction_id": r.stage3a_extraction_id}}
    if values is not None:
        out["fields"] = {v.field_name: {"status": v.status, "value_text": v.value_text, "tri_state": v.tri_state,
                                        "unit": v.unit, "reason": v.reason, "strength": v.evidence_strength}
                         for v in values}
    return out


def _job_out(j: FieldExtractionJob) -> dict:
    return {"id": j.id, "stage3a_extraction_id": j.stage3a_extraction_id, "status": j.status, "reason": j.reason,
            "force": j.force, "attempt_count": j.attempt_count, "next_retry_at": _iso(j.next_retry_at),
            "started_at": _iso(j.started_at), "finished_at": _iso(j.finished_at), "locked_by": j.locked_by,
            "outcome": j.outcome, "error_code": j.error_code, "error_message": j.error_message,
            "field_extraction_id": j.field_extraction_id, "created_at": _iso(j.created_at)}


def _values(db: Session, run_id: int) -> list[TenderFieldValue]:
    return list(db.scalars(select(TenderFieldValue).where(TenderFieldValue.field_extraction_id == run_id)
                           .order_by(TenderFieldValue.id)).all())


def _has_value(field_name: str, **conds):
    clauses = [TenderFieldValue.field_extraction_id == TenderFieldExtraction.id,
               TenderFieldValue.field_name == field_name]
    if "tri_state" in conds:
        clauses.append(TenderFieldValue.tri_state == conds["tri_state"])
    if "text_eq" in conds:
        clauses.append(func.lower(TenderFieldValue.value_text) == conds["text_eq"].lower())
    if "text_like" in conds:
        clauses.append(func.lower(TenderFieldValue.value_text).like(f"%{conds['text_like'].lower()}%"))
    return exists().where(and_(*clauses))


def _tri(name: str, value: str | None) -> str | None:
    if value is None:
        return None
    v = value.upper()
    if v not in TRI:
        raise HTTPException(status_code=422, detail=f"{name} must be TRUE, FALSE or UNKNOWN")
    return v


# ===========================================================================
# Static routes (keep above /{field_extraction_id})
# ===========================================================================
@router.get("", response_model=dict, dependencies=[Depends(require_tender_analysis_reader)])
def list_field_extractions(
    bid_number: Optional[str] = Query(None),
    tender_id: Optional[int] = Query(None),
    status: Optional[str] = Query(None, description="SUCCESS | PARTIAL_SUCCESS | FAILED"),
    current_only: bool = Query(True),
    item_category: Optional[str] = Query(None, description="substring, case-insensitive"),
    bid_type: Optional[str] = Query(None, description="exact, case-insensitive (e.g. 'Two Packet Bid')"),
    emd_required: Optional[str] = Query(None, description="TRUE | FALSE | UNKNOWN"),
    mse_relaxation: Optional[str] = Query(None, description="TRUE | FALSE | UNKNOWN"),
    startup_relaxation: Optional[str] = Query(None, description="TRUE | FALSE | UNKNOWN"),
    oem_authorization_required: Optional[str] = Query(None, description="TRUE | FALSE | UNKNOWN"),
    inspection_required: Optional[str] = Query(None, description="TRUE | FALSE | UNKNOWN"),
    field: Optional[str] = Query(None, description="generic filter: registry field name ..."),
    value: Optional[str] = Query(None, description="... and its exact value_text (case-insensitive)"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> dict:
    stmt = select(TenderFieldExtraction)
    if bid_number:
        try:
            stmt = stmt.where(TenderFieldExtraction.bid_number == normalize_bid_number(bid_number))
        except InvalidBidNumber as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    if tender_id is not None:
        stmt = stmt.where(TenderFieldExtraction.tender_id == tender_id)
    if status:
        stmt = stmt.where(TenderFieldExtraction.status == status)
    if current_only:
        stmt = stmt.where(TenderFieldExtraction.is_current.is_(True))
    if item_category:
        stmt = stmt.where(_has_value("item_category", text_like=item_category))
    if bid_type:
        stmt = stmt.where(_has_value("bid_type", text_eq=bid_type))
    params = {"emd_required": emd_required, "mse_relaxation": mse_relaxation,
              "startup_relaxation": startup_relaxation,
              "oem_authorization_required": oem_authorization_required, "inspection_required": inspection_required}
    for qname, raw in params.items():
        tri = _tri(qname, raw)
        if tri:
            stmt = stmt.where(_has_value(TRI_FILTERS[qname], tri_state=tri))
    if field or value:
        if not field or value is None or field not in BY_NAME:
            raise HTTPException(status_code=422, detail="field must be a registry field name and value is required")
        spec = BY_NAME[field]
        stmt = stmt.where(_has_value(field, tri_state=value.upper()) if spec.value_type == "BOOL"
                          else _has_value(field, text_eq=value))
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    rows = db.scalars(stmt.order_by(TenderFieldExtraction.id.desc()).offset((page - 1) * page_size)
                      .limit(page_size)).all()
    return {"items": [_run_out(r) for r in rows], **_page(total, page, page_size)}


@router.get("/jobs", response_model=dict, dependencies=[Depends(require_tender_fields_operator)])
def list_jobs(status: Optional[str] = Query(None), stage3a_extraction_id: Optional[int] = Query(None),
              page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
              db: Session = Depends(get_db)) -> dict:
    stmt = select(FieldExtractionJob)
    if status:
        stmt = stmt.where(FieldExtractionJob.status == status)
    if stage3a_extraction_id is not None:
        stmt = stmt.where(FieldExtractionJob.stage3a_extraction_id == stage3a_extraction_id)
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    rows = db.scalars(stmt.order_by(FieldExtractionJob.updated_at.desc(), FieldExtractionJob.id.desc())
                      .offset((page - 1) * page_size).limit(page_size)).all()
    return {"items": [_job_out(j) for j in rows], **_page(total, page, page_size)}


@router.get("/jobs/{job_id}", response_model=dict, dependencies=[Depends(require_tender_fields_operator)])
def get_job(job_id: int, db: Session = Depends(get_db)) -> dict:
    j = db.get(FieldExtractionJob, job_id)
    if j is None:
        raise HTTPException(status_code=404, detail="Field extraction job not found")
    return _job_out(j)


@router.get("/worker", response_model=dict, dependencies=[Depends(require_tender_fields_operator)])
def worker_status(db: Session = Depends(get_db), worker=Depends(get_field_extraction_worker),
                  scheduler=Depends(get_scheduler)) -> dict:
    return field_extraction_status(db, worker, scheduler)


@router.get("/bid/{bid_number:path}", response_model=dict, dependencies=[Depends(require_tender_analysis_reader)])
def by_bid(bid_number: str, db: Session = Depends(get_db)) -> dict:
    """Current Stage 3B results of every document version of a bid.

    Documents/versions are NOT merged: each entry keeps its own document and version
    identity, newest version first per document (``is_latest_version`` marks it).
    """
    try:
        bid = normalize_bid_number(bid_number)
    except InvalidBidNumber as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if db.scalar(select(Tender.id).where(Tender.bid_number == bid)) is None:
        raise HTTPException(status_code=404, detail="Tender not found")
    runs = db.scalars(select(TenderFieldExtraction).where(TenderFieldExtraction.bid_number == bid,
                                                          TenderFieldExtraction.is_current.is_(True))
                      .order_by(TenderFieldExtraction.document_id, TenderFieldExtraction.version_number.desc())).all()
    seen_docs: set[int] = set()
    items = []
    for r in runs:
        item = _run_out(r, _values(db, r.id))
        item["is_latest_version"] = r.document_id not in seen_docs
        seen_docs.add(r.document_id)
        items.append(item)
    return {"bid_number": bid, "precedence": "per document: newest version first; documents are not merged in Stage 3B",
            "items": items}


@router.get("/extraction/{stage3a_extraction_id}", response_model=dict, dependencies=[Depends(require_tender_analysis_reader)])
def by_stage3a(stage3a_extraction_id: int, db: Session = Depends(get_db)) -> dict:
    if db.get(DocumentExtraction, stage3a_extraction_id) is None:
        raise HTTPException(status_code=404, detail="Stage 3A extraction not found")
    runs = db.scalars(select(TenderFieldExtraction)
                      .where(TenderFieldExtraction.stage3a_extraction_id == stage3a_extraction_id)
                      .order_by(TenderFieldExtraction.id.desc())).all()
    cur = next((r for r in runs if r.is_current and r.extractor_version == FIELD_EXTRACTOR_VERSION), None)
    if cur is None:
        raise HTTPException(status_code=404, detail="No current field extraction for this Stage 3A extraction")
    return {"current": _run_out(cur, _values(db, cur.id)),
            "history": [{"id": r.id, "status": r.status, "is_current": r.is_current,
                         "extractor_version": r.extractor_version, "created_at": _iso(r.created_at)} for r in runs]}


def _queue(db: Session, stage3a_extraction_id: int, force: bool) -> dict:
    if db.get(DocumentExtraction, stage3a_extraction_id) is None:
        raise HTTPException(status_code=404, detail="Stage 3A extraction not found")
    res = enqueue_field_extraction(db, stage3a_extraction_id,
                                   FieldJobReason.REEXTRACT if force else FieldJobReason.MANUAL, force=force)
    db.commit()
    if res.skipped_reason == "not_ready":
        raise HTTPException(status_code=409, detail="Stage 3A extraction is not current or not usable "
                                                    "(needs SUCCESS / PARTIAL_SUCCESS)")
    return {"queued": res.created, "job_id": res.job_id, "reason": res.skipped_reason,
            "status": res.job.status if res.job is not None else None, "force": force}


@router.post("/extraction/{stage3a_extraction_id}/queue", response_model=dict, dependencies=[Depends(require_tender_fields_operator)])
def queue(stage3a_extraction_id: int, db: Session = Depends(get_db)) -> dict:
    return _queue(db, stage3a_extraction_id, False)


@router.post("/extraction/{stage3a_extraction_id}/reextract", response_model=dict, dependencies=[Depends(require_tender_fields_operator)])
def reextract(stage3a_extraction_id: int, db: Session = Depends(get_db)) -> dict:
    return _queue(db, stage3a_extraction_id, True)


# ===========================================================================
# Dynamic /{field_extraction_id} routes (keep LAST)
# ===========================================================================
def _run(db: Session, run_id: int) -> TenderFieldExtraction:
    r = db.get(TenderFieldExtraction, run_id)
    if r is None:
        raise HTTPException(status_code=404, detail="Field extraction not found")
    return r


@router.get("/{field_extraction_id}", response_model=dict, dependencies=[Depends(require_tender_analysis_reader)])
def get_run(field_extraction_id: int, db: Session = Depends(get_db)) -> dict:
    r = _run(db, field_extraction_id)
    return _run_out(r, _values(db, r.id))


@router.get("/{field_extraction_id}/values", response_model=dict, dependencies=[Depends(require_tender_analysis_reader)])
def get_values(field_extraction_id: int, group: Optional[str] = Query(None),
               status: Optional[str] = Query(None, description="RESOLVED | CONFLICT | UNKNOWN"),
               db: Session = Depends(get_db)) -> dict:
    r = _run(db, field_extraction_id)
    vals = [v for v in _values(db, r.id) if (group is None or v.field_group == group)
            and (status is None or v.status == status)]
    return {"field_extraction_id": r.id, "source": _run_out(r)["source"], "items": [_value_out(v) for v in vals]}


@router.get("/{field_extraction_id}/evidence", response_model=dict, dependencies=[Depends(require_tender_analysis_reader)])
def get_evidence(field_extraction_id: int, field_name: Optional[str] = Query(None),
                 db: Session = Depends(get_db)) -> dict:
    r = _run(db, field_extraction_id)
    stmt = select(TenderFieldEvidence).where(TenderFieldEvidence.field_extraction_id == r.id)
    if field_name:
        stmt = stmt.where(TenderFieldEvidence.field_name == field_name)
    rows = db.scalars(stmt.order_by(TenderFieldEvidence.id)).all()
    return {"field_extraction_id": r.id, "source": _run_out(r)["source"], "items": [_evidence_out(e) for e in rows]}


@router.get("/{field_extraction_id}/conflicts", response_model=dict, dependencies=[Depends(require_tender_analysis_reader)])
def get_conflicts(field_extraction_id: int, db: Session = Depends(get_db)) -> dict:
    r = _run(db, field_extraction_id)
    vals = [v for v in _values(db, r.id) if v.status == FieldStatus.CONFLICT.value]
    ev = {}
    if vals:
        for e in db.scalars(select(TenderFieldEvidence).where(
                TenderFieldEvidence.field_extraction_id == r.id,
                TenderFieldEvidence.field_name.in_([v.field_name for v in vals])).order_by(TenderFieldEvidence.id)):
            ev.setdefault(e.field_name, []).append(_evidence_out(e))
    return {"field_extraction_id": r.id, "source": _run_out(r)["source"],
            "items": [{**_value_out(v), "evidence": ev.get(v.field_name, [])} for v in vals]}
