"""Canonical append-only audit-chain operations."""
from __future__ import annotations
from datetime import date, datetime, timezone
from decimal import Decimal
import hashlib, json
from typing import Any
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.database.kosh_models import KoshAuditEntry
from app.database.session import reserve_sqlite_writer
from app.utils.dates import utcnow

GENESIS_HASH = "0" * 64

def _json_default(value: object) -> str:
    if isinstance(value, Decimal): return format(value, "f")
    if isinstance(value, datetime):
        if value.tzinfo is None: value=value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    if isinstance(value, date): return value.isoformat()
    raise TypeError(f"Unsupported audit value: {type(value).__name__}")

def canonical_json(value: object) -> str:
    return json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False,default=_json_default)

def _iso_utc(value: datetime) -> str:
    if value.tzinfo is None: value=value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00","Z")

def event_hash(entry: KoshAuditEntry) -> str:
    parts=[entry.prev_hash,str(entry.sequence),_iso_utc(entry.recorded_at),"" if entry.seller_id is None else str(entry.seller_id),entry.actor_type,entry.actor_id or "",entry.action,entry.tier,entry.policy_decision,entry.approval_id or "",entry.params_hash]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()

def append_event(session: Session, *, seller_id: int | None, actor_type: str, actor_id: str | None,
                 action: str, tier: str, payload: dict[str, Any], policy_decision: str,
                 approval_id: str | None=None) -> KoshAuditEntry:
    reserve_sqlite_writer(session,renew_read=True)
    previous=session.scalar(select(KoshAuditEntry).order_by(KoshAuditEntry.sequence.desc()).limit(1))
    payload_json=canonical_json(payload); now=utcnow()
    entry=KoshAuditEntry(seller_id=seller_id,sequence=(previous.sequence if previous else 0)+1,
        actor_type=actor_type,actor_id=actor_id,action=action,tier=tier,
        params_hash=hashlib.sha256(payload_json.encode("utf-8")).hexdigest(),payload=json.loads(payload_json),
        policy_decision=policy_decision,approval_id=approval_id,
        prev_hash=previous.entry_hash if previous else GENESIS_HASH,entry_hash="0"*64,
        recorded_at=now,created_at=now,updated_at=now)
    entry.entry_hash=event_hash(entry);session.add(entry);session.flush();return entry
