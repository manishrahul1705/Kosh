"""Typed application settings loaded from environment variables / .env."""

from __future__ import annotations

from functools import lru_cache
from decimal import Decimal
from typing import Literal
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.constants import CollectorMode

PROJECT_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_GEM_BID_LIST_URL = "https://bidplus.gem.gov.in/all-bids"

# Worker switches that must be off while APP_STARTUP_MODE=verify.
_WORKER_FLAGS = (
    "document_worker_enabled",
    "extraction_worker_enabled",
    "field_extraction_worker_enabled",
    "ai_analysis_worker_enabled",
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_env: str = "development"
    # Local test sign-in without Supabase (app/api/dev_login.py). Development only:
    # refused when APP_ENV=production, and only answers requests from this computer.
    dev_login_enabled: bool = False
    # Supabase project URL (public). Read from the environment or .env; see app/api/auth.py.
    supabase_url: str = ""
    database_url: str = "sqlite:///./data/gem.db"
    auto_migrate: bool = True
    # Startup mode. normal = existing behaviour. verify = read-only inspection: no
    # migrations, no startup recovery, no scheduler, no background workers. The
    # database engine must also open read-only (enforced in session.py).
    app_startup_mode: Literal["normal", "verify"] = "normal"
    # Startup recovery marks RUNNING rows left by a previous process as FAILED or RETRY.
    # Independent of SCHEDULER_ENABLED. Default true for backward compatibility.
    startup_recovery_enabled: bool = True

    # --- Source -----------------------------------------------------------
    gem_bid_list_url: str = DEFAULT_GEM_BID_LIST_URL
    # JSON endpoint the public listing page itself posts to. Empty = derive
    # from gem_bid_list_url (<origin>/all-bids-data).
    gem_bid_data_url: str = ""
    # Sort order requested from the listing. Newest-first means newly
    # published bids land on the first pages, inside MAX_PAGES_PER_RUN.
    gem_sort: str = "Bid-Start-Date-Latest"
    # Zone used for listing timestamps. The listing JSON marks them with a
    # trailing "Z" (UTC). Keep "UTC" unless you verified against the GeM UI
    # that the "Z" is a mislabel for IST (see README, Date/time handling).
    gem_api_timestamp_zone: str = "UTC"
    user_agent: str = "GeMTenderIntelligence/1.0 (Stage-1 public bid discovery)"

    # --- Collection -------------------------------------------------------
    collector_mode: CollectorMode = CollectorMode.AUTO
    fixture_dir: str = "tests/fixtures/gem/default"
    collection_interval_minutes: int = Field(default=30, ge=1)
    collect_on_startup: bool = True
    scheduler_enabled: bool = True
    request_timeout_seconds: float = Field(default=30.0, gt=0)
    request_delay_seconds: float = Field(default=2.0, ge=0)
    max_retries: int = Field(default=3, ge=0, le=10)
    backoff_base_seconds: float = Field(default=2.0, ge=0)
    max_retry_after_seconds: float = Field(default=300.0, ge=0)
    max_pages_per_run: int = Field(default=100, ge=1)
    mark_expired_as_closed: bool = True

    # --- Stage 2: Documents -----------------------------------------------
    document_reference_discovery_enabled: bool = True
    document_reference_max_depth: int = Field(default=3, ge=0, le=10)
    document_reference_max_per_document: int = Field(default=50, ge=1, le=500)
    document_reference_max_per_tender: int = Field(default=200, ge=1, le=2000)
    document_reference_max_acquisitions: int = Field(default=30, ge=1, le=200)
    document_reference_allowed_hosts: str = "bidplus.gem.gov.in,mkp.gem.gov.in,admin.gem.gov.in,fulfilment.gem.gov.in"
    document_reference_require_https: bool = True
    document_storage_path: str = "data/tenders"
    max_document_size_mb: int = Field(default=100, ge=1)
    document_request_timeout_seconds: float = Field(default=60.0, gt=0)
    document_connect_timeout_seconds: float = Field(default=10.0, gt=0, le=60)
    document_download_timeout_seconds: float = Field(default=120.0, gt=0, le=600)
    document_max_retries: int = Field(default=3, ge=0, le=10)
    document_request_delay_seconds: float = Field(default=2.0, ge=0)
    document_refresh_interval_minutes: int = Field(default=60, ge=1)
    # Stage 2B processes ONE job at a time (SQLite MVP). Values > 1 are
    # accepted for compatibility but the worker logs a warning and uses 1.
    document_worker_concurrency: int = Field(default=1, ge=1)
    # Queue a NEW_TENDER DocumentJob when Stage 1 inserts a tender.
    auto_download_new_tenders: bool = True
    save_document_debug_snapshots: bool = False

    # --- Stage 2B: automated document job processing ----------------------
    # Master switch for the scheduled worker inside the API process. OFF by
    # default so upgrading never starts consuming an existing backlog by
    # surprise; enable after a controlled `run_document_worker.py --bid` test.
    document_worker_enabled: bool = False
    # How often the scheduler polls the queue (worker poll frequency).
    document_job_poll_seconds: int = Field(default=30, ge=5)
    # Jobs processed per poll (each job = one tender's Stage 2A acquisition).
    document_worker_max_jobs_per_run: int = Field(default=1, ge=1, le=50)
    # Pause between consecutive jobs inside one run (outbound GeM pacing).
    document_inter_job_delay_seconds: float = Field(default=10.0, ge=0)
    # Job-level attempts (separate from Stage 2A per-request retries).
    document_max_attempts: int = Field(default=3, ge=1, le=10)
    # Job-level backoff: base * 2**(attempt-1), capped.
    document_retry_backoff_minutes: float = Field(default=15.0, ge=0)
    document_retry_max_backoff_minutes: float = Field(default=360.0, ge=0)
    # A RUNNING job older than this is considered orphaned (crash recovery).
    document_stale_running_minutes: int = Field(default=30, ge=1)
    # After any job ends BLOCKED (CAPTCHA/401/403), pause ALL processing this long.
    document_block_cooldown_minutes: int = Field(default=60, ge=0)
    # Periodic refresh of ONGOING tenders (due-time based, never "everything").
    periodic_document_refresh_enabled: bool = True
    document_refresh_check_minutes: int = Field(default=10, ge=1)
    # Max PERIODIC_REFRESH jobs queued at any one time.
    document_refresh_batch_size: int = Field(default=10, ge=1, le=500)
    # Queue exactly one FINAL_REFRESH job when a tender goes ONGOING -> CLOSED.
    final_refresh_on_close: bool = True
    # Default --limit for scripts/backfill_document_jobs.py.
    document_backfill_batch_size: int = Field(default=10, ge=1)
    # Lock files (empty = next to LOCK_FILE).
    document_worker_lock_file: str = ""
    scheduler_lock_file: str = ""

    # --- Stage 3A: document text / table / structure extraction -------------
    # Run the extraction worker inside the API scheduler. OFF by default.
    extraction_worker_enabled: bool = False
    # Queue an extraction job when Stage 2 stores a new VALID DocumentVersion.
    extraction_auto_queue: bool = True
    extraction_job_poll_seconds: int = Field(default=30, ge=5)
    extraction_worker_max_jobs_per_run: int = Field(default=1, ge=1, le=50)
    extraction_max_attempts: int = Field(default=3, ge=1, le=10)
    extraction_retry_backoff_minutes: float = Field(default=5.0, ge=0)
    extraction_retry_max_backoff_minutes: float = Field(default=120.0, ge=0)
    extraction_stale_running_minutes: int = Field(default=30, ge=1)
    extraction_backfill_batch_size: int = Field(default=20, ge=1)
    # A page "has text" when it has at least this many letters/digits.
    extraction_min_page_chars: int = Field(default=20, ge=1)
    # Safety cap: pages beyond this are not parsed (extraction becomes PARTIAL).
    extraction_max_pages: int = Field(default=500, ge=1)
    extraction_tables_enabled: bool = True
    # Optional local OCR (Tesseract) for pages without a text layer. OFF by default.
    ocr_enabled: bool = False
    ocr_languages: str = "eng"
    ocr_dpi: int = Field(default=200, ge=72, le=600)
    ocr_executable: str = ""
    ocr_max_pages: int = Field(default=50, ge=1, le=500)
    ocr_max_pixels: int = Field(default=8_000_000, ge=10_000, le=20_000_000)
    ocr_timeout_seconds: int = Field(default=30, ge=1, le=120)
    ocr_document_timeout_seconds: int = Field(default=120, ge=1, le=600)
    ocr_memory_mb: int = Field(default=512, ge=128, le=2048)
    ocr_max_output_bytes: int = Field(default=2_000_000, ge=1024, le=10_000_000)
    ocr_min_confidence: float = Field(default=85, ge=0, le=100)
    ocr_sparse_native_chars: int = Field(default=200, ge=20, le=2000)
    ocr_large_image_ratio: float = Field(default=0.5, ge=0.1, le=1)
    ocr_max_low_confidence_ratio: float = Field(default=0.10, ge=0, le=1)
    supporting_max_units: int = Field(default=10000, ge=1, le=50000)
    supporting_max_characters: int = Field(default=1_000_000, ge=100, le=5_000_000)
    supporting_max_sheets: int = Field(default=20, ge=1, le=100)
    supporting_max_rows: int = Field(default=5000, ge=1, le=10000)
    supporting_max_columns: int = Field(default=200, ge=1, le=1000)
    supporting_max_cells: int = Field(default=50000, ge=1, le=200000)
    extraction_worker_lock_file: str = ""

    # --- Stage 3B: deterministic tender field extraction --------------------
    # Run the field-extraction worker inside the API scheduler. OFF by default.
    field_extraction_worker_enabled: bool = False
    # Queue a field-extraction job when Stage 3A produces a usable extraction.
    field_extraction_auto_queue: bool = True
    field_extraction_job_poll_seconds: int = Field(default=30, ge=5)
    field_extraction_worker_max_jobs_per_run: int = Field(default=1, ge=1, le=100)
    field_extraction_max_attempts: int = Field(default=3, ge=1, le=10)
    field_extraction_retry_backoff_minutes: float = Field(default=5.0, ge=0)
    field_extraction_stale_running_minutes: int = Field(default=30, ge=1)
    field_extraction_backfill_batch_size: int = Field(default=20, ge=1)
    # Zone of wall-clock date/times printed inside GeM documents (GeM shows IST).
    field_extraction_document_timezone: str = "Asia/Kolkata"
    field_extraction_worker_lock_file: str = ""

    # --- Stage 3C: AI-assisted requirement interpretation -------------------
    # Provider: "" (not configured) | gemini | openai_compatible | mock (offline, tests/verification)
    ai_provider: str = ""
    ai_model: str = ""
    # Secret: ONLY from the environment / .env. Never logged, stored or returned.
    ai_api_key: SecretStr = SecretStr("")
    # Empty = provider default (gemini: Google endpoint; openai_compatible: required)
    ai_base_url: str = ""
    ai_request_timeout_seconds: float = Field(default=60.0, gt=0, le=600)
    # Immediate retries for TRANSIENT provider failures only (timeout / 429 / 5xx / network)
    ai_max_retries: int = Field(default=1, ge=0, le=5)
    ai_retry_base_delay_seconds: float = Field(default=2.0, ge=0, le=60)
    ai_max_output_tokens: int = Field(default=4096, ge=256, le=65536)
    ai_temperature: float = Field(default=0.0, ge=0, le=1)
    # OpenAI-compatible servers: send response_format={"type":"json_object"}
    ai_openai_json_mode: bool = True
    # Cost / size controls for what is sent to the provider
    ai_max_chunks_per_analysis: int = Field(default=40, ge=1, le=500)
    ai_max_input_characters: int = Field(default=30000, ge=6000, le=1_000_000)  # whole prompt incl. ~4k instructions
    ai_max_chunk_characters: int = Field(default=3000, ge=200, le=50000)
    # GeM standard disclaimer / GTC text is excluded unless this is true
    ai_include_boilerplate: bool = False
    # Worker (OFF by default) and queue
    ai_analysis_scope: Literal["DOCUMENT", "TENDER_CORPUS"] = "TENDER_CORPUS"
    ai_analysis_worker_enabled: bool = False
    ai_analysis_auto_queue: bool = True
    ai_analysis_job_poll_seconds: int = Field(default=60, ge=5)
    ai_max_jobs_per_run: int = Field(default=1, ge=1, le=20)
    ai_analysis_max_attempts: int = Field(default=3, ge=1, le=10)
    ai_analysis_retry_backoff_minutes: float = Field(default=10.0, ge=0)
    ai_analysis_stale_running_minutes: int = Field(default=30, ge=1)
    # Provider calls (job attempts) allowed per rolling 24 h; 0 = no analysis at all
    ai_max_analyses_per_day: int = Field(default=20, ge=0, le=10000)
    # After an auth/config failure the worker pauses this long before claiming again
    ai_blocked_cooldown_minutes: int = Field(default=60, ge=1)
    ai_analysis_worker_lock_file: str = ""

    # --- Status verification + seller matching (deterministic, no AI) -----
    # Re-derive LIVE/CLOSED/... from deadlines between collection runs.
    status_check_interval_minutes: int = Field(default=15, ge=1)
    # Compare live tenders with every seller profile and keep match results current.
    matching_enabled: bool = True
    matching_interval_minutes: int = Field(default=15, ge=1)
    matching_max_evaluations_per_run: int = Field(default=500, ge=1, le=100000)

    # --- Ops --------------------------------------------------------------
    log_level: str = "INFO"
    log_format: str = "text"  # text | json
    save_debug_snapshots: bool = False
    debug_dir: str = "data/debug"
    lock_file: str = "data/collection.lock"
    kosh_private_storage_path: str = "private_storage"
    kosh_max_upload_mb: int = Field(default=10, ge=1, le=100)
    kosh_as_of_date: str = ""
    kosh_alert_threshold: float = Field(default=0.5, ge=0, le=1)
    kosh_plan_target_prob: Decimal = Field(default=Decimal("0.20"), ge=0, lt=1)
    kosh_plan_percentile: int = Field(default=25, ge=10, le=50)

    @field_validator("log_level")
    @classmethod
    def _upper_level(cls, v: str) -> str:
        return v.upper()

    @model_validator(mode="after")
    def _enforce_startup_safety(self) -> "Settings":
        self.assert_startup_safe()
        return self

    def assert_startup_safe(self) -> None:
        """Reject unsafe or contradictory startup configuration.

        Runs as a model validator and again from create_app(), because
        Settings.model_copy() bypasses validators.
        """
        problems: list[str] = []
        if self.app_startup_mode == "verify":
            if self.auto_migrate:
                problems.append("AUTO_MIGRATE must be false")
            if self.scheduler_enabled:
                problems.append("SCHEDULER_ENABLED must be false")
            if self.startup_recovery_enabled:
                problems.append("STARTUP_RECOVERY_ENABLED must be false")
            for flag in _WORKER_FLAGS:
                if getattr(self, flag):
                    problems.append(f"{flag.upper()} must be false")
        if self.app_env.strip().lower() == "production" and self.dev_login_enabled:
            problems.append("DEV_LOGIN_ENABLED must be false when APP_ENV=production")
        if self.app_env.strip().lower() == "production" and self.auto_migrate:
            problems.append("AUTO_MIGRATE must be false when APP_ENV=production "
                            "(apply migrations with scripts/migrate.py)")
        if problems:
            raise ValueError("Unsafe startup configuration: " + "; ".join(problems))

    @property
    def resolved_data_url(self) -> str:
        if self.gem_bid_data_url:
            return self.gem_bid_data_url
        parts = urlsplit(self.gem_bid_list_url)
        return f"{parts.scheme}://{parts.netloc}/all-bids-data"

    @property
    def source_origin(self) -> str:
        parts = urlsplit(self.gem_bid_list_url)
        return f"{parts.scheme}://{parts.netloc}"

    def resolve_path(self, value: str) -> Path:
        p = Path(value)
        return p if p.is_absolute() else PROJECT_ROOT / p

    @property
    def resolved_database_url(self) -> str:
        """Make relative SQLite paths relative to the project root, not the CWD."""
        url = self.database_url
        prefix = "sqlite:///"
        if url.startswith(prefix) and not url.startswith("sqlite:////"):
            rel = url[len(prefix):]
            if rel and rel != ":memory:":
                return prefix + str(self.resolve_path(rel))
        return url

    @property
    def resolved_document_storage_path(self) -> Path:
        """Resolve document storage path relative to project root."""
        return self.resolve_path(self.document_storage_path)

    @property
    def resolved_document_worker_lock_file(self) -> Path:
        if self.document_worker_lock_file:
            return self.resolve_path(self.document_worker_lock_file)
        return self.resolve_path(self.lock_file).with_name("document_worker.lock")

    @property
    def resolved_extraction_worker_lock_file(self) -> Path:
        if self.extraction_worker_lock_file:
            return self.resolve_path(self.extraction_worker_lock_file)
        return self.resolve_path(self.lock_file).with_name("extraction_worker.lock")

    @property
    def resolved_field_extraction_worker_lock_file(self) -> Path:
        if self.field_extraction_worker_lock_file:
            return self.resolve_path(self.field_extraction_worker_lock_file)
        return self.resolve_path(self.lock_file).with_name("field_extraction_worker.lock")

    @property
    def resolved_ai_analysis_worker_lock_file(self) -> Path:
        if self.ai_analysis_worker_lock_file:
            return self.resolve_path(self.ai_analysis_worker_lock_file)
        return self.resolve_path(self.lock_file).with_name("ai_analysis_worker.lock")

    def ai_api_key_value(self) -> str:
        """The secret itself - for the provider's request header ONLY. Never log or store it."""
        k = self.ai_api_key
        return k.get_secret_value() if isinstance(k, SecretStr) else str(k or "")

    @property
    def ai_provider_name(self) -> str:
        return (self.ai_provider or "").strip().lower()

    @property
    def resolved_scheduler_lock_file(self) -> Path:
        if self.scheduler_lock_file:
            return self.resolve_path(self.scheduler_lock_file)
        return self.resolve_path(self.lock_file).with_name("scheduler.lock")


@lru_cache
def get_settings() -> Settings:
    return Settings()
