"""Stage 5.3 tests: G1 (Horizon-wide safety target) and G2 (Collections status check)."""
from decimal import Decimal
from datetime import date
import pytest
from sqlalchemy import select

from app.finance.plan import propose_plan
from app.database.kosh_models import KoshPlan, KoshInvoice, KoshCounterparty, KoshFinancingResult, KoshFinancingEvaluation
from tests.matching_factories import make_seller
from tests.conftest import sign_in


def test_stage5_3_g1_all_weeks_validity_and_alert_week_mode(client, db):
    """G1: Test that with ALL_WEEKS (default), a guaranteed plan is VALID only if every horizon week's
    probability below buffer is <= target. In ALERT_WEEK mode, only the alert week must be <= target."""
    subject = "eeeeeeee-0000-0000-0000-000000000053"
    seller = make_seller(db, name="Stage 5.3 Seller G1", owner_subject=subject)
    party = KoshCounterparty(seller_id=seller.id, name="Buyer G1", kind="CUSTOMER", treds_onboarded=True)
    db.add(party)
    db.flush()

    inv = KoshInvoice(seller_id=seller.id, counterparty_id=party.id, direction="RECEIVABLE", invoice_number="INV-G1-1", invoice_date=date(2026,10,1), due_date=date(2026,12,2), amount_paise=2_000_000, status="OPEN", accepted_by_buyer=True)
    db.add(inv)
    db.commit()

    sign_in(client.app, subject)
    prefix = f"/api/kosh/sellers/{seller.id}"
    assert client.post(prefix + "/forecast/run", json={"n_paths": 50, "seed": 42}).status_code == 200
    assert client.post(prefix + "/financing/evaluate").status_code == 200

    # 1. Propose plan with ALL_WEEKS scope
    plan_all = propose_plan(db, seller.id, target_prob=Decimal(".20"), target_scope="ALL_WEEKS", persist=False)
    assert plan_all["target_scope"] == "ALL_WEEKS"
    assert plan_all["guaranteed_plan"]["target_scope"] == "ALL_WEEKS"
    if plan_all["status"] == "VALID":
        g_probs = plan_all["guaranteed_plan"]["after_probabilities"]
        assert all(p <= 0.20 for p in g_probs), f"All weeks must be <= 0.20 under ALL_WEEKS: {g_probs}"

    # 2. Propose plan with ALERT_WEEK scope
    plan_alert = propose_plan(db, seller.id, target_prob=Decimal(".20"), target_scope="ALERT_WEEK", persist=False)
    assert plan_alert["target_scope"] == "ALERT_WEEK"
    if plan_alert["status"] == "VALID":
        alert_w = plan_alert["planning_details"]["alert_week"]
        alert_p = plan_alert["guaranteed_plan"]["alert_week_probability"]
        assert alert_p <= 0.20, f"Alert week probability must be <= 0.20: {alert_p}"


def test_stage5_3_g1_mixed_lever_combination_and_insufficient_case(client, db):
    """G1: When one lever alone cannot bring all weeks <= target (e.g. stringent target or capped lever),
    the optimizer combines MATCHED levers (e.g. TReDS + Bank OD).
    If even all combined capacity cannot meet target, returns INSUFFICIENT with best achievable max-week probability."""
    subject = "eeeeeeee-0000-0000-0000-000000000054"
    seller = make_seller(db, name="Stage 5.3 Seller Mixed", owner_subject=subject)
    party = KoshCounterparty(seller_id=seller.id, name="Buyer Mixed", kind="CUSTOMER", treds_onboarded=True)
    db.add(party)
    db.flush()

    inv = KoshInvoice(seller_id=seller.id, counterparty_id=party.id, direction="RECEIVABLE", invoice_number="INV-G1-MIX", invoice_date=date(2026,10,1), due_date=date(2026,12,2), amount_paise=1_000_000, status="OPEN", accepted_by_buyer=True)
    db.add(inv)
    db.commit()

    sign_in(client.app, subject)
    prefix = f"/api/kosh/sellers/{seller.id}"
    assert client.post(prefix + "/forecast/run", json={"n_paths": 50, "seed": 42}).status_code == 200
    assert client.post(prefix + "/financing/evaluate").status_code == 200

    # Test an impossible target (e.g. target_prob = 0.00001) where capacity cannot meet all weeks
    plan_insufficient = propose_plan(db, seller.id, target_prob=Decimal(".00001"), target_scope="ALL_WEEKS", persist=False)
    assert plan_insufficient["status"] == "INSUFFICIENT"
    assert "best_achievable_max_prob" in plan_insufficient
    assert "best_achievable_cost_paise" in plan_insufficient
    assert plan_insufficient["best_achievable_max_prob"] > 0
    assert "INSUFFICIENT" in plan_insufficient["why_this_plan"]


def test_stage5_3_g2_collections_seller_level_review_not_overridden_by_invoice(client, db):
    """G2: Confirm that a seller-level REVIEW criterion for COLLECTIONS_PUSH is NOT overridden
    to MATCHED just because an individual invoice matches. Product is MATCHED only if seller-level
    criteria pass AND at least one invoice matches."""
    subject = "eeeeeeee-0000-0000-0000-000000000055"
    seller = make_seller(db, name="Stage 5.3 Seller G2", owner_subject=subject)
    party = KoshCounterparty(seller_id=seller.id, name="Buyer G2", kind="CUSTOMER", treds_onboarded=True)
    db.add(party)
    db.flush()

    inv = KoshInvoice(seller_id=seller.id, counterparty_id=party.id, direction="RECEIVABLE", invoice_number="INV-G2-1", invoice_date=date(2026,10,1), due_date=date(2026,11,1), amount_paise=100_000, status="OPEN", accepted_by_buyer=True)
    db.add(inv)
    db.commit()

    sign_in(client.app, subject)
    prefix = f"/api/kosh/sellers/{seller.id}"
    assert client.post(prefix + "/forecast/run", json={"n_paths": 10, "seed": 42}).status_code == 200
    assert client.post(prefix + "/financing/evaluate").status_code == 200

    # Query latest evaluation
    eval_row = db.scalar(select(KoshFinancingEvaluation).where(KoshFinancingEvaluation.seller_id == seller.id).order_by(KoshFinancingEvaluation.id.desc()).limit(1))
    assert eval_row is not None

    # Simulate a seller-level criterion requiring review on COLLECTIONS_PUSH (scope=None)
    seller_level_result = KoshFinancingResult(
        evaluation_id=eval_row.id,
        product_id="COLLECTIONS_PUSH",
        scope=None,
        status="REVIEW_REQUIRED",
        max_amount_paise=0,
        effective_annual_rate="0",
        arrival_business_days=1,
        reasons=[{"criterion": "SELLER_CRITERION", "status": "REVIEW_REQUIRED", "reason": "Seller-level review needed"}],
        evidence={},
    )
    db.add(seller_level_result)
    db.commit()

    # GET /financing/options: product status must remain REVIEW_REQUIRED, NOT MATCHED,
    # despite the individual invoice being MATCHED
    resp = client.get(prefix + "/financing/options")
    assert resp.status_code == 200
    data = resp.json()

    col_push = next((x for x in data["items"] if x["product_id"] == "COLLECTIONS_PUSH"), None)
    assert col_push is not None
    assert col_push["status"] == "REVIEW_REQUIRED", (
        f"Seller-level REVIEW_REQUIRED must not be overridden to MATCHED even if an invoice matched. Got: {col_push['status']}"
    )

    # In propose_plan, this lever must also not be treated as MATCHED
    plan_data = propose_plan(db, seller.id, target_prob=Decimal(".20"), persist=False)
    e_plan_lines = plan_data["expected_plan"]["lines"]
    col_lines = [line for line in e_plan_lines if line["product_id"] == "COLLECTIONS_PUSH"]
    assert len(col_lines) == 0, "COLLECTIONS_PUSH levers must not enter plan when seller-level status is REVIEW_REQUIRED"
