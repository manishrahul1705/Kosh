"""Private T1 cash-report generation and T3 consent-bound sharing proposals."""
import base64,hashlib
from datetime import date
from fastapi import APIRouter,Depends,HTTPException
from fastapi.responses import Response
from pydantic import BaseModel,ConfigDict,Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.api.deps import get_db
from app.api.seller_authorization import AuthorizedSeller,require_seller_read,require_seller_edit
from app.database.kosh_models import KoshOperationRecord,KoshAddonDraft
from app.database.session import reserve_sqlite_writer
from app.finance.cash_report import snapshot,build_pdf
from app.audit.ledger import append_event
from app.audit.verify import verify_chain
from app.policy.internal import gate
from app.actions.addons import draft_hash,create_from_draft
from app.actions.read import out
from app.lending.catalogue import load_catalogue
router=APIRouter(prefix="/api/kosh/sellers/{seller_id}/reports",tags=["kosh-reports"])
class ShareIn(BaseModel):
    model_config=ConfigDict(extra="forbid")
    recipient_id:str=Field(min_length=1,max_length=64)
def owned(db,seller_id,report_id):
    row=db.scalar(select(KoshOperationRecord).where(KoshOperationRecord.id==report_id,KoshOperationRecord.seller_id==seller_id,KoshOperationRecord.kind=="REPORT"))
    if row is None:raise HTTPException(404,"Report not found")
    return row
@router.post("")
def generate(seller_id:int,db:Session=Depends(get_db),access:AuthorizedSeller=Depends(require_seller_edit)):
    reserve_sqlite_writer(db,renew_read=True);gate(db,seller_id,access.user_id,source="ADDON:reports")
    if not verify_chain(db).valid:raise HTTPException(409,"Audit chain invalid")
    try:data=snapshot(db,seller_id)
    except ValueError as exc:raise HTTPException(409,str(exc))
    pdf=build_pdf(data);digest=hashlib.sha256(pdf).hexdigest()
    row=KoshOperationRecord(seller_id=seller_id,kind="REPORT",evidence_ref=f"forecast:{data['run_id']}",data={"pdf_base64":base64.b64encode(pdf).decode(),"pdf_sha256":digest,"snapshot":data},status="DRAFT",created_by_user_id=access.user_id);db.add(row);db.flush()
    append_event(db,seller_id=seller_id,actor_type="HUMAN",actor_id=str(access.user_id),action="report.generate",tier="T1",payload={"report_id":row.id,"pdf_sha256":digest,"audit_hash":data['audit_hash']},policy_decision="ALLOW");db.commit();return {"id":row.id,"tier":"T1","pdf_sha256":digest,"download":f"/api/kosh/sellers/{seller_id}/reports/{row.id}/pdf"}
@router.get("")
def listing(seller_id:int,db:Session=Depends(get_db),access:AuthorizedSeller=Depends(require_seller_read)):
    items=[{"id":r.id,"status":r.status,"evidence_ref":r.evidence_ref,"pdf_sha256":r.data['pdf_sha256']} for r in db.scalars(select(KoshOperationRecord).where(KoshOperationRecord.seller_id==seller_id,KoshOperationRecord.kind=="REPORT").order_by(KoshOperationRecord.id.desc()))]
    append_event(db,seller_id=seller_id,actor_type="HUMAN",actor_id=str(access.user_id),action="reports.read",tier="T0",payload={},policy_decision="ALLOW");db.commit();return {"items":items,"role":access.role,"recipients":[{"id":p['id'],"label":p['display_name']} for p in load_catalogue()]}
@router.get("/{report_id}/pdf")
def download(seller_id:int,report_id:int,db:Session=Depends(get_db),access:AuthorizedSeller=Depends(require_seller_read)):
    row=owned(db,seller_id,report_id);pdf=base64.b64decode(row.data['pdf_base64'])
    if hashlib.sha256(pdf).hexdigest()!=row.data['pdf_sha256']:raise HTTPException(409,"Report integrity failed")
    append_event(db,seller_id=seller_id,actor_type="HUMAN",actor_id=str(access.user_id),action="report.download",tier="T0",payload={"id":row.id},policy_decision="ALLOW");db.commit();return Response(pdf,media_type="application/pdf",headers={"Content-Disposition":f'attachment; filename="kosh-cash-{row.id}.pdf"'})
@router.post("/{report_id}/share")
def share(seller_id:int,report_id:int,payload:ShareIn,db:Session=Depends(get_db),access:AuthorizedSeller=Depends(require_seller_edit)):
    reserve_sqlite_writer(db,renew_read=True);gate(db,seller_id,access.user_id,source="ADDON:reports");report=owned(db,seller_id,report_id)
    if report.status!="DRAFT":raise HTTPException(409,"Only an active internal report draft may be shared")
    if payload.recipient_id not in {p['id'] for p in load_catalogue()}:raise HTTPException(422,"Unknown registered recipient")
    existing=next((d for d in db.scalars(select(KoshAddonDraft).where(KoshAddonDraft.seller_id==seller_id,KoshAddonDraft.module=="reports",KoshAddonDraft.kind=="SHARE_DATA_PACK")) if d.params.get('report_id')==report.id and d.params.get('recipient_id')==payload.recipient_id),None)
    if existing:
        intent=create_from_draft(db,seller_id=seller_id,draft_id=existing.id,creator_id=access.user_id);db.commit();return out(intent)
    row=KoshAddonDraft(seller_id=seller_id,module="reports",kind="SHARE_DATA_PACK",params={"feature_module":"reports","amount_paise":0,"report_id":report.id,"pdf_sha256":report.data['pdf_sha256'],"allowlist_key":f"recipient:{payload.recipient_id}","recipient_id":payload.recipient_id,"sharing_purpose":"SHARE_DATA_PACK","sharing_fields":["cash_report_pdf","forecast","plan","options","audit_hash"],"evidence_reference":f"report:{report.id}:{report.data['pdf_sha256']}","funding_date":report.data['snapshot']['as_of'],"days":0,"cost_paise":0},body=f"Internal cash-position application pack #{report.id}",evidence_hash="",status="DRAFT",created_by_user_id=access.user_id);row.evidence_hash=draft_hash(row);db.add(row);db.flush()
    intent=create_from_draft(db,seller_id=seller_id,draft_id=row.id,creator_id=access.user_id);db.commit();return out(intent)
