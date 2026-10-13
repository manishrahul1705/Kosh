"""Authorized local sandbox inbox; no external delivery capability."""
from fastapi import APIRouter,Depends,HTTPException
from sqlalchemy.orm import Session
from app.api.deps import get_db
from app.api.seller_authorization import AuthorizedSeller,require_seller_approval
from app.actions.step_up import inbox
from app.audit.ledger import append_event
from app.core.config import get_settings

router=APIRouter(prefix="/api/kosh/sellers/{seller_id}/sandbox",tags=["kosh-sandbox"])

@router.get("/inbox")
def read_inbox(seller_id:int,db:Session=Depends(get_db),access:AuthorizedSeller=Depends(require_seller_approval)):
    if get_settings().app_env.strip().lower()=="production":raise HTTPException(403,"Sandbox OTP inbox is disabled in production")
    items=inbox(db,seller_id=seller_id,actor_id=access.user_id)
    append_event(db,seller_id=seller_id,actor_type="HUMAN",actor_id=str(access.user_id),action="sandbox.inbox.read",tier="T0",payload={"count":len(items)},policy_decision="ALLOW");db.commit()
    return {"seller_id":seller_id,"items":items}
