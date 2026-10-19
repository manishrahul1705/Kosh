"""Idempotent Tally-style CSV import into counterparties and invoices."""
import csv,json
from datetime import datetime,timedelta
from pathlib import Path
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.database.kosh_models import KoshCounterparty,KoshInvoice
from app.finance.intake.money import parse_inr_to_paise
from app.finance.intake.gstin import validate_gstin

def import_books_csv(session:Session,*,seller_id:int,path:Path,version_id:int)->dict:
    created=review=0
    with path.open(encoding="utf-8-sig",newline="") as stream:
        for line,row in enumerate(csv.DictReader(stream),2):
            reasons=[];voucher=(row.get("voucher_type") or "").strip().lower();direction="RECEIVABLE" if voucher=="sales" else "PAYABLE" if voucher=="purchase" else None
            amount,reason=parse_inr_to_paise(row.get("amount", ""));reasons += [reason] if reason else []
            try:invoice_date=datetime.strptime(row.get("invoice_date", ""),"%Y-%m-%d").date()
            except ValueError:invoice_date=datetime(1970,1,1).date();reasons.append("INVALID_INVOICE_DATE")
            try:due=datetime.strptime(row.get("due_date", ""),"%Y-%m-%d").date() if row.get("due_date") else invoice_date+timedelta(days=int(row.get("credit_days") or 0))
            except ValueError:due=invoice_date;reasons.append("INVALID_DUE_DATE")
            gstin=(row.get("party_gstin") or "").strip() or None
            if gstin and not validate_gstin(gstin):reasons.append("INVALID_GSTIN")
            party_name=(row.get("party_name") or "UNKNOWN").strip() or "UNKNOWN"
            stored_direction=direction or "RECEIVABLE";kind="CUSTOMER" if stored_direction=="RECEIVABLE" else "SUPPLIER"
            party=session.scalar(select(KoshCounterparty).where(KoshCounterparty.seller_id==seller_id,KoshCounterparty.name==party_name,KoshCounterparty.kind==kind))
            if not party:party=KoshCounterparty(seller_id=seller_id,name=party_name,kind=kind,gstin=gstin);session.add(party);session.flush()
            number=(row.get("invoice_number") or f"REVIEW-{line}").strip()
            invoice=session.scalar(select(KoshInvoice).where(KoshInvoice.seller_id==seller_id,KoshInvoice.direction==stored_direction,KoshInvoice.counterparty_id==party.id,KoshInvoice.invoice_number==number))
            if invoice:continue
            paid_amount,paid_reason=parse_inr_to_paise(row.get("paid_amount", "")) if row.get("paid_amount") else (None,None)
            if paid_reason:reasons.append("INVALID_PAID_AMOUNT")
            try:paid_date=datetime.strptime(row.get("paid_date", ""),"%Y-%m-%d").date() if row.get("paid_date") else None
            except ValueError:paid_date=None;reasons.append("INVALID_PAID_DATE")
            status="REVIEW" if reasons else "PAID" if paid_amount is not None and paid_amount>=(amount or 0) else "PARTIAL" if paid_amount else "OPEN"
            invoice=KoshInvoice(seller_id=seller_id,counterparty_id=party.id,direction=stored_direction,invoice_number=number,invoice_date=invoice_date,due_date=due,amount_paise=amount or 0,status=status,paid_date=paid_date,paid_amount_paise=paid_amount,source_document_version_id=version_id,source_location=json.dumps({"row":line,"reasons":reasons}))
            session.add(invoice);created+=1;review+=bool(reasons)
    session.flush();return {"created":created,"review":review}
