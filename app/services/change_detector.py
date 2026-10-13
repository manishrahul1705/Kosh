"""Fingerprinting and field-level diffing on normalized metadata (never HTML)."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from app.core.constants import TRACKED_FIELDS


def canonical_value(value: Any) -> str | None:
    """Stable string form used for fingerprints and the audit trail."""
    if value is None:
        return None
    if isinstance(value, Enum):
        return str(value.value)
    if isinstance(value, datetime):
        # Stored values are naive UTC; render explicitly as UTC.
        if value.tzinfo is not None:
            raise ValueError("expected naive UTC datetime")
        return value.isoformat(timespec="seconds") + "Z"
    if isinstance(value, Decimal):
        normalized = value.normalize()
        # Avoid scientific notation for integral values (Decimal('1E+3')).
        return format(normalized, "f")
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def tracked_values(obj: Any) -> dict[str, str | None]:
    """Extract tracked fields from a TenderRecord or a Tender ORM row."""
    return {name: canonical_value(getattr(obj, name, None)) for name in TRACKED_FIELDS}


def compute_fingerprint(obj: Any) -> str:
    payload = json.dumps(tracked_values(obj), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def diff_fields(old: Any, new: Any) -> list[tuple[str, str | None, str | None]]:
    """Return [(field, old_value, new_value)] for tracked fields that differ."""
    before, after = tracked_values(old), tracked_values(new)
    return [(f, before[f], after[f]) for f in TRACKED_FIELDS if before[f] != after[f]]
