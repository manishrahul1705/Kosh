"""Plan safety target and cost transparency contracts."""
from decimal import Decimal
from datetime import date
from sqlalchemy import select

from app.core.config import Settings
from app.finance.plan import validate_and_complete
from app.finance.forecast import ForecastInputs,simulate
from app.database.kosh_models import KoshForecastRun,KoshForecastWeek,KoshFinancingEvaluation,KoshFinancingResult
from app.database.auth_models import AppUser
from tests.matching_factories import make_seller


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
    monkeypatch.setattr("app.finance.plan.load_inputs",lambda *args:inputs)
    plan=propose_plan(db,seller.id)
    assert plan.status=="VALID"
    assert plan.planning_details["target_probability"]=="0.20"
    assert plan.planning_details["baseline_status"]=="VALID"
    assert plan.total_cost_paise==plan.baseline_cost_paise
    assert plan.after_probabilities==plan.planning_details["baseline_after_probabilities"]
