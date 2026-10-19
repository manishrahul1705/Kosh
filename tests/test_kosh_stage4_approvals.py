"""Approval parameter binding, single use, expiry and human-role contracts."""
from datetime import timedelta
import pytest
from sqlalchemy import select
from app.actions.approvals import approve,consume,reject,ActionError,secret
from app.actions.planner import create_from_plan_line
from app.database.kosh_models import KoshActionIntent,KoshAuditEntry
from app.database.auth_models import AppUser,SellerMembership
from app.core.config import Settings
from app.utils.dates import utcnow
from tests.test_kosh_stage4_intents import planned_line,SUBJECT
from tests.conftest import sign_in


def proposed(db,**kwargs):
    seller,user,invoice,line=planned_line(db,**kwargs)
    intent=create_from_plan_line(db,seller_id=seller.id,plan_line_id=line.id,creator_id=user.id);db.commit()
    return seller,user,intent


def test_single_use_token_and_signature_and_parameter_tampering(db):
    seller,user,intent=proposed(db)
    artifact,token=approve(db,seller_id=seller.id,intent_id=intent.id,actor_id=user.id);db.commit()
    assert artifact.expires_at-artifact.issued_at==timedelta(minutes=5)
    with pytest.raises(ActionError) as invalid:consume(db,seller_id=seller.id,intent_id=intent.id,actor_id=user.id,token=token+"x")
    assert invalid.value.rule=="TOKEN_INVALID";db.commit()
    consume(db,seller_id=seller.id,intent_id=intent.id,actor_id=user.id,token=token);db.commit()
    with pytest.raises(ActionError) as replay:consume(db,seller_id=seller.id,intent_id=intent.id,actor_id=user.id,token=token)
    assert replay.value.rule=="TOKEN_REPLAY";db.commit()
    assert db.scalar(select(KoshAuditEntry).where(KoshAuditEntry.action=="security.token_replay"))
    intent.params={**intent.params,"amount_paise":intent.params["amount_paise"]+1};db.commit()
    with pytest.raises(ActionError) as tampered:consume(db,seller_id=seller.id,intent_id=intent.id,actor_id=user.id,token=token)
    assert tampered.value.rule=="PARAMS_TAMPERED";db.commit()
    assert intent.status=="BLOCKED"


def test_token_expiry_and_rejection_revoke_token(db,monkeypatch):
    seller,user,intent=proposed(db)
    artifact,token=approve(db,seller_id=seller.id,intent_id=intent.id,actor_id=user.id);db.commit()
    monkeypatch.setattr("app.actions.approvals.utcnow",lambda:artifact.expires_at+timedelta(seconds=1))
    with pytest.raises(ActionError) as expired:consume(db,seller_id=seller.id,intent_id=intent.id,actor_id=user.id,token=token)
    assert expired.value.rule=="TOKEN_EXPIRED";db.commit()
    assert intent.status=="EXPIRED"


def test_rejection_revokes_unused_approval(db):
    seller,user,intent=proposed(db)
    artifact,token=approve(db,seller_id=seller.id,intent_id=intent.id,actor_id=user.id);db.commit()
    reject(db,seller_id=seller.id,intent_id=intent.id,actor_id=user.id);db.commit()
    assert intent.status=="REJECTED" and artifact.revoked_at is not None
    with pytest.raises(ActionError) as revoked:consume(db,seller_id=seller.id,intent_id=intent.id,actor_id=user.id,token=token)
    assert revoked.value.rule=="TOKEN_REVOKED"


def test_t3_creator_needs_other_approver_when_one_exists(db):
    seller,user,intent=proposed(db,product="TREDS_INVOICE_DISCOUNTING")
    second=AppUser(supabase_user_id="eeeeeeee-0000-0000-0000-000000000045");db.add(second);db.flush()
    db.add(SellerMembership(seller_id=seller.id,user_id=second.id,role="APPROVER",status="ACTIVE"))
    intent.status="PROPOSED";db.commit()
    with pytest.raises(ActionError) as denied:approve(db,seller_id=seller.id,intent_id=intent.id,actor_id=user.id)
    assert denied.value.rule=="SECOND_APPROVER"


def test_approval_routes_authorize_every_endpoint(client,db,monkeypatch):
    from app.api.auth import get_token_verifier
    monkeypatch.setenv("SUPABASE_URL","https://kosh-tests.supabase.co");get_token_verifier.cache_clear()
    seller,user,intent=proposed(db)
    other,other_user,other_intent=proposed(db,name="Other approval",subject="eeeeeeee-0000-0000-0000-000000000046")
    prefix=f"/api/kosh/sellers/{seller.id}/actions/intents/{intent.id}"
    for suffix in ("approve","reject","recheck"):assert client.post(prefix+"/"+suffix,json={}).status_code==401
    sign_in(client.app,SUBJECT)
    for suffix in ("approve","reject","recheck"):assert client.post(f"/api/kosh/sellers/{other.id}/actions/intents/{other_intent.id}/{suffix}",json={}).status_code==403
    for suffix in ("approve","reject","recheck"):assert client.post(f"/api/kosh/sellers/{seller.id}/actions/intents/{other_intent.id}/{suffix}",json={}).status_code==404
    assert client.post(prefix+"/approve",json={}).status_code==200
    membership=db.scalar(select(SellerMembership).where(SellerMembership.seller_id==seller.id,SellerMembership.user_id==user.id));membership.role="VIEWER";db.commit()
    for suffix in ("approve","reject","recheck"):assert client.post(prefix+"/"+suffix,json={}).status_code==403


def test_production_secret_required_and_development_secret_is_process_local(monkeypatch):
    with pytest.raises(ValueError,match="KOSH_APPROVAL_SECRET"):Settings(_env_file=None,app_env="production",kosh_approval_secret=None)
    from types import SimpleNamespace
    monkeypatch.setattr("app.actions.approvals.get_settings",lambda:SimpleNamespace(kosh_approval_secret=None))
    assert len(secret())==32 and secret()==secret()
