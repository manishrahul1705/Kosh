"""Offline RA -> authoritative main bid -> corpus -> AI -> seller -> portal."""

import json
from datetime import timedelta
import httpx
import pytest
from sqlalchemy import select, func
from app.database.models import (
    Tender, TenderDocument, DocumentVersion, DocumentReference, ExtractionJob,
    AIAnalysisRun, AIRequirement, AIRequirementEvidence, AIEvidenceChunk,
    TenderFieldExtraction, TenderFieldValue, DocumentExtraction,
)
from app.documents.references import classify_reference, ReferenceDiscovery
from app.documents.documents_service import DocumentsService
from app.corpus.service import build_corpus
from app.corpus.queue import enqueue_corpus
from app.corpus.analysis import prepare_corpus
from app.ai.service import AnalysisService
from app.ai.providers.mock import MockProvider
from app.ai.grounding import ground
from app.ai.schema import parse_envelope
from app.ai.chunker import Chunk
from app.fields.turnover import turnover_amount
from app.matching.service import MatchingService
from app.database.matching_models import SellerTenderMatch
from app.services.status_service import apply_current_status
from app.api.portal import _analysis
from app.utils.dates import utcnow
from tests.pdf_factory import PdfBuilder, text_pdf
from tests.test_corpus import seed, public_dns, extract_all, source_pdf, SPEC
from tests.matching_factories import make_seller, make_tender

URL = "https://bidplus.gem.gov.in/showbidDocument/9723394"
CONTEXT = "Please refer to Bid document of GEM/2026/B/7889130 for technical specification, terms & conditions and other details."


@pytest.mark.parametrize("anchor", ["GEM/2026/B/7889130", "Download"])
def test_authoritative_main_bid_classification(anchor):
    assert classify_reference(URL, anchor, CONTEXT) == ("TENDER_DOCUMENT", "MAIN_BID", True)


@pytest.mark.parametrize("url,context", [
    (URL, "GEM/2026/B/7889130 is mentioned for comparison"),
    (URL, "Unrelated GEM/2026/B/7889130 technical specification for comparison"),
    (URL.replace("bidplus.gem.gov.in", "example.com"), CONTEXT),
    (URL.replace("showbidDocument", "showradocumentPdf"), CONTEXT),
    (URL + "/evil", CONTEXT),
    (URL, "Please refer to technical specification GEM/2026/R/748499"),
])
def test_unrelated_main_bid_not_included(url, context):
    assert not classify_reference(url, "", context)[2]


@pytest.mark.parametrize("raw", ["7 Lakhs", "7 Lakh", "₹7 lakh", "INR 7 lakh", "7,00,000", "0.07 crore"])
def test_turnover_units_from_evidence(raw):
    quote = f"The bidder must have minimum annual turnover: {raw}"
    assert turnover_amount(quote).number == 700000
    chunk = Chunk("C1", 1, "CLAUSE_TEXT", "SECTION_TEXT", 1, 1, quote)
    env = parse_envelope(json.dumps({"summary": "Tender", "requirements": [{
        "requirement_type": "TURNOVER", "title": "Turnover", "obligation_level": "MANDATORY",
        "value": 7, "unit": "INR", "evidence": [{"chunk_id": "C1", "quote": quote}],
    }]}))
    req = ground(env, [chunk]).requirements[0]
    assert req.value_number == 700000


def test_label_unit_and_stage3b(db):
    from tests.stage3a_rows import make_stage3a
    from tests.test_stage3b_fields import fields_of
    ext = make_stage3a(db, tables=[(1, 1, 100.0, [[
        "Minimum Average Annual Turnover of the bidder (For 3 Years) (In Lakhs) INR", "7"
    ]])])
    value = fields_of(db, ext.id)["bidder_turnover_amount"].selected
    assert value.number == 700000 and value.unit == "INR"


@pytest.mark.parametrize("raw", ["7-10 lakh", "7 lakh or 10 lakh", "-7 lakh", "USD 7 lakh", "not specified", "7 lakh crore"])
def test_ambiguous_turnover_has_no_threshold(raw):
    assert turnover_amount("Turnover: " + raw) is None


@pytest.mark.parametrize("source_kind", ["R", "B"])
def test_ra_main_bid_package_end_to_end(db, settings, session_factory, tmp_path, source_kind):
    b = PdfBuilder()
    p = b.page()
    p.text(40, 40, f"Bid Number: GEM/2026/{source_kind}/748499")
    p.text(40, 65, "Please refer to Bid document of GEM/2026/B/7889130")
    p.text(40, 82, "for technical specification, terms & conditions and other details.")
    p.link(URL, top=65)
    cfg, tender, version = seed(db, tmp_path, settings, b.build())
    tender.bid_number = f"GEM/2026/{source_kind}/748499"
    tender.title = tender.category = "Fixed Computer Workstation"
    tender.status = "ONGOING"
    tender.bid_end_at = utcnow() + timedelta(days=7)
    apply_current_status(db, tender, now=utcnow())
    db.commit()
    calls = []
    def handler(request):
        calls.append(str(request.url))
        content = source_pdf((SPEC,)) if str(request.url) == URL else text_pdf(
            [["The bidder must have minimum annual turnover: INR 7 lakh."]]
        )
        return httpx.Response(200, content=content, headers={"content-type": "application/pdf"})
    discovery = ReferenceDiscovery(DocumentsService(cfg, transport=httpx.MockTransport(handler), sleep=lambda _: None), resolver=public_dns)
    # Reproduce an already excluded reference; refresh repairs rather than duplicates it.
    discovery.run(db, tender, acquire=False)
    ref = db.scalar(select(DocumentReference))
    ref.category, ref.document_type, ref.corpus_relevant = "UNKNOWN_REFERENCE", "UNKNOWN", False
    ref.status, ref.reason = "EXCLUDED", "UNKNOWN_REFERENCE"
    db.commit()
    old_id = ref.id
    before = build_corpus(db, tender.id)["fingerprint"]
    discovery.run(db, tender)
    assert ref.id == old_id and ref.status == "ACQUIRED" and ref.corpus_relevant
    assert db.get(TenderDocument, ref.target_document_id).document_type == "MAIN_BID"
    assert db.scalar(select(ExtractionJob.id).where(ExtractionJob.document_version_id == ref.target_version_id))
    assert db.scalar(select(func.count()).select_from(Tender)) == 1
    assert calls == [URL, SPEC]
    discovery.run(db, tender)
    assert calls == [URL, SPEC]
    assert db.scalar(select(func.count()).select_from(TenderDocument)) == 3
    extract_all(db, cfg, session_factory, tender.id)
    corpus = build_corpus(db, tender.id)
    assert corpus["complete"] and len(corpus["documents"]) == 3
    assert corpus["fingerprint"] != before
    job = enqueue_corpus(db, tender.id, cfg)
    assert job.created
    db.commit()
    ai = AnalysisService(cfg, session_factory, provider_factory=lambda: MockProvider())
    prepared = prepare_corpus(ai, tender.id)
    assert len(prepared.sources) == 3
    call = ai.call(prepared)
    interpreted = ai.interpret(prepared, call.response)
    with session_factory() as session:
        run_id = ai.persist(session, prepared, call, interpreted)
        session.commit()
    db.expire_all()
    assert db.get(AIAnalysisRun, run_id).analysis_scope == "TENDER_CORPUS"
    assert len(set(db.scalars(select(AIEvidenceChunk.document_version_id).where(AIEvidenceChunk.analysis_run_id == run_id)))) == 3
    seller = make_seller(db, name="Workstation seller", terms="Workstation", turnover=800000)
    stats = MatchingService(db).recalculate(now=utcnow(), tender_ids=[tender.id], seller_ids=[seller.id])
    assert stats.evaluated == 1 and stats.errors == 0
    match = db.scalar(select(SellerTenderMatch).where(SellerTenderMatch.tender_id == tender.id))
    assert match is not None
    output = _analysis(db, tender.id, {})
    assert output["summary"] and output["sections"]["eligibility"]
    assert all(r["evidence"] for rows in output["sections"].values() for r in rows)
    # Losing reference coverage invalidates matching even without new row IDs.
    fingerprint = match.tender_state_fingerprint
    ref.status = "DOWNLOAD_FAILED"
    db.commit()
    changed = MatchingService(db).recalculate(now=utcnow(), tender_ids=[tender.id], seller_ids=[seller.id])
    assert changed.evaluated == 1 and changed.errors == 0
    assert match.tender_state_fingerprint != fingerprint
    assert match.match_status == "REVIEW_REQUIRED"
    assert _analysis(db, tender.id, {})["analysis_status"] == "STALE"
    updated_job = enqueue_corpus(db, tender.id, cfg)
    assert updated_job.created and updated_job.job_id != job.job_id


@pytest.mark.parametrize("quote,expected", [
    ("The bidder must have minimum annual turnover: INR 7 lakh.", 700000),
    ("The bidder must have minimum annual turnover: 7 lakh or 10 lakh.", None),
    ("The bidder turnover during the last three financial years, ending on 31st March, should be as indicated in the bid document.", None),
])
def test_historical_ai_turnover_cannot_compare_seven_rupees(db, quote, expected):
    from app.eligibility.service import EligibilityService
    tender = make_tender(db, bid="GEM/2026/B/800001", fields={})
    fx = db.scalar(select(TenderFieldExtraction).where(TenderFieldExtraction.tender_id == tender.id))
    run = AIAnalysisRun(
        tender_id=tender.id, stage3b_extraction_id=fx.id, stage3a_extraction_id=fx.stage3a_extraction_id,
        document_id=fx.document_id, document_version_id=fx.document_version_id,
        bid_number=tender.bid_number, document_type="MAIN_BID", version_number=1,
        analyzer_name="test", provider="mock", model="mock", prompt_version="old",
        schema_version="old", chunker_version="old", analysis_scope="TENDER_CORPUS", status="SUCCESS",
    )
    db.add(run)
    db.flush()
    req = AIRequirement(analysis_run_id=run.id, tender_id=tender.id, sequence=1, requirement_type="TURNOVER", category="ELIGIBILITY",
                        title="Turnover", obligation_level="MANDATORY", applies_to="BIDDER",
                        value_text="7", value_number=7, unit="INR")
    chunk = AIEvidenceChunk(analysis_run_id=run.id, chunk_key="C1", sequence=1, kind="CLAUSE_TEXT",
                           source_type="SECTION_TEXT", stage3a_extraction_id=fx.stage3a_extraction_id,
                           document_version_id=fx.document_version_id, page_number=1, page_end=1,
                           text=quote, char_count=len(quote), text_sha256="0" * 64)
    db.add_all([req, chunk])
    db.flush()
    db.add(AIRequirementEvidence(requirement_id=req.id, analysis_run_id=run.id, chunk_id=chunk.id,
                                chunk_key="C1", page_number=1, quote=quote))
    db.commit()
    requirements, _ = EligibilityService(db)._extract_tender_requirements(tender.id, build_corpus(db, tender.id), run)
    assert requirements[0]["value_number"] == expected
    assert req.value_number == 7  # The stored historical row is never repaired in place.


def test_stage3b_money_amount_reaches_eligibility(db):
    from app.eligibility.service import EligibilityService
    tender = make_tender(db, bid="GEM/2026/B/800002", fields={})
    fx = db.scalar(select(TenderFieldExtraction).where(TenderFieldExtraction.tender_id == tender.id))
    db.add_all([
        TenderFieldValue(field_extraction_id=fx.id, tender_id=tender.id, field_name="bidder_turnover_required",
                         field_group="PERFORMANCE", value_type="BOOL", status="RESOLVED", tri_state="TRUE"),
        TenderFieldValue(field_extraction_id=fx.id, tender_id=tender.id, field_name="bidder_turnover_amount",
                         field_group="PERFORMANCE", value_type="MONEY", status="RESOLVED", value_number=700000),
    ])
    db.commit()
    requirements, _ = EligibilityService(db)._extract_tender_requirements(tender.id, build_corpus(db, tender.id))
    assert len(requirements) == 1
    assert requirements[0]["value_number"] == 700000 and requirements[0]["type"] == "TURNOVER"


@pytest.mark.parametrize("applies_to", ["OEM", "BIDDER_OR_OEM", "UNKNOWN"])
def test_oem_turnover_is_not_compared_to_bidder(applies_to):
    from app.eligibility.engine import EligibilityEngine
    result = EligibilityEngine().evaluate_requirement(
        {"type": "TURNOVER", "value_number": 700000, "applies_to": applies_to},
        {"attributes": []},
    )
    assert result["status"] == "REVIEW_REQUIRED"


@pytest.mark.parametrize("level", ["UNKNOWN", "CONDITIONAL"])
def test_uncertain_obligation_cannot_approve_or_reject_seller(level):
    from app.eligibility.engine import EligibilityEngine
    result = EligibilityEngine().evaluate_requirement(
        {"type": "TURNOVER", "value_number": 700000, "obligation": level},
        {"attributes": [{"key": "annual_turnover", "value_type": "NUMBER", "value_number": 1}]},
    )
    assert result["status"] == "REVIEW_REQUIRED"


def test_independently_discovered_bid_identity_preserved(db, settings, tmp_path):
    b = PdfBuilder()
    page = b.page()
    page.text(40, 40, "Please refer to Bid document of GEM/2026/B/7889130")
    page.text(40, 58, "for technical specification, terms & conditions and other details.")
    page.link(URL, top=40)
    cfg, ra, _ = seed(db, tmp_path, settings, b.build())
    ra.bid_number = "GEM/2026/R/748499"
    bid = Tender(bid_number="GEM/2026/B/7889130", source_url=URL, status="ONGOING",
                 source_fingerprint="original", first_seen_at=utcnow(), last_seen_at=utcnow())
    db.add(bid)
    db.commit()
    identity = bid.id
    discovery = ReferenceDiscovery(DocumentsService(cfg, transport=httpx.MockTransport(
        lambda _: httpx.Response(200, content=text_pdf([["Bid Number: GEM/2026/B/7889130"]]),
                                headers={"content-type": "application/pdf"})), sleep=lambda _: None), resolver=public_dns)
    discovery.run(db, ra)
    discovery.run(db, ra)
    assert db.scalar(select(func.count()).select_from(Tender)) == 2
    assert bid.id == identity and bid.source_fingerprint == "original"
    assert db.scalar(select(func.count()).select_from(TenderDocument).where(TenderDocument.tender_id == ra.id)) == 2
    assert db.scalar(select(DocumentReference)).status == "ACQUIRED"
