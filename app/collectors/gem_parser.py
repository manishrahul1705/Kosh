"""GeM BidPlus listing parsing (pure functions, no network).

How the public listing works (inspected 2026-10-04, see README "Collector
strategy"): ``/all-bids`` is a JavaScript shell. The page itself POSTs to
``/all-bids-data`` (form fields ``payload`` = JSON search/filter/page and
``csrf_bd_gem_nk`` = an anti-CSRF token embedded in the public page) and gets
JSON back: ``{"code":200,"response":{"response":{"numFound":N,"docs":[...]}}}``
with ~10 docs per page. Most doc fields are single-element lists.
"""

from __future__ import annotations

import json
import re
from typing import Any

from app.collectors.base import ItemFailure
from app.core.constants import TenderStatus
from app.schemas.tender import TenderRecord
from app.utils.bid_number import InvalidBidNumber, bid_type_from_bid_number, normalize_bid_number
from app.utils.dates import parse_listing_timestamp

CSRF_FIELD = "csrf_bd_gem_nk"
CSRF_COOKIE = "csrf_gem_cookie"
STATUS_FILTER_ONGOING = "ongoing_bids"

_TOKEN_RE = re.compile(r"csrf_bd_gem_nk['\"]?\s*[:=,]\s*['\"]?([0-9a-fA-F]{16,})")
_TOKEN_INPUT_RE = re.compile(
    r"name=['\"]csrf_bd_gem_nk['\"][^>]*value=['\"]([^'\"]+)['\"]"
    r"|value=['\"]([^'\"]+)['\"][^>]*name=['\"]csrf_bd_gem_nk['\"]",
    re.IGNORECASE,
)

# Markers of CAPTCHA / human verification / WAF block pages. Matching any of
# these stops the run (BLOCKED_BY_HUMAN_VERIFICATION); nothing is solved.
_BLOCK_MARKERS = (
    "captcha",
    "recaptcha",
    "hcaptcha",
    "cf-challenge",
    "challenge-platform",
    "verify you are human",
    "are you a robot",
    "human verification",
    "request rejected",
    "access denied",
    "the requested url was rejected",
    "attention required",
)

# Doc keys we expect on a listing doc; used to sanity check the payload shape.
KNOWN_DOC_KEYS = (
    "b_bid_number", "b_id", "b_category_name", "bd_category_name", "bbt_title",
    "b_total_quantity", "final_start_date_sort", "final_end_date_sort",
    "ba_official_details_minName", "ba_official_details_deptName",
)


class PayloadShapeError(ValueError):
    """The response is JSON but not the listing structure we understand."""


def build_listing_form(page: int, sort: str, status_filter: str = STATUS_FILTER_ONGOING) -> dict[str, str]:
    """The form body the public listing page posts (minus the CSRF field)."""
    payload = {
        "page": page,
        "param": {"searchBid": "", "searchType": "fullText"},
        "filter": {
            "bidStatusType": status_filter,
            "byType": "all",
            "highBidValue": "",
            "byEndDate": {"from": "", "to": ""},
            "sort": sort,
        },
    }
    return {"payload": json.dumps(payload, separators=(",", ":"))}


def extract_csrf_token(html: str) -> str | None:
    m = _TOKEN_RE.search(html or "")
    if m:
        return m.group(1)
    m = _TOKEN_INPUT_RE.search(html or "")
    if m:
        return m.group(1) or m.group(2)
    return None


def detect_block(text: str | None, http_status: int | None = None) -> str | None:
    """Return a reason string when the response is an access-control page."""
    if http_status == 403:
        return "HTTP 403 Forbidden (access denied by source)"
    if not text:
        return None
    head = text[:20000].lower()
    # A JSON listing payload is never a block page.
    if head.lstrip().startswith("{") and '"response"' in head:
        return None
    for marker in _BLOCK_MARKERS:
        if marker in head:
            return f"challenge marker detected: {marker!r}"
    return None


def redact_secrets(text: str) -> str:
    """Strip CSRF tokens / session-ish values before writing debug snapshots."""
    text = _TOKEN_RE.sub("csrf_bd_gem_nk=<redacted>", text)
    text = re.sub(r"(?i)(csrf[_a-z]*['\"]?\s*[:=]\s*['\"]?)[0-9a-z]{12,}", r"\1<redacted>", text)
    text = re.sub(r"(?i)(set-cookie|cookie)\s*:\s*[^\n]+", r"\1: <redacted>", text)
    return text


def _first(value: Any) -> Any:
    if isinstance(value, list):
        return value[0] if value else None
    return value


def _text(value: Any) -> str | None:
    v = _first(value)
    if v is None:
        return None
    s = " ".join(str(v).split())
    return s or None


def _int(value: Any) -> int | None:
    v = _first(value)
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    try:
        s = str(v).strip().replace(",", "")
        return int(float(s)) if s else None
    except ValueError:
        return None


def unpack_listing_payload(payload: dict[str, Any]) -> tuple[list[Any], int | None]:
    """Return (docs, numFound). ``{}`` means an empty page."""
    if not payload:
        return [], None
    if not isinstance(payload, dict):
        raise PayloadShapeError("listing payload is not a JSON object")
    code = payload.get("code")
    outer = payload.get("response")
    if code not in (None, 200, "200") and not outer:
        raise PayloadShapeError(f"listing returned code={code!r} message={payload.get('message')!r}")
    inner = (outer or {}).get("response") if isinstance(outer, dict) else None
    if not isinstance(inner, dict):
        raise PayloadShapeError("listing payload missing response.response")
    docs = inner.get("docs") or []
    if not isinstance(docs, list):
        raise PayloadShapeError("listing docs is not a list")
    total = inner.get("numFound")
    return docs, int(total) if isinstance(total, (int, str)) and str(total).isdigit() else None


def doc_to_record(
    doc: dict[str, Any],
    *,
    source_origin: str,
    timestamp_zone: str = "UTC",
    status: TenderStatus = TenderStatus.ONGOING,
) -> TenderRecord:
    """Map one listing doc to a TenderRecord. Raises on unusable docs."""
    if not isinstance(doc, dict):
        raise ValueError("doc is not an object")
    bid_number = normalize_bid_number(_first(doc.get("b_bid_number")))

    # bbt_title is the human title when present; otherwise the listing shows
    # the item/category name (b_category_name) as the bid's headline.
    title = _text(doc.get("bbt_title")) or _text(doc.get("b_category_name"))
    category = _text(doc.get("bd_category_name")) or _text(doc.get("b_category_name"))

    internal_id = _text(doc.get("b_id")) or _text(doc.get("id"))
    source_url = f"{source_origin}/showbidDocument/{internal_id}" if internal_id else None

    return TenderRecord(
        bid_number=bid_number,
        title=title,
        bid_type=bid_type_from_bid_number(bid_number),
        buyer_name=None,  # not exposed by the public listing
        ministry=_text(doc.get("ba_official_details_minName")),
        department=_text(doc.get("ba_official_details_deptName")),
        organisation=None,  # not exposed by the public listing
        category=category,
        quantity=_int(doc.get("b_total_quantity")),
        estimated_value=None,  # not exposed by the public listing
        published_at=parse_listing_timestamp(_text(doc.get("final_start_date_sort")), timestamp_zone),
        bid_end_at=parse_listing_timestamp(_text(doc.get("final_end_date_sort")), timestamp_zone),
        bid_opening_at=None,  # not exposed by the public listing
        source_url=source_url,
        status=status,
        source_internal_id=internal_id,
    )


def parse_listing_page(
    payload: dict[str, Any],
    *,
    page: int,
    source_origin: str,
    timestamp_zone: str = "UTC",
    status: TenderStatus = TenderStatus.ONGOING,
) -> tuple[list[TenderRecord], list[ItemFailure], int, int | None]:
    """Parse a page. Returns (records, failures, doc_count, numFound).

    A malformed doc becomes an ItemFailure; it never aborts the page.
    """
    docs, total = unpack_listing_payload(payload)
    records: list[TenderRecord] = []
    failures: list[ItemFailure] = []
    for idx, doc in enumerate(docs):
        hint = None
        if isinstance(doc, dict):
            raw_bid = _first(doc.get("b_bid_number"))
            hint = str(raw_bid)[:60] if raw_bid is not None else None
        try:
            records.append(
                doc_to_record(doc, source_origin=source_origin, timestamp_zone=timestamp_zone, status=status)
            )
        except InvalidBidNumber as exc:
            failures.append(ItemFailure(page, idx, f"invalid bid number: {exc}", hint))
        except Exception as exc:  # malformed field values etc.
            failures.append(ItemFailure(page, idx, f"{type(exc).__name__}: {str(exc)[:200]}", hint))
    return records, failures, len(docs), total
