"""Approval-gated execution, actual cash effects and honest reforecast."""
from datetime import date
from dataclasses import replace
import pytest
from sqlalchemy import select,func
from app.finance.forecast import ForecastInputs,simulate,load_inputs
from app.actions.approvals import approve,ActionError
from app.actions.execution import execute
from app.actions.integrity import current_hash
from app.database.kosh_models import KoshSandboxLedgerEntry,KoshForecastRun,KoshPlan
from app.lending.service import run_evaluation
from app.database.kosh_models import KoshFinancingResult
from app.finance.costs import financing_quote
from app.lending.catalogue import load_catalogue
from tests.test_kosh_stage4_approvals import proposed
from tests.test_kosh_stage4_sandbox import authorized
from tests.test_kosh_stage4_sharing import scoped
from tests.test_kosh_stage4_intents import SUBJECT
from tests.conftest import sign_in


def test_sandbox_component_distinct_and_partial_receivable_conservation():
    inputs=ForecastInputs(0,({"id":7,"counterparty_id":1,"direction":"RECEIVABLE","due_date":date(2026,10,26),"amount_paise":1000},),(),(0,),{},(),(),0)
    funded=replace(inputs,sandbox_cash_events=({"date":"2026-10-16","amount_paise":390,"component":"sandbox"},),sandbox_invoice_reductions={7:400})
    result=simulate(funded,as_of=date(2026,10,13),n_paths=20,seed=42,include_forecast_sales=False,buffer_paise=0)
    assert result["weeks"][0]["expected_inflow_sandbox_paise"]==390
    assert result["weeks"][0]["expected_inflow_committed_paise"]==0
    assert result["weeks"][2]["expected_inflow_committed_paise"]==600
    assert result["weeks"][-1]["p50_closing_balance_paise"]==990
    assert result==simulate(funded,as_of=date(2026,10,13),n_paths=20,seed=42,include_forecast_sales=False,buffer_paise=0)


def test_message_success_reforecasts_without_invented_receipt_and_repeat_review(db):
    seller,user,intent=proposed(db)
    artifact,token=approve(db,seller_id=seller.id,intent_id=intent.id,actor_id=user.id);db.commit()
    result=execute(db,seller_id=seller.id,intent_id=intent.id,actor_id=user.id,token=token);db.commit()
    assert intent.status=="SUCCEEDED" and result.status=="SETTLED"
    assert result.result["before_probabilities"]==result.result["after_probabilities"]
    assert db.scalar(select(func.count()).select_from(KoshSandboxLedgerEntry))==0
    before=db.get(KoshForecastRun,result.result["before_forecast_run_id"])
    after=db.get(KoshForecastRun,result.result["after_forecast_run_id"])
    assert (before.seed,before.as_of_date,before.n_paths)==(after.seed,after.as_of_date,after.n_paths)
    run_evaluation(db,seller.id,date(2026,10,13));db.flush()
    result_row=db.scalar(select(KoshFinancingResult).where(KoshFinancingResult.product_id=="COLLECTIONS_PUSH").order_by(KoshFinancingResult.id.desc()).limit(1))
    assert result_row.status in {"REVIEW_REQUIRED","NOT_MATCHED"}
    assert any(r["criterion"]=="COLLECTION_REPEAT_OUTCOME_PRESENT" and r["status"]=="REVIEW_REQUIRED" for r in result_row.reasons)


def test_execute_route_requires_owner_or_approver_and_rejects_parameter_override(client,db,monkeypatch):
    from app.api.auth import get_token_verifier
    from app.database.auth_models import SellerMembership
    monkeypatch.setenv("SUPABASE_URL","https://kosh-tests.supabase.co");get_token_verifier.cache_clear()
    seller,user,intent=proposed(db)
    other,other_user,other_intent=proposed(db,name="Other execution",subject="eeeeeeee-0000-0000-0000-000000000050")
    artifact,token=approve(db,seller_id=seller.id,intent_id=intent.id,actor_id=user.id);db.commit()
    endpoint=f"/api/kosh/sellers/{seller.id}/actions/intents/{intent.id}/execute"
    assert client.post(endpoint,json={"approval_token":token}).status_code==401
    sign_in(client.app,SUBJECT)
    assert client.post(f"/api/kosh/sellers/{other.id}/actions/intents/{other_intent.id}/execute",json={"approval_token":token}).status_code==403
    assert client.post(f"/api/kosh/sellers/{seller.id}/actions/intents/{other_intent.id}/execute",json={"approval_token":token}).status_code==404
    assert client.post(endpoint,json={"approval_token":token,"amount_paise":999}).status_code==403
    response=client.post(endpoint,json={"approval_token":token});assert response.status_code==200
    assert response.json()["result"]["seed"]==42
    assert client.post(endpoint,json={"approval_token":token}).status_code==403
    db.rollback();db.expire_all()
    membership=db.scalar(select(SellerMembership).where(SellerMembership.seller_id==seller.id,SellerMembership.user_id==user.id));membership.role="VIEWER";db.commit()
    assert client.post(endpoint,json={"approval_token":token}).status_code==403


def test_executed_treds_posts_only_net_amount_and_reduces_only_financed_part(db):
    seller,user,intent=proposed(db,product="TREDS_INVOICE_DISCOUNTING")
    product=next(p for p in load_catalogue() if p["id"]=="TREDS_INVOICE_DISCOUNTING")
    quote=financing_quote(product,intent.params["amount_paise"],days=47)
    intent.params={**intent.params,"cost_paise":quote["cost_paise"],"effective_annual_rate":quote["effective_annual_rate"]};intent.params_hash=current_hash(intent);intent.status="PROPOSED";db.commit()
    scoped(db,seller,user,intent)
    artifact,token=approve(db,seller_id=seller.id,intent_id=intent.id,actor_id=user.id,otp_verified=True);db.commit()
    before=load_inputs(db,seller.id,date(2026,10,13))
    result=execute(db,seller_id=seller.id,intent_id=intent.id,actor_id=user.id,token=token);db.commit()
    after=load_inputs(db,seller.id,date(2026,10,13))
    assert before.sandbox_invoice_reductions=={}
    assert after.sandbox_invoice_reductions[intent.params["invoice_id"]]==50_000
    assert after.sandbox_cash_events[0]["amount_paise"]==50_000-quote["cost_paise"]
    assert result.result["after_forecast_run_id"]!=result.result["before_forecast_run_id"]


def test_hypothetical_cash_api_rejects_fractional_paise_and_fake_sandbox_tags(client,db):
    from tests.matching_factories import make_seller
    seller=make_seller(db,name="Strict scenario",owner_subject=SUBJECT);sign_in(client.app,SUBJECT)
    for event in ({"date":"2026-10-13","amount_paise":1.5},{"date":"2026-10-13","amount_paise":True},{"date":"2026-10-13","amount_paise":100,"component":"sandbox"}):
        response=client.post(f"/api/kosh/sellers/{seller.id}/forecast/whatif",json={"extra_inflows":[event]})
        assert response.status_code==422
