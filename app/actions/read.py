"""Read-only queries; no intent factory or execution imports."""
from datetime import datetime,timezone,timedelta
from zoneinfo import ZoneInfo
from sqlalchemy import select,func,or_
from app.database.kosh_models import KoshActionIntent
from app.utils.dates import utcnow

def day_used(db,seller_id,*,now=None,exclude_intent_id=None):
    now=now or utcnow()
    local=now.replace(tzinfo=timezone.utc).astimezone(ZoneInfo("Asia/Kolkata"))
    start=local.replace(hour=0,minute=0,second=0,microsecond=0).astimezone(timezone.utc).replace(tzinfo=None)
    rows=db.scalars(select(KoshActionIntent).where(KoshActionIntent.seller_id==seller_id,KoshActionIntent.status.in_(["APPROVED","EXECUTING","SUCCEEDED"]),KoshActionIntent.approved_at>=start,KoshActionIntent.approved_at<start+timedelta(days=1),or_(KoshActionIntent.status!="APPROVED",KoshActionIntent.expires_at>now))).all()
    return sum(row.params.get("amount_paise",0) for row in rows if row.id!=exclude_intent_id)

def out(row):
    result={c.name:(getattr(row,c.name).isoformat()+"Z" if isinstance(getattr(row,c.name),datetime) else getattr(row,c.name)) for c in row.__table__.columns}
    if result.get('status')=='APPROVED' and getattr(row,'expires_at',None) and row.expires_at<=utcnow():result['status']='EXPIRED'
    return result

def owned(db,seller_id,intent_id,*,lock=False):
    stmt=select(KoshActionIntent).where(KoshActionIntent.id==intent_id,KoshActionIntent.seller_id==seller_id)
    return db.scalar(stmt.with_for_update() if lock else stmt)
