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

def _attribute_sources(db,seller_id):
    rev=db.scalar(select(SellerRevision).where(SellerRevision.seller_id==seller_id,SellerRevision.is_active.is_(True)).order_by(SellerRevision.revision_number.desc()).limit(1))
    sources={}
    if not rev:return sources
    for row in db.scalars(select(SellerAttribute).where(SellerAttribute.revision_id==rev.id)):
        is_owner=bool(row.context and "owner" in row.context.lower())
        sources[row.key]={
            "origin":"OWNER_DECLARATION" if is_owner else "SELF_DECLARED",
            "strength":"OWNER_DECLARATION",
            "reference":row.context or "Business profile",
            "recorded_at":row.created_at.isoformat() if row.created_at else None,
            "verified":False,
        }
    for doc in db.scalars(select(SellerDocument).where(SellerDocument.revision_id==rev.id)):
        is_verified=(doc.status=="VERIFIED")
        sources[doc.document_type]={
            "origin":"DOCUMENT",
            "strength":"INDEPENDENTLY_VERIFIED" if is_verified else "LINKED_DOCUMENT",
            "reference":doc.filename or doc.display_name,
            "recorded_at":doc.created_at.isoformat() if doc.created_at else None,
            "verified":is_verified,
        }
    return sources

def run_evaluation(db,seller_id:int,as_of:date)->KoshFinancingEvaluation:
    run=db.scalar(select(KoshForecastRun).where(KoshForecastRun.seller_id==seller_id,KoshForecastRun.status=="SUCCESS").order_by(KoshForecastRun.id.desc()).limit(1))
    if not run:raise ValueError("No successful forecast")
    rev,a,docs=_attributes(db,seller_id);sources=_attribute_sources(db,seller_id);peak=max((w.expected_shortfall_paise for w in db.scalars(select(KoshForecastWeek).where(KoshForecastWeek.run_id==run.id))),default=0)
    
    udyam_doc=db.scalar(select(SellerDocument).where(SellerDocument.revision_id==rev.id,SellerDocument.document_type=="UDYAM_CERTIFICATE")) if rev else None
    if udyam_doc:
        udyam_strength="INDEPENDENTLY_VERIFIED" if udyam_doc.status=="VERIFIED" else "LINKED_DOCUMENT"
        udyam_source=sources.get("UDYAM_CERTIFICATE")
        udyam_cert_val=True
    elif a.get("udyam_certificate_present") is not None:
        udyam_strength="OWNER_DECLARATION"
        udyam_source=sources.get("udyam_certificate_present")
        s=str(a.get("udyam_certificate_present")).lower()
        udyam_cert_val=True if s in {"true","1","yes"} else False if s in {"false","0","no"} else None
    else:
        udyam_strength=None
        udyam_source=None
        udyam_cert_val=None

    po_doc=db.scalar(select(SellerDocument).where(SellerDocument.revision_id==rev.id,SellerDocument.document_type.in_(["GEM_PO","PURCHASE_ORDER"]))) if rev else None
    if po_doc:
        po_strength="INDEPENDENTLY_VERIFIED" if po_doc.status=="VERIFIED" else "LINKED_DOCUMENT"
        po_source=sources.get(po_doc.document_type)
        doc_present=True
    elif a.get("gem_po_document") is not None or a.get("document_present") is not None:
        raw_val=a.get("gem_po_document") if a.get("gem_po_document") is not None else a.get("document_present")
        po_strength="OWNER_DECLARATION"
        po_source=sources.get("gem_po_document") or sources.get("document_present")
        s=str(raw_val).lower()
        doc_present=True if s in {"true","1","yes"} else False if s in {"false","0","no"} else None
    else:
        po_strength=None
        po_source=None
        doc_present=None

    rel_months=None
    if a.get("supplier_relationship_months") is not None:
        try:rel_months=int(a["supplier_relationship_months"])
        except (ValueError,TypeError):pass
    on_time_ratio=None
    if a.get("supplier_on_time_ratio") is not None:
        try:on_time_ratio=float(a["supplier_on_time_ratio"])
        except (ValueError,TypeError):pass

    facts={
        "UDYAM_REGISTERED":True if a.get("udyam_number") else None,
        "UDYAM_REGISTERED_SOURCE":sources.get("udyam_number"),
        "UDYAM_CATEGORY_IN":a.get("udyam_category"),
        "UDYAM_CATEGORY_IN_SOURCE":sources.get("udyam_category"),
        "UDYAM_CERTIFICATE_PRESENT":udyam_cert_val,
        "UDYAM_CERTIFICATE_PRESENT_STRENGTH":udyam_strength,
        "UDYAM_CERTIFICATE_PRESENT_SOURCE":udyam_source,
        "GST_REGISTERED":True if a.get("gstin") else None,
        "GST_REGISTERED_SOURCE":sources.get("gstin"),
        "BUSINESS_VINTAGE_MIN_MONTHS":None,
        "TURNOVER_RANGE":a.get("last_fy_turnover_paise"),
        "TURNOVER_RANGE_SOURCE":sources.get("last_fy_turnover_paise"),
        "AMOUNT_WITHIN_LIMIT":peak,
        "LIMIT_HEADROOM_MIN":int(a["bank_od_limit_paise"])-int(a["bank_od_utilised_paise"]) if a.get("bank_od_limit_paise") is not None and a.get("bank_od_utilised_paise") is not None else None,
        "LIMIT_HEADROOM_MIN_SOURCE":sources.get("bank_od_limit_paise"),
        "SUPPLIER_RELATIONSHIP_MIN_MONTHS":rel_months,
        "SUPPLIER_RELATIONSHIP_MIN_MONTHS_SOURCE":sources.get("supplier_relationship_months"),
        "SUPPLIER_ON_TIME_RATIO_MIN":on_time_ratio,
        "SUPPLIER_ON_TIME_RATIO_MIN_SOURCE":sources.get("supplier_on_time_ratio"),
        "SUPPLIER_AGREEMENT_CONFIRMED":str(a.get("supplier_extension_status") or "").upper() or None,
        "SUPPLIER_AGREEMENT_CONFIRMED_SOURCE":sources.get("supplier_extension_status"),
        "DOCUMENT_PRESENT":doc_present,
        "DOCUMENT_PRESENT_STRENGTH":po_strength,
        "DOCUMENT_PRESENT_SOURCE":po_source,
    }
    if a.get("incorporation_date"):
        try:
            incorporated=date.fromisoformat(a["incorporation_date"])
            facts["BUSINESS_VINTAGE_MIN_MONTHS"]=max(0,(as_of.year-incorporated.year)*12+as_of.month-incorporated.month-(as_of.day<incorporated.day))
        except (ValueError,TypeError):pass
    for kind,key in [("NON_CORPORATE","non_corporate"),("NON_FARM","non_farm"),("INCOME_GENERATING","income_generating"),("MICRO_SMALL_ENTERPRISE","micro_small_enterprise"),("TARUN_AVAILED_AND_REPAID","tarun_availed_and_repaid")]:
        value=a.get(key)
        facts[kind]=True if str(value).lower() in {"true","1","1.0","yes"} else False if str(value).lower() in {"false","0","0.0","no"} else None
        facts[kind+"_SOURCE"]=sources.get(key)
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
        elif product["id"]=="SUPPLIER_TERM_EXTENSION":
            scopes=[]
            payables=db.execute(select(KoshInvoice,KoshCounterparty).join(KoshCounterparty,KoshCounterparty.id==KoshInvoice.counterparty_id).where(KoshInvoice.seller_id==seller_id,KoshInvoice.direction=="PAYABLE",KoshInvoice.status!="PAID").order_by(KoshInvoice.due_date,KoshInvoice.id)).all()
            supplier_ids={party.id for _,party in payables}
            for invoice,party in payables:
                remaining=max(0,invoice.amount_paise-(invoice.paid_amount_paise or 0))
                s_rel=a.get(f"supplier_{party.id}_relationship_months")
                s_on_time=a.get(f"supplier_{party.id}_on_time_ratio")
                s_ext=a.get(f"supplier_{party.id}_extension_status")
                if s_rel is None and len(supplier_ids)==1:
                    s_rel=a.get("supplier_relationship_months")
                if s_on_time is None and len(supplier_ids)==1:
                    s_on_time=a.get("supplier_on_time_ratio")
                if s_ext is None and len(supplier_ids)==1:
                    s_ext=a.get("supplier_extension_status")
                rel_m=int(s_rel) if s_rel is not None else None
                on_t=float(s_on_time) if s_on_time is not None else None
                ext_st=str(s_ext).upper() if s_ext is not None else "UNKNOWN"
                supplier_src=sources.get(f"supplier_{party.id}_relationship_months") or (sources.get("supplier_relationship_months") if len(supplier_ids)==1 else None) or {
                    "origin":"OWNER_DECLARATION",
                    "strength":"OWNER_DECLARATION",
                    "reference":f"Supplier: {party.name}",
                    "recorded_at":None,
                    "verified":False,
                }
                local={
                    **facts,
                    "SUPPLIER_RELATIONSHIP_MIN_MONTHS":rel_m,
                    "SUPPLIER_RELATIONSHIP_MIN_MONTHS_SOURCE":supplier_src,
                    "SUPPLIER_ON_TIME_RATIO_MIN":on_t,
                    "SUPPLIER_ON_TIME_RATIO_MIN_SOURCE":supplier_src,
                    "SUPPLIER_AGREEMENT_CONFIRMED":ext_st,
                    "SUPPLIER_AGREEMENT_CONFIRMED_SOURCE":supplier_src,
                    "INVOICE_EVIDENCE_VERIFIED":True,
                    "INVOICE_OPEN_AMOUNT_POSITIVE":remaining>0,
                }
                scopes.append((f"invoice:{invoice.id}",local,remaining))
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
            db.add(KoshFinancingResult(evaluation_id=evaluation.id,product_id=product["id"],scope=scope,status=result["status"],max_amount_paise=min(int(cap),int(product["max_amount_paise"])),effective_annual_rate=rate,arrival_business_days=product["arrival_business_days"],reasons=result["reasons"],evidence=[r.get("business_evidence") for r in result["reasons"] if r.get("business_evidence")]+([{"invoice_id":invoice.id,"invoice_number":invoice.invoice_number,"buyer":party.name,"party":party.name,"counterparty_id":party.id,"direction":invoice.direction,"due_date":invoice.due_date.isoformat()}] if scope and (invoice:=db.get(KoshInvoice,int(scope.split(":")[1]))) and (party:=db.get(KoshCounterparty,invoice.counterparty_id)) else [])))
    return evaluation
