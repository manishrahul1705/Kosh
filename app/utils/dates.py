"""Date/time helpers.

Storage convention: every timestamp is stored as a *naive UTC* datetime
(SQLite has no timezone type; PostgreSQL migrations can switch the columns to
TIMESTAMPTZ without changing values). The API re-attaches UTC on output.

Ambiguity rule: a timestamp without an explicit offset is never interpreted
silently. Callers must pass the zone the source is known to use; otherwise
``AmbiguousTimestampError`` is raised.
"""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")

_DISPLAY_FORMATS = (
    "%d-%m-%Y %I:%M %p",
    "%d-%m-%Y %I:%M:%S %p",
    "%d-%m-%Y %H:%M:%S",
    "%d-%m-%Y %H:%M",
    "%d/%m/%Y %I:%M %p",
    "%d/%m/%Y %H:%M:%S",
    "%d/%m/%Y %H:%M",
)


class AmbiguousTimestampError(ValueError):
    pass


def utcnow() -> datetime:
    """Current time as naive UTC (storage convention)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def to_utc_naive(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        raise AmbiguousTimestampError("refusing to convert a naive datetime without a zone")
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def as_aware_utc(dt: datetime | None) -> datetime | None:
    """Attach UTC to a stored naive-UTC value (for API output)."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_iso_to_utc(value: str | None, assume_zone: str | None = None) -> datetime | None:
    """Parse an ISO-8601 string to naive UTC.

    * ``2026-10-14T10:00:00Z`` / ``+05:30`` offsets are honoured.
    * A naive value is only accepted when ``assume_zone`` is given.
    * Empty input returns None.
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        if not assume_zone:
            raise AmbiguousTimestampError(f"timestamp has no offset: {value!r}")
        dt = dt.replace(tzinfo=ZoneInfo(assume_zone))
    return to_utc_naive(dt)


def parse_listing_timestamp(value: str | None, source_zone: str = "UTC") -> datetime | None:
    """Parse a listing-JSON timestamp.

    ``source_zone`` documents what the trailing ``Z`` really means for this
    source. With "UTC" (default) the offset is trusted. With another zone the
    wall-clock value is re-interpreted in that zone (explicit, configured
    decision; see README).
    """
    if value is None or not str(value).strip():
        return None
    text = str(value).strip()
    if source_zone.upper() == "UTC":
        return parse_iso_to_utc(text)
    if text.endswith(("Z", "z")):
        text = text[:-1]
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is not None:
        return to_utc_naive(dt)
    return to_utc_naive(dt.replace(tzinfo=ZoneInfo(source_zone)))


def parse_display_datetime(value: str | None, assume_zone: str | None) -> datetime | None:
    """Parse a human display string such as ``03-10-2026 7:00 PM``.

    GeM's HTML shows IST wall-clock times without an offset, so the caller
    must state the zone explicitly (normally ``Asia/Kolkata``).
    """
    if value is None or not str(value).strip():
        return None
    if not assume_zone:
        raise AmbiguousTimestampError(f"display timestamp needs an explicit zone: {value!r}")
    text = " ".join(str(value).split())
    for fmt in _DISPLAY_FORMATS:
        try:
            naive = datetime.strptime(text, fmt)
        except ValueError:
            continue
        return to_utc_naive(naive.replace(tzinfo=ZoneInfo(assume_zone)))
    raise ValueError(f"unrecognised date format: {value!r}")
