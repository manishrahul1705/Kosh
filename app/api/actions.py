"""Seller-scoped plan-derived intent routes; arbitrary action parameters are blocked."""
from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel,ConfigDict,StrictInt,Field,ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.api.deps import get_db
from app.api.seller_authorization import AuthorizedSeller,require_seller_edit,require_seller_read,require_seller_approval
from app.audit.ledger import append_event
from app.database.kosh_models import KoshActionIntent
from app.actions.planner import create_from_plan_line
from app.actions.read import out,owned
from app.policy.controls import context
from app.actions.approvals import approve,reject,recheck,ActionError

router=APIRouter(prefix="/api/kosh/sellers/{seller_id}/actions/intents",tags=["kosh-actions"])

class FromLine(BaseModel):
    model_config=ConfigDict(extra="forbid")
    plan_line_id:StrictInt=Field(gt=0)

@router.post("")
def propose(seller_id:int,payload:dict,db:Session=Depends(get_db),access:AuthorizedSeller=Depends(require_seller_edit)):
    if set(payload)!={"plan_line_id"}:
        rules=["FREE_TEXT_INTENT","TRUSTED_ORIGIN"]
        ctx=context(db,seller_id)
        if payload.get("action_type")=="PAYMENT" and f"payee:{payload.get('payee_ref',payload.get('payee'))}" not in ctx.allowlist:rules.append("ALLOWLIST")
        if payload.get("source")=="DOCUMENT" or payload.get("params_origin")=="DOCUMENT":rules.append("DOCUMENT_PARAMETERS")
        if ctx.global_kill or ctx.seller_kill:rules.append("KILL_SWITCH")
        policy={"tier":"T4","decision":"DENY","rule_ids":rules,"reasons":["Intent parameters may only come from a valid server plan line."]}
        append_event(db,seller_id=seller_id,actor_type="HUMAN",actor_id=str(access.user_id),action="security.intent_blocked",tier="T4",payload={"attempt_keys":sorted(payload),"policy":policy},policy_decision="DENY");db.commit()
        raise HTTPException(403,detail=policy)
    try:
        request=FromLine.model_validate(payload)
        intent=create_from_plan_line(db,seller_id=seller_id,plan_line_id=request.plan_line_id,creator_id=access.user_id)
    except ValidationError:raise HTTPException(422,"A positive integer plan_line_id is required")
    except LookupError as exc:raise HTTPException(404,str(exc))
    except ValueError as exc:raise HTTPException(409,str(exc))
    db.commit();return out(intent)

@router.get("")
def inbox(seller_id:int,db:Session=Depends(get_db),access:AuthorizedSeller=Depends(require_seller_read)):
    rows=db.scalars(select(KoshActionIntent).where(KoshActionIntent.seller_id==seller_id).order_by(KoshActionIntent.created_at.desc(),KoshActionIntent.id)).all()
    append_event(db,seller_id=seller_id,actor_type="HUMAN",actor_id=str(access.user_id),action="intent.inbox.read",tier="T0",payload={},policy_decision="ALLOW");db.commit()
    return {"seller_id":seller_id,"role":access.role,"items":[out(row) for row in rows]}

@router.get("/{intent_id}")
def detail(seller_id:int,intent_id:str,db:Session=Depends(get_db),access:AuthorizedSeller=Depends(require_seller_read)):
    row=owned(db,seller_id,intent_id)
    if row is None:raise HTTPException(404,"Intent not found")
    append_event(db,seller_id=seller_id,actor_type="HUMAN",actor_id=str(access.user_id),action="intent.read",tier="T0",payload={"intent_id":row.id},policy_decision="ALLOW");db.commit();return out(row)


class ApprovalIn(BaseModel):
    model_config=ConfigDict(extra="forbid")
    otp_code:str|None=Field(default=None,max_length=6)

def action_error(db,exc):
    db.commit()
    raise HTTPException(exc.status_code,detail={"rule_ids":[exc.rule],"reason":str(exc)})

@router.post("/{intent_id}/approve")
def approve_route(seller_id:int,intent_id:str,payload:ApprovalIn=ApprovalIn(),db:Session=Depends(get_db),access:AuthorizedSeller=Depends(require_seller_approval)):
    try:
        verified=False
        if payload.otp_code is not None:
            from app.actions.step_up import verify
            verified=verify(db,seller_id=seller_id,intent_id=intent_id,actor_id=access.user_id,code=payload.otp_code)
        artifact,token=approve(db,seller_id=seller_id,intent_id=intent_id,actor_id=access.user_id,otp_verified=verified)
    except ActionError as exc:action_error(db,exc)
    db.commit();return {"intent_id":intent_id,"approval_token":token,"expires_at":artifact.expires_at.isoformat()+"Z","jti":artifact.jti}

@router.post("/{intent_id}/reject")
def reject_route(seller_id:int,intent_id:str,db:Session=Depends(get_db),access:AuthorizedSeller=Depends(require_seller_approval)):
    try:row=reject(db,seller_id=seller_id,intent_id=intent_id,actor_id=access.user_id)
    except ActionError as exc:action_error(db,exc)
    db.commit();return out(row)

@router.post("/{intent_id}/recheck")
def recheck_route(seller_id:int,intent_id:str,db:Session=Depends(get_db),access:AuthorizedSeller=Depends(require_seller_approval)):
    try:row=recheck(db,seller_id=seller_id,intent_id=intent_id,actor_id=access.user_id)
    except ActionError as exc:action_error(db,exc)
    db.commit();return out(row)


@router.post("/{intent_id}/otp")
def otp_route(seller_id:int,intent_id:str,db:Session=Depends(get_db),access:AuthorizedSeller=Depends(require_seller_approval)):
    from app.actions.step_up import request
    try:challenge=request(db,seller_id=seller_id,intent_id=intent_id,actor_id=access.user_id)
    except ActionError as exc:action_error(db,exc)
    db.commit();return {"challenge_id":challenge.id,"expires_at":challenge.expires_at.isoformat()+"Z","delivery":"SANDBOX_INBOX"}
