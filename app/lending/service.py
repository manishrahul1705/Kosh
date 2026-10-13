"""Persist deterministic financing evaluations from seller evidence."""
from __future__ import annotations
from datetime import date
from decimal import Decimal
from sqlalchemy import select
from app.database.models import SellerAttribute,SellerDocument,SellerRevision
from app.database.kosh_models import KoshCounterparty,KoshFinancingEvaluation,KoshFinancingResult,KoshForecastRun,KoshForecastWeek,KoshInvoice
from app.lending.catalogue import load_catalogue
from app.finance.costs import financing_quote
from app.lending.evaluator import evaluate_product

def _attributes(db,seller_id):
    rev=db.scalar(select(SellerRevision).where(SellerRevision.seller_id==seller_id,SellerRevision.is_active.is_(True)).order_by(SellerRevision.revision_number.desc()).limit(1));out={}
    if not rev:return None,out,set()
    for row in db.scalars(select(SellerAttribute).where(SellerAttribute.revision_id==rev.id)):out[row.key]=row.value_number if row.value_type=="NUMBER" else row.value_text
    docs={x.document_type for x in db.scalars(select(SellerDocument).where(SellerDocument.revision_id==rev.id))};return rev,out,docs

def run_evaluation(db,seller_id:int,as_of:date)->KoshFinancingEvaluation:
    run=db.scalar(select(KoshForecastRun).where(KoshForecastRun.seller_id==seller_id,KoshForecastRun.status=="SUCCESS").order_by(KoshForecastRun.id.desc()).limit(1))
    if not run:raise ValueError("No successful forecast")
    rev,a,docs=_attributes(db,seller_id);peak=max(w.expected_shortfall_paise for w in db.scalars(select(KoshForecastWeek).where(KoshForecastWeek.run_id==run.id)))
    facts={"UDYAM_REGISTERED":True if a.get("udyam_number") else None,"UDYAM_CATEGORY_IN":a.get("udyam_category"),"UDYAM_CERTIFICATE_PRESENT":True if "UDYAM_CERTIFICATE" in docs else None,"GST_REGISTERED":True if a.get("gstin") else None,"BUSINESS_VINTAGE_MIN_MONTHS":None,"TURNOVER_RANGE":a.get("last_fy_turnover_paise"),"AMOUNT_WITHIN_LIMIT":peak,"LIMIT_HEADROOM_MIN":int(a["bank_od_limit_paise"])-int(a["bank_od_utilised_paise"]) if a.get("bank_od_limit_paise") is not None and a.get("bank_od_utilised_paise") is not None else None,"SUPPLIER_RELATIONSHIP_MIN_MONTHS":None,"SUPPLIER_ON_TIME_RATIO_MIN":None,"DOCUMENT_PRESENT":None}
    if a.get("incorporation_date"):
        try:
            incorporated=date.fromisoformat(a["incorporation_date"])
            facts["BUSINESS_VINTAGE_MIN_MONTHS"]=max(0,(as_of.year-incorporated.year)*12+as_of.month-incorporated.month-(as_of.day<incorporated.day))
        except (ValueError,TypeError):pass
    for kind,key in [("NON_CORPORATE","non_corporate"),("NON_FARM","non_farm"),("INCOME_GENERATING","income_generating"),("MICRO_SMALL_ENTERPRISE","micro_small_enterprise"),("TARUN_AVAILED_AND_REPAID","tarun_availed_and_repaid")]:
        value=a.get(key)
        facts[kind]=True if str(value).lower() in {"true","1","1.0","yes"} else False if str(value).lower() in {"false","0","0.0","no"} else None
    evaluation=KoshFinancingEvaluation(seller_id=seller_id,forecast_run_id=run.id,input_fingerprint=run.input_fingerprint);db.add(evaluation);db.flush()
    from app.finance.sandbox_ledger import financed,reminder_sent
    for product in load_catalogue():
        scopes=[(None,facts,product["max_amount_paise"])]
        if product["id"] in {"TREDS_INVOICE_DISCOUNTING","COLLECTIONS_PUSH"}:
            scopes=[]
            from app.finance.plan import _arrival
            funding=_arrival(as_of,product["arrival_business_days"])
            for invoice,party in db.execute(select(KoshInvoice,KoshCounterparty).join(KoshCounterparty,KoshCounterparty.id==KoshInvoice.counterparty_id).where(KoshInvoice.seller_id==seller_id,KoshInvoice.direction=="RECEIVABLE",KoshInvoice.status!="PAID").order_by(KoshInvoice.due_date,KoshInvoice.id)):
                remaining=max(0,invoice.amount_paise-(invoice.paid_amount_paise or 0)-financed(db,seller_id,invoice.id))
                local={**facts,"BUYER_TREDS_ONBOARDED":party.treds_onboarded,"INVOICE_ACCEPTED":invoice.accepted_by_buyer,"INVOICE_NOT_OVERDUE":invoice.due_date>=as_of,"RECEIVABLE_OVERDUE_OR_DUE_WITHIN_DAYS":(invoice.due_date-as_of).days,"INVOICE_DUE_AFTER_FUNDING":invoice.due_date>funding,"INVOICE_EVIDENCE_VERIFIED":None if invoice.status=="REVIEW" else True,"INVOICE_OPEN_AMOUNT_POSITIVE":remaining>0,"COLLECTION_REPEAT_ATTEMPT":reminder_sent(db,seller_id,invoice.id),"COLLECTION_REPEAT_OUTCOME_PRESENT":None}
                cap=remaining if product["id"]=="TREDS_INVOICE_DISCOUNTING" else remaining//2
                scopes.append((f"invoice:{invoice.id}",local,cap))
        if not scopes:scopes=[(None,facts,0)]
        for scope,local,cap in scopes:
            clauses=list(product["criteria"])
            if scope:
                clauses.extend([{"type":"INVOICE_EVIDENCE_VERIFIED"},{"type":"INVOICE_OPEN_AMOUNT_POSITIVE"}])
                if product["id"]=="TREDS_INVOICE_DISCOUNTING":clauses.append({"type":"INVOICE_DUE_AFTER_FUNDING"})
                elif product["id"]=="COLLECTIONS_PUSH":clauses.append({"type":"COLLECTION_REPEAT_OUTCOME_PRESENT"})
            result=evaluate_product({**product,"criteria":clauses},{**local,"product_max":product["max_amount_paise"]},as_of=as_of);rate=product["cost_model"]["annual_rate"]
            if product["id"]=="BANK_OD_DRAWDOWN":
                from app.database.kosh_models import KoshSandboxLedgerEntry
                from sqlalchemy import func
                used=db.scalar(select(func.coalesce(func.sum(KoshSandboxLedgerEntry.amount_paise),0)).where(KoshSandboxLedgerEntry.seller_id==seller_id,KoshSandboxLedgerEntry.kind=="OD_DRAWDOWN"))
                cap=max(0,(facts["LIMIT_HEADROOM_MIN"] or 0)-int(used))
                local={**local,"LIMIT_HEADROOM_MIN":cap if facts["LIMIT_HEADROOM_MIN"] is not None else None}
                result=evaluate_product(product,local,as_of=as_of)
            if product["id"]=="MUDRA_LOAN" and facts["TARUN_AVAILED_AND_REPAID"] is not True:cap=min(cap,100_000_000)
            rate=financing_quote(product,min(int(cap),int(product["max_amount_paise"])))["effective_annual_rate"]
            db.add(KoshFinancingResult(evaluation_id=evaluation.id,product_id=product["id"],scope=scope,status=result["status"],max_amount_paise=min(int(cap),int(product["max_amount_paise"])),effective_annual_rate=rate,arrival_business_days=product["arrival_business_days"],reasons=result["reasons"],evidence=[r.get("business_evidence") for r in result["reasons"] if r.get("business_evidence")]+([{"invoice_id":invoice.id,"invoice_number":invoice.invoice_number,"buyer":party.name,"due_date":invoice.due_date.isoformat()}] if scope and (invoice:=db.get(KoshInvoice,int(scope.split(":")[1]))) and (party:=db.get(KoshCounterparty,invoice.counterparty_id)) else [])))
    return evaluation


