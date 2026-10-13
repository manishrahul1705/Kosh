"""SQLAlchemy 2.x ORM models.

Portable types only (no SQLite-specific DDL) so the same models and Alembic
migrations run on PostgreSQL. Timestamps are naive UTC (see app/utils/dates).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    Numeric,
    String,
    Text,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.utils.dates import utcnow

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_name)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

# BIGINT on PostgreSQL, INTEGER on SQLite (keeps SQLite autoincrement rowid).
PK = BigInteger().with_variant(Integer(), "sqlite")


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class CollectionRun(Base):
    __tablename__ = "collection_runs"

    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    pages_checked: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    bids_seen: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    new_bids: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    updated_bids: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    unchanged_bids: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failed_items: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text)
    trigger_type: Mapped[str] = mapped_column(String(20), nullable=False)


class Tender(Base):
    __tablename__ = "tenders"

    # Stable surrogate key: Stage 2 (documents) references tenders.id.
    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    bid_number: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    title: Mapped[str | None] = mapped_column(Text)
    bid_type: Mapped[str | None] = mapped_column(String(32))
    buyer_name: Mapped[str | None] = mapped_column(Text)
    ministry: Mapped[str | None] = mapped_column(Text)
    department: Mapped[str | None] = mapped_column(Text)
    organisation: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(String(512), index=True)
    quantity: Mapped[int | None] = mapped_column(BigInteger)
    estimated_value: Mapped[Decimal | None] = mapped_column(Numeric(20, 2))
    published_at: Mapped[datetime | None] = mapped_column(DateTime)
    bid_end_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    bid_opening_at: Mapped[datetime | None] = mapped_column(DateTime)
    source_url: Mapped[str | None] = mapped_column(Text)
    source_internal_id: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="UNKNOWN", index=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    last_changed_at: Mapped[datetime | None] = mapped_column(DateTime)
    source_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    changes: Mapped[list["TenderChange"]] = relationship(
        back_populates="tender", cascade="all, delete-orphan", order_by="TenderChange.id"
    )
    # Deterministic current state (see app.services.status_service). Kept in its own
    # table so ``status`` stays exactly what the GeM source reported.
    status_record: Mapped["TenderStatusRecord | None"] = relationship(
        back_populates="tender", uselist=False, cascade="all, delete-orphan"
    )

    @property
    def current_status(self) -> str:
        return self.status_record.current_status if self.status_record else "UNKNOWN"

    @property
    def status_source(self) -> str | None:
        return self.status_record.status_source if self.status_record else None

    @property
    def last_status_check_at(self) -> datetime | None:
        return self.status_record.last_status_check_at if self.status_record else None


class TenderChange(Base):
    __tablename__ = "tender_changes"
    __table_args__ = (Index("ix_tender_changes_tender_detected", "tender_id", "detected_at"),)

    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    tender_id: Mapped[int] = mapped_column(
        PK, ForeignKey("tenders.id", ondelete="CASCADE"), nullable=False, index=True
    )
    field_name: Mapped[str] = mapped_column(String(64), nullable=False)
    old_value: Mapped[str | None] = mapped_column(Text)
    new_value: Mapped[str | None] = mapped_column(Text)
    detected_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    collection_run_id: Mapped[int | None] = mapped_column(
        PK, ForeignKey("collection_runs.id", ondelete="SET NULL"), index=True
    )

    tender: Mapped[Tender] = relationship(back_populates="changes")


class TenderStatusRecord(Base):
    """Current deterministic status of a tender (migration 0018). One row per tender.

    LIVE | UPCOMING | CLOSED | CANCELLED | UNKNOWN, derived from the source status and the
    deadline by app.services.status_service (never by an LLM).
    """
    __tablename__ = "tender_status"

    tender_id: Mapped[int] = mapped_column(PK, ForeignKey("tenders.id", ondelete="CASCADE"), primary_key=True)
    current_status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    status_source: Mapped[str] = mapped_column(String(40), nullable=False)
    last_status_check_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    changed_at: Mapped[datetime | None] = mapped_column(DateTime)

    tender: Mapped[Tender] = relationship(back_populates="status_record")


class TenderStatusEvent(Base):
    """History of current-status transitions (what changed, when, and why)."""
    __tablename__ = "tender_status_events"
    __table_args__ = (Index("ix_tender_status_events_tender_detected", "tender_id", "detected_at"),)

    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    tender_id: Mapped[int] = mapped_column(PK, ForeignKey("tenders.id", ondelete="CASCADE"), nullable=False)
    old_status: Mapped[str | None] = mapped_column(String(20))
    new_status: Mapped[str] = mapped_column(String(20), nullable=False)
    status_source: Mapped[str] = mapped_column(String(40), nullable=False)
    detected_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)

    tender: Mapped[Tender] = relationship()


# ============================================================================
# STAGE 2: DOCUMENT ACQUISITION & VERSION MANAGEMENT
# ============================================================================


class TenderDocument(Base):
    """Logical document attached to a tender (main bid, ATC, specification, etc).
    
    A document may have multiple versions (content changed).
    Each version has a unique content hash.
    """
    __tablename__ = "tender_documents"
    __table_args__ = (
        Index("ix_tender_documents_tender_document_key", "tender_id", "document_key"),
        Index("ix_tender_documents_type", "document_type"),
    )

    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    tender_id: Mapped[int] = mapped_column(
        PK, ForeignKey("tenders.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Unique identifier within this tender (e.g. "main_bid", "atc_1", "specification_v2")
    document_key: Mapped[str] = mapped_column(String(128), nullable=False)
    # Document type: MAIN_BID, ATC, SPECIFICATION, BOQ, SCOPE_OF_WORK, etc
    document_type: Mapped[str] = mapped_column(String(40), nullable=False)
    # Human-readable label discovered from the page (e.g. "Buyer Added ATC")
    display_name: Mapped[str | None] = mapped_column(Text)
    # Original filename from Content-Disposition or URL (e.g. "RFQ_2026.pdf")
    original_filename: Mapped[str | None] = mapped_column(Text)
    # GeM or other source URL where document was discovered
    source_url: Mapped[str | None] = mapped_column(Text)
    # Foreign key to current version (latest)
    current_version_id: Mapped[int | None] = mapped_column(
        PK, ForeignKey("document_versions.id", ondelete="SET NULL"), index=True
    )
    # When this document was first discovered
    discovered_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    # When this document was last seen during a scan
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    # Whether this document is currently active (true = expected to exist on GeM)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    tender: Mapped[Tender] = relationship(back_populates="documents")
    versions: Mapped[list["DocumentVersion"]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        order_by="DocumentVersion.version_number",
        foreign_keys="DocumentVersion.document_id",
    )
    events: Mapped[list["DocumentEvent"]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        order_by="DocumentEvent.detected_at",
        foreign_keys="DocumentEvent.document_id",
    )


class DocumentVersion(Base):
    """Immutable record of a document's content at a point in time.
    
    When content changes (hash changes), a new version is created.
    If content is unchanged, no new version is created.
    """
    __tablename__ = "document_versions"
    __table_args__ = (
        Index("ix_document_versions_document_sha256", "document_id", "sha256"),
        Index("ix_document_versions_validation", "validation_status"),
        # Stage 2B (0003): DB-level race safety for Stage 2A's dedup/versioning.
        # (Created by the migration only when existing data has no duplicates.)
        Index("uq_document_versions_document_version", "document_id", "version_number", unique=True),
        Index("uq_document_versions_document_sha256", "document_id", "sha256", unique=True),
    )

    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    document_id: Mapped[int] = mapped_column(
        PK, ForeignKey("tender_documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Version number within this document (1, 2, 3, ...)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    # SHA-256 hash of file content (for deduplication and integrity)
    sha256: Mapped[str | None] = mapped_column(String(64), index=True)
    # File size in bytes
    file_size: Mapped[int | None] = mapped_column(BigInteger)
    # MIME type detected from content (e.g. "application/pdf")
    mime_type: Mapped[str | None] = mapped_column(String(128))
    # File extension (e.g. "pdf", "xlsx", "docx")
    extension: Mapped[str | None] = mapped_column(String(32))
    # Local filesystem path where file is stored (relative to storage root)
    storage_path: Mapped[str | None] = mapped_column(Text)
    # URL where this version was originally found
    source_url: Mapped[str | None] = mapped_column(Text)
    # Final resolved URL (after redirects)
    final_url: Mapped[str | None] = mapped_column(Text)
    # When the file was successfully downloaded
    downloaded_at: Mapped[datetime | None] = mapped_column(DateTime)
    # HTTP status code when downloaded
    http_status: Mapped[int | None] = mapped_column(Integer)
    # Validation status: VALID, INVALID, PENDING, NOT_ATTEMPTED
    validation_status: Mapped[str] = mapped_column(String(20), default="PENDING", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    document: Mapped[TenderDocument] = relationship(
        back_populates="versions",
        foreign_keys=[document_id],
    )


class DocumentEvent(Base):
    """Audit trail for document lifecycle events.
    
    Tracks: DISCOVERED, DOWNLOADED, UNCHANGED, UPDATED, DOWNLOAD_FAILED,
    INVALID_FILE, REMOVED_FROM_SOURCE, RESTORED, BLOCKED.
    """
    __tablename__ = "document_events"
    __table_args__ = (
        Index("ix_document_events_detected", "document_id", "detected_at"),
        Index("ix_document_events_type", "event_type"),
    )

    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    document_id: Mapped[int] = mapped_column(
        PK, ForeignKey("tender_documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Event type enum
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    # Version before change (if applicable, e.g. for UPDATED)
    old_version_id: Mapped[int | None] = mapped_column(
        PK, ForeignKey("document_versions.id", ondelete="SET NULL")
    )
    # Version after change (if applicable, e.g. for UPDATED or DOWNLOADED)
    new_version_id: Mapped[int | None] = mapped_column(
        PK, ForeignKey("document_versions.id", ondelete="SET NULL")
    )
    # When event was detected
    detected_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    # Optional reference to which collection run scanned this (if from async scanning)
    collection_run_id: Mapped[int | None] = mapped_column(
        PK, ForeignKey("collection_runs.id", ondelete="SET NULL"), index=True
    )
    # Free-form details (error message, reasoning, etc)
    details: Mapped[str | None] = mapped_column(Text)

    document: Mapped[TenderDocument] = relationship(
        back_populates="events",
        foreign_keys=[document_id],
    )


class DocumentJob(Base):
    """Queue entry for document discovery/download work.
    
    When a new tender is discovered, a job is created.
    Jobs can be processed immediately or queued for later.
    """
    __tablename__ = "document_jobs"
    __table_args__ = (
        Index("ix_document_jobs_status", "status"),
        Index("ix_document_jobs_tender", "tender_id", "status"),
        # Stage 2B (0003): claim scan + at most ONE queued job per tender.
        Index("ix_document_jobs_status_next_retry", "status", "next_retry_at"),
        Index(
            "uq_document_jobs_tender_queued",
            "tender_id",
            unique=True,
            sqlite_where=text("status IN ('PENDING', 'RETRY')"),
            postgresql_where=text("status IN ('PENDING', 'RETRY')"),
        ),
    )

    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    tender_id: Mapped[int] = mapped_column(
        PK, ForeignKey("tenders.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Job status: PENDING, RUNNING, SUCCESS, PARTIAL_SUCCESS, FAILED, RETRY, BLOCKED, SKIPPED
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING")
    # How many times this job has been attempted
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # When job started execution
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    # When job finished (regardless of status)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    # When to retry this job (if transient failure)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime)
    # Error code (HTTP status, exception class, etc)
    error_code: Mapped[str | None] = mapped_column(String(40))
    # Human-readable error message
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)
    # --- Stage 2B (migration 0003) ---------------------------------------
    # Why the job exists: NEW_TENDER | PERIODIC_REFRESH | FINAL_REFRESH | MANUAL |
    # BACKFILL | RETRY.  NULL = created before Stage 2B.
    reason: Mapped[str | None] = mapped_column(String(32))
    # Worker identity ("host:pid:token") that claimed the RUNNING job.
    locked_by: Mapped[str | None] = mapped_column(String(128))
    # Stage 2A outcome of the last attempt (SUCCESS_WITH_DOCUMENTS, TRANSIENT_FAILURE, ...)
    outcome: Mapped[str | None] = mapped_column(String(40))
    # JSON counters of the last attempt: discovered/downloaded/unchanged/failed.
    result_summary: Mapped[str | None] = mapped_column(Text)

    tender: Mapped[Tender] = relationship(
        back_populates="document_jobs",
        foreign_keys=[tender_id],
    )


# Update Tender to include relationship back to documents and jobs
Tender.documents = relationship(
    "TenderDocument", back_populates="tender", cascade="all, delete-orphan"
)
Tender.document_jobs = relationship(
    "DocumentJob", back_populates="tender", cascade="all, delete-orphan"
)


# ============================================================================
# STAGE 3A: DOCUMENT TEXT / TABLE / STRUCTURE EXTRACTION (migration 0004)
# ============================================================================
# Derived data only: Stage 2 rows and files are never modified. Every row carries
# document_version_id (and pages/tables/sections carry page_number, 1-based) so
# later stages can always cite "MAIN_BID v1, page 6".

_CURRENT_SQLITE = text("is_current = 1")
_CURRENT_PG = text("is_current IS TRUE")
_QUEUED_EXTRACTION = text("status IN ('PENDING', 'RETRY')")


class DocumentExtraction(Base):
    """One extraction run of one immutable DocumentVersion by one extractor version."""

    __tablename__ = "document_extractions"
    __table_args__ = (
        # Idempotency: at most one CURRENT extraction per (version, extractor_version).
        Index("uq_document_extractions_version_current", "document_version_id", "extractor_version",
              unique=True, sqlite_where=_CURRENT_SQLITE, postgresql_where=_CURRENT_PG),
        Index("ix_document_extractions_status", "status"),
        Index("ix_document_extractions_quality", "quality_status"),
    )

    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    document_version_id: Mapped[int] = mapped_column(
        PK, ForeignKey("document_versions.id", ondelete="CASCADE"), nullable=False, index=True)
    document_id: Mapped[int] = mapped_column(
        PK, ForeignKey("tender_documents.id", ondelete="CASCADE"), nullable=False, index=True)
    tender_id: Mapped[int] = mapped_column(
        PK, ForeignKey("tenders.id", ondelete="CASCADE"), nullable=False, index=True)
    extractor_name: Mapped[str] = mapped_column(String(40), nullable=False)
    extractor_version: Mapped[str] = mapped_column(String(40), nullable=False)
    parser_version: Mapped[str | None] = mapped_column(String(80))
    # SUCCESS | PARTIAL_SUCCESS | OCR_REQUIRED | FAILED | UNSUPPORTED
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    # GOOD | PARTIAL | OCR_REQUIRED | EMPTY | FAILED | UNSUPPORTED
    quality_status: Mapped[str] = mapped_column(String(20), nullable=False)
    # TEXT_NATIVE | TEXT_PARTIAL | LIKELY_SCANNED | EMPTY | UNSUPPORTED
    text_class: Mapped[str | None] = mapped_column(String(20))
    # False once superseded by a forced re-extraction (kept as history).
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Integrity: hash/size of the exact bytes that were parsed.
    source_sha256: Mapped[str | None] = mapped_column(String(64))
    source_file_size: Mapped[int | None] = mapped_column(BigInteger)
    page_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    pages_with_text: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    pages_without_text: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    pages_ocr: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_characters: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    total_words: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    tables_found: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sections_found: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    images_found: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    unmapped_glyphs: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # pages_with_text / page_count (0 when there are no pages)
    text_coverage_ratio: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    error_code: Mapped[str | None] = mapped_column(String(40))
    error_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)


class DocumentPage(Base):
    """Text of one page (1-based page_number) of one extraction."""

    __tablename__ = "document_pages"
    __table_args__ = (
        Index("uq_document_pages_extraction_page", "extraction_id", "page_number", unique=True),
        Index("ix_document_pages_version_page", "document_version_id", "page_number"),
    )

    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    extraction_id: Mapped[int] = mapped_column(
        PK, ForeignKey("document_extractions.id", ondelete="CASCADE"), nullable=False, index=True)
    document_version_id: Mapped[int] = mapped_column(
        PK, ForeignKey("document_versions.id", ondelete="CASCADE"), nullable=False)
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    raw_text: Mapped[str | None] = mapped_column(Text)
    normalized_text: Mapped[str | None] = mapped_column(Text)
    char_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    word_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    meaningful_char_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    has_text: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    image_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    unmapped_glyph_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # NATIVE (PDF text layer) | OCR | NONE
    text_source: Mapped[str] = mapped_column(String(10), nullable=False, default="NATIVE")
    width: Mapped[float | None] = mapped_column(Float)
    height: Mapped[float | None] = mapped_column(Float)
    error_code: Mapped[str | None] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


class DocumentTable(Base):
    """A table found on a page, stored as a JSON grid of cells (null = empty/merged cell)."""

    __tablename__ = "document_tables"
    __table_args__ = (
        Index("uq_document_tables_extraction_page_index", "extraction_id", "page_number", "table_index",
              unique=True),
        Index("ix_document_tables_version_page", "document_version_id", "page_number"),
    )

    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    extraction_id: Mapped[int] = mapped_column(
        PK, ForeignKey("document_extractions.id", ondelete="CASCADE"), nullable=False, index=True)
    document_version_id: Mapped[int] = mapped_column(
        PK, ForeignKey("document_versions.id", ondelete="CASCADE"), nullable=False)
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    table_index: Mapped[int] = mapped_column(Integer, nullable=False)  # 1-based within the page
    row_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    column_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    table_json: Mapped[str] = mapped_column(Text, nullable=False)
    table_text: Mapped[str | None] = mapped_column(Text)  # search-friendly rendering
    bbox_json: Mapped[str | None] = mapped_column(Text)
    extraction_method: Mapped[str] = mapped_column(String(40), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


class DocumentSection(Base):
    """A detected heading (section start), in document order."""

    __tablename__ = "document_sections"
    __table_args__ = (
        Index("uq_document_sections_extraction_sequence", "extraction_id", "sequence", unique=True),
        Index("ix_document_sections_normalized", "normalized_heading"),
    )

    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    extraction_id: Mapped[int] = mapped_column(
        PK, ForeignKey("document_extractions.id", ondelete="CASCADE"), nullable=False, index=True)
    document_version_id: Mapped[int] = mapped_column(
        PK, ForeignKey("document_versions.id", ondelete="CASCADE"), nullable=False)
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)  # 1-based, document order
    heading: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_heading: Mapped[str] = mapped_column(String(255), nullable=False)
    heading_level: Mapped[int | None] = mapped_column(Integer)
    detection_method: Mapped[str] = mapped_column(String(30), nullable=False)
    char_offset: Mapped[int | None] = mapped_column(Integer)  # offset in page normalized_text
    top: Mapped[float | None] = mapped_column(Float)  # y position on the page (PDF points)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


class ExtractionJob(Base):
    """Queue entry for Stage 3A extraction of one DocumentVersion (Stage 2B pattern)."""

    __tablename__ = "extraction_jobs"
    __table_args__ = (
        Index("ix_extraction_jobs_status_next_retry", "status", "next_retry_at"),
        Index("uq_extraction_jobs_version_queued", "document_version_id", unique=True,
              sqlite_where=_QUEUED_EXTRACTION, postgresql_where=_QUEUED_EXTRACTION),
    )

    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    document_version_id: Mapped[int] = mapped_column(
        PK, ForeignKey("document_versions.id", ondelete="CASCADE"), nullable=False, index=True)
    # PENDING | RUNNING | SUCCESS | PARTIAL_SUCCESS | RETRY | FAILED | OCR_REQUIRED | SKIPPED
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING")
    # NEW_VERSION | BACKFILL | MANUAL | REEXTRACT
    reason: Mapped[str | None] = mapped_column(String(32))
    force: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime)
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    locked_by: Mapped[str | None] = mapped_column(String(128))
    outcome: Mapped[str | None] = mapped_column(String(40))
    error_code: Mapped[str | None] = mapped_column(String(40))
    error_message: Mapped[str | None] = mapped_column(Text)
    extraction_id: Mapped[int | None] = mapped_column(
        PK, ForeignKey("document_extractions.id", ondelete="SET NULL"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)


# ============================================================================
# STAGE 3B: DETERMINISTIC TENDER FIELD EXTRACTION (migration 0005)
# ============================================================================
# Interpretation layer above Stage 3A. Reads Stage 3A rows only; never touches
# Stage 2 files or Stage 3A rows. One run = one Stage 3A extraction (= one
# DocumentVersion) x one field-extractor version; history is kept (is_current).

_QUEUED_FIELD_JOB = text("status IN ('PENDING', 'RETRY')")


class TenderFieldExtraction(Base):
    __tablename__ = "tender_field_extractions"
    __table_args__ = (
        Index("uq_tender_field_extractions_source_current", "stage3a_extraction_id", "extractor_version",
              unique=True, sqlite_where=_CURRENT_SQLITE, postgresql_where=_CURRENT_PG),
        Index("ix_tender_field_extractions_status", "status"),
        Index("ix_tender_field_extractions_bid_number", "bid_number"),
    )

    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    stage3a_extraction_id: Mapped[int] = mapped_column(
        PK, ForeignKey("document_extractions.id", ondelete="CASCADE"), nullable=False, index=True)
    document_version_id: Mapped[int] = mapped_column(
        PK, ForeignKey("document_versions.id", ondelete="CASCADE"), nullable=False, index=True)
    document_id: Mapped[int] = mapped_column(
        PK, ForeignKey("tender_documents.id", ondelete="CASCADE"), nullable=False)
    tender_id: Mapped[int] = mapped_column(
        PK, ForeignKey("tenders.id", ondelete="CASCADE"), nullable=False, index=True)
    bid_number: Mapped[str] = mapped_column(String(64), nullable=False)
    document_type: Mapped[str] = mapped_column(String(40), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    extractor_name: Mapped[str] = mapped_column(String(40), nullable=False)
    extractor_version: Mapped[str] = mapped_column(String(40), nullable=False)
    # SUCCESS | PARTIAL_SUCCESS | FAILED
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    fields_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    fields_resolved: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    fields_unknown: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    fields_conflict: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    candidates_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    error_code: Mapped[str | None] = mapped_column(String(40))
    error_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)


class TenderFieldValue(Base):
    """One row per registry field per run - including UNKNOWN fields (never omitted)."""

    __tablename__ = "tender_field_values"
    __table_args__ = (
        Index("uq_tender_field_values_extraction_field", "field_extraction_id", "field_name", unique=True),
        Index("ix_tender_field_values_field_text", "field_name", "value_text"),
        Index("ix_tender_field_values_field_tri", "field_name", "tri_state"),
    )

    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    field_extraction_id: Mapped[int] = mapped_column(
        PK, ForeignKey("tender_field_extractions.id", ondelete="CASCADE"), nullable=False, index=True)
    tender_id: Mapped[int] = mapped_column(PK, ForeignKey("tenders.id", ondelete="CASCADE"), nullable=False,
                                           index=True)
    field_name: Mapped[str] = mapped_column(String(64), nullable=False)
    field_group: Mapped[str] = mapped_column(String(32), nullable=False)
    value_type: Mapped[str] = mapped_column(String(16), nullable=False)
    # RESOLVED | CONFLICT | UNKNOWN
    status: Mapped[str] = mapped_column(String(12), nullable=False)
    # Why UNKNOWN/CONFLICT: NOT_FOUND | MASKED_IN_SOURCE | NOT_APPLICABLE_IN_SOURCE | UNPARSEABLE | CONFLICTING_EVIDENCE
    reason: Mapped[str | None] = mapped_column(String(40))
    # TRUE | FALSE | UNKNOWN (boolean-style fields only)
    tri_state: Mapped[str | None] = mapped_column(String(8))
    value_text: Mapped[str | None] = mapped_column(Text)       # canonical form, for filtering
    value_number: Mapped[float | None] = mapped_column(Float)  # numeric form, for range filters
    value_json: Mapped[str | None] = mapped_column(Text)       # full normalized value
    unit: Mapped[str | None] = mapped_column(String(16))
    evidence_strength: Mapped[str | None] = mapped_column(String(20))
    candidate_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


class TenderFieldEvidence(Base):
    """Every candidate found for a field, with full provenance (none are discarded)."""

    __tablename__ = "tender_field_evidence"
    __table_args__ = (
        Index("ix_tender_field_evidence_field", "field_extraction_id", "field_name"),
    )

    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    field_value_id: Mapped[int] = mapped_column(
        PK, ForeignKey("tender_field_values.id", ondelete="CASCADE"), nullable=False, index=True)
    field_extraction_id: Mapped[int] = mapped_column(
        PK, ForeignKey("tender_field_extractions.id", ondelete="CASCADE"), nullable=False)
    field_name: Mapped[str] = mapped_column(String(64), nullable=False)
    stage3a_extraction_id: Mapped[int] = mapped_column(
        PK, ForeignKey("document_extractions.id", ondelete="CASCADE"), nullable=False)
    document_version_id: Mapped[int] = mapped_column(
        PK, ForeignKey("document_versions.id", ondelete="CASCADE"), nullable=False)
    page_number: Mapped[int | None] = mapped_column(Integer)
    table_id: Mapped[int | None] = mapped_column(PK, ForeignKey("document_tables.id", ondelete="SET NULL"))
    table_index: Mapped[int | None] = mapped_column(Integer)
    row_index: Mapped[int | None] = mapped_column(Integer)  # 0-based row within the table
    section_id: Mapped[int | None] = mapped_column(PK, ForeignKey("document_sections.id", ondelete="SET NULL"))
    section_heading: Mapped[str | None] = mapped_column(String(255))
    # TABLE_CELL | TABLE_ROW | SECTION_TEXT | PAGE_TEXT | DERIVED | METADATA
    evidence_type: Mapped[str] = mapped_column(String(20), nullable=False)
    # SYSTEM_METADATA | EXACT_TABLE | SECTION_TABLE | EXACT_LABEL | SECTION_CONTEXT | REGEX_FALLBACK | DERIVED
    strength: Mapped[str] = mapped_column(String(20), nullable=False)
    rule: Mapped[str] = mapped_column(String(64), nullable=False)
    source_label: Mapped[str | None] = mapped_column(Text)
    raw_value: Mapped[str | None] = mapped_column(Text)
    source_text: Mapped[str | None] = mapped_column(Text)
    normalized_json: Mapped[str | None] = mapped_column(Text)
    value_key: Mapped[str | None] = mapped_column(String(255))
    # SELECTED | AGREES | OVERRIDDEN | CONFLICTING | IGNORED
    disposition: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


class FieldExtractionJob(Base):
    """Queue entry for Stage 3B on one Stage 3A extraction (Stage 2B/3A job pattern)."""

    __tablename__ = "field_extraction_jobs"
    __table_args__ = (
        Index("ix_field_extraction_jobs_status_next_retry", "status", "next_retry_at"),
        Index("uq_field_extraction_jobs_source_queued", "stage3a_extraction_id", unique=True,
              sqlite_where=_QUEUED_FIELD_JOB, postgresql_where=_QUEUED_FIELD_JOB),
    )

    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    stage3a_extraction_id: Mapped[int] = mapped_column(
        PK, ForeignKey("document_extractions.id", ondelete="CASCADE"), nullable=False, index=True)
    # PENDING | RUNNING | SUCCESS | PARTIAL_SUCCESS | RETRY | FAILED | SKIPPED
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING")
    # STAGE3A_COMPLETED | BACKFILL | MANUAL | REEXTRACT
    reason: Mapped[str | None] = mapped_column(String(32))
    force: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime)
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    locked_by: Mapped[str | None] = mapped_column(String(128))
    outcome: Mapped[str | None] = mapped_column(String(40))
    error_code: Mapped[str | None] = mapped_column(String(40))
    error_message: Mapped[str | None] = mapped_column(Text)
    field_extraction_id: Mapped[int | None] = mapped_column(
        PK, ForeignKey("tender_field_extractions.id", ondelete="SET NULL"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)


# ---------------------------------------------------------------------------
# Stage 3C - AI-assisted tender requirement interpretation
# ---------------------------------------------------------------------------
# An additional, auditable interpretation layer ABOVE Stage 3B. Reads Stage 3A
# rows and Stage 3B values; never changes them. One run = one Stage 3B run x one
# (provider, model, prompt version, schema version); history is kept (is_current).
# No API key or provider credential is ever stored.

_QUEUED_AI_JOB = text("status IN ('PENDING', 'RETRY')")


class AIAnalysisRun(Base):
    __tablename__ = "ai_analysis_runs"
    __table_args__ = (
        Index("uq_ai_analysis_runs_source_current", "stage3b_extraction_id", "provider", "model",
              "prompt_version", "schema_version", unique=True,
              sqlite_where=text("is_current = 1 AND analysis_scope = 'DOCUMENT'"), postgresql_where=text("is_current IS TRUE AND analysis_scope = 'DOCUMENT'")),
        Index("uq_ai_analysis_runs_corpus_current", "tender_id", "corpus_fingerprint", "provider", "model", "prompt_version", "schema_version", unique=True,
              sqlite_where=text("is_current = 1 AND analysis_scope = 'TENDER_CORPUS'"), postgresql_where=text("is_current IS TRUE AND analysis_scope = 'TENDER_CORPUS'")),
        Index("ix_ai_analysis_runs_status", "status"),
        Index("ix_ai_analysis_runs_bid_number", "bid_number"),
    )

    analysis_scope: Mapped[str] = mapped_column(String(20), nullable=False, default="DOCUMENT", server_default="DOCUMENT")
    corpus_fingerprint: Mapped[str | None] = mapped_column(String(64))
    corpus_snapshot_json: Mapped[str | None] = mapped_column(Text)
    corpus_completeness: Mapped[str | None] = mapped_column(String(40))

    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    stage3b_extraction_id: Mapped[int] = mapped_column(
        PK, ForeignKey("tender_field_extractions.id", ondelete="CASCADE"), nullable=False, index=True)
    stage3a_extraction_id: Mapped[int] = mapped_column(
        PK, ForeignKey("document_extractions.id", ondelete="CASCADE"), nullable=False, index=True)
    document_version_id: Mapped[int] = mapped_column(
        PK, ForeignKey("document_versions.id", ondelete="CASCADE"), nullable=False, index=True)
    document_id: Mapped[int] = mapped_column(
        PK, ForeignKey("tender_documents.id", ondelete="CASCADE"), nullable=False)
    tender_id: Mapped[int] = mapped_column(
        PK, ForeignKey("tenders.id", ondelete="CASCADE"), nullable=False, index=True)
    bid_number: Mapped[str] = mapped_column(String(64), nullable=False)
    document_type: Mapped[str] = mapped_column(String(40), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    analyzer_name: Mapped[str] = mapped_column(String(40), nullable=False)
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    model: Mapped[str] = mapped_column(String(120), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(40), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(40), nullable=False)
    chunker_version: Mapped[str] = mapped_column(String(40), nullable=False)
    # SUCCESS | PARTIAL_SUCCESS (failed attempts are recorded on the job, not as runs)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    status_code: Mapped[str | None] = mapped_column(String(40))
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    summary: Mapped[str | None] = mapped_column(Text)
    chunks_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    chunks_sent: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    input_characters: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    requirements_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rejected_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    flags_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    ambiguities_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    conflicts_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    total_tokens: Mapped[int | None] = mapped_column(Integer)
    finish_reason: Mapped[str | None] = mapped_column(String(40))
    provider_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    request_sha256: Mapped[str | None] = mapped_column(String(64))   # hash of the exact prompt sent
    response_sha256: Mapped[str | None] = mapped_column(String(64))  # hash of the raw model text
    rejected_json: Mapped[str | None] = mapped_column(Text)          # rejected items + reasons (audit)
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)


class AIEvidenceChunk(Base):
    """A bounded, provenance-carrying piece of Stage 3A text built for one run (sent or not)."""

    __tablename__ = "ai_evidence_chunks"
    __table_args__ = (
        Index("uq_ai_evidence_chunks_run_key", "analysis_run_id", "chunk_key", unique=True),
    )

    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    analysis_run_id: Mapped[int] = mapped_column(
        PK, ForeignKey("ai_analysis_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    chunk_key: Mapped[str] = mapped_column(String(16), nullable=False)    # "C7" - the id the model sees
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)         # BUYER_ATC | CLAUSE_TEXT | ...
    source_type: Mapped[str] = mapped_column(String(20), nullable=False)  # SECTION_TEXT | TABLE
    stage3a_extraction_id: Mapped[int] = mapped_column(
        PK, ForeignKey("document_extractions.id", ondelete="CASCADE"), nullable=False)
    document_version_id: Mapped[int] = mapped_column(
        PK, ForeignKey("document_versions.id", ondelete="CASCADE"), nullable=False)
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    page_end: Mapped[int] = mapped_column(Integer, nullable=False)
    section_id: Mapped[int | None] = mapped_column(PK, ForeignKey("document_sections.id", ondelete="SET NULL"))
    section_heading: Mapped[str | None] = mapped_column(String(255))
    table_id: Mapped[int | None] = mapped_column(PK, ForeignKey("document_tables.id", ondelete="SET NULL"))
    text: Mapped[str] = mapped_column(Text, nullable=False)
    char_count: Mapped[int] = mapped_column(Integer, nullable=False)
    text_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    sent: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    exclusion_reason: Mapped[str | None] = mapped_column(String(40))  # BOILERPLATE | CHUNK_LIMIT | CHAR_LIMIT
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


class AIRequirement(Base):
    """One validated, evidence-grounded requirement interpretation (never a seller verdict)."""

    __tablename__ = "ai_requirements"
    __table_args__ = (
        Index("ix_ai_requirements_run_type", "analysis_run_id", "requirement_type"),
        Index("ix_ai_requirements_level", "obligation_level"),
    )

    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    analysis_run_id: Mapped[int] = mapped_column(
        PK, ForeignKey("ai_analysis_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    tender_id: Mapped[int] = mapped_column(PK, ForeignKey("tenders.id", ondelete="CASCADE"), nullable=False,
                                           index=True)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    requirement_type: Mapped[str] = mapped_column(String(40), nullable=False)
    model_requirement_type: Mapped[str | None] = mapped_column(String(80))  # original label if mapped to OTHER
    category: Mapped[str] = mapped_column(String(24), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    obligation: Mapped[str | None] = mapped_column(Text)
    # MANDATORY | OPTIONAL | CONDITIONAL | INFORMATIONAL | UNKNOWN
    obligation_level: Mapped[str] = mapped_column(String(16), nullable=False)
    model_obligation_level: Mapped[str | None] = mapped_column(String(32))  # what the model said
    level_adjustment: Mapped[str | None] = mapped_column(String(40))        # why we changed it, if we did
    condition_text: Mapped[str | None] = mapped_column(Text)
    value_text: Mapped[str | None] = mapped_column(Text)
    value_number: Mapped[float | None] = mapped_column(Float)
    unit: Mapped[str | None] = mapped_column(String(32))
    applies_to: Mapped[str] = mapped_column(String(24), nullable=False, default="UNKNOWN")
    risk_flags_json: Mapped[str | None] = mapped_column(Text)
    ambiguity: Mapped[str | None] = mapped_column(Text)
    is_buyer_atc: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


class AIRequirementEvidence(Base):
    """Verified link requirement -> chunk (+ the quote found in that chunk's text)."""

    __tablename__ = "ai_requirement_evidence"

    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    requirement_id: Mapped[int] = mapped_column(
        PK, ForeignKey("ai_requirements.id", ondelete="CASCADE"), nullable=False, index=True)
    analysis_run_id: Mapped[int] = mapped_column(
        PK, ForeignKey("ai_analysis_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    chunk_id: Mapped[int] = mapped_column(
        PK, ForeignKey("ai_evidence_chunks.id", ondelete="CASCADE"), nullable=False, index=True)
    chunk_key: Mapped[str] = mapped_column(String(16), nullable=False)
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    section_id: Mapped[int | None] = mapped_column(PK, ForeignKey("document_sections.id", ondelete="SET NULL"))
    section_heading: Mapped[str | None] = mapped_column(String(255))
    quote: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


class AIAnalysisFlag(Base):
    """Review / disagreement / ambiguity flag. Stage 3B values are never changed - only flagged."""

    __tablename__ = "ai_analysis_flags"
    __table_args__ = (
        Index("ix_ai_analysis_flags_run_type", "analysis_run_id", "flag_type"),
    )

    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    analysis_run_id: Mapped[int] = mapped_column(
        PK, ForeignKey("ai_analysis_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    requirement_id: Mapped[int | None] = mapped_column(
        PK, ForeignKey("ai_requirements.id", ondelete="CASCADE"), index=True)
    flag_type: Mapped[str] = mapped_column(String(40), nullable=False)
    severity: Mapped[str] = mapped_column(String(10), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    stage3b_field_name: Mapped[str | None] = mapped_column(String(64))
    stage3b_value: Mapped[str | None] = mapped_column(Text)
    stage3b_evidence_strength: Mapped[str | None] = mapped_column(String(20))
    ai_value: Mapped[str | None] = mapped_column(Text)
    chunk_keys_json: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


class AIAnalysisJob(Base):
    """Queue entry for Stage 3C on one Stage 3B run (Stage 2B/3A/3B job pattern + BLOCKED)."""

    __tablename__ = "ai_analysis_jobs"
    __table_args__ = (
        Index("uq_ai_analysis_jobs_corpus_active", "tender_id", "corpus_fingerprint", "provider", "model", "prompt_version", "schema_version", unique=True,
              sqlite_where=text("status IN ('PENDING', 'RETRY', 'RUNNING') AND analysis_scope = 'TENDER_CORPUS'"), postgresql_where=text("status IN ('PENDING', 'RETRY', 'RUNNING') AND analysis_scope = 'TENDER_CORPUS'")),
        Index("ix_ai_analysis_jobs_status_next_retry", "status", "next_retry_at"),
        Index("uq_ai_analysis_jobs_source_queued", "stage3b_extraction_id", unique=True,
              sqlite_where=text("status IN ('PENDING', 'RETRY') AND analysis_scope = 'DOCUMENT'"), postgresql_where=text("status IN ('PENDING', 'RETRY') AND analysis_scope = 'DOCUMENT'")),
    )

    analysis_scope: Mapped[str] = mapped_column(String(20), nullable=False, default="DOCUMENT", server_default="DOCUMENT")
    corpus_fingerprint: Mapped[str | None] = mapped_column(String(64))
    corpus_snapshot_json: Mapped[str | None] = mapped_column(Text)
    tender_id: Mapped[int | None] = mapped_column(PK, ForeignKey("tenders.id", ondelete="CASCADE"))
    prompt_version: Mapped[str | None] = mapped_column(String(40))
    schema_version: Mapped[str | None] = mapped_column(String(40))

    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    stage3b_extraction_id: Mapped[int] = mapped_column(
        PK, ForeignKey("tender_field_extractions.id", ondelete="CASCADE"), nullable=False, index=True)
    # PENDING | RUNNING | SUCCESS | PARTIAL_SUCCESS | RETRY | FAILED | BLOCKED | SKIPPED
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING")
    # STAGE3B_COMPLETED | BACKFILL | MANUAL | REANALYZE
    reason: Mapped[str | None] = mapped_column(String(32))
    force: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime)
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    locked_by: Mapped[str | None] = mapped_column(String(128))
    provider: Mapped[str | None] = mapped_column(String(40))
    model: Mapped[str | None] = mapped_column(String(120))
    outcome: Mapped[str | None] = mapped_column(String(40))
    error_code: Mapped[str | None] = mapped_column(String(40))
    error_message: Mapped[str | None] = mapped_column(Text)   # redacted; never contains credentials
    analysis_run_id: Mapped[int | None] = mapped_column(
        PK, ForeignKey("ai_analysis_runs.id", ondelete="SET NULL"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)


class AIProviderCall(Base):
    """One row per provider HTTP call attempt (audit + daily cost cap). No prompt, response
    text or credential is stored - only metadata."""

    __tablename__ = "ai_provider_calls"
    __table_args__ = (
        Index("ix_ai_provider_calls_started", "started_at"),
    )

    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    job_id: Mapped[int | None] = mapped_column(PK, ForeignKey("ai_analysis_jobs.id", ondelete="SET NULL"),
                                               index=True)
    stage3b_extraction_id: Mapped[int | None] = mapped_column(
        PK, ForeignKey("tender_field_extractions.id", ondelete="SET NULL"))
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    model: Mapped[str] = mapped_column(String(120), nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)   # OK | error code
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class DocumentReferenceScan(Base):
    """Discovery coverage for an immutable source version; limits/errors never mean complete."""
    __tablename__ = "document_reference_scans"
    document_version_id: Mapped[int] = mapped_column(PK, ForeignKey("document_versions.id", ondelete="CASCADE"), primary_key=True)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    rules_version: Mapped[str] = mapped_column(String(40), nullable=False)
    scanned_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)


class DocumentReference(Base):
    __tablename__ = "document_references"
    __table_args__ = (Index("uq_document_reference_origin", "source_version_id", "page_number", "url_sha256", unique=True),)
    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    tender_id: Mapped[int] = mapped_column(PK, ForeignKey("tenders.id", ondelete="CASCADE"), index=True)
    source_document_id: Mapped[int] = mapped_column(PK, ForeignKey("tender_documents.id", ondelete="CASCADE"))
    source_version_id: Mapped[int] = mapped_column(PK, ForeignKey("document_versions.id", ondelete="CASCADE"), index=True)
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    anchor_text: Mapped[str | None] = mapped_column(Text)
    context: Mapped[str | None] = mapped_column(Text)
    original_url: Mapped[str] = mapped_column(Text, nullable=False)
    canonical_url: Mapped[str] = mapped_column(Text, nullable=False)
    url_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    target_document_id: Mapped[int | None] = mapped_column(PK, ForeignKey("tender_documents.id", ondelete="SET NULL"))
    target_version_id: Mapped[int | None] = mapped_column(PK, ForeignKey("document_versions.id", ondelete="SET NULL"))
    category: Mapped[str] = mapped_column(String(40), nullable=False)
    document_type: Mapped[str] = mapped_column(String(40), nullable=False)
    corpus_relevant: Mapped[bool] = mapped_column(Boolean, nullable=False)
    discovery_method: Mapped[str] = mapped_column(String(40), nullable=False, default="PDF_URI_ANNOTATION")
    depth: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    first_discovered_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)


class AIAnalysisRunSource(Base):
    __tablename__ = "ai_analysis_run_sources"
    __table_args__ = (Index("uq_ai_run_source", "analysis_run_id", "document_version_id", unique=True),)
    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    analysis_run_id: Mapped[int] = mapped_column(PK, ForeignKey("ai_analysis_runs.id", ondelete="CASCADE"), index=True)
    document_id: Mapped[int] = mapped_column(PK, ForeignKey("tender_documents.id", ondelete="CASCADE"))
    document_version_id: Mapped[int] = mapped_column(PK, ForeignKey("document_versions.id", ondelete="CASCADE"))
    stage3a_extraction_id: Mapped[int | None] = mapped_column(PK, ForeignKey("document_extractions.id", ondelete="SET NULL"))
    stage3b_extraction_id: Mapped[int | None] = mapped_column(PK, ForeignKey("tender_field_extractions.id", ondelete="SET NULL"))
    document_type: Mapped[str] = mapped_column(String(40), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    source_order: Mapped[int] = mapped_column(Integer, nullable=False)
    included: Mapped[bool] = mapped_column(Boolean, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)


# ============================================================================
# STAGE 4: SELLER PROFILE & ELIGIBILITY ENGINE (migration 0008)
# ============================================================================

class Seller(Base):
    """Root seller entity."""
    __tablename__ = "sellers"

    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    organization_id: Mapped[str | None] = mapped_column(String(64), index=True) # External/Internal ID
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    revisions: Mapped[list["SellerRevision"]] = relationship(back_populates="seller", cascade="all, delete-orphan")


class SellerRevision(Base):
    """Immutable snapshot of a seller's profile at a point in time."""
    __tablename__ = "seller_revisions"
    __table_args__ = (
        Index("uq_seller_revision_fingerprint", "seller_id", "fingerprint", unique=True),
    )

    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    seller_id: Mapped[int] = mapped_column(PK, ForeignKey("sellers.id", ondelete="CASCADE"), nullable=False, index=True)
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    comment: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    seller: Mapped[Seller] = relationship(back_populates="revisions")
    attributes: Mapped[list["SellerAttribute"]] = relationship(back_populates="revision", cascade="all, delete-orphan")
    documents: Mapped[list["SellerDocument"]] = relationship(back_populates="revision", cascade="all, delete-orphan")


class SellerAttribute(Base):
    """Key-value data for a seller revision (turnover, MSME status, etc.)."""
    __tablename__ = "seller_attributes"
    __table_args__ = (
        Index("uq_seller_attribute_key", "revision_id", "key", unique=True),
    )

    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    revision_id: Mapped[int] = mapped_column(PK, ForeignKey("seller_revisions.id", ondelete="CASCADE"), nullable=False, index=True)
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    value_type: Mapped[str] = mapped_column(String(20), nullable=False) # TEXT, NUMBER, BOOLEAN, JSON
    value_text: Mapped[str | None] = mapped_column(Text)
    value_number: Mapped[float | None] = mapped_column(Float)
    value_json: Mapped[str | None] = mapped_column(Text)
    # Metadata for the value (e.g., Financial Year for turnover)
    context: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    revision: Mapped[SellerRevision] = relationship(back_populates="attributes")


class SellerDocument(Base):
    """Document evidence for a seller revision."""
    __tablename__ = "seller_documents"

    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    revision_id: Mapped[int] = mapped_column(PK, ForeignKey("seller_revisions.id", ondelete="CASCADE"), nullable=False, index=True)
    document_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    filename: Mapped[str] = mapped_column(Text, nullable=False)
    sha256: Mapped[str | None] = mapped_column(String(64))
    storage_path: Mapped[str | None] = mapped_column(Text)
    issue_date: Mapped[datetime | None] = mapped_column(DateTime)
    expiry_date: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    # Verified by human, pending, etc.
    status: Mapped[str] = mapped_column(String(20), default="PENDING", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    revision: Mapped[SellerRevision] = relationship(back_populates="documents")


class EligibilityRun(Base):
    """Overall outcome of an eligibility evaluation."""
    __tablename__ = "eligibility_runs"
    __table_args__ = (
        Index("ix_eligibility_runs_tender_seller", "tender_id", "seller_id"),
        Index("uq_eligibility_run_version", "tender_id", "seller_revision_id", "corpus_fingerprint", "engine_version", "ai_state_fingerprint", unique=True),
    )

    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    tender_id: Mapped[int] = mapped_column(PK, ForeignKey("tenders.id", ondelete="CASCADE"), nullable=False, index=True)
    seller_id: Mapped[int] = mapped_column(PK, ForeignKey("sellers.id", ondelete="CASCADE"), nullable=False, index=True)
    seller_revision_id: Mapped[int] = mapped_column(PK, ForeignKey("seller_revisions.id", ondelete="CASCADE"), nullable=False, index=True)
    corpus_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    engine_version: Mapped[str] = mapped_column(String(40), nullable=False)

    # ELIGIBLE | NOT_ELIGIBLE | CONDITIONALLY_ELIGIBLE | REVIEW_REQUIRED | INSUFFICIENT_INFORMATION | ANALYSIS_INCOMPLETE
    status: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    summary: Mapped[str | None] = mapped_column(Text)

    # Snapshot of Stage 3 analysis used
    ai_state_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    ai_analysis_run_id: Mapped[int | None] = mapped_column(PK, ForeignKey("ai_analysis_runs.id", ondelete="SET NULL"))

    passed_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failed_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    review_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    insufficient_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    evaluated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    results: Mapped[list["EligibilityRequirementResult"]] = relationship(back_populates="run", cascade="all, delete-orphan")


class EligibilityRequirementResult(Base):
    """Outcome for a single tender requirement."""
    __tablename__ = "eligibility_requirement_results"

    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(PK, ForeignKey("eligibility_runs.id", ondelete="CASCADE"), nullable=False, index=True)

    # Reference to Stage 3B or 3C requirement
    requirement_name: Mapped[str] = mapped_column(String(128), nullable=False)
    requirement_type: Mapped[str] = mapped_column(String(64), nullable=False)

    # PASS | FAIL | PASS_WITH_RELAXATION | CONDITIONALLY_PASS | REVIEW_REQUIRED | INSUFFICIENT_INFORMATION | NOT_APPLICABLE
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)

    # Explicit relaxation used (e.g., "MSE_TURNOVER_EXEMPTION")
    relaxation_applied: Mapped[str | None] = mapped_column(String(64))

    # Source provenance (Stage 3B field id or Stage 3C requirement id)
    stage3b_field_id: Mapped[int | None] = mapped_column(PK, ForeignKey("tender_field_values.id", ondelete="SET NULL"))
    ai_requirement_id: Mapped[int | None] = mapped_column(PK, ForeignKey("ai_requirements.id", ondelete="SET NULL"))

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    run: Mapped[EligibilityRun] = relationship(back_populates="results")
    evidence: Mapped[list["EligibilityEvidence"]] = relationship(back_populates="result", cascade="all, delete-orphan")


class EligibilityEvidence(Base):
    """Link between a requirement result and specific seller attributes/documents."""
    __tablename__ = "eligibility_evidence"

    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    result_id: Mapped[int] = mapped_column(PK, ForeignKey("eligibility_requirement_results.id", ondelete="CASCADE"), nullable=False, index=True)

    # Links to seller data
    seller_attribute_id: Mapped[int | None] = mapped_column(PK, ForeignKey("seller_attributes.id", ondelete="SET NULL"))
    seller_document_id: Mapped[int | None] = mapped_column(PK, ForeignKey("seller_documents.id", ondelete="SET NULL"))

    # The value or status of the seller data at the time of evaluation
    evidence_value: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    result: Mapped[EligibilityRequirementResult] = relationship(back_populates="evidence")

# ============================================================================
# RETIRED TABLES (intentionally not mapped)
# ============================================================================
# Migrations 0010/0012 (opportunity_score_runs, opportunity_score_dimensions,
# opportunity_evidence, scoring_configurations) and 0013 (seller_cost_profiles,
# tender_financial_scenarios, tender_cash_flow_events,
# tender_financial_evaluation_snapshots, financial_change_audit) created tables
# for features that are out of product scope. The migration history is kept so
# existing databases stay valid; no application code reads or writes them.
# Seller-tender matching lives in SellerTenderMatch (app/database/matching_models.py).
