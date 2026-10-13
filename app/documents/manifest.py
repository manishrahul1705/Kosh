"""Per-tender manifest.json generation (current version + full version history)."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.database.models import DocumentVersion, Tender, TenderDocument
from app.utils.dates import utcnow


def generate_manifest(db: Session, tender: Tender) -> dict:
    """Build the manifest dict for a tender's documents.

    Each document lists ALL versions (history is never dropped) plus
    ``current_version_id`` / ``current_version_number`` so consumers know which
    version is current.
    """
    manifest: dict = {
        "bid_number": tender.bid_number,
        "tender_id": tender.id,
        "title": tender.title,
        "last_checked": utcnow().isoformat(),
        "documents": [],
    }

    docs = db.scalars(
        select(TenderDocument).where(TenderDocument.tender_id == tender.id).order_by(TenderDocument.id)
    ).all()

    for doc in docs:
        versions = db.scalars(
            select(DocumentVersion)
            .where(DocumentVersion.document_id == doc.id)
            .order_by(DocumentVersion.version_number)
        ).all()

        current = next((v for v in versions if v.id == doc.current_version_id), None)

        entry = {
            "id": doc.id,
            "type": doc.document_type,
            "display_name": doc.display_name,
            "active": doc.is_active,
            "discovered_at": doc.discovered_at.isoformat(),
            "current_version_id": doc.current_version_id,
            "current_version_number": current.version_number if current else None,
            "versions": [],
        }
        for v in versions:
            entry["versions"].append(
                {
                    "id": v.id,
                    "number": v.version_number,
                    "current": v.id == doc.current_version_id,
                    "sha256": v.sha256,
                    "size": v.file_size,
                    "type": v.mime_type,
                    "extension": v.extension,
                    "downloaded_at": v.downloaded_at.isoformat() if v.downloaded_at else None,
                    "validation": v.validation_status,
                    "storage": v.storage_path,
                }
            )
        manifest["documents"].append(entry)

    return manifest


def manifest_path_for(settings: Settings, tender: Tender) -> Path:
    return settings.resolved_document_storage_path / tender.bid_number.replace("/", "_") / "manifest.json"


def write_manifest(settings: Settings, tender: Tender, manifest: dict) -> Path:
    """Atomically write manifest.json (temp file + replace); returns its path."""
    path = manifest_path_for(settings, tender)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".tmp_manifest_", suffix=".json", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)
        os.replace(tmp, path)  # replacing the manifest is intended (it is regenerated state)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return path
