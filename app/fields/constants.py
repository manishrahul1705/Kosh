"""Stage 3B vocabulary. Bump FIELD_EXTRACTOR_VERSION when field semantics change
(a new current run is then produced; old runs stay as history)."""

from __future__ import annotations

from enum import Enum

FIELD_EXTRACTOR_NAME = "gem-fields"
FIELD_EXTRACTOR_VERSION = "stage3b-v6"


class ValueType(str, Enum):
    TEXT = "TEXT"
    INTEGER = "INTEGER"
    DECIMAL = "DECIMAL"
    PERCENT = "PERCENT"
    MONEY = "MONEY"
    DATETIME = "DATETIME"
    DATE = "DATE"
    DURATION = "DURATION"
    BOOL = "BOOL"        # three-state: TRUE / FALSE / UNKNOWN
    LIST = "LIST"


class FieldStatus(str, Enum):
    RESOLVED = "RESOLVED"
    CONFLICT = "CONFLICT"
    UNKNOWN = "UNKNOWN"


class TriState(str, Enum):
    TRUE = "TRUE"
    FALSE = "FALSE"
    UNKNOWN = "UNKNOWN"


class Reason(str, Enum):
    NOT_FOUND = "NOT_FOUND"
    MASKED_IN_SOURCE = "MASKED_IN_SOURCE"            # e.g. "***********"
    NOT_APPLICABLE_IN_SOURCE = "NOT_APPLICABLE_IN_SOURCE"  # e.g. "N/a"
    UNPARSEABLE = "UNPARSEABLE"
    CONFLICTING_EVIDENCE = "CONFLICTING_EVIDENCE"


class EvidenceType(str, Enum):
    TABLE_CELL = "TABLE_CELL"
    TABLE_ROW = "TABLE_ROW"
    SECTION_TEXT = "SECTION_TEXT"
    PAGE_TEXT = "PAGE_TEXT"
    DERIVED = "DERIVED"
    METADATA = "METADATA"


class Strength(str, Enum):
    """Rule/evidence strength - NOT a probability."""
    SYSTEM_METADATA = "SYSTEM_METADATA"   # Stage 2 / Stage 3A rows (bid number, version...)
    EXACT_TABLE = "EXACT_TABLE"           # structured table, label alias matched
    SECTION_TABLE = "SECTION_TABLE"       # structured table, label valid only inside a known section
    EXACT_LABEL = "EXACT_LABEL"           # "label value" line in page text
    SECTION_CONTEXT = "SECTION_CONTEXT"   # bounded pattern inside a known section (e.g. ATC clause)
    DERIVED = "DERIVED"                   # implied by another explicit candidate (e.g. EMD amount -> EMD required)
    REGEX_FALLBACK = "REGEX_FALLBACK"     # bounded pattern anywhere in page text


STRENGTH_RANK = {
    Strength.SYSTEM_METADATA.value: 0,
    Strength.EXACT_TABLE.value: 1,
    Strength.SECTION_TABLE.value: 2,
    Strength.EXACT_LABEL.value: 3,
    Strength.SECTION_CONTEXT.value: 4,
    Strength.DERIVED.value: 4,
    Strength.REGEX_FALLBACK.value: 5,
}
# Weaker *text-parsing* tiers: when they disagree with a single stronger value they
# are kept as OVERRIDDEN evidence (page-text parsing noise). Disagreement from any
# other tier (another table, an ATC clause, a derived fact) is a CONFLICT.
OVERRIDABLE = frozenset({Strength.EXACT_LABEL.value, Strength.REGEX_FALLBACK.value})


class Disposition(str, Enum):
    SELECTED = "SELECTED"
    AGREES = "AGREES"
    OVERRIDDEN = "OVERRIDDEN"
    CONFLICTING = "CONFLICTING"
    IGNORED = "IGNORED"     # masked / not-applicable / unparseable source value


class RunStatus(str, Enum):
    SUCCESS = "SUCCESS"
    PARTIAL_SUCCESS = "PARTIAL_SUCCESS"
    FAILED = "FAILED"


class FieldJobStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    PARTIAL_SUCCESS = "PARTIAL_SUCCESS"
    RETRY = "RETRY"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class FieldJobReason(str, Enum):
    STAGE3A_COMPLETED = "STAGE3A_COMPLETED"
    BACKFILL = "BACKFILL"
    MANUAL = "MANUAL"
    REEXTRACT = "REEXTRACT"


QUEUED_FIELD_JOB_STATUSES = (FieldJobStatus.PENDING.value, FieldJobStatus.RETRY.value)

# Stage 3A results Stage 3B may consume.
USABLE_STAGE3A_STATUSES = ("SUCCESS", "PARTIAL_SUCCESS")


class FieldErrorCode(str, Enum):
    STAGE3A_NOT_FOUND = "STAGE3A_NOT_FOUND"
    STAGE3A_NOT_USABLE = "STAGE3A_NOT_USABLE"       # OCR_REQUIRED / FAILED / UNSUPPORTED
    STAGE3A_SUPERSEDED = "STAGE3A_SUPERSEDED"       # not the current Stage 3A extraction
    ALREADY_EXTRACTED = "ALREADY_EXTRACTED"
    FIELD_CONFLICTS = "FIELD_CONFLICTS"
    STAGE3A_PARTIAL = "STAGE3A_PARTIAL"
    NO_FIELDS_FOUND = "NO_FIELDS_FOUND"
    DATABASE_ERROR = "DATABASE_ERROR"
    ENGINE_ERROR = "ENGINE_ERROR"
