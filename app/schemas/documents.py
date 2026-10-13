"""Stage 2: Document schemas and constants."""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class DocumentType(str, Enum):
    """Normalized document types discovered on tender detail pages."""
    MAIN_BID = "MAIN_BID"
    ATC = "ATC"
    SPECIFICATION = "SPECIFICATION"
    BOQ = "BOQ"
    SCOPE_OF_WORK = "SCOPE_OF_WORK"
    CORRIGENDUM = "CORRIGENDUM"
    ANNEXURE = "ANNEXURE"
    DRAWING = "DRAWING"
    TECHNICAL_DOCUMENT = "TECHNICAL_DOCUMENT"
    ADDITIONAL_DOCUMENT = "ADDITIONAL_DOCUMENT"
    OTHER = "OTHER"
    UNKNOWN = "UNKNOWN"


class DocumentEventType(str, Enum):
    """Document lifecycle events."""
    DISCOVERED = "DISCOVERED"
    DOWNLOADED = "DOWNLOADED"
    UNCHANGED = "UNCHANGED"
    UPDATED = "UPDATED"
    DOWNLOAD_FAILED = "DOWNLOAD_FAILED"
    INVALID_FILE = "INVALID_FILE"
    REMOVED_FROM_SOURCE = "REMOVED_FROM_SOURCE"
    RESTORED = "RESTORED"
    BLOCKED = "BLOCKED"


class DocumentJobStatus(str, Enum):
    """Document job queue statuses."""
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    PARTIAL_SUCCESS = "PARTIAL_SUCCESS"
    FAILED = "FAILED"
    RETRY = "RETRY"
    BLOCKED = "BLOCKED"
    SKIPPED = "SKIPPED"


# Queued = waiting for a worker; Active = queued or being processed.
QUEUED_JOB_STATUSES: tuple[str, ...] = (DocumentJobStatus.PENDING.value, DocumentJobStatus.RETRY.value)
ACTIVE_JOB_STATUSES: tuple[str, ...] = QUEUED_JOB_STATUSES + (DocumentJobStatus.RUNNING.value,)
TERMINAL_JOB_STATUSES: tuple[str, ...] = (
    DocumentJobStatus.SUCCESS.value,
    DocumentJobStatus.PARTIAL_SUCCESS.value,
    DocumentJobStatus.FAILED.value,
    DocumentJobStatus.BLOCKED.value,
    DocumentJobStatus.SKIPPED.value,
)


class DocumentJobReason(str, Enum):
    """Why a DocumentJob exists (document_jobs.reason; NULL = created before Stage 2B)."""
    NEW_TENDER = "NEW_TENDER"
    PERIODIC_REFRESH = "PERIODIC_REFRESH"
    FINAL_REFRESH = "FINAL_REFRESH"
    MANUAL = "MANUAL"
    BACKFILL = "BACKFILL"
    RETRY = "RETRY"


class ValidationStatus(str, Enum):
    """Document validation result."""
    PENDING = "PENDING"
    VALID = "VALID"
    INVALID = "INVALID"
    NOT_ATTEMPTED = "NOT_ATTEMPTED"


class DocumentCandidate(BaseModel):
    """A document discovered on a tender detail page (before download)."""

    model_config = ConfigDict(frozen=True)

    # Classified document type
    document_type: DocumentType
    # Human-readable label found on the page
    display_name: str | None = None
    # Where to download from
    source_url: str
    # Filename from HTML or URL (for storage)
    original_filename: str | None = None
    # Unique key within tender (e.g. "atc_1", "specification")
    document_key: str | None = None


class DocumentVersionOut(BaseModel):
    """A specific version of a document (immutable once created)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    version_number: int
    sha256: str | None = None
    file_size: int | None = None
    mime_type: str | None = None
    extension: str | None = None
    downloaded_at: datetime | None = None
    http_status: int | None = None
    validation_status: str
    created_at: datetime


class DocumentEventOut(BaseModel):
    """A document lifecycle event."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    event_type: str
    old_version_id: int | None = None
    new_version_id: int | None = None
    detected_at: datetime
    details: str | None = None


class DocumentOut(BaseModel):
    """A logical document with its versions and events."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    tender_id: int
    document_key: str
    document_type: str
    display_name: str | None = None
    original_filename: str | None = None
    source_url: str | None = None
    discovered_at: datetime
    last_seen_at: datetime
    is_active: bool
    current_version_id: int | None = None
    created_at: datetime
    updated_at: datetime
    versions: list[DocumentVersionOut] = Field(default_factory=list)
    events: list[DocumentEventOut] = Field(default_factory=list)


class DocumentJobOut(BaseModel):
    """Document discovery/download job status."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    tender_id: int
    status: str
    attempt_count: int
    started_at: datetime | None = None
    finished_at: datetime | None = None
    next_retry_at: datetime | None = None
    error_code: str | None = None
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime
    # Stage 2B
    reason: str | None = None
    locked_by: str | None = None
    outcome: str | None = None
    result_summary: str | None = None
