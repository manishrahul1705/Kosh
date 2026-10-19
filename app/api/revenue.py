"""Authorized optional revenue signal read, with no external model calls."""
from datetime import date
import importlib.util
from fastapi import APIRouter,Depends
from sqlalchemy.orm import Session
from sqlalchemy import select
from app.database.kosh_models import KoshOperationRecord
from app.api.deps import get_db
from app.api.seller_authorization import AuthorizedSeller,require_seller_read
from app.finance.forecast import load_inputs
from app.finance.revenue import revenue_signal
from app.core.config import get_settings
from app.audit.ledger import append_event
router=APIRouter(prefix="/api/kosh/sellers/{seller_id}/revenue",tags=["kosh-revenue"])
@router.get("")
def signal(seller_id:int,db:Session=Depends(get_db),access:AuthorizedSeller=Depends(require_seller_read)):
    as_of=date.fromisoformat(get_settings().kosh_as_of_date or date.today().isoformat());inputs=load_inputs(db,seller_id,as_of,include_addon_events=False)
    result=revenue_signal(inputs.historical_sales)
    history=[{"as_of":row.data["as_of"],"total_paise":row.data["total_paise"]} for row in db.scalars(
        select(KoshOperationRecord).where(KoshOperationRecord.seller_id==seller_id,
        KoshOperationRecord.kind=="REVENUE_SIGNAL").order_by(KoshOperationRecord.id))]
    append_event(db,seller_id=seller_id,actor_type="HUMAN",actor_id=str(access.user_id),action="revenue.signal.read",tier="T0",payload={"model":result.get('model')},policy_decision="ALLOW");db.commit()
    return {**result,"history":history,"optional":True,"enabled_by_default":False,"source":"Owned historical sales invoices","available_packages":{n:importlib.util.find_spec(n) is not None for n in ('xgboost','shap')}}
