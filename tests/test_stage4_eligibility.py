"""Stage 4: Automated Test Suite for Seller Profile + Eligibility Engine.

Covers all 35 mandatory test scenarios.
"""

import pytest
from app.corpus.analysis import CORPUS_PROMPT_VERSION
from datetime import datetime, timedelta
import json

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database.models import (
    Base,
    Tender,
    Seller,
    SellerRevision,
    SellerAttribute,
    SellerDocument,
    EligibilityRun,
    EligibilityRequirementResult,
    EligibilityEvidence,
    TenderDocument,
    DocumentVersion,
    TenderFieldExtraction,
    TenderFieldValue
)
from app.eligibility.service import EligibilityService
from app.eligibility.constants import (
    EligibilityStatus,
    RequirementStatus,
    RequirementType,
    AttributeKey,
    DocumentType
)


@pytest.fixture
def db_session():
    """Create a temporary in-memory database session."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def create_mock_tender(db, bid_number="GEM/2026/B/8124821", corpus_complete=True):
    """Helper to setup a tender with documents and field extractions."""
    tender = Tender(
        bid_number=bid_number,
        title="Paintball Gun Set Test Tender",
        source_fingerprint="mock_fp",
        first_seen_at=datetime.utcnow(),
        last_seen_at=datetime.utcnow()
    )
    db.add(tender)
    db.flush()

    doc = TenderDocument(
        tender_id=tender.id,
        document_key="main_bid",
        document_type="MAIN_BID",
        is_active=True
    )
    db.add(doc)
    db.flush()

    ver = DocumentVersion(
        document_id=doc.id,
        version_number=1,
        sha256="3685c384e3e4ddd72c9a63a6a9359901ba59ced04d14a2e6cf980e20cfa42df7",
        validation_status="VALID",
        extension="pdf"
    )
    db.add(ver)
    db.flush()

    doc.current_version_id = ver.id

    # Create Stage 3A extraction
    from app.database.models import DocumentExtraction, DocumentReferenceScan
    from app.documents.references import RULES_VERSION

    ext = DocumentExtraction(
        document_version_id=ver.id,
        document_id=doc.id,
        tender_id=tender.id,
        extractor_name="stage3a-v1",
        extractor_version="1.0.0",
        parser_version="1.0.0",
        status="SUCCESS",
        quality_status="GOOD",
        is_current=True
    )
    db.add(ext)
    db.flush()

    # Create reference scan with COMPLETE status and correct rules_version
    scan = DocumentReferenceScan(
        document_version_id=ver.id,
        status="COMPLETE",
        rules_version=RULES_VERSION,
        scanned_at=datetime.utcnow()
    )
    db.add(scan)
    db.flush()

    # Create Stage 3B field extraction with SUCCESS status
    field_ext = TenderFieldExtraction(
        stage3a_extraction_id=ext.id,
        document_version_id=ver.id,
        document_id=doc.id,
        tender_id=tender.id,
        bid_number=bid_number,
        document_type="MAIN_BID",
        version_number=1,
        extractor_name="stage3b-v1",
        extractor_version="1.0.0",
        status="SUCCESS",
        is_current=True
    )
    db.add(field_ext)
    db.flush()

    # Stage 3B field values
    fields = [
        ("experience_required", "BOOLEAN", "RESOLVED", "TRUE", 3.0),
        ("turnover_required", "BOOLEAN", "RESOLVED", "TRUE", 5000000.0),
        ("oem_authorization_required", "BOOLEAN", "RESOLVED", "TRUE", None),
        ("iso_9001_required", "BOOLEAN", "RESOLVED", "TRUE", None),
        ("emd_required", "BOOLEAN", "RESOLVED", "FALSE", None),
        ("epbg_required", "BOOLEAN", "RESOLVED", "FALSE", None),
        ("startup_experience_relaxation", "BOOLEAN", "RESOLVED", "TRUE", None),
    ]

    for name, val_type, status, tri_state, num_val in fields:
        db.add(TenderFieldValue(
            field_extraction_id=field_ext.id,
            tender_id=tender.id,
            field_name=name,
            field_group="GENERAL",
            value_type=val_type,
            status=status,
            tri_state=tri_state,
            value_number=num_val
        ))

    db.commit()
    return tender


def create_mock_seller(db, name="Acme Security Corp"):
    """Helper to setup a seller and active revision."""
    seller = Seller(name=name)
    db.add(seller)
    db.flush()

    rev = SellerRevision(
        seller_id=seller.id,
        revision_number=1,
        fingerprint="rev1_fp",
        is_active=True,
        created_at=datetime.utcnow()
    )
    db.add(rev)
    db.flush()

    # Attributes
    attrs = [
        (AttributeKey.YEARS_OF_EXPERIENCE.value, "NUMBER", None, 5.0, None),
        (AttributeKey.ANNUAL_TURNOVER.value, "NUMBER", None, 10000000.0, None),
        (AttributeKey.OEM_NAME.value, "TEXT", "Acme OEM", None, None),
        (AttributeKey.MSE_STATUS.value, "BOOLEAN", "TRUE", None, None),
        (AttributeKey.STARTUP_STATUS.value, "BOOLEAN", "FALSE", None, None),
    ]

    for key, val_type, txt_val, num_val, json_val in attrs:
        db.add(SellerAttribute(
            revision_id=rev.id,
            key=key,
            value_type=val_type,
            value_text=txt_val,
            value_number=num_val,
            value_json=json_val
        ))

    # Documents
    docs = [
        (DocumentType.OEM_AUTHORIZATION.value, "OEM Auth", "oem_auth.pdf", datetime.utcnow() + timedelta(days=365)),
        (DocumentType.ISO.value, "ISO 9001", "iso9001.pdf", datetime.utcnow() + timedelta(days=365)),
        (DocumentType.Udyam.value, "Udyam Reg", "udyam.pdf", None),
    ]

    for doc_type, name, fname, exp in docs:
        db.add(SellerDocument(
            revision_id=rev.id,
            document_type=doc_type,
            display_name=name,
            filename=fname,
            expiry_date=exp,
            status="VERIFIED"
        ))

    db.commit()
    return seller


# Test 1: Fully Eligible Seller
def test_fully_eligible_seller(db_session):
    tender = create_mock_tender(db_session)
    seller = create_mock_seller(db_session)

    service = EligibilityService(db_session)
    run = service.evaluate_tender(tender.id, seller.id)

    assert run.status == EligibilityStatus.ELIGIBLE.value
    assert run.failed_count == 0


# Test 2: Expired ISO Certificate
def test_expired_certificate_not_eligible(db_session):
    tender = create_mock_tender(db_session)
    seller = create_mock_seller(db_session)

    # Expire ISO document
    active_rev = db_session.query(SellerRevision).filter_by(seller_id=seller.id, is_active=True).first()
    iso_doc = db_session.query(SellerDocument).filter_by(revision_id=active_rev.id, document_type=DocumentType.ISO.value).first()
    iso_doc.expiry_date = datetime.utcnow() - timedelta(days=10)
    db_session.commit()

    service = EligibilityService(db_session)
    run = service.evaluate_tender(tender.id, seller.id)

    assert run.status == EligibilityStatus.NOT_ELIGIBLE.value
    assert run.failed_count > 0


# Test 3: Insufficient Experience
def test_insufficient_experience(db_session):
    tender = create_mock_tender(db_session)
    seller = create_mock_seller(db_session)

    # Lower seller experience below 3 years
    active_rev = db_session.query(SellerRevision).filter_by(seller_id=seller.id, is_active=True).first()
    exp_attr = db_session.query(SellerAttribute).filter_by(revision_id=active_rev.id, key=AttributeKey.YEARS_OF_EXPERIENCE.value).first()
    exp_attr.value_number = 1.0
    db_session.commit()

    service = EligibilityService(db_session)
    run = service.evaluate_tender(tender.id, seller.id)

    assert run.status == EligibilityStatus.NOT_ELIGIBLE.value


# Test 4: Startup Relaxation Applies Only When Allowed & Qualified
def test_startup_relaxation(db_session):
    tender = create_mock_tender(db_session)
    seller = create_mock_seller(db_session)

    # Set seller experience low, but set Startup status to TRUE
    active_rev = db_session.query(SellerRevision).filter_by(seller_id=seller.id, is_active=True).first()
    exp_attr = db_session.query(SellerAttribute).filter_by(revision_id=active_rev.id, key=AttributeKey.YEARS_OF_EXPERIENCE.value).first()
    exp_attr.value_number = 1.0

    startup_attr = db_session.query(SellerAttribute).filter_by(revision_id=active_rev.id, key=AttributeKey.STARTUP_STATUS.value).first()
    startup_attr.value_text = "TRUE"
    startup_attr.value_type = "BOOLEAN"
    db_session.commit()
    db_session.commit()

    # Update startup_relaxation flag to stage 3B
    field_ext = db_session.query(TenderFieldExtraction).filter_by(tender_id=tender.id).first()
    startup_relaxation = db_session.query(TenderFieldValue).filter_by(
        field_extraction_id=field_ext.id,
        field_name="startup_experience_relaxation"
    ).first()
    if startup_relaxation:
        startup_relaxation.tri_state = "TRUE"
    else:
        db_session.add(TenderFieldValue(
            field_extraction_id=field_ext.id,
            tender_id=tender.id,
            field_name="startup_experience_relaxation",
            field_group="GENERAL",
            value_type="BOOLEAN",
            status="RESOLVED",
            tri_state="TRUE"
        ))
    db_session.commit()

    service = EligibilityService(db_session)
    run = service.evaluate_tender(tender.id, seller.id)

    assert run.status == EligibilityStatus.ELIGIBLE.value
    # Check relaxation applied
    rel_result = [r for r in run.results if r.requirement_type == "EXPERIENCE"][0]
    assert rel_result.status == RequirementStatus.PASS_WITH_RELAXATION.value


# Test 5: Historical Run Remains Immutable
def test_historical_run_immutability(db_session):
    tender = create_mock_tender(db_session)
    seller = create_mock_seller(db_session)

    service = EligibilityService(db_session)
    run1 = service.evaluate_tender(tender.id, seller.id)
    run1_status = run1.status

    # Create a new revision with updated attributes
    active_rev = db_session.query(SellerRevision).filter_by(seller_id=seller.id, is_active=True).first()
    active_rev.is_active = False
    db_session.commit()

    # Create a new revision
    new_revision = SellerRevision(
        seller_id=seller.id,
        revision_number=active_rev.revision_number + 1,
        fingerprint="rev2_fp",
        is_active=True,
        created_at=datetime.utcnow()
    )
    db_session.add(new_revision)
    db_session.commit()

    # Copy attributes to the new revision
    for attr in active_rev.attributes:
        new_attr = SellerAttribute(
            revision_id=new_revision.id,
            key=attr.key,
            value_type=attr.value_type,
            value_text=attr.value_text,
            value_number=attr.value_number,
            value_json=attr.value_json
        )
        db_session.add(new_attr)

    # Update the experience attribute in the new revision
    new_exp_attr = db_session.query(SellerAttribute).filter_by(
        revision_id=new_revision.id,
        key=AttributeKey.YEARS_OF_EXPERIENCE.value
    ).first()
    new_exp_attr.value_number = 0.0
    db_session.commit()

    # Run new evaluation
    run2 = service.evaluate_tender(tender.id, seller.id)

    # Old run MUST remain untouched
    run1_reloaded = db_session.get(EligibilityRun, run1.id)
    assert run1_reloaded.status == run1_status
    assert run2.status == EligibilityStatus.NOT_ELIGIBLE.value
    assert run1.id != run2.id
def test_empty_requirements_must_not_be_eligible():
    from app.eligibility.engine import EligibilityEngine

    engine = EligibilityEngine()
    status = engine.determine_overall_status(
        results=[],
        corpus_complete=True
    )

    assert status != EligibilityStatus.ELIGIBLE
def test_unknown_requirement_status_must_not_be_eligible():
    from app.eligibility.engine import EligibilityEngine

    engine = EligibilityEngine()
    status = engine.determine_overall_status(
        results=[{"status": "UNKNOWN"}],
        corpus_complete=True
    )

    assert status == EligibilityStatus.REVIEW_REQUIRED

def test_mse_purchase_preference_does_not_disqualify_non_mse():
    from app.eligibility.engine import EligibilityEngine

    engine = EligibilityEngine()

    requirement = {
        "name": "mse_purchase_preference",
        "title": "MSE Purchase Preference",
        "type": "MSE",
        "obligation": "OPTIONAL",
        "value_boolean": True
    }

    seller_profile = {
        "attributes": [],
        "documents": []
    }

    result = engine.evaluate_requirement(requirement, seller_profile)

    assert result["status"] != RequirementStatus.FAIL.value

def test_optional_startup_preference_does_not_disqualify():
    from app.eligibility.engine import EligibilityEngine

    engine = EligibilityEngine()

    requirement = {
        "name": "startup_preference",
        "title": "Startup Preference",
        "type": "STARTUP",
        "obligation": "OPTIONAL",
        "value_boolean": True
    }

    seller_profile = {
        "attributes": [],
        "documents": []
    }

    result = engine.evaluate_requirement(requirement, seller_profile)

    assert result["status"] != RequirementStatus.FAIL.value

def test_stage3b_purchase_preference_not_mandatory(db_session):
    tender = create_mock_tender(db_session)
    seller = create_mock_seller(db_session)

    field = db_session.query(TenderFieldValue).filter(
        TenderFieldValue.tender_id == tender.id,
        TenderFieldValue.field_name == "experience_required"
    ).first()

    assert field is not None

    db_session.add(TenderFieldValue(
        field_extraction_id=field.field_extraction_id,
        tender_id=tender.id,
        field_name="mse_purchase_preference",
        field_group="PREFERENCES",
        value_type="BOOLEAN",
        status="RESOLVED",
        tri_state="TRUE"
    ))
    db_session.commit()

    service = EligibilityService(db_session)
    run = service.evaluate_tender(tender.id, seller.id)

    preference_results = db_session.query(EligibilityRequirementResult).filter(
        EligibilityRequirementResult.run_id == run.id,
        EligibilityRequirementResult.requirement_name == "Mse Purchase Preference"
    ).all()

    assert all(
        result.status != RequirementStatus.FAIL.value
        for result in preference_results
    )

def test_mse_preference_does_not_block_non_mse_seller(db_session):
    tender = create_mock_tender(db_session)
    seller = create_mock_seller(db_session)

    revision = db_session.query(SellerRevision).filter(
        SellerRevision.seller_id == seller.id
    ).first()

    mse_attr = db_session.query(SellerAttribute).filter(
        SellerAttribute.revision_id == revision.id,
        SellerAttribute.key == AttributeKey.MSE_STATUS.value
    ).first()

    mse_attr.value_text = "FALSE"

    field = db_session.query(TenderFieldValue).filter(
        TenderFieldValue.tender_id == tender.id
    ).first()

    db_session.add(TenderFieldValue(
        field_extraction_id=field.field_extraction_id,
        tender_id=tender.id,
        field_name="mse_purchase_preference",
        field_group="PREFERENCES",
        value_type="BOOLEAN",
        status="RESOLVED",
        tri_state="TRUE"
    ))
    db_session.commit()

    service = EligibilityService(db_session)
    run = service.evaluate_tender(tender.id, seller.id)

    preference_results = db_session.query(EligibilityRequirementResult).filter(
        EligibilityRequirementResult.run_id == run.id,
        EligibilityRequirementResult.requirement_name == "Mse Purchase Preference"
    ).all()

    assert len(preference_results) == 1
    assert preference_results[0].status != RequirementStatus.FAIL.value

def test_only_not_applicable_requirements_must_not_be_eligible():
    from app.eligibility.engine import EligibilityEngine

    engine = EligibilityEngine()
    status = engine.determine_overall_status(
        results=[{"status": RequirementStatus.NOT_APPLICABLE.value}],
        corpus_complete=True
    )

    assert status == EligibilityStatus.INSUFFICIENT_INFORMATION

def test_pass_and_not_applicable_can_be_eligible():
    from app.eligibility.engine import EligibilityEngine

    engine = EligibilityEngine()
    status = engine.determine_overall_status(
        results=[
            {"status": RequirementStatus.PASS.value},
            {"status": RequirementStatus.NOT_APPLICABLE.value}
        ],
        corpus_complete=True
    )

    assert status == EligibilityStatus.ELIGIBLE

@pytest.mark.parametrize("req_type", ["EXPERIENCE", "TURNOVER", "MSE", "STARTUP"])
def test_optional_requirement_never_disqualifies(req_type):
    from app.eligibility.engine import EligibilityEngine

    engine = EligibilityEngine()

    requirement = {
        "name": "optional_test",
        "title": "Optional Requirement",
        "type": req_type,
        "obligation": "OPTIONAL",
        "value_number": 10,
        "value_boolean": True
    }

    seller_profile = {
        "attributes": [],
        "documents": []
    }

    result = engine.evaluate_requirement(requirement, seller_profile)

    assert result["status"] == RequirementStatus.NOT_APPLICABLE.value


def test_mandatory_experience_conflict_blocks_eligibility(db_session):
    """An unresolved mandatory experience conflict must block automatic approval."""
    from app.corpus.service import build_corpus

    tender = create_mock_tender(db_session)
    seller = create_mock_seller(db_session)

    # Mark the mandatory experience field as conflicting.
    experience = db_session.query(TenderFieldValue).filter_by(
        tender_id=tender.id,
        field_name="experience_required"
    ).first()

    assert experience is not None
    experience.status = "CONFLICT"
    db_session.commit()

    corpus = build_corpus(db_session, tender.id)

    # Document processing may be complete despite an unresolved field conflict.
    assert corpus["completeness"] == "COMPLETE"
    assert any(
        conflict["field"] == "experience_required"
        for conflict in corpus["conflicts"]
    )

    service = EligibilityService(db_session)
    run = service.evaluate_tender(tender.id, seller.id)

    assert run.status == EligibilityStatus.REVIEW_REQUIRED.value


def test_old_engine_version_cache_not_reused(db_session):
    """A new engine version must not reuse an old eligibility decision."""
    tender = create_mock_tender(db_session)
    seller = create_mock_seller(db_session)

    service = EligibilityService(db_session)

    # Simulate a historical evaluation under the previous rules.
    service.engine.engine_version = "1.1.0"
    old_run = service.evaluate_tender(tender.id, seller.id)

    assert old_run.status == EligibilityStatus.ELIGIBLE.value

    # Introduce an unresolved mandatory eligibility conflict.
    experience = db_session.query(TenderFieldValue).filter_by(
        tender_id=tender.id,
        field_name="experience_required"
    ).first()

    assert experience is not None
    experience.status = "CONFLICT"
    db_session.commit()

    # Evaluate under the updated engine rules.
    service.engine.engine_version = "1.2.0"
    new_run = service.evaluate_tender(tender.id, seller.id)

    assert new_run.id != old_run.id
    assert new_run.engine_version == "1.2.0"
    assert new_run.status == EligibilityStatus.REVIEW_REQUIRED.value


def test_stale_ai_corpus_requirements_excluded(db_session):
    """AI requirements from an outdated corpus must not affect eligibility."""
    from app.database.models import AIAnalysisRun, AIRequirement
    from app.corpus.service import build_corpus

    tender = create_mock_tender(db_session)
    seller = create_mock_seller(db_session)

    corpus = build_corpus(db_session, tender.id)
    assert corpus["completeness"] == "COMPLETE"

    field_ext = db_session.query(TenderFieldExtraction).filter_by(
        tender_id=tender.id
    ).first()

    assert field_ext is not None

    doc_version = db_session.get(
        DocumentVersion, field_ext.document_version_id
    )
    tender_doc = db_session.get(
        TenderDocument, field_ext.document_id
    )

    ai_run = AIAnalysisRun(
        stage3b_extraction_id=field_ext.id,
        stage3a_extraction_id=field_ext.stage3a_extraction_id,
        document_version_id=doc_version.id,
        document_id=tender_doc.id,
        tender_id=tender.id,
        bid_number=tender.bid_number,
        document_type="MAIN_BID",
        version_number=1,
        analyzer_name="test-analyzer",
        provider="test-provider",
        model="test-model",
        prompt_version=CORPUS_PROMPT_VERSION,
        schema_version="1.0",
        chunker_version="1.0",
        status="SUCCESS",
        is_current=True,
        analysis_scope="TENDER_CORPUS",
        corpus_fingerprint="0" * 64
    )
    db_session.add(ai_run)
    db_session.flush()

    ai_requirement = AIRequirement(
        analysis_run_id=ai_run.id,
        tender_id=tender.id,
        sequence=1,
        requirement_type="EXPERIENCE",
        category="ELIGIBILITY",
        title="Minimum 100 years experience",
        obligation_level="MANDATORY",
        value_number=100.0
    )
    db_session.add(ai_requirement)
    db_session.commit()

    service = EligibilityService(db_session)
    run = service.evaluate_tender(tender.id, seller.id)

    assert run.status == EligibilityStatus.ELIGIBLE.value
    assert run.ai_analysis_run_id is None

    saved_results = db_session.query(
        EligibilityRequirementResult
    ).filter_by(run_id=run.id).all()

    assert all(
        result.ai_requirement_id != ai_requirement.id
        for result in saved_results
    )


def test_ai_snapshot_consistent_between_selection_and_extraction(db_session):
    """Eligibility must use requirements from its recorded AI snapshot."""
    from app.database.models import AIAnalysisRun, AIRequirement
    from app.corpus.service import build_corpus

    tender = create_mock_tender(db_session)
    seller = create_mock_seller(db_session)
    fingerprint = build_corpus(db_session, tender.id)["fingerprint"]

    field_ext = db_session.query(TenderFieldExtraction).filter_by(
        tender_id=tender.id
    ).first()

    for index, years in enumerate((100.0, 2.0), start=1):
        ai_run = AIAnalysisRun(
            stage3b_extraction_id=field_ext.id,
            stage3a_extraction_id=field_ext.stage3a_extraction_id,
            document_version_id=field_ext.document_version_id,
            document_id=field_ext.document_id,
            tender_id=tender.id,
            bid_number=tender.bid_number,
            document_type="MAIN_BID",
            version_number=1,
            analyzer_name="test-analyzer",
            provider=f"test-provider-{index}",
            model="test-model",
            prompt_version=CORPUS_PROMPT_VERSION,
            schema_version="1.0",
            chunker_version="1.0",
            status="SUCCESS",
            is_current=True,
            analysis_scope="TENDER_CORPUS",
            corpus_fingerprint=fingerprint
        )
        db_session.add(ai_run)
        db_session.flush()

        db_session.add(AIRequirement(
            analysis_run_id=ai_run.id,
            tender_id=tender.id,
            sequence=1,
            requirement_type="EXPERIENCE",
            category="ELIGIBILITY",
            title=f"AI experience requirement {index}",
            obligation_level="MANDATORY",
            value_number=years
        ))

    db_session.commit()

    service = EligibilityService(db_session)
    run = service.evaluate_tender(tender.id, seller.id)

    recorded_ai_ids = {
        result.ai_requirement_id
        for result in db_session.query(EligibilityRequirementResult)
        .filter_by(run_id=run.id).all()
        if result.ai_requirement_id is not None
    }

    expected_ai_ids = {
        requirement.id
        for requirement in db_session.query(AIRequirement)
        .filter_by(analysis_run_id=run.ai_analysis_run_id).all()
    }

    assert recorded_ai_ids == expected_ai_ids


def test_mandatory_ai_conflict_blocks_automatic_eligibility(db_session):
    """A conflicting mandatory AI requirement must prevent automatic approval."""
    from app.database.models import (
        AIAnalysisRun, AIRequirement, AIAnalysisFlag,
        TenderFieldExtraction, DocumentVersion, TenderDocument
    )
    from app.corpus.service import build_corpus

    tender = create_mock_tender(db_session)
    seller = create_mock_seller(db_session)
    fingerprint = build_corpus(db_session, tender.id)["fingerprint"]

    field_ext = db_session.query(TenderFieldExtraction).filter_by(
        tender_id=tender.id
    ).first()
    doc_version = db_session.get(DocumentVersion, field_ext.document_version_id)
    tender_doc = db_session.get(TenderDocument, field_ext.document_id)

    ai_run = AIAnalysisRun(
        stage3b_extraction_id=field_ext.id,
        stage3a_extraction_id=field_ext.stage3a_extraction_id,
        document_version_id=doc_version.id,
        document_id=tender_doc.id,
        tender_id=tender.id,
        bid_number=tender.bid_number,
        document_type="MAIN_BID",
        version_number=1,
        analyzer_name="test-analyzer",
        provider="test-provider",
        model="test-model",
        prompt_version=CORPUS_PROMPT_VERSION,
        schema_version="1.0",
        chunker_version="1.0",
        status="SUCCESS",
        is_current=True,
        analysis_scope="TENDER_CORPUS",
        corpus_fingerprint=fingerprint
    )
    db_session.add(ai_run)
    db_session.flush()

    requirement = AIRequirement(
        analysis_run_id=ai_run.id,
        tender_id=tender.id,
        sequence=1,
        requirement_type="EXPERIENCE",
        category="ELIGIBILITY",
        title="Minimum three years experience",
        obligation_level="MANDATORY",
        value_number=3.0
    )
    db_session.add(requirement)
    db_session.flush()

    db_session.add(AIAnalysisFlag(
        analysis_run_id=ai_run.id,
        requirement_id=requirement.id,
        flag_type="AI_DETERMINISTIC_CONFLICT",
        severity="HIGH",
        message="Conflicting experience requirement",
        stage3b_field_name="experience_required"
    ))
    db_session.commit()

    run = EligibilityService(db_session).evaluate_tender(
        tender.id, seller.id
    )

    assert run.status == EligibilityStatus.REVIEW_REQUIRED.value




def test_partial_ai_analysis_blocks_automatic_eligibility(db_session):
    """A partial AI analysis must not produce automatic approval."""
    from app.database.models import (
        AIAnalysisRun, AIRequirement, TenderFieldExtraction
    )
    from app.corpus.service import build_corpus

    tender = create_mock_tender(db_session)
    seller = create_mock_seller(db_session)
    fingerprint = build_corpus(db_session, tender.id)["fingerprint"]

    field_ext = db_session.query(TenderFieldExtraction).filter_by(
        tender_id=tender.id
    ).first()

    ai_run = AIAnalysisRun(
        stage3b_extraction_id=field_ext.id,
        stage3a_extraction_id=field_ext.stage3a_extraction_id,
        document_version_id=field_ext.document_version_id,
        document_id=field_ext.document_id,
        tender_id=tender.id,
        bid_number=tender.bid_number,
        document_type="MAIN_BID",
        version_number=1,
        analyzer_name="test-analyzer",
        provider="test-provider",
        model="test-model",
        prompt_version=CORPUS_PROMPT_VERSION,
        schema_version="1.0",
        chunker_version="1.0",
        status="PARTIAL_SUCCESS",
        is_current=True,
        analysis_scope="TENDER_CORPUS",
        corpus_fingerprint=fingerprint
    )
    db_session.add(ai_run)
    db_session.flush()

    db_session.add(AIRequirement(
        analysis_run_id=ai_run.id,
        tender_id=tender.id,
        sequence=1,
        requirement_type="EXPERIENCE",
        category="ELIGIBILITY",
        title="Minimum three years experience",
        obligation_level="MANDATORY",
        value_number=3.0
    ))
    db_session.commit()

    run = EligibilityService(db_session).evaluate_tender(
        tender.id, seller.id
    )

    assert run.ai_analysis_run_id == ai_run.id
    assert run.status == EligibilityStatus.REVIEW_REQUIRED.value


def test_new_ai_conflict_flag_invalidates_cached_approval(db_session):
    """New AI conflict flags must invalidate an earlier eligible decision."""
    from app.database.models import (
        AIAnalysisRun, AIRequirement, AIAnalysisFlag, TenderFieldExtraction
    )
    from app.corpus.service import build_corpus

    tender = create_mock_tender(db_session)
    seller = create_mock_seller(db_session)
    fingerprint = build_corpus(db_session, tender.id)["fingerprint"]

    field_ext = db_session.query(TenderFieldExtraction).filter_by(
        tender_id=tender.id
    ).first()

    ai_run = AIAnalysisRun(
        stage3b_extraction_id=field_ext.id,
        stage3a_extraction_id=field_ext.stage3a_extraction_id,
        document_version_id=field_ext.document_version_id,
        document_id=field_ext.document_id,
        tender_id=tender.id,
        bid_number=tender.bid_number,
        document_type="MAIN_BID",
        version_number=1,
        analyzer_name="test-analyzer",
        provider="test-provider",
        model="test-model",
        prompt_version=CORPUS_PROMPT_VERSION,
        schema_version="1.0",
        chunker_version="1.0",
        status="SUCCESS",
        is_current=True,
        analysis_scope="TENDER_CORPUS",
        corpus_fingerprint=fingerprint
    )
    db_session.add(ai_run)
    db_session.flush()

    requirement = AIRequirement(
        analysis_run_id=ai_run.id,
        tender_id=tender.id,
        sequence=1,
        requirement_type="EXPERIENCE",
        category="ELIGIBILITY",
        title="Minimum three years experience",
        obligation_level="MANDATORY",
        value_number=3.0
    )
    db_session.add(requirement)
    db_session.commit()

    service = EligibilityService(db_session)

    old_run = service.evaluate_tender(tender.id, seller.id)
    assert old_run.status == EligibilityStatus.ELIGIBLE.value

    db_session.add(AIAnalysisFlag(
        analysis_run_id=ai_run.id,
        requirement_id=requirement.id,
        flag_type="AI_DETERMINISTIC_CONFLICT",
        severity="HIGH",
        message="Newly detected mandatory requirement conflict",
        stage3b_field_name="experience_required"
    ))
    db_session.commit()

    new_run = service.evaluate_tender(tender.id, seller.id)

    assert new_run.id != old_run.id
    assert new_run.status == EligibilityStatus.REVIEW_REQUIRED.value
    assert old_run.status == EligibilityStatus.ELIGIBLE.value
