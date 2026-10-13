#!/usr/bin/env python
"""Read-only inspection of Stage 3B results (never writes).

    python scripts/inspect_tender_fields.py --list                              # Stage 3A extractions + Stage 3B state
    python scripts/inspect_tender_fields.py --stage3a-extraction-id 1           # all fields (current run)
    python scripts/inspect_tender_fields.py --stage3a-extraction-id 1 --resolved-only
    python scripts/inspect_tender_fields.py --stage3a-extraction-id 1 --evidence [--field past_performance_percentage]
    python scripts/inspect_tender_fields.py --stage3a-extraction-id 1 --conflicts
    python scripts/inspect_tender_fields.py --stage3a-extraction-id 1 --verify-sources
    python scripts/inspect_tender_fields.py --bid GEM/2026/B/8124821
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import select  # noqa: E402

from app.core.config import Settings  # noqa: E402
from app.database.models import (  # noqa: E402
    DocumentExtraction,
    DocumentPage,
    DocumentSection,
    DocumentTable,
    DocumentVersion,
    FieldExtractionJob,
    Tender,
    TenderDocument,
    TenderFieldEvidence,
    TenderFieldExtraction,
    TenderFieldValue,
)
from app.database.session import build_engine, build_session_factory  # noqa: E402
from app.extraction.constants import ExtractionError  # noqa: E402
from app.extraction.storage import hash_file, resolve_source_path  # noqa: E402
from app.fields.service import current_field_extraction_id  # noqa: E402
from app.utils.bid_number import InvalidBidNumber, normalize_bid_number  # noqa: E402


def stage3a_digest(s, extraction_id: int) -> str:
    """SHA-256 over the Stage 3A extraction row and all its pages/tables/sections (read-only)."""
    h = hashlib.sha256()
    e = s.get(DocumentExtraction, extraction_id)
    h.update(repr([getattr(e, c.name) for c in DocumentExtraction.__table__.columns]).encode())
    for model in (DocumentPage, DocumentTable, DocumentSection):
        for row in s.scalars(select(model).where(model.extraction_id == extraction_id).order_by(model.id)):
            h.update(repr([getattr(row, c.name) for c in model.__table__.columns]).encode())
    return h.hexdigest()


def show_list(s) -> None:
    rows = s.execute(select(DocumentExtraction.id, DocumentExtraction.status, DocumentExtraction.is_current,
                            Tender.bid_number, TenderDocument.document_type, DocumentVersion.version_number,
                            DocumentVersion.id)
                     .join(DocumentVersion, DocumentVersion.id == DocumentExtraction.document_version_id)
                     .join(TenderDocument, TenderDocument.id == DocumentVersion.document_id)
                     .join(Tender, Tender.id == TenderDocument.tender_id)
                     .order_by(DocumentExtraction.id)).all()
    print(f"{'stage3a_id':>10}  {'bid_number':<22} {'document':<12} {'ver_id':>6}  {'3A status':<16} stage3b")
    for eid, st, cur, bid, dtype, vn, vid in rows:
        run_id = current_field_extraction_id(s, eid)
        if run_id:
            r = s.get(TenderFieldExtraction, run_id)
            state = f"{r.status} (field_extraction_id {r.id}; {r.fields_resolved} resolved/{r.fields_conflict} conflict)"
        else:
            j = s.scalar(select(FieldExtractionJob).where(FieldExtractionJob.stage3a_extraction_id == eid)
                         .order_by(FieldExtractionJob.id.desc()).limit(1))
            state = f"job {j.id} {j.status}" if j else "-"
        print(f"{eid:>10}  {bid:<22} {dtype + ' v' + str(vn):<12} {vid:>6}  {st + ('' if cur else ' (old)'):<16} {state}")


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except Exception:
            pass
    p = argparse.ArgumentParser(description="Inspect Stage 3B tender fields (read-only)")
    p.add_argument("--list", action="store_true")
    p.add_argument("--stage3a-extraction-id", type=int)
    p.add_argument("--field-extraction-id", type=int, help="a specific (e.g. superseded) Stage 3B run")
    p.add_argument("--bid")
    p.add_argument("--resolved-only", action="store_true")
    p.add_argument("--evidence", action="store_true")
    p.add_argument("--field")
    p.add_argument("--conflicts", action="store_true")
    p.add_argument("--verify-sources", action="store_true")
    a = p.parse_args(argv)
    settings = Settings()
    engine = build_engine(settings.resolved_database_url)
    factory = build_session_factory(engine)
    try:
        with factory() as s:
            if a.list:
                show_list(s)
                return 0
            if a.bid:
                try:
                    bid = normalize_bid_number(a.bid)
                except InvalidBidNumber as exc:
                    print(f"Invalid bid number: {exc}")
                    return 2
                runs = s.scalars(select(TenderFieldExtraction).where(TenderFieldExtraction.bid_number == bid,
                                                                     TenderFieldExtraction.is_current.is_(True))
                                 .order_by(TenderFieldExtraction.version_number.desc())).all()
                if not runs:
                    print(f"No current Stage 3B results for {bid}.")
                    return 0
                run = runs[0]
            elif a.field_extraction_id:
                run = s.get(TenderFieldExtraction, a.field_extraction_id)
            elif a.stage3a_extraction_id:
                rid = current_field_extraction_id(s, a.stage3a_extraction_id)
                run = s.get(TenderFieldExtraction, rid) if rid else None
                if run is None and not a.verify_sources:
                    print(f"No current Stage 3B run for Stage 3A extraction {a.stage3a_extraction_id}.")
                    return 0
            else:
                p.print_help()
                return 2

            eid = run.stage3a_extraction_id if run else a.stage3a_extraction_id
            if a.verify_sources:
                e = s.get(DocumentExtraction, eid)
                v = s.get(DocumentVersion, e.document_version_id)
                print("Source immutability check (read-only):")
                print(f"  Stage 3A extraction {eid}: status={e.status} pages={e.page_count} tables={e.tables_found} "
                      f"sections={e.sections_found}")
                print(f"  Stage 3A row digest: {stage3a_digest(s, eid)}")
                print("    (identical before and after Stage 3B => Stage 3A rows untouched)")
                print(f"  DocumentVersion {v.id}: v{v.version_number} sha256={v.sha256}")
                try:
                    sha, size = hash_file(resolve_source_path(settings.resolved_document_storage_path, v.storage_path))
                    print(f"  PDF on disk:   sha256={sha} size={size}")
                    print(f"  PDF MATCH:     {'YES' if sha == v.sha256 else 'NO'}")
                except ExtractionError as exc:
                    print(f"  PDF check: {exc}")
                if run is None:
                    return 0

            print(f"Tender:   {run.bid_number}")
            print(f"Document: {run.document_type} v{run.version_number}   (document_version_id {run.document_version_id}, "
                  f"Stage 3A extraction {run.stage3a_extraction_id})")
            print(f"Field extraction {run.id}: {run.status}  [{run.extractor_version}, current={run.is_current}]  "
                  f"{run.fields_resolved} resolved | {run.fields_unknown} unknown | {run.fields_conflict} conflict")
            vals = s.scalars(select(TenderFieldValue).where(TenderFieldValue.field_extraction_id == run.id)
                             .order_by(TenderFieldValue.id)).all()
            if a.conflicts:
                vals = [v for v in vals if v.status == "CONFLICT"]
                print(f"\n----- Conflicts ({len(vals)}) -----")
            elif not a.evidence or not a.field:
                print("\n----- Fields -----")
            if not (a.evidence and a.field):
                for v in vals:
                    if a.resolved_only and v.status != "RESOLVED":
                        continue
                    if a.field and v.field_name != a.field:
                        continue
                    shown = v.value_text if v.status == "RESOLVED" else f"<{v.status}: {v.reason}>"
                    tri = f" [{v.tri_state}]" if v.tri_state and v.status == "RESOLVED" else ""
                    unit = f" {v.unit}" if v.unit and v.value_type not in ("DURATION",) else ""
                    print(f"  {v.field_name:40s} {str(shown)[:90]}{unit}{tri}"
                          f"{'  (' + v.evidence_strength + ')' if v.evidence_strength else ''}")
            if a.evidence or a.conflicts:
                names = {v.field_name for v in vals} if a.conflicts else None
                stmt = select(TenderFieldEvidence).where(TenderFieldEvidence.field_extraction_id == run.id)
                if a.field:
                    stmt = stmt.where(TenderFieldEvidence.field_name == a.field)
                rows = [e for e in s.scalars(stmt.order_by(TenderFieldEvidence.id)) if names is None or e.field_name in names]
                print(f"\n----- Evidence ({len(rows)}) -----")
                for e in rows:
                    loc = f"page {e.page_number}" if e.page_number else "metadata"
                    if e.table_index:
                        loc += f", table {e.table_index}, row {e.row_index}"
                    if e.section_heading:
                        loc += f", section '{e.section_heading}'"
                    print(f"  {e.field_name} [{e.disposition}] {e.strength}/{e.evidence_type} rule={e.rule} ({loc})")
                    print(f"      label={e.source_label!r} raw={str(e.raw_value)[:80]!r} "
                          f"normalized={json.loads(e.normalized_json) if e.normalized_json else None}")
        return 0
    finally:
        engine.dispose()


if __name__ == "__main__":
    sys.exit(main())
