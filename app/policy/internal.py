"""Policy gate for audited internal drafts and fact proposals."""
from fastapi import HTTPException
from app.policy.rules import evaluate
from app.policy.controls import context
from app.audit.ledger import append_event

def gate(db,seller_id,actor_id,*,action="APPLICATION_PACK_DRAFT",source="ADDON:operations"):
    from app.finance.modules import enabled
    if not enabled(db,seller_id,source.split(':',1)[-1]):
        append_event(db,seller_id=seller_id,actor_type="HUMAN",actor_id=str(actor_id),action="module.action_blocked",tier="T1",payload={"module":source.split(':',1)[-1]},policy_decision="DENY");db.commit();raise HTTPException(403,{"rule_ids":["MODULE_DISABLED"],"reason":"This module is disabled; its page remains available."})
    decision=evaluate(action,{},context(db,seller_id),origin=source)
    if decision.decision=="DENY":
        append_event(db,seller_id=seller_id,actor_type="HUMAN",actor_id=str(actor_id),action="security.intent_blocked",tier="T4",payload={"policy":decision.as_dict()},policy_decision="DENY");db.commit()
        raise HTTPException(403,decision.as_dict())
    return decision
