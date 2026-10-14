"""Owner flags stay visible, suppress inputs/actions and invalidate stale plan views."""
from datetime import date
from fastapi.encoders import jsonable_encoder
from sqlalchemy import select
from app.finance.forecast import load_inputs,simulate
from app.api.financing import _plan_out
from app.actions.planner import create_from_plan_line
from app.actions.approvals import approve,ActionError
from app.database.kosh_models import KoshPlan
from tests.test_kosh_stage4_intents import planned_line,SUBJECT
from tests.conftest import sign_in
import pytest

def test_owner_module_off_preserves_listing_and_restores_base_cash(client,db):
    seller,user,_,_=planned_line(db);sign_in(client.app,SUBJECT);prefix=f'/api/kosh/sellers/{seller.id}'
    modules=client.get(prefix+'/modules').json();assert len(modules['items'])==18 and all(m['enabled'] for m in modules['items'])
    event=client.post(prefix+'/cash-events',json={'event_type':'EXPECTED_RECEIVABLE','source_module':'sales','evidence_ref':'sale:flag-test','event_date':'2026-10-16','amount_paise':10000}).json();client.post(prefix+f"/cash-events/{event['id']}/confirm")
    client.post(prefix+'/forecast/run',json={'seed':42,'n_paths':10,'include_forecast_sales':False})
    before=client.get(prefix+'/forecast/latest').json();assert before['weeks'][0]['expected_inflow_addon_paise']==10000
    toggle=client.put(prefix+'/modules/sales',json={'enabled':False}).json();assert toggle['forecast_refreshed'] and toggle['visible']
    db.rollback();base=simulate(load_inputs(db,seller.id,date(2026,10,13),include_addon_events=False),as_of=date(2026,10,13),n_paths=10,seed=42,include_forecast_sales=False,buffer_paise=100000000)
    off=client.get(prefix+'/forecast/latest').json();assert [{k:v for k,v in w.items() if k!='run_id'} for w in off['weeks']]==jsonable_encoder(base['weeks'])
    rows=client.get(prefix+'/modules').json()['items'];assert len(rows)==18 and next(m for m in rows if m['module']=='sales')['enabled'] is False
    assert client.post(prefix+'/cash-events',json={'event_type':'EXPECTED_RECEIVABLE','source_module':'sales','evidence_ref':'sale:disabled','event_date':'2026-10-16','amount_paise':100}).status_code==403

def test_module_disable_stops_later_approval_and_live_changes_mark_plan_stale(client,db):
    seller,user,invoice,line=planned_line(db);sign_in(client.app,SUBJECT);prefix=f'/api/kosh/sellers/{seller.id}'
    intent=create_from_plan_line(db,seller_id=seller.id,plan_line_id=line.id,creator_id=user.id);db.commit()
    client.put(prefix+'/modules/collections',json={'enabled':False})
    db.rollback()
    with pytest.raises(ActionError,match='disabled'):approve(db,seller_id=seller.id,intent_id=intent.id,actor_id=user.id)
    db.rollback();plan=db.get(KoshPlan,line.plan_id);assert _plan_out(db,plan)['status']=='STALE'

def test_changed_cash_evidence_cannot_create_intent_from_old_proof(client,db):
    seller,user,invoice,line=planned_line(db);sign_in(client.app,SUBJECT);prefix=f'/api/kosh/sellers/{seller.id}'
    event=client.post(prefix+'/cash-events',json={'event_type':'SCHEDULED_PAYABLE','source_module':'procurement','evidence_ref':'po:new-fact','event_date':'2026-10-16','amount_paise':20000}).json();client.post(prefix+f"/cash-events/{event['id']}/confirm")
    db.rollback()
    with pytest.raises(ValueError,match='STALE_PLAN_INPUTS'):create_from_plan_line(db,seller_id=seller.id,plan_line_id=line.id,creator_id=user.id)
    assert _plan_out(db,db.get(KoshPlan,line.plan_id))['status']=='STALE'
