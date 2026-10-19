"""Authorized audit export, exported-proof verification and security counters."""
from fastapi import APIRouter,Depends,HTTPException,Response
from pydantic import BaseModel,ConfigDict,Field
from sqlalchemy.orm import Session
from app.api.deps import get_db
from app.api.seller_authorization import AuthorizedSeller,require_seller_read
from app.audit.ledger import append_event
from app.audit.export import export_jsonl,verify_jsonl,security_counts

router=APIRouter(prefix="/api/kosh/sellers/{seller_id}/audit",tags=["kosh-audit-export"])

def record(db,seller_id,access,action,payload,decision="ALLOW"):
    append_event(db,seller_id=seller_id,actor_type="HUMAN",actor_id=str(access.user_id),action=action,tier="T0",payload=payload,policy_decision=decision);db.commit()

@router.get("/export")
def export(seller_id:int,db:Session=Depends(get_db),access:AuthorizedSeller=Depends(require_seller_read)):
    record(db,seller_id,access,"audit.export",{"format":"JSONL","scope":"SELLER_WITH_OPAQUE_ANCHORS"})
    try:text=export_jsonl(db,seller_id)
    except ValueError as exc:raise HTTPException(409,str(exc))
    return Response(text,media_type="application/x-ndjson",headers={"Content-Disposition":f'attachment; filename="kosh-audit-{seller_id}.jsonl"'})

class VerifyIn(BaseModel):
    model_config=ConfigDict(extra="forbid")
    jsonl:str=Field(max_length=2_000_000)

@router.post("/verify-export")
def verify(seller_id:int,payload:VerifyIn,db:Session=Depends(get_db),access:AuthorizedSeller=Depends(require_seller_read)):
    result=verify_jsonl(db,seller_id,payload.jsonl)
    record(db,seller_id,access,"audit.export.verify",{"valid":result["valid"],"reason":result.get("reason")},"ALLOW" if result["valid"] else "DENY")
    return result

@router.get("/security-events")
def counters(seller_id:int,db:Session=Depends(get_db),access:AuthorizedSeller=Depends(require_seller_read)):
    counts=security_counts(db,seller_id);record(db,seller_id,access,"audit.security_counts.read",counts)
    return {"seller_id":seller_id,"counts":counts}
