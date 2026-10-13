"""Collection-run schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_serializer

from app.utils.dates import as_aware_utc


class RunSummary(BaseModel):
    """Result of one discovery run (also returned by POST /api/collection/run)."""

    run_id: int
    status: str
    trigger_type: str
    pages_checked: int = 0
    bids_seen: int = 0
    new_bids: int = 0
    updated_bids: int = 0
    unchanged_bids: int = 0
    failed_items: int = 0
    closed_by_deadline: int = 0
    error_message: str | None = None


class CollectionRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    started_at: datetime
    finished_at: datetime | None
    status: str
    pages_checked: int
    bids_seen: int
    new_bids: int
    updated_bids: int
    unchanged_bids: int
    failed_items: int
    error_message: str | None
    trigger_type: str

    @field_serializer("started_at", "finished_at")
    def _ser_dt(self, v: datetime | None) -> str | None:
        aware = as_aware_utc(v)
        return aware.isoformat() if aware else None


class StatsOut(BaseModel):
    total_tenders: int
    ongoing: int
    closed: int
    new_last_24h: int
    last_collection: str | None
    last_collection_status: str | None
    collection_running: bool

    # Stage 2: Document metrics
    documents_total: int = 0
    documents_downloaded: int = 0
    document_versions_total: int = 0
    failed_document_jobs: int = 0
    pending_document_jobs: int = 0
    tenders_without_documents: int = 0

    # Stage 2B: job processing health
    running_document_jobs: int = 0
    retry_document_jobs: int = 0
    blocked_document_jobs: int = 0
    stale_running_document_jobs: int = 0
    oldest_pending_document_job_at: str | None = None
    last_successful_document_processing_at: str | None = None
    document_worker: dict | None = None

    # Stage 3A: extraction
    extractions_total: int = 0
    extractions_success: int = 0
    extractions_partial: int = 0
    extractions_failed: int = 0
    extractions_ocr_required: int = 0
    extraction_jobs_pending: int = 0
    extraction_jobs_running: int = 0
    extraction_jobs_retry: int = 0
    extraction_jobs_failed: int = 0
    document_versions_without_extraction: int = 0
    pages_extracted: int = 0
    tables_extracted: int = 0
    extraction: dict | None = None

    # Stage 3B: tender fields
    stage3a_extractions_eligible_for_fields: int = 0
    field_extractions_total: int = 0
    field_extractions_success: int = 0
    field_extractions_partial: int = 0
    field_extractions_failed: int = 0
    field_extraction_jobs_pending: int = 0
    field_extraction_jobs_running: int = 0
    stage3a_extractions_unqueued_for_fields: int = 0
    fields_extracted: int = 0
    fields_unknown: int = 0
    fields_conflicted: int = 0
    field_extraction: dict | None = None

    # Stage 3C: AI requirement interpretation (never contains credentials)
    ai_provider_configured: bool = False
    ai_analyses_total: int = 0
    ai_analyses_success: int = 0
    ai_analyses_partial: int = 0
    ai_analysis_jobs_pending: int = 0
    ai_analysis_jobs_running: int = 0
    ai_analysis_jobs_retry: int = 0
    ai_analysis_jobs_failed: int = 0
    ai_analysis_jobs_blocked: int = 0
    stage3b_runs_unqueued_for_ai: int = 0
    ai_requirements_generated: int = 0
    ai_ambiguities: int = 0
    ai_conflict_flags: int = 0
    ai_review_flags: int = 0
    ai_analysis: dict | None = None
