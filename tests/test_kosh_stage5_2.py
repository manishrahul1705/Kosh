"""Stage 5.2 tests: F1 (Collections vs Review consistency) and F2 (Guaranteed vs Expected cash)."""
from decimal import Decimal
from datetime import date
import pytest
from sqlalchemy import select

from app.finance.plan import propose_plan
from app.database.kosh_models import KoshPlan, KoshInvoice, KoshCounterparty
from tests.matching_factories import make_seller
from tests.conftest import sign_in


def test_stage5_2_f1_multiscope_product_status_matches_candidate_invoices(client, db):
    """F1: Ensure multi-scope product status (COLLECTIONS_PUSH, etc.) is MATCHED if any candidate is MATCHED,
    REVIEW_REQUIRED if none are MATCHED but some are REVIEW_REQUIRED, and NOT_MATCHED otherwise."""
    subject = "eeeeeeee-0000-0000-0000-000000000051"
    seller = make_seller(db, name="Stage 5.2 Seller F1", owner_subject=subject)
    party = KoshCounterparty(seller_id=seller.id, name="Buyer F1", kind="CUSTOMER", treds_onboarded=True)
    db.add(party)
    db.flush()

    inv1 = KoshInvoice(seller_id=seller.id, counterparty_id=party.id, direction="RECEIVABLE", invoice_number="INV-F1-1", invoice_date=date(2026,10,1), due_date=date(2026,11,1), amount_paise=100_000, status="OPEN", accepted_by_buyer=True)
    inv2 = KoshInvoice(seller_id=seller.id, counterparty_id=party.id, direction="RECEIVABLE", invoice_number="INV-F1-2", invoice_date=date(2026,10,1), due_date=date(2026,11,1), amount_paise=200_000, status="REVIEW", accepted_by_buyer=True)
    db.add_all([inv1, inv2])
    db.commit()

    sign_in(client.app, subject)
    prefix = f"/api/kosh/sellers/{seller.id}"
    assert client.post(prefix + "/forecast/run", json={"n_paths": 10, "seed": 42}).status_code == 200
    assert client.post(prefix + "/financing/evaluate").status_code == 200

    resp = client.get(prefix + "/financing/options")
    assert resp.status_code == 200, resp.text
    data = resp.json()

    col_push = next((x for x in data["items"] if x["product_id"] == "COLLECTIONS_PUSH"), None)
    assert col_push is not None
    assert col_push.get("invoice_eligibility") is not None
    # inv1 is MATCHED, inv2 is REVIEW_REQUIRED
    statuses = {x["status"] for x in col_push["invoice_eligibility"]}
    assert "MATCHED" in statuses
    assert "REVIEW_REQUIRED" in statuses
    # Because at least one is MATCHED, product status must be MATCHED (resolving F1 contradiction)
    assert col_push["status"] == "MATCHED", "Product status must be MATCHED when any candidate invoice is MATCHED"


def test_stage5_2_f2_guaranteed_vs_expected_plan_and_target_verification(client, db):
    """F2: A plan produces guaranteed_plan (cash-posting levers only: TReDS, OD, loans) and expected_plan
    (including collections). Validity check against safety target uses the guaranteed figure."""
    subject = "eeeeeeee-0000-0000-0000-000000000052"
    seller = make_seller(db, name="Stage 5.2 Seller F2", owner_subject=subject)
    party = KoshCounterparty(seller_id=seller.id, name="Buyer F2", kind="CUSTOMER", treds_onboarded=True)
    db.add(party)
    db.flush()

    inv = KoshInvoice(seller_id=seller.id, counterparty_id=party.id, direction="RECEIVABLE", invoice_number="INV-F2-1", invoice_date=date(2026,10,1), due_date=date(2026,12,2), amount_paise=500_000, status="OPEN", accepted_by_buyer=True)
    db.add(inv)
    db.commit()

    sign_in(client.app, subject)
    prefix = f"/api/kosh/sellers/{seller.id}"
    assert client.post(prefix + "/forecast/run", json={"n_paths": 10, "seed": 42}).status_code == 200
    assert client.post(prefix + "/financing/evaluate").status_code == 200

    # 1. Propose plan via propose_plan
    plan_data = propose_plan(db, seller.id, target_prob=Decimal(".20"), persist=False)
    assert "guaranteed_plan" in plan_data
    assert "expected_plan" in plan_data
    g_plan = plan_data["guaranteed_plan"]
    e_plan = plan_data["expected_plan"]

    # Guaranteed plan must contain NO collections push or supplier extension
    g_product_ids = {line["product_id"] for line in g_plan["lines"]}
    assert "COLLECTIONS_PUSH" not in g_product_ids
    assert "SUPPLIER_TERM_EXTENSION" not in g_product_ids

    # 2. Persisted plan via API endpoint
    create_resp = client.post(f"{prefix}/plans", json={"target_probability": "0.20"})
    assert create_resp.status_code == 200, create_resp.text
    plan_id = create_resp.json()["plan_id"]

    detail_resp = client.get(f"{prefix}/plans/{plan_id}")
    assert detail_resp.status_code == 200, detail_resp.text
    out = detail_resp.json()

    assert "guaranteed_plan" in out
    assert "expected_plan" in out
    assert out["guaranteed_plan"] is not None
    assert out["expected_plan"] is not None
    assert "guaranteed_status" in out["planning_details"]
    assert "expected_total_cost_paise" in out["planning_details"]

    # Target validity check must use guaranteed status
    if out["planning_details"]["guaranteed_status"] == "VALID":
        assert out["status"] == "VALID"
