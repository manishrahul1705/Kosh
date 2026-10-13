"""Idempotent sandbox execution, genuine cash effects and reconciliation."""
from datetime import date,timedelta,timezone
from sqlalchemy import select,func
import pytest
from app.sandbox.adapters import run,reconcile,balance,AdapterError
from app.actions.approvals import approve,consume
from app.actions.integrity import current_hash
from app.database.kosh_models import KoshSandboxExecution,KoshSandboxLedgerEntry,KoshSandboxOutbox
from app.database.models import SellerAttribute,SellerRevision
from app.policy.controls import editable_control
from app.consent.sharing import grant
from app.finance.costs import financing_quote
from app.lending.catalogue import load_catalogue
from app.utils.dates import utcnow
from tests.test_kosh_stage4_approvals import proposed


def authorized(db,product="COLLECTIONS_PUSH",**kwargs):
    seller,user,intent=proposed(db,product=product,**kwargs)
    if product!="COLLECTIONS_PUSH":
        days=47 if product=="TREDS_INVOICE_DISCOUNTING" else 30
        p=next(p for p in load_catalogue() if p["id"]==product)
        quote=financing_quote(p,intent.params["amount_paise"],days=days)
        intent.params={**intent.params,"days":days,"funding_date":"2026-10-16" if product=="TREDS_INVOICE_DISCOUNTING" else "2026-10-13","repayment_date":"2026-12-02" if product=="TREDS_INVOICE_DISCOUNTING" else "2026-11-12","cost_paise":quote["cost_paise"],"effective_annual_rate":quote["effective_annual_rate"]}
        intent.params_hash=current_hash(intent);intent.status="PROPOSED";db.commit()
        grant(db,seller_id=seller.id,actor_id=user.id,purpose=intent.params["sharing_purpose"],recipient_id=product,fields=intent.params["sharing_fields"],expires_at=(utcnow()+timedelta(days=1)).replace(tzinfo=timezone.utc));db.commit()
    artifact,token=approve(db,seller_id=seller.id,intent_id=intent.id,actor_id=user.id,otp_verified=intent.tier=="T3");db.commit()
    consume(db,seller_id=seller.id,intent_id=intent.id,actor_id=user.id,token=token)
    intent.status="EXECUTING";db.flush()
    return seller,user,intent


def test_messages_only_outbox_not_fabricated_collections_cash(db):
    seller,user,intent=authorized(db)
    result=run(db,intent);db.commit()
    assert result.status=="SETTLED" and result.result["cash_received_paise"]==0
    assert db.scalar(select(func.count()).select_from(KoshSandboxLedgerEntry))==0
    assert db.scalar(select(func.count()).select_from(KoshSandboxOutbox))==1
    repeated=run(db,intent);db.commit()
    assert repeated.id==result.id
    assert db.scalar(select(func.count()).select_from(KoshSandboxOutbox))==1
    assert reconcile(db,seller.id)["status"]=="MATCHED"


def test_treds_best_bid_t_plus_one_partial_only_idempotent_and_reconciliation(db):
    seller,user,intent=authorized(db,"TREDS_INVOICE_DISCOUNTING")
    result=run(db,intent);db.commit()
    assert result.status=="SETTLED" and result.result["settlement_business_days"]==1
    assert result.result["scheduled_submission_date"]=="2026-10-15" and result.result["settlement_date"]=="2026-10-16"
    assert result.result["accepted_bid"]["annual_rate"]=="0.085"
    assert result.result["remaining_invoice_paise"]==50_000
    entry=db.scalar(select(KoshSandboxLedgerEntry))
    assert entry.receivable_reduction_paise==50_000 and entry.amount_paise==50_000-intent.params["cost_paise"] and entry.label=="SANDBOX"
    assert run(db,intent).id==result.id;db.commit()
    assert db.scalar(select(func.count()).select_from(KoshSandboxLedgerEntry))==1
    assert reconcile(db,seller.id)["status"]=="MATCHED"
    entry.amount_paise+=1;db.commit()
    assert reconcile(db,seller.id)["status"]=="MISMATCH"


def test_failure_injection_safe_retry_and_no_duplicate_money_or_message(db):
    seller,user,intent=authorized(db)
    controls=editable_control(db,seller.id);controls.sandbox_fail_next=True;db.commit()
    first=run(db,intent);db.commit()
    assert first.status=="FAILED" and first.error=="SIMULATED_FAILURE_INJECTION"
    assert db.scalar(select(func.count()).select_from(KoshSandboxOutbox))==0
    second=run(db,intent);db.commit()
    assert second.id==first.id and second.status=="SETTLED"
    assert db.scalar(select(func.count()).select_from(KoshSandboxExecution))==1
    assert db.scalar(select(func.count()).select_from(KoshSandboxOutbox))==1


def test_adapter_refuses_unapproved_execution(db):
    seller,user,intent=proposed(db)
    with pytest.raises(AdapterError,match="APPROVED_EXECUTION_REQUIRED"):run(db,intent)


def test_bank_draw_headroom_actual_interest_and_future_repayment(db):
    seller,user,intent=authorized(db,"BANK_OD_DRAWDOWN")
    revision=db.scalar(select(SellerRevision).where(SellerRevision.seller_id==seller.id,SellerRevision.is_active.is_(True)))
    for key,value in (("bank_od_limit_paise",200_000),("bank_od_utilised_paise",100_000)):
        db.add(SellerAttribute(revision_id=revision.id,key=key,value_type="NUMBER",value_number=value,value_text=str(value)))
    db.commit()
    result=run(db,intent);db.commit()
    assert result.status=="SETTLED" and result.result["remaining_headroom_paise"]==50_000
    entries=db.scalars(select(KoshSandboxLedgerEntry).order_by(KoshSandboxLedgerEntry.entry_date)).all()
    assert entries[0].amount_paise==50_000 and entries[1].status=="SCHEDULED"
    assert entries[1].amount_paise==-(50_000+intent.params["cost_paise"])
    assert balance(db,seller.id,as_of=date(2026,10,13))["sandbox_delta_paise"]==50_000
    assert balance(db,seller.id,as_of=date(2026,10,13))["base_balance_paise"] is None


def test_sandbox_read_and_failure_routes_are_authorized(client,db,monkeypatch):
    from tests.conftest import sign_in
    from tests.test_kosh_stage4_intents import SUBJECT
    from app.api.auth import get_token_verifier
    from app.database.auth_models import SellerMembership
    monkeypatch.setenv("SUPABASE_URL","https://kosh-tests.supabase.co");get_token_verifier.cache_clear()
    seller,user,intent=proposed(db)
    other,other_user,other_intent=proposed(db,name="Other sandbox",subject="eeeeeeee-0000-0000-0000-000000000049")
    paths=["executions","outbox","statement","balance","reconciliation"]
    for path in paths:assert client.get(f"/api/kosh/sellers/{seller.id}/sandbox/{path}").status_code==401
    assert client.post(f"/api/kosh/sellers/{seller.id}/sandbox/failure-injection",json={"enabled":True}).status_code==401
    sign_in(client.app,SUBJECT)
    for path in paths:
        assert client.get(f"/api/kosh/sellers/{other.id}/sandbox/{path}").status_code==403
        assert client.get(f"/api/kosh/sellers/{seller.id}/sandbox/{path}").status_code==200
    assert client.get(f"/api/kosh/sellers/{seller.id}/sandbox/reconciliation?execution_id=unknown").status_code==404
    assert client.post(f"/api/kosh/sellers/{other.id}/sandbox/failure-injection",json={"enabled":True}).status_code==403
    assert client.post(f"/api/kosh/sellers/{seller.id}/sandbox/failure-injection",json={"enabled":True}).status_code==200
    db.rollback();db.expire_all()
    membership=db.scalar(select(SellerMembership).where(SellerMembership.seller_id==seller.id,SellerMembership.user_id==user.id));membership.role="VIEWER";db.commit()
    assert client.post(f"/api/kosh/sellers/{seller.id}/sandbox/failure-injection",json={"enabled":True}).status_code==403
