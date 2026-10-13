"""Canonical GeM bid-number handling.

Canonical form: ``GEM/<YYYY>/<LETTER>/<DIGITS>`` e.g. ``GEM/2026/B/8014206``.
The letter segment is ``B`` for a bid and ``R`` for a reverse auction on the
public listing; other single letters are accepted but not interpreted.
"""

from __future__ import annotations

import re

_BID_RE = re.compile(r"^GEM/(\d{4})/([A-Z])/(\d{1,12})$")
_SEARCH_RE = re.compile(r"GEM\s*/\s*\d{4}\s*/\s*[A-Z]\s*/\s*\d{1,12}", re.IGNORECASE)

BID_TYPE_BY_SEGMENT = {"B": "BID", "R": "RA"}


class InvalidBidNumber(ValueError):
    pass


def normalize_bid_number(raw: object) -> str:
    """Return the canonical bid number or raise InvalidBidNumber."""
    if raw is None:
        raise InvalidBidNumber("bid number is missing")
    text = str(raw)
    # JSON-escaped slashes, odd whitespace (incl. NBSP) and casing.
    text = text.replace("\\/", "/").replace(" ", " ").strip().upper()
    text = re.sub(r"\s*/\s*", "/", text)
    text = re.sub(r"\s+", "", text)
    m = _BID_RE.match(text)
    if not m:
        raise InvalidBidNumber(f"not a GeM bid number: {str(raw)[:60]!r}")
    year = int(m.group(1))
    if not 2000 <= year <= 2100:
        raise InvalidBidNumber(f"implausible year in bid number: {text}")
    # Drop leading zeros in the serial so "0123" and "123" cannot diverge.
    serial = str(int(m.group(3)))
    return f"GEM/{m.group(1)}/{m.group(2)}/{serial}"


def try_normalize_bid_number(raw: object) -> str | None:
    try:
        return normalize_bid_number(raw)
    except InvalidBidNumber:
        return None


def find_bid_number(text: str) -> str | None:
    """Find the first bid number embedded in free text."""
    m = _SEARCH_RE.search(text or "")
    return try_normalize_bid_number(m.group(0)) if m else None


def bid_type_from_bid_number(bid_number: str) -> str | None:
    """Derive BID / RA from the canonical number's letter segment (evidence-based)."""
    parts = bid_number.split("/")
    if len(parts) != 4:
        return None
    return BID_TYPE_BY_SEGMENT.get(parts[2])
