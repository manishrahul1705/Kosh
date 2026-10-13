"""Safe, read-only access to Stage 2 stored files.

Database paths are untrusted: they must be relative, must not contain "..",
and their fully resolved location (symlinks followed) must stay inside the
configured Stage 2 storage root. Files are only ever opened for reading.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path, PurePosixPath

from app.extraction.constants import ErrorCode, ExtractionError

_WINDOWS_DRIVE = re.compile(r"^[A-Za-z]:")
PDF_MAGIC = b"%PDF-"


def resolve_source_path(storage_root: Path, storage_path: str | None) -> Path:
    """Return the absolute path of a stored version file, or raise ExtractionError."""
    if not storage_path or not storage_path.strip():
        raise ExtractionError(ErrorCode.VERSION_NOT_ELIGIBLE, "DocumentVersion has no storage_path")
    rel = storage_path.strip().replace("\\", "/")  # legacy Windows-style rows
    pure = PurePosixPath(rel)
    if pure.is_absolute() or rel.startswith("//") or _WINDOWS_DRIVE.match(rel):
        raise ExtractionError(ErrorCode.UNSAFE_PATH, f"Absolute storage path refused: {storage_path!r}")
    if any(part == ".." for part in pure.parts):
        raise ExtractionError(ErrorCode.UNSAFE_PATH, f"Parent traversal refused: {storage_path!r}")

    root = storage_root.resolve()
    candidate = (root / Path(*pure.parts)).resolve()  # follows symlinks
    try:
        candidate.relative_to(root)
    except ValueError:
        raise ExtractionError(ErrorCode.UNSAFE_PATH, f"Path escapes storage root: {storage_path!r}") from None
    if not candidate.exists():
        raise ExtractionError(ErrorCode.FILE_MISSING, f"Stored file not found: {rel}")
    if not candidate.is_file():
        raise ExtractionError(ErrorCode.FILE_UNREADABLE, f"Stored path is not a regular file: {rel}")
    return candidate


def hash_file(path: Path) -> tuple[str, int]:
    """SHA-256 and size of the file (streamed, read-only)."""
    h = hashlib.sha256()
    size = 0
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
                size += len(chunk)
    except OSError as exc:
        raise ExtractionError(ErrorCode.FILE_UNREADABLE, f"Cannot read stored file: {exc}") from exc
    return h.hexdigest(), size


def sniff_file_type(path: Path) -> str:
    """'pdf' | 'zip' | 'unknown' from content (never from the extension alone)."""
    try:
        with open(path, "rb") as f:
            head = f.read(1024)
    except OSError as exc:
        raise ExtractionError(ErrorCode.FILE_UNREADABLE, f"Cannot read stored file: {exc}") from exc
    if PDF_MAGIC in head:  # the spec allows leading junk before the header
        return "pdf"
    if path.suffix.lower()=='.html':
        from app.documents.formats import inspect_document,DocumentFormatError
        try:return inspect_document(path,expected='html')
        except DocumentFormatError:return 'unknown'
    if head.startswith(b"PK\x03\x04"):
        from app.documents.formats import inspect_document, DocumentFormatError
        try:return inspect_document(path)
        except DocumentFormatError:return "zip"
    from app.documents.formats import inspect_document, DocumentFormatError
    try:return inspect_document(path, expected=path.suffix.lstrip(".") if path.suffix.lower() in {".csv",".txt",".png",".jpg",".jpeg",".doc",".xls",".zip"} else None)
    except DocumentFormatError:pass
    return "unknown"
