"""Cash-buffer alerts and deterministic counterfactual root causes."""
from __future__ import annotations
from collections import defaultdict
from datetime import date
from app.finance.forecast import ForecastInputs,simulate

def build_alert(inputs:ForecastInputs,forecast:dict[str,object],*,as_of:date,threshold:float=.5)->dict[str,object]|None:
    alert_week=next((row for row in forecast["weeks"] if row["prob_below_buffer"]>=threshold),None)
    if not alert_week:return None
    base=int(alert_week["expected_shortfall_paise"]);grouped=defaultdict(list)
    for invoice in inputs.invoices:
        if invoice["direction"]=="RECEIVABLE":grouped[int(invoice["counterparty_id"])].append(invoice)
    causes=[]
    for counterparty_id,invoices in grouped.items():
        immediate=simulate(inputs,as_of=as_of,n_paths=int(forecast["n_paths"]),seed=int(forecast["seed"]),include_forecast_sales=True,buffer_paise=int(forecast["buffer_paise"]),customer_delay_shift_days={counterparty_id:-365})
        contribution=max(0,base-int(immediate["weeks"][int(alert_week["week_index"])-1]["expected_shortfall_paise"]))
        typical=sorted(inputs.customer_delays.get(counterparty_id,inputs.portfolio_delays))[len(inputs.customer_delays.get(counterparty_id,inputs.portfolio_delays))//2]
        causes.append({"type":"CUSTOMER","counterparty_id":counterparty_id,"customer":invoices[0]["party"],"invoice_numbers":[row["number"] for row in invoices],"amount_paise":sum(int(row["amount_paise"]) for row in invoices),"typical_delay_days":typical,"current_delay_days":max((as_of-row["due_date"]).days for row in invoices),"contribution_paise":contribution})
    clustered=[item for item in inputs.obligations if any(int(alert_week["week_index"])==(date.fromisoformat(raw)-forecast["weeks"][0]["week_start"]).days//7+1 for raw in item["dates"])]
    if clustered:causes.append({"type":"OBLIGATION_CLUSTER","label":", ".join(str(row["label"]) for row in clustered),"amount_paise":sum(int(row["amount_paise"]) for row in clustered),"contribution_paise":sum(int(row["amount_paise"]) for row in clustered)})
    causes.sort(key=lambda row:int(row["contribution_paise"]),reverse=True)
    return {"week_index":alert_week["week_index"],"probability":alert_week["prob_below_buffer"],"expected_shortfall_paise":base,"peak_expected_shortfall_paise":max(int(row["expected_shortfall_paise"]) for row in forecast["weeks"]),"causes":causes[:5],"summary":f"Week {alert_week['week_index']} ({alert_week['week_start'].strftime('%d %b')}-{alert_week['week_end'].strftime('%d %b')}): {alert_week['prob_below_buffer']:.0%} chance of falling below the cash buffer."}
