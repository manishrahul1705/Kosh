"""Seller-authorized read-only cash chat; action requests are audited refusals."""
import hashlib
from fastapi import APIRouter,Depends
from pydantic import BaseModel,ConfigDict,Field
from sqlalchemy.orm import Session
from app.api.deps import get_db
from app.api.seller_authorization import AuthorizedSeller,require_seller_edit
from app.finance.kosh_chat import answer
from app.audit.ledger import append_event
router=APIRouter(prefix="/api/kosh/sellers/{seller_id}/chat",tags=["kosh-chat"])
class QuestionIn(BaseModel):
    model_config=ConfigDict(extra="forbid")
    question:str=Field(min_length=1,max_length=2000)
@router.post("")
def reply(seller_id:int,payload:QuestionIn,db:Session=Depends(get_db),access:AuthorizedSeller=Depends(require_seller_edit)):
    result=answer(db,seller_id,payload.question);refused=result['status']=='REFUSED'
    append_event(db,seller_id=seller_id,actor_type="HUMAN",actor_id=str(access.user_id),action="security.intent_blocked" if refused else "chat.read",tier="T4" if refused else "T0",payload={"question_hash":hashlib.sha256(payload.question.encode()).hexdigest(),"rule_ids":result['rule_ids'],"fact_ids":[f['id'] for f in result['facts']]},policy_decision="DENY" if refused else "ALLOW");db.commit();return result
