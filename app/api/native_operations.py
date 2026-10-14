"""Native sales, PO, RFQ and material-price proposals with tenant-owned evidence."""
from datetime import date
from decimal import Decimal,ROUND_HALF_UP
from typing import Literal
from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel,ConfigDict,StrictInt,Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.api.deps import get_db
from app.api.seller_authorization import AuthorizedSeller,require_seller_read,require_seller_edit,require_seller_owner
from app.database.kosh_models import KoshOperationRecord,KoshCashEvent,KoshCounterparty,KoshAddonDraft
from app.database.session import reserve_sqlite_writer
from app.audit.ledger import append_event
from app.policy.internal import gate
from app.actions.addons import draft_hash,create_from_draft
from app.actions.read import out
from app.utils.dates import utcnow
from app.core.config import get_settings
router=APIRouter(prefix="/api/kosh/sellers/{seller_id}/operations",tags=["kosh-operations"])
MARKET_SAMPLE=[{"material_code":"STEEL","change_percent":"8","source":"Bundled fictional offline sample","verified_market_fact":False},{"material_code":"ALUMINIUM","change_percent":"-3","source":"Bundled fictional offline sample","verified_market_fact":False}]
class StrictInput(BaseModel):model_config=ConfigDict(extra="forbid")
class OrderIn(StrictInput):
    direction:Literal["SALE","PO"]
    counterparty_id:StrictInt=Field(gt=0)
    amount_paise:StrictInt=Field(gt=0,le=9000000000000000)
    payment_date:date
    material_code:str=Field(pattern=r"^[A-Z0-9_-]{1,40}$")
    evidence_ref:str=Field(min_length=1,max_length=160)
    estimated_cost_paise:StrictInt|None=Field(default=None,ge=0,le=9000000000000000)
    quantity:StrictInt|None=Field(default=None,ge=1,le=1000000)
    delivery_date:date|None=None
    location:str|None=Field(default=None,max_length=160)
    special_requirements:str|None=Field(default=None,max_length=1000)
class PricingIn(StrictInput):
    purchase_order_id:StrictInt=Field(gt=0)
    change_percent:Decimal=Field(ge=-100,le=100)
    evidence_ref:str=Field(min_length=1,max_length=160)
class RFQIn(StrictInput):
    counterparty_id:StrictInt=Field(gt=0)
    material_code:str=Field(pattern=r"^[A-Z0-9_-]{1,40}$")
    quantity:StrictInt=Field(gt=0,le=1000000)
    needed_date:date
    evidence_ref:str=Field(min_length=1,max_length=160)
def party(db,seller_id,party_id):
    row=db.scalar(select(KoshCounterparty).where(KoshCounterparty.id==party_id,KoshCounterparty.seller_id==seller_id))
    if row is None:raise HTTPException(404,"Counterparty not found")
    return row
def owned(db,seller_id,record_id,kind=None):
    row=db.scalar(select(KoshOperationRecord).where(KoshOperationRecord.id==record_id,KoshOperationRecord.seller_id==seller_id).with_for_update())
    if row is None or (kind and row.kind!=kind):raise HTTPException(404,"Operation record not found")
    return row
def record(db,seller_id,access,action,payload,tier="T1"):
    append_event(db,seller_id=seller_id,actor_type="HUMAN",actor_id=str(access.user_id),action=action,tier=tier,payload=payload,policy_decision="ALLOW");db.commit()
@router.get("")
def listing(seller_id:int,db:Session=Depends(get_db),access:AuthorizedSeller=Depends(require_seller_read)):
    items=[{**out(row),"data":{k:v for k,v in row.data.items() if k!="pdf_base64"}} for row in db.scalars(select(KoshOperationRecord).where(KoshOperationRecord.seller_id==seller_id).order_by(KoshOperationRecord.id.desc()))]
    record(db,seller_id,access,"operations.read",{},"T0");return {"items":items,"role":access.role,"counterparties":[{"id":p.id,"name":p.name,"kind":p.kind} for p in db.scalars(select(KoshCounterparty).where(KoshCounterparty.seller_id==seller_id))],"market_sample":MARKET_SAMPLE,"drafts":[{"id":d.id,"module":d.module,"kind":d.kind,"body":d.body,"status":d.status} for d in db.scalars(select(KoshAddonDraft).where(KoshAddonDraft.seller_id==seller_id))],"external_delivery":False}
@router.post("/orders")
def order(seller_id:int,payload:OrderIn,db:Session=Depends(get_db),access:AuthorizedSeller=Depends(require_seller_edit)):
    reserve_sqlite_writer(db,renew_read=True);gate(db,seller_id,access.user_id,source="ADDON:sales" if payload.direction=="SALE" else "ADDON:procurement");party(db,seller_id,payload.counterparty_id)
    existing=db.scalar(select(KoshOperationRecord).where(KoshOperationRecord.seller_id==seller_id,KoshOperationRecord.kind==payload.direction,KoshOperationRecord.evidence_ref==payload.evidence_ref))
    if existing:
        if any(existing.data.get(key)!=value for key,value in payload.model_dump(mode="json").items()):raise HTTPException(409,"Order evidence already used with different parameters")
        record(db,seller_id,access,"operations.order.propose.repeat",{"record_id":existing.id});return out(existing)
    if db.scalar(select(KoshCashEvent.id).where(KoshCashEvent.seller_id==seller_id,KoshCashEvent.source_module==("sales" if payload.direction=="SALE" else "procurement"),KoshCashEvent.event_type==("EXPECTED_RECEIVABLE" if payload.direction=="SALE" else "SCHEDULED_PAYABLE"),KoshCashEvent.evidence_ref==payload.evidence_ref)) is not None:raise HTTPException(409,"Cash evidence already registered; use the existing event")
    event=KoshCashEvent(seller_id=seller_id,event_type="EXPECTED_RECEIVABLE" if payload.direction=="SALE" else "SCHEDULED_PAYABLE",source_module="sales" if payload.direction=="SALE" else "procurement",evidence_ref=payload.evidence_ref,event_date=payload.payment_date,amount_paise=payload.amount_paise,status="PROPOSED",created_by_user_id=access.user_id);db.add(event);db.flush()
    data=payload.model_dump(mode="json");data["cash_event_id"]=event.id
    row=KoshOperationRecord(seller_id=seller_id,kind=payload.direction,evidence_ref=payload.evidence_ref,data=data,status="PROPOSED",created_by_user_id=access.user_id);db.add(row);db.flush();record(db,seller_id,access,"operations.order.propose",{"record_id":row.id,"cash_event_id":event.id});return out(row)
@router.post("/orders/{record_id}/confirm")
def confirm_order(seller_id:int,record_id:int,db:Session=Depends(get_db),access:AuthorizedSeller=Depends(require_seller_owner)):
    reserve_sqlite_writer(db,renew_read=True);gate(db,seller_id,access.user_id);row=owned(db,seller_id,record_id)
    if row.kind not in {"SALE","PO","PRICE_CHANGE"}:raise HTTPException(409,"This record has no cash-event confirmation")
    event=db.scalar(select(KoshCashEvent).where(KoshCashEvent.id==row.data['cash_event_id'],KoshCashEvent.seller_id==seller_id).with_for_update())
    if event is None:raise HTTPException(409,"Cash-event evidence missing")
    if row.status not in {"PROPOSED","CONFIRMED"}:raise HTTPException(409,"Superseded or rejected proposal cannot be confirmed")
    if row.kind=="PRICE_CHANGE":
        for previous in db.scalars(select(KoshOperationRecord).where(KoshOperationRecord.seller_id==seller_id,KoshOperationRecord.kind=="PRICE_CHANGE",KoshOperationRecord.status=="CONFIRMED",KoshOperationRecord.id!=row.id)):
            if previous.data['purchase_order_id']==row.data['purchase_order_id']:
                previous.status="SUPERSEDED";old_event=db.get(KoshCashEvent,previous.data['cash_event_id']);old_event.status="REJECTED"
    event.status="CONFIRMED";event.confirmed_at=event.confirmed_at or utcnow();event.confirmed_by_user_id=access.user_id;row.status="CONFIRMED";row.updated_at=utcnow();record(db,seller_id,access,"operations.order.confirm",{"record_id":row.id,"cash_event_id":event.id});return out(row)
@router.post("/pricing")
def pricing(seller_id:int,payload:PricingIn,db:Session=Depends(get_db),access:AuthorizedSeller=Depends(require_seller_edit)):
    reserve_sqlite_writer(db,renew_read=True);gate(db,seller_id,access.user_id,source="ADDON:pricing");po=owned(db,seller_id,payload.purchase_order_id,"PO")
    if po.status!="CONFIRMED":raise HTTPException(409,"Confirm the planned purchase first")
    existing=db.scalar(select(KoshOperationRecord).where(KoshOperationRecord.seller_id==seller_id,KoshOperationRecord.kind=="PRICE_CHANGE",KoshOperationRecord.evidence_ref==payload.evidence_ref))
    if existing:
        if existing.data['purchase_order_id']!=po.id or Decimal(existing.data['change_percent'])!=payload.change_percent:raise HTTPException(409,"Price evidence already used with different parameters")
        record(db,seller_id,access,"operations.pricing.propose.repeat",{"record_id":existing.id});return out(existing)
    delta=int((Decimal(po.data['amount_paise'])*payload.change_percent/100).quantize(Decimal(1),rounding=ROUND_HALF_UP))
    event=KoshCashEvent(seller_id=seller_id,event_type="COST_CHANGE",cost_direction="INCREASE" if delta>=0 else "DECREASE",source_module="pricing",evidence_ref=payload.evidence_ref,event_date=date.fromisoformat(po.data['payment_date']),amount_paise=abs(delta),status="PROPOSED",created_by_user_id=access.user_id);db.add(event);db.flush()
    row=KoshOperationRecord(seller_id=seller_id,kind="PRICE_CHANGE",evidence_ref=payload.evidence_ref,data={"purchase_order_id":po.id,"change_percent":str(payload.change_percent),"delta_paise":delta,"cash_event_id":event.id,"material_code":po.data['material_code']},status="PROPOSED",created_by_user_id=access.user_id);db.add(row);db.flush();record(db,seller_id,access,"operations.pricing.propose",{"record_id":row.id,"delta_paise":delta});return out(row)
@router.post("/rfqs")
def rfq(seller_id:int,payload:RFQIn,db:Session=Depends(get_db),access:AuthorizedSeller=Depends(require_seller_edit)):
    reserve_sqlite_writer(db,renew_read=True);gate(db,seller_id,access.user_id,source="ADDON:procurement");recipient=party(db,seller_id,payload.counterparty_id)
    row=KoshAddonDraft(seller_id=seller_id,module="procurement",kind="RFQ_MESSAGE",body=f"Request quotation for {payload.quantity} units of {payload.material_code}, required {payload.needed_date.isoformat()}. Please provide price and delivery terms.",params={"feature_module":"procurement","counterparty_id":recipient.id,"amount_paise":0,"allowlist_key":f"counterparty:{recipient.id}","funding_date":payload.needed_date.isoformat(),"days":0,"cost_paise":0,"evidence_reference":payload.evidence_ref},evidence_hash="",status="DRAFT",created_by_user_id=access.user_id);row.evidence_hash=draft_hash(row);db.add(row);db.flush();record(db,seller_id,access,"operations.rfq.draft",{"draft_id":row.id});return {"id":row.id,"body":row.body,"tier":"T1","drafts":[{"id":d.id,"module":d.module,"kind":d.kind,"body":d.body,"status":d.status} for d in db.scalars(select(KoshAddonDraft).where(KoshAddonDraft.seller_id==seller_id))],"external_delivery":False}
@router.post("/drafts/{draft_id}/intent")
def intent(seller_id:int,draft_id:int,db:Session=Depends(get_db),access:AuthorizedSeller=Depends(require_seller_edit)):
    try:row=create_from_draft(db,seller_id=seller_id,draft_id=draft_id,creator_id=access.user_id)
    except LookupError as exc:raise HTTPException(404,str(exc))
    except ValueError as exc:raise HTTPException(409,str(exc))
    db.commit();return out(row)


from app.schemas.native_operations import ResourceIn,WorkflowIn,NotificationIn,AgentIn,CompletionIn,MaterialCSVIn
from app.finance.operations import analytics
from app.finance.kosh_chat import GUARD
from app.database.kosh_models import KoshActionIntent,KoshSandboxExecution
import csv,io

@router.get("/dashboard")
def dashboard(seller_id:int,db:Session=Depends(get_db),access:AuthorizedSeller=Depends(require_seller_read)):
    result=analytics(db,seller_id);record(db,seller_id,access,"operations.dashboard.read",{},"T0");return {**result,"role":access.role}

@router.post("/resources")
def resource(seller_id:int,payload:ResourceIn,db:Session=Depends(get_db),access:AuthorizedSeller=Depends(require_seller_edit)):
    reserve_sqlite_writer(db,renew_read=True);gate(db,seller_id,access.user_id)
    data=payload.model_dump(mode='json');kind=data.pop('kind');evidence=data.pop('evidence_ref')
    as_of=get_settings().kosh_as_of_date or date.today().isoformat()
    if data.get('observed_date') and data['observed_date']>as_of:raise HTTPException(422,'An observed fact cannot have a future date')
    feature={'MATERIAL':'inventory','INVENTORY':'inventory','QUOTE':'procurement','SHIPMENT':'supply_chain','SHIPMENT_STEP':'supply_chain','ONBOARDING':'onboarding','KNOWLEDGE':'knowledge','MARKET_SIGNAL':'market','GOAL':'goals','TASK':'goals','STRUCTURAL_RISK':'pricing'}[kind]
    gate(db,seller_id,access.user_id,source=f'ADDON:{feature}')
    for key,value in data.items():
        if value is None:continue
        if key in {'supplier_id','counterparty_id'}:party(db,seller_id,value)
        if key in {'material_id','purchase_order_id','shipment_id','goal_id'}:owned(db,seller_id,value,{'material_id':'MATERIAL','purchase_order_id':'PO','shipment_id':'SHIPMENT','goal_id':'GOAL'}[key])
        if key=='rfq_draft_id':
            draft=db.scalar(select(KoshAddonDraft).where(KoshAddonDraft.id==value,KoshAddonDraft.seller_id==seller_id,KoshAddonDraft.kind=='RFQ_MESSAGE'))
            if draft is None or draft.params['counterparty_id']!=data['supplier_id']:raise HTTPException(404,'Owned RFQ and supplier evidence required')
    suspected=any(GUARD.search(str(data.get(key,''))) for key in ('text','headline','observation'))
    row=KoshOperationRecord(seller_id=seller_id,kind=kind,evidence_ref=evidence,data=data,status='REVIEW_REQUIRED' if suspected else 'PROPOSED',created_by_user_id=access.user_id);db.add(row);db.flush()
    if suspected:append_event(db,seller_id=seller_id,actor_type='SYSTEM',actor_id=None,action='security.injection_detected',tier='T0',payload={'operation_record_id':row.id},policy_decision='DENY')
    record(db,seller_id,access,'operations.resource.propose',{'id':row.id,'kind':kind});return out(row)

@router.post('/resources/{record_id}/confirm')
def confirm_resource(seller_id:int,record_id:int,db:Session=Depends(get_db),access:AuthorizedSeller=Depends(require_seller_owner)):
    reserve_sqlite_writer(db,renew_read=True);gate(db,seller_id,access.user_id);row=owned(db,seller_id,record_id)
    if row.kind not in {'MATERIAL','INVENTORY','QUOTE','SHIPMENT','SHIPMENT_STEP','GOAL','TASK','KNOWLEDGE','ONBOARDING','MARKET_SIGNAL','STRUCTURAL_RISK'}:raise HTTPException(409,'Use the dedicated confirmation for this resource')
    if row.status=='REVIEW_REQUIRED':raise HTTPException(409,'Untrusted instruction text cannot be confirmed as operating evidence')
    if row.status=='CONFIRMED':record(db,seller_id,access,'operations.resource.confirm.repeat',{'id':row.id});return out(row)
    row.status='CONFIRMED';row.updated_at=utcnow()
    if row.kind=='MATERIAL':
        shortage=max(0,row.data['reorder_point']-row.data['quantity']);amount=shortage*row.data['unit_cost_paise']
        if amount:
            from app.core.config import get_settings
            event=KoshCashEvent(seller_id=seller_id,event_type='FINANCING_NEED',source_module='operations',evidence_ref=f'material:{row.id}',event_date=date.fromisoformat(get_settings().kosh_as_of_date or date.today().isoformat()),amount_paise=amount,status='PROPOSED',created_by_user_id=access.user_id);db.add(event);db.flush();row.data={**row.data,'cash_event_id':event.id}
    if row.kind=='SHIPMENT_STEP' and row.data.get('documented_payment_date'):
        shipment=owned(db,seller_id,row.data['shipment_id'],'SHIPMENT');po=owned(db,seller_id,shipment.data['purchase_order_id'],'PO')
        event=db.scalar(select(KoshCashEvent).where(KoshCashEvent.id==po.data['cash_event_id'],KoshCashEvent.seller_id==seller_id).with_for_update())
        if event is None or event.status!='CONFIRMED':raise HTTPException(409,'Confirmed payable required for timing update')
        previous=event.event_date;event.event_date=date.fromisoformat(row.data['documented_payment_date']);row.data={**row.data,'previous_payment_date':previous.isoformat(),'cash_event_id':event.id}
    record(db,seller_id,access,'operations.resource.confirm',{'id':row.id,'kind':row.kind});return out(row)

@router.post('/resources/{record_id}/complete')
def complete_task(seller_id:int,record_id:int,payload:CompletionIn,db:Session=Depends(get_db),access:AuthorizedSeller=Depends(require_seller_owner)):
    reserve_sqlite_writer(db,renew_read=True);gate(db,seller_id,access.user_id);row=owned(db,seller_id,record_id,'TASK')
    if row.status!='CONFIRMED':raise HTTPException(409,'Confirm the task before completion')
    row.status='COMPLETED';row.data={**row.data,'completion_evidence':payload.evidence_ref};row.updated_at=utcnow();record(db,seller_id,access,'operations.task.complete',{'id':row.id,'evidence_ref':payload.evidence_ref});return out(row)

@router.post('/workflows')
def workflow(seller_id:int,payload:WorkflowIn,db:Session=Depends(get_db),access:AuthorizedSeller=Depends(require_seller_edit)):
    reserve_sqlite_writer(db,renew_read=True);gate(db,seller_id,access.user_id,source='ADDON:workflows')
    draft=db.scalar(select(KoshAddonDraft).where(KoshAddonDraft.id==payload.draft_id,KoshAddonDraft.seller_id==seller_id))
    if draft is None:raise HTTPException(404,'Draft not found')
    row=KoshOperationRecord(seller_id=seller_id,kind='WORKFLOW',evidence_ref=payload.evidence_ref,data={'draft_id':draft.id,'steps':[{'name':'Observe evidence','status':'DONE'},{'name':'Validate trusted draft','status':'PENDING'},{'name':'Human approval','status':'PAUSED'},{'name':'Sandbox execution','status':'PENDING'},{'name':'Reconcile','status':'PENDING'}]},status='DRAFT',created_by_user_id=access.user_id);db.add(row);db.flush();record(db,seller_id,access,'operations.workflow.create',{'id':row.id});return out(row)

@router.post('/workflows/{record_id}/advance')
def advance(seller_id:int,record_id:int,db:Session=Depends(get_db),access:AuthorizedSeller=Depends(require_seller_edit)):
    reserve_sqlite_writer(db,renew_read=True);gate(db,seller_id,access.user_id,source='ADDON:workflows');row=owned(db,seller_id,record_id,'WORKFLOW');data=dict(row.data)
    if not data.get('intent_id'):
        try:intent=create_from_draft(db,seller_id=seller_id,draft_id=data['draft_id'],creator_id=access.user_id)
        except (ValueError,LookupError) as exc:raise HTTPException(409,str(exc))
        data['intent_id']=intent.id
    else:
        intent=db.scalar(select(KoshActionIntent).where(KoshActionIntent.id==data['intent_id'],KoshActionIntent.seller_id==seller_id))
        if intent is None:raise HTTPException(409,'Workflow intent missing')
    execution=db.scalar(select(KoshSandboxExecution).where(KoshSandboxExecution.intent_id==intent.id,KoshSandboxExecution.seller_id==seller_id))
    status='COMPLETED' if intent.status=='SUCCEEDED' and execution and execution.status=='SETTLED' else 'EXECUTION_PAUSED' if intent.status=='APPROVED' else 'BLOCKED' if intent.status in {'BLOCKED','FAILED','REJECTED','EXPIRED'} else 'APPROVAL_PAUSED'
    data['steps']=[{'name':'Observe evidence','status':'DONE'},{'name':'Validate trusted draft','status':'DONE'},{'name':'Human approval','status':'DONE' if intent.status in {'APPROVED','EXECUTING','SUCCEEDED'} else 'PAUSED'},{'name':'Sandbox execution','status':'DONE' if status=='COMPLETED' else 'PAUSED'},{'name':'Reconcile','status':'DONE' if status=='COMPLETED' else 'PENDING'}];data['history']=[*data.get('history',[]),{'at':utcnow().isoformat()+'Z','status':status}];row.data=data;row.status=status;row.updated_at=utcnow();record(db,seller_id,access,'operations.workflow.advance',{'id':row.id,'intent_id':intent.id,'status':status});return out(row)

@router.post('/notifications')
def notification(seller_id:int,payload:NotificationIn,db:Session=Depends(get_db),access:AuthorizedSeller=Depends(require_seller_edit)):
    reserve_sqlite_writer(db,renew_read=True);gate(db,seller_id,access.user_id,source='ADDON:notifications');resource=owned(db,seller_id,payload.record_id);recipient=party(db,seller_id,payload.counterparty_id)
    row=KoshAddonDraft(seller_id=seller_id,module='operations',kind='NOTIFICATION_MESSAGE',params={'feature_module':'notifications','channel':payload.channel,'counterparty_id':recipient.id,'allowlist_key':f'counterparty:{recipient.id}','amount_paise':0,'funding_date':(get_settings().kosh_as_of_date or date.today().isoformat()),'days':0,'cost_paise':0,'evidence_reference':payload.evidence_ref},body=f'Operational update: record {resource.id} ({resource.kind}) has status {resource.status}. Please contact the business for details.',evidence_hash='',status='DRAFT',created_by_user_id=access.user_id);row.evidence_hash=draft_hash(row);db.add(row);db.flush();record(db,seller_id,access,'operations.notification.draft',{'draft_id':row.id,'record_id':resource.id});return {'id':row.id,'body':row.body,'tier':'T1','external_delivery':False}

@router.post('/agents/run')
def agent(seller_id:int,payload:AgentIn,db:Session=Depends(get_db),access:AuthorizedSeller=Depends(require_seller_edit)):
    reserve_sqlite_writer(db,renew_read=True);gate(db,seller_id,access.user_id);facts=analytics(db,seller_id)
    proposals=[]
    if payload.agent in {'procurement','supplier','pricing','executive'}:proposals.extend({'type':'REORDER_PROPOSAL','material_id':i['material_id'],'amount_paise':i['shortage_cost_paise'],'requires_owner_confirmation':True} for i in facts['inventory'] if i['shortage_units'])
    if payload.agent in {'collections','customer','sales','executive'}:proposals.append({'type':'REVIEW_OWNED_RECEIVABLES','href':'/operations/collections','requires_human_approval_before_send':True})
    if payload.agent in {'reporting','revenue','market'}:proposals.append({'type':'READ_COMPUTED_SIGNAL','href':{'reporting':'/operations/reports','revenue':'/operations/revenue','market':'/operations/pricing'}[payload.agent]})
    row=KoshOperationRecord(seller_id=seller_id,kind='AGENT_RUN',evidence_ref=payload.evidence_ref,data={'agent':payload.agent,'proposals':proposals,'execution_authority':'NONE'},status='COMPLETED',created_by_user_id=access.user_id);db.add(row);db.flush();record(db,seller_id,access,'operations.agent.run',{'id':row.id,'agent':payload.agent});return out(row)

@router.post('/materials/import')
def material_csv(seller_id:int,payload:MaterialCSVIn,db:Session=Depends(get_db),access:AuthorizedSeller=Depends(require_seller_edit)):
    from app.schemas.native_operations import MaterialIn
    reserve_sqlite_writer(db,renew_read=True);gate(db,seller_id,access.user_id)
    parsed=list(csv.DictReader(io.StringIO(payload.csv_text)))
    if not parsed or len(parsed)>200:raise HTTPException(422,'Between one and 200 material rows required')
    values=[]
    try:
        for item in parsed:values.append(MaterialIn(kind='MATERIAL',material_code=item['material_code'],quantity=int(item['quantity']),reorder_point=int(item['reorder_point']),unit_cost_paise=int(item['unit_cost_paise']),evidence_ref=payload.evidence_ref))
    except (KeyError,ValueError) as exc:raise HTTPException(422,'Use material_code, quantity, reorder_point, unit_cost_paise with integer amounts') from exc
    ids=[]
    for item in values:
        data=item.model_dump(mode='json');data.pop('kind');data.pop('evidence_ref');row=KoshOperationRecord(seller_id=seller_id,kind='MATERIAL',evidence_ref=payload.evidence_ref,data=data,status='PROPOSED',created_by_user_id=access.user_id);db.add(row);db.flush();ids.append(row.id)
    record(db,seller_id,access,'operations.material_csv.propose',{'ids':ids,'evidence_ref':payload.evidence_ref});return {'ids':ids,'status':'PROPOSED','confirmation_required':True}


from app.schemas.native_operations import CounterpartyIn,ConversationIn
from app.finance.operations import conversation_candidates
@router.post('/counterparties')
def register_counterparty(seller_id:int,payload:CounterpartyIn,db:Session=Depends(get_db),access:AuthorizedSeller=Depends(require_seller_owner)):
    reserve_sqlite_writer(db,renew_read=True);gate(db,seller_id,access.user_id)
    if GUARD.search(payload.name):raise HTTPException(422,'Instruction-like identity requires review')
    existing=db.scalar(select(KoshCounterparty).where(KoshCounterparty.seller_id==seller_id,KoshCounterparty.name==payload.name,KoshCounterparty.kind==payload.kind))
    if existing:record(db,seller_id,access,'operations.counterparty.repeat',{'id':existing.id});return {'id':existing.id,'status':'REGISTERED'}
    contact=KoshCounterparty(seller_id=seller_id,name=payload.name,kind=payload.kind);db.add(contact);db.flush()
    mission=KoshOperationRecord(seller_id=seller_id,kind='SALES_MISSION' if payload.kind=='CUSTOMER' else 'PROCUREMENT_MISSION',evidence_ref=payload.evidence_ref,data={'counterparty_id':contact.id,'contact_label':payload.contact_label,'amount_paise':None,'cost_paise':None,'payment_date':None,'next_step':'Document sales order or purchase requirement; no automatic messages'},status='GATHER_EVIDENCE',created_by_user_id=access.user_id);db.add(mission);db.flush();record(db,seller_id,access,'operations.counterparty.register',{'id':contact.id,'mission_id':mission.id});return {'id':contact.id,'mission_id':mission.id,'status':'REGISTERED','send_permission':'Allowlist and 24-hour cool-off still required'}
@router.post('/conversations')
def conversation(seller_id:int,payload:ConversationIn,db:Session=Depends(get_db),access:AuthorizedSeller=Depends(require_seller_edit)):
    reserve_sqlite_writer(db,renew_read=True);gate(db,seller_id,access.user_id,source="ADDON:sales" if payload.direction=="SALE" else "ADDON:procurement");party(db,seller_id,payload.counterparty_id)
    data=payload.model_dump(mode='json');evidence=data.pop('evidence_ref');data['candidates']=conversation_candidates(payload.text);data['execution_authority']='NONE'
    row=KoshOperationRecord(seller_id=seller_id,kind='CONVERSATION',evidence_ref=evidence,data=data,status='REVIEW_REQUIRED',created_by_user_id=access.user_id);db.add(row);db.flush()
    if GUARD.search(payload.text):append_event(db,seller_id=seller_id,actor_type='SYSTEM',actor_id=None,action='security.injection_detected',tier='T0',payload={'conversation_id':row.id},policy_decision='DENY')
    record(db,seller_id,access,'operations.conversation.record',{'id':row.id,'channel':payload.channel});return out(row)


@router.post('/records/{record_id}/reject')
def reject_record(seller_id:int,record_id:int,payload:CompletionIn,db:Session=Depends(get_db),access:AuthorizedSeller=Depends(require_seller_owner)):
    reserve_sqlite_writer(db,renew_read=True);gate(db,seller_id,access.user_id);row=owned(db,seller_id,record_id)
    if row.status in {'EXECUTED','COMPLETED','SUPERSEDED'}:raise HTTPException(409,'Executed or superseded evidence cannot be rejected')
    if row.kind=='WORKFLOW' and row.data.get('intent_id'):
        from app.actions.approvals import reject,ActionError
        try:reject(db,seller_id=seller_id,intent_id=row.data['intent_id'],actor_id=access.user_id)
        except ActionError as exc:raise HTTPException(exc.status_code,str(exc))
    if row.data.get('cash_event_id'):
        event=db.scalar(select(KoshCashEvent).where(KoshCashEvent.id==row.data['cash_event_id'],KoshCashEvent.seller_id==seller_id).with_for_update())
        if event is not None:event.status='REJECTED'
    row.status='REJECTED';row.data={**row.data,'rejection_evidence':payload.evidence_ref};row.updated_at=utcnow();record(db,seller_id,access,'operations.record.reject',{'id':row.id,'evidence_ref':payload.evidence_ref});return out(row)

@router.post('/demo')
def demo(seller_id:int,db:Session=Depends(get_db),access:AuthorizedSeller=Depends(require_seller_edit)):
    reserve_sqlite_writer(db,renew_read=True);gate(db,seller_id,access.user_id);facts=analytics(db,seller_id)
    steps=[{'name':'Observe owned cash and inventory','status':'DONE','inventory_records':len(facts['inventory'])},{'name':'Review shortage proposals','status':'DONE','shortage_count':sum(bool(r['shortage_units']) for r in facts['inventory'])},{'name':'Check quote evidence','status':'REVIEW_REQUIRED' if not facts['quotes'] or any(q['status']=='REVIEW_REQUIRED' for q in facts['quotes']) else 'DONE'},{'name':'Human approval before any outbound step','status':'PAUSED'}]
    row=KoshOperationRecord(seller_id=seller_id,kind='DEMO_RUN',evidence_ref='owner:offline-business-review',data={'steps':steps,'cash_posted_paise':0,'messages_sent':0,'basis':'Owned facts only; no source inputs changed or outcomes invented'},status='INTERNAL_REVIEW',created_by_user_id=access.user_id);db.add(row);db.flush();record(db,seller_id,access,'operations.demo.review',{'id':row.id});return out(row)


from app.schemas.native_operations import SurchargeIn
from fastapi import Query
@router.get('/knowledge/search')
def knowledge_search(seller_id:int,q:str=Query(min_length=1,max_length=100),db:Session=Depends(get_db),access:AuthorizedSeller=Depends(require_seller_read)):
    tokens=set(q.lower().split());items=[]
    for row in db.scalars(select(KoshOperationRecord).where(KoshOperationRecord.seller_id==seller_id,KoshOperationRecord.kind=='KNOWLEDGE')):
        text=' '.join(str(row.data.get(k,'')) for k in ('title','text','topic','tags'));count=sum(token in text.lower() for token in tokens)
        if count:items.append({'id':row.id,'status':row.status,'evidence_ref':row.evidence_ref,'match_count':count,'data':row.data,'execution_authority':'NONE'})
    items.sort(key=lambda r:(-r['match_count'],r['id']));record(db,seller_id,access,'operations.knowledge.search',{'matches':len(items)},'T0');return {'items':items}
@router.get('/orders/{record_id}/document')
def order_document(seller_id:int,record_id:int,db:Session=Depends(get_db),access:AuthorizedSeller=Depends(require_seller_read)):
    row=owned(db,seller_id,record_id)
    if row.kind not in {'SALE','PO'}:raise HTTPException(404,'Order document not found')
    recipient=party(db,seller_id,row.data['counterparty_id'])
    body=f"INTERNAL {'PURCHASE ORDER' if row.kind=='PO' else 'SALES ORDER'} #{row.id}\nStatus: {row.status}\nCounterparty: {recipient.name}\nMaterial: {row.data['material_code']}\nAmount: INR {Decimal(row.data['amount_paise'])/100:,.2f}\nPayment date: {row.data['payment_date']}\nEvidence: {row.evidence_ref}\nNo external commitment or dispatch is implied. Approval-gated sandbox outreach only."
    record(db,seller_id,access,'operations.order.document.read',{'id':row.id},'T0');return {'id':row.id,'body':body,'internal_only':True}
@router.post('/surcharge')
def surcharge(seller_id:int,payload:SurchargeIn,db:Session=Depends(get_db),access:AuthorizedSeller=Depends(require_seller_edit)):
    reserve_sqlite_writer(db,renew_read=True);gate(db,seller_id,access.user_id,source='ADDON:pricing');sale=owned(db,seller_id,payload.sales_order_id,'SALE');cost=sale.data.get('estimated_cost_paise')
    if sale.status!='CONFIRMED' or cost is None:result={'status':'REVIEW_REQUIRED','reason':'Confirmed sales order and documented estimated production cost required.'}
    else:
        delta=int((Decimal(cost)*payload.cost_change_percent/100).quantize(Decimal(1),rounding=ROUND_HALF_UP));result={'status':'COMPUTED_SCENARIO','original_margin_paise':sale.data['amount_paise']-cost,'cost_delta_paise':delta,'revised_margin_without_surcharge_paise':sale.data['amount_paise']-cost-delta,'surcharge_to_preserve_estimated_margin_paise':delta,'reason':'Owner-supplied cost estimate; hypothetical pass-through is not a customer commitment or receipt.'}
    row=KoshOperationRecord(seller_id=seller_id,kind='SURCHARGE_SCENARIO',evidence_ref=payload.evidence_ref,data={'sales_order_id':sale.id,'result':result},status=result['status'],created_by_user_id=access.user_id);db.add(row);db.flush();record(db,seller_id,access,'operations.surcharge.scenario',{'id':row.id});return result


@router.get('/messaging-status')
def messaging_status(seller_id:int,db:Session=Depends(get_db),access:AuthorizedSeller=Depends(require_seller_read)):
    import importlib.util
    missing=[name for name in ('segno','neonize') if importlib.util.find_spec(name) is None]
    result={'transport':'SANDBOX_ONLY','external_delivery':False,'device_pairing':'BLOCKED_OFFLINE','qr_code':None,'missing_packages':missing,'reason':'Live device pairing requires unavailable dependencies and external account authentication. Native notifications use the approved sandbox adapter and Kosh login. Installing packages alone does not authorize or enable live delivery.','owner_command':'.\\.venv\\Scripts\\python.exe -m pip install segno neonize'}
    record(db,seller_id,access,'operations.messaging_status.read',{},'T0');return result
