"""Automatic seller <-> tender matching: relevance kept separate from eligibility,
explained reasons, unknown never turned into failure, recalculation on profile
or tender change, and no AI calls."""

from __future__ import annotations

import json

import pytest
from sqlalchemy import func, select

from app.database.matching_models import SellerTenderMatch
from app.database.models import AIProviderCall, EligibilityRun, Tender, TenderFieldValue
from app.matching.relevance import evaluate_relevance, parse_terms, tokenize
from app.matching.service import MATCHER_VERSION, MatchingService, match_status_for
from app.services.status_service import verify_statuses
from app.utils.dates import utcnow
from tests.matching_factories import make_seller, make_tender, new_revision


# ---------------------------------------------------------------------------
# Relevance (pure)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("terms,category,title,expected", [
    (["Laptop"], "Laptop - Notebook", "Supply of laptops", "RELEVANT"),               # category match
    (["laptops"], "Laptop - Notebook", None, "RELEVANT"),                             # plural folded
    (["office chair"], "Office Chairs", None, "RELEVANT"),                            # multi-word, all tokens
    (["office chair"], "Office Table", None, "NOT_RELEVANT"),                         # partial is not enough
    (["Laptop"], "Desktop Computers", "Supply of desktop computer", "NOT_RELEVANT"),  # category mismatch
    (["CCTV camera", "Laptop"], "Desktop", "Laptop and printer AMC", "RELEVANT"),     # title match
    ([], "Laptop", None, "UNKNOWN"),                                                  # no seller terms
    (["Laptop"], None, None, "UNKNOWN"),                                              # nothing to compare
])
def test_relevance(terms, category, title, expected):
    assert evaluate_relevance(terms, category, title).status == expected


def test_term_parsing_text_and_json():
    assert parse_terms(["Laptop, Desktop; Printer\nScanner", '["CCTV Camera", "laptop"]']) == [
        "Laptop", "Desktop", "Printer", "Scanner", "CCTV Camera"]
    assert parse_terms(["the, of, and"]) == []          # stopwords only -> no usable term
    assert tokenize("Batteries & Boxes") == frozenset({"battery", "box"})


def test_unknown_eligibility_never_becomes_failure():
    assert match_status_for("ELIGIBLE") == "MATCHED"
    assert match_status_for("NOT_ELIGIBLE") == "NOT_MATCHED"
    for s in ("INSUFFICIENT_INFORMATION", "REVIEW_REQUIRED", "CONDITIONALLY_ELIGIBLE", "ANALYSIS_INCOMPLETE", None):
        assert match_status_for(s) == "REVIEW_REQUIRED"


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

def _match(db, seller, tender) -> SellerTenderMatch | None:
    return db.scalar(select(SellerTenderMatch).where(SellerTenderMatch.seller_id == seller.id,
                                                     SellerTenderMatch.tender_id == tender.id))


def _reasons(m: SellerTenderMatch) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for r in json.loads(m.reasons_json):
        out.setdefault(r["kind"], []).append(f'{r["requirement_type"]}: {r["detail"]}')
    return out


def _run(db, **kw):
    return MatchingService(db).recalculate(now=utcnow(), **kw)


@pytest.mark.parametrize("profile,expected,kinds", [
    (dict(), "MATCHED", {"MATCHED": ["RELEVANCE", "TURNOVER", "EXPERIENCE", "ISO"]}),
    (dict(turnover=1_000_000.0), "NOT_MATCHED", {"FAILED": ["TURNOVER"]}),              # turnover not satisfied
    (dict(turnover=None), "REVIEW_REQUIRED", {"REVIEW": ["TURNOVER"]}),                 # turnover unknown
    (dict(years=1.0), "NOT_MATCHED", {"FAILED": ["EXPERIENCE"]}),                       # experience failed
    (dict(iso=False), "REVIEW_REQUIRED", {"REVIEW": ["ISO"]}),                          # certificate missing
    (dict(turnover=1_000_000.0, years=1.0, iso=False), "NOT_MATCHED",
     {"FAILED": ["TURNOVER", "EXPERIENCE"], "REVIEW": ["ISO"]}),                        # multiple requirements
])
def test_eligibility_outcomes_with_reasons(db, profile, expected, kinds):
    tender = make_tender(db, bid="GEM/2026/B/8800001")
    seller = make_seller(db, name="S", **profile)
    stats = _run(db)
    assert stats.evaluated == 1 and stats.errors == 0
    m = _match(db, seller, tender)
    assert m.match_status == expected and m.relevance_status == "RELEVANT"
    reasons = _reasons(m)
    for kind, types in kinds.items():
        got = [r.split(":")[0] for r in reasons.get(kind, [])]
        for t in types:
            assert t in got, (kind, t, reasons)
    if expected == "NOT_MATCHED":
        assert any("Seller" in r for r in reasons["FAILED"])          # reason names the seller fact


def test_oem_authorization_unknown_is_review_required(db):
    tender = make_tender(db, bid="GEM/2026/B/8800002", fields={"oem_authorization_required": ("TRUE", None)})
    seller = make_seller(db, name="NoOEM")
    _run(db)
    m = _match(db, seller, tender)
    assert m.match_status == "REVIEW_REQUIRED"
    assert any("OEM" in r and "sufficient evidence" in r for r in _reasons(m)["REVIEW"])
    explicit_no = make_seller(db, name="ExplicitNo", oem=False)
    _run(db)
    assert _match(db, explicit_no, tender).match_status == "NOT_MATCHED"


def test_irrelevant_seller_gets_no_match_and_no_eligibility_run(db):
    tender = make_tender(db, bid="GEM/2026/B/8800003")
    seller = make_seller(db, name="Chairs", terms="Office Chair")
    stats = _run(db)
    assert _match(db, seller, tender) is None and stats.evaluated == 0
    assert db.scalar(select(func.count()).select_from(EligibilityRun)) == 0


def test_seller_without_terms_is_not_matched_to_everything(db):
    make_tender(db, bid="GEM/2026/B/8800004")
    seller = make_seller(db, name="Empty", terms=None)
    _run(db)
    assert db.scalar(select(func.count()).select_from(SellerTenderMatch)
                     .where(SellerTenderMatch.seller_id == seller.id)) == 0


def test_many_sellers_one_tender_and_idempotent_rerun(db):
    tender = make_tender(db, bid="GEM/2026/B/8800005")
    sellers = [make_seller(db, name=f"S{i}", turnover=10_000_000.0 * (i + 1)) for i in range(5)]
    first = _run(db)
    assert first.evaluated == 5 and first.sellers_considered == 5
    statuses = [_match(db, s, tender).match_status for s in sellers]
    assert statuses == ["NOT_MATCHED", "MATCHED", "MATCHED", "MATCHED", "MATCHED"]   # needs >= 2 crore
    again = _run(db)
    assert again.evaluated == 0 and again.up_to_date == 5                           # nothing changed
    assert db.scalar(select(func.count()).select_from(SellerTenderMatch)) == 5      # no duplicates


def test_profile_change_recalculates_only_that_seller(db):
    tender = make_tender(db, bid="GEM/2026/B/8800006")
    a = make_seller(db, name="A", years=1.0)
    b = make_seller(db, name="B")
    _run(db)
    assert _match(db, a, tender).match_status == "NOT_MATCHED"
    rev = new_revision(db, a, changes={"years_of_experience": ("NUMBER", None, 4.0)})
    stats = _run(db)
    assert stats.evaluated == 1 and stats.up_to_date == 1     # B untouched
    m = _match(db, a, tender)
    assert m.match_status == "MATCHED" and m.seller_revision_id == rev.id
    assert _match(db, b, tender).match_status == "MATCHED"


def test_profile_change_can_remove_relevance(db):
    tender = make_tender(db, bid="GEM/2026/B/8800007")
    s = make_seller(db, name="Pivot")
    _run(db)
    new_revision(db, s, changes={"product_category": ("TEXT", "Office Chair", None)})
    stats = _run(db)
    m = _match(db, s, tender)
    assert stats.marked_not_relevant == 1
    assert (m.relevance_status, m.match_status) == ("NOT_RELEVANT", "NOT_MATCHED")


def test_tender_change_recalculates_affected_matches(db):
    tender = make_tender(db, bid="GEM/2026/B/8800008")
    s = make_seller(db, name="T", turnover=25_000_000.0)
    _run(db)
    assert _match(db, s, tender).match_status == "MATCHED"
    # Amendment: turnover requirement raised to 3 crore; the tender's analysed state changes
    fv = db.scalar(select(TenderFieldValue).where(TenderFieldValue.tender_id == tender.id,
                                                  TenderFieldValue.field_name == "turnover_required"))
    fv.value_number = 30_000_000.0
    t = db.get(Tender, tender.id)
    t.source_fingerprint = "fp-amended"
    db.commit()
    stats = _run(db)
    assert stats.evaluated == 1
    assert _match(db, s, tender).match_status == "NOT_MATCHED"


def test_closed_and_cancelled_tenders_are_not_matched(db):
    closed = make_tender(db, bid="GEM/2026/B/8800009", deadline_days=-1)
    cancelled = make_tender(db, bid="GEM/2026/B/8800010", source_status="CANCELLED")
    s = make_seller(db, name="X")
    stats = _run(db)
    assert stats.tenders_considered == 0
    assert _match(db, s, closed) is None and _match(db, s, cancelled) is None


def test_tender_expiry_hides_but_keeps_history(db):
    tender = make_tender(db, bid="GEM/2026/B/8800011", deadline_days=0.0005)   # ~40 seconds
    s = make_seller(db, name="H")
    _run(db)
    assert _match(db, s, tender) is not None
    from datetime import timedelta
    verify_statuses(db, now=utcnow() + timedelta(minutes=5))
    db.commit()
    assert db.get(Tender, tender.id).current_status == "CLOSED"
    assert _match(db, s, tender) is not None          # historical result kept, not deleted


def test_analysis_incomplete_is_review_not_failure(db):
    tender = make_tender(db, bid="GEM/2026/B/8800012", fields={})
    from app.database.models import DocumentReferenceScan
    for scan in db.scalars(select(DocumentReferenceScan)).all():
        scan.status = "PENDING"                         # corpus not complete yet
    db.commit()
    s = make_seller(db, name="I")
    _run(db)
    m = _match(db, s, tender)
    assert m.match_status == "REVIEW_REQUIRED" and m.failed_count == 0


def test_matching_never_calls_an_ai_provider(db):
    make_tender(db, bid="GEM/2026/B/8800013")
    for i in range(3):
        make_seller(db, name=f"N{i}")
    _run(db)
    assert db.scalar(select(func.count()).select_from(AIProviderCall)) == 0


def test_evaluation_budget_defers_and_resumes(db):
    for i in range(3):
        make_tender(db, bid=f"GEM/2026/B/88001{i:02d}")
    make_seller(db, name="Budget")
    first = _run(db, max_evaluations=2)
    assert (first.evaluated, first.deferred) == (2, 1)
    second = _run(db, max_evaluations=2)
    assert (second.evaluated, second.up_to_date) == (1, 2)
    assert db.scalar(select(func.count()).select_from(SellerTenderMatch)) == 3
    assert {m.matcher_version for m in db.scalars(select(SellerTenderMatch)).all()} == {MATCHER_VERSION}
