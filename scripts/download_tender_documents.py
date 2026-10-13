#!/usr/bin/env python3
"""Download and process documents for a single tender by bid number.

Usage:
    python scripts/download_tender_documents.py --bid "GEM/2026/B/8014206"
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import select

from app.core.config import get_settings
from app.database.models import DocumentVersion, Tender, TenderDocument
from app.database.session import build_engine, build_session_factory
from app.documents.documents_service import DocumentsService
from app.documents.manifest import generate_manifest as build_manifest
from app.documents.manifest import write_manifest
from app.utils.bid_number import normalize_bid_number, InvalidBidNumber
from app.utils.dates import utcnow

logger = logging.getLogger("download_tender")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)


def generate_manifest(db, settings, tender: Tender) -> dict:
    """Generate manifest for a tender's documents (kept for compatibility)."""
    return build_manifest(db, tender)


def main():
    # Never crash on a console that cannot encode a character.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except Exception:
            pass
    parser = argparse.ArgumentParser(
        description="Download and process documents for a single tender"
    )
    parser.add_argument(
        "--bid",
        type=str,
        required=True,
        help="Tender bid number (e.g., GEM/2026/B/8014206)",
    )
    parser.add_argument(
        "--page-html",
        type=str,
        help="Path to HTML file for testing (skips live GeM access)",
    )
    args = parser.parse_args()

    # Normalize bid number
    try:
        bid_number = normalize_bid_number(args.bid)
    except InvalidBidNumber as e:
        logger.error(f"Invalid bid number: {e}")
        sys.exit(1)

    settings = get_settings()
    engine = build_engine(settings.resolved_database_url)
    session_factory = build_session_factory(engine)
    db = session_factory()
    exit_code = 0

    try:
        # Find tender
        tender = db.scalar(select(Tender).where(Tender.bid_number == bid_number))
        if not tender:
            logger.error(f"Tender {bid_number} not found")
            sys.exit(1)

        logger.info(f"Processing tender: {tender.bid_number}")
        logger.info(f"Title: {tender.title}")
        logger.info(f"Status: {tender.status}")

        # Load page HTML if provided
        page_html = None
        if args.page_html:
            page_path = Path(args.page_html)
            if not page_path.exists():
                logger.error(f"HTML file not found: {page_path}")
                sys.exit(1)
            with open(page_path, encoding="utf-8") as f:
                page_html = f.read()
            logger.info(f"Using HTML from {page_path}")

        # Perform document discovery and download
        service = DocumentsService(settings)
        result = service.discover_and_download_tender_documents(db, tender.id, page_html)

        # Print results
        print()
        print("=" * 60)
        print(f"TENDER: {tender.bid_number}")
        print("=" * 60)
        print(f"Title: {tender.title}")
        print(f"Status: {tender.status}")
        print()

        outcome = result.get("outcome")
        if result.get("status") == "BLOCKED":
            print("WARNING: Document acquisition BLOCKED (human verification / access denied).")
            print("         Not retried and not bypassed.")
        elif outcome == "TRANSIENT_FAILURE":
            print("FAILED (temporary): GeM/network problem; existing documents are untouched. Try again later.")
        elif outcome == "PERMANENT_FAILURE":
            print("FAILED: document acquisition failed (see errors below).")
        elif outcome == "SUCCESS_NO_DOCUMENTS":
            print("OK: page fetched successfully but no documents were found.")
        if result.get("error"):
            print(f"Reason: {result.get('error')}")
        print(f"Result: {outcome or result.get('status')}")
        print()

        print(f"Documents discovered: {result.get('discovered', 0)}")
        print(f"Documents downloaded: {result.get('downloaded', 0)}")
        print(f"Unchanged: {result.get('unchanged', 0)}")
        print(f"Failed: {result.get('failed', 0)}")

        if result.get("errors"):
            print()
            print("Errors:")
            for error in result["errors"]:
                print(f"  - {error}")

        # Show document status (current version, not just a count)
        db.expire_all()
        docs = db.scalars(
            select(TenderDocument).where(TenderDocument.tender_id == tender.id)
        ).all()

        if docs:
            print()
            print("Document Status:")
            print("-" * 60)
            for doc in sorted(docs, key=lambda d: d.document_type):
                versions = db.scalars(
                    select(DocumentVersion).where(DocumentVersion.document_id == doc.id)
                ).all()
                current = next((v for v in versions if v.id == doc.current_version_id), None)
                shown = current.version_number if current else len(versions)
                active_status = "+" if doc.is_active else "-"
                print(
                    f"{active_status} {doc.document_type:20} v{shown} "
                    f"({len(versions)} stored version(s)) {doc.display_name or ''}"
                )

        # Always regenerate the manifest from the database (truthful current state)
        manifest = build_manifest(db, tender)
        manifest_path = write_manifest(settings, tender, manifest)
        logger.info(f"Manifest saved to {manifest_path}")
        print()
        print(f"Manifest: {manifest_path}")
        print()

        if result.get("status") in ("FAILED", "BLOCKED"):
            exit_code = 3 if result.get("status") == "BLOCKED" else 2
        elif result.get("status") == "PARTIAL_SUCCESS":
            exit_code = 1

    except Exception as e:
        logger.exception(f"Error processing tender: {e}")
        sys.exit(1)

    finally:
        db.close()
        engine.dispose()

    return exit_code


if __name__ == "__main__":
    sys.exit(main() or 0)
