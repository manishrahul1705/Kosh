"""Stage 3A extraction service: DocumentVersion -> persisted, traceable extraction.

Two phases, so no database transaction is held while a PDF is parsed:

  prepare(version_id)   short read-only session (version metadata, idempotency
                        check) -> session closed -> safe path resolution -> SHA-256
                        check against the Stage 2 row -> file-type sniff -> page-by-page
                        parse -> normalize -> tables -> headings -> quality -> (OCR if
                        enabled). Result is held in memory.
  persist(session, p)   adds the extraction + pages + tables + sections in the
                        caller's transaction (the worker also finishes the job there,
                        so result and job state commit atomically).

Source files are opened read-only; Stage 2 rows are only read.
"""

from __future__ import annotations

import json
import logging
import time
import math
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.core.logging import log_event
from app.database.models import (
    DocumentExtraction,
    DocumentPage,
    DocumentSection,
    DocumentTable,
    DocumentVersion,
    Tender,
    TenderDocument,
)
from app.extraction.constants import (
    EXTRACTOR_NAME,
    EXTRACTOR_VERSION,
    TABLE_METHOD,
    ErrorCode,
    ExtractionError,
    ExtractionStatus,
    QualityStatus,
    TextClass,
)
from app.extraction.headings import Heading, body_font_size, detect_headings, locate_offsets
from app.extraction.normalize import count_unmapped_glyphs, meaningful_char_count, normalize_text, word_count
from app.extraction.ocr import BaseOCRProvider, OCRResult, get_ocr_provider
from app.extraction.pdf_parser import ParsedTable, PdfPlumberParser, parser_version
from app.extraction.quality import PageQuality, classify
from app.extraction.storage import hash_file, resolve_source_path, sniff_file_type
from app.fields.job_queue import queue_after_stage3a_commit
from app.utils.dates import utcnow

logger = logging.getLogger("app.extraction.service")

ALREADY = "ALREADY_EXTRACTED"
EXTRACTED = "EXTRACTED"
ERROR = "ERROR"


@dataclass
class VersionInfo:
    version_id: int
    document_id: int
    tender_id: int
    bid_number: str
    document_type: str
    document_key: str
    version_number: int
    storage_path: str | None
    sha256: str | None
    validation_status: str


@dataclass
class PageRecord:
    page_number: int
    raw_text: str
    normalized_text: str
    char_count: int
    word_count: int
    meaningful_char_count: int
    has_text: bool
    image_count: int
    unmapped_glyph_count: int
    text_source: str
    width: float | None
    height: float | None
    error_code: str | None
    ocr_metadata: dict | None = None


@dataclass
class ExtractionRecord:
    status: str
    quality_status: str
    text_class: str | None
    error_code: str | None = None
    error_message: str | None = None
    pages: list[PageRecord] = field(default_factory=list)
    tables: list[ParsedTable] = field(default_factory=list)
    sections: list[Heading] = field(default_factory=list)
    page_count: int = 0
    pages_with_text: int = 0
    pages_ocr: int = 0
    total_characters: int = 0
    total_words: int = 0
    images_found: int = 0
    unmapped_glyphs: int = 0
    coverage: float = 0.0
    source_sha256: str | None = None
    source_file_size: int | None = None
    parser_version: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration_ms: int | None = None


@dataclass
class Prepared:
    version_id: int
    force: bool
    info: VersionInfo | None = None
    already_extraction_id: int | None = None
    error: ExtractionError | None = None       # NOT persisted (retryable / not eligible)
    record: ExtractionRecord | None = None     # to persist


@dataclass
class ExtractionOutcome:
    outcome: str                      # EXTRACTED | ALREADY_EXTRACTED | ERROR
    document_version_id: int
    extraction_id: int | None = None
    status: str | None = None         # extraction status when EXTRACTED / ALREADY
    quality_status: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    retryable: bool = False
    page_count: int = 0
    pages_with_text: int = 0
    total_words: int = 0
    total_characters: int = 0
    tables_found: int = 0
    sections_found: int = 0
    duration_ms: int | None = None


def current_extraction_id(session: Session, version_id: int, extractor_version: str = EXTRACTOR_VERSION) -> int | None:
    return session.scalar(select(DocumentExtraction.id).where(
        DocumentExtraction.document_version_id == version_id,
        DocumentExtraction.extractor_version == extractor_version,
        DocumentExtraction.is_current.is_(True)).limit(1))


class ExtractionService:
    def __init__(self, settings: Settings, session_factory: sessionmaker[Session], *,
                 ocr_provider: BaseOCRProvider | None = None, use_default_ocr: bool = True,
                 clock: Callable[[], datetime] = utcnow) -> None:
        self.settings = settings
        self.session_factory = session_factory
        self.storage_root = settings.resolved_document_storage_path
        self.ocr = ocr_provider if ocr_provider is not None else (get_ocr_provider(settings) if use_default_ocr else None)
        self.clock = clock

    # ------------------------------------------------------------------
    def load_version(self, session: Session, version_id: int) -> VersionInfo | None:
        row = session.execute(
            select(DocumentVersion.id, DocumentVersion.document_id, DocumentVersion.version_number,
                   DocumentVersion.storage_path, DocumentVersion.sha256, DocumentVersion.validation_status,
                   TenderDocument.tender_id, TenderDocument.document_type, TenderDocument.document_key,
                   Tender.bid_number)
            .join(TenderDocument, TenderDocument.id == DocumentVersion.document_id)
            .join(Tender, Tender.id == TenderDocument.tender_id)
            .where(DocumentVersion.id == version_id)
        ).one_or_none()
        if row is None:
            return None
        return VersionInfo(row.id, row.document_id, row.tender_id, row.bid_number, row.document_type,
                           row.document_key, row.version_number, row.storage_path, row.sha256, row.validation_status)

    def prepare(self, version_id: int, force: bool = False) -> Prepared:
        prepared = Prepared(version_id=version_id, force=force)
        with self.session_factory() as s:
            info = self.load_version(s, version_id)
            existing = current_extraction_id(s, version_id) if info is not None else None
            s.rollback()  # read-only; release the snapshot before any file work
        if info is None:
            prepared.error = ExtractionError(ErrorCode.VERSION_NOT_FOUND, f"DocumentVersion {version_id} not found")
            return prepared
        prepared.info = info
        if info.validation_status != "VALID":
            prepared.error = ExtractionError(ErrorCode.VERSION_NOT_ELIGIBLE,
                                             f"validation_status is {info.validation_status}, not VALID")
            return prepared
        if existing is not None and not force:
            prepared.already_extraction_id = existing
            return prepared

        started, t0 = self.clock(), time.monotonic()
        log_event(logger, logging.INFO, "extraction_started", document_version_id=version_id,
                  bid=info.bid_number, document=f"{info.document_type} v{info.version_number}", force=force)
        try:
            path = resolve_source_path(self.storage_root, info.storage_path)
            sha, size = hash_file(path)
            if info.sha256 and sha != info.sha256:
                raise ExtractionError(ErrorCode.FILE_HASH_MISMATCH,
                                      f"Stored file SHA-256 {sha[:12]}... differs from DocumentVersion "
                                      f"{info.sha256[:12]}... (Stage 2 must re-acquire)")
            ftype = sniff_file_type(path)
            if ftype in {"docx", "xlsx", "csv", "txt", "html"}:
                from app.extraction.supporting import extract_supporting
                from app.documents.formats import DocumentFormatError
                try: record = extract_supporting(path, ftype, self.settings)
                except DocumentFormatError as exc:
                    record = ExtractionRecord("FAILED", "FAILED", None, str(exc), "Supporting document rejected by bounded extraction")
            elif ftype in {"png", "jpg"}:
                from PIL import Image
                with Image.open(path) as image:
                    page = PageRecord(1,"","",0,0,0,False,1,0,"NONE",image.width,image.height,None)
                done = self._apply_ocr(path,[page],self.settings.extraction_min_page_chars)
                record = self._ocr_record([page],[],[],False,done)
            elif ftype != "pdf":
                record = ExtractionRecord(ExtractionStatus.UNSUPPORTED.value, QualityStatus.UNSUPPORTED.value,
                                          TextClass.UNSUPPORTED.value, ErrorCode.UNSUPPORTED_FILE_TYPE.value,
                                          f"UNSUPPORTED_DOCUMENT_TYPE: {ftype}")
            else:
                record = self._parse_pdf(path)
            record.source_sha256, record.source_file_size = sha, size
        except ExtractionError as exc:
            if exc.retryable:
                prepared.error = exc
                log_event(logger, logging.WARNING, "extraction_failed", document_version_id=version_id,
                          error_code=exc.code, retryable=True)
                return prepared
            record = ExtractionRecord(ExtractionStatus.FAILED.value, QualityStatus.FAILED.value, None,
                                      exc.code, exc.message[:4000])
        record.parser_version = record.parser_version or parser_version()
        record.started_at, record.completed_at = started, self.clock()
        record.duration_ms = int((time.monotonic() - t0) * 1000)
        prepared.record = record
        self._log_result(info, record)
        return prepared

    def _parse_pdf(self, path) -> ExtractionRecord:
        parser = PdfPlumberParser(tables_enabled=self.settings.extraction_tables_enabled)
        total = parser.page_count(path)
        max_pages = self.settings.extraction_max_pages
        min_chars = self.settings.extraction_min_page_chars
        pages: list[PageRecord] = []
        tables: list[ParsedTable] = []
        lines = []
        sizes: Counter = Counter()
        for pp in parser.iter_pages(path, max_pages):
            norm = normalize_text(pp.raw_text)
            meaningful = meaningful_char_count(norm)
            scanned_body=(pp.image_count>0 and pp.image_area_ratio>=self.settings.ocr_large_image_ratio
                          and meaningful<self.settings.ocr_sparse_native_chars)
            pages.append(PageRecord(
                page_number=pp.page_number, raw_text=pp.raw_text, normalized_text=norm, char_count=len(norm),
                word_count=word_count(norm), meaningful_char_count=meaningful, has_text=meaningful >= min_chars and not scanned_body,
                image_count=pp.image_count, unmapped_glyph_count=count_unmapped_glyphs(pp.raw_text),
                text_source="NATIVE" if norm else "NONE", width=pp.width, height=pp.height,
                error_code=pp.error_code))
            tables.extend(pp.tables)
            lines.extend(pp.lines)
            sizes.update(pp.char_sizes)
            log_event(logger, logging.DEBUG, "page_extracted", page=pp.page_number, chars=len(norm),
                      tables=len(pp.tables), error=pp.error_code)
            for t in pp.tables:
                log_event(logger, logging.DEBUG, "table_extracted", page=t.page_number, index=t.table_index,
                          rows=t.row_count, cols=t.column_count)

        pages_ocr = self._apply_ocr(path, pages, min_chars)
        headings = detect_headings(lines, body_font_size(sizes))
        locate_offsets(headings, {p.page_number: p.normalized_text for p in pages})
        return self._ocr_record(pages,tables,headings,total > max_pages,pages_ocr)

    def _ocr_record(self,pages,tables,headings,truncated,pages_ocr):
        q = classify([PageQuality(p.has_text, p.image_count, p.error_code == "PARSER_ERROR") for p in pages],
                     truncated=truncated)
        problems=[p.error_code for p in pages if p.error_code and p.error_code.startswith(("OCR_","LOW_OCR"))]
        if problems:
            q.status="PARTIAL_SUCCESS" if any(p.has_text for p in pages) else "OCR_REQUIRED"
            q.quality="PARTIAL" if any(p.has_text for p in pages) else "OCR_REQUIRED"
            q.error_code=problems[0];q.message="OCR coverage requires review: "+", ".join(sorted(set(problems)))
        for p in pages:
            if p.ocr_metadata:
                headings.append(Heading(p.page_number,len(headings)+1,json.dumps(p.ocr_metadata,sort_keys=True),
                                        "ocr provenance",None,"OCR_METADATA",-1.0,None))
        headings.sort(key=lambda h:(h.page_number,h.top))
        for i,h in enumerate(headings,1):h.sequence=i
        text_class=("MIXED" if any(p.has_text and p.text_source in {"NATIVE","MIXED"} for p in pages) else "OCR") if pages_ocr else q.text_class
        return ExtractionRecord(
            status=q.status, quality_status=q.quality, text_class=text_class, error_code=q.error_code,
            error_message=q.message, pages=pages, tables=tables, sections=headings, page_count=len(pages),
            pages_with_text=sum(p.has_text for p in pages), pages_ocr=pages_ocr,
            total_characters=sum(p.char_count for p in pages), total_words=sum(p.word_count for p in pages),
            images_found=sum(p.image_count for p in pages),
            unmapped_glyphs=sum(p.unmapped_glyph_count for p in pages), coverage=q.coverage)

    def _apply_ocr(self, path, pages: list[PageRecord], min_chars: int) -> int:
        if self.ocr is None:
            return 0
        done = 0
        attempted = 0
        deadline=time.monotonic()+self.settings.ocr_document_timeout_seconds
        if hasattr(self.ocr,'deadline'):self.ocr.deadline=deadline
        for p in pages:
            if p.has_text or p.error_code or not p.image_count:
                continue
            attempted += 1
            if time.monotonic()>=deadline:
                p.error_code='OCR_DOCUMENT_TIMEOUT';continue
            if attempted > self.settings.ocr_max_pages:
                p.error_code="OCR_PAGE_LIMIT";continue
            try:
                result = self.ocr.ocr_page(path, p.page_number)
                if isinstance(result,str):result=OCRResult(result)
                if result.error_code:
                    p.error_code=result.error_code;continue
                text=result.text
            except Exception as exc:
                log_event(logger, logging.WARNING, "ocr_page_failed", page=p.page_number, error=type(exc).__name__)
                p.error_code="OCR_FAILED"
                continue
            norm = normalize_text(text)
            meaningful = meaningful_char_count(norm)
            if meaningful >= min_chars:
                native=p.normalized_text if p.meaningful_char_count>=min_chars else ''
                raw_native=p.raw_text if native else ''
                if native:
                    norm=native+'\n'+norm;text=raw_native+'\n'+text
                    meaningful=meaningful_char_count(norm)
                p.raw_text, p.normalized_text, p.char_count = text, norm, len(norm)
                p.word_count, p.meaningful_char_count, p.has_text = word_count(norm), meaningful, True
                p.text_source = "MIXED" if native else "OCR"
                conf=result.confidence
                valid_conf=isinstance(conf,(int,float)) and not isinstance(conf,bool) and math.isfinite(conf) and 0<=conf<=100
                low=(not result.script_verified or not valid_conf or conf < self.settings.ocr_min_confidence
                     or (result.words and result.low_confidence_words/result.words > self.settings.ocr_max_low_confidence_ratio))
                if low:p.error_code="LOW_OCR_CONFIDENCE"
                p.ocr_metadata={"method":"OCR","engine":self.ocr.name,"confidence":conf if valid_conf else None,
                                "source_method":p.text_source,"ocr_start":len(native)+1 if native else 0,
                                "ocr_end":len(norm),"native_text_preserved":bool(native),
                                "language":result.language,"low_confidence_words":result.low_confidence_words,
                                "script":result.script,"script_verified":result.script_verified,
                                "words":result.words,"review_required":bool(low),"tables_reconstructed":False}
                done += 1
            else:p.error_code="OCR_EMPTY"
        return done

    def _log_result(self, info: VersionInfo, r: ExtractionRecord) -> None:
        event, level = {
            ExtractionStatus.SUCCESS.value: ("extraction_completed", logging.INFO),
            ExtractionStatus.PARTIAL_SUCCESS.value: ("extraction_partial", logging.WARNING),
            ExtractionStatus.OCR_REQUIRED.value: ("extraction_ocr_required", logging.WARNING),
        }.get(r.status, ("extraction_failed", logging.WARNING))
        log_event(logger, level, event, document_version_id=info.version_id, bid=info.bid_number,
                  status=r.status, quality=r.quality_status, pages=r.page_count, pages_with_text=r.pages_with_text,
                  words=r.total_words, tables=len(r.tables), sections=len(r.sections), error_code=r.error_code,
                  duration_ms=r.duration_ms)

    # ------------------------------------------------------------------
    def persist(self, session: Session, prepared: Prepared) -> int:
        """Add the extraction and its children to the caller's transaction (no commit).

        Raises IntegrityError if another current extraction appeared meanwhile.
        """
        r, info = prepared.record, prepared.info
        assert r is not None and info is not None
        now = self.clock()
        if prepared.force:
            session.execute(
                update(DocumentExtraction)
                .where(DocumentExtraction.document_version_id == info.version_id,
                       DocumentExtraction.extractor_version == EXTRACTOR_VERSION,
                       DocumentExtraction.is_current.is_(True))
                .values(is_current=False, updated_at=now)
                .execution_options(synchronize_session=False)
            )
        ext = DocumentExtraction(
            document_version_id=info.version_id, document_id=info.document_id, tender_id=info.tender_id,
            extractor_name=EXTRACTOR_NAME, extractor_version=EXTRACTOR_VERSION, parser_version=r.parser_version,
            status=r.status, quality_status=r.quality_status, text_class=r.text_class, is_current=True,
            source_sha256=r.source_sha256, source_file_size=r.source_file_size, page_count=r.page_count,
            pages_with_text=r.pages_with_text, pages_without_text=r.page_count - r.pages_with_text,
            pages_ocr=r.pages_ocr, total_characters=r.total_characters, total_words=r.total_words,
            tables_found=len(r.tables), sections_found=len(r.sections), images_found=r.images_found,
            unmapped_glyphs=r.unmapped_glyphs, text_coverage_ratio=r.coverage, duration_ms=r.duration_ms,
            error_code=r.error_code, error_message=r.error_message, started_at=r.started_at,
            completed_at=r.completed_at, created_at=now, updated_at=now)
        session.add(ext)
        session.flush()
        vid = info.version_id
        session.add_all([DocumentPage(
            extraction_id=ext.id, document_version_id=vid, page_number=p.page_number, raw_text=p.raw_text,
            normalized_text=p.normalized_text, char_count=p.char_count, word_count=p.word_count,
            meaningful_char_count=p.meaningful_char_count, has_text=p.has_text, image_count=p.image_count,
            unmapped_glyph_count=p.unmapped_glyph_count, text_source=p.text_source, width=p.width,
            height=p.height, error_code=p.error_code, created_at=now) for p in r.pages])
        session.add_all([DocumentTable(
            extraction_id=ext.id, document_version_id=vid, page_number=t.page_number, table_index=t.table_index,
            row_count=t.row_count, column_count=t.column_count, table_json=json.dumps(t.rows, ensure_ascii=False),
            table_text=table_to_text(t.rows), bbox_json=json.dumps({"coordinates":list(t.bbox),"location":t.location} if t.location else list(t.bbox)), extraction_method=t.method or TABLE_METHOD,
            created_at=now) for t in r.tables])
        session.add_all([DocumentSection(
            extraction_id=ext.id, document_version_id=vid, page_number=h.page_number, sequence=h.sequence,
            heading=h.heading, normalized_heading=h.normalized_heading, heading_level=h.heading_level,
            detection_method=h.detection_method, char_offset=h.char_offset, top=h.top, created_at=now)
            for h in r.sections])
        session.flush()
        return ext.id

    # ------------------------------------------------------------------
    def extract_version(self, version_id: int, force: bool = False) -> ExtractionOutcome:
        """prepare + persist + commit (used by CLI/tests; the worker finalizes its job atomically)."""
        p = self.prepare(version_id, force)
        if p.already_extraction_id is not None:
            return self.outcome_for_existing(version_id, p.already_extraction_id)
        if p.error is not None:
            return ExtractionOutcome(ERROR, version_id, error_code=p.error.code, error_message=p.error.message,
                                     retryable=p.error.retryable)
        with self.session_factory() as s:
            try:
                from app.database.session import reserve_sqlite_writer
                reserve_sqlite_writer(s)
                ext_id = self.persist(s, p)
                s.commit()
                queue_after_stage3a_commit(s, ext_id, self.settings)  # Stage 3B; separate commit, never raises
            except IntegrityError:
                s.rollback()
                existing = current_extraction_id(s, version_id)
                return self.outcome_for_existing(version_id, existing)
            except OperationalError as exc:
                s.rollback()
                return ExtractionOutcome(ERROR, version_id, error_code=ErrorCode.DATABASE_ERROR.value,
                                         error_message=str(exc)[:500], retryable=True)
        return outcome_from_record(version_id, ext_id, p.record)

    def outcome_for_existing(self, version_id: int, extraction_id: int | None) -> ExtractionOutcome:
        with self.session_factory() as s:
            e = s.get(DocumentExtraction, extraction_id) if extraction_id else None
            if e is None:
                return ExtractionOutcome(ALREADY, version_id, extraction_id)
            return ExtractionOutcome(ALREADY, version_id, e.id, e.status, e.quality_status, e.error_code,
                                     e.error_message, False, e.page_count, e.pages_with_text, e.total_words,
                                     e.total_characters, e.tables_found, e.sections_found, e.duration_ms)


def outcome_from_record(version_id: int, extraction_id: int, r: ExtractionRecord) -> ExtractionOutcome:
    return ExtractionOutcome(EXTRACTED, version_id, extraction_id, r.status, r.quality_status, r.error_code,
                             r.error_message, False, r.page_count, r.pages_with_text, r.total_words,
                             r.total_characters, len(r.tables), len(r.sections), r.duration_ms)


def table_to_text(rows: list[list[str | None]]) -> str:
    """Search-friendly rendering: cells joined with ' | ', one row per line (cell line breaks -> spaces)."""
    out = []
    for row in rows:
        out.append(" | ".join(" ".join((c or "").split()) for c in row))
    return "\n".join(out)
