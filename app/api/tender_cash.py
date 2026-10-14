"""Matched tender affordability as a labelled scenario, never a funding action."""
from datetime import date
import json
from decimal import Decimal
from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel,ConfigDict,StrictInt,StrictBool,Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.api.deps import get_db
from app.api.seller_authorization import AuthorizedSeller,require_seller_read,require_seller_edit
from app.database.models import Tender
from app.database.matching_models import SellerTenderMatch
from app.database.kosh_models import KoshForecastRun,KoshOperationRecord,KoshCashEvent
from app.database.session import reserve_sqlite_writer
from app.finance.forecast import load_inputs,simulate,week_bounds
from app.audit.ledger import append_event,canonical_json
from app.policy.internal import gate
from app.core.config import get_settings
router=APIRouter(prefix="/api/kosh/sellers/{seller_id}/tender-to-cash",tags=["kosh-tender-cash"])
class TenderCashIn(BaseModel):
    model_config=ConfigDict(extra='forbid')
    emd_paise:StrictInt|None=Field(default=None,ge=0,le=1000000000000000)
    emd_date:date|None=None
    performance_security_cash_paise:StrictInt|None=Field(default=None,ge=0,le=1000000000000000)
    security_date:date|None=None
    production_cost_paise:StrictInt|None=Field(default=None,ge=0,le=1000000000000000)
    production_date:date|None=None
    contract_receivable_paise:StrictInt|None=Field(default=None,ge=0,le=1000000000000000)
    government_payment_date:date|None=None
    emd_refund_paise:StrictInt|None=Field(default=None,ge=0,le=1000000000000000)
    emd_refund_date:date|None=None
    cpse_buyer:StrictBool|None=None
    evidence_ref:str=Field(min_length=1,max_length=160)
def record(db,seller_id,access,action,payload,tier='T0'):
    append_event(db,seller_id=seller_id,actor_type='HUMAN',actor_id=str(access.user_id),action=action,tier=tier,payload=payload,policy_decision='ALLOW');db.commit()
@router.get('')
def listing(seller_id:int,db:Session=Depends(get_db),access:AuthorizedSeller=Depends(require_seller_read)):
    items=[{'tender_id':t.id,'bid_number':t.bid_number,'title':t.title,'buyer':t.buyer_name,'match_status':m.match_status} for t,m in db.execute(select(Tender,SellerTenderMatch).join(SellerTenderMatch,SellerTenderMatch.tender_id==Tender.id).where(SellerTenderMatch.seller_id==seller_id,SellerTenderMatch.match_status=='MATCHED'))]
    record(db,seller_id,access,'tender_cash.read',{});return {'items':items}
@router.post('/{tender_id}')
def scenario(seller_id:int,tender_id:int,payload:TenderCashIn,db:Session=Depends(get_db),access:AuthorizedSeller=Depends(require_seller_edit)):
    reserve_sqlite_writer(db,renew_read=True);gate(db,seller_id,access.user_id,source='ADDON:tender_to_cash')
    match=db.scalar(select(SellerTenderMatch).where(SellerTenderMatch.seller_id==seller_id,SellerTenderMatch.tender_id==tender_id))
    if match is None:raise HTTPException(404,'Tender not available in this seller scope')
    if match.match_status!='MATCHED':raise HTTPException(409,'A matched tender is required; review missing eligibility facts first')
    missing=[];events=[]
    for amount_field,date_field,sign in [('emd_paise','emd_date',-1),('performance_security_cash_paise','security_date',-1),('production_cost_paise','production_date',-1),('contract_receivable_paise','government_payment_date',1),('emd_refund_paise','emd_refund_date',1)]:
        amount=getattr(payload,amount_field);day=getattr(payload,date_field)
        if amount is None:missing.append(amount_field)
        elif amount and day is None:missing.append(date_field)
        elif amount:events.append({'date':day.isoformat(),'amount_paise':amount*sign})
    if payload.cpse_buyer is None:missing.append('cpse_buyer_evidence')
    suggestions=[{'product':'GEM_SAHAY_PO_FINANCE','status':'REVIEW_REQUIRED','reason':'Required evidence missing and current primary-source product terms unverified.'},{'product':'TREDS_INVOICE_DISCOUNTING','status':'REVIEW_REQUIRED','reason':'CPSE buyer flag: verify TReDS onboarding, accepted invoice and future invoice eligibility before relying.' if payload.cpse_buyer is True else 'Buyer classification and accepted-invoice evidence required.'}]
    result={'status':'REVIEW_REQUIRED' if missing else 'COMPUTED_SCENARIO','missing':missing,'scenario_only':True,'financing_suggestions':suggestions,'evidence_ref':payload.evidence_ref,'assumptions':'Owner-supplied scenario cash deposits/costs and payment dates. Security face value is not assumed to be a cash outflow. Unknown refunds are not fabricated.'}
    if not missing:
        run=db.scalar(select(KoshForecastRun).where(KoshForecastRun.seller_id==seller_id,KoshForecastRun.status=='SUCCESS').order_by(KoshForecastRun.id.desc()))
        if run is None:raise HTTPException(409,'Run a base cash forecast first')
        if any(date.fromisoformat(e['date'])<run.as_of_date for e in events):raise HTTPException(422,'New order scenario dates cannot precede financial as-of date')
        outside=any(date.fromisoformat(e['date'])>week_bounds(run.as_of_date,13)[1] for e in events)
        if outside:result['status']='REVIEW_REQUIRED';result['missing'].append('cash_timing_outside_13_week_horizon')
        cash=0;peak=0
        for event in sorted(events,key=lambda e:(e['date'],e['amount_paise'])):cash+=event['amount_paise'];peak=max(peak,-cash)
        inputs=load_inputs(db,seller_id,run.as_of_date,include_addon_events=run.params.get('include_addon_events',True),include_customer_history=run.params.get('include_customer_history',False),include_revenue_signal=run.params.get('include_revenue_signal',False))
        kwargs=dict(as_of=run.as_of_date,n_paths=run.n_paths,seed=run.seed,include_forecast_sales=run.include_forecast_sales,buffer_paise=run.buffer_paise)
        base=simulate(inputs,**kwargs);forecast=simulate(inputs,extra_inflows=events,**kwargs)
        target=get_settings().kosh_plan_target_prob;threshold=Decimal(str(get_settings().kosh_alert_threshold));worst=max(Decimal(str(w['prob_below_buffer'])) for w in forecast['weeks'])
        result.update(working_capital_needed_paise=peak,base_run_id=run.id,seed=run.seed,base_weeks=base['weeks'],scenario_weeks=forecast['weeks'],safety='REVIEW_REQUIRED' if outside else 'SCENARIO_TARGET_MET' if worst<=target and worst<threshold else 'FINANCING_OR_REVIEW_NEEDED',safety_reason='Same-seed weekly scenario; no funding or tender award is executed.')
        event=KoshCashEvent(seller_id=seller_id,event_type='FINANCING_NEED',source_module='tender_to_cash',evidence_ref=f'tender:{tender_id}:{payload.evidence_ref}',event_date=min(date.fromisoformat(e['date']) for e in events) if events else run.as_of_date,amount_paise=peak,status='PROPOSED',created_by_user_id=access.user_id)
        existing=db.scalar(select(KoshCashEvent).where(KoshCashEvent.seller_id==seller_id,KoshCashEvent.source_module=='tender_to_cash',KoshCashEvent.evidence_ref==event.evidence_ref,KoshCashEvent.event_type=='FINANCING_NEED'))
        if existing:
            if existing.amount_paise!=peak:raise HTTPException(409,'Scenario evidence already used with different capital requirement')
            event=existing
        else:db.add(event);db.flush()
        result['financing_need_event_id']=event.id
    result=json.loads(canonical_json(result))
    row=KoshOperationRecord(seller_id=seller_id,kind='TENDER_SCENARIO',evidence_ref=payload.evidence_ref,data={'tender_id':tender_id,'inputs':payload.model_dump(mode='json'),'result':result},status=result['status'],created_by_user_id=access.user_id);db.add(row);db.flush();record(db,seller_id,access,'tender_cash.scenario',{'id':row.id,'tender_id':tender_id,'status':result['status']},'T1');return {'id':row.id,**result}
