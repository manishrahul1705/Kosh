"""Offline correctness contracts for financing evidence, cash costs and plans."""
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.finance.costs import financing_quote
from app.finance.forecast import ForecastInputs, simulate
from app.finance.plan import optimize_levers, plan_scenario, validate_and_complete, propose_plan
from app.lending.catalogue import load_catalogue
from app.lending.evaluator import criterion_result, evaluate_product
from app.database.kosh_models import KoshFinancingEvaluation, KoshFinancingResult, KoshForecastRun, KoshPlanLine
from app.database.auth_models import AppUser, SellerMembership
from tests.conftest import sign_in
from tests.matching_factories import make_seller

AS_OF = date(2026, 10, 13)
SUBJECT = "eeeeeeee-0000-0000-0000-000000000031"
PRODUCTS = {p["id"]: p for p in load_catalogue()}
BOOL_TYPES = ["UDYAM_REGISTERED", "UDYAM_CERTIFICATE_PRESENT", "GST_REGISTERED",
              "BUYER_TREDS_ONBOARDED", "INVOICE_ACCEPTED", "INVOICE_NOT_OVERDUE",
              "DOCUMENT_PRESENT", "NON_CORPORATE", "NON_FARM", "INCOME_GENERATING",
              "MICRO_SMALL_ENTERPRISE", "TARUN_AVAILED_AND_REPAID"]
CASES = [(kind, {}, True, False) for kind in BOOL_TYPES] + [
    ("UDYAM_CATEGORY_IN", {"values": ["SMALL"]}, "SMALL", "MEDIUM"),
    ("BUSINESS_VINTAGE_MIN_MONTHS", {"value": 12}, 12, 11),
    ("TURNOVER_RANGE", {"min": 100, "max": 200}, 100, 201),
    ("AMOUNT_WITHIN_LIMIT", {"max": 100}, 100, 101),
    ("LIMIT_HEADROOM_MIN", {"value": 100}, 100, 99),
    ("RECEIVABLE_OVERDUE_OR_DUE_WITHIN_DAYS", {"days": 30}, 30, 31),
    ("SUPPLIER_RELATIONSHIP_MIN_MONTHS", {"value": 12}, 12, 11),
    ("SUPPLIER_ON_TIME_RATIO_MIN", {"value": .9}, .9, .89),
    ("MUDRA_CATEGORY_AMOUNT", {"category": "Tarun Plus", "min_exclusive": 100_000_000, "max": 200_000_000}, 200_000_000, 200_000_001),
]


@pytest.mark.parametrize("kind,clause,passing,failing", CASES)
@pytest.mark.parametrize("state", ["pass", "fail", "unknown"])
def test_each_criterion_tri_state(kind, clause, passing, failing, state):
    key = "AMOUNT_WITHIN_LIMIT" if kind == "MUDRA_CATEGORY_AMOUNT" else kind
    facts = {"AMOUNT_WITHIN_LIMIT": 150_000_000, key: {"pass": passing, "fail": failing, "unknown": None}[state]}
    result = criterion_result({"type": kind, **clause}, facts, as_of=AS_OF)
    assert result["status"] == {"pass": "MATCHED", "fail": "NOT_MATCHED", "unknown": "REVIEW_REQUIRED"}[state]


@pytest.mark.parametrize("source", [{"as_of_date": "2026-01-01"}, {"verified_on": "2026-01-01"}, {"verified_on": "invalid"}, {"verified_on": "2027-01-01"}])
def test_source_needs_review(source):
    assert criterion_result({"type": "GST_REGISTERED", "source": source}, {"GST_REGISTERED": True}, as_of=AS_OF)["status"] == "REVIEW_REQUIRED"


def test_unknown_type_and_missing_evidence_review():
    assert criterion_result({"type": "NEW_UNSUPPORTED"}, {"NEW_UNSUPPORTED": True}, as_of=AS_OF)["status"] == "REVIEW_REQUIRED"
    assert criterion_result({"type": "GST_REGISTERED"}, {}, as_of=AS_OF)["status"] == "REVIEW_REQUIRED"


@pytest.mark.parametrize("evidence", [True, False, None])
def test_gem_sahay_always_review(evidence):
    result = evaluate_product(PRODUCTS["GEM_SAHAY_PO_FINANCE"], {"DOCUMENT_PRESENT": evidence}, as_of=AS_OF)
    assert result["status"] == "REVIEW_REQUIRED"
    assert "routing" not in str(result).lower()


def test_supplier_missing_evidence_stays_review():
    product = PRODUCTS["SUPPLIER_TERM_EXTENSION"]
    assert evaluate_product(product, {}, as_of=AS_OF)["status"] == "REVIEW_REQUIRED"
    for missing in ["SUPPLIER_RELATIONSHIP_MIN_MONTHS", "SUPPLIER_ON_TIME_RATIO_MIN"]:
        facts = {"SUPPLIER_RELATIONSHIP_MIN_MONTHS": 120, "SUPPLIER_ON_TIME_RATIO_MIN": 1}
        facts.pop(missing)
        assert evaluate_product(product, facts, as_of=AS_OF)["status"] == "REVIEW_REQUIRED"


@pytest.mark.parametrize("rupees,category,status", [
    (50_000, "Shishu", "MATCHED"), (50_001, "Kishore", "MATCHED"),
    (500_000, "Kishore", "MATCHED"), (500_001, "Tarun", "MATCHED"),
    (1_000_000, "Tarun", "MATCHED"), (1_000_001, "Tarun Plus", "MATCHED"),
    (2_000_000, "Tarun Plus", "MATCHED"), (2_000_001, None, "NOT_MATCHED"),
])
def test_mudra_category_boundaries(rupees, category, status):
    facts = {kind: True for kind in BOOL_TYPES}
    facts["AMOUNT_WITHIN_LIMIT"] = rupees * 100
    result = evaluate_product(PRODUCTS["MUDRA_LOAN"], facts, as_of=AS_OF)
    assert result["status"] == status
    selected = [r for r in result["reasons"] if r["reason_code"] == "CATEGORY_SELECTED"]
    assert len(selected) == (1 if category else 0)
    if category: assert selected[0]["reason"].startswith(category + ":")
    for criterion in PRODUCTS["MUDRA_LOAN"]["criteria"]:
        assert "mudra.org.in" in criterion["source_url"]
        assert criterion["verified_on"] == "2026-10-13"


def test_tarun_plus_requires_repaid_tarun_and_unknown_is_review():
    facts = {kind: True for kind in BOOL_TYPES}
    facts["AMOUNT_WITHIN_LIMIT"] = 150_000_000
    facts["TARUN_AVAILED_AND_REPAID"] = False
    assert evaluate_product(PRODUCTS["MUDRA_LOAN"], facts, as_of=AS_OF)["status"] == "NOT_MATCHED"
    facts["TARUN_AVAILED_AND_REPAID"] = None
    assert evaluate_product(PRODUCTS["MUDRA_LOAN"], facts, as_of=AS_OF)["status"] == "REVIEW_REQUIRED"
    facts["AMOUNT_WITHIN_LIMIT"] = 100_000_000
    assert evaluate_product(PRODUCTS["MUDRA_LOAN"], facts, as_of=AS_OF)["status"] == "MATCHED"


@pytest.mark.parametrize("product_id", list(PRODUCTS))
def test_effective_rate_from_cash_flows_each_product(product_id):
    product = PRODUCTS[product_id]; amount = 10_000_000
    quote = financing_quote(product, amount); model = product["cost_model"]
    rate = Decimal(quote["effective_annual_rate"]); days = quote["days"]
    assert quote["amount_paise"] == amount
    if product_id in {"COLLECTIONS_PUSH", "SUPPLIER_TERM_EXTENSION"}:
        assert quote["cost_paise"] == 0 and rate == 0
    elif product_id == "TREDS_INVOICE_DISCOUNTING":
        assert abs(rate - Decimal(quote["cost_paise"]) / quote["net_proceeds_paise"] * 365 / days) < Decimal("1e-20")
        assert Decimal(".07") <= Decimal(model["annual_rate"]) <= Decimal(".10")
    else:
        fee = amount - quote["net_proceeds_paise"]
        repayment = Decimal(amount + quote["cost_paise"] - fee)
        assert abs(repayment / (1 + rate) ** (Decimal(days) / 365) - quote["net_proceeds_paise"]) < Decimal("1e-18")


def lever(name, cap, cost, status="MATCHED", **kwargs):
    return {"product_id": name, "cap": cap, "unit_cost": Decimal(str(cost)), "rate": Decimal(str(cost)), "scope": None, "status": status, "arrival_business_days": 0, **kwargs}


def test_caps_exclusions_and_determinism():
    levers = [lever("A", 60, .01), lever("B", 100, .02), lever("C", 999, 0, "REVIEW_REQUIRED"), lever("D", 999, 0, "NOT_MATCHED")]
    first = optimize_levers(100, levers, solver="GREEDY")
    assert first == optimize_levers(100, levers, solver="GREEDY")
    assert [(x["product_id"], x["amount"]) for x in first[1]] == [("A", 60), ("B", 40)]
    assert all(0 < x["amount"] <= x["cap"] for x in first[1])


def test_linprog_and_greedy_agree_on_cost():
    pytest.importorskip("scipy", reason="SciPy is actually unavailable")
    levers = [lever("A", 60, .01, net_factor=Decimal(".9")), lever("B", 100, .02)]
    lp = optimize_levers(100, levers, solver="LINPROG")
    greedy = optimize_levers(100, levers, solver="GREEDY")
    assert lp[0] == "LINPROG"
    assert sum(x["amount"] * x["unit_cost"] for x in lp[1]) == sum(x["amount"] * x["unit_cost"] for x in greedy[1])


def test_validity_loop_extends_and_impossible_is_insufficient():
    calls = []
    def check(lines):
        total = sum(x["amount"] for x in lines); calls.append(total)
        return {"weeks": [{"prob_below_buffer": .5 if total < 90 else .49}]}
    levers = [lever("A", 60, .01), lever("B", 60, .02), lever("C", 999, 0, "REVIEW_REQUIRED")]
    chosen, after, status = validate_and_complete([{**levers[0], "amount": 10}], levers, check, target_week=1, threshold=.5)
    assert calls[0] == 10 and 60 in calls and 120 in calls
    assert status == "PROPOSED" and after["weeks"][0]["prob_below_buffer"] < .5
    assert sum(x["amount"] for x in chosen) == 90
    assert all(x["amount"] <= x["cap"] for x in chosen)
    chosen, after, status = validate_and_complete([], levers[:1], check, target_week=1, threshold=.5)
    assert status == "INSUFFICIENT" and after["weeks"][0]["prob_below_buffer"] >= .5


def test_valid_plan_same_seed_real_forecast_and_partial_invoice_conservation():
    inputs = ForecastInputs(0, ({"id": 7, "counterparty_id": 3, "party": "Buyer", "number": "I", "direction": "RECEIVABLE", "due_date": date(2026, 10, 26), "amount_paise": 1_000_000},), (), (0,), {3: (0,)}, (), (), 0)
    run = SimpleNamespace(as_of_date=AS_OF, n_paths=20, seed=42, include_forecast_sales=False, buffer_paise=400_000)
    item = lever("TREDS_INVOICE_DISCOUNTING", 1_000_000, .03, scope="invoice:7", arrival_business_days=3)
    check = lambda lines: plan_scenario(inputs, run, lines, PRODUCTS)
    chosen, after, status = validate_and_complete([{**item, "amount": 100_000}], [item], check, target_week=1, threshold=.5)
    assert status == "PROPOSED" and after["weeks"][0]["prob_below_buffer"] == 0
    assert (chosen, after, status) == validate_and_complete([{**item, "amount": 100_000}], [item], check, target_week=1, threshold=.5)
    quote = financing_quote(PRODUCTS[item["product_id"]], chosen[0]["amount"])
    assert after["weeks"][2]["expected_inflow_committed_paise"] == 1_000_000 - chosen[0]["amount"]
    assert sum(w["expected_inflow_committed_paise"] for w in after["weeks"]) == 1_000_000 - quote["cost_paise"]


def test_all_financing_routes_authorize_and_options_contract(client, db, monkeypatch):
    from app.api.auth import get_token_verifier
    monkeypatch.setenv("SUPABASE_URL", "https://kosh-tests.supabase.co"); get_token_verifier.cache_clear()
    owner = make_seller(db, name="Hardening owner", owner_subject=SUBJECT)
    other = make_seller(db, name="Hardening other", owner_subject="eeeeeeee-0000-0000-0000-000000000032")
    routes = [("post", "/financing/evaluate"), ("get", "/financing/options"), ("get", "/financing/options/MUDRA_LOAN/explain"), ("post", "/plans"), ("get", "/plans/latest"), ("get", "/plans/1"), ("get", "/plan")]
    for method, suffix in routes:
        assert getattr(client, method)(f"/api/kosh/sellers/{owner.id}{suffix}").status_code == 401
    sign_in(client.app, SUBJECT)
    for method, suffix in routes:
        assert getattr(client, method)(f"/api/kosh/sellers/{other.id}{suffix}").status_code == 403
    assert client.post(f"/api/kosh/sellers/{owner.id}/forecast/run", json={"n_paths": 20, "seed": 42}).status_code == 200
    assert client.post(f"/api/kosh/sellers/{owner.id}/financing/evaluate").status_code == 200
    evaluation = db.scalar(select(KoshFinancingEvaluation).where(KoshFinancingEvaluation.seller_id == owner.id))
    row = db.scalar(select(KoshFinancingResult).where(KoshFinancingResult.evaluation_id == evaluation.id, KoshFinancingResult.product_id == "NBFC_UNSECURED_BUSINESS_LOAN"))
    row.status = "NOT_MATCHED"; db.commit()
    data = client.get(f"/api/kosh/sellers/{owner.id}/financing/options").json()
    assert "no provider pays for placement" in data["sort_rule"] and "effective annual cost" in data["sort_rule"]
    assert len({x["product_id"] for x in data["items"]}) == len(PRODUCTS)
    assert any(x["status"] == "NOT_MATCHED" for x in data["items"])
    assert all({"amount_paise", "days", "cost_paise", "effective_annual_rate"} <= x.keys() for x in data["items"])
    assert next(x for x in data["items"] if x["product_id"] == "BANK_OD_DRAWDOWN")["status"] == "REVIEW_REQUIRED"
    # A plan owned by another seller is hidden even under an authorized seller URL.
    from app.database.kosh_models import KoshPlan
    other_user = db.scalar(select(AppUser).where(AppUser.supabase_user_id == "eeeeeeee-0000-0000-0000-000000000032"))
    other_run = KoshForecastRun(seller_id=other.id, as_of_date=AS_OF, n_paths=1, seed=42, params={}, input_fingerprint="b"*64, include_forecast_sales=False, buffer_paise=1, status="SUCCESS", created_by_user_id=other_user.id)
    db.add(other_run); db.flush()
    foreign_plan = KoshPlan(seller_id=other.id, forecast_run_id=other_run.id, forecast_fingerprint=other_run.input_fingerprint, method="GREEDY", status="INSUFFICIENT", total_cost_paise=0, baseline_cost_paise=0, before_probabilities=[1], after_probabilities=[1])
    db.add(foreign_plan); db.commit()
    assert client.get(f"/api/kosh/sellers/{owner.id}/plans/{foreign_plan.id}").status_code == 404
    user = db.scalar(select(AppUser).where(AppUser.supabase_user_id == SUBJECT))
    membership = db.scalar(select(SellerMembership).where(SellerMembership.user_id == user.id, SellerMembership.seller_id == owner.id))
    membership.role = "VIEWER"; db.commit()
    for suffix in ["/financing/evaluate", "/plans"]:
        assert client.post(f"/api/kosh/sellers/{owner.id}{suffix}").status_code == 403
    assert client.get(f"/api/kosh/sellers/{owner.id}/financing/options").status_code == 200


def test_persisted_impossible_plan_status_and_exclusion(client, db):
    seller = make_seller(db, name="Impossible hardening", owner_subject=SUBJECT)
    sign_in(client.app, SUBJECT)
    client.post(f"/api/kosh/sellers/{seller.id}/forecast/run", json={"n_paths": 20, "seed": 42})
    client.post(f"/api/kosh/sellers/{seller.id}/financing/evaluate")
    plan = propose_plan(db, seller.id); db.flush()
    assert plan.status == "INSUFFICIENT"
    assert db.scalars(select(KoshPlanLine).where(KoshPlanLine.plan_id == plan.id)).all() == []
    assert plan.after_probabilities[0] >= .5
