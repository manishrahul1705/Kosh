"""Safe serving of stored tender document files (shared by documents + portal APIs)."""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import HTTPException
from fastapi.responses import FileResponse

from app.database.models import DocumentVersion

logger = logging.getLogger("app.api.file_access")


def stored_file_response(storage_root: Path, version: DocumentVersion) -> FileResponse:
    """Serve a stored document version as an attachment.

    * Only paths recorded in the database are used (no client-supplied path).
    * The resolved path must stay inside the storage root (no traversal or symlink escape).
    * Files are always sent as attachments with ``nosniff``, so an untrusted file is
      never rendered inline by the browser.
    """
    if not version.storage_path:
        raise HTTPException(status_code=404, detail="File not available")
    try:
        root = storage_root.resolve()
        file_path = (root / version.storage_path).resolve()
    except (ValueError, OSError):
        raise HTTPException(status_code=403, detail="Access denied") from None
    if not file_path.is_relative_to(root):
        logger.warning("document_path_outside_storage version_id=%s", version.id)
        raise HTTPException(status_code=403, detail="Access denied")
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    filename = Path(version.storage_path).name or f"document_v{version.version_number}"
    return FileResponse(
        file_path,
        media_type="application/octet-stream",
        filename=filename,
        content_disposition_type="attachment",
        headers={"X-Content-Type-Options": "nosniff"},
    )
