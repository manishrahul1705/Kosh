"""Persistent policy settings with UTC cool-off dates."""
from datetime import datetime
from sqlalchemy import select
from app.core.config import get_settings
from app.database.kosh_models import KoshPolicyControl
from app.policy.rules import PolicyContext
from app.utils.dates import utcnow


def control(db,seller_id=None):
    key="GLOBAL" if seller_id is None else f"SELLER:{seller_id}"
    return db.scalar(select(KoshPolicyControl).where(KoshPolicyControl.scope_key==key))


def editable_control(db,seller_id=None):
    row=control(db,seller_id)
    if row is None:
        settings=get_settings()
        row=KoshPolicyControl(scope_key="GLOBAL" if seller_id is None else f"SELLER:{seller_id}",seller_id=seller_id,kill_switch=False,max_action_paise=settings.kosh_action_limit_paise,max_day_paise=settings.kosh_day_limit_paise,allowlist=[],updated_at=utcnow())
        db.add(row);db.flush()
    return row


def context(db,seller_id,*,now=None,day_used_paise=0,**kwargs):
    settings=get_settings();global_row=control(db);seller_row=control(db,seller_id)
    entries={} if seller_row is None else {entry["key"]:datetime.fromisoformat(entry["added_at"].removesuffix("Z")) for entry in seller_row.allowlist}
    return PolicyContext(now=now or utcnow(),global_kill=settings.kosh_global_kill_switch or bool(global_row and global_row.kill_switch),seller_kill=bool(seller_row and seller_row.kill_switch),max_action_paise=min(global_row.max_action_paise if global_row else settings.kosh_action_limit_paise,seller_row.max_action_paise if seller_row else settings.kosh_action_limit_paise),max_day_paise=min(global_row.max_day_paise if global_row else settings.kosh_day_limit_paise,seller_row.max_day_paise if seller_row else settings.kosh_day_limit_paise),day_used_paise=day_used_paise,allowlist=entries,**kwargs)
