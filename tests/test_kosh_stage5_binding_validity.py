"""Regression tests for binding-plan validity, allocation alignment and proof enforcement.

Asserts:
1. When guaranteed financing is INSUFFICIENT and collections are VALID:
   - overall status remains INSUFFICIENT;
   - real persisted line exists with status == 'INSUFFICIENT';
   - create_from_plan_line raises ValueError('VALID_PLAN_REQUIRED').
2. When binding plan is VALID, stored proof, costs and lines match binding allocation
   even when expected collections allocation differs.
3. In target_scope == 'ALL_WEEKS', action creation proof verifies every week <= target.
4. NBFC baseline comparison excludes collections.
"""
from decimal import Decimal
from datetime import date
import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.finance.plan import propose_plan
from app.actions.planner import create_from_plan_line
from app.database.models import SellerRevision, SellerAttribute
from app.database.kosh_models import (
    KoshPlan,
    KoshPlanLine,
    KoshInvoice,
    KoshCounterparty,
)
from tests.matching_factories import make_seller
from tests.conftest import sign_in


@pytest.fixture(autouse=True)
def configure_kosh_env(monkeypatch):
    monkeypatch.setenv("KOSH_AS_OF_DATE", "2026-10-13")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_binding_status_insufficient_when_guaranteed_fails_but_collections_pass(client, db, monkeypatch):
    """Collections-only VALID must not make the binding status VALID.

    Scenario: A seller with a cash shortfall has small TReDS capacity that cannot
    close the gap, but large Collections capacity that can.
    - Guaranteed plan: INSUFFICIENT
    - Expected plan: VALID
    - Overall plan: INSUFFICIENT
    - Persisted lines: 1 real line with status == 'INSUFFICIENT'
    - Action gate: raises ValueError('VALID_PLAN_REQUIRED')
    """
    monkeypatch.setenv("KOSH_AS_OF_DATE", "2026-10-13")

    subject = "eeeeeeee-0000-0000-0000-binding-test1"
    seller = make_seller(db, name="BindingGuard Seller", owner_subject=subject)

    party_treds = KoshCounterparty(
        seller_id=seller.id, name="Buyer BG TReDS", kind="CUSTOMER", treds_onboarded=True,
    )
    party_regular = KoshCounterparty(
        seller_id=seller.id, name="Buyer BG Regular", kind="CUSTOMER", treds_onboarded=False,
    )
    db.add_all([party_treds, party_regular])
    db.flush()

    rev = db.query(SellerRevision).filter_by(seller_id=seller.id, is_active=True).one()
    db.add(SellerAttribute(revision_id=rev.id, key="cash_buffer_paise", value_type="NUMBER", value_number=10_000_000))
    db.commit()

    # TReDS invoice (guaranteed capacity: 2,000,000 paise).
    # 2M < 10M buffer, so guaranteed plan alone CANNOT close the shortfall.
    inv_treds = KoshInvoice(
        seller_id=seller.id, counterparty_id=party_treds.id, direction="RECEIVABLE",
        invoice_number="INV-BG-TREDS", invoice_date=date(2026, 10, 1),
        due_date=date(2026, 11, 20), amount_paise=2_000_000, status="OPEN",
        accepted_by_buyer=True,
    )
    db.add(inv_treds)

    # Collection invoice on non-TReDS buyer (due in 7 days, <=30 days).
    # 30M invoice gives 15M collections capacity > 10M buffer, closing the shortfall.
    inv_col = KoshInvoice(
        seller_id=seller.id, counterparty_id=party_regular.id, direction="RECEIVABLE",
        invoice_number="INV-BG-COL-1", invoice_date=date(2026, 10, 1),
        due_date=date(2026, 10, 20), amount_paise=30_000_000, status="OPEN",
        accepted_by_buyer=True,
    )
    db.add(inv_col)
    db.commit()

    sign_in(client.app, subject)
    prefix = f"/api/kosh/sellers/{seller.id}"
    assert client.post(prefix + "/forecast/run", json={"n_paths": 10, "seed": 42, "include_forecast_sales": False}).status_code == 200
    assert client.post(prefix + "/financing/evaluate").status_code == 200

    plan = propose_plan(db, seller.id, target_prob=Decimal(".20"), target_scope="ALERT_WEEK", persist=True)
    db.commit()

    g_status = plan.planning_details["guaranteed_status"]
    e_status = plan.planning_details["expected_plan"]["status"]
    overall = plan.status

    # Unconditional status checks: guaranteed fails, collections pass, overall stays INSUFFICIENT
    assert g_status == "INSUFFICIENT"
    assert e_status == "VALID"
    assert overall == "INSUFFICIENT"

    # Persisted lines check: real line exists representing the binding allocation
    lines = db.scalars(select(KoshPlanLine).where(KoshPlanLine.plan_id == plan.id)).all()
    assert len(lines) == 1
    line = lines[0]
    assert line.product_id == "TREDS_INVOICE_DISCOUNTING"
    assert line.amount_paise == 2_000_000
    assert line.status == "INSUFFICIENT"

    # Action creation gate check: must reject non-VALID plan
    with pytest.raises(ValueError, match="VALID_PLAN_REQUIRED"):
        create_from_plan_line(db, seller_id=seller.id, plan_line_id=line.id, creator_id=1)


def test_binding_plan_amounts_and_costs_match_guaranteed_allocation(client, db, monkeypatch):
    """When a plan is VALID, stored proof, costs and lines match the guaranteed allocation.

    Even when the expected plan includes zero-cost collections levers, the executable
    financing allocation, total cost, after_probabilities and persisted KoshPlanLine rows
    must consistently represent the financing-only binding plan.
    """
    monkeypatch.setenv("KOSH_AS_OF_DATE", "2026-10-13")

    subject = "eeeeeeee-0000-0000-0000-binding-test2"
    seller = make_seller(db, name="BindingValid Seller", owner_subject=subject)

    party_treds = KoshCounterparty(
        seller_id=seller.id, name="Buyer BV TReDS", kind="CUSTOMER", treds_onboarded=True,
    )
    party_regular = KoshCounterparty(
        seller_id=seller.id, name="Buyer BV Regular", kind="CUSTOMER", treds_onboarded=False,
    )
    db.add_all([party_treds, party_regular])
    db.flush()

    rev = db.query(SellerRevision).filter_by(seller_id=seller.id, is_active=True).one()
    db.add(SellerAttribute(revision_id=rev.id, key="cash_buffer_paise", value_type="NUMBER", value_number=10_000_000))
    db.commit()

    # Large TReDS invoice (guaranteed capacity: 15,000,000 paise > 10,000,000 buffer)
    inv_treds = KoshInvoice(
        seller_id=seller.id, counterparty_id=party_treds.id, direction="RECEIVABLE",
        invoice_number="INV-BV-TREDS", invoice_date=date(2026, 10, 1),
        due_date=date(2026, 11, 20), amount_paise=15_000_000, status="OPEN",
        accepted_by_buyer=True,
    )
    db.add(inv_treds)

    # Collection invoice on non-TReDS buyer
    inv_col = KoshInvoice(
        seller_id=seller.id, counterparty_id=party_regular.id, direction="RECEIVABLE",
        invoice_number="INV-BV-COL-1", invoice_date=date(2026, 10, 1),
        due_date=date(2026, 10, 20), amount_paise=20_000_000, status="OPEN",
        accepted_by_buyer=True,
    )
    db.add(inv_col)
    db.commit()

    sign_in(client.app, subject)
    prefix = f"/api/kosh/sellers/{seller.id}"
    assert client.post(prefix + "/forecast/run", json={"n_paths": 10, "seed": 42, "include_forecast_sales": False}).status_code == 200
    assert client.post(prefix + "/financing/evaluate").status_code == 200

    plan = propose_plan(db, seller.id, target_prob=Decimal(".20"), target_scope="ALERT_WEEK", persist=True)
    db.commit()

    g_status = plan.planning_details["guaranteed_status"]
    e_status = plan.planning_details["expected_plan"]["status"]
    assert g_status == "VALID"
    assert e_status == "VALID"
    assert plan.status == "VALID"

    # Cost and probabilities must match guaranteed allocation, NOT expected plan
    assert plan.total_cost_paise == plan.planning_details["guaranteed_total_cost_paise"]
    assert plan.total_cost_paise > 0
    assert plan.after_probabilities == plan.planning_details["guaranteed_plan"]["after_probabilities"]

    # Persisted lines must be financing-only (no collections push)
    lines = db.scalars(select(KoshPlanLine).where(KoshPlanLine.plan_id == plan.id)).all()
    assert len(lines) == 1
    line = lines[0]
    assert line.product_id == "TREDS_INVOICE_DISCOUNTING"
    assert line.status == "VALID"
    assert line.cost_paise == plan.total_cost_paise
    assert all(l.product_id != "COLLECTIONS_PUSH" for l in lines)


def test_all_weeks_action_proof_checks_every_week(client, db, monkeypatch):
    """In ALL_WEEKS scope, create_from_plan_line must verify all weeks <= target_probability."""
    monkeypatch.setenv("KOSH_AS_OF_DATE", "2026-10-13")

    subject = "eeeeeeee-0000-0000-0000-binding-test3"
    seller = make_seller(db, name="ProofCheck Seller", owner_subject=subject)

    party = KoshCounterparty(
        seller_id=seller.id, name="Buyer PC", kind="CUSTOMER", treds_onboarded=True,
    )
    db.add(party)
    db.flush()

    rev = db.query(SellerRevision).filter_by(seller_id=seller.id, is_active=True).one()
    db.add(SellerAttribute(revision_id=rev.id, key="cash_buffer_paise", value_type="NUMBER", value_number=10_000_000))
    db.commit()

    inv = KoshInvoice(
        seller_id=seller.id, counterparty_id=party.id, direction="RECEIVABLE",
        invoice_number="INV-PC-1", invoice_date=date(2026, 10, 1),
        due_date=date(2026, 11, 20), amount_paise=15_000_000, status="OPEN",
        accepted_by_buyer=True,
    )
    db.add(inv)
    db.commit()

    sign_in(client.app, subject)
    prefix = f"/api/kosh/sellers/{seller.id}"
    assert client.post(prefix + "/forecast/run", json={"n_paths": 10, "seed": 42, "include_forecast_sales": False}).status_code == 200
    assert client.post(prefix + "/financing/evaluate").status_code == 200

    plan = propose_plan(db, seller.id, target_prob=Decimal(".20"), target_scope="ALL_WEEKS", persist=True)
    db.commit()

    lines = db.scalars(select(KoshPlanLine).where(KoshPlanLine.plan_id == plan.id)).all()
    assert len(lines) >= 1
    line = lines[0]

    # Test Case 1: When a non-alert week exceeds the target_probability in ALL_WEEKS mode,
    # action creation must raise PLAN_PROOF_INVALID even if the alert week is below target.
    original_probs = list(plan.after_probabilities)
    tampered_probs = list(original_probs)
    tampered_probs[4] = 0.25  # Week 5 exceeds 0.20 target, but is below 0.50 threshold
    plan.after_probabilities = tampered_probs
    db.commit()

    with pytest.raises(ValueError, match="PLAN_PROOF_INVALID"):
        create_from_plan_line(db, seller_id=seller.id, plan_line_id=line.id, creator_id=1)

    # Test Case 2: When all weeks are <= target_probability, verification passes
    valid_probs = [0.10] * len(original_probs)
    plan.after_probabilities = valid_probs
    db.commit()

    # Must not raise PLAN_PROOF_INVALID (may succeed or raise later date/module check, but not proof)
    try:
        create_from_plan_line(db, seller_id=seller.id, plan_line_id=line.id, creator_id=1)
        passed_proof = True
    except ValueError as e:
        passed_proof = (str(e) != "PLAN_PROOF_INVALID")
    assert passed_proof, "Proof verification should pass when all weeks <= target_probability"


def test_nbfc_baseline_excludes_collections(client, db, monkeypatch):
    """The NBFC comparison baseline must not include COLLECTIONS_PUSH levers."""
    monkeypatch.setenv("KOSH_AS_OF_DATE", "2026-10-13")

    subject = "eeeeeeee-0000-0000-0000-baseline-test"
    seller = make_seller(db, name="BaselineCheck Seller", owner_subject=subject)
    party = KoshCounterparty(
        seller_id=seller.id, name="Buyer BL", kind="CUSTOMER", treds_onboarded=True,
    )
    db.add(party)
    db.flush()

    inv = KoshInvoice(
        seller_id=seller.id, counterparty_id=party.id, direction="RECEIVABLE",
        invoice_number="INV-BL-1", invoice_date=date(2026, 10, 1),
        due_date=date(2026, 11, 20), amount_paise=500_000, status="OPEN",
        accepted_by_buyer=True,
    )
    db.add(inv)
    db.commit()

    sign_in(client.app, subject)
    prefix = f"/api/kosh/sellers/{seller.id}"
    assert client.post(prefix + "/forecast/run", json={"n_paths": 10, "seed": 42, "include_forecast_sales": False}).status_code == 200
    assert client.post(prefix + "/financing/evaluate").status_code == 200

    plan_data = propose_plan(db, seller.id, target_prob=Decimal(".20"), persist=False)

    baseline_lines = plan_data.get("planning_details", {}).get("baseline_lines", [])
    baseline_product_ids = {line["product_id"] for line in baseline_lines}
    assert "COLLECTIONS_PUSH" not in baseline_product_ids, (
        "NBFC baseline must not include COLLECTIONS_PUSH; got: " + str(baseline_product_ids)
    )
    for pid in baseline_product_ids:
        assert pid == "NBFC_UNSECURED_BUSINESS_LOAN", (
            f"Unexpected product {pid} in NBFC baseline"
        )
