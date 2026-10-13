"""Additional product validation gaps, all offline and disposable."""
import pytest
from app.fields.turnover import turnover_amount
from tests.test_stage3b_fields import fields_of
from tests.stage3a_rows import make_stage3a
from tests.matching_factories import make_tender
from app.corpus.service import build_corpus
from app.eligibility.service import EligibilityService
from app.database.models import TenderFieldExtraction, TenderFieldValue
from sqlalchemy import select


@pytest.mark.parametrize("text", [
    "Turnover: up to INR 7 lakh", "Turnover (In Lakhs): INR 7 crore",
    "Turnover: GBP 7 lakh", "Turnover: £7 lakh", "Turnover: €7 lakh",
    "Turnover: " + "9" * 400 + " lakh",
    "The minimum average annual financial turnover of the bidder during the last three financial years, ending on 31st March of the previous financial year, should be as indicated in the bid document.",
    "Turnover requirement ending on 31 March is specified in the bid document.",
    "Turnover for 3 years is required.",
    "Turnover growth of 20% is required.",
])
def test_ambiguous_or_unsupported_threshold_is_not_compared(text):
    assert turnover_amount(text) is None


@pytest.mark.parametrize("value,expected", [
    ("at least INR 7 lakh", 700000), ("INR 1.5 crore", 15000000),
    ("INR 700 thousand", 700000), ("INR 700,000", 700000),
])
def test_unambiguous_lower_thresholds(value, expected):
    assert turnover_amount("Turnover: " + value).number == expected


def test_ai_turnover_date_quote_does_not_ground_model_amount():
    import json
    from app.ai.chunker import Chunk
    from app.ai.grounding import ground
    from app.ai.schema import parse_envelope
    quote = ("The minimum average annual financial turnover of the bidder during the last three "
             "financial years, ending on 31st March of the previous financial year, "
             "should be as indicated in the bid document.")
    chunk = Chunk("C1", 1, "CLAUSE_TEXT", "SECTION_TEXT", 1, 1, quote)
    envelope = parse_envelope(json.dumps({"summary": "Tender", "requirements": [{
        "requirement_type": "TURNOVER", "title": "Annual turnover", "obligation_level": "MANDATORY",
        "value": 410000, "unit": "INR", "evidence": [{"chunk_id": "C1", "quote": quote}],
    }]}))
    requirement = ground(envelope, [chunk]).requirements[0]
    assert requirement.value_number is None and requirement.unit is None
    assert requirement.ambiguity


@pytest.mark.parametrize("entity", ["MSE", "Startup"])
def test_ra_exemption_label_supported(db, entity):
    extraction = make_stage3a(db, tables=[(1, 1, 100., [[
        f"{entity} Exemption for Years Of Experience and Turnover", "Yes | Complete"
    ]])])
    fields = fields_of(db, extraction.id)
    assert fields[f"{entity.lower()}_experience_turnover_relaxation"].tri_state == "TRUE"


def test_turnover_unit_only_in_table_header(db):
    extraction = make_stage3a(db, tables=[(1, 1, 100., [
        ["Parameter", "Value (INR Lakhs)"],
        ["Minimum Average Annual Turnover of the bidder (For 3 Years)", "7"],
    ])])
    value = fields_of(db, extraction.id)["bidder_turnover_amount"].selected
    assert value.number == 700000 and value.unit == "INR"


@pytest.mark.parametrize("entity", ["mse", "startup"])
def test_combined_relaxation_enters_eligibility(db, entity):
    tender = make_tender(db, bid="GEM/2026/B/9600001", fields={})
    extraction = db.scalar(select(TenderFieldExtraction).where(TenderFieldExtraction.tender_id == tender.id))
    for name, tri, number in [
        (f"{entity}_experience_turnover_relaxation", "TRUE", None),
        ("bidder_turnover_amount", None, 700000),
        ("experience_required", "TRUE", 3),
    ]:
        db.add(TenderFieldValue(field_extraction_id=extraction.id, tender_id=tender.id,
            field_name=name, field_group="PERFORMANCE", value_type="BOOL" if tri else "MONEY",
            status="RESOLVED", tri_state=tri, value_number=number))
    db.commit()
    requirements, _ = EligibilityService(db)._extract_tender_requirements(tender.id, build_corpus(db, tender.id))
    assert len(requirements) == 2
    assert all(r[f"{entity}_relaxation"] is True for r in requirements)


def test_resolved_experience_duration_enters_eligibility(db):
    tender = make_tender(db, bid="GEM/2026/B/9600002", fields={})
    extraction = db.scalar(select(TenderFieldExtraction).where(TenderFieldExtraction.tender_id == tender.id))
    for name, tri, number in [("experience_required", "TRUE", None), ("experience_years", None, 3)]:
        db.add(TenderFieldValue(field_extraction_id=extraction.id, tender_id=tender.id, field_name=name,
            field_group="PERFORMANCE", value_type="BOOL" if tri else "DURATION", status="RESOLVED",
            tri_state=tri, value_number=number, unit="YEARS" if number else None))
    db.commit()
    requirements, _ = EligibilityService(db)._extract_tender_requirements(tender.id, build_corpus(db, tender.id))
    assert len(requirements) == 1 and requirements[0]["value_number"] == 3


@pytest.mark.parametrize("kind", ["EXPERIENCE", "TURNOVER", "OEM_AUTHORIZATION"])
def test_explicitly_false_requirement_is_not_a_gate(kind):
    from app.eligibility.engine import EligibilityEngine
    result = EligibilityEngine().evaluate_requirement({"type": kind, "value_boolean": False}, {"attributes": []})
    assert result["status"] == "NOT_APPLICABLE"


@pytest.mark.parametrize("kind", ["EXPERIENCE", "TURNOVER"])
def test_conflicting_exemption_is_review_before_rejection(kind):
    from app.eligibility.engine import EligibilityEngine
    key = "years_of_experience" if kind == "EXPERIENCE" else "annual_turnover"
    result = EligibilityEngine().evaluate_requirement(
        {"type": kind, "value_number": 700000, "relaxation_conflict": True},
        {"attributes": [{"key": key, "value_type": "NUMBER", "value_number": 1}]})
    assert result["status"] == "REVIEW_REQUIRED"


def test_gem_uploaded_quality_plan_is_authoritative_supporting_document():
    from app.documents.references import classify_reference
    url = "https://bidplus.gem.gov.in/resources/upload_nas/AugQ326/bidding/biddoc/bid-9723394/1786085135.pdf"
    assert classify_reference(url, "1786085135.pdf", "Quality Assurance Plan document") == (
        "TENDER_DOCUMENT", "TECHNICAL_DOCUMENT", True)
    assert not classify_reference(url, "1786085135.pdf", "See unrelated comparison")[2]
    assert not classify_reference(url.replace("bidplus.gem.gov.in", "example.com"),
                                  "1786085135.pdf", "Quality Assurance Plan document")[2]
