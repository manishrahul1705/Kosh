"""Idempotent dispatch from validated private documents into the cash ledger."""
import json
from pathlib import Path
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.audit.ledger import append_event
from app.database.kosh_models import KoshCounterparty,KoshInvoice,KoshPrivateDocument,KoshPrivateDocumentVersion
from app.finance.intake.bank_statement import import_bank_statement
from app.finance.intake.books_csv import import_books_csv
from app.finance.intake.invoice_pdf import extract_invoice_pdf

def process_private_document(session:Session,*,document:KoshPrivateDocument,version:KoshPrivateDocumentVersion,path:Path,actor_id:int)->dict:
    if document.status in {"PROCESSED","REVIEW"}:return {"created":0,"review":int(document.status=="REVIEW"),"idempotent":True}
    document.status="PROCESSING";session.flush();summary={"created":0,"review":0};reasons=[]
    if document.kind=="BOOKS_EXPORT" and version.detected_format=="csv":summary=import_books_csv(session,seller_id=document.seller_id,path=path,version_id=version.id)
    elif document.kind=="BANK_STATEMENT" and version.detected_format in {"json","csv"}:summary=import_bank_statement(session,seller_id=document.seller_id,path=path,version_id=version.id)
    elif document.kind in {"SALES_INVOICE","PURCHASE_BILL"} and version.detected_format=="pdf":
        result=extract_invoice_pdf(path);reasons=result["reasons"]
        if not result["invoice_number"]:reasons.append("MISSING_INVOICE_NUMBER")
        if not result["invoice_date"]:reasons.append("MISSING_INVOICE_DATE")
        if result["amounts"]["total"] is None:reasons.append("MISSING_TOTAL")
        if result["invoice_number"] and result["invoice_date"] and result["amounts"]["total"] is not None:
            direction="RECEIVABLE" if document.kind=="SALES_INVOICE" else "PAYABLE"
            invoice=session.scalar(select(KoshInvoice).where(KoshInvoice.seller_id==document.seller_id,KoshInvoice.direction==direction,KoshInvoice.invoice_number==result["invoice_number"],KoshInvoice.invoice_date==result["invoice_date"],KoshInvoice.amount_paise.between(result["amounts"]["total"]-100,result["amounts"]["total"]+100)))
            if invoice:
                invoice.source_document_version_id=version.id;invoice.source_location=json.dumps({**result["source_location"],"method":result["method"],"reasons":reasons,"linked_books_invoice":True});summary={"created":0,"review":int(bool(reasons)),"linked":1}
                if reasons:invoice.status="REVIEW"
            kind="CUSTOMER" if document.kind=="SALES_INVOICE" else "SUPPLIER";name=result["buyer_name"] if kind=="CUSTOMER" else result["seller_name"]
            if not name:
                reasons.append("MISSING_PARTY_NAME")
            if invoice or not name:pass
            else:
                party=session.scalar(select(KoshCounterparty).where(KoshCounterparty.seller_id==document.seller_id,KoshCounterparty.name==name,KoshCounterparty.kind==kind))
                if not party:party=KoshCounterparty(seller_id=document.seller_id,name=name,kind=kind);session.add(party);session.flush()
                invoice=session.scalar(select(KoshInvoice).where(KoshInvoice.seller_id==document.seller_id,KoshInvoice.direction==direction,KoshInvoice.counterparty_id==party.id,KoshInvoice.invoice_number==result["invoice_number"]))
                if not invoice:
                    invoice=KoshInvoice(seller_id=document.seller_id,counterparty_id=party.id,direction=direction,invoice_number=result["invoice_number"],invoice_date=result["invoice_date"],due_date=result["due_date"] or result["invoice_date"],amount_paise=result["amounts"]["total"],status="REVIEW" if reasons else "OPEN",source_document_version_id=version.id,source_location=json.dumps({**result["source_location"],"method":result["method"],"reasons":reasons}));session.add(invoice);summary={"created":1,"review":int(bool(reasons))}
    else:reasons=["UNSUPPORTED_PROCESSOR"]
    if reasons:summary["review"]=max(1,summary.get("review",0))
    document.status="REVIEW" if reasons or summary.get("review") else "PROCESSED";document.status_reason=";".join(reasons) or ("ROW_REVIEW_REQUIRED" if summary.get("review") else None)
    if "INSTRUCTION_TEXT_DETECTED" in reasons:append_event(session,seller_id=document.seller_id,actor_type="SYSTEM",actor_id=None,action="security.injection_detected",tier="T0_READ",payload={"document_id":document.id,"version_id":version.id},policy_decision="DENY")
    append_event(session,seller_id=document.seller_id,actor_type="HUMAN",actor_id=str(actor_id),action="document.process",tier="T1_DRAFT",payload={"document_id":document.id,"version_id":version.id,"summary":summary,"reasons":reasons},policy_decision="ALLOW")
    session.commit();return {**summary,"reasons":reasons,"idempotent":False}
