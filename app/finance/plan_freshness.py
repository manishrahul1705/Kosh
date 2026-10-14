"""Read-only plan display validity against the latest computed cash basis."""
from sqlalchemy import select
from app.database.kosh_models import KoshForecastRun
from app.finance.forecast import current_fingerprint

def display_status(db,plan):
    if plan.status!='VALID':return plan.status
    latest=db.scalar(select(KoshForecastRun).where(KoshForecastRun.seller_id==plan.seller_id,KoshForecastRun.status=='SUCCESS').order_by(KoshForecastRun.id.desc()))
    if latest and ((plan.forecast_run_id!=latest.id and plan.planning_details.get('actual_execution',{}).get('forecast_run_id')!=latest.id) or current_fingerprint(db,latest)!=latest.input_fingerprint):return 'STALE'
    return plan.status
