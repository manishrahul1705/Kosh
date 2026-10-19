"""Purpose/recipient/field scoped consent and revocation enforcement."""
from datetime import timedelta,timezone
import pytest
from sqlalchemy import select
from app.consent.sharing import grant,revoke,active
from app.actions.planner import decision_for
from app.actions.approvals import approve,consume,recheck,ActionError
from app.actions.step_up import request,verify,inbox
from app.database.auth_models import SellerMembership
from app.utils.dates import utcnow
from tests.test_kosh_stage4_approvals import proposed
from tests.test_kosh_stage4_intents import SUBJECT
from tests.conftest import sign_in


def scoped(db,seller,user,intent,**kwargs):
    values={"seller_id":seller.id,"actor_id":user.id,"purpose":intent.params["sharing_purpose"],"recipient_id":intent.params["recipient_id"],"fields":intent.params["sharing_fields"],"expires_at":(utcnow()+timedelta(days=1)).replace(tzinfo=timezone.utc),**kwargs}
    artifact=grant(db,**values);db.commit();return artifact


def test_scope_exact_and_missing_or_expired_fields_do_not_pass(db):
    seller,user,intent=proposed(db,product="TREDS_INVOICE_DISCOUNTING")
    assert "CONSENT_SCOPE" in decision_for(db,intent).rule_ids
    artifact=scoped(db,seller,user,intent)
    assert decision_for(db,intent).decision=="NEEDS_APPROVAL"
    request_scope={"seller_id":seller.id,"purpose":artifact.purpose,"recipient_id":artifact.recipient_id,"fields":artifact.fields}
    assert active(db,**request_scope).id==artifact.id
    for mismatch in ({"purpose":"LOAN_APPLICATION"},{"recipient_id":"BANK_OD_DRAWDOWN"},{"fields":[*artifact.fields,"gstin"]},{"seller_id":seller.id+999}):
        assert active(db,**{**request_scope,**mismatch}) is None
    artifact.expires_at=utcnow()-timedelta(seconds=1);db.commit()
    assert active(db,**request_scope) is None


def test_revocation_stops_sharing_after_otp_and_approval(db):
    seller,user,intent=proposed(db,product="TREDS_INVOICE_DISCOUNTING")
    artifact=scoped(db,seller,user,intent)
    recheck(db,seller_id=seller.id,intent_id=intent.id,actor_id=user.id);db.commit()
    request(db,seller_id=seller.id,intent_id=intent.id,actor_id=user.id);db.commit()
    code=inbox(db,seller_id=seller.id,actor_id=user.id)[0]["payload"]["code"]
    verified=verify(db,seller_id=seller.id,intent_id=intent.id,actor_id=user.id,code=code)
    approval,token=approve(db,seller_id=seller.id,intent_id=intent.id,actor_id=user.id,otp_verified=verified);db.commit()
    revoke(db,seller_id=seller.id,consent_id=artifact.id,actor_id=user.id);db.commit()
    with pytest.raises(ActionError) as blocked:consume(db,seller_id=seller.id,intent_id=intent.id,actor_id=user.id,token=token)
    assert blocked.value.rule=="CONSENT_SCOPE";db.commit()
    assert approval.used_at is None and intent.status=="BLOCKED"


def test_unknown_fields_and_unregistered_recipient_are_rejected(db):
    seller,user,intent=proposed(db,product="TREDS_INVOICE_DISCOUNTING")
    for overrides in ({"fields":["approval_token"]},{"recipient_id":"UNVERIFIED_LENDER"},{"purpose":"ANYTHING"}):
        with pytest.raises(ValueError):scoped(db,seller,user,intent,**overrides)
    with pytest.raises(ValueError,match="naive datetime"):
        scoped(db,seller,user,intent,expires_at=utcnow()+timedelta(days=1))


def test_sharing_routes_roles_tenant_scope_and_audit(client,db,monkeypatch):
    from app.api.auth import get_token_verifier
    from app.database.kosh_models import KoshAuditEntry
    monkeypatch.setenv("SUPABASE_URL","https://kosh-tests.supabase.co");get_token_verifier.cache_clear()
    seller,user,intent=proposed(db,product="TREDS_INVOICE_DISCOUNTING")
    other,other_user,other_intent=proposed(db,name="Other sharing",subject="eeeeeeee-0000-0000-0000-000000000048",product="TREDS_INVOICE_DISCOUNTING")
    foreign=scoped(db,other,other_user,other_intent)
    payload={"purpose":"TREDS_FINANCE","recipient_id":"TREDS_INVOICE_DISCOUNTING","fields":["invoice_id","amount_paise","due_date"],"expires_at":(utcnow()+timedelta(days=1)).isoformat()+"Z"}
    prefix=f"/api/kosh/sellers/{seller.id}/consents/sharing"
    assert client.post(prefix,json=payload).status_code==401 and client.get(prefix).status_code==401
    assert client.post(prefix+f"/{foreign.id}/revoke").status_code==401
    sign_in(client.app,SUBJECT)
    other_prefix=f"/api/kosh/sellers/{other.id}/consents/sharing"
    assert client.post(other_prefix,json=payload).status_code==403 and client.get(other_prefix).status_code==403
    assert client.post(other_prefix+f"/{foreign.id}/revoke").status_code==403
    assert client.post(prefix+f"/{foreign.id}/revoke").status_code==404
    created=client.post(prefix,json=payload);assert created.status_code==200
    assert client.get(prefix).status_code==200
    assert client.post(prefix+f"/{created.json()['id']}/revoke").status_code==200
    db.rollback();db.expire_all()
    membership=db.scalar(select(SellerMembership).where(SellerMembership.seller_id==seller.id,SellerMembership.user_id==user.id));membership.role="VIEWER";db.commit()
    assert client.post(prefix,json=payload).status_code==403
    assert client.post(prefix+f"/{created.json()['id']}/revoke").status_code==403
    assert client.get(prefix).status_code==200
    actions=set(db.scalars(select(KoshAuditEntry.action).where(KoshAuditEntry.seller_id==seller.id)))
    assert {"sharing.consent.grant","sharing.consent.revoke","sharing.consents.read"}<=actions
