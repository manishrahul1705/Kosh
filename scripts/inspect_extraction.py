#!/usr/bin/env python
"""Read-only inspection of Stage 3A results (never parses, never writes).

    python scripts/inspect_extraction.py --list-versions                    # find VALID versions
    python scripts/inspect_extraction.py --list-versions --bid GEM/2026/B/8124821
    python scripts/inspect_extraction.py --document-version-id 13           # summary
    python scripts/inspect_extraction.py --document-version-id 13 --page 1 --page 2
    python scripts/inspect_extraction.py --document-version-id 13 --tables [--max-tables 5]
    python scripts/inspect_extraction.py --document-version-id 13 --sections
    python scripts/inspect_extraction.py --document-version-id 13 --verify-source
"""

from __future__ import annotations

import argparse
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
    ExtractionJob,
    Tender,
    TenderDocument,
)
from app.database.session import build_engine, build_session_factory  # noqa: E402
from app.extraction.constants import ExtractionError  # noqa: E402
from app.extraction.service import current_extraction_id  # noqa: E402
from app.extraction.storage import hash_file, resolve_source_path  # noqa: E402
from app.utils.bid_number import InvalidBidNumber, normalize_bid_number  # noqa: E402


def list_versions(s, bid: str | None, limit: int) -> None:
    stmt = (select(DocumentVersion.id, Tender.bid_number, TenderDocument.document_type, DocumentVersion.version_number,
                   DocumentVersion.validation_status, DocumentVersion.file_size, DocumentVersion.storage_path)
            .join(TenderDocument, TenderDocument.id == DocumentVersion.document_id)
            .join(Tender, Tender.id == TenderDocument.tender_id)
            .order_by(DocumentVersion.id.desc()).limit(limit))
    if bid:
        stmt = stmt.where(Tender.bid_number == bid)
    rows = s.execute(stmt).all()
    print(f"{'version_id':>10}  {'bid_number':<22} {'document':<12} {'valid':<7} {'bytes':>8}  extraction")
    for vid, b, dtype, vn, valid, size, _path in rows:
        ext_id = current_extraction_id(s, vid)
        state = "-"
        if ext_id:
            e = s.get(DocumentExtraction, ext_id)
            state = f"{e.status} (id {e.id})"
        else:
            job = s.scalar(select(ExtractionJob).where(ExtractionJob.document_version_id == vid)
                           .order_by(ExtractionJob.id.desc()).limit(1))
            if job:
                state = f"job {job.id} {job.status}"
        print(f"{vid:>10}  {b:<22} {dtype + ' v' + str(vn):<12} {valid:<7} {size or 0:>8}  {state}")
    if not rows:
        print("No document versions found.")


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except Exception:
            pass
    p = argparse.ArgumentParser(description="Inspect Stage 3A extraction results (read-only)")
    p.add_argument("--list-versions", action="store_true")
    p.add_argument("--bid")
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--document-version-id", type=int)
    p.add_argument("--extraction-id", type=int, help="inspect a specific (e.g. superseded) extraction")
    p.add_argument("--page", type=int, action="append", help="1-based page number (repeatable)")
    p.add_argument("--raw", action="store_true", help="with --page: show raw_text instead of normalized_text")
    p.add_argument("--max-chars", type=int, default=1500)
    p.add_argument("--tables", action="store_true")
    p.add_argument("--max-tables", type=int, default=5)
    p.add_argument("--sections", action="store_true")
    p.add_argument("--verify-source", action="store_true",
                   help="re-hash the stored file and compare with Stage 2's DocumentVersion")
    args = p.parse_args(argv)

    settings = Settings()
    engine = build_engine(settings.resolved_database_url)
    factory = build_session_factory(engine)
    try:
        with factory() as s:
            if args.list_versions:
                bid = None
                if args.bid:
                    try:
                        bid = normalize_bid_number(args.bid)
                    except InvalidBidNumber as exc:
                        print(f"Invalid bid number: {exc}")
                        return 2
                list_versions(s, bid, args.limit)
                return 0
            if not args.document_version_id and not args.extraction_id:
                p.print_help()
                return 2
            if args.extraction_id:
                e = s.get(DocumentExtraction, args.extraction_id)
            else:
                ext_id = current_extraction_id(s, args.document_version_id)
                e = s.get(DocumentExtraction, ext_id) if ext_id else None
            vid = e.document_version_id if e else args.document_version_id
            v = s.get(DocumentVersion, vid)
            if v is None:
                print(f"DocumentVersion {vid} not found.")
                return 2
            doc = s.get(TenderDocument, v.document_id)
            tender = s.get(Tender, doc.tender_id)
            print(f"Tender:   {tender.bid_number}")
            print(f"Document: {doc.document_type} v{v.version_number}   (document_version_id {v.id})")
            if args.verify_source:
                print("\nSource integrity (Stage 2 DocumentVersion vs. file on disk):")
                print(f"  storage_path:   {v.storage_path}")
                print(f"  version_number: {v.version_number}")
                print(f"  DB sha256:      {v.sha256}")
                try:
                    path = resolve_source_path(settings.resolved_document_storage_path, v.storage_path)
                    sha, size = hash_file(path)
                    print(f"  file sha256:    {sha}")
                    print(f"  file size:      {size} (DB {v.file_size})")
                    print(f"  MATCH:          {'YES' if sha == v.sha256 and size == v.file_size else 'NO'}")
                except ExtractionError as exc:
                    print(f"  ERROR: {exc}")
                if e is not None:
                    print(f"  extraction parsed sha256: {e.source_sha256} -> "
                          f"{'same bytes' if e.source_sha256 == v.sha256 else 'DIFFERENT'}")
            if e is None:
                print("\nNo current extraction for this version yet.")
                return 0
            print(f"\nExtraction: {e.status}   (extraction_id {e.id}, {e.extractor_version}, current={e.is_current})")
            print(f"Pages: {e.page_count}   Pages with text: {e.pages_with_text}   Words: {e.total_words}   "
                  f"Characters: {e.total_characters}")
            print(f"Tables: {e.tables_found}   Sections: {e.sections_found}   Quality: {e.quality_status}   "
                  f"text_class: {e.text_class}")
            if e.error_code:
                print(f"Note: {e.error_code}: {e.error_message}")
            for n in args.page or []:
                pg = s.scalar(select(DocumentPage).where(DocumentPage.extraction_id == e.id,
                                                         DocumentPage.page_number == n))
                print(f"\n----- Page {n} " + ("(raw_text)" if args.raw else "(normalized_text)") + " -----")
                if pg is None:
                    print("(no such page)")
                    continue
                text = (pg.raw_text if args.raw else pg.normalized_text) or ""
                print(f"[chars={pg.char_count} words={pg.word_count} has_text={pg.has_text} source={pg.text_source}]")
                print(text[: args.max_chars] + (" ..." if len(text) > args.max_chars else ""))
            if args.tables:
                rows = s.scalars(select(DocumentTable).where(DocumentTable.extraction_id == e.id)
                                 .order_by(DocumentTable.page_number, DocumentTable.table_index)).all()
                print(f"\n----- Tables ({len(rows)}; showing {min(len(rows), args.max_tables)}) -----")
                for t in rows[: args.max_tables]:
                    print(f"\nPage {t.page_number}, table {t.table_index}: {t.row_count} x {t.column_count}")
                    for row in json.loads(t.table_json):
                        print("  | " + " | ".join(" ".join((c or "").split())[:60] for c in row))
            if args.sections:
                rows = s.scalars(select(DocumentSection).where(DocumentSection.extraction_id == e.id)
                                 .order_by(DocumentSection.sequence)).all()
                print(f"\n----- Sections ({len(rows)}) -----")
                for h in rows:
                    print(f"  {h.sequence:>3}. page {h.page_number:<3} L{h.heading_level or '-'} "
                          f"[{h.detection_method}] {h.normalized_heading}")
        return 0
    finally:
        engine.dispose()


if __name__ == "__main__":
    sys.exit(main())
