"""Canonical binding of action parameters and provenance."""
import hashlib
from app.audit.ledger import canonical_json

def parameters_hash(*,seller_id,source,action_type,params,plan_line_id,tier):
    envelope={"seller_id":seller_id,"source":source,"action_type":action_type,"params":params,"plan_line_id":plan_line_id,"tier":tier}
    return hashlib.sha256(canonical_json(envelope).encode("utf-8")).hexdigest()

def current_hash(intent):
    return parameters_hash(seller_id=intent.seller_id,source=intent.source,action_type=intent.action_type,params=intent.params,plan_line_id=intent.plan_line_id,tier=intent.tier)
