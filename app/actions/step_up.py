"""Local OTP step-up with hashed challenges and encrypted sandbox delivery."""
import base64,hashlib,hmac,json,secrets,uuid
from datetime import timedelta
from cryptography.fernet import Fernet,InvalidToken
from sqlalchemy import select
from app.actions.approvals import locked,denied,secret,ActionError
from app.actions.planner import decision_for
from app.audit.ledger import append_event,canonical_json
from app.core.config import get_settings
from app.database.kosh_models import KoshOtpChallenge,KoshSandboxInbox
from app.utils.dates import utcnow

def cipher():return Fernet(base64.urlsafe_b64encode(hashlib.sha256(secret()+b"sandbox-inbox-v1").digest()))

def code_hash(challenge,code):
    message=f"otp:{challenge.id}:{challenge.intent_id}:{challenge.params_hash}:{code}"
    return hmac.new(secret(),message.encode(),hashlib.sha256).hexdigest()

def request(db,*,seller_id,intent_id,actor_id):
    intent,role=locked(db,seller_id,intent_id,actor_id)
    if get_settings().app_env.strip().lower()=="production":denied(db,intent,actor_id,"SANDBOX_OTP_ONLY","Simulated OTP delivery is available only outside production.")
    if intent.tier!="T3":denied(db,intent,actor_id,"OTP_TIER","OTP step-up is required only for T3.")
    if intent.status not in {"PROPOSED","BLOCKED","EXPIRED"}:denied(db,intent,actor_id,"OTP_STATE","Intent is not awaiting step-up.",status_code=409)
    decision=decision_for(db,intent,phase="approve",actor_role=role)
    if decision.decision=="DENY":denied(db,intent,actor_id,decision.rule_ids[0],decision.reasons[0])
    now=utcnow()
    recent=db.scalars(select(KoshOtpChallenge).where(KoshOtpChallenge.seller_id==seller_id,KoshOtpChallenge.approver_id==actor_id,KoshOtpChallenge.created_at>=now-timedelta(hours=1)).order_by(KoshOtpChallenge.created_at.desc())).all()
    if len(recent)>=10 or (recent and recent[0].created_at>now-timedelta(seconds=30)):
        denied(db,intent,actor_id,"OTP_RATE_LIMIT","OTP delivery is rate-limited.",status_code=429,security_action="security.otp_rate_limited")
    if any(row.intent_id==intent.id and row.attempts>=3 and row.expires_at>now for row in recent):
        denied(db,intent,actor_id,"OTP_ATTEMPTS","This challenge exhausted its three attempts; wait until it expires.",status_code=429,security_action="security.otp_locked")
    for previous in recent:
        if previous.intent_id==intent.id and previous.consumed_at is None:previous.consumed_at=now
    code=f"{secrets.randbelow(1_000_000):06d}"
    challenge=KoshOtpChallenge(id=str(uuid.uuid4()),seller_id=seller_id,intent_id=intent.id,approver_id=actor_id,params_hash=intent.params_hash,code_hash="",attempts=0,created_at=now,expires_at=now+timedelta(minutes=5))
    challenge.code_hash=code_hash(challenge,code)
    message=KoshSandboxInbox(id=str(uuid.uuid4()),seller_id=seller_id,recipient_user_id=actor_id,kind="OTP",intent_id=intent.id,encrypted_payload=cipher().encrypt(canonical_json({"code":code,"challenge_id":challenge.id}).encode()).decode(),created_at=now,expires_at=challenge.expires_at)
    db.add_all([challenge,message])
    append_event(db,seller_id=seller_id,actor_type="SYSTEM",actor_id=str(actor_id),action="otp.deliver.sandbox",tier="T3",payload={"intent_id":intent.id,"challenge_id":challenge.id,"expires_at":challenge.expires_at},policy_decision="ALLOW")
    return challenge

def verify(db,*,seller_id,intent_id,actor_id,code):
    intent,role=locked(db,seller_id,intent_id,actor_id)
    row=db.scalar(select(KoshOtpChallenge).where(KoshOtpChallenge.seller_id==seller_id,KoshOtpChallenge.intent_id==intent.id,KoshOtpChallenge.approver_id==actor_id,KoshOtpChallenge.params_hash==intent.params_hash).order_by(KoshOtpChallenge.created_at.desc()).limit(1).with_for_update())
    if row is None:denied(db,intent,actor_id,"OTP_MISSING","Request an OTP challenge first.",security_action="security.otp_failed")
    now=utcnow()
    if row.expires_at<=now:denied(db,intent,actor_id,"OTP_EXPIRED","OTP challenge expired.",status_code=410,security_action="security.otp_failed")
    if row.consumed_at is not None:denied(db,intent,actor_id,"OTP_REPLAY","OTP challenge has already been used.",security_action="security.otp_failed")
    if row.attempts>=3:denied(db,intent,actor_id,"OTP_ATTEMPTS","Maximum three OTP attempts exceeded.",status_code=429,security_action="security.otp_locked")
    row.attempts+=1
    if not isinstance(code,str) or len(code)!=6 or not code.isascii() or not code.isdigit() or not hmac.compare_digest(code_hash(row,code),row.code_hash):
        denied(db,intent,actor_id,"OTP_INVALID","OTP verification failed.",security_action="security.otp_failed")
    row.verified_at=now;row.consumed_at=now
    append_event(db,seller_id=seller_id,actor_type="HUMAN",actor_id=str(actor_id),action="otp.verify",tier="T3",payload={"intent_id":intent.id,"challenge_id":row.id},policy_decision="ALLOW")
    return True

def inbox(db,*,seller_id,actor_id):
    now=utcnow();items=[]
    for row in db.scalars(select(KoshSandboxInbox).where(KoshSandboxInbox.seller_id==seller_id,KoshSandboxInbox.recipient_user_id==actor_id).order_by(KoshSandboxInbox.created_at.desc())):
        payload=None
        if row.expires_at is None or row.expires_at>now:
            try:payload=json.loads(cipher().decrypt(row.encrypted_payload.encode()))
            except (InvalidToken,ValueError):pass
        items.append({"id":row.id,"kind":row.kind,"intent_id":row.intent_id,"payload":payload,"created_at":row.created_at.isoformat()+"Z","expires_at":row.expires_at.isoformat()+"Z" if row.expires_at else None,"status":"DELIVERED" if payload is not None else "EXPIRED" if row.expires_at is not None and row.expires_at<=now else "UNAVAILABLE"})
    return items
