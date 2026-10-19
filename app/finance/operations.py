"""Deterministic operational analytics over seller-owned persisted facts."""
from decimal import Decimal
from sqlalchemy import select
from app.database.kosh_models import KoshOperationRecord,KoshCashEvent,KoshActionIntent,KoshSandboxOutbox,KoshAuditEntry,KoshForecastRun,KoshForecastWeek,KoshAddonDraft

def analytics(db,seller_id):
    rows=list(db.scalars(select(KoshOperationRecord).where(KoshOperationRecord.seller_id==seller_id).order_by(KoshOperationRecord.id)))
    confirmed=[r for r in rows if r.status in {"CONFIRMED","COMPLETED"}]
    materials={r.data['material_code']:r for r in confirmed if r.kind=='MATERIAL'}
    inventory=[]
    for code,material in materials.items():
        adjustments=[r for r in confirmed if r.kind=='INVENTORY' and r.data['material_id']==material.id]
        quantity=adjustments[-1].data['quantity'] if adjustments else material.data['quantity']
        shortage=max(0,material.data['reorder_point']-quantity)
        inventory.append({'material_id':material.id,'material_code':code,'quantity':quantity,'reorder_point':material.data['reorder_point'],'shortage_units':shortage,'shortage_cost_paise':shortage*material.data['unit_cost_paise'],'signal':'REORDER_PROPOSAL' if shortage else 'WITHIN_DOCUMENTED_BUFFER'})
    quotes=[]
    for r in confirmed:
        if r.kind!='QUOTE':continue
        complete=all(r.data.get(k) is not None for k in ('lead_days','quality_score','reliability_score'))
        quotes.append({'id':r.id,**r.data,'status':'COMPARABLE' if complete else 'REVIEW_REQUIRED','scoring_assumption':'Illustrative weights: price 55%, lead time 25%, quality 10%, reliability 10%; not a probability.','reason':'Documented price, lead time, quality and reliability required; missing scores are never invented.'})
    groups={}
    for quote in quotes:
        rfq=db.get(KoshAddonDraft,quote['rfq_draft_id'])
        key=(rfq.params['material_code'],rfq.params['quantity'],rfq.params['funding_date']) if rfq and 'material_code' in rfq.params and 'quantity' in rfq.params else quote['rfq_draft_id']
        groups.setdefault(key,[]).append(quote)
    for group in groups.values():
        eligible=[q for q in group if q['status']=='COMPARABLE']
        if not eligible:continue
        min_price=min(q['price_paise'] for q in eligible);min_lead=min(q['lead_days'] for q in eligible)
        for q in eligible:
            q['score']=str(Decimal('.55')*Decimal(min_price)/q['price_paise']+Decimal('.25')*(Decimal(min_lead+1)/Decimal(q['lead_days']+1))+Decimal('.10')*Decimal(q['quality_score'])+Decimal('.10')*Decimal(q['reliability_score']))
        winner=max(eligible,key=lambda q:(Decimal(q['score']),-q['id']))
        for q in eligible:q['recommended']=q['id']==winner['id']
    sales=[]
    for row in confirmed:
        if row.kind=='SALE':
            cost=row.data.get('estimated_cost_paise');amount=row.data['amount_paise']
            sales.append({'order_id':row.id,'estimated_margin_paise':amount-cost if cost is not None else None,'estimated_margin_rate':str(Decimal(amount-cost)/amount) if cost is not None else None,'status':'ESTIMATE' if cost is not None else 'REVIEW_REQUIRED','source':'Owner-supplied cost estimate, not realized profit'})
    workflow=[]
    for row in rows:
        if row.kind=='WORKFLOW':
            intent=db.scalar(select(KoshActionIntent).where(KoshActionIntent.id==row.data.get('intent_id'),KoshActionIntent.seller_id==seller_id)) if row.data.get('intent_id') else None
            workflow.append({'id':row.id,'status':row.status,'intent_status':intent.status if intent else None,'steps':row.data.get('steps',[]),'intent_id':intent.id if intent else None})
    goal_measurements=[]
    run=db.scalar(select(KoshForecastRun).where(KoshForecastRun.seller_id==seller_id,KoshForecastRun.status=='SUCCESS').order_by(KoshForecastRun.id.desc()))
    weeks=list(db.scalars(select(KoshForecastWeek).where(KoshForecastWeek.run_id==run.id))) if run else []
    for goal in (r for r in confirmed if r.kind=='GOAL'):
        measurement=None;status='REVIEW_REQUIRED';source=None
        if goal.data['goal']=='CASH_BUFFER':
            week=next((w for w in weeks if w.week_start.isoformat()<=goal.data['due_date']<=w.week_end.isoformat()),None)
            if week:measurement=week.p50_closing_balance_paise;status='PROJECTED';source=f'forecast:{run.id}:week:{week.week_index}'
        elif goal.data['goal']=='MARGIN' and sales and all(s['estimated_margin_paise'] is not None for s in sales):measurement=sum(s['estimated_margin_paise'] for s in sales);status='ESTIMATE';source='Owner-supplied sales cost estimates'
        goal_measurements.append({'goal_id':goal.id,'goal':goal.data['goal'],'status':status,'measured_paise':measurement,'gap_paise':max(0,goal.data['target_paise']-measurement) if measurement is not None else None,'source':source,'reason':'Projected/estimated values do not prove realized performance; collections require actual receipt evidence.'})
    signals=[{'id':r.id,'kind':r.kind,'data':r.data,'status':r.status} for r in rows if r.kind in {'MARKET_SIGNAL','STRUCTURAL_RISK','KNOWLEDGE','GOAL','TASK','SHIPMENT','SHIPMENT_STEP','ONBOARDING'}]
    return {'goal_measurements':goal_measurements,'inventory':inventory,'quotes':quotes,'sales_margins':sales,'workflows':workflow,'signals':signals,'cash_events':[{'id':e.id,'status':e.status,'event_type':e.event_type,'amount_paise':e.amount_paise} for e in db.scalars(select(KoshCashEvent).where(KoshCashEvent.seller_id==seller_id))],'outbox_count':len(list(db.scalars(select(KoshSandboxOutbox.id).where(KoshSandboxOutbox.seller_id==seller_id)))),'timeline':[{'sequence':a.sequence,'action':a.action,'tier':a.tier} for a in db.scalars(select(KoshAuditEntry).where(KoshAuditEntry.seller_id==seller_id).order_by(KoshAuditEntry.sequence.desc()).limit(30))],'agent_rule':'Deterministic proposals and evidence checks only; outbound steps pause for Stage 4 approval.'}


def conversation_candidates(text):
    import re
    from app.finance.intake.money import parse_inr_to_paise
    price=re.search(r'(?:INR|Rs\.?)\s*([0-9,]+(?:\.[0-9]{1,2})?)',text,re.I)
    lead=re.search(r'(\d{1,3})\s*days',text,re.I)
    return {'candidate_price_paise':parse_inr_to_paise(price.group(1))[0] if price else None,'candidate_lead_days':int(lead.group(1)) if lead else None,'status':'REVIEW_REQUIRED','reason':'Incoming text is untrusted data; confirm a separate typed quote before ranking or cash use.'}
