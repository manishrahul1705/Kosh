"""Verification for the persisted audit hash chain."""
from dataclasses import dataclass
import hashlib
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.audit.ledger import GENESIS_HASH,canonical_json,event_hash
from app.database.kosh_models import KoshAuditEntry

@dataclass(frozen=True)
class VerifyResult:
    valid: bool
    entries: int
    broken_at_sequence: int|None=None
    reason: str|None=None

def verify_chain(session: Session) -> VerifyResult:
    rows=list(session.scalars(select(KoshAuditEntry).order_by(KoshAuditEntry.sequence)))
    previous=GENESIS_HASH
    for expected,row in enumerate(rows,1):
        if row.sequence!=expected:return VerifyResult(False,len(rows),row.sequence,"NON_CONTIGUOUS_SEQUENCE")
        if row.prev_hash!=previous:return VerifyResult(False,len(rows),row.sequence,"PREVIOUS_HASH_MISMATCH")
        if row.params_hash!=hashlib.sha256(canonical_json(row.payload).encode()).hexdigest():return VerifyResult(False,len(rows),row.sequence,"PAYLOAD_HASH_MISMATCH")
        if row.entry_hash!=event_hash(row):return VerifyResult(False,len(rows),row.sequence,"ENTRY_HASH_MISMATCH")
        previous=row.entry_hash
    return VerifyResult(True,len(rows))
