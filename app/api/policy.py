"""Owner-only policy changes and seller-authorized policy inspection."""
from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel,ConfigDict,Field,StrictInt,StrictBool
from sqlalchemy import select
from sqlalchemy.orm import Session
from typing import Literal
from app.api.deps import get_db
from app.api.seller_authorization import AuthorizedSeller,require_seller_read,require_seller_owner
from app.audit.ledger import append_event
from app.database.auth_models import SellerMembership
from app.database.models import Seller
from app.database.kosh_models import KoshCounterparty
from app.lending.catalogue import load_catalogue
from app.policy.controls import context,editable_control
from app.utils.dates import utcnow

router=APIRouter(prefix="/api/kosh/sellers/{seller_id}/policy",tags=["kosh-policy"])

class LimitsIn(BaseModel):
    model_config=ConfigDict(extra="forbid")
    max_action_paise:StrictInt=Field(ge=0)
    max_day_paise:StrictInt=Field(ge=0)

class AllowlistIn(BaseModel):
    model_config=ConfigDict(extra="forbid")
    kind:Literal["COUNTERPARTY","RECIPIENT","PAYEE"]
    reference:str=Field(min_length=1,max_length=64,pattern=r"^[A-Za-z0-9_-]+$")
    counterparty_id:StrictInt|None=None

class KillIn(BaseModel):
    model_config=ConfigDict(extra="forbid")
    enabled:StrictBool
    scope:Literal["SELLER","GLOBAL"]="SELLER"

def record(db,seller_id,access,action,payload):
    append_event(db,seller_id=seller_id,actor_type="HUMAN",actor_id=str(access.user_id),action=action,tier="T1_DRAFT",payload=payload,policy_decision="ALLOW")
    db.commit()

@router.get("")
def inspect(seller_id:int,db:Session=Depends(get_db),access:AuthorizedSeller=Depends(require_seller_read)):
    ctx=context(db,seller_id)
    record(db,seller_id,access,"policy.read",{})
    return {"global_kill":ctx.global_kill,"seller_kill":ctx.seller_kill,"max_action_paise":ctx.max_action_paise,"max_day_paise":ctx.max_day_paise,"allowlist":[{"key":key,"added_at":added.isoformat()+"Z"} for key,added in ctx.allowlist.items()],"role":access.role}

@router.put("")
def update(seller_id:int,payload:LimitsIn,db:Session=Depends(get_db),access:AuthorizedSeller=Depends(require_seller_owner)):
    row=editable_control(db,seller_id);row.max_action_paise=payload.max_action_paise;row.max_day_paise=payload.max_day_paise;row.updated_at=utcnow()
    record(db,seller_id,access,"policy.update",payload.model_dump())
    return {"status":"UPDATED"}

@router.post("/allowlist")
def allowlist(seller_id:int,payload:AllowlistIn,db:Session=Depends(get_db),access:AuthorizedSeller=Depends(require_seller_owner)):
    if payload.kind in {"COUNTERPARTY","PAYEE"}:
        try:party_id=int(payload.reference) if payload.kind=="COUNTERPARTY" else payload.counterparty_id
        except ValueError:raise HTTPException(422,"Counterparty reference must be its ID")
        party=db.scalar(select(KoshCounterparty).where(KoshCounterparty.id==party_id,KoshCounterparty.seller_id==seller_id))
        if party is None:raise HTTPException(404,"Counterparty not found")
    elif payload.reference not in {p["id"] for p in load_catalogue()}:raise HTTPException(422,"Unknown financing recipient")
    key=f"{payload.kind.lower()}:{payload.reference}"
    row=editable_control(db,seller_id)
    if not any(entry["key"]==key for entry in row.allowlist):row.allowlist=[*row.allowlist,{"key":key,"added_at":utcnow().isoformat()+"Z"}]
    row.updated_at=utcnow();record(db,seller_id,access,"policy.allowlist.add",{"key":key})
    return {"key":key,"cool_off_hours":24}

@router.delete("/allowlist/{key}")
def remove(seller_id:int,key:str,db:Session=Depends(get_db),access:AuthorizedSeller=Depends(require_seller_owner)):
    row=editable_control(db,seller_id);row.allowlist=[entry for entry in row.allowlist if entry["key"]!=key];row.updated_at=utcnow()
    record(db,seller_id,access,"policy.allowlist.remove",{"key":key});return {"status":"REMOVED"}

@router.post("/kill-switch")
def kill(seller_id:int,payload:KillIn,db:Session=Depends(get_db),access:AuthorizedSeller=Depends(require_seller_owner)):
    if payload.scope=="GLOBAL":
        owned=set(db.scalars(select(SellerMembership.seller_id).where(SellerMembership.user_id==access.user_id,SellerMembership.role=="OWNER",SellerMembership.status=="ACTIVE")))
        if not set(db.scalars(select(Seller.id)))<=owned:raise HTTPException(403,"Global controls require OWNER membership for every seller")
    row=editable_control(db,None if payload.scope=="GLOBAL" else seller_id);row.kill_switch=payload.enabled;row.updated_at=utcnow()
    record(db,seller_id,access,"policy.kill_switch",payload.model_dump());return {"enabled":row.kill_switch,"scope":payload.scope}
