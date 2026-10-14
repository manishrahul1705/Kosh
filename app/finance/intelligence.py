"""Read-only customer evidence and deterministic delay enrichment."""
from decimal import Decimal
from sqlalchemy import select
from app.database.kosh_models import KoshCounterparty,KoshInvoice,KoshOperationRecord

def customer_snapshot(db,seller_id,as_of):
    items=[]
    for party in db.scalars(select(KoshCounterparty).where(KoshCounterparty.seller_id==seller_id,KoshCounterparty.kind=="CUSTOMER")):
        invoices=list(db.scalars(select(KoshInvoice).where(KoshInvoice.seller_id==seller_id,KoshInvoice.counterparty_id==party.id,KoshInvoice.direction=="RECEIVABLE",KoshInvoice.status!="REVIEW",KoshInvoice.invoice_date<=as_of)))
        observations=sorted(max(0,(i.paid_date-i.due_date).days) for i in invoices if i.paid_date and i.paid_date<=as_of)
        open_amount=sum(max(0,i.amount_paise-(i.paid_amount_paise or 0)) for i in invoices if i.status!="PAID")
        median=observations[len(observations)//2] if observations else None
        items.append({"counterparty_id":party.id,"name":party.name,"open_receivables_paise":open_amount,"observed_delay_days":observations,"median_delay_days":median,"credit_signal":"REVIEW_REQUIRED" if len(observations)<5 else "HIGH_DELAY" if median>=45 else "MODERATE_DELAY" if median>=15 else "LOW_DELAY","source":"Owned invoice payment history"})
    total=sum(i['open_receivables_paise'] for i in items)
    for item in items:item['concentration_share']=str(Decimal(item['open_receivables_paise'])/total) if total else None
    return items

def enriched_delays(db,seller_id,as_of,base):
    result=dict(base)
    for row in db.scalars(select(KoshOperationRecord).where(KoshOperationRecord.seller_id==seller_id,KoshOperationRecord.kind=="PAYMENT_HISTORY",KoshOperationRecord.status=="CONFIRMED").order_by(KoshOperationRecord.id)):
        if row.data['observed_date']<=as_of.isoformat():
            party_id=row.data['counterparty_id'];result[party_id]=(*result.get(party_id,()),*row.data['delay_days'])
    return result
