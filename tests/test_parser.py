"""Bid-number normalization, listing parsing, block detection, date parsing."""

from __future__ import annotations

import json
from datetime import datetime

import pytest

from app.collectors.gem_parser import (
    PayloadShapeError,
    build_listing_form,
    detect_block,
    extract_csrf_token,
    parse_listing_page,
    redact_secrets,
)
from app.core.constants import TenderStatus
from app.utils.bid_number import (
    InvalidBidNumber,
    bid_type_from_bid_number,
    find_bid_number,
    normalize_bid_number,
)
from app.utils.dates import (
    AmbiguousTimestampError,
    parse_display_datetime,
    parse_iso_to_utc,
    parse_listing_timestamp,
)
from tests.conftest import FIXTURES, ORIGIN


# --- 1. Bid number normalization -------------------------------------------
@pytest.mark.parametrize(
    "raw",
    ["GEM/2026/B/8014206", "gem/2026/b/8014206", " GEM/2026/B/8014206", "GEM/2026/B/8014206 \n",
     "GEM / 2026 / B / 8014206", "GEM\\/2026\\/B\\/8014206", "GEM/2026/B/08014206", " gem/2026/B/8014206"],
)
def test_bid_number_variants_resolve_to_canonical(raw):
    assert normalize_bid_number(raw) == "GEM/2026/B/8014206"


@pytest.mark.parametrize("raw", [None, "", "GEM/26/B/1", "GEM/2026/BB/1", "XYZ/2026/B/1", "GEM/2026/B/", "GEM/1899/B/5"])
def test_invalid_bid_numbers_rejected(raw):
    with pytest.raises(InvalidBidNumber):
        normalize_bid_number(raw)


def test_bid_type_from_segment_and_search():
    assert bid_type_from_bid_number("GEM/2026/B/1") == "BID"
    assert bid_type_from_bid_number("GEM/2026/R/1") == "RA"
    assert bid_type_from_bid_number("GEM/2026/Q/1") is None
    assert find_bid_number("Bid No.: gem/2026/b/123 dated today") == "GEM/2026/B/123"


# --- 2. Listing parsing ------------------------------------------------------
def _load(path):
    return json.loads(path.read_text())


def test_parse_listing_page_maps_fields():
    payload = _load(FIXTURES / "mock_abc" / "initial" / "page_1.json")
    records, failures, doc_count, total = parse_listing_page(payload, page=1, source_origin=ORIGIN)
    assert (doc_count, total, failures) == (3, 3, [])
    a = records[0]
    assert a.bid_number == "GEM/2026/B/8100101"
    assert a.title == "Tender A - Desktop Computers"
    assert a.category == "Desktop Computers"
    assert a.quantity == 11
    assert a.ministry == "Ministry of Defence"
    assert a.department == "Department of Military Affairs"
    assert a.bid_type == "BID"
    assert a.status is TenderStatus.ONGOING
    assert a.source_url == f"{ORIGIN}/showbidDocument/9000101"
    assert a.bid_end_at == datetime(2026, 10, 20, 9, 30)  # stored as naive UTC
    assert a.published_at == datetime(2026, 10, 1, 4, 30)


def test_missing_fields_stay_null_not_invented():
    payload = _load(FIXTURES / "mock_abc" / "initial" / "page_1.json")
    rec = parse_listing_page(payload, page=1, source_origin=ORIGIN)[0][0]
    assert rec.estimated_value is None
    assert rec.buyer_name is None
    assert rec.organisation is None
    assert rec.bid_opening_at is None


def test_bbt_title_preferred_when_present():
    payload = _load(FIXTURES / "mock_abc" / "initial" / "page_1.json")
    payload["response"]["response"]["docs"][0]["bbt_title"] = ["Atomic Layer Deposition System"]
    rec = parse_listing_page(payload, page=1, source_origin=ORIGIN)[0][0]
    assert rec.title == "Atomic Layer Deposition System"


def test_malformed_items_become_failures_not_crashes():
    payload = _load(FIXTURES / "malformed" / "page_1.json")
    records, failures, doc_count, _ = parse_listing_page(payload, page=4, source_origin=ORIGIN)
    assert doc_count == 5
    assert len(records) == 3
    assert len(failures) == 2
    assert {f.page for f in failures} == {4}
    assert failures[1].hint == "NOT-A-BID"


def test_bad_field_value_is_item_failure():
    payload = _load(FIXTURES / "mock_abc" / "initial" / "page_1.json")
    payload["response"]["response"]["docs"][1]["final_end_date_sort"] = ["not-a-date"]
    records, failures, _, _ = parse_listing_page(payload, page=1, source_origin=ORIGIN)
    assert len(records) == 2 and len(failures) == 1


def test_empty_and_wrong_shape_payloads():
    assert parse_listing_page({}, page=9, source_origin=ORIGIN)[2] == 0
    with pytest.raises(PayloadShapeError):
        parse_listing_page({"code": 500, "message": "error"}, page=1, source_origin=ORIGIN)
    with pytest.raises(PayloadShapeError):
        parse_listing_page({"code": 200, "response": {"foo": 1}}, page=1, source_origin=ORIGIN)


def test_listing_form_requests_ongoing_bids():
    form = build_listing_form(3, "Bid-Start-Date-Latest")
    payload = json.loads(form["payload"])
    assert payload["page"] == 3
    assert payload["filter"]["bidStatusType"] == "ongoing_bids"
    assert payload["filter"]["sort"] == "Bid-Start-Date-Latest"


def test_csrf_token_extraction_and_redaction():
    html = (FIXTURES / "listing_shell.html").read_text()
    token = extract_csrf_token(html)
    assert token == "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
    assert token not in redact_secrets(html)
    assert extract_csrf_token('<input type="hidden" name="csrf_bd_gem_nk" value="abc123">') == "abc123"
    assert extract_csrf_token("<html>nothing</html>") is None


# --- Block detection ---------------------------------------------------------
def test_block_detection():
    assert detect_block((FIXTURES / "blocked" / "page_2.html").read_text())
    assert detect_block("<html>Request Rejected. The requested URL was rejected</html>")
    assert detect_block("anything", http_status=403)
    assert detect_block('{"code":200,"response":{"response":{"docs":[]}}}') is None
    assert detect_block("<html>ordinary page</html>") is None


# --- 10. Date parsing -------------------------------------------------------
def test_iso_with_offsets_converted_to_utc():
    assert parse_iso_to_utc("2026-10-14T10:00:00Z") == datetime(2026, 10, 14, 10, 0)
    assert parse_iso_to_utc("2026-10-14T15:30:00+05:30") == datetime(2026, 10, 14, 10, 0)
    assert parse_iso_to_utc("") is None


def test_naive_timestamp_is_never_silently_interpreted():
    with pytest.raises(AmbiguousTimestampError):
        parse_iso_to_utc("2026-10-14T10:00:00")
    assert parse_iso_to_utc("2026-10-14T15:30:00", assume_zone="Asia/Kolkata") == datetime(2026, 10, 14, 10, 0)
    with pytest.raises(AmbiguousTimestampError):
        parse_display_datetime("03-10-2026 7:00 PM", assume_zone=None)


def test_display_dates_in_ist():
    assert parse_display_datetime("03-10-2026 7:00 PM", "Asia/Kolkata") == datetime(2026, 10, 3, 13, 30)
    assert parse_display_datetime("10-10-2026 15:00:00", "Asia/Kolkata") == datetime(2026, 10, 10, 9, 30)
    with pytest.raises(ValueError):
        parse_display_datetime("tomorrow", "Asia/Kolkata")


def test_listing_timestamp_zone_override():
    assert parse_listing_timestamp("2026-10-14T10:00:00Z", "UTC") == datetime(2026, 10, 14, 10, 0)
    # If the trailing Z were verified to be a mislabelled IST wall clock:
    assert parse_listing_timestamp("2026-10-14T10:00:00Z", "Asia/Kolkata") == datetime(2026, 10, 14, 4, 30)
