"""Stage 3B: deterministic tender field extraction from Stage 3A rows.

Stage 3A rows are written directly (tests/stage3a_rows.py) - no PDFs, no network.
One end-to-end test goes PDF -> Stage 3A -> hook -> Stage 3B with a generated PDF.
"""

from __future__ import annotations

import ast
import hashlib
import json
import socket
import threading
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError

from app.core.config import PROJECT_ROOT, Settings
from app.database.models import (
    DocumentExtraction,
    DocumentPage,
    DocumentSection,
    DocumentTable,
    FieldExtractionJob,
    TenderFieldEvidence,
    TenderFieldExtraction,
    TenderFieldValue,
)
from app.fields import job_queue as fq
from app.fields.constants import FieldJobReason, FIELD_EXTRACTOR_VERSION
from app.fields.engine import run_engine
from app.fields.evidence import Candidate, load_source
from app.fields.job_queue import backfill_field_jobs, enqueue_field_extraction
from app.fields.job_worker import SKIP_BUSY, FieldExtractionJobWorker
from app.fields.labels import english_label, label_key
from app.fields.normalizers import (
    Rejected,
    norm_bool,
    norm_datetime,
    norm_duration,
    norm_integer,
    norm_money,
    norm_percent,
    norm_text,
)
from app.fields.registry import BY_NAME, FIELDS
from app.fields.resolver import resolve
from app.fields.service import ALREADY, EXTRACTED, NOT_READY, FieldExtractionService
from app.utils.dates import utcnow
from tests.stage3a_rows import BASE_PAGES, BASE_SECTIONS, BASE_TABLES, H, drop_rows, make_stage3a, replace_row


# ---------------------------------------------------------------------------
class Clock:
    def __init__(self):
        self.now = utcnow()

    def __call__(self):
        return self.now

    def advance(self, **kw):
        self.now += timedelta(**kw)


@pytest.fixture
def fsettings(settings: Settings, tmp_path: Path) -> Settings:
    return settings.model_copy(update={"document_storage_path": str(tmp_path / "tenders"),
                                       "field_extraction_max_attempts": 3,
                                       "field_extraction_retry_backoff_minutes": 5.0})


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def fservice(fsettings, session_factory, clock):
    return FieldExtractionService(fsettings, session_factory, clock=clock)


@pytest.fixture
def fworker(fsettings, session_factory, fservice, clock):
    return FieldExtractionJobWorker(fsettings, session_factory, fservice, clock=clock)


def fresh(db):
    db.commit()
    db.expire_all()


def fields_of(db, stage3a_id) -> dict:
    with_src = load_source(db, stage3a_id)
    db.rollback()
    return run_engine(with_src).by_name()


def val(results, name):
    r = results[name]
    return r.selected.value if r.selected is not None else None


def values_of(db, run_id) -> dict[str, TenderFieldValue]:
    fresh(db)
    return {v.field_name: v for v in db.scalars(select(TenderFieldValue).where(
        TenderFieldValue.field_extraction_id == run_id))}


def evidence_of(db, run_id, field) -> list[TenderFieldEvidence]:
    fresh(db)
    return list(db.scalars(select(TenderFieldEvidence).where(TenderFieldEvidence.field_extraction_id == run_id,
                                                             TenderFieldEvidence.field_name == field)
                           .order_by(TenderFieldEvidence.id)))


def stage3a_digest(db, eid) -> str:
    fresh(db)
    h = hashlib.sha256()
    for model in (DocumentExtraction, DocumentPage, DocumentTable, DocumentSection):
        col = DocumentExtraction.id if model is DocumentExtraction else model.extraction_id
        for row in db.scalars(select(model).where(col == eid).order_by(model.id)):
            h.update(repr([getattr(row, c.name) for c in model.__table__.columns]).encode())
    return h.hexdigest()


# ===========================================================================
# 4-13. table extraction, labels, normalization, three-state
# ===========================================================================
def test_exact_table_fields_from_bilingual_labels(db):
    e = make_stage3a(db)
    r = fields_of(db, e.id)
    assert val(r, "ministry_state") == "Ministry Of Defence"
    assert val(r, "department") == "Department Of Military Affairs"
    assert val(r, "organisation") == "Indian Army"                     # 20
    assert val(r, "item_category") == "Paintball Gun Set"              # 19
    assert val(r, "total_quantity") == 2                               # 18
    assert val(r, "bid_type") == "Two Packet Bid"                      # 21
    assert val(r, "evaluation_method") == "Total value wise evaluation"  # 22
    assert val(r, "bid_offer_validity_days") == 155
    assert r["total_quantity"].strength == "EXACT_TABLE"
    assert r["item_description"].selected.value == ["Paintball Gun Set ( 2 per seat )"]


def test_english_label_extraction_and_replacement_glyph_tolerance():
    assert english_label(f"{H}बड {H}ववरण/Bid Opening\nDate/Time") == "Bid Opening Date/Time"
    assert english_label(f"िनर{H}{H}ण आव{H}यक/Inspection Required (By\nEmpanelled)") == \
        "Inspection Required (By Empanelled)"
    assert english_label("Past Performance") == "Past Performance"
    assert label_key("ePBG Percentage(%)") == "epbg percentage"
    assert BY_NAME["inspection_required"].aliases[0].matches(
        label_key(english_label(f"िनर{H}{H}ण/Inspection Required (By Empanelled Inspection Authority)")))
    assert BY_NAME["mse_experience_turnover_relaxation"].aliases[0].matches(
        label_key("MSE Relaxation for Years Of Experience and Turnover"))  # real "Of" variant


def test_date_normalization_uses_document_timezone():
    n = norm_datetime("16-10-2026 21:00:00", "Asia/Kolkata")
    assert n.value == {"local": "2026-10-16T21:00:00+05:30", "utc": "2026-10-16T15:30:00Z", "timezone": "Asia/Kolkata"}
    assert norm_datetime("06-10-2026", "Asia/Kolkata", date_only=True).value == {"date": "2026-10-06"}
    assert isinstance(norm_datetime("31-02-2026 10:00", "Asia/Kolkata"), Rejected)


def test_integer_percent_duration_normalization():
    assert norm_integer("155 (Days)").value == 155 and isinstance(norm_integer("2.5"), Rejected)
    assert norm_percent("10 %").value == 10.0 and norm_percent("5.00").value == 5.0
    assert isinstance(norm_percent("150"), Rejected)
    assert norm_duration("2 Days").value == {"value": 2.0, "unit": "DAYS"}
    assert norm_duration("2 Year (s)").value == {"value": 2.0, "unit": "YEARS"}
    assert norm_duration("1.0 (year)").key == norm_duration("1 Year").key
    assert norm_duration("12", "MONTHS").value == {"value": 12.0, "unit": "MONTHS"}
    assert isinstance(norm_duration("12"), Rejected)  # unit never guessed
    assert norm_duration("1 Year(s) 1 Day(s)").text == "1 YEARS 1 DAYS"


def test_currency_normalization():
    for raw in ("₹ 50,000", "Rs. 50000", "INR 50,000"):
        n = norm_money(raw)
        assert (n.number, n.value["currency"]) == (50000.0, "INR"), raw
    lakh = norm_money("20 Lakh (s)")
    assert lakh.number == 2_000_000 and lakh.value["currency"] is None   # currency not assumed
    assert lakh.value["stated_unit"] == "LAKH"
    assert norm_money("1,00,000").number == 100000
    assert norm_money("1.5 Crore").number == 15_000_000
    assert norm_money("26000", currency_hint="INR").value["currency"] == "INR"


def test_boolean_normalization_is_careful():
    assert norm_bool("Yes").tri_state == "TRUE" and norm_bool("No").tri_state == "FALSE"
    assert norm_bool("Yes | Complete").details == {"qualifier": "Complete"}
    assert norm_bool("Required").tri_state == "TRUE" and norm_bool("Not Required").tri_state == "FALSE"
    assert norm_bool("Applicable").tri_state == "TRUE" and norm_bool("Not Applicable").tri_state == "FALSE"
    assert isinstance(norm_bool("Maybe later"), Rejected)
    assert norm_text("***********").reason == "MASKED_IN_SOURCE"
    assert norm_text("N/a").reason == "NOT_APPLICABLE_IN_SOURCE"


def test_three_state_and_missing_is_unknown_not_false(db):
    e = make_stage3a(db, tables=drop_rows(BASE_TABLES, "Bid to RA enabled", "Arbitration Clause"))
    r = fields_of(db, e.id)
    assert r["mediation_clause"].tri_state == "FALSE"                         # explicit "No"
    for name in ("bid_to_ra_enabled", "manufacturer_authorization_required", "emd_exemption_allowed"):
        assert (r[name].status, r[name].tri_state, r[name].reason) == ("UNKNOWN", "UNKNOWN", "NOT_FOUND"), name
    assert r["arbitration_clause"].status == "UNKNOWN"                         # page text has no such line either
    assert r["office"].status == "UNKNOWN" and r["office"].reason == "MASKED_IN_SOURCE"
    assert r["estimated_bid_value"].reason == "NOT_FOUND"


# ===========================================================================
# 14-17. EMD / ePBG
# ===========================================================================
def test_emd_no_is_false_via_section_context(db):
    r = fields_of(db, make_stage3a(db).id)
    assert r["emd_required"].tri_state == "FALSE" and r["emd_required"].strength == "SECTION_TABLE"
    assert r["epbg_required"].tri_state == "FALSE"
    assert r["emd_required"].candidates[0].section_heading == "emd detail"


def test_emd_yes_from_amount_and_explicit_required(db):
    tables = [t for t in BASE_TABLES if not (t[0] == 2 and t[1] == 2)] + [
        (2, 2, 677.0, [["एडवाईजर{H} ब{H}क/Advisory Bank", "State Bank of India"], ["ईएमड{H} रािश/EMD Amount", "26000"]])]
    r = fields_of(db, make_stage3a(db, tables=tables).id)
    assert r["emd_required"].tri_state == "TRUE" and r["emd_required"].strength == "DERIVED"
    assert r["emd_amount"].selected.number == 26000 and r["emd_advisory_bank"].selected.value == "State Bank of India"
    assert r["epbg_required"].tri_state == "FALSE"     # ePBG "Required" row is NOT confused with EMD
    tables2 = replace_row(BASE_TABLES, "Required", "Yes")
    r2 = fields_of(db, make_stage3a(db, bid="GEM/2026/B/1", tables=tables2).id)
    assert r2["emd_required"].tri_state == "TRUE"


def test_emd_unknown_without_emd_section(db):
    sections = [s for s in BASE_SECTIONS if s[3] not in ("emd detail", "epbg detail")]
    r = fields_of(db, make_stage3a(db, sections=sections).id)
    # The bare "Required: No" rows now have no EMD/ePBG section context -> never guessed
    assert r["emd_required"].status == "UNKNOWN" and r["epbg_required"].status == "UNKNOWN"


def test_epbg_parsing(db):
    tables = [t for t in BASE_TABLES if not (t[0] == 2 and t[1] == 3)] + [
        (2, 3, 754.0, [["Advisory Bank", "PUNJAB NATIONAL BANK"], ["ePBG Percentage(%)", "3.00"],
                       ["Duration of ePBG required (Months).", "12"]])]
    r = fields_of(db, make_stage3a(db, tables=tables).id)
    assert r["epbg_percentage"].selected.value == 3.0
    assert r["epbg_duration"].selected.value == {"value": 12.0, "unit": "MONTHS"}
    assert r["epbg_required"].tri_state == "TRUE" and r["epbg_advisory_bank"].selected.value == "PUNJAB NATIONAL BANK"
    assert r["emd_advisory_bank"].status == "UNKNOWN"


# ===========================================================================
# 18-37. individual fields
# ===========================================================================
def test_inspection_past_performance_preferences_relaxations(db):
    r = fields_of(db, make_stage3a(db).id)
    assert r["inspection_required"].tri_state == "FALSE"                      # 23
    assert val(r, "past_performance_percentage") == 10.0                      # 24
    assert r["past_performance_required"].tri_state == "TRUE"
    assert r["mse_experience_turnover_relaxation"].tri_state == "FALSE"       # 28
    assert r["startup_experience_turnover_relaxation"].tri_state == "FALSE"   # 29
    assert r["mse_purchase_preference"].tri_state == "TRUE"                   # 30
    assert val(r, "mse_price_preference_percent") == 15.0 and val(r, "mse_quantity_preference_percent") == 25.0
    assert r["mii_purchase_preference"].tri_state == "FALSE"                  # 31
    assert val(r, "technical_clarification_days") == {"value": 2.0, "unit": "DAYS"}
    assert val(r, "bid_end_datetime")["utc"] == "2026-10-16T15:30:00Z"
    assert val(r, "bid_opening_datetime")["local"] == "2026-10-17T21:00:00+05:30"


def test_relaxation_yes_complete(db):
    tables = replace_row(BASE_TABLES, "MSE Relaxation for Years of\nExperience and Turnover".split("\n")[-1], "x")
    tables = replace_row(BASE_TABLES, "Experience and Turnover", "Yes | Complete")
    r = fields_of(db, make_stage3a(db, tables=tables).id)
    assert r["mse_experience_turnover_relaxation"].tri_state == "TRUE"
    assert r["mse_experience_turnover_relaxation"].selected.details == {"qualifier": "Complete"}


def test_experience_and_turnover_amounts(db):
    t = [(1, 2, 400.0, [["Years of Past Experience Required for same/similar service", "3 Year (s)"],
                        ["Minimum Average Annual Turnover of the bidder (For 3 Years)", "20 Lakh (s)"],
                        ["OEM Average Turnover (Last 3 Years)", "100 Lakh (s)"]])]
    r = fields_of(db, make_stage3a(db, tables=BASE_TABLES + t).id)
    assert val(r, "experience_years") == {"value": 3.0, "unit": "YEARS"}       # 25
    assert r["experience_required"].tri_state == "TRUE"
    assert r["bidder_turnover_amount"].selected.number == 2_000_000             # 26
    assert r["bidder_turnover_required"].tri_state == "TRUE"
    assert r["oem_turnover_amount"].selected.number == 10_000_000               # 27
    assert r["oem_turnover_required"].tri_state == "TRUE"


def test_documents_required_and_oem_authorization(db):
    r = fields_of(db, make_stage3a(db).id)
    docs = val(r, "documents_required_from_seller")
    assert docs == ["Experience Criteria", "Past Performance", "Bidder Turnover", "Certificate (Requested in ATC)",
                    "OEM Authorization Certificate", "OEM Annual Turnover"]       # 36
    assert r["documents_required_from_seller"].selected.details["note"].startswith("*In case")
    assert r["oem_authorization_required"].tri_state == "TRUE"                  # 32
    assert r["oem_authorization_required"].candidates[0].rule == "derived_from_documents_required"
    assert r["experience_required"].tri_state == "TRUE" and r["oem_turnover_required"].tri_state == "TRUE"
    assert r["manufacturer_authorization_required"].status == "UNKNOWN"


def test_certificates_only_from_atc_and_explicit_sources(db):
    r = fields_of(db, make_stage3a(db).id)
    assert val(r, "certificate_requirements") == ["ISO 9001", "Certificate (Requested in ATC)"]  # 33
    assert "ISO 14001" not in json.dumps(val(r, "certificate_requirements"))  # only in GeM disclaimer text
    iso = [c for c in r["certificate_requirements"].candidates if c.rule == "atc_iso_certificate"][0]
    assert iso.section_heading == "certificates" and iso.page_number == 4


def test_warranty_from_atc_clause(db):
    r = fields_of(db, make_stage3a(db).id)
    assert val(r, "warranty_period") == {"value": 5.0, "unit": "YEARS"}       # 34
    assert r["warranty_period"].strength == "SECTION_CONTEXT"
    assert r["warranty_period"].candidates[0].section_heading == "warranty"
    assert r["warranty_required"].tri_state == "TRUE"


def test_delivery_and_consignee_table(db):
    r = fields_of(db, make_stage3a(db).id)
    assert val(r, "delivery_period") == {"value": 15.0, "unit": "DAYS"}      # 35
    assert val(r, "delivery_locations") == ["Jalpaiguri"]                      # masked prefix removed
    rec = val(r, "consignee_details")[0]
    assert (rec["sno"], rec["quantity"], rec["delivery_days"], rec["consignee"]) == (1, 2, 15, None)
    assert rec["address_raw"] == "***********Jalpaiguri"                      # raw kept
    assert val(r, "quantity_by_consignee") == [{"sno": 1, "consignee": None, "address": "Jalpaiguri", "quantity": 2}]


def test_delivery_days_varying_by_consignee_is_not_a_conflict(db):
    tables = [t for t in BASE_TABLES if t[0] != 4] + [(4, 1, 110.0, [
        ["S.No.", "Consignee", "Address", "Quantity", "Delivery Days"],
        ["1", "Officer A", "Delhi", "2", "15"], ["2", "Officer B", "Mumbai", "3", "30"]])]
    r = fields_of(db, make_stage3a(db, tables=tables).id)
    assert r["delivery_period"].status == "RESOLVED" and r["delivery_period"].selected.text == "VARIES"
    assert val(r, "delivery_locations") == ["Delhi", "Mumbai"]


def test_buyer_atc_presence_and_clauses(db):
    r = fields_of(db, make_stage3a(db).id)
    assert r["buyer_added_atc_present"].tri_state == "TRUE"                    # 37
    assert [c["title"] for c in val(r, "buyer_added_atc_clauses")] == ["1. Generic", "3. Warranty", "5. Certificates"]
    sections = [s for s in BASE_SECTIONS if "buyer added" not in s[3]]
    pages = {**BASE_PAGES, 4: BASE_PAGES[4].replace("/Buyer Added Bid Specific Terms and Conditions\n", "")}
    r2 = fields_of(db, make_stage3a(db, bid="GEM/2026/B/2", sections=sections, pages=pages).id)
    # The GeM disclaimer mentions "Buyer added ATC Clauses" generically - that is NOT evidence
    assert r2["buyer_added_atc_present"].status == "UNKNOWN"
    assert r2["warranty_period"].status == "UNKNOWN" and r2["certificate_requirements"].status == "RESOLVED"


# ===========================================================================
# 38-45. evidence, precedence, conflicts, no inference
# ===========================================================================
def test_evidence_page_table_raw_rule_and_type_are_persisted(db, fservice):
    e = make_stage3a(db)
    out = fservice.extract(e.id)
    ev = evidence_of(db, out.field_extraction_id, "past_performance_percentage")
    table_ev = ev[0]
    assert (table_ev.page_number, table_ev.table_index, table_ev.row_index) == (2, 1, 2)      # 38, 39
    assert table_ev.table_id is not None and table_ev.raw_value == "10 %"                      # 40
    assert (table_ev.evidence_type, table_ev.strength, table_ev.rule) == ("TABLE_CELL", "EXACT_TABLE",
                                                                         "table_label_alias")  # 41
    assert table_ev.source_label == "Past Performance" and table_ev.disposition == "SELECTED"
    assert json.loads(table_ev.normalized_json) == 10.0
    assert ev[1].rule == "past_performance_clause" and ev[1].disposition == "AGREES" and ev[1].page_number == 3
    assert table_ev.stage3a_extraction_id == e.id and table_ev.document_version_id == e.document_version_id
    v = values_of(db, out.field_extraction_id)["past_performance_percentage"]
    assert (v.status, v.value_text, v.value_number, v.unit, v.evidence_strength) == ("RESOLVED", "10", 10.0,
                                                                                     "PERCENT", "EXACT_TABLE")


def test_strong_table_evidence_beats_weaker_regex(db):
    pages = {**BASE_PAGES, 3: BASE_PAGES[3].replace("for 10% of bid quantity", "for 20% of bid quantity")}
    r = fields_of(db, make_stage3a(db, pages=pages).id)["past_performance_percentage"]
    assert r.status == "RESOLVED" and r.selected.value == 10.0                 # 42
    assert sorted(r.dispositions) == ["OVERRIDDEN", "SELECTED"]                # weaker text kept, not hidden
    overridden = r.candidates[r.dispositions.index("OVERRIDDEN")]
    assert overridden.strength == "REGEX_FALLBACK" and overridden.result.value == 20.0


def test_conflict_between_two_tables_keeps_both_sources(db):
    extra = [(5, 1, 100.0, [["Past Performance", "30 %"]])]
    r = fields_of(db, make_stage3a(db, tables=BASE_TABLES + extra).id)["past_performance_percentage"]
    assert r.status == "CONFLICT" and r.reason == "CONFLICTING_EVIDENCE" and r.selected is None      # 43
    conflicting = [c for c, d in zip(r.candidates, r.dispositions) if d == "CONFLICTING"]
    assert {(c.page_number, c.result.value) for c in conflicting} >= {(2, 10.0), (5, 30.0)}           # 44
    assert json.loads(r.value_json())["conflicting_values"]


def test_table_vs_atc_clause_is_a_conflict_not_silent_choice(db):
    tables = BASE_TABLES + [(3, 4, 720.0, [["Warranty of required product", "1 Year"]])]
    r = fields_of(db, make_stage3a(db, tables=tables).id)
    w = r["warranty_period"]
    assert w.status == "CONFLICT"
    assert {c.rule for c in w.candidates} == {"section_table_label_alias", "atc_warranty_clause"}
    assert r["warranty_required"].tri_state == "TRUE"   # both sources agree a warranty is required


def test_no_unsupported_inference(db):
    # Remove the documents list and every explicit fact: generic disclaimer text must not create facts
    tables = drop_rows(BASE_TABLES, "Document required\nfrom seller".split("\n")[-1])
    tables = drop_rows(tables, "from seller")
    r = fields_of(db, make_stage3a(db, tables=tables).id)
    for name in ("oem_authorization_required", "experience_required", "bidder_turnover_required",
                 "oem_turnover_required", "manufacturer_authorization_required", "experience_years",
                 "bidder_turnover_amount", "emd_amount", "emd_exemption_allowed"):
        assert r[name].status == "UNKNOWN", name                                # 45
    assert "ISO 14001" not in json.dumps(val(r, "certificate_requirements"))
    assert r["past_performance_required"].tri_state == "TRUE"  # explicit 10 % table row still counts


def test_bid_number_mismatch_is_strict_conflict():
    spec = BY_NAME["bid_number"]
    a = Candidate("bid_number", norm_text("GEM/2026/B/1"), "x", "METADATA", "SYSTEM_METADATA", "stage2_metadata")
    b = Candidate("bid_number", norm_text("GEM/2026/B/2"), "x", "PAGE_TEXT", "EXACT_LABEL", "document_bid_number")
    assert resolve(spec, [a, b]).status == "CONFLICT"
    assert resolve(BY_NAME["item_category"], [
        Candidate("item_category", norm_text("A"), "A", "TABLE_CELL", "EXACT_TABLE", "t"),
        Candidate("item_category", norm_text("B"), "B", "PAGE_TEXT", "EXACT_LABEL", "p")]).status == "RESOLVED"


def test_registry_is_consistent():
    assert len({f.name for f in FIELDS}) == len(FIELDS) >= 60
    for f in FIELDS:
        assert f.group and f.value_type
        for a in f.aliases:
            assert a.mode in ("exact", "prefix", "contains") and a.key


# ===========================================================================
# 46-49. idempotency, force/history, versions, not-ready
# ===========================================================================
def test_idempotent_and_force_keeps_history(db, fservice):
    e = make_stage3a(db)
    first = fservice.extract(e.id)
    fresh(db)
    counts = [db.scalar(select(func.count()).select_from(m)) for m in (TenderFieldExtraction, TenderFieldValue,
                                                                        TenderFieldEvidence)]
    again = fservice.extract(e.id)
    assert (first.outcome, again.outcome, again.field_extraction_id) == (EXTRACTED, ALREADY, first.field_extraction_id)
    fresh(db)
    assert [db.scalar(select(func.count()).select_from(m)) for m in (TenderFieldExtraction, TenderFieldValue,
                                                                      TenderFieldEvidence)] == counts   # 46
    forced = fservice.extract(e.id, force=True)
    fresh(db)
    old, new = db.get(TenderFieldExtraction, first.field_extraction_id), db.get(TenderFieldExtraction,
                                                                               forced.field_extraction_id)
    assert (old.is_current, new.is_current) == (False, True)                                         # 47
    assert len(values_of(db, old.id)) == len(values_of(db, new.id)) == len(FIELDS)


def test_db_allows_one_current_run_per_stage3a_extraction(db, fservice, session_factory):
    e = make_stage3a(db)
    fservice.extract(e.id)
    with session_factory() as s:
        s.add(TenderFieldExtraction(stage3a_extraction_id=e.id, document_version_id=e.document_version_id,
                                    document_id=e.document_id, tender_id=e.tender_id, bid_number="x",
                                    document_type="MAIN_BID", version_number=1, extractor_name="gem-fields",
                                    extractor_version=FIELD_EXTRACTOR_VERSION, status="SUCCESS", is_current=True))
        with pytest.raises(IntegrityError):
            s.commit()


def test_versions_are_kept_separate(db, fservice):
    e1 = make_stage3a(db)
    from app.database.models import TenderDocument
    doc = db.get(TenderDocument, e1.document_id)
    e2 = make_stage3a(db, tables=replace_row(BASE_TABLES, "Total Quantity", "5"), version_number=2, document=doc)
    o1, o2 = fservice.extract(e1.id), fservice.extract(e2.id)
    assert values_of(db, o1.field_extraction_id)["total_quantity"].value_text == "2"
    assert values_of(db, o2.field_extraction_id)["total_quantity"].value_text == "5"                  # 48
    assert values_of(db, o1.field_extraction_id)["document_version_number"].value_text == "1"


def test_stage3a_not_ready_is_never_faked(db, fservice, fworker):
    scanned = make_stage3a(db, status="OCR_REQUIRED", quality="OCR_REQUIRED")
    out = fservice.extract(scanned.id)
    assert (out.outcome, out.error_code) == (NOT_READY, "STAGE3A_NOT_USABLE")                          # 49
    assert enqueue_field_extraction(db, scanned.id, FieldJobReason.MANUAL).skipped_reason == "not_ready"
    old = make_stage3a(db, bid="GEM/2026/B/3", is_current=False)
    assert fservice.extract(old.id).error_code == "STAGE3A_SUPERSEDED"
    assert fservice.extract(999999).error_code == "STAGE3A_NOT_FOUND"
    fresh(db)
    assert db.scalar(select(func.count()).select_from(TenderFieldExtraction)) == 0
    # a job that became not-ready after queueing is SKIPPED, not SUCCESS
    db.add(FieldExtractionJob(stage3a_extraction_id=scanned.id, status="PENDING", reason="MANUAL"))
    db.commit()
    j = fworker.run_batch().jobs[0]
    assert (j.status, j.error_code) == ("SKIPPED", "STAGE3A_NOT_USABLE")


# ===========================================================================
# 50-53. Stage 3A hook, queue failure, backfill
# ===========================================================================
def test_stage3a_to_stage3b_hook_end_to_end_from_pdf(db, fsettings, session_factory):
    """Real path: generated PDF -> Stage 3A service -> hook queues Stage 3B -> worker extracts fields."""
    from app.extraction.service import ExtractionService
    from tests.test_stage3a_extraction import store_version
    from tests.pdf_factory import gem_like_pdf

    v = store_version(db, fsettings, gem_like_pdf())
    out3a = ExtractionService(fsettings, session_factory, use_default_ocr=False).extract_version(v.id)
    fresh(db)
    jobs = db.scalars(select(FieldExtractionJob)).all()
    assert [(j.stage3a_extraction_id, j.reason, j.status) for j in jobs] == [
        (out3a.extraction_id, "STAGE3A_COMPLETED", "PENDING")]                                           # 50
    batch = FieldExtractionJobWorker(fsettings, session_factory).run_batch()
    assert batch.jobs[0].status in ("SUCCESS", "PARTIAL_SUCCESS")
    vals = values_of(db, batch.jobs[0].field_extraction_id)
    assert vals["emd_amount"].value_number == 25000 and vals["emd_amount"].unit == "INR"   # "Rs. 25,000"
    assert vals["total_quantity"].status == "UNKNOWN"  # fixture PDF has no Total Quantity -> not invented
    path = fsettings.resolved_document_storage_path / v.storage_path
    assert hashlib.sha256(path.read_bytes()).hexdigest() == v.sha256                                  # 65


def test_queue_failure_never_rolls_back_stage3a(db, fsettings, session_factory, monkeypatch, caplog):
    from app.extraction.service import ExtractionService
    from app.services.field_status import field_extraction_status
    from tests.pdf_factory import gem_like_pdf
    from tests.test_stage3a_extraction import store_version

    def boom(*a, **k):
        raise RuntimeError("stage 3b queue down")

    monkeypatch.setattr(fq, "enqueue_field_extraction", boom)
    caplog.set_level("ERROR")
    v = store_version(db, fsettings, gem_like_pdf())
    out = ExtractionService(fsettings, session_factory, use_default_ocr=False).extract_version(v.id)
    assert out.status == "SUCCESS"
    fresh(db)
    assert db.get(DocumentExtraction, out.extraction_id).status == "SUCCESS"                          # 51
    assert db.scalar(select(func.count()).select_from(FieldExtractionJob)) == 0
    assert any("field_extraction_job_queue_failed" in r.getMessage() for r in caplog.records)
    assert field_extraction_status(db)["stage3a_extractions_unqueued"] == 1
    monkeypatch.undo()
    assert backfill_field_jobs(db, limit=5) == [out.extraction_id]                                    # recoverable


def test_backfill_limit_and_dry_run(db):
    ids = [make_stage3a(db, bid=f"GEM/2026/B/70000{i}").id for i in range(4)]
    make_stage3a(db, bid="GEM/2026/B/7999999", status="OCR_REQUIRED")          # never a candidate
    assert backfill_field_jobs(db, limit=2, dry_run=True) == [ids[3], ids[2]]                       # 53
    db.rollback()
    fresh(db)
    assert db.scalar(select(func.count()).select_from(FieldExtractionJob)) == 0
    first = backfill_field_jobs(db, limit=2)
    db.commit()
    second = backfill_field_jobs(db, limit=5)
    db.commit()
    assert first == [ids[3], ids[2]] and second == [ids[1], ids[0]]                                   # 52
    assert backfill_field_jobs(db, limit=5) == []


# ===========================================================================
# 54-56. worker lifecycle, retry/recovery, race safety
# ===========================================================================
def test_worker_lifecycle_and_atomic_finish(db, session_factory, fworker, fservice):
    e = make_stage3a(db)
    res = enqueue_field_extraction(db, e.id, FieldJobReason.MANUAL)
    db.commit()
    seen = {}
    original = fservice.prepare

    def spy(stage3a_id, force=False):
        with session_factory() as other:
            row = other.get(FieldExtractionJob, res.job_id)
            seen.update(status=row.status, locked_by=row.locked_by)
            other.execute(text("PRAGMA busy_timeout=200"))
            other.execute(text("UPDATE tenders SET title='write during rules' WHERE id=:i"), {"i": e.tender_id})
            other.commit()   # no SQLite write lock held while rules run
        return original(stage3a_id, force)

    fservice.prepare = spy
    j = fworker.run_batch().jobs[0]
    assert seen == {"status": "RUNNING", "locked_by": fworker.worker_id}                              # 54
    fresh(db)
    job = db.get(FieldExtractionJob, res.job_id)
    assert (j.status, job.status, job.locked_by, job.field_extraction_id) == ("SUCCESS", "SUCCESS", None,
                                                                              j.field_extraction_id)
    assert fworker.run_batch().processed == 0


def test_engine_exception_retries_then_fails(db, fworker, fservice, clock):
    e = make_stage3a(db)
    res = enqueue_field_extraction(db, e.id, FieldJobReason.MANUAL)
    db.commit()

    def boom(*a, **k):
        raise RuntimeError("rule bug")

    fservice.prepare = boom
    fworker.run_batch()
    fresh(db)
    job = db.get(FieldExtractionJob, res.job_id)
    assert (job.status, job.error_code) == ("RETRY", "ENGINE_ERROR") and job.next_retry_at == clock.now + timedelta(minutes=5)
    assert fworker.run_batch().processed == 0                     # next_retry_at respected
    clock.advance(minutes=6)
    fworker.run_batch()
    clock.advance(minutes=11)
    fworker.run_batch()
    fresh(db)
    assert db.get(FieldExtractionJob, res.job_id).status == "FAILED"                                  # 55


def test_stale_running_job_recovered_and_live_one_untouched(db, session_factory, fworker, clock):
    a = make_stage3a(db, bid="GEM/2026/B/1000001")
    b = make_stage3a(db, bid="GEM/2026/B/1000002")
    with session_factory() as s:
        s.add_all([FieldExtractionJob(id=40, stage3a_extraction_id=a.id, status="RUNNING", attempt_count=1,
                                      started_at=clock.now, locked_by=f"{socket.gethostname()}:1:dead"),
                   FieldExtractionJob(id=41, stage3a_extraction_id=b.id, status="RUNNING", attempt_count=1,
                                      started_at=clock.now, locked_by="other-host:2:live")])
        s.commit()
    batch = fworker.run_batch(max_jobs=5)
    fresh(db)
    assert batch.recovered_stale == 1 and db.get(FieldExtractionJob, 40).status == "SUCCESS"
    assert db.get(FieldExtractionJob, 41).status == "RUNNING"


def test_sqlite_race_safety(db, session_factory, fsettings, fservice, clock):
    ids = [make_stage3a(db, bid=f"GEM/2026/B/60000{i}").id for i in range(4)]
    for i in ids:
        enqueue_field_extraction(db, i, FieldJobReason.MANUAL)
    db.commit()
    with session_factory() as s:   # one queued job per Stage 3A extraction (DB-enforced)
        s.add(FieldExtractionJob(stage3a_extraction_id=ids[0], status="RETRY"))
        with pytest.raises(IntegrityError):
            s.commit()
    workers = [FieldExtractionJobWorker(fsettings, session_factory, fservice, clock=clock) for _ in range(3)]
    with workers[0].lock.acquire():
        assert workers[1].run_batch().skipped_reason == SKIP_BUSY
    threads = [threading.Thread(target=w.run_batch, kwargs={"max_jobs": 4}) for w in workers]
    for t in threads:
        t.start()
    for t in threads:
        t.join(60)
    fresh(db)
    assert db.scalar(select(func.count()).select_from(TenderFieldExtraction)) == 4                    # 56
    assert all(j.status == "SUCCESS" and j.attempt_count == 1 for j in db.scalars(select(FieldExtractionJob)))


# ===========================================================================
# 57-63. API, health, stats, scheduler
# ===========================================================================
@pytest.fixture
def api(settings, session_factory, source):
    from fastapi.testclient import TestClient

    from app.main import create_app

    with TestClient(create_app(settings, session_factory=session_factory, collector_factory=source)) as c:
        yield c


def test_static_routes_are_not_swallowed(authorized_fields_api, db):
    api = authorized_fields_api
    paths = [p for p, ops in api.app.openapi()["paths"].items() if "{" not in p and "get" in ops]
    assert {"/api/tender-fields", "/api/tender-fields/jobs", "/api/tender-fields/worker"} <= set(paths)
    for p in paths:
        r = api.get(p)
        if r.status_code == 422:
            assert "path" not in [e.get("loc", [None])[0] for e in r.json().get("detail", [])], p     # 57
    make_stage3a(db)
    assert api.get("/api/tender-fields/bid/GEM/2026/B/8124821").status_code == 200
    assert api.get("/api/tender-fields/jobs", params={"page": 1}).status_code == 200
    assert api.get("/api/tender-fields/not-a-number").status_code == 422



@pytest.fixture
def authorized_fields_api(api, session_factory):
    """Authorized tender-fields operator in the temporary test database."""
    from uuid import uuid4
    from app.api.auth import get_current_user
    from app.core.supabase_auth import AuthenticatedIdentity
    from app.database.auth_models import AppUser
    from app.database.platform_auth_models import PlatformOperatorGrant

    subject = str(uuid4())

    with session_factory() as db:
        user = AppUser(supabase_user_id=subject)
        db.add(user)
        db.flush()

        db.add(
            PlatformOperatorGrant(
                user_id=user.id,
                granted_by_user_id=user.id,
                permission="TENDER_FIELDS_MANAGE",
                status="ACTIVE",
            )
        )
        db.add(PlatformOperatorGrant(user_id=user.id, granted_by_user_id=user.id, permission="TENDER_ANALYSIS_READ", status="ACTIVE"))
        db.commit()

    identity = AuthenticatedIdentity(
        subject=subject,
        email="stage3b-test@example.com",
        claims={"sub": subject, "role": "authenticated"},
    )

    api.app.dependency_overrides[get_current_user] = lambda: identity

    try:
        yield api
    finally:
        api.app.dependency_overrides.pop(get_current_user, None)


def test_api_list_detail_values_evidence_conflicts_and_filters(authorized_fields_api, db, fsettings, session_factory):
    e1 = make_stage3a(db)
    e2 = make_stage3a(db, bid="GEM/2026/B/5000002",
                      tables=replace_row(BASE_TABLES + [(5, 1, 100.0, [["Past Performance", "30 %"]])],
                                         "MSE Relaxation for Years of Experience and Turnover", "Yes | Complete"))
    q1 = authorized_fields_api.post(f"/api/tender-fields/extraction/{e1.id}/queue").json()
    q2 = authorized_fields_api.post(f"/api/tender-fields/extraction/{e1.id}/queue").json()
    assert q1["queued"] is True and q2["reason"] == "already_queued" and q2["job_id"] == q1["job_id"]
    svc = FieldExtractionService(fsettings, session_factory)
    r1, r2 = svc.extract(e1.id), svc.extract(e2.id)

    lst = authorized_fields_api.get("/api/tender-fields", params={"page": 1, "page_size": 20}).json()
    assert lst["total"] == 2                                                                         # 58
    d = authorized_fields_api.get(f"/api/tender-fields/{r1.field_extraction_id}").json()
    assert d["source"]["bid_number"] == "GEM/2026/B/8124821" and d["source"]["stage3a_extraction_id"] == e1.id
    assert d["fields"]["emd_required"] == {"status": "RESOLVED", "value_text": "FALSE", "tri_state": "FALSE",
                                           "unit": None, "reason": None, "strength": "SECTION_TABLE"}
    vals = authorized_fields_api.get(f"/api/tender-fields/{r1.field_extraction_id}/values", params={"group": "DATES"}).json()
    assert {v["field_name"] for v in vals["items"]} == {"bid_end_datetime", "bid_opening_datetime",
                                                        "bid_offer_validity_days", "contract_period"}   # 59
    ev = authorized_fields_api.get(f"/api/tender-fields/{r1.field_extraction_id}/evidence",
                 params={"field_name": "total_quantity"}).json()["items"]
    assert ev[0]["page_number"] == 1 and ev[0]["table_index"] == 1 and ev[0]["raw_value"] == "2"
    conf = authorized_fields_api.get(f"/api/tender-fields/{r2.field_extraction_id}/conflicts").json()["items"]
    assert [c["field_name"] for c in conf] == ["past_performance_percentage"] and len(conf[0]["evidence"]) >= 2
    assert authorized_fields_api.get(f"/api/tender-fields/{r1.field_extraction_id}/conflicts").json()["items"] == []

    def total(**params):
        return authorized_fields_api.get("/api/tender-fields", params=params).json()["total"]
    assert total(mse_relaxation="TRUE") == 1 and total(mse_relaxation="FALSE") == 1                  # 60
    assert total(emd_required="FALSE") == 2 and total(emd_required="TRUE") == 0
    assert total(startup_relaxation="FALSE") == 2 and total(inspection_required="FALSE") == 2
    assert total(oem_authorization_required="TRUE") == 2
    assert total(item_category="paintball") == 2 and total(bid_type="two packet bid") == 2
    assert total(bid_number="GEM/2026/B/5000002") == 1
    assert total(field="past_performance_percentage", value="10") == 1
    assert authorized_fields_api.get("/api/tender-fields", params={"emd_required": "MAYBE"}).status_code == 422
    by_bid = authorized_fields_api.get("/api/tender-fields/bid/GEM/2026/B/8124821").json()
    assert by_bid["items"][0]["is_latest_version"] is True and "not merged" in by_bid["precedence"]
    by3a = authorized_fields_api.get(f"/api/tender-fields/extraction/{e1.id}").json()
    assert by3a["current"]["id"] == r1.field_extraction_id
    re = authorized_fields_api.post(f"/api/tender-fields/extraction/{e1.id}/reextract").json()
    assert re["force"] is True and re["job_id"] == q1["job_id"]
    assert authorized_fields_api.get(f"/api/tender-fields/jobs/{q1['job_id']}").json()["force"] is True
    assert authorized_fields_api.post("/api/tender-fields/extraction/999999/queue").status_code == 404


def test_health_and_stats_metrics(api, db, fsettings, session_factory):
    e1 = make_stage3a(db)
    make_stage3a(db, bid="GEM/2026/B/5000003")
    make_stage3a(db, bid="GEM/2026/B/5000004", status="OCR_REQUIRED")
    FieldExtractionService(fsettings, session_factory).extract(e1.id)
    from tests.conftest import sign_in
    sign_in(api.app)
    s = api.get("/api/stats").json()
    api.app.dependency_overrides.clear()
    assert s["stage3a_extractions_eligible_for_fields"] == 2 and s["field_extractions_total"] == 1  # 62
    assert s["stage3a_extractions_unqueued_for_fields"] == 1 and s["fields_conflicted"] == 0
    assert s["fields_extracted"] + s["fields_unknown"] == len(FIELDS)
    assert s["total_tenders"] == 3 and "extraction" in s and "document_worker" in s   # old contract intact
    h = api.get("/health").json()
    fw = h["field_extraction_worker"]
    assert h["status"] == "healthy" and fw["field_extraction_worker_enabled"] is False                # 61
    assert fw["stage3a_extractions_unqueued"] == 1 and fw["field_extraction_scheduler_running"] is False
    assert "extraction_worker" in h and "document_worker" in h


def test_scheduler_disabled_by_default(settings, session_factory, source):
    from fastapi.testclient import TestClient

    from app.main import create_app
    from app.scheduler.scheduler import FIELD_EXTRACTION_WORKER_JOB_ID

    assert Settings(_env_file=None).field_extraction_worker_enabled is False                            # 63
    base = {"scheduler_enabled": True, "collect_on_startup": False}
    app = create_app(settings.model_copy(update=base), session_factory=session_factory, collector_factory=source)
    with TestClient(app):
        assert app.state.scheduler._scheduler.get_job(FIELD_EXTRACTION_WORKER_JOB_ID) is None
    on = settings.model_copy(update={**base, "field_extraction_worker_enabled": True,
                                     "field_extraction_job_poll_seconds": 40})
    app = create_app(on, session_factory=session_factory, collector_factory=source)
    with TestClient(app) as c:
        j = app.state.scheduler._scheduler.get_job(FIELD_EXTRACTION_WORKER_JOB_ID)
        assert j.trigger.interval.total_seconds() == 40 and j.max_instances == 1
        assert c.get("/health").json()["field_extraction_worker"]["field_extraction_scheduler_running"] is True


# ===========================================================================
# 64-67. immutability, no network, no LLM
# ===========================================================================
def test_stage3a_rows_are_not_modified(db, fservice):
    e = make_stage3a(db)
    before = stage3a_digest(db, e.id)
    fservice.extract(e.id)
    fservice.extract(e.id, force=True)
    assert stage3a_digest(db, e.id) == before                                                          # 64


def test_no_network_and_no_file_access_needed(db, fservice, monkeypatch, fsettings):
    e = make_stage3a(db)   # its storage_path points to a file that does not exist at all

    def no_network(*a, **k):
        raise AssertionError("Stage 3B attempted network access")

    monkeypatch.setattr(socket.socket, "connect", no_network)
    monkeypatch.setattr(socket, "create_connection", no_network)
    out = fservice.extract(e.id)
    assert out.outcome == EXTRACTED and out.fields_resolved > 30                                        # 66
    assert not (fsettings.resolved_document_storage_path / "x").exists()                               # 65


def test_no_llm_or_pdf_dependency_in_stage3b():
    allowed_import_roots = {"__future__", "app", "collections", "dataclasses", "datetime", "decimal", "enum",
                            "json", "logging", "math", "os", "re", "socket", "sqlalchemy", "threading", "time",
                            "uuid", "zoneinfo"}
    for path in (PROJECT_ROOT / "app" / "fields").glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else (
                [node.module or ""] if isinstance(node, ast.ImportFrom) else [])
            for n in names:
                assert n.split(".")[0] in allowed_import_roots, f"{path.name} imports unapproved dependency {n}"  # 67
    approved_requirements = {"fastapi", "uvicorn", "sqlalchemy", "alembic", "pydantic", "pydantic-settings",
                             "python-dotenv", "httpx", "pyjwt", "beautifulsoup4", "apscheduler", "filelock",
                             "python-multipart", "tzdata", "pdfplumber", "reportlab", "pytest", "pytest-asyncio"}
    declared = set()
    for raw in (PROJECT_ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines():
        item = raw.split("#", 1)[0].strip().lower()
        if not item:
            continue
        for separator in (";", "[", "<", ">", "=", "!", "~"):
            item = item.split(separator, 1)[0]
        declared.add(item)
    assert declared <= approved_requirements, f"unapproved Python requirements: {sorted(declared - approved_requirements)}"
