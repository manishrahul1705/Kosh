"""Sandbox OTP hashing, delivery, limits, expiry and authorization."""
from datetime import timedelta
import pytest
from sqlalchemy import select
from app.actions.step_up import request,verify,inbox
from app.actions.approvals import ActionError
from app.actions.integrity import current_hash
from app.database.kosh_models import KoshOtpChallenge,KoshSandboxInbox,KoshAuditEntry
from app.database.auth_models import SellerMembership
from app.core.config import Settings
from app.utils.dates import utcnow
from tests.test_kosh_stage4_approvals import proposed
from tests.test_kosh_stage4_intents import SUBJECT
from tests.conftest import sign_in


def money_intent(db,**kwargs):
    # Isolate money-only step-up from sharing consent, tested by its own phase.
    seller,user,intent=proposed(db,product="TREDS_INVOICE_DISCOUNTING",**kwargs)
    intent.params={**intent.params,"sharing_fields":[]};intent.params_hash=current_hash(intent);intent.status="PROPOSED";db.commit()
    return seller,user,intent


def delivered(db,seller,user,intent):
    challenge=request(db,seller_id=seller.id,intent_id=intent.id,actor_id=user.id);db.commit()
    code=inbox(db,seller_id=seller.id,actor_id=user.id)[0]["payload"]["code"]
    return challenge,code


def test_otp_hash_encrypted_delivery_success_single_use_and_no_audit_plaintext(db):
    seller,user,intent=money_intent(db)
    challenge,code=delivered(db,seller,user,intent)
    assert len(code)==6 and code.isdigit() and len(challenge.code_hash)==64 and challenge.code_hash!=code
    message=db.scalar(select(KoshSandboxInbox))
    assert message.encrypted_payload!=code and '"code"' not in message.encrypted_payload
    assert verify(db,seller_id=seller.id,intent_id=intent.id,actor_id=user.id,code=code);db.commit()
    assert challenge.verified_at and challenge.consumed_at and challenge.attempts==1
    with pytest.raises(ActionError) as replay:verify(db,seller_id=seller.id,intent_id=intent.id,actor_id=user.id,code=code)
    assert replay.value.rule=="OTP_REPLAY";db.commit()
    for event in db.scalars(select(KoshAuditEntry)):
        assert "code" not in event.payload and "otp_code" not in event.payload


def test_three_attempt_limit_and_delivery_rate_limit(db):
    seller,user,intent=money_intent(db)
    challenge,code=delivered(db,seller,user,intent)
    wrong=("1" if code[0]!="1" else "2")+code[1:]
    for _ in range(3):
        with pytest.raises(ActionError) as failure:verify(db,seller_id=seller.id,intent_id=intent.id,actor_id=user.id,code=wrong)
        assert failure.value.rule=="OTP_INVALID";db.commit()
    assert challenge.attempts==3
    with pytest.raises(ActionError) as limit:verify(db,seller_id=seller.id,intent_id=intent.id,actor_id=user.id,code=code)
    assert limit.value.rule=="OTP_ATTEMPTS";db.commit()
    with pytest.raises(ActionError) as rate:request(db,seller_id=seller.id,intent_id=intent.id,actor_id=user.id)
    assert rate.value.status_code==429


def test_otp_expiry_suppresses_inbox_code(db):
    seller,user,intent=money_intent(db)
    challenge,code=delivered(db,seller,user,intent)
    challenge.expires_at=utcnow()-timedelta(seconds=1)
    message=db.scalar(select(KoshSandboxInbox));message.expires_at=challenge.expires_at;db.commit()
    assert inbox(db,seller_id=seller.id,actor_id=user.id)[0]["payload"] is None
    with pytest.raises(ActionError) as expired:verify(db,seller_id=seller.id,intent_id=intent.id,actor_id=user.id,code=code)
    assert expired.value.rule=="OTP_EXPIRED"


def test_unreadable_delivery_is_unknown_not_guessed_expiry(db):
    seller,user,intent=money_intent(db)
    challenge,code=delivered(db,seller,user,intent)
    message=db.scalar(select(KoshSandboxInbox));message.encrypted_payload="unreadable";db.commit()
    result=inbox(db,seller_id=seller.id,actor_id=user.id)[0]
    assert result["payload"] is None and result["status"]=="UNAVAILABLE"


def test_otp_routes_and_private_inbox_roles_and_cross_tenant(client,db,monkeypatch):
    from app.api.auth import get_token_verifier
    monkeypatch.setenv("SUPABASE_URL","https://kosh-tests.supabase.co");get_token_verifier.cache_clear()
    seller,user,intent=money_intent(db)
    other,other_user,other_intent=money_intent(db,name="Other OTP",subject="eeeeeeee-0000-0000-0000-000000000047")
    otp=f"/api/kosh/sellers/{seller.id}/actions/intents/{intent.id}/otp"
    mailbox=f"/api/kosh/sellers/{seller.id}/sandbox/inbox"
    assert client.post(otp).status_code==401 and client.get(mailbox).status_code==401
    sign_in(client.app,SUBJECT)
    assert client.post(f"/api/kosh/sellers/{other.id}/actions/intents/{other_intent.id}/otp").status_code==403
    assert client.get(f"/api/kosh/sellers/{other.id}/sandbox/inbox").status_code==403
    assert client.post(otp).status_code==200
    response=client.get(mailbox);assert response.status_code==200
    code=response.json()["items"][0]["payload"]["code"]
    approval=client.post(otp.removesuffix("/otp")+"/approve",json={"otp_code":code})
    assert approval.status_code==200 and approval.json()["approval_token"]
    db.rollback();db.expire_all()
    membership=db.scalar(select(SellerMembership).where(SellerMembership.seller_id==seller.id,SellerMembership.user_id==user.id));membership.role="VIEWER";db.commit()
    assert client.post(otp).status_code==403 and client.get(mailbox).status_code==403


@pytest.mark.parametrize("value",[None,"","short"])
def test_production_secret_is_not_empty_or_case_bypass(value):
    with pytest.raises(ValueError,match="KOSH_APPROVAL_SECRET"):Settings(_env_file=None,app_env=" Production ",kosh_approval_secret=value)
