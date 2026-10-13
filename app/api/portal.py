"""Client portal API: each client sees only the tenders matched to its own seller profile.

Every route is scoped by ``seller_id`` in the path. That ID is never trusted on
its own: ``authorize_seller`` requires an ACTIVE membership of the verified
identity (Supabase JWT) for that seller. Every query is also filtered by the
same seller_id, so another seller's data is unreachable even with a guessed ID:
the API returns 403 for a seller you don't belong to and 404 for tenders not
matched to your seller.

Read-only, deterministic, no AI calls. Tender content shown here was
extracted once per tender and is displayed together with its evidence
(document, page, quote). Values the documents do not state stay null /
"not specified".
"""

from __future__ import annotations

import json
import threading
import time
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.api.deps import get_db
from app.api.file_access import stored_file_response
from app.api.seller_authorization import EDIT_ROLES, READ_ROLES, authorize_seller
from app.core.supabase_auth import AuthenticatedIdentity
from app.database.matching_models import SellerTenderMatch
from app.database.models import (
    AIAnalysisFlag,
    AIAnalysisRun,
    AIEvidenceChunk,
    AIRequirement,
    AIRequirementEvidence,
    DocumentVersion,
    DocumentExtraction,
    DocumentTable,
    DocumentSection,
    DocumentEvent,
    Seller,
    SellerAttribute,
    SellerRevision,
    Tender,
    TenderChange,
    TenderDocument,
    TenderFieldExtraction,
    TenderFieldValue,
    TenderFieldEvidence,
    TenderStatusEvent,
    TenderStatusRecord,
)
from app.matching.relevance import RELEVANCE_ATTRIBUTE_KEYS, parse_terms
from app.matching.service import ACTIVE_TENDER_STATES, MatchingService, MatchStatus
from app.services.status_service import AMENDMENT_FIELDS
from app.utils.dates import as_aware_utc, to_utc_naive, utcnow

router = APIRouter(prefix="/api/portal", tags=["client-portal"])

_STATUS_ORDER = case(
    (SellerTenderMatch.match_status == MatchStatus.MATCHED, 0),
    (SellerTenderMatch.match_status == MatchStatus.REVIEW_REQUIRED, 1),
    else_=2,
)
_REQUIREMENT_SECTIONS = {
    "ELIGIBILITY": "eligibility", "DOCUMENTS": "eligibility", "COMPLIANCE": "eligibility",
    "TECHNICAL": "technical", "DELIVERY_WARRANTY": "technical",
    "COMMERCIAL": "conditions", "OTHER": "conditions",
}


def _iso(value: datetime | None) -> str | None:
    aware = as_aware_utc(value)
    return aware.isoformat() if aware else None


def _escape_like(term: str) -> str:
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _require_match(db: Session, seller_id: int, tender_id: int) -> SellerTenderMatch:
    match = db.scalar(select(SellerTenderMatch).where(
        SellerTenderMatch.seller_id == seller_id, SellerTenderMatch.tender_id == tender_id,
        SellerTenderMatch.relevance_status == "RELEVANT"))
    if match is None:
        raise HTTPException(status_code=404, detail="Tender not found for this seller")
    return match


def _reasons(match: SellerTenderMatch) -> dict[str, list[dict]]:
    try:
        items = json.loads(match.reasons_json or "[]")
    except json.JSONDecodeError:
        items = []
    grouped: dict[str, list[dict]] = {"matched": [], "failed": [], "needs_review": [], "info": []}
    key = {"MATCHED": "matched", "FAILED": "failed", "REVIEW": "needs_review"}
    for item in items:
        grouped[key.get(item.get("kind"), "info")].append({
            "requirement": item.get("requirement"),
            "requirement_type": item.get("requirement_type"),
            "detail": item.get("detail"),
            "relaxation_applied": item.get("relaxation_applied"),
        })
    return grouped


def _match_out(match: SellerTenderMatch, with_reasons: bool) -> dict:
    out = {
        "match_status": match.match_status,
        "relevance_status": match.relevance_status,
        "eligibility_status": match.eligibility_status,
        "matched_terms": json.loads(match.matched_terms_json or "[]"),
        "requirements_passed": match.passed_count,
        "requirements_failed": match.failed_count,
        "requirements_needing_review": match.review_count,
        "computed_at": _iso(match.computed_at),
    }
    if with_reasons:
        out["reasons"] = _reasons(match)
    return out


def _tender_card(t: Tender, match: SellerTenderMatch, now: datetime) -> dict:
    days_left = None
    if t.bid_end_at is not None:
        days_left = round((t.bid_end_at - now).total_seconds() / 86400, 1)
    return {
        "tender_id": t.id,
        "bid_number": t.bid_number,
        "title": t.title,
        "buyer_name": t.buyer_name,
        "ministry": t.ministry,
        "department": t.department,
        "category": t.category,
        "quantity": t.quantity,
        "bid_start_at": _iso(t.published_at),
        "bid_end_at": _iso(t.bid_end_at),
        "days_to_deadline": days_left,
        "current_status": t.current_status,
        "last_updated_at": _iso(max(x for x in (t.updated_at, match.computed_at) if x is not None)),
        "match": _match_out(match, with_reasons=False),
    }


# ---------------------------------------------------------------------------


@router.get("/sellers/{seller_id}/summary")
def portal_summary(seller_id: int, db: Session = Depends(get_db),
                   identity: AuthenticatedIdentity = Depends(get_current_user)) -> dict:
    """Dashboard counts and profile guidance for one seller."""
    authorize_seller(seller_id, identity, db, READ_ROLES)
    now = utcnow()
    rows = db.execute(
        select(SellerTenderMatch.match_status, func.count())
        .join(Tender, Tender.id == SellerTenderMatch.tender_id)
        .join(TenderStatusRecord, TenderStatusRecord.tender_id == Tender.id)
        .where(SellerTenderMatch.seller_id == seller_id, SellerTenderMatch.relevance_status == "RELEVANT",
               TenderStatusRecord.current_status.in_(ACTIVE_TENDER_STATES))
        .group_by(SellerTenderMatch.match_status)).all()
    counts = {MatchStatus.MATCHED: 0, MatchStatus.REVIEW_REQUIRED: 0, MatchStatus.NOT_MATCHED: 0}
    counts.update({k: v for k, v in rows})
    closing_soon = db.scalar(
        select(func.count()).select_from(SellerTenderMatch)
        .join(Tender, Tender.id == SellerTenderMatch.tender_id)
        .join(TenderStatusRecord, TenderStatusRecord.tender_id == Tender.id)
        .where(SellerTenderMatch.seller_id == seller_id, SellerTenderMatch.relevance_status == "RELEVANT",
               SellerTenderMatch.match_status.in_((MatchStatus.MATCHED, MatchStatus.REVIEW_REQUIRED)),
               TenderStatusRecord.current_status.in_(ACTIVE_TENDER_STATES),
               Tender.bid_end_at.is_not(None), Tender.bid_end_at <= now + timedelta(days=3))) or 0
    last = db.scalar(select(func.max(SellerTenderMatch.computed_at)).where(SellerTenderMatch.seller_id == seller_id))
    rev = db.scalar(select(SellerRevision).where(SellerRevision.seller_id == seller_id,
                                                 SellerRevision.is_active.is_(True))
                    .order_by(SellerRevision.revision_number.desc()))
    terms: list[str] = []
    if rev is not None:
        attrs = db.scalars(select(SellerAttribute).where(SellerAttribute.revision_id == rev.id,
                                                         SellerAttribute.key.in_(RELEVANCE_ATTRIBUTE_KEYS))).all()
        terms = parse_terms([a.value_json or a.value_text for a in attrs])
    guidance = [] if terms else [
        "Add your products, services or keywords (profile attributes 'product_category', 'products', "
        "'services' or 'keywords') so matching tenders can be found automatically."]
    return {
        "seller_id": seller_id,
        "live_matched": counts[MatchStatus.MATCHED],
        "live_review_required": counts[MatchStatus.REVIEW_REQUIRED],
        "live_not_matched": counts[MatchStatus.NOT_MATCHED],
        "closing_within_3_days": closing_soon,
        "matching_terms": terms,
        "last_matched_at": _iso(last),
        "guidance": guidance,
    }


@router.get("/sellers/{seller_id}/tenders")
def portal_tenders(
    seller_id: int,
    view: Literal["actionable", "matched", "review", "not_matched", "all"] = Query("actionable"),
    live_only: bool = Query(True, description="Only LIVE / UPCOMING tenders"),
    closing_within_days: int | None = Query(None, ge=0, le=365),
    category: str | None = Query(None, max_length=200),
    buyer: str | None = Query(None, max_length=200),
    q: str | None = Query(None, max_length=200, description="Search bid number / title"),
    bid_end_from: datetime | None = Query(None),
    bid_end_to: datetime | None = Query(None),
    page: int = Query(1, ge=1, le=10000),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    identity: AuthenticatedIdentity = Depends(get_current_user),
) -> dict:
    """This seller's tenders: MATCHED first, then REVIEW_REQUIRED, soonest deadline first."""
    authorize_seller(seller_id, identity, db, READ_ROLES)
    now = utcnow()
    stmt = (select(Tender, SellerTenderMatch)
            .join(SellerTenderMatch, SellerTenderMatch.tender_id == Tender.id)
            .outerjoin(TenderStatusRecord, TenderStatusRecord.tender_id == Tender.id)
            .where(SellerTenderMatch.seller_id == seller_id, SellerTenderMatch.relevance_status == "RELEVANT"))
    statuses = {
        "actionable": (MatchStatus.MATCHED, MatchStatus.REVIEW_REQUIRED),
        "matched": (MatchStatus.MATCHED,),
        "review": (MatchStatus.REVIEW_REQUIRED,),
        "not_matched": (MatchStatus.NOT_MATCHED,),
        "all": (MatchStatus.MATCHED, MatchStatus.REVIEW_REQUIRED, MatchStatus.NOT_MATCHED),
    }[view]
    stmt = stmt.where(SellerTenderMatch.match_status.in_(statuses))
    if live_only:
        stmt = stmt.where(TenderStatusRecord.current_status.in_(ACTIVE_TENDER_STATES))
    if closing_within_days is not None:
        stmt = stmt.where(Tender.bid_end_at.is_not(None), Tender.bid_end_at >= now,
                          Tender.bid_end_at <= now + timedelta(days=closing_within_days))
    if category:
        stmt = stmt.where(Tender.category.ilike(f"%{_escape_like(category)}%", escape="\\"))
    if buyer:
        like = f"%{_escape_like(buyer)}%"
        stmt = stmt.where(or_(Tender.buyer_name.ilike(like, escape="\\"), Tender.ministry.ilike(like, escape="\\"),
                              Tender.department.ilike(like, escape="\\"),
                              Tender.organisation.ilike(like, escape="\\")))
    if q:
        like = f"%{_escape_like(q)}%"
        stmt = stmt.where(or_(Tender.bid_number.ilike(like, escape="\\"), Tender.title.ilike(like, escape="\\")))
    for value, op in ((bid_end_from, ">="), (bid_end_to, "<=")):
        if value is not None:
            if value.tzinfo is None:
                raise HTTPException(status_code=422, detail="Date filters must include a timezone offset")
            naive = to_utc_naive(value)
            stmt = stmt.where(Tender.bid_end_at >= naive if op == ">=" else Tender.bid_end_at <= naive)
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    rows = db.execute(stmt.order_by(_STATUS_ORDER, Tender.bid_end_at.is_(None), Tender.bid_end_at, Tender.id)
                      .offset((page - 1) * page_size).limit(page_size)).all()
    return {
        "items": [_tender_card(t, m, now) for t, m in rows],
        "total": total, "page": page, "page_size": page_size,
        "pages": (total + page_size - 1) // page_size,
    }


@router.get("/sellers/{seller_id}/tenders/{tender_id}")
def portal_tender_detail(seller_id: int, tender_id: int, db: Session = Depends(get_db),
                         identity: AuthenticatedIdentity = Depends(get_current_user)) -> dict:
    """One structured, evidence-backed tender view plus this seller's match explanation."""
    authorize_seller(seller_id, identity, db, READ_ROLES)
    match = _require_match(db, seller_id, tender_id)
    t = db.get(Tender, tender_id)
    if t is None:
        raise HTTPException(status_code=404, detail="Tender not found for this seller")

    documents = _documents(db, tender_id)
    doc_by_version = {v["version_id"]: d for d in documents for v in d["versions"]}
    analysis = _analysis(db, tender_id, doc_by_version)
    from app.corpus.service import build_corpus
    corpus=build_corpus(db,tender_id)
    return {
        "basic": {
            "tender_id": t.id, "bid_number": t.bid_number, "title": t.title, "bid_type": t.bid_type,
            "buyer_name": t.buyer_name, "ministry": t.ministry, "department": t.department,
            "organisation": t.organisation, "category": t.category, "quantity": t.quantity,
            "estimated_value": str(t.estimated_value) if t.estimated_value is not None else None,
            "bid_start_at": _iso(t.published_at), "bid_end_at": _iso(t.bid_end_at),
            "bid_opening_at": _iso(t.bid_opening_at), "source_url": t.source_url,
        },
        "status": {
            "current_status": t.current_status, "status_source": t.status_source,
            "source_reported_status": t.status, "last_status_check_at": _iso(t.last_status_check_at),
            "last_seen_on_gem_at": _iso(t.last_seen_at), "last_updated_at": _iso(t.updated_at),
        },
        "summary": analysis["summary"],
        "analysis_status": analysis["analysis_status"],
        "package": {k:corpus[k] for k in ('complete','completeness','reasons','fingerprint','relevant_document_count','missing_reference_count')},
        "deterministic_requirements": _deterministic_requirements(db,tender_id,corpus,doc_by_version),
        "analysis_model": analysis.get("model"),
        "eligibility": analysis["sections"]["eligibility"],
        "technical_requirements": analysis["sections"]["technical"],
        "important_conditions": analysis["sections"]["conditions"],
        "extracted_fields": _fields(db, tender_id, corpus),
        "review_flags": analysis["flags"],
        "amendments": _amendments(db, tender_id, documents),
        "documents": documents,
        "match": _match_out(match, with_reasons=True),
    }


@router.get("/sellers/{seller_id}/tenders/{tender_id}/documents/{document_id}/versions/{version_id}/download")
def portal_document_download(seller_id: int, tender_id: int, document_id: int, version_id: int,
                             request: Request, db: Session = Depends(get_db),
                             identity: AuthenticatedIdentity = Depends(get_current_user)):
    """Download a collected tender document, but only for a tender matched to this seller."""
    authorize_seller(seller_id, identity, db, READ_ROLES)
    _require_match(db, seller_id, tender_id)
    version = db.scalar(
        select(DocumentVersion).join(TenderDocument, TenderDocument.id == DocumentVersion.document_id)
        .where(DocumentVersion.id == version_id, DocumentVersion.document_id == document_id,
               TenderDocument.tender_id == tender_id))
    if version is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return stored_file_response(request.app.state.settings.resolved_document_storage_path, version)


@router.post("/sellers/{seller_id}/matches/refresh")
def portal_refresh_matches(seller_id: int, request: Request, db: Session = Depends(get_db),
                           identity: AuthenticatedIdentity = Depends(get_current_user)) -> dict:
    """Recompute this seller's matches now (after a profile change). Deterministic; no AI calls."""
    authorize_seller(seller_id, identity, db, EDIT_ROLES)
    if db.get(Seller, seller_id) is None:
        raise HTTPException(status_code=404, detail="Seller not found")
    _refresh_cooldown(request, seller_id)
    limit = request.app.state.settings.matching_max_evaluations_per_run
    stats = MatchingService(db).recalculate(now=utcnow(), seller_ids=[seller_id], max_evaluations=limit)
    return {"seller_id": seller_id, **stats.as_dict()}


REFRESH_COOLDOWN_SECONDS = 30
_refresh_lock = threading.Lock()


def _refresh_cooldown(request: Request, seller_id: int) -> None:
    """At most one manual recomputation per seller per cooldown window (429 otherwise)."""
    state = request.app.state
    with _refresh_lock:
        last: dict[int, float] = getattr(state, "portal_refresh_at", None) or {}
        now = time.monotonic()
        if now - last.get(seller_id, -1e9) < REFRESH_COOLDOWN_SECONDS:
            raise HTTPException(status_code=429, detail="Matches were refreshed moments ago; try again shortly",
                                headers={"Retry-After": str(REFRESH_COOLDOWN_SECONDS)})
        last[seller_id] = now
        state.portal_refresh_at = last


# ---------------------------------------------------------------------------
# Detail helpers
# ---------------------------------------------------------------------------


def _documents(db: Session, tender_id: int) -> list[dict]:
    docs = db.scalars(select(TenderDocument).where(TenderDocument.tender_id == tender_id)
                      .order_by(TenderDocument.id)).all()
    out = []
    for d in docs:
        event=db.scalar(select(DocumentEvent).where(DocumentEvent.document_id==d.id).order_by(DocumentEvent.id.desc()).limit(1))
        extractions={e.document_version_id:e for e in db.scalars(select(DocumentExtraction).where(
            DocumentExtraction.document_id==d.id,DocumentExtraction.is_current.is_(True)).order_by(DocumentExtraction.id))}
        ocr_metadata={}
        for h in db.scalars(select(DocumentSection).join(DocumentExtraction,DocumentExtraction.id==DocumentSection.extraction_id).where(
            DocumentExtraction.document_id==d.id,DocumentExtraction.is_current.is_(True),DocumentSection.detection_method=='OCR_METADATA')):
            ocr_metadata.setdefault(h.extraction_id,[]).append(json.loads(h.heading))
        versions = db.scalars(select(DocumentVersion).where(DocumentVersion.document_id == d.id)
                              .order_by(DocumentVersion.version_number)).all()
        out.append({
            "document_id": d.id, "document_type": d.document_type, "display_name": d.display_name,
            "filename": d.original_filename, "source_url": d.source_url, "is_active": d.is_active,
            "discovered_at": _iso(d.discovered_at), "current_version_id": d.current_version_id,
            "processing_state":event.event_type if event else "PENDING",
            "versions": [{
                "version_id": v.id, "version_number": v.version_number, "sha256": v.sha256,
                "file_size": v.file_size, "mime_type": v.mime_type, "downloaded_at": _iso(v.downloaded_at),
                "validation_status": v.validation_status, "downloadable": bool(v.storage_path),
                "file_type":v.extension,
                "processing_state":extractions[v.id].status if v.id in extractions else "PENDING",
                "extraction_state":extractions[v.id].text_class if v.id in extractions else None,
                "extraction_quality":extractions[v.id].quality_status if v.id in extractions else None,
                "extraction_error":extractions[v.id].error_code if v.id in extractions else None,
                "ocr":ocr_metadata.get(extractions[v.id].id,[]) if v.id in extractions else [],
            } for v in versions],
        })
    return out


def _analysis(db: Session, tender_id: int, doc_by_version: dict[int, dict]) -> dict[str, Any]:
    sections: dict[str, list[dict]] = {"eligibility": [], "technical": [], "conditions": []}
    run = db.scalar(select(AIAnalysisRun).where(
        AIAnalysisRun.tender_id == tender_id, AIAnalysisRun.analysis_scope == "TENDER_CORPUS",
        AIAnalysisRun.is_current.is_(True)).order_by(AIAnalysisRun.id.desc()))
    if run is None:
        return {"summary": None, "analysis_status": "NOT_ANALYSED", "sections": sections, "flags": []}
    if run.corpus_fingerprint:
        from app.corpus.analysis import CORPUS_PROMPT_VERSION
        from app.corpus.service import build_corpus
        if run.prompt_version != CORPUS_PROMPT_VERSION or run.corpus_fingerprint != build_corpus(db, tender_id)["fingerprint"]:
            return {"summary": None, "analysis_status": "STALE", "sections": sections,
                    "flags": [{"flag_type": "ANALYSIS_INCOMPLETE", "severity": "HIGH",
                               "message": "Tender package or AI input policy changed; updated analysis is pending."}]}
    if run.status not in ("SUCCESS", "PARTIAL_SUCCESS"):
        return {"summary": None, "analysis_status": run.status, "sections": sections, "flags": []}

    reqs = db.scalars(select(AIRequirement).where(AIRequirement.analysis_run_id == run.id)
                      .order_by(AIRequirement.sequence)).all()
    evidence: dict[int, list[dict]] = defaultdict(list)
    if reqs:
        rows = db.execute(
            select(AIRequirementEvidence, AIEvidenceChunk.document_version_id,AIEvidenceChunk.table_id)
            .join(AIEvidenceChunk, AIEvidenceChunk.id == AIRequirementEvidence.chunk_id)
            .where(AIRequirementEvidence.analysis_run_id == run.id)).all()
        for ev, version_id, table_id in rows:
            doc = doc_by_version.get(version_id) or {}
            location=None
            if table_id:
                table=db.get(DocumentTable,table_id)
                bbox=json.loads(table.bbox_json) if table and table.bbox_json else None
                if isinstance(bbox,dict):
                    original=bbox.get('location') or {}
                    location={k:original[k] for k in ('kind','sheet','table','row_base') if k in original}
                    cells=original.get('cells',[])
                    if cells:location['cell_range']=[cells[0],cells[-1]]
            evidence[ev.requirement_id].append({
                "document_id": doc.get("document_id"), "document_type": doc.get("document_type"),
                "document_name": doc.get("display_name") or doc.get("filename"),
                "page": ev.page_number or None, "section": ev.section_heading, "quote": ev.quote,
                **({"source_location":location} if location else {}),
            })
    for r in reqs:
        sections[_REQUIREMENT_SECTIONS.get(r.category, "conditions")].append({
            "requirement_type": r.requirement_type, "category": r.category, "title": r.title,
            "summary": r.summary, "obligation_level": r.obligation_level, "condition": r.condition_text,
            "value_text": r.value_text, "value_number": r.value_number, "unit": r.unit,
            "ambiguity": r.ambiguity, "risk_flags": json.loads(r.risk_flags_json) if r.risk_flags_json else [],
            "review_required": r.obligation_level == "UNKNOWN" or bool(r.ambiguity),
            "evidence": evidence.get(r.id, []),
        })
    flags = [{"flag_type": f.flag_type, "severity": f.severity, "message": f.message}
             for f in db.scalars(select(AIAnalysisFlag).where(AIAnalysisFlag.analysis_run_id == run.id)
                                 .order_by(AIAnalysisFlag.id)).all()]
    return {"summary": run.summary, "analysis_status": run.status, "sections": sections, "flags": flags,
            "model": {"provider": run.provider, "model": run.model, "prompt_version": run.prompt_version,
                      "completed_at": _iso(run.completed_at)}}


def _deterministic_requirements(db,tender_id,corpus,doc_by_version):
    from app.eligibility.service import EligibilityService
    requirements,_=EligibilityService(db)._extract_tender_requirements(tender_id,corpus,None)
    ids=[fid for r in requirements for fid in r.get('stage3b_field_ids',[])]
    evidence=defaultdict(list)
    if ids:
        for e in db.scalars(select(TenderFieldEvidence).where(TenderFieldEvidence.field_value_id.in_(ids),TenderFieldEvidence.disposition.in_(['SELECTED','AGREES'])).order_by(TenderFieldEvidence.id)):
            d=doc_by_version.get(e.document_version_id,{})
            normalized=json.loads(e.normalized_json) if e.normalized_json else None
            location=normalized.get('source_location') if isinstance(normalized,dict) else None
            evidence[e.field_value_id].append({'document_id':d.get('document_id'),'document_version_id':e.document_version_id,'document_name':d.get('display_name') or d.get('filename'),'document_type':d.get('document_type'),'page':e.page_number or None,'section':e.section_heading,'quote':e.source_text or e.raw_value or e.source_label or '',**({'source_location':location} if location else {})})
    return [{'requirement_type':r['type'],'category':'DETERMINISTIC','title':r['title'],'summary':None,'obligation_level':r['obligation'],'condition':None,'value_text':r.get('value_text'),'value_number':r.get('value_number'),'unit':None,'ambiguity':None,'risk_flags':[],'review_required':bool(r.get('relaxation_conflict')),'evidence':[e for fid in r.get('stage3b_field_ids',[]) for e in evidence.get(fid,[])]} for r in requirements]

def _fields(db: Session, tender_id: int, corpus: dict | None = None) -> list[dict]:
    """Deterministically extracted fields. UNKNOWN values are listed as not specified, never guessed."""
    if corpus is None:
        from app.corpus.service import build_corpus
        corpus=build_corpus(db,tender_id)
    ext_ids=[d['stage3b_extraction_id'] for d in corpus['documents'] if d.get('stage3b_extraction_id')]
    if not ext_ids:
        return []
    values = db.scalars(select(TenderFieldValue).where(TenderFieldValue.field_extraction_id.in_(ext_ids))
                        .order_by(TenderFieldValue.field_group, TenderFieldValue.field_name)).all()
    return [{
        "field": v.field_name, "group": v.field_group, "status": v.status, "reason": v.reason,
        "value": v.value_text if v.status == "RESOLVED" else None,
        "number": v.value_number if v.status == "RESOLVED" else None,
        "flag": v.tri_state, "unit": v.unit, "evidence_strength": v.evidence_strength,
    } for v in values]


def _amendments(db: Session, tender_id: int, documents: list[dict]) -> dict:
    changes = db.scalars(select(TenderChange).where(
        TenderChange.tender_id == tender_id,
        TenderChange.field_name.in_(AMENDMENT_FIELDS + ("status",)))
        .order_by(TenderChange.detected_at, TenderChange.id)).all()
    doc_changes = [
        {"document_id": d["document_id"], "document_type": d["document_type"],
         "name": d["display_name"] or d["filename"], "versions": len(d["versions"])}
        for d in documents
        if len(d["versions"]) > 1 or "CORRIGENDUM" in (d["document_type"] or "").upper()
        or "AMENDMENT" in (d["document_type"] or "").upper()
    ]
    field_changes = [{"field": c.field_name, "old": c.old_value, "new": c.new_value,
                      "detected_at": _iso(c.detected_at)} for c in changes]
    status_history = [{"old": e.old_status, "new": e.new_status, "reason": e.status_source,
                       "detected_at": _iso(e.detected_at)}
                      for e in db.scalars(select(TenderStatusEvent).where(TenderStatusEvent.tender_id == tender_id)
                                          .order_by(TenderStatusEvent.detected_at, TenderStatusEvent.id)).all()]
    return {
        "amended": bool(doc_changes) or any(c["field"] in AMENDMENT_FIELDS for c in field_changes),
        "field_changes": field_changes,
        "changed_documents": doc_changes,
        "status_history": status_history,
    }
