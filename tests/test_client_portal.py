"""Client portal: content, ordering, and strict per-client isolation, enforced on the backend.

Client A and Client B each own one seller. Every attempt by A to read or
modify B's data must fail safely: 403 for B's seller scope, 404 for a tender
that is not matched to A.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.api.auth import get_current_user, get_token_verifier
from app.core.supabase_auth import AuthenticatedIdentity
from app.database.models import (
    AIAnalysisRun,
    AIEvidenceChunk,
    AIRequirement,
    AIRequirementEvidence,
    DocumentExtraction,
    DocumentVersion,
    Tender,
    TenderDocument,
)
from app.main import create_app
from app.matching.service import MatchingService
from app.utils.dates import utcnow
from tests.matching_factories import make_seller, make_tender

A_SUB = "aaaaaaaa-0000-0000-0000-000000000001"
B_SUB = "bbbbbbbb-0000-0000-0000-000000000002"


def _ident(sub: str) -> AuthenticatedIdentity:
    return AuthenticatedIdentity(subject=sub, email=None, claims={"sub": sub, "role": "authenticated"})


@pytest.fixture
def portal(settings, session_factory, source, tmp_path, monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://portal-tests.supabase.co")
    get_token_verifier.cache_clear()
    storage = tmp_path / "tenders"
    (storage / "GEM_A").mkdir(parents=True)
    (storage / "GEM_A" / "main.pdf").write_bytes(b"%PDF-1.4 sample")
    cfg = settings.model_copy(update={"document_storage_path": str(storage)})
    app = create_app(cfg, session_factory=session_factory, collector_factory=source)

    with session_factory() as db:
        laptop_live = make_tender(db, bid="GEM/2026/B/9100001", storage_path="GEM_A/main.pdf", deadline_days=5)
        laptop_soon = make_tender(db, bid="GEM/2026/B/9100002", deadline_days=1,
                                  fields={"oem_authorization_required": ("TRUE", None)})   # -> review for A
        laptop_closed = make_tender(db, bid="GEM/2026/B/9100003", deadline_days=-2)
        chairs = make_tender(db, bid="GEM/2026/B/9100004", title="Office chairs", category="Office Chair")
        _add_ai_requirement(db, laptop_live.id)
        a = make_seller(db, name="Client A Laptops", owner_subject=A_SUB)
        b = make_seller(db, name="Client B Chairs", terms="Office Chair", owner_subject=B_SUB)
        MatchingService(db).recalculate(now=utcnow())
        ids = dict(a=a.id, b=b.id, live=laptop_live.id, soon=laptop_soon.id, closed=laptop_closed.id,
                   chairs=chairs.id)
        doc = db.scalar(select(TenderDocument).where(TenderDocument.tender_id == laptop_live.id))
        ids["doc"], ids["ver"] = doc.id, doc.current_version_id
        chairs_doc = db.scalar(select(TenderDocument).where(TenderDocument.tender_id == chairs.id))
        ids["chairs_doc"], ids["chairs_ver"] = chairs_doc.id, chairs_doc.current_version_id

    with TestClient(app) as c:
        def as_user(sub):
            if sub is None:
                c.app.dependency_overrides.pop(get_current_user, None)
            else:
                c.app.dependency_overrides[get_current_user] = lambda: _ident(sub)
            return c
        yield as_user, ids
    get_token_verifier.cache_clear()


def _add_ai_requirement(db, tender_id: int) -> None:
    """A current corpus AI analysis with one evidence-grounded requirement (as Stage 3C stores it)."""
    ver = db.scalar(select(DocumentVersion).join(TenderDocument, TenderDocument.id == DocumentVersion.document_id)
                    .where(TenderDocument.tender_id == tender_id))
    ext = db.scalar(select(DocumentExtraction).where(DocumentExtraction.document_version_id == ver.id))
    from app.database.models import TenderFieldExtraction
    fx = db.scalar(select(TenderFieldExtraction).where(TenderFieldExtraction.tender_id == tender_id))
    run = AIAnalysisRun(stage3b_extraction_id=fx.id, stage3a_extraction_id=ext.id, document_version_id=ver.id,
                        document_id=ver.document_id, tender_id=tender_id, bid_number="GEM/2026/B/9100001",
                        document_type="MAIN_BID", version_number=1, analyzer_name="corpus", provider="mock",
                        model="mock-v1", prompt_version="corpus-prompt-v2", schema_version="s", chunker_version="c",
                        status="SUCCESS", is_current=True, analysis_scope="TENDER_CORPUS",
                        summary="Supply of 50 laptops to the Ministry of Education.")
    db.add(run)
    db.flush()
    chunk = AIEvidenceChunk(analysis_run_id=run.id, chunk_key="C1", sequence=1, kind="CLAUSE_TEXT",
                            source_type="SECTION_TEXT", stage3a_extraction_id=ext.id, document_version_id=ver.id,
                            page_number=3, page_end=3, text="Bidder shall have ISO 9001 certification.",
                            char_count=41, text_sha256="0" * 64)
    db.add(chunk)
    db.flush()
    req = AIRequirement(analysis_run_id=run.id, tender_id=tender_id, sequence=1, requirement_type="WARRANTY",
                        category="DELIVERY_WARRANTY", title="Three year onsite warranty", obligation_level="MANDATORY",
                        value_number=3, unit="YEARS")
    db.add(req)
    db.flush()
    db.add(AIRequirementEvidence(requirement_id=req.id, analysis_run_id=run.id, chunk_id=chunk.id, chunk_key="C1",
                                 page_number=3, quote="Bidder shall have ISO 9001 certification."))
    db.commit()


# ---------------------------------------------------------------------------
# What a client sees
# ---------------------------------------------------------------------------

def test_dashboard_lists_matched_live_first_then_review(portal):
    as_user, ids = portal
    c = as_user(A_SUB)
    body = c.get(f"/api/portal/sellers/{ids['a']}/tenders").json()
    assert [(i["tender_id"], i["match"]["match_status"]) for i in body["items"]] == [
        (ids["live"], "MATCHED"), (ids["soon"], "REVIEW_REQUIRED")]
    assert ids["closed"] not in [i["tender_id"] for i in body["items"]]        # expired kept out of live view
    assert ids["chairs"] not in [i["tender_id"] for i in body["items"]]        # irrelevant global tender
    hist = c.get(f"/api/portal/sellers/{ids['a']}/tenders", params={"live_only": False, "view": "all"}).json()
    assert {i["tender_id"] for i in hist["items"]} == {ids["live"], ids["soon"]}   # closed one never matched (not live)
    review = c.get(f"/api/portal/sellers/{ids['a']}/tenders", params={"view": "review"}).json()
    assert [i["tender_id"] for i in review["items"]] == [ids["soon"]]
    soon = c.get(f"/api/portal/sellers/{ids['a']}/tenders", params={"closing_within_days": 2}).json()
    assert [i["tender_id"] for i in soon["items"]] == [ids["soon"]]
    assert c.get(f"/api/portal/sellers/{ids['a']}/tenders", params={"buyer": "Education"}).json()["total"] == 2
    assert c.get(f"/api/portal/sellers/{ids['a']}/tenders", params={"category": "%"}).json()["total"] == 0


def test_summary_counts_and_guidance(portal):
    as_user, ids = portal
    s = as_user(A_SUB).get(f"/api/portal/sellers/{ids['a']}/summary").json()
    assert (s["live_matched"], s["live_review_required"], s["closing_within_3_days"]) == (1, 1, 1)
    assert s["matching_terms"] == ["Laptop"] and s["guidance"] == []


def test_tender_detail_is_structured_with_evidence_and_reasons(portal):
    as_user, ids = portal
    d = as_user(A_SUB).get(f"/api/portal/sellers/{ids['a']}/tenders/{ids['live']}").json()
    assert d["basic"]["bid_number"] == "GEM/2026/B/9100001" and d["status"]["current_status"] == "LIVE"
    assert d["summary"] == "Supply of 50 laptops to the Ministry of Education."
    tech = d["technical_requirements"]
    assert tech[0]["title"] == "Three year onsite warranty"
    assert tech[0]["evidence"] == [{"document_id": ids["doc"], "document_type": "MAIN_BID",
                                    "document_name": "Bid Document", "page": 3, "section": None,
                                    "quote": "Bidder shall have ISO 9001 certification."}]
    assert d["documents"][0]["versions"][0]["sha256"] and d["documents"][0]["versions"][0]["downloadable"]
    reasons = d["match"]["reasons"]
    assert d["match"]["match_status"] == "MATCHED" and not reasons["failed"]
    assert {r["requirement_type"] for r in reasons["matched"]} >= {"RELEVANCE", "TURNOVER", "EXPERIENCE", "ISO"}
    assert d["amendments"]["amended"] is False
    review = as_user(A_SUB).get(f"/api/portal/sellers/{ids['a']}/tenders/{ids['soon']}").json()
    assert review["analysis_status"] == "NOT_ANALYSED" and review["summary"] is None   # never invented
    assert any(r["requirement_type"] == "OEM_AUTHORIZATION" for r in review["match"]["reasons"]["needs_review"])


def test_document_download_for_matched_tender(portal):
    as_user, ids = portal
    r = as_user(A_SUB).get(
        f"/api/portal/sellers/{ids['a']}/tenders/{ids['live']}/documents/{ids['doc']}/versions/{ids['ver']}/download")
    assert r.status_code == 200 and r.content == b"%PDF-1.4 sample"
    assert r.headers["content-disposition"].startswith("attachment")
    assert r.headers["x-content-type-options"] == "nosniff"


# ---------------------------------------------------------------------------
# Tenant isolation (all must fail safely)
# ---------------------------------------------------------------------------

def test_client_a_cannot_read_client_b_data(portal):
    as_user, ids = portal
    c = as_user(A_SUB)
    b = ids["b"]
    for url in (f"/api/portal/sellers/{b}/summary", f"/api/portal/sellers/{b}/tenders",
                f"/api/portal/sellers/{b}/tenders/{ids['chairs']}",
                f"/api/sellers/{b}", f"/api/eligibility?seller_id={b}"):
        assert c.get(url).status_code == 403, url
    assert c.post(f"/api/portal/sellers/{b}/matches/refresh").status_code == 403
    # A's own listing never contains B's results
    assert all(i["tender_id"] != ids["chairs"] for i in
               c.get(f"/api/portal/sellers/{ids['a']}/tenders", params={"view": "all", "live_only": False})
               .json()["items"])


def test_client_a_cannot_fetch_client_b_match_via_own_scope(portal):
    as_user, ids = portal
    c = as_user(A_SUB)
    # chairs tender is matched to B only: via A's scope it does not exist
    assert c.get(f"/api/portal/sellers/{ids['a']}/tenders/{ids['chairs']}").status_code == 404
    assert c.get(f"/api/portal/sellers/{ids['a']}/tenders/{ids['closed']}").status_code == 404
    assert c.get(f"/api/portal/sellers/{ids['a']}/tenders/999999").status_code == 404


def test_client_a_cannot_obtain_documents_outside_its_matches(portal):
    as_user, ids = portal
    c = as_user(A_SUB)
    base = f"/api/portal/sellers/{ids['a']}/tenders"
    # B's tender document through A's scope
    assert c.get(f"{base}/{ids['chairs']}/documents/{ids['chairs_doc']}/versions/{ids['chairs_ver']}/download") \
        .status_code == 404
    # B's document id spliced under A's matched tender
    assert c.get(f"{base}/{ids['live']}/documents/{ids['chairs_doc']}/versions/{ids['chairs_ver']}/download") \
        .status_code == 404
    # B's scope entirely
    assert c.get(f"/api/portal/sellers/{ids['b']}/tenders/{ids['chairs']}/documents/{ids['chairs_doc']}/versions/"
                 f"{ids['chairs_ver']}/download").status_code == 403


def test_client_a_cannot_edit_client_b_profile(portal):
    as_user, ids = portal
    r = as_user(A_SUB).post(f"/api/sellers/{ids['b']}/attributes",
                            data={"key": "product_category", "value_type": "TEXT", "value_text": "Laptop"})
    assert r.status_code == 403
    r = as_user(A_SUB).post("/api/eligibility/evaluate", json={"tender_id": ids["chairs"], "seller_id": ids["b"]})
    assert r.status_code == 403


def test_seller_id_in_request_is_not_trusted(portal):
    """A user with no membership at all gets nothing, whatever IDs are sent."""
    as_user, ids = portal
    c = as_user(str(uuid.uuid4()))
    for sid in (ids["a"], ids["b"]):
        assert c.get(f"/api/portal/sellers/{sid}/tenders").status_code == 403


def test_unauthenticated_and_misconfigured_auth(portal, monkeypatch):
    as_user, ids = portal
    c = as_user(None)
    for url in (f"/api/portal/sellers/{ids['a']}/tenders", "/api/tenders", "/api/stats", "/api/sellers"):
        assert c.get(url).status_code == 401, url
    monkeypatch.delenv("SUPABASE_URL")
    get_token_verifier.cache_clear()
    r = c.get(f"/api/portal/sellers/{ids['a']}/tenders")
    assert r.status_code == 503 and r.json() == {"detail": "Authentication is not configured"}


def test_profile_change_then_refresh_updates_portal(portal, session_factory):
    as_user, ids = portal
    c = as_user(A_SUB)
    r = c.post(f"/api/sellers/{ids['a']}/attributes",
               data={"key": "annual_turnover", "value_type": "NUMBER", "value_number": "100000"})
    assert r.status_code == 200
    refreshed = c.post(f"/api/portal/sellers/{ids['a']}/matches/refresh").json()
    assert refreshed["evaluated"] >= 1 and refreshed["errors"] == 0
    again = c.post(f"/api/portal/sellers/{ids['a']}/matches/refresh")
    assert again.status_code == 429 and again.headers["retry-after"] == "30"   # bounded manual recomputation
    items = c.get(f"/api/portal/sellers/{ids['a']}/tenders", params={"view": "not_matched"}).json()["items"]
    assert ids["live"] in [i["tender_id"] for i in items]
    d = c.get(f"/api/portal/sellers/{ids['a']}/tenders/{ids['live']}").json()
    assert any(r["requirement_type"] == "TURNOVER" for r in d["match"]["reasons"]["failed"])


@pytest.mark.parametrize("data", [
    {"key": "Bad Key!", "value_type": "TEXT", "value_text": "x"},
    {"key": "annual_turnover", "value_type": "NUMBER"},
    {"key": "mse_status", "value_type": "BOOLEAN", "value_text": "maybe"},
    {"key": "products", "value_type": "JSON", "value_json": "{not json"},
    {"key": "products", "value_type": "SQL", "value_text": "x"},
    {"key": "keywords", "value_type": "TEXT", "value_text": "x" * 5001},
])
def test_profile_attribute_input_is_validated(portal, data):
    as_user, ids = portal
    assert as_user(A_SUB).post(f"/api/sellers/{ids['a']}/attributes", data=data).status_code == 422
