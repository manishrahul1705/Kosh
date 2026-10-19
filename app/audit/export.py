"""Tenant-private audit JSONL with opaque anchors for other sellers' chain links."""
import hashlib,json
from sqlalchemy import select
from app.audit.ledger import canonical_json,GENESIS_HASH
from app.audit.verify import verify_chain
from app.database.kosh_models import KoshAuditEntry

FORMAT="KOSH_AUDIT_V1"

def scoped_records(rows,seller_id):
    records=[]
    for row in rows:
        if row.seller_id==seller_id:
            record={"type":"ENTRY","row":{column.name:getattr(row,column.name) for column in row.__table__.columns}}
        else:record={"type":"ANCHOR","sequence":row.sequence,"prev_hash":row.prev_hash,"entry_hash":row.entry_hash}
        records.append(record)
    header={"type":"HEADER","format":FORMAT,"seller_id":seller_id,"head_sequence":rows[-1].sequence if rows else 0,"head_hash":rows[-1].entry_hash if rows else GENESIS_HASH,"own_entries":sum(row.seller_id==seller_id for row in rows)}
    return [header,*records]

def export_jsonl(db,seller_id):
    result=verify_chain(db)
    if not result.valid:raise ValueError("AUDIT_CHAIN_INVALID")
    rows=list(db.scalars(select(KoshAuditEntry).order_by(KoshAuditEntry.sequence)))
    return "\n".join(canonical_json(record) for record in scoped_records(rows,seller_id))+"\n"

def verify_jsonl(db,seller_id,text):
    def invalid(reason):return {"valid":False,"reason":reason,"entries":0}
    if len(text)>2_000_000:return invalid("EXPORT_TOO_LARGE")
    try:records=[json.loads(line) for line in text.splitlines() if line.strip()]
    except (ValueError,TypeError):return invalid("INVALID_JSONL")
    if not records or not isinstance(records[0],dict):return invalid("HEADER_REQUIRED")
    header=records[0]
    if header.get("format")!=FORMAT or type(header.get("seller_id")) is not int or header["seller_id"]!=seller_id:return invalid("SELLER_SCOPE_MISMATCH")
    sequence=header.get("head_sequence")
    if type(sequence) is not int or sequence<0:return invalid("INVALID_HEAD_SEQUENCE")
    chain=verify_chain(db)
    if not chain.valid:return invalid("DATABASE_CHAIN_INVALID")
    rows=list(db.scalars(select(KoshAuditEntry).where(KoshAuditEntry.sequence<=sequence).order_by(KoshAuditEntry.sequence)))
    expected=scoped_records(rows,seller_id)
    if len(records)!=len(expected):return invalid("ENTRY_COUNT_MISMATCH")
    for index,(actual,wanted) in enumerate(zip(records,expected)):
        if canonical_json(actual)!=canonical_json(wanted):return invalid("HEADER_MISMATCH" if index==0 else "ENTRY_OR_ANCHOR_MISMATCH")
    return {"valid":True,"entries":header["own_entries"],"chain_links":sequence,"head_hash":header["head_hash"],"reason":None,"verification_basis":"Trusted database chain; foreign payloads remain undisclosed."}

def security_counts(db,seller_id):
    events=db.scalars(select(KoshAuditEntry.action).where(KoshAuditEntry.seller_id==seller_id)).all()
    return {"blocked_intents":events.count("security.intent_blocked"),"failed_otps":events.count("security.otp_failed"),"token_replays":events.count("security.token_replay"),"injection_detections":events.count("security.injection_detected"),"reconciliation_mismatches":events.count("security.reconciliation_mismatch")}
