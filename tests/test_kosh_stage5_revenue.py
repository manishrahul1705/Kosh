"""Explainable optional signal, no extra dependencies and exact disabled base."""
from datetime import date
from dataclasses import replace
from app.finance.revenue import revenue_signal
from app.finance.forecast import ForecastInputs,simulate

def test_contributions_sum_and_optional_cash_component():
    model=revenue_signal([10000,11000,12000,13000,14000,15000,16000,17000])
    assert 'Dependency-free' in model['model'] and 'not SHAP' in model['explainability']
    for week in model['weeks']:assert week['predicted_revenue_paise']==week['level_contribution_paise']+week['trend_contribution_paise'] and isinstance(week['predicted_revenue_paise'],int)
    inputs=ForecastInputs(0,(),(),(0,),{},(10000,)*26,(0,)*26,0)
    args=dict(as_of=date(2026,10,13),n_paths=20,seed=42,include_forecast_sales=True,buffer_paise=0)
    base=simulate(inputs,**args);enriched=replace(inputs,revenue_predictions=tuple(w['predicted_revenue_paise'] for w in model['weeks']))
    result=simulate(enriched,**args)
    assert result!=base and result==simulate(enriched,**args)
    assert any(w['expected_inflow_revenue_paise']>0 for w in result['weeks'])
    assert all(w['expected_inflow_forecast_paise']==0 for w in result['weeks'])
    assert simulate(replace(enriched,revenue_predictions=()),**args)==base
    assert revenue_signal([])['status']=='REVIEW_REQUIRED'
