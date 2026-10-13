"""Stage 3B engine: Source (Stage 3A rows, in memory) -> one FieldResult per registry field.

Pure and deterministic: same Source + same registry => same output. No DB, no I/O.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from app.fields.constants import FieldStatus
from app.fields.derived import derived_candidates
from app.fields.evidence import Candidate, Source
from app.fields.registry import FIELDS
from app.fields.resolver import FieldResult, resolve
from app.fields.rules_table import consignee_candidates, label_value_candidates
from app.fields.rules_text import identity_candidates, page_label_candidates, regex_candidates, section_candidates


@dataclass
class EngineOutput:
    results: list[FieldResult]

    def count(self, status: str) -> int:
        return sum(1 for r in self.results if r.status == status)

    @property
    def resolved(self) -> int:
        return self.count(FieldStatus.RESOLVED.value)

    @property
    def unknown(self) -> int:
        return self.count(FieldStatus.UNKNOWN.value)

    @property
    def conflicts(self) -> int:
        return self.count(FieldStatus.CONFLICT.value)

    @property
    def candidates_total(self) -> int:
        return sum(len(r.candidates) for r in self.results)

    def by_name(self) -> dict[str, FieldResult]:
        return {r.spec.name: r for r in self.results}


def collect_candidates(src: Source, zone: str) -> list[Candidate]:
    cands: list[Candidate] = []
    cands += identity_candidates(src, zone)
    cands += label_value_candidates(src, zone)
    cands += consignee_candidates(src)
    cands += section_candidates(src)
    cands += page_label_candidates(src, zone)
    cands += regex_candidates(src)
    from app.fields.normalizers import Rejected
    for c in cands:
        if c.page_number in src.review_pages:c.result=Rejected("LOW_OCR_CONFIDENCE")
    cands += derived_candidates(cands)
    for c in cands:
        if c.page_number in src.review_pages:
            c.result=Rejected("LOW_OCR_CONFIDENCE")
        if c.page_number==0:
            table=next((t for t in src.tables if t.id==c.table_id),None)
            if table and table.location:
                c.source_location=dict(table.location)
                if c.row_index is not None:
                    c.source_location['row_index']=c.row_index
                    cells=table.location.get('cells',[])
                    if c.row_index<len(cells):c.source_location['cells']=cells[c.row_index]
            else:
                text=src.page_text(0);at=text.find(c.source_text or '')
                section=src.section_at(0,max(0,at))
                if section:c.source_location={'kind':'logical','location':section.heading}
    return cands


def run_engine(src: Source, zone: str = "Asia/Kolkata") -> EngineOutput:
    grouped: dict[str, list[Candidate]] = defaultdict(list)
    for c in collect_candidates(src, zone):
        grouped[c.field_name].append(c)
    return EngineOutput([resolve(spec, grouped.get(spec.name, [])) for spec in FIELDS])
