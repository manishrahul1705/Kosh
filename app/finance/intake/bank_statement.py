"""Import bounded bank JSON/CSV records with masked account references."""
import csv,json,re
from datetime import datetime
from pathlib import Path
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.database.kosh_models import KoshBankTransaction
from app.finance.intake.money import parse_inr_to_paise

def _mask(value:str)->str:return "****"+re.sub(r"\D","",value)[-4:]
def import_bank_statement(session:Session,*,seller_id:int,path:Path,version_id:int)->dict:
    if path.read_bytes().lstrip().startswith((b"{",b"[")):
        data=json.loads(path.read_text(encoding="utf-8-sig"));account=data.get("account_ref_masked") or data.get("account") or "0000";rows=data.get("transactions",[])
    else:
        with path.open(encoding="utf-8-sig",newline="") as stream:rows=list(csv.DictReader(stream))
        account=rows[0].get("account_ref_masked","0000") if rows else "0000"
    created=review=0
    for row in rows:
        txn_id=str(row.get("txn_id") or "").strip()
        if not txn_id or session.scalar(select(KoshBankTransaction).where(KoshBankTransaction.seller_id==seller_id,KoshBankTransaction.txn_id==txn_id)):continue
        amount,reason=parse_inr_to_paise(str(row.get("amount","")));balance,breason=parse_inr_to_paise(str(row.get("balance","")))
        try:txn_date=datetime.strptime(str(row.get("date")),"%Y-%m-%d").date()
        except ValueError:review+=1;continue
        if reason or breason:review+=1;continue
        signed=amount if str(row.get("type","CREDIT")).upper()=="CREDIT" else -amount
        session.add(KoshBankTransaction(seller_id=seller_id,account_ref_masked=_mask(account),txn_id=txn_id,txn_date=txn_date,narration=str(row.get("narration") or ""),amount_paise=signed,balance_paise=balance,source_document_version_id=version_id));created+=1
    session.flush();return {"created":created,"review":review}
