"""Rules-first extraction from native-text private invoice PDFs."""
from datetime import datetime,timedelta
from pathlib import Path
import re
from app.extraction.pdf_parser import PdfPlumberParser
from app.finance.intake.money import parse_inr_to_paise
from app.finance.intake.gstin import validate_gstin

INJECTION=re.compile(r"ignore\s+(?:all|previous)\s+instructions|\bsystem\s*:|you are now|(?:pay|transfer).{0,80}\baccount\b|urgent payment|[A-Za-z0-9+/]{180,}={0,2}",re.I|re.S)

def extract_invoice_pdf(path:Path,*,ocr_provider=None)->dict:
    pages=list(PdfPlumberParser(tables_enabled=True).iter_pages(path,100));texts=[p.raw_text for p in pages];ocr_used=False;scan=any(not p.raw_text.strip() for p in pages)
    if scan:
        from app.core.config import get_settings
        cfg=get_settings()
        if ocr_provider is None and cfg.ocr_enabled:
            from app.extraction.ocr import get_ocr_provider
            ocr_provider=get_ocr_provider(cfg)
        if ocr_provider is not None and ocr_provider.available():
            import time
            if hasattr(ocr_provider,'deadline'):ocr_provider.deadline=time.monotonic()+cfg.ocr_document_timeout_seconds
            for index,page in enumerate(pages[:min(3,cfg.ocr_max_pages)]):
                if not page.raw_text.strip():
                    result=ocr_provider.ocr_page(path,page.page_number)
                    if result.text:texts[index]=result.text;ocr_used=True
    text="\n".join(texts)
    def find(pattern):
        m=re.search(pattern,text,re.I);return m.group(1).strip() if m else None
    number=find(r"invoice\s*(?:number|no\.?|#)\s*[:\-]?\s*([A-Z0-9/\-]+)")
    date_text=find(r"invoice\s*date\s*[:\-]?\s*(\d{1,2}[-/]\d{1,2}[-/]\d{4})")
    due_text=find(r"due\s*date\s*[:\-]?\s*(\d{1,2}[-/]\d{1,2}[-/]\d{4})")
    terms=find(r"\bnet\s+(\d{1,3})\b")
    def date_of(value):
        if not value:return None
        for fmt in ("%d-%m-%Y","%d/%m/%Y"):
            try:return datetime.strptime(value,fmt).date()
            except ValueError:pass
        return None
    invoice_date=date_of(date_text);due_date=date_of(due_text)
    if not due_date and invoice_date and terms:due_date=invoice_date+timedelta(days=int(terms))
    amounts={}
    for key,label in (("taxable","taxable value"),("cgst","cgst"),("sgst","sgst"),("igst","igst"),("total","grand total|invoice total|total amount")):
        value=find(rf"(?:{label})\s*[:\-]?\s*((?:₹|rs\.?|inr)?\s*[\d,]+(?:\.\d{{1,2}})?)")
        amounts[key]=parse_inr_to_paise(value)[0] if value else None
    known_taxes=sum(amounts[k] or 0 for k in ("cgst","sgst","igst"))
    reasons=["OCR_DERIVED_FIELDS_REVIEW"] if ocr_used else ["SCANNED_PAGE_REVIEW"] if scan else []
    if amounts["taxable"] is not None and amounts["total"] is not None and abs(amounts["taxable"]+known_taxes-amounts["total"])>100:reasons.append("TOTALS_MISMATCH")
    gstin=find(r"buyer\s*gstin\s*[:\-]?\s*([0-9A-Z]{15})")
    if gstin and not validate_gstin(gstin):reasons.append("INVALID_GSTIN")
    if INJECTION.search(text):reasons.append("INSTRUCTION_TEXT_DETECTED")
    buyer=find(r"buyer\s*[:\-]\s*([^\n\r]+)")
    seller=find(r"seller\s*[:\-]\s*([^\n\r]+)")
    if not seller:
        first=next((line.strip() for line in text.splitlines() if line.strip()),None)
        seller=first if first and "invoice" not in first.lower() else None
    return {"invoice_number":number,"invoice_date":invoice_date,"due_date":due_date,"buyer_gstin":gstin,"buyer_name":buyer,"seller_name":seller,"amounts":amounts,"text":text,"source_location":{"page":1,"quote":(number or "")},"method":"OCR_REVIEW" if ocr_used else "NATIVE","reasons":reasons}
