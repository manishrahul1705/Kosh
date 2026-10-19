"""Five-minute single-use approvals bound to exact canonical intent parameters."""
import base64,hashlib,hmac,json,secrets,uuid
from datetime import datetime,timedelta,timezone
from sqlalchemy import select
from app.core.config import get_settings
from app.audit.ledger import append_event,canonical_json
from app.database.session import reserve_sqlite_writer
from app.database.auth_models import SellerMembership
from app.database.kosh_models import KoshActionApproval,KoshPolicyControl
from app.actions.integrity import current_hash
from app.actions.read import owned
from app.actions.planner import decision_for
from app.utils.dates import utcnow

_DEV_SECRET=secrets.token_bytes(32)

class ActionError(RuntimeError):
    def __init__(self,rule,reason,status_code=403):
        super().__init__(reason);self.rule=rule;self.status_code=status_code

def secret():
    configured=get_settings().kosh_approval_secret
    return configured.get_secret_value().encode("utf-8") if configured and configured.get_secret_value() else _DEV_SECRET

def epoch(value):return int(value.replace(tzinfo=timezone.utc).timestamp())

def token_for(approval):
    payload={"intent_id":approval.intent_id,"params_hash":approval.params_hash,"approver_id":approval.approver_id,"nonce":approval.jti,"exp":epoch(approval.expires_at)}
    encoded=base64.urlsafe_b64encode(canonical_json(payload).encode()).decode().rstrip("=")
    signature=hmac.new(secret(),encoded.encode(),hashlib.sha256).hexdigest()
    return encoded+"."+signature

def denied(db,intent,actor_id,rule,reason,*,status_code=403,security_action="security.intent_blocked",new_status=None):
    if new_status and intent.status not in {"SUCCEEDED","EXECUTING"}:intent.status=new_status;intent.updated_at=utcnow()
    append_event(db,seller_id=intent.seller_id,actor_type="HUMAN",actor_id=str(actor_id),action=security_action,tier=intent.tier,payload={"intent_id":intent.id,"rule_ids":[rule],"reason":reason},policy_decision="DENY")
    raise ActionError(rule,reason,status_code)

def locked(db,seller_id,intent_id,actor_id,*,approval_role=True):
    reserve_sqlite_writer(db,renew_read=True)
    # Serialize approvals against policy changes and per-seller daily reservations.
    db.scalars(select(KoshPolicyControl).where(KoshPolicyControl.scope_key.in_(["GLOBAL",f"SELLER:{seller_id}"])).order_by(KoshPolicyControl.scope_key).with_for_update()).all()
    intent=owned(db,seller_id,intent_id,lock=True)
    if intent is None:raise ActionError("NOT_FOUND","Intent not found",404)
    membership=db.scalar(select(SellerMembership).where(SellerMembership.seller_id==seller_id,SellerMembership.user_id==actor_id,SellerMembership.status=="ACTIVE").execution_options(populate_existing=True).with_for_update())
    allowed={"OWNER","APPROVER"} if approval_role else {"OWNER","ADMIN","EDITOR"}
    if membership is None or membership.role not in allowed:denied(db,intent,actor_id,"APPROVER_ROLE","Role is not permitted for this action.")
    if not secrets.compare_digest(current_hash(intent),intent.params_hash):denied(db,intent,actor_id,"PARAMS_TAMPERED","Canonical parameters or provenance changed.",new_status="BLOCKED")
    return intent,membership.role

def revoke_unused(db,intent_id,now):
    for artifact in db.scalars(select(KoshActionApproval).where(KoshActionApproval.intent_id==intent_id,KoshActionApproval.used_at.is_(None),KoshActionApproval.revoked_at.is_(None))):artifact.revoked_at=now

def recheck(db,*,seller_id,intent_id,actor_id):
    intent,role=locked(db,seller_id,intent_id,actor_id)
    if intent.status=="APPROVED" and intent.expires_at and intent.expires_at<=utcnow():intent.status="EXPIRED"
    if intent.status not in {"BLOCKED","EXPIRED","FAILED"}:denied(db,intent,actor_id,"RECHECK_STATE","Only blocked, expired or failed intents can be rechecked.",status_code=409)
    decision=decision_for(db,intent)
    intent.policy_decision=decision.as_dict()
    if decision.decision=="DENY":denied(db,intent,actor_id,decision.rule_ids[0],decision.reasons[0],new_status="BLOCKED")
    revoke_unused(db,intent.id,utcnow());intent.status="PROPOSED";intent.expires_at=None
    append_event(db,seller_id=seller_id,actor_type="HUMAN",actor_id=str(actor_id),action="intent.recheck",tier=intent.tier,payload={"intent_id":intent.id,"policy":decision.as_dict()},policy_decision=decision.decision)
    return intent

def approve(db,*,seller_id,intent_id,actor_id,otp_verified=False):
    intent,role=locked(db,seller_id,intent_id,actor_id)
    now=utcnow()
    if intent.status=="APPROVED" and intent.expires_at and intent.expires_at<=now:
        denied(db,intent,actor_id,"APPROVAL_EXPIRED","Expired approval must be rechecked.",new_status="EXPIRED",status_code=410)
    if intent.status!="PROPOSED":denied(db,intent,actor_id,"APPROVAL_STATE","Intent must be proposed before approval.",status_code=409)
    if intent.tier=="T3" and intent.created_by_user_id==actor_id:
        others=db.scalars(select(SellerMembership.user_id).where(SellerMembership.seller_id==seller_id,SellerMembership.status=="ACTIVE",SellerMembership.role.in_(["OWNER","APPROVER"]),SellerMembership.user_id!=actor_id)).all()
        if others:denied(db,intent,actor_id,"SECOND_APPROVER","Another active approver exists; the creator cannot supply the executable approval.")
    decision=decision_for(db,intent,phase="approve",actor_role=role,otp_verified=otp_verified)
    if decision.decision=="DENY":denied(db,intent,actor_id,decision.rule_ids[0],decision.reasons[0],new_status="BLOCKED")
    if intent.tier=="T3" and not otp_verified:denied(db,intent,actor_id,"OTP_REQUIRED","T3 requires verified OTP step-up.")
    if intent.tier not in {"T2","T3"}:denied(db,intent,actor_id,"HUMAN_TIER","This route only approves T2 and T3 intents.")
    artifact=KoshActionApproval(jti=str(uuid.uuid4()),intent_id=intent.id,seller_id=seller_id,params_hash=intent.params_hash,approver_id=actor_id,issued_at=now,expires_at=now+timedelta(minutes=5),otp_verified=otp_verified)
    db.add(artifact);intent.status="APPROVED";intent.approved_at=now;intent.expires_at=artifact.expires_at;intent.policy_decision=decision.as_dict()
    append_event(db,seller_id=seller_id,actor_type="HUMAN",actor_id=str(actor_id),action="intent.approve",tier=intent.tier,payload={"intent_id":intent.id,"jti":artifact.jti,"params_hash":artifact.params_hash,"expires_at":artifact.expires_at},policy_decision="ALLOW",approval_id=artifact.jti)
    return artifact,token_for(artifact)

def reject(db,*,seller_id,intent_id,actor_id):
    intent,role=locked(db,seller_id,intent_id,actor_id)
    if intent.status not in {"PROPOSED","BLOCKED","APPROVED"}:denied(db,intent,actor_id,"REJECTION_STATE","Completed or expired intents cannot be rejected.",status_code=409)
    revoke_unused(db,intent.id,utcnow());intent.status="REJECTED"
    append_event(db,seller_id=seller_id,actor_type="HUMAN",actor_id=str(actor_id),action="intent.reject",tier=intent.tier,payload={"intent_id":intent.id},policy_decision="DENY")
    return intent

def consume(db,*,seller_id,intent_id,actor_id,token):
    intent,role=locked(db,seller_id,intent_id,actor_id)
    try:
        if not isinstance(token,str) or len(token)>4096:raise ValueError()
        encoded,signature=token.split(".")
        expected=hmac.new(secret(),encoded.encode(),hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected,signature):raise ValueError()
        payload=json.loads(base64.urlsafe_b64decode(encoded+"="*(-len(encoded)%4)))
        if set(payload)!={"intent_id","params_hash","approver_id","nonce","exp"}:raise ValueError()
        if type(payload["exp"]) is not int or type(payload["approver_id"]) is not int:raise ValueError()
    except (ValueError,TypeError,UnicodeError,json.JSONDecodeError):denied(db,intent,actor_id,"TOKEN_INVALID","Approval token signature or format is invalid.",security_action="security.token_invalid")
    if payload["intent_id"]!=intent.id or payload["approver_id"]!=actor_id or payload["params_hash"]!=intent.params_hash:denied(db,intent,actor_id,"TOKEN_BINDING","Token does not match this intent, exact parameters or approver.",security_action="security.token_invalid")
    artifact=db.scalar(select(KoshActionApproval).where(KoshActionApproval.jti==payload["nonce"],KoshActionApproval.intent_id==intent.id,KoshActionApproval.seller_id==seller_id).with_for_update())
    if artifact is None or artifact.params_hash!=intent.params_hash or artifact.approver_id!=actor_id:denied(db,intent,actor_id,"TOKEN_UNKNOWN","Approval artifact not found.",security_action="security.token_invalid")
    if artifact.used_at is not None:denied(db,intent,actor_id,"TOKEN_REPLAY","Approval token is single-use.",security_action="security.token_replay")
    if artifact.revoked_at is not None:denied(db,intent,actor_id,"TOKEN_REVOKED","Approval was revoked.",security_action="security.token_invalid")
    now=utcnow()
    if epoch(now)>=payload["exp"] or artifact.expires_at<=now:denied(db,intent,actor_id,"TOKEN_EXPIRED","Approval token expired.",new_status="EXPIRED",status_code=410,security_action="security.token_expired")
    if intent.status!="APPROVED":denied(db,intent,actor_id,"EXECUTION_STATE","Intent is not approved.",status_code=409)
    decision=decision_for(db,intent,phase="execute",actor_role=role,approved=True,otp_verified=artifact.otp_verified)
    if decision.decision!="ALLOW":denied(db,intent,actor_id,decision.rule_ids[0],decision.reasons[0],new_status="BLOCKED")
    artifact.used_at=now
    append_event(db,seller_id=seller_id,actor_type="HUMAN",actor_id=str(actor_id),action="approval.consume",tier=intent.tier,payload={"intent_id":intent.id,"jti":artifact.jti},policy_decision="ALLOW",approval_id=artifact.jti)
    return intent,artifact
