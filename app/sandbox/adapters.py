"""Intent-keyed sandbox transactions, ledger and outbox only."""
import hashlib,uuid
from datetime import date,timedelta
from decimal import Decimal
from sqlalchemy import select,func
from app.actions.integrity import current_hash
from app.audit.ledger import append_event,canonical_json
from app.database.kosh_models import KoshSandboxExecution,KoshSandboxLedgerEntry,KoshSandboxOutbox,KoshActionApproval,KoshPolicyControl,KoshInvoice,KoshActionIntent,KoshCounterparty
from app.database.session import reserve_sqlite_writer
from app.finance.costs import financing_quote
from app.lending.catalogue import load_catalogue
from app.lending.service import _attributes
from app.utils.dates import utcnow

class AdapterError(RuntimeError):pass

ADAPTERS={"OD_DRAWDOWN":"BANK","TREDS_FINANCE":"TREDS","LOAN_APPLICATION":"LENDER","COLLECTIONS_REMINDER":"MESSAGES","SUPPLIER_TERM_REQUEST":"MESSAGES","SHARE_DATA_PACK":"SHARING"}

def business_after(day):
    day+=timedelta(days=1)
    while day.weekday()>=5:day+=timedelta(days=1)
    return day

def business_before(day):
    day-=timedelta(days=1)
    while day.weekday()>=5:day-=timedelta(days=1)
    return day

def ledger_item(key,day,amount,kind,*,invoice_id=None,reduction=0,status="POSTED"):
    return {"entry_key":key,"entry_date":day.isoformat(),"amount_paise":amount,"kind":kind,"invoice_id":invoice_id,"receivable_reduction_paise":reduction,"status":status,"label":"SANDBOX"}

def expected(intent):
    p=intent.params;amount=p["amount_paise"];funding=date.fromisoformat(p["funding_date"])
    if intent.action_type=="TREDS_FINANCE":return [ledger_item("settlement",funding,amount-p["cost_paise"],"TREDS_SETTLEMENT",invoice_id=p["invoice_id"],reduction=amount)]
    if intent.action_type=="OD_DRAWDOWN":return [ledger_item("draw",funding,amount,"OD_DRAWDOWN"),ledger_item("repayment",date.fromisoformat(p["repayment_date"]),-(amount+p["cost_paise"]),"OD_REPAYMENT",status="SCHEDULED")]
    # Application submission, data sharing and messaging do not imply cash receipts.
    return []

def record(db,intent,action,payload,decision="ALLOW"):
    append_event(db,seller_id=intent.seller_id,actor_type="SYSTEM",actor_id=None,action=action,tier=intent.tier,payload={"intent_id":intent.id,**payload},policy_decision=decision)

def run(db,intent):
    reserve_sqlite_writer(db,renew_read=True)
    if intent.status!="EXECUTING" or current_hash(intent)!=intent.params_hash:raise AdapterError("APPROVED_EXECUTION_REQUIRED")
    authorization=db.scalar(select(KoshActionApproval).where(KoshActionApproval.intent_id==intent.id,KoshActionApproval.params_hash==intent.params_hash,KoshActionApproval.used_at.is_not(None),KoshActionApproval.revoked_at.is_(None)).order_by(KoshActionApproval.used_at.desc()).limit(1))
    if authorization is None or (intent.tier=="T3" and not authorization.otp_verified):raise AdapterError("CONSUMED_APPROVAL_REQUIRED")
    adapter=ADAPTERS.get(intent.action_type)
    if adapter is None:raise AdapterError("NO_SANDBOX_ADAPTER")
    key=f"sandbox:{intent.id}"
    row=db.scalar(select(KoshSandboxExecution).where(KoshSandboxExecution.idempotency_key==key,KoshSandboxExecution.seller_id==intent.seller_id).with_for_update())
    if row is not None:
        if row.params_hash!=intent.params_hash:raise AdapterError("IDEMPOTENCY_PARAMETERS_CHANGED")
        if row.status=="SETTLED":
            record(db,intent,"sandbox.idempotent_retry",{"execution_id":row.id})
            return row
    else:
        row=KoshSandboxExecution(id=str(uuid.uuid4()),intent_id=intent.id,seller_id=intent.seller_id,idempotency_key=key,params_hash=intent.params_hash,adapter=adapter,status="PENDING",expected_entries=expected(intent),result={},history=[],created_at=utcnow(),updated_at=utcnow())
        db.add(row)
    row.status="PENDING";row.history=[*row.history,{"status":"PENDING","at":utcnow().isoformat()+"Z"}];row.error=None
    controls=db.scalar(select(KoshPolicyControl).where(KoshPolicyControl.scope_key==f"SELLER:{intent.seller_id}").with_for_update())
    if controls is not None and controls.sandbox_fail_next:
        controls.sandbox_fail_next=False;row.status="FAILED";row.error="SIMULATED_FAILURE_INJECTION"
        row.history=[*row.history,{"status":"FAILED","at":utcnow().isoformat()+"Z"}]
        record(db,intent,"sandbox.failed",{"execution_id":row.id,"rule_ids":[row.error]},"DENY")
        return row
    p=intent.params
    try:
        if p.get("sharing_fields"):
            from app.consent.sharing import active
            consent=active(db,seller_id=intent.seller_id,purpose=p["sharing_purpose"],recipient_id=p["recipient_id"],fields=p["sharing_fields"],lock=True)
            if consent is None:raise AdapterError("CONSENT_SCOPE_REVOKED_OR_EXPIRED")
        if adapter in {"BANK","TREDS"}:
            product=next(product for product in load_catalogue() if product["id"]==p["product_code"])
            quote=financing_quote(product,p["amount_paise"],days=p["days"])
            if quote["cost_paise"]!=p["cost_paise"]:raise AdapterError("PRICE_CHANGED_REPLAN_REQUIRED")
        if adapter=="BANK":
            _,attributes,_=_attributes(db,intent.seller_id)
            if attributes.get("bank_od_limit_paise") is None or attributes.get("bank_od_utilised_paise") is None:raise AdapterError("OD_HEADROOM_UNKNOWN")
            used=db.scalar(select(func.coalesce(func.sum(KoshSandboxLedgerEntry.amount_paise),0)).where(KoshSandboxLedgerEntry.seller_id==intent.seller_id,KoshSandboxLedgerEntry.kind=="OD_DRAWDOWN"))
            headroom=int(attributes["bank_od_limit_paise"])-int(attributes["bank_od_utilised_paise"])-int(used)
            if p["amount_paise"]>headroom:raise AdapterError("OD_HEADROOM_EXCEEDED")
            row.result={"provider":"SANDBOX_BANK","drawn_paise":p["amount_paise"],"remaining_headroom_paise":headroom-p["amount_paise"]}
        elif adapter=="TREDS":
            invoice=db.scalar(select(KoshInvoice).where(KoshInvoice.id==p["invoice_id"],KoshInvoice.seller_id==intent.seller_id,KoshInvoice.status=="OPEN"))
            if invoice is None or invoice.accepted_by_buyer is not True:raise AdapterError("TREDS_INVOICE_EVIDENCE_CHANGED")
            buyer=db.scalar(select(KoshCounterparty).where(KoshCounterparty.id==invoice.counterparty_id,KoshCounterparty.seller_id==intent.seller_id))
            if buyer is None or buyer.treds_onboarded is not True:raise AdapterError("TREDS_BUYER_EVIDENCE_CHANGED")
            financed=db.scalar(select(func.coalesce(func.sum(KoshSandboxLedgerEntry.receivable_reduction_paise),0)).where(KoshSandboxLedgerEntry.seller_id==intent.seller_id,KoshSandboxLedgerEntry.invoice_id==invoice.id))
            if p["amount_paise"]>invoice.amount_paise-(invoice.paid_amount_paise or 0)-int(financed):raise AdapterError("INVOICE_AVAILABLE_AMOUNT_EXCEEDED")
            funding=date.fromisoformat(p["funding_date"]);submission=business_before(funding)
            if business_after(submission)!=funding or (invoice.due_date-funding).days!=p["days"]:raise AdapterError("MATURITY_OR_SETTLEMENT_DATE_CHANGED")
            nominal=Decimal(product["cost_model"]["annual_rate"])
            bids=[{"bid_id":f"sandbox-bid-{index+1}","annual_rate":str(nominal+increment),"illustrative":True} for index,increment in enumerate((Decimal(0),Decimal(".005"),Decimal(".01")))]
            best=min(bids,key=lambda bid:Decimal(bid["annual_rate"]))
            row.result={"provider":"SANDBOX_TREDS","upload":{"invoice_id":invoice.id,"amount_paise":p["amount_paise"],"due_date":invoice.due_date.isoformat()},"bids":bids,"accepted_bid":best,"scheduled_submission_date":submission.isoformat(),"settlement_date":funding.isoformat(),"settlement_business_days":1,"financed_part_paise":p["amount_paise"],"remaining_invoice_paise":invoice.amount_paise-int(financed)-p["amount_paise"]}
        elif adapter=="LENDER":
            row.result={"provider":"SANDBOX_LENDER","application_id":f"application:{intent.id}","application_status":"SUBMITTED","recipient_id":p["recipient_id"],"shared_fields":p["sharing_fields"],"cash_disbursed_paise":0}
        elif adapter=="MESSAGES":
            existing=db.scalar(select(KoshSandboxOutbox).where(KoshSandboxOutbox.execution_id==row.id))
            if existing is None:
                message=KoshSandboxOutbox(id=str(uuid.uuid4()),seller_id=intent.seller_id,execution_id=row.id,intent_id=intent.id,channel="EMAIL",recipient_ref=p["allowlist_key"],body=f"Please review receivable #{p.get('invoice_id')} and arrange payment. Requested collection amount: INR {Decimal(p['amount_paise'])/100:,.2f}.",status="SUBMITTED",created_at=utcnow())
                db.add(message)
            row.result={"provider":"SANDBOX_MESSAGES","channel":"EMAIL","recipient_ref":p["allowlist_key"],"cash_received_paise":0,"note":"Outbox submission is not evidence of a customer payment."}
        elif adapter=="SHARING":
            if not p.get("evidence_reference"):raise AdapterError("SHARING_EVIDENCE_REQUIRED")
            row.result={"provider":"SANDBOX_SHARING","recipient_id":p["recipient_id"],"shared_fields":p["sharing_fields"],"evidence_reference":p.get("evidence_reference")}
        if p.get("sharing_fields"):
            record(db,intent,"sharing.submit.sandbox",{"execution_id":row.id,"consent_id":consent.id,"recipient_id":p["recipient_id"],"fields":p["sharing_fields"]})
        row.status="SUBMITTED";row.history=[*row.history,{"status":"SUBMITTED","at":utcnow().isoformat()+"Z"}]
        record(db,intent,"sandbox.submitted",{"execution_id":row.id,"adapter":adapter,"expected_hash":hashlib.sha256(canonical_json(row.expected_entries).encode()).hexdigest()})
        for entry in row.expected_entries:
            existing=db.scalar(select(KoshSandboxLedgerEntry).where(KoshSandboxLedgerEntry.execution_id==row.id,KoshSandboxLedgerEntry.entry_key==entry["entry_key"]))
            if existing is None:db.add(KoshSandboxLedgerEntry(execution_id=row.id,seller_id=intent.seller_id,entry_key=entry["entry_key"],entry_date=date.fromisoformat(entry["entry_date"]),amount_paise=entry["amount_paise"],kind=entry["kind"],invoice_id=entry["invoice_id"],receivable_reduction_paise=entry["receivable_reduction_paise"],status=entry["status"],label="SANDBOX"))
        row.status="SETTLED";row.updated_at=utcnow();row.history=[*row.history,{"status":"SETTLED","at":utcnow().isoformat()+"Z"}]
        record(db,intent,"sandbox.settled",{"execution_id":row.id,"adapter":adapter,"cash_entries":len(row.expected_entries)})
    except (AdapterError,ValueError,StopIteration) as exc:
        row.status="FAILED";row.error=str(exc);row.history=[*row.history,{"status":"FAILED","at":utcnow().isoformat()+"Z"}]
        record(db,intent,"sandbox.failed",{"execution_id":row.id,"reason":row.error},"DENY")
    return row

def balance(db,seller_id,*,as_of):
    from app.database.kosh_models import KoshBankTransaction
    base=db.scalar(select(KoshBankTransaction).where(KoshBankTransaction.seller_id==seller_id,KoshBankTransaction.txn_date<=as_of).order_by(KoshBankTransaction.txn_date.desc(),KoshBankTransaction.id.desc()).limit(1))
    delta=db.scalar(select(func.coalesce(func.sum(KoshSandboxLedgerEntry.amount_paise),0)).where(KoshSandboxLedgerEntry.seller_id==seller_id,KoshSandboxLedgerEntry.status=="POSTED",KoshSandboxLedgerEntry.entry_date<=as_of))
    return {"source":"SANDBOX","as_of":as_of.isoformat(),"base_balance_paise":base.balance_paise if base else None,"sandbox_delta_paise":int(delta),"balance_paise":base.balance_paise+int(delta) if base else None}

def reconcile(db,seller_id,execution_id=None):
    stmt=select(KoshSandboxExecution).where(KoshSandboxExecution.seller_id==seller_id,KoshSandboxExecution.status=="SETTLED")
    if execution_id:stmt=stmt.where(KoshSandboxExecution.id==execution_id)
    mismatches=[]
    for execution in db.scalars(stmt):
        intent=db.get(KoshActionIntent,execution.intent_id)
        expected_entries=expected(intent)
        if current_hash(intent)!=execution.params_hash or intent.params_hash!=execution.params_hash:
            mismatches.append({"execution_id":execution.id,"rule_id":"INTENT_BINDING_MISMATCH"})
        if execution.expected_entries!=expected_entries:
            mismatches.append({"execution_id":execution.id,"rule_id":"EXPECTATION_MISMATCH"})
        actual=[{"entry_key":entry.entry_key,"entry_date":entry.entry_date.isoformat(),"amount_paise":entry.amount_paise,"kind":entry.kind,"invoice_id":entry.invoice_id,"receivable_reduction_paise":entry.receivable_reduction_paise,"status":entry.status,"label":entry.label} for entry in db.scalars(select(KoshSandboxLedgerEntry).where(KoshSandboxLedgerEntry.execution_id==execution.id,KoshSandboxLedgerEntry.seller_id==seller_id))]
        if sorted(actual,key=lambda x:x["entry_key"])!=sorted(expected_entries,key=lambda x:x["entry_key"]):mismatches.append({"execution_id":execution.id,"rule_id":"LEDGER_MISMATCH"})
    return {"status":"MATCHED" if not mismatches else "MISMATCH","mismatches":mismatches}
