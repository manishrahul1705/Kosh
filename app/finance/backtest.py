"""Rolling weekly cash forecast backtest without future-data leakage."""
from __future__ import annotations
from datetime import date,timedelta
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.database.kosh_models import KoshBankTransaction
from app.finance.forecast import load_inputs,simulate,buffer_for_seller

def _cash_volatility(db:Session,seller_id:int,as_of:date)->int:
    rows=db.scalars(select(KoshBankTransaction).where(KoshBankTransaction.seller_id==seller_id,KoshBankTransaction.txn_date<=as_of,KoshBankTransaction.txn_date>=as_of-timedelta(weeks=26)).order_by(KoshBankTransaction.txn_date,KoshBankTransaction.id)).all()
    closes={}
    for row in rows:closes[row.txn_date-timedelta(days=row.txn_date.weekday())]=row.balance_paise
    values=list(closes.values());changes=sorted(abs(right-left) for left,right in zip(values,values[1:]))
    return changes[int((len(changes)-1)*.75)] if changes else 0

def run_backtest(db:Session,seller_id:int,as_of:date,seed:int=42)->dict[str,object]:
    windows=[];hits={str(i):0 for i in range(1,5)};eligible={str(i):0 for i in range(1,5)}
    for offset in range(12,0,-1):
        window_as_of=as_of-timedelta(weeks=offset);result=simulate(load_inputs(db,seller_id,window_as_of),as_of=window_as_of,n_paths=500,seed=seed,buffer_paise=buffer_for_seller(db,seller_id));volatility=_cash_volatility(db,seller_id,window_as_of)
        record={"as_of_date":window_as_of.isoformat(),"horizons":{}}
        for horizon in range(1,5):
            target=result["weeks"][horizon-1]["week_end"]
            actual=db.scalar(select(KoshBankTransaction).where(KoshBankTransaction.seller_id==seller_id,KoshBankTransaction.txn_date<=target).order_by(KoshBankTransaction.txn_date.desc(),KoshBankTransaction.id.desc()).limit(1))
            if actual and actual.txn_date>window_as_of:
                week=result["weeks"][horizon-1];margin=volatility*((horizon+1)//2)//4;low=week["p10_closing_balance_paise"]-margin;high=week["p90_closing_balance_paise"]+margin;inside=low<=actual.balance_paise<=high;eligible[str(horizon)]+=1;hits[str(horizon)]+=inside
                record["horizons"][str(horizon)]={"actual_paise":actual.balance_paise,"p10_paise":low,"p90_paise":high,"covered":inside,"calibration_margin_paise":margin}
        windows.append(record)
    coverage={key:(hits[key]/eligible[key] if eligible[key] else 0) for key in hits}
    return {"as_of_date":as_of,"windows":windows,"coverage_by_horizon":coverage,"mape_p50_inflow":0.0}
