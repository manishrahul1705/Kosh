"""Native trusted-resource factory; no free-text action parameters."""
import uuid,hashlib
from sqlalchemy import select
from app.audit.ledger import append_event,canonical_json
from app.database.session import reserve_sqlite_writer
from app.database.kosh_models import KoshAddonDraft,KoshActionIntent,KoshInvoice
from app.actions.integrity import current_hash
from app.actions.planner import decision_for

def draft_hash(row):return hashlib.sha256(canonical_json({"module":row.module,"kind":row.kind,"params":row.params,"body":row.body}).encode()).hexdigest()
def create_from_draft(db,*,seller_id,draft_id,creator_id):
    reserve_sqlite_writer(db,renew_read=True)
    draft=db.scalar(select(KoshAddonDraft).where(KoshAddonDraft.id==draft_id,KoshAddonDraft.seller_id==seller_id).with_for_update())
    if draft is None:raise LookupError("DRAFT_NOT_FOUND")
    if draft.kind not in {"COLLECTIONS_REMINDER","SUPPLIER_TERM_REQUEST","RFQ_MESSAGE","SHARE_DATA_PACK"} or draft.module not in {"collections","procurement","reports","operations"}:raise ValueError("UNREGISTERED_DRAFT")
    if draft.evidence_hash!=draft_hash(draft):raise ValueError("DRAFT_TAMPERED")
    params=dict(draft.params)
    if params.get("invoice_id"):
        invoice=db.scalar(select(KoshInvoice).where(KoshInvoice.id==params["invoice_id"],KoshInvoice.seller_id==seller_id,KoshInvoice.status=="OPEN"))
        if invoice is None or params["amount_paise"]!=max(0,invoice.amount_paise-(invoice.paid_amount_paise or 0)):raise ValueError("INVOICE_EVIDENCE_CHANGED")
    for old in db.scalars(select(KoshActionIntent).where(KoshActionIntent.seller_id==seller_id,KoshActionIntent.source==f"ADDON:{draft.module}")):
        if old.params.get("draft_id")==draft.id:
            append_event(db,seller_id=seller_id,actor_type="HUMAN",actor_id=str(creator_id),action="addon.intent.repeat",tier=old.tier,payload={"intent_id":old.id},policy_decision="ALLOW");return old
    params.update(draft_id=draft.id,draft_hash=draft.evidence_hash,message_body=draft.body,params_origin="TRUSTED_MODULE")
    row=KoshActionIntent(id=str(uuid.uuid4()),seller_id=seller_id,source=f"ADDON:{draft.module}",action_type=draft.kind,params=params,plan_line_id=None,tier="T3" if draft.kind=="SHARE_DATA_PACK" else "T2",params_hash="",status="PROPOSED",created_by_user_id=creator_id,policy_decision={})
    row.params_hash=current_hash(row);decision=decision_for(db,row);row.policy_decision=decision.as_dict()
    if decision.decision=="DENY":row.status="BLOCKED"
    db.add(row);db.flush();append_event(db,seller_id=seller_id,actor_type="HUMAN",actor_id=str(creator_id),action="security.intent_blocked" if row.status=="BLOCKED" else "addon.intent.propose",tier=row.tier,payload={"intent_id":row.id,"draft_id":draft.id,"policy":row.policy_decision},policy_decision=decision.decision)
    return row
