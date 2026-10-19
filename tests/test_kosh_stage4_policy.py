"""Deterministic policy and owner-control authorization contracts."""
from datetime import datetime,timedelta
from dataclasses import replace
import pytest
from sqlalchemy import select
from app.policy.rules import PolicyContext,evaluate,TIERS
from app.database.auth_models import AppUser,SellerMembership
from app.database.kosh_models import KoshCounterparty,KoshAuditEntry
from tests.conftest import sign_in
from tests.matching_factories import make_seller

NOW=datetime(2026,10,13,12)


def context(**kwargs):
    return PolicyContext(now=NOW,allowlist={"counterparty:1":NOW-timedelta(days=2)},**kwargs)


@pytest.mark.parametrize("action,tier",list(TIERS.items()))
def test_tier_mapping(action,tier):
    decision=evaluate(action,{"allowlist_key":"counterparty:1"},context())
    assert decision.tier==tier
    assert decision.decision==("DENY" if tier=="T4" else "ALLOW" if tier in {"T0","T1"} else "NEEDS_APPROVAL")


@pytest.mark.parametrize("flag",["global_kill","seller_kill"])
def test_kill_switch_blocks_every_tier(flag):
    for action in TIERS:
        decision=evaluate(action,{"allowlist_key":"counterparty:1"},context(**{flag:True}))
        assert decision.tier=="T4" and decision.rule_ids==("KILL_SWITCH",)


def test_document_parameters_bank_changes_unknown_action_and_unknown_payee_block():
    assert evaluate("PAYMENT",{"allowlist_key":"counterparty:1"},context(),origin="DOCUMENT").rule_ids==("DOCUMENT_PARAMETERS",)
    for action in ("CHANGE_BANK_DETAILS","UNSUPPORTED"):
        assert evaluate(action,{},context()).tier=="T4"
    decision=evaluate("PAYMENT",{"allowlist_key":"payee:XXXX"},context())
    assert decision.tier=="T4" and "ALLOWLIST" in decision.rule_ids


def test_cool_off_limits_integer_paise_and_consent_scope():
    params={"amount_paise":100,"allowlist_key":"counterparty:1"}
    ctx=context()
    assert "COOL_OFF" in evaluate("OD_DRAWDOWN",params,replace(ctx,allowlist={"counterparty:1":NOW-timedelta(hours=23,minutes=59)})).rule_ids
    assert "COOL_OFF" not in evaluate("OD_DRAWDOWN",params,replace(ctx,allowlist={"counterparty:1":NOW-timedelta(hours=24)})).rule_ids
    assert "ACTION_LIMIT" in evaluate("OD_DRAWDOWN",params,replace(ctx,max_action_paise=99)).rule_ids
    assert "DAY_LIMIT" in evaluate("OD_DRAWDOWN",params,replace(ctx,max_day_paise=199,day_used_paise=100)).rule_ids
    for bad in (True,1.5,"100",-1):assert "INTEGER_PAISE" in evaluate("OD_DRAWDOWN",{**params,"amount_paise":bad},ctx).rule_ids
    assert "CONSENT_SCOPE" in evaluate("SHARE_DATA_PACK",{**params,"sharing_fields":["gstin"]},ctx).rule_ids


def test_execution_requires_approval_and_t3_step_up_and_role():
    params={"allowlist_key":"counterparty:1"}
    for role in ("VIEWER","EDITOR","ADMIN"):
        assert "APPROVER_ROLE" in evaluate("OD_DRAWDOWN",params,context(actor_role=role),phase="approve").rule_ids
    assert evaluate("OD_DRAWDOWN",params,context(actor_role="OWNER",approved=True),phase="execute").decision=="NEEDS_APPROVAL"
    assert evaluate("OD_DRAWDOWN",params,context(actor_role="OWNER",approved=True,otp_verified=True),phase="execute").decision=="ALLOW"
    assert evaluate("COLLECTIONS_REMINDER",params,context(actor_role="APPROVER",approved=True),phase="execute").decision=="ALLOW"


def test_policy_routes_owner_only_cross_tenant_and_audited(client,db,monkeypatch):
    from app.api.auth import get_token_verifier
    monkeypatch.setenv("SUPABASE_URL","https://kosh-tests.supabase.co");get_token_verifier.cache_clear()
    subject="eeeeeeee-0000-0000-0000-000000000041"
    seller=make_seller(db,name="Policy owner",owner_subject=subject)
    other=make_seller(db,name="Policy other",owner_subject="eeeeeeee-0000-0000-0000-000000000042")
    party=KoshCounterparty(seller_id=seller.id,name="Buyer",kind="CUSTOMER");foreign=KoshCounterparty(seller_id=other.id,name="Other buyer",kind="CUSTOMER")
    db.add_all([party,foreign]);db.commit()
    suffixes=[("get","",None),("put","",{"max_action_paise":1000,"max_day_paise":2000}),("post","/allowlist",{"kind":"COUNTERPARTY","reference":str(party.id)}),("delete","/allowlist/counterparty:1",None),("post","/kill-switch",{"enabled":True})]
    def call(method,url,payload):return getattr(client,method)(url,**({"json":payload} if payload else {}))
    prefix=f"/api/kosh/sellers/{seller.id}/policy"
    for method,suffix,payload in suffixes:assert call(method,prefix+suffix,payload).status_code==401
    sign_in(client.app,subject)
    for method,suffix,payload in suffixes:assert call(method,f"/api/kosh/sellers/{other.id}/policy"+suffix,payload).status_code==403
    assert client.post(prefix+"/allowlist",json={"kind":"COUNTERPARTY","reference":str(foreign.id)}).status_code==404
    assert client.post(prefix+"/allowlist",json={"kind":"COUNTERPARTY","reference":str(party.id)}).status_code==200
    assert client.put(prefix,json={"max_action_paise":1000,"max_day_paise":2000}).status_code==200
    assert client.post(prefix+"/kill-switch",json={"enabled":True,"scope":"GLOBAL"}).status_code==403
    assert client.post(prefix+"/kill-switch",json={"enabled":True}).status_code==200
    assert client.get(prefix).json()["seller_kill"]
    user=db.scalar(select(AppUser).where(AppUser.supabase_user_id==subject));membership=db.scalar(select(SellerMembership).where(SellerMembership.user_id==user.id,SellerMembership.seller_id==seller.id))
    membership.role="VIEWER";db.commit()
    for method,suffix,payload in suffixes:
        if method!="get":assert call(method,prefix+suffix,payload).status_code==403
    assert client.get(prefix).status_code==200
    actions=set(db.scalars(select(KoshAuditEntry.action).where(KoshAuditEntry.seller_id==seller.id)))
    assert {"policy.allowlist.add","policy.update","policy.kill_switch","policy.read"}<=actions
