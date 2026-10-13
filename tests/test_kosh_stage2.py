"""Stage 2 cash forecast, alert, analysis and API contracts."""
from datetime import date,timedelta
from types import SimpleNamespace
from dataclasses import replace
import time
from sqlalchemy import select
from app.database.kosh_models import KoshAlert,KoshCounterparty,KoshForecastRun,KoshInvoice
from app.finance.alerts import build_alert
from app.finance.forecast import ForecastInputs,fingerprint,load_inputs,obligation_dates,simulate,week_bounds
from scripts.kosh_generate_demo import generate
from app.finance.intake.invoice_pdf import extract_invoice_pdf
from tests.conftest import sign_in
from tests.matching_factories import make_seller

SUBJECT="eeeeeeee-0000-0000-0000-000000000021"

def inputs(review=0):
    return ForecastInputs(20_000_000,({"id":1,"counterparty_id":1,"party":"Known Customer","number":"I-1","direction":"RECEIVABLE","due_date":date(2026,10,14),"amount_paise":40_000_000},),(),(0,),{1:(0,0,0,0,0)},(10_000_000,)*26,(12_000_000,)*26,review)

def test_week_one_contains_as_of_and_runs_monday_to_sunday():
    assert week_bounds(date(2026,10,13))==(date(2026,10,12),date(2026,10,18))

def test_obligation_calendar_rules():
    payroll=SimpleNamespace(active=True,recurrence="MONTHLY",kind="PAYROLL",next_due_date=date(2026,10,1),day_of_month=31)
    gst=SimpleNamespace(active=True,recurrence="MONTHLY",kind="GST",next_due_date=date(2026,10,1),day_of_month=20)
    tds=SimpleNamespace(active=True,recurrence="MONTHLY",kind="TDS",next_due_date=date(2026,11,1),day_of_month=7)
    assert date(2026,10,30) in obligation_dates(payroll,date(2026,10,1),date(2026,11,30))
    assert date(2026,10,20) in obligation_dates(gst,date(2026,10,1),date(2026,11,30))
    assert date(2026,11,9) in obligation_dates(tds,date(2026,10,1),date(2026,11,30))

def test_fixed_invoice_lands_in_exact_week():
    result=simulate(inputs(),as_of=date(2026,10,13),n_paths=20,seed=1,include_forecast_sales=False,buffer_paise=0)
    assert result["weeks"][0]["expected_inflow_committed_paise"]==40_000_000
    assert sum(row["expected_inflow_committed_paise"] for row in result["weeks"][1:])==0

def test_determinism_and_fingerprint_changes():
    first=simulate(inputs(),as_of=date(2026,10,13),n_paths=50,seed=42);second=simulate(inputs(),as_of=date(2026,10,13),n_paths=50,seed=42)
    assert first==second
    assert fingerprint(inputs(),{"seed":42})!=fingerprint(inputs(1),{"seed":42})

def test_review_amount_reported_but_excluded():
    plain=simulate(inputs(),as_of=date(2026,10,13),n_paths=10,seed=1,include_forecast_sales=False);reviewed=simulate(inputs(55_000),as_of=date(2026,10,13),n_paths=10,seed=1,include_forecast_sales=False)
    assert plain["weeks"]==reviewed["weeks"] and reviewed["under_review_paise"]==55_000

def test_root_cause_known_customer_is_first():
    data=replace(inputs(),customer_delays={1:(30,30,30,30,30)},portfolio_delays=(30,));forecast=simulate(data,as_of=date(2026,10,13),n_paths=100,seed=9,include_forecast_sales=False,buffer_paise=50_000_000)
    alert=build_alert(data,forecast,as_of=date(2026,10,13),threshold=.5)
    assert alert and alert["causes"][0]["customer"]=="Known Customer"

def test_performance_bound():
    started=time.perf_counter();simulate(inputs(),as_of=date(2026,10,13),n_paths=2000,seed=42)
    assert time.perf_counter()-started<5

def test_generated_pdfs_are_native_reconciled_and_date_bounded(tmp_path):
    manifest=generate(42,tmp_path,date(2026,10,13));files=sorted((tmp_path/"invoices").glob("*.pdf"));assert manifest["invoice_pdfs"]==len(files)==15
    parsed=[extract_invoice_pdf(path) for path in files]
    assert all(row["method"]=="NATIVE" and row["amounts"]["total"] is not None and "TOTALS_MISMATCH" not in row["reasons"] for row in parsed)
    poison=next(row for row in parsed if row["invoice_number"]=="POISON-001");assert poison["seller_name"]=="Aster Alloy Supplies" and "INSTRUCTION_TEXT_DETECTED" in poison["reasons"]

def test_historical_inputs_treat_future_payment_as_unknown(db):
    seller=make_seller(db,name="No leakage seller");party=KoshCounterparty(seller_id=seller.id,name="Customer",kind="CUSTOMER");db.add(party);db.flush()
    invoice=KoshInvoice(seller_id=seller.id,counterparty_id=party.id,direction="RECEIVABLE",invoice_number="FUTURE-1",invoice_date=date(2026,7,1),due_date=date(2026,8,1),amount_paise=12300,status="PAID",paid_date=date(2026,9,1),paid_amount_paise=12300);db.add(invoice);db.flush()
    historic=load_inputs(db,seller.id,date(2026,8,15));current=load_inputs(db,seller.id,date(2026,9,2))
    assert historic.invoices[0]["amount_paise"]==12300 and current.invoices==()

def test_forecast_routes_authorize_and_whatif_is_not_persisted(client,db):
    owner=make_seller(db,name="Forecast owner",owner_subject=SUBJECT);other=make_seller(db,name="Forecast other")
    sign_in(client.app,SUBJECT)
    assert client.post(f"/api/kosh/sellers/{other.id}/forecast/run",json={}).status_code==403
    response=client.post(f"/api/kosh/sellers/{owner.id}/forecast/run",json={"n_paths":20,"seed":3});assert response.status_code==200
    before=db.scalar(select(KoshForecastRun).where(KoshForecastRun.seller_id==owner.id).count()) if False else len(db.scalars(select(KoshForecastRun).where(KoshForecastRun.seller_id==owner.id)).all())
    whatif=client.post(f"/api/kosh/sellers/{owner.id}/forecast/whatif",json={"customer_delay_shift_days":{},"exclude_counterparties":[],"extra_inflows":[]});assert whatif.status_code==200
    db.expire_all();after=len(db.scalars(select(KoshForecastRun).where(KoshForecastRun.seller_id==owner.id)).all());assert after==before
    assert client.get(f"/api/kosh/sellers/{owner.id}/analysis").status_code==200

def test_alert_acknowledge_is_tenant_scoped(client,db):
    owner=make_seller(db,name="Alert owner",owner_subject=SUBJECT);other=make_seller(db,name="Alert other");sign_in(client.app,SUBJECT)
    run=KoshForecastRun(seller_id=other.id,as_of_date=date(2026,10,13),horizon_weeks=13,n_paths=1,seed=1,params={},input_fingerprint="a"*64,include_forecast_sales=True,buffer_paise=1,status="SUCCESS",created_by_user_id=1);db.add(run);db.flush();alert=KoshAlert(seller_id=other.id,run_id=run.id,week_index=1,probability=1,expected_shortfall_paise=1,peak_expected_shortfall_paise=1,causes=[],status="OPEN");db.add(alert);db.commit()
    assert client.post(f"/api/kosh/sellers/{other.id}/alerts/{alert.id}/acknowledge").status_code==403
