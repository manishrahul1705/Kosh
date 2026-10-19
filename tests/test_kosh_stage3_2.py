"""Plan safety target and cost transparency contracts."""
from decimal import Decimal
from datetime import date
from sqlalchemy import select

from app.core.config import Settings
from app.finance.plan import validate_and_complete
from app.finance.forecast import ForecastInputs,simulate
from app.finance.costs import financing_quote
from app.lending.catalogue import load_catalogue
from app.database.kosh_models import KoshForecastRun,KoshForecastWeek,KoshFinancingEvaluation,KoshFinancingResult
from app.database.auth_models import AppUser
from tests.matching_factories import make_seller
import pytest


def lever(cap=100):
    return {"product_id":"BANK_OD_DRAWDOWN","scope":None,"status":"MATCHED","cap":cap,"unit_cost":Decimal(".01")}


def test_default_safety_target_is_separate_from_alert_threshold():
    settings=Settings(_env_file=None)
    assert settings.kosh_plan_target_prob==Decimal(".20")
    assert settings.kosh_alert_threshold==.5


def test_target_is_inclusive_threshold_is_strict_and_every_week_is_checked():
    item=lever()
    def check(lines):
        amount=sum(x["amount"] for x in lines)
        return {"weeks":[{"prob_below_buffer":.2 if amount>=80 else .3},{"prob_below_buffer":.49}]}
    chosen,after,status=validate_and_complete([{**item,"amount":10}],[item],check,target_week=1,threshold=.5,target_prob=Decimal(".2"))
    assert status=="VALID" and chosen[0]["amount"]==80
    assert after["weeks"][0]["prob_below_buffer"]==.2
    def unsafe_horizon(lines):return {"weeks":[{"prob_below_buffer":.1},{"prob_below_buffer":.5}]}
    assert validate_and_complete([], [item],unsafe_horizon,target_week=1,threshold=.5,target_prob=Decimal(".2"))[2]=="INSUFFICIENT"


def test_safety_target_not_alert_threshold_controls_insufficient():
    def check(lines):return {"weeks":[{"prob_below_buffer":.3}]}
    assert validate_and_complete([], [lever()],check,target_week=1,threshold=.5,target_prob=Decimal(".2"))[2]=="INSUFFICIENT"


def test_actual_tenor_changes_cost_and_quote_basis_stays_ninety_days():
    products={p["id"]:p for p in load_catalogue()}
    for product_id in ("TREDS_INVOICE_DISCOUNTING","BANK_OD_DRAWDOWN","NBFC_UNSECURED_BUSINESS_LOAN"):
        short=financing_quote(products[product_id],1_000_000,days=30)
        long=financing_quote(products[product_id],1_000_000,days=90)
        assert short["days"]==30 and short["cost_paise"]<long["cost_paise"]
        assert financing_quote(products[product_id],1_000_000)["days"]==90
    assert (date(2026,12,2)-date(2026,10,16)).days==47


def test_actual_line_dates_drive_discount_cash_flow():
    from types import SimpleNamespace
    from app.finance.plan import plan_scenario
    products={p["id"]:p for p in load_catalogue()}
    inputs=ForecastInputs(0,({"id":7,"counterparty_id":1,"direction":"RECEIVABLE","due_date":date(2026,12,2),"amount_paise":1_000_000},),(),(0,),{},(),(),0)
    run=SimpleNamespace(as_of_date=date(2026,10,13),n_paths=1,seed=42,include_forecast_sales=False,buffer_paise=0)
    line={"product_id":"TREDS_INVOICE_DISCOUNTING","amount":500_000,"scope":"invoice:7","arrival_business_days":3,"days":47}
    result=plan_scenario(inputs,run,[line],products)
    quote=financing_quote(products[line["product_id"]],line["amount"],days=47)
    assert result["weeks"][0]["expected_inflow_committed_paise"]==quote["net_proceeds_paise"]
    assert sum(w["expected_inflow_committed_paise"] for w in result["weeks"])==1_000_000-quote["cost_paise"]


def test_sanctioned_od_draw_has_no_upfront_fee():
    from decimal import ROUND_HALF_UP
    product=next(p for p in load_catalogue() if p["id"]=="BANK_OD_DRAWDOWN")
    for days in (1,30,90):
        quote=financing_quote(product,1_000_000,days=days)
        assert quote["net_proceeds_paise"]==1_000_000
        expected=int((Decimal(1_000_000)*Decimal(".12")*days/365).quantize(Decimal(1),rounding=ROUND_HALF_UP))
        assert quote["cost_paise"]==expected


def test_operational_levers_have_no_invented_financing_tenor():
    for product in load_catalogue():
        if product["id"] in {"COLLECTIONS_PUSH","SUPPLIER_TERM_EXTENSION"}:
            quote=financing_quote(product,100_000,days=0)
            assert quote["days"]==0 and quote["cost_paise"]==0 and quote["effective_annual_rate"]=="0"
        else:
            with pytest.raises(ValueError):financing_quote(product,100_000,days=0)


@pytest.mark.parametrize("kind",["INVOICE_DUE_AFTER_FUNDING","INVOICE_EVIDENCE_VERIFIED","INVOICE_OPEN_AMOUNT_POSITIVE"])
@pytest.mark.parametrize("value,status",[(True,"MATCHED"),(False,"NOT_MATCHED"),(None,"REVIEW_REQUIRED")])
def test_invoice_criterion_tri_state(kind,value,status):
    from app.lending.evaluator import criterion_result
    assert criterion_result({"type":kind},{kind:value},as_of=date(2026,10,13))["status"]==status


def test_every_open_invoice_has_exact_product_reasons(client,db):
    from app.database.kosh_models import KoshCounterparty,KoshInvoice
    from tests.conftest import sign_in
    subject="eeeeeeee-0000-0000-0000-000000000036"
    seller=make_seller(db,name="Invoice eligibility",owner_subject=subject)
    parties=[KoshCounterparty(seller_id=seller.id,name="Onboarded",kind="CUSTOMER",treds_onboarded=True),KoshCounterparty(seller_id=seller.id,name="Not onboarded",kind="CUSTOMER",treds_onboarded=False)]
    db.add_all(parties);db.flush()
    cases=[("GOOD",0,date(2026,11,1),True,"OPEN"),("BUYER",1,date(2026,11,1),True,"OPEN"),("UNACCEPTED",0,date(2026,11,1),False,"OPEN"),("OVERDUE",0,date(2026,10,12),True,"OPEN"),("TOO_EARLY",0,date(2026,10,14),True,"OPEN"),("OUTSIDE",0,date(2026,12,20),True,"OPEN"),("REVIEW",0,date(2026,11,1),True,"REVIEW")]
    for number,party,due,accepted,status in cases:db.add(KoshInvoice(seller_id=seller.id,counterparty_id=parties[party].id,direction="RECEIVABLE",invoice_number=number,invoice_date=date(2026,10,1),due_date=due,amount_paise=100_000,status=status,accepted_by_buyer=accepted))
    db.commit();sign_in(client.app,subject)
    prefix=f"/api/kosh/sellers/{seller.id}"
    assert client.post(prefix+"/forecast/run",json={"n_paths":10,"seed":42}).status_code==200
    assert client.post(prefix+"/financing/evaluate").status_code==200
    options=client.get(prefix+"/financing/options").json()["items"]
    treds=next(x for x in options if x["product_id"]=="TREDS_INVOICE_DISCOUNTING")
    collections=next(x for x in options if x["product_id"]=="COLLECTIONS_PUSH")
    assert len(treds["invoice_eligibility"])==len(collections["invoice_eligibility"])==len(cases)
    def by_number(product):return {next(e["invoice_number"] for e in x["evidence"] if "invoice_number" in e):x for x in product["invoice_eligibility"]}
    td=by_number(treds);cc=by_number(collections)
    assert td["GOOD"]["eligible"]
    for number,criterion in [("BUYER","BUYER_TREDS_ONBOARDED"),("UNACCEPTED","INVOICE_ACCEPTED"),("OVERDUE","INVOICE_NOT_OVERDUE"),("TOO_EARLY","INVOICE_DUE_AFTER_FUNDING")]:
        assert not td[number]["eligible"]
        assert any(r["criterion"]==criterion and r["status"]=="NOT_MATCHED" for r in td[number]["reasons"])
    assert cc["OUTSIDE"]["status"]=="NOT_MATCHED"
    assert td["REVIEW"]["status"]=="REVIEW_REQUIRED"


def test_collection_and_discount_caps_cannot_double_finance_same_invoice():
    from app.finance.plan import reserve_shared_invoice_capacity
    collection={"product_id":"COLLECTIONS_PUSH","scope":"invoice:1","status":"MATCHED","cap":50}
    discount={"product_id":"TREDS_INVOICE_DISCOUNTING","scope":"invoice:1","status":"MATCHED","cap":100}
    unrelated={"product_id":"TREDS_INVOICE_DISCOUNTING","scope":"invoice:2","status":"MATCHED","cap":100}
    reserve_shared_invoice_capacity([collection,discount,unrelated])
    assert collection["cap"]+discount["cap"]==100
    assert unrelated["cap"]==100


def test_optional_lp_receives_dimensionless_fractions(monkeypatch):
    import sys
    from types import ModuleType,SimpleNamespace
    from app.finance.plan import optimize_levers
    scipy=ModuleType("scipy");optimize=ModuleType("scipy.optimize");calls=[]
    def linprog(c,**kwargs):
        calls.append((c,kwargs))
        assert kwargs["bounds"]==[(0,1)]
        assert abs(kwargs["A_ub"][0][0])<=1 and abs(kwargs["b_ub"][0])<=1
        return SimpleNamespace(success=True,x=[.5])
    optimize.linprog=linprog;monkeypatch.setitem(sys.modules,"scipy",scipy);monkeypatch.setitem(sys.modules,"scipy.optimize",optimize)
    item={**lever(100),"unit_cost":Decimal(".01")}
    method,chosen=optimize_levers(50,[item])
    assert method=="LINPROG" and chosen[0]["amount"]==50 and calls


def test_curve_tighter_targets_never_reduce_fixture_cost():
    item=lever()
    def check(lines):
        amount=sum(x["amount"] for x in lines)
        return {"weeks":[{"prob_below_buffer":max(0,(100-amount)/100)}]}
    costs=[]
    for target in (".40",".30",".20",".10"):
        chosen,after,status=validate_and_complete([], [item],check,target_week=1,threshold=.5,target_prob=Decimal(target))
        assert status=="VALID" and Decimal(str(after["weeks"][0]["prob_below_buffer"]))<=Decimal(target)
        costs.append(sum(x["amount"]*x["unit_cost"] for x in chosen))
    assert costs==sorted(costs) and len(set(costs))==4


def test_chosen_target_persisted_and_audited_curve_read_authorized(client,db,monkeypatch):
    from tests.conftest import sign_in
    from app.api.auth import get_token_verifier
    from app.database.kosh_models import KoshAuditEntry,KoshPlan
    monkeypatch.setenv("SUPABASE_URL","https://kosh-tests.supabase.co");get_token_verifier.cache_clear()
    subject="eeeeeeee-0000-0000-0000-000000000034"
    owner=make_seller(db,name="Curve owner",owner_subject=subject)
    other=make_seller(db,name="Curve other",owner_subject="eeeeeeee-0000-0000-0000-000000000035")
    path=f"/api/kosh/sellers/{owner.id}"
    assert client.get(path+"/financing/safety-curve").status_code==401
    sign_in(client.app,subject)
    assert client.get(f"/api/kosh/sellers/{other.id}/financing/safety-curve").status_code==403
    client.post(path+"/forecast/run",json={"n_paths":10,"seed":42})
    client.post(path+"/financing/evaluate")
    result=client.post(path+"/plans",json={"target_probability":"0.30"})
    assert result.status_code==200
    plan=db.get(KoshPlan,result.json()["plan_id"])
    assert plan.planning_details["target_probability"]=="0.30"
    event=db.scalar(select(KoshAuditEntry).where(KoshAuditEntry.action=="plan.propose").order_by(KoshAuditEntry.id.desc()))
    assert event.payload["target_probability"]=="0.30"
    assert client.post(path+"/plans",json={"target_probability":"0.50"}).status_code==409
    curve=client.get(path+"/financing/safety-curve")
    assert curve.status_code==200 and len(curve.json()["items"])==4
    assert all(x["status"]=="INSUFFICIENT" for x in curve.json()["items"])


def test_nbfc_baseline_is_forecast_verified_at_same_target(db,monkeypatch):
    from app.finance.plan import propose_plan
    seller=make_seller(db,name="Safety comparison",owner_subject="eeeeeeee-0000-0000-0000-000000000033")
    user=db.scalar(select(AppUser).where(AppUser.supabase_user_id=="eeeeeeee-0000-0000-0000-000000000033"))
    as_of=date(2026,10,13)
    inputs=ForecastInputs(1000,({"id":1,"counterparty_id":1,"direction":"PAYABLE","due_date":date(2026,11,20),"amount_paise":700},),(),(0,),{},(),(),0)
    result=simulate(inputs,as_of=as_of,n_paths=20,seed=42,include_forecast_sales=False,buffer_paise=500)
    run=KoshForecastRun(seller_id=seller.id,as_of_date=as_of,n_paths=20,seed=42,params={},input_fingerprint="a"*64,include_forecast_sales=False,buffer_paise=500,status="SUCCESS",created_by_user_id=user.id)
    db.add(run);db.flush()
    for week in result["weeks"]:db.add(KoshForecastWeek(run_id=run.id,**week))
    evaluation=KoshFinancingEvaluation(seller_id=seller.id,forecast_run_id=run.id,input_fingerprint=run.input_fingerprint)
    db.add(evaluation);db.flush()
    db.add(KoshFinancingResult(evaluation_id=evaluation.id,product_id="NBFC_UNSECURED_BUSINESS_LOAN",status="MATCHED",max_amount_paise=1000,effective_annual_rate=".3",arrival_business_days=5,reasons=[],evidence=[]))
    db.flush()
    monkeypatch.setattr("app.finance.plan.load_inputs",lambda *args,**kwargs:inputs)
    plan=propose_plan(db,seller.id)
    assert plan.status=="VALID"
    assert plan.planning_details["target_probability"]=="0.20"
    assert plan.planning_details["baseline_status"]=="VALID"
    assert plan.total_cost_paise==plan.baseline_cost_paise
    assert plan.after_probabilities==plan.planning_details["baseline_after_probabilities"]
    # No 0.50 alert does not mean the tighter chosen target has been reached.
    for week in db.scalars(select(KoshForecastWeek).where(KoshForecastWeek.run_id==run.id)):
        week.prob_below_buffer=.3 if week.week_index==6 else 0
    db.flush()
    def below_threshold_not_target(inputs,run,chosen,products):
        amount=sum(line["amount"] for line in chosen)
        return {"weeks":[{"prob_below_buffer":(.3 if amount<100 else .1) if index==6 else 0} for index in range(1,14)]}
    monkeypatch.setattr("app.finance.plan.plan_scenario",below_threshold_not_target)
    tighter=propose_plan(db,seller.id)
    assert tighter.planning_details["alert_week"]==6
    assert tighter.status=="VALID" and tighter.after_probabilities[5]<=.2
