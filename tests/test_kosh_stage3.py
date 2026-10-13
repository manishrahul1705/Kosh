from datetime import date
from decimal import Decimal
import pytest
from app.finance.costs import discounting_effective_rate,loan_apr
from app.finance.plan import optimize_levers
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
def test_financing_routes_authorize(client,db,monkeypatch):
    from app.api.auth import get_token_verifier
    monkeypatch.setenv("SUPABASE_URL","https://kosh-tests.supabase.co");get_token_verifier.cache_clear();owner=make_seller(db,name="Owner",owner_subject=SUBJECT);other=make_seller(db,name="Other",owner_subject="eeeeeeee-0000-0000-0000-000000000032")
    assert client.get(f"/api/kosh/sellers/{owner.id}/financing/options").status_code==401;sign_in(client.app,SUBJECT)
    assert client.get(f"/api/kosh/sellers/{other.id}/financing/options").status_code==403
    response=client.get(f"/api/kosh/sellers/{owner.id}/financing/options");assert response.status_code==200;assert "no provider pays for placement" in response.json()["sort_rule"]
    assert client.post(f"/api/kosh/sellers/{other.id}/plans").status_code==403
