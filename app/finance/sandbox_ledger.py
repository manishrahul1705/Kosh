"""Read-only labelled cash overlay from settled sandbox execution evidence."""
from sqlalchemy import select,func
from app.database.kosh_models import KoshSandboxLedgerEntry,KoshSandboxExecution,KoshActionIntent

def overlay(db,seller_id,as_of):
    entries=db.scalars(select(KoshSandboxLedgerEntry).join(KoshSandboxExecution,KoshSandboxExecution.id==KoshSandboxLedgerEntry.execution_id).where(KoshSandboxLedgerEntry.seller_id==seller_id,KoshSandboxExecution.status=="SETTLED").order_by(KoshSandboxLedgerEntry.entry_date,KoshSandboxLedgerEntry.id)).all()
    opening=0;future=[];reductions={}
    for entry in entries:
        if entry.invoice_id and entry.receivable_reduction_paise:reductions[entry.invoice_id]=reductions.get(entry.invoice_id,0)+entry.receivable_reduction_paise
        if entry.entry_date<=as_of and entry.status=="POSTED":opening+=entry.amount_paise
        else:future.append({"date":entry.entry_date.isoformat(),"amount_paise":entry.amount_paise,"component":"sandbox","source_entry_id":entry.id,"status":entry.status})
    return opening,tuple(future),reductions

def financed(db,seller_id,invoice_id):
    return int(db.scalar(select(func.coalesce(func.sum(KoshSandboxLedgerEntry.receivable_reduction_paise),0)).join(KoshSandboxExecution,KoshSandboxExecution.id==KoshSandboxLedgerEntry.execution_id).where(KoshSandboxLedgerEntry.seller_id==seller_id,KoshSandboxLedgerEntry.invoice_id==invoice_id,KoshSandboxExecution.status=="SETTLED")))

def reminder_sent(db,seller_id,invoice_id):
    return db.scalar(select(KoshActionIntent.id).where(KoshActionIntent.seller_id==seller_id,KoshActionIntent.action_type=="COLLECTIONS_REMINDER",KoshActionIntent.status=="SUCCEEDED",KoshActionIntent.params["invoice_id"].as_integer()==invoice_id).limit(1)) is not None
