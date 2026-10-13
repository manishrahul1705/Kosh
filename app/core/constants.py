"""Application-wide constants (no GeM-specific parsing logic lives here)."""

from __future__ import annotations

from enum import Enum


class TenderStatus(str, Enum):
    ONGOING = "ONGOING"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"
    UNKNOWN = "UNKNOWN"


class RunStatus(str, Enum):
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    PARTIAL_SUCCESS = "PARTIAL_SUCCESS"
    FAILED = "FAILED"
    BLOCKED_BY_HUMAN_VERIFICATION = "BLOCKED_BY_HUMAN_VERIFICATION"


class TriggerType(str, Enum):
    SCHEDULED = "scheduled"
    MANUAL = "manual"
    CLI = "cli"


class CollectorMode(str, Enum):
    AUTO = "auto"
    HTTP = "http"
    BROWSER = "browser"
    FIXTURE = "fixture"


class Classification(str, Enum):
    NEW = "NEW"
    UPDATED = "UPDATED"
    UNCHANGED = "UNCHANGED"
    FAILED = "FAILED"


# Fields that participate in the source fingerprint and in field-level change
# detection. Volatile bookkeeping fields (last_seen_at, updated_at, ...) are
# deliberately excluded.
TRACKED_FIELDS: tuple[str, ...] = (
    "title",
    "bid_type",
    "buyer_name",
    "ministry",
    "department",
    "organisation",
    "category",
    "quantity",
    "estimated_value",
    "published_at",
    "bid_end_at",
    "bid_opening_at",
    "source_url",
    "status",
)

BLOCKED_EVENT = "BLOCKED_BY_HUMAN_VERIFICATION"
