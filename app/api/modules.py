"""Owner module settings; every module remains visible and seller-scoped."""
from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel,ConfigDict,StrictBool
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.api.deps import get_db
from app.api.seller_authorization import AuthorizedSeller,require_seller_read,require_seller_owner
from app.database.kosh_models import KoshModuleFlag,KoshForecastRun
from app.database.session import reserve_sqlite_writer
from app.finance.modules import MODULES,enabled
from app.audit.ledger import append_event
from app.policy.controls import editable_control
from app.utils.dates import utcnow
router=APIRouter(prefix='/api/kosh/sellers/{seller_id}/modules',tags=['kosh-modules'])
class FlagIn(BaseModel):
    model_config=ConfigDict(extra='forbid')
    enabled:StrictBool
@router.get('')
def listing(seller_id:int,db:Session=Depends(get_db),access:AuthorizedSeller=Depends(require_seller_read)):
    items=[{'module':key,'name':data[0],'cash_feed':data[1],'href':data[2],'enabled':enabled(db,seller_id,key)} for key,data in MODULES.items()]
    append_event(db,seller_id=seller_id,actor_type='HUMAN',actor_id=str(access.user_id),action='modules.read',tier='T0',payload={},policy_decision='ALLOW');db.commit();return {'role':access.role,'items':items}
@router.put('/{module}')
def toggle(seller_id:int,module:str,payload:FlagIn,db:Session=Depends(get_db),access:AuthorizedSeller=Depends(require_seller_owner)):
    if module not in MODULES:raise HTTPException(404,'Module not found')
    reserve_sqlite_writer(db,renew_read=True);control=editable_control(db,seller_id)
    db.refresh(control,with_for_update=True)
    row=db.get(KoshModuleFlag,(seller_id,module))
    if row is None:row=KoshModuleFlag(seller_id=seller_id,module=module);db.add(row)
    row.enabled=payload.enabled;row.updated_at=utcnow()
    append_event(db,seller_id=seller_id,actor_type='HUMAN',actor_id=str(access.user_id),action='module.toggle',tier='T1',payload={'module':module,'enabled':payload.enabled},policy_decision='ALLOW');db.commit()
    latest=db.scalar(select(KoshForecastRun).where(KoshForecastRun.seller_id==seller_id,KoshForecastRun.status=='SUCCESS').order_by(KoshForecastRun.id.desc()))
    if latest:
        from app.api.cash import run_forecast,ForecastRunIn
        run_forecast(seller_id,ForecastRunIn(n_paths=latest.n_paths,seed=latest.seed,include_forecast_sales=latest.include_forecast_sales,include_addon_events=latest.params.get('include_addon_events',True),include_customer_history=latest.params.get('include_customer_history',False),include_revenue_signal=latest.params.get('include_revenue_signal',False)),db,access)
    return {'module':module,'enabled':payload.enabled,'forecast_refreshed':latest is not None,'visible':True}
