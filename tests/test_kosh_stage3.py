from datetime import date
from decimal import Decimal
import pytest
from app.finance.costs import discounting_effective_rate,loan_apr
from app.finance.plan import optimize_levers
from app.finance.forecast import ForecastInputs,simulate
from app.lending.evaluator import criterion_result,evaluate_product
from tests.conftest import sign_in
from tests.matching_factories import make_seller

SUBJECT="eeeeeeee-0000-0000-0000-000000000031"
@pytest.mark.parametrize("kind,value,expected",[("GST_REGISTERED",True,"MATCHED"),("GST_REGISTERED",False,"NOT_MATCHED"),("GST_REGISTERED",None,"REVIEW_REQUIRED"),("UNKNOWN",True,"REVIEW_REQUIRED")])
def test_criterion_states(kind,value,expected):assert criterion_result({"type":kind,"source":{}},{kind:value},as_of=date(2026,10,13))["status"]==expected
def test_stale_and_gem_sahay_review():
    assert criterion_result({"type":"GST_REGISTERED","source":{"as_of_date":"2026-01-01"}},{"GST_REGISTERED":True},as_of=date(2026,10,13))["reason_code"]=="STALE_SOURCE"
    assert evaluate_product({"id":"GEM_SAHAY_PO_FINANCE","criteria":[]},{},as_of=date(2026,10,13))["status"]=="REVIEW_REQUIRED"
def test_decimal_costs():
    assert discounting_effective_rate(10000,200,100,30)==Decimal(300)/Decimal(9700)*Decimal(365)/Decimal(30)
    assert Decimal("0.09")<loan_apr(10000,[(365,11000)])<Decimal("0.11")
def test_optimizer_caps_and_excludes_review():
    method,lines=optimize_levers(100,[{"product_id":"A","status":"MATCHED","cap":60,"unit_cost":.01,"rate":Decimal(".01"),"scope":None},{"product_id":"B","status":"MATCHED","cap":60,"unit_cost":.02,"rate":Decimal(".02"),"scope":None},{"product_id":"C","status":"REVIEW_REQUIRED","cap":999,"unit_cost":0,"rate":Decimal(0),"scope":None}]);assert method in {"LINPROG","GREEDY"};assert sum(x["amount"] for x in lines)>=100;assert all(x["amount"]<=x["cap"] and x["product_id"]!="C" for x in lines)

def _timing_case(**kwargs):
    inputs=ForecastInputs(0,({"id":7,"counterparty_id":3,"party":"Buyer","number":"INV-7","direction":"RECEIVABLE","due_date":date(2026,10,26),"amount_paise":1000},),(),(0,),{3:(0,)},(),(),0)
    return simulate(inputs,as_of=date(2026,10,13),n_paths=1,seed=42,include_forecast_sales=False,buffer_paise=0,**kwargs)["weeks"]

def test_partial_collections_reduces_later_invoice_exactly():
    weeks=_timing_case(extra_inflows=[{"date":"2026-10-13","amount_paise":400}],invoice_amount_reductions={7:400})
    assert weeks[0]["expected_inflow_committed_paise"]==400
    assert weeks[2]["expected_inflow_committed_paise"]==600

def test_treds_removes_later_invoice_and_adds_net_proceeds():
    weeks=_timing_case(extra_inflows=[{"date":"2026-10-13","amount_paise":970}],accelerated_invoice_ids={7})
    assert weeks[0]["expected_inflow_committed_paise"]==970
    assert sum(w["expected_inflow_committed_paise"] for w in weeks[1:])==0

def test_timing_levers_conserve_horizon_cash_except_discount_cost():
    base=sum(w["expected_inflow_committed_paise"] for w in _timing_case())
    collections=sum(w["expected_inflow_committed_paise"] for w in _timing_case(extra_inflows=[{"date":"2026-10-13","amount_paise":400}],invoice_amount_reductions={7:400}))
    treds=sum(w["expected_inflow_committed_paise"] for w in _timing_case(extra_inflows=[{"date":"2026-10-13","amount_paise":970}],accelerated_invoice_ids={7}))
    assert collections==base==1000
    assert treds==base-30
def test_financing_routes_authorize(client,db,monkeypatch):
    from app.api.auth import get_token_verifier
    monkeypatch.setenv("SUPABASE_URL","https://kosh-tests.supabase.co");get_token_verifier.cache_clear();owner=make_seller(db,name="Owner",owner_subject=SUBJECT);other=make_seller(db,name="Other",owner_subject="eeeeeeee-0000-0000-0000-000000000032")
    assert client.get(f"/api/kosh/sellers/{owner.id}/financing/options").status_code==401;sign_in(client.app,SUBJECT)
    assert client.get(f"/api/kosh/sellers/{other.id}/financing/options").status_code==403
    response=client.get(f"/api/kosh/sellers/{owner.id}/financing/options");assert response.status_code==200;assert "no provider pays for placement" in response.json()["sort_rule"]
    assert client.post(f"/api/kosh/sellers/{other.id}/plans").status_code==403
