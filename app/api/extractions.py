"""Stage 3A extraction API.

ROUTE ORDER MATTERS (see the Stage 2 /jobs bug): every static path is declared
before the dynamic ``/{extraction_id}`` routes. A regression test checks that no
static route is shadowed.

Every extraction response carries ``source`` provenance (tender, bid number,
document type/key, version number, document_version_id, sha256) so later
stages can cite "MAIN_BID v1, page 6".
"""

from __future__ import annotations

import json
import math
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.platform_authorization import require_document_jobs_operator, require_tender_analysis_reader
from app.api.deps import get_db, get_extraction_worker, get_scheduler
from app.database.models import (
    DocumentExtraction,
    DocumentPage,
    DocumentSection,
    DocumentTable,
    DocumentVersion,
    ExtractionJob,
    Tender,
    TenderDocument,
)
from app.extraction.constants import EXTRACTOR_VERSION, ExtractionJobReason
from app.extraction.job_queue import enqueue_extraction
from app.services.extraction_status import extraction_status
from app.utils.dates import as_aware_utc

router = APIRouter(prefix="/api/extractions", tags=["extractions"])


def _iso(dt):
    a = as_aware_utc(dt)
    return a.isoformat() if a else None


def _source(db: Session, version_id: int) -> dict | None:
    row = db.execute(
        select(DocumentVersion.id, DocumentVersion.version_number, DocumentVersion.sha256,
               TenderDocument.id.label("document_id"), TenderDocument.document_type, TenderDocument.document_key,
               Tender.id.label("tender_id"), Tender.bid_number)
        .join(TenderDocument, TenderDocument.id == DocumentVersion.document_id)
        .join(Tender, Tender.id == TenderDocument.tender_id)
        .where(DocumentVersion.id == version_id)).first()
    if row is None:
        return None
    return {"tender_id": row.tender_id, "bid_number": row.bid_number, "document_id": row.document_id,
            "document_type": row.document_type, "document_key": row.document_key,
            "document_version_id": row.id, "version_number": row.version_number, "sha256": row.sha256}


def _extraction_out(db: Session, e: DocumentExtraction, with_source: bool = True) -> dict:
    out = {
        "id": e.id, "document_version_id": e.document_version_id, "document_id": e.document_id,
        "tender_id": e.tender_id, "extractor_name": e.extractor_name, "extractor_version": e.extractor_version,
        "parser_version": e.parser_version, "status": e.status, "quality_status": e.quality_status,
        "text_class": e.text_class, "is_current": e.is_current, "source_sha256": e.source_sha256,
        "source_file_size": e.source_file_size, "page_count": e.page_count, "pages_with_text": e.pages_with_text,
        "pages_without_text": e.pages_without_text, "pages_ocr": e.pages_ocr,
        "total_characters": e.total_characters, "total_words": e.total_words, "tables_found": e.tables_found,
        "sections_found": e.sections_found, "images_found": e.images_found, "unmapped_glyphs": e.unmapped_glyphs,
        "text_coverage_ratio": e.text_coverage_ratio, "duration_ms": e.duration_ms, "error_code": e.error_code,
        "error_message": e.error_message, "started_at": _iso(e.started_at), "completed_at": _iso(e.completed_at),
        "created_at": _iso(e.created_at),
    }
    if with_source:
        out["source"] = _source(db, e.document_version_id)
    return out


def _job_out(j: ExtractionJob) -> dict:
    return {"id": j.id, "document_version_id": j.document_version_id, "status": j.status, "reason": j.reason,
            "force": j.force, "attempt_count": j.attempt_count, "next_retry_at": _iso(j.next_retry_at),
            "started_at": _iso(j.started_at), "finished_at": _iso(j.finished_at), "locked_by": j.locked_by,
            "outcome": j.outcome, "error_code": j.error_code, "error_message": j.error_message,
            "extraction_id": j.extraction_id, "created_at": _iso(j.created_at), "updated_at": _iso(j.updated_at)}


def _page(total: int, page: int, page_size: int) -> dict:
    return {"total": total, "page": page, "page_size": page_size,
            "pages": math.ceil(total / page_size) if total else 0}


def _get_extraction(db: Session, extraction_id: int) -> DocumentExtraction:
    e = db.get(DocumentExtraction, extraction_id)
    if e is None:
        raise HTTPException(status_code=404, detail="Extraction not found")
    return e


# ===========================================================================
# Static routes (keep above /{extraction_id})
# ===========================================================================
@router.get("", response_model=dict, dependencies=[Depends(require_tender_analysis_reader)])
def list_extractions(
    tender_id: Optional[int] = Query(None),
    document_version_id: Optional[int] = Query(None),
    status: Optional[str] = Query(None, description="SUCCESS | PARTIAL_SUCCESS | OCR_REQUIRED | FAILED | UNSUPPORTED"),
    quality_status: Optional[str] = Query(None),
    current_only: bool = Query(True, description="Hide extractions superseded by a forced re-extraction"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> dict:
    stmt = select(DocumentExtraction)
    if tender_id is not None:
        stmt = stmt.where(DocumentExtraction.tender_id == tender_id)
    if document_version_id is not None:
        stmt = stmt.where(DocumentExtraction.document_version_id == document_version_id)
    if status is not None:
        stmt = stmt.where(DocumentExtraction.status == status)
    if quality_status is not None:
        stmt = stmt.where(DocumentExtraction.quality_status == quality_status)
    if current_only:
        stmt = stmt.where(DocumentExtraction.is_current.is_(True))
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    rows = db.scalars(stmt.order_by(DocumentExtraction.id.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    return {"items": [_extraction_out(db, e) for e in rows], **_page(total, page, page_size)}


@router.get("/jobs", response_model=dict, dependencies=[Depends(require_document_jobs_operator)])
def list_extraction_jobs(
    status: Optional[str] = Query(None),
    document_version_id: Optional[int] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> dict:
    stmt = select(ExtractionJob)
    if status is not None:
        stmt = stmt.where(ExtractionJob.status == status)
    if document_version_id is not None:
        stmt = stmt.where(ExtractionJob.document_version_id == document_version_id)
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    rows = db.scalars(stmt.order_by(ExtractionJob.updated_at.desc(), ExtractionJob.id.desc())
                      .offset((page - 1) * page_size).limit(page_size)).all()
    return {"items": [_job_out(j) for j in rows], **_page(total, page, page_size)}


@router.get("/jobs/{job_id}", response_model=dict, dependencies=[Depends(require_document_jobs_operator)])
def get_extraction_job(job_id: int, db: Session = Depends(get_db)) -> dict:
    j = db.get(ExtractionJob, job_id)
    if j is None:
        raise HTTPException(status_code=404, detail="Extraction job not found")
    return _job_out(j)


@router.get("/worker", response_model=dict, dependencies=[Depends(require_document_jobs_operator)])
def get_extraction_worker_status(db: Session = Depends(get_db), worker=Depends(get_extraction_worker),
                                 scheduler=Depends(get_scheduler)) -> dict:
    return extraction_status(db, worker, scheduler)


@router.get("/document-version/{document_version_id}", response_model=dict, dependencies=[Depends(require_tender_analysis_reader)])
def get_extraction_for_version(document_version_id: int, db: Session = Depends(get_db)) -> dict:
    """Current extraction (EXTRACTOR_VERSION) of a version + history of superseded ones."""
    if db.get(DocumentVersion, document_version_id) is None:
        raise HTTPException(status_code=404, detail="Document version not found")
    rows = db.scalars(select(DocumentExtraction).where(DocumentExtraction.document_version_id == document_version_id)
                      .order_by(DocumentExtraction.id.desc())).all()
    current = next((e for e in rows if e.is_current and e.extractor_version == EXTRACTOR_VERSION), None)
    if current is None:
        raise HTTPException(status_code=404, detail="No current extraction for this document version")
    return {"current": _extraction_out(db, current),
            "history": [{"id": e.id, "status": e.status, "extractor_version": e.extractor_version,
                         "is_current": e.is_current, "created_at": _iso(e.created_at)} for e in rows]}


def _queue(db: Session, document_version_id: int, force: bool) -> dict:
    if db.get(DocumentVersion, document_version_id) is None:
        raise HTTPException(status_code=404, detail="Document version not found")
    reason = ExtractionJobReason.REEXTRACT if force else ExtractionJobReason.MANUAL
    res = enqueue_extraction(db, document_version_id, reason, force=force)
    db.commit()
    if res.skipped_reason == "not_eligible":
        raise HTTPException(status_code=409, detail="Document version is not VALID or has no stored file")
    return {"queued": res.created, "job_id": res.job_id, "reason": res.skipped_reason,
            "status": res.job.status if res.job is not None else None, "force": force}


@router.post("/document-version/{document_version_id}/queue", response_model=dict, dependencies=[Depends(require_document_jobs_operator)])
def queue_extraction(document_version_id: int, db: Session = Depends(get_db)) -> dict:
    """Queue a normal extraction (no-op if already extracted / already queued)."""
    return _queue(db, document_version_id, force=False)


@router.post("/document-version/{document_version_id}/reextract", response_model=dict, dependencies=[Depends(require_document_jobs_operator)])
def reextract(document_version_id: int, db: Session = Depends(get_db)) -> dict:
    """Queue a FORCED re-extraction: the old extraction is kept but marked is_current=false."""
    return _queue(db, document_version_id, force=True)


# ===========================================================================
# Dynamic /{extraction_id} routes (keep LAST)
# ===========================================================================
@router.get("/{extraction_id}", response_model=dict, dependencies=[Depends(require_tender_analysis_reader)])
def get_extraction(extraction_id: int, db: Session = Depends(get_db)) -> dict:
    return _extraction_out(db, _get_extraction(db, extraction_id))


@router.get("/{extraction_id}/pages", response_model=dict, dependencies=[Depends(require_tender_analysis_reader)])
def list_pages(extraction_id: int, include_text: bool = Query(False, description="Include normalized_text"),
               db: Session = Depends(get_db)) -> dict:
    e = _get_extraction(db, extraction_id)
    rows = db.scalars(select(DocumentPage).where(DocumentPage.extraction_id == e.id)
                      .order_by(DocumentPage.page_number)).all()
    items = []
    for p in rows:
        item = {"page_number": p.page_number or None, "logical_unit":p.page_number==0, "char_count": p.char_count, "word_count": p.word_count,
                "has_text": p.has_text, "image_count": p.image_count, "text_source": p.text_source,
                "unmapped_glyph_count": p.unmapped_glyph_count, "error_code": p.error_code}
        if include_text:
            item["normalized_text"] = p.normalized_text
        items.append(item)
    return {"extraction_id": e.id, "source": _source(db, e.document_version_id), "items": items}


@router.get("/{extraction_id}/pages/{page_number}", response_model=dict, dependencies=[Depends(require_tender_analysis_reader)])
def get_page(extraction_id: int, page_number: int, db: Session = Depends(get_db)) -> dict:
    e = _get_extraction(db, extraction_id)
    p = db.scalar(select(DocumentPage).where(DocumentPage.extraction_id == e.id,
                                             DocumentPage.page_number == page_number))
    if p is None:
        raise HTTPException(status_code=404, detail="Page not found (page numbers are 1-based)")
    return {"extraction_id": e.id, "source": _source(db, e.document_version_id), "page_number": p.page_number or None,"logical_unit":p.page_number==0,
            "raw_text": p.raw_text, "normalized_text": p.normalized_text, "char_count": p.char_count,
            "word_count": p.word_count, "meaningful_char_count": p.meaningful_char_count, "has_text": p.has_text,
            "image_count": p.image_count, "unmapped_glyph_count": p.unmapped_glyph_count,
            "text_source": p.text_source, "width": p.width, "height": p.height, "error_code": p.error_code}


@router.get("/{extraction_id}/tables", response_model=dict, dependencies=[Depends(require_tender_analysis_reader)])
def list_tables(extraction_id: int, page_number: Optional[int] = Query(None), db: Session = Depends(get_db)) -> dict:
    e = _get_extraction(db, extraction_id)
    stmt = select(DocumentTable).where(DocumentTable.extraction_id == e.id)
    if page_number is not None:
        stmt = stmt.where(DocumentTable.page_number == page_number)
    rows = db.scalars(stmt.order_by(DocumentTable.page_number, DocumentTable.table_index)).all()
    return {"extraction_id": e.id, "source": _source(db, e.document_version_id), "items": [
        {"id": t.id, "page_number": t.page_number or None, "table_index": t.table_index, "row_count": t.row_count,
         "column_count": t.column_count, "rows": json.loads(t.table_json), "text": t.table_text,
         "bbox": json.loads(t.bbox_json) if t.bbox_json else None, "extraction_method": t.extraction_method}
        for t in rows]}


@router.get("/{extraction_id}/sections", response_model=dict, dependencies=[Depends(require_tender_analysis_reader)])
def list_sections(extraction_id: int, db: Session = Depends(get_db)) -> dict:
    e = _get_extraction(db, extraction_id)
    rows = db.scalars(select(DocumentSection).where(DocumentSection.extraction_id == e.id)
                      .order_by(DocumentSection.sequence)).all()
    return {"extraction_id": e.id, "source": _source(db, e.document_version_id), "items": [
        {"sequence": s.sequence, "page_number": s.page_number or None, "heading": s.heading,
         "normalized_heading": s.normalized_heading, "heading_level": s.heading_level,
         "detection_method": s.detection_method, "char_offset": s.char_offset, "top": s.top}
        for s in rows]}
