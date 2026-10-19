"""Dependency-free explainable revenue signal; cash forecast remains authoritative."""
from decimal import Decimal,ROUND_HALF_UP

def paise(value):return int(value.quantize(Decimal(1),rounding=ROUND_HALF_UP))
def revenue_signal(history):
    values=[Decimal(value) for value in history[-8:]]
    if not values:return {"status":"REVIEW_REQUIRED","weeks":[],"reason":"No historical sales evidence"}
    level=sum(values)/len(values)
    older=values[:len(values)//2];recent=values[len(values)//2:]
    trend=(sum(recent)/len(recent)-sum(older)/len(older))/max(1,len(recent)) if older else Decimal(0)
    weeks=[]
    for index in range(1,14):
        # Bounded trend avoids unverified exponential growth.
        bounded=max(-level/4,min(level/4,trend));raw=level+bounded*min(index,4);prediction=max(0,paise(raw))
        weeks.append({"week_index":index,"predicted_revenue_paise":prediction,"level_contribution_paise":paise(level),"trend_contribution_paise":prediction-paise(level)})
    return {"status":"COMPUTED","model":"Dependency-free recent-level plus bounded-trend model","weeks":weeks,"reason":"Computed from the last eight observed weekly sales totals. Not a receipt or underwriting fact.","explainability":"Level plus bounded trend contributions sum exactly to each prediction; these are not SHAP values.","cash_timing":"Uses the existing forecast six-week invoice credit assumption and sampled observed portfolio delays; replaces forecast sales rather than double-counting them."}
