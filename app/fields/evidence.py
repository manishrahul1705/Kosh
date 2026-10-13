"""Evidence model: what Stage 3B reads (Stage 3A rows) and what it produces (candidates).

``load_source`` reads one Stage 3A extraction in ONE short read-only session
(4 queries, no N+1). Everything after that is pure in-memory rule evaluation:
no database transaction is held while rules run.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import (
    DocumentExtraction,
    DocumentPage,
    DocumentSection,
    DocumentTable,
    DocumentVersion,
    Tender,
    TenderDocument,
)
from app.fields.normalizers import Normalized, Rejected


@dataclass(frozen=True)
class SectionRef:
    id: int
    page_number: int
    top: float
    sequence: int
    heading: str
    normalized: str
    method: str
    char_offset: int | None


@dataclass
class TableRef:
    id: int
    page_number: int
    table_index: int
    top: float
    rows: list[list[str | None]]
    section: SectionRef | None = None
    location: dict | None = None


@dataclass
class PageRef:
    page_number: int
    text: str


@dataclass
class Source:
    stage3a_extraction_id: int
    stage3a_status: str
    stage3a_is_current: bool
    document_version_id: int
    document_id: int
    tender_id: int
    bid_number: str
    document_type: str
    version_number: int
    pages: list[PageRef] = field(default_factory=list)
    tables: list[TableRef] = field(default_factory=list)
    sections: list[SectionRef] = field(default_factory=list)
    review_pages: set[int] = field(default_factory=set)
    file_type: str = 'pdf'
    ocr_metadata: dict = field(default_factory=dict)

    def section_before(self, page_number: int, top: float) -> SectionRef | None:
        """Nearest heading at or above (page, top) - the section a table/line belongs to."""
        best = None
        for s in self.sections:  # sections are in document order
            if (s.page_number, s.top) <= (page_number, top):
                best = s
            else:
                break
        return best

    def section_at(self, page_number: int, offset: int) -> SectionRef | None:
        """Last section that starts at or before character ``offset`` of ``page_number``."""
        best = None
        for s in self.sections:
            off = s.char_offset if s.char_offset is not None else 0
            if (s.page_number, off) <= (page_number, offset):
                best = s
            else:
                break
        return best

    def page_text(self, page_number: int) -> str:
        for p in self.pages:
            if p.page_number == page_number:
                return p.text
        return ""

    def section_span(self, start: SectionRef, stop_normalized: tuple[str, ...] = (),
                     stop_at_next: bool = False) -> list[tuple[int, str]]:
        """Text pieces (page_number, text) from ``start`` up to the next section whose
        normalized heading is in ``stop_normalized`` (or simply the next section when
        ``stop_at_next``), or the end of the document."""
        idx = self.sections.index(start)
        end = None
        for s in self.sections[idx + 1:]:
            if stop_at_next or s.normalized in stop_normalized:
                end = s
                break
        pieces = []
        for p in self.pages:
            if p.page_number < start.page_number or (end and p.page_number > end.page_number):
                continue
            text = p.text
            lo = (start.char_offset or 0) if p.page_number == start.page_number else 0
            hi = len(text)
            if end and p.page_number == end.page_number and end.char_offset is not None:
                hi = end.char_offset
            if hi > lo:
                pieces.append((p.page_number, lo, text[lo:hi]))
        return pieces


@dataclass
class Candidate:
    field_name: str
    result: Normalized | Rejected
    raw_value: str | None
    evidence_type: str
    strength: str
    rule: str
    source_label: str | None = None
    page_number: int | None = None
    table_id: int | None = None
    table_index: int | None = None
    row_index: int | None = None
    section_id: int | None = None
    section_heading: str | None = None
    source_text: str | None = None
    source_location: dict | None = None

    @property
    def informative(self) -> bool:
        return isinstance(self.result, Normalized)


def load_source(session: Session, stage3a_extraction_id: int) -> Source | None:
    e = session.get(DocumentExtraction, stage3a_extraction_id)
    if e is None:
        return None
    meta = session.execute(
        select(Tender.bid_number, TenderDocument.document_type, DocumentVersion.version_number,DocumentVersion.extension)
        .join(TenderDocument, TenderDocument.id == DocumentVersion.document_id)
        .join(Tender, Tender.id == TenderDocument.tender_id)
        .where(DocumentVersion.id == e.document_version_id)).one()
    src = Source(stage3a_extraction_id=e.id, stage3a_status=e.status, stage3a_is_current=bool(e.is_current),
                 document_version_id=e.document_version_id, document_id=e.document_id, tender_id=e.tender_id,
                 bid_number=meta.bid_number, document_type=meta.document_type, version_number=meta.version_number)
    src.file_type=(e.parser_version.split(': ')[-1] if (e.parser_version or '').startswith('bounded-supporting-xml-v1: ') else meta.extension or 'pdf')
    src.pages = [PageRef(p, t or "") for p, t in session.execute(
        select(DocumentPage.page_number, DocumentPage.normalized_text)
        .where(DocumentPage.extraction_id == e.id).order_by(DocumentPage.page_number)).all()]
    src.review_pages=set(session.scalars(select(DocumentPage.page_number).where(
        DocumentPage.extraction_id==e.id,DocumentPage.error_code=="LOW_OCR_CONFIDENCE")))
    src.sections = [SectionRef(r.id, r.page_number, r.top if r.top is not None else 0.0, r.sequence, r.heading,
                               r.normalized_heading, r.detection_method, r.char_offset)
                    for r in session.scalars(select(DocumentSection).where(DocumentSection.extraction_id == e.id)
                                             .order_by(DocumentSection.sequence)).all()]
    for section in src.sections:
        if section.method=='OCR_METADATA':src.ocr_metadata[section.page_number]=json.loads(section.heading)
    src.sections=[s for s in src.sections if s.method!='OCR_METADATA']
    for t in session.scalars(select(DocumentTable).where(DocumentTable.extraction_id == e.id)
                             .order_by(DocumentTable.page_number, DocumentTable.table_index)).all():
        bbox = json.loads(t.bbox_json) if t.bbox_json else [0, 0, 0, 0]
        location=bbox.get("location") if isinstance(bbox,dict) else None
        coords=bbox.get("coordinates",[0,0,0,0]) if isinstance(bbox,dict) else bbox
        ref = TableRef(t.id, t.page_number, t.table_index, float(coords[1]), json.loads(t.table_json),location=location)
        ref.section = src.section_before(t.page_number, ref.top)
        src.tables.append(ref)
    return src
