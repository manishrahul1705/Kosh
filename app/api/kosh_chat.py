"""Seller-authorized read-only cash chat; action requests are audited refusals."""
import hashlib
from fastapi import APIRouter,Depends
from pydantic import BaseModel,ConfigDict,Field
from sqlalchemy.orm import Session
from sqlalchemy import select
from app.api.deps import get_db
from app.api.seller_authorization import AuthorizedSeller,require_seller_edit,require_seller_read
from app.database.kosh_models import KoshOperationRecord
from app.finance.kosh_chat import answer
from app.finance.modules import enabled
from app.audit.ledger import append_event
router=APIRouter(prefix="/api/kosh/sellers/{seller_id}/chat",tags=["kosh-chat"])
class QuestionIn(BaseModel):
    model_config=ConfigDict(extra="forbid")
    question:str=Field(min_length=1,max_length=2000)
@router.get("/history")
def history(seller_id:int,db:Session=Depends(get_db),access:AuthorizedSeller=Depends(require_seller_read)):
    rows=db.scalars(select(KoshOperationRecord).where(KoshOperationRecord.seller_id==seller_id,
        KoshOperationRecord.kind=="CHAT_MESSAGE").order_by(KoshOperationRecord.id.desc()).limit(20))
    return {"items":[{"id":row.id,**row.data} for row in rows]}
@router.post("")
def reply(seller_id:int,payload:QuestionIn,db:Session=Depends(get_db),access:AuthorizedSeller=Depends(require_seller_edit)):
    result=answer(db,seller_id,payload.question) if enabled(db,seller_id,'chat') else {'status':'REFUSED','reason':'Cash chat is disabled for this seller.','facts':[],'rule_ids':['MODULE_DISABLED']};refused=result['status']=='REFUSED'
    if not refused:
        db.add(KoshOperationRecord(seller_id=seller_id,kind="CHAT_MESSAGE",evidence_ref="cash-chat",
            data={"question":payload.question,"answer":result},status="CONFIRMED",created_by_user_id=access.user_id))
    append_event(db,seller_id=seller_id,actor_type="HUMAN",actor_id=str(access.user_id),action="security.intent_blocked" if refused else "chat.read",tier="T4" if refused else "T0",payload={"question_hash":hashlib.sha256(payload.question.encode()).hexdigest(),"rule_ids":result['rule_ids'],"fact_ids":[f['id'] for f in result['facts']]},policy_decision="DENY" if refused else "ALLOW");db.commit();return result
