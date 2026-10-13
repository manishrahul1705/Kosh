"""Stage 3A vocabulary. Bump EXTRACTOR_VERSION whenever extraction output changes
in a way that should produce a NEW current extraction (old ones stay as history)."""

from __future__ import annotations

from enum import Enum

EXTRACTOR_NAME = "pdfplumber"
EXTRACTOR_VERSION = "stage3a-v3"
TABLE_METHOD = "pdfplumber:lines"


class ExtractionStatus(str, Enum):
    SUCCESS = "SUCCESS"
    PARTIAL_SUCCESS = "PARTIAL_SUCCESS"
    OCR_REQUIRED = "OCR_REQUIRED"
    FAILED = "FAILED"
    UNSUPPORTED = "UNSUPPORTED"


class QualityStatus(str, Enum):
    GOOD = "GOOD"
    PARTIAL = "PARTIAL"
    OCR_REQUIRED = "OCR_REQUIRED"
    EMPTY = "EMPTY"
    FAILED = "FAILED"
    UNSUPPORTED = "UNSUPPORTED"


class TextClass(str, Enum):
    OCR = "OCR"
    MIXED = "MIXED"
    TEXT_NATIVE = "TEXT_NATIVE"
    TEXT_PARTIAL = "TEXT_PARTIAL"
    LIKELY_SCANNED = "LIKELY_SCANNED"
    EMPTY = "EMPTY"
    UNSUPPORTED = "UNSUPPORTED"


class ExtractionJobStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    PARTIAL_SUCCESS = "PARTIAL_SUCCESS"
    RETRY = "RETRY"
    FAILED = "FAILED"
    OCR_REQUIRED = "OCR_REQUIRED"
    SKIPPED = "SKIPPED"


class ExtractionJobReason(str, Enum):
    NEW_VERSION = "NEW_VERSION"   # queued by Stage 2 after a new version was committed
    BACKFILL = "BACKFILL"
    MANUAL = "MANUAL"
    REEXTRACT = "REEXTRACT"       # force=True


QUEUED_EXTRACTION_STATUSES = (ExtractionJobStatus.PENDING.value, ExtractionJobStatus.RETRY.value)
ACTIVE_EXTRACTION_STATUSES = QUEUED_EXTRACTION_STATUSES + (ExtractionJobStatus.RUNNING.value,)


class ErrorCode(str, Enum):
    VERSION_NOT_FOUND = "VERSION_NOT_FOUND"
    VERSION_NOT_ELIGIBLE = "VERSION_NOT_ELIGIBLE"     # not VALID / no storage_path
    UNSAFE_PATH = "UNSAFE_PATH"                       # escapes storage root
    FILE_MISSING = "FILE_MISSING"
    FILE_UNREADABLE = "FILE_UNREADABLE"
    FILE_HASH_MISMATCH = "FILE_HASH_MISMATCH"         # bytes differ from Stage 2 sha256
    PDF_CORRUPT = "PDF_CORRUPT"
    PASSWORD_PROTECTED = "PASSWORD_PROTECTED"
    UNSUPPORTED_FILE_TYPE = "UNSUPPORTED_FILE_TYPE"
    PARSER_ERROR = "PARSER_ERROR"
    DATABASE_ERROR = "DATABASE_ERROR"
    OCR_REQUIRED = "OCR_REQUIRED"
    PAGE_LIMIT = "PAGE_LIMIT"
    PAGE_ERRORS = "PAGE_ERRORS"
    PAGES_NEED_OCR = "PAGES_NEED_OCR"
    ALREADY_EXTRACTED = "ALREADY_EXTRACTED"


# Retryable = may succeed later without code changes (Stage 2 restores the file,
# transient I/O or DB contention). Everything else is permanent for that version.
RETRYABLE_ERRORS = frozenset({ErrorCode.FILE_MISSING.value, ErrorCode.FILE_UNREADABLE.value,
                              ErrorCode.DATABASE_ERROR.value})


class ExtractionError(Exception):
    def __init__(self, code: ErrorCode | str, message: str):
        self.code = code.value if isinstance(code, ErrorCode) else str(code)
        self.message = message
        super().__init__(f"{self.code}: {message}")

    @property
    def retryable(self) -> bool:
        return self.code in RETRYABLE_ERRORS
