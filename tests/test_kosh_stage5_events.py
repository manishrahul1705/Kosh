"""Cash proposals, owner confirmation, exact switch-off and route authorization."""
from datetime import date
import pytest

@pytest.fixture(autouse=True)
def configured_auth(monkeypatch):
    from app.api.auth import get_token_verifier
    monkeypatch.setenv("SUPABASE_URL","https://kosh-tests.supabase.co");get_token_verifier.cache_clear()
from sqlalchemy import select
from app.database.auth_models import SellerMembership
from app.database.kosh_models import KoshCashEvent
from app.finance.forecast import load_inputs,simulate
from tests.test_kosh_stage4_intents import planned_line,SUBJECT
from tests.conftest import sign_in

def test_cash_events_confirm_and_switch_off_exactly(client,db):
    seller,user,_,_=planned_line(db);sign_in(client.app,SUBJECT)
    prefix=f"/api/kosh/sellers/{seller.id}/cash-events"
    args=dict(as_of=date(2026,10,13),n_paths=10,seed=42,include_forecast_sales=False,buffer_paise=0)
    base=simulate(load_inputs(db,seller.id,args['as_of'],include_addon_events=False),**args)
    payload=dict(event_type="EXPECTED_RECEIVABLE",source_module="sales",evidence_ref="order:ABC-1",event_date="2026-10-16",amount_paise=12345)
    row=client.post(prefix,json=payload).json();assert row['status']=='PROPOSED'
    db.rollback();assert simulate(load_inputs(db,seller.id,args['as_of']),**args)==base
    assert client.post(prefix+f"/{row['id']}/confirm").status_code==200
    db.rollback();changed=simulate(load_inputs(db,seller.id,args['as_of']),**args)
    assert changed['weeks'][0]['expected_inflow_addon_paise']==12345
    assert changed['weeks'][0]['p50_closing_balance_paise']==base['weeks'][0]['p50_closing_balance_paise']+12345
    assert simulate(load_inputs(db,seller.id,args['as_of'],include_addon_events=False),**args)==base
    payload.update(event_type="SCHEDULED_PAYABLE",source_module="procurement",evidence_ref="po:1",amount_paise=345)
    payable=client.post(prefix,json=payload).json();client.post(prefix+f"/{payable['id']}/confirm")
    db.rollback();assert simulate(load_inputs(db,seller.id,args['as_of']),**args)['weeks'][0]['expected_outflow_addon_paise']==345
    payload.update(event_type="FINANCING_NEED",amount_paise=999)
    need=client.post(prefix,json=payload).json();client.post(prefix+f"/{need['id']}/confirm")
    db.rollback();assert simulate(load_inputs(db,seller.id,args['as_of']),**args)['weeks'][0]['expected_outflow_addon_paise']==345
    for bad in (1.5,True,-1):
        payload['amount_paise']=bad;assert client.post(prefix,json=payload).status_code==422

def test_event_routes_auth_cross_tenant_and_owner_only_confirmation(client,db):
    seller,user,_,_=planned_line(db)
    other,_,_,_=planned_line(db,name="Other events",subject="eeeeeeee-0000-0000-0000-000000000054")
    prefix=f"/api/kosh/sellers/{seller.id}/cash-events";payload=dict(event_type="COST_CHANGE",source_module="pricing",evidence_ref="purchase:1",event_date="2026-11-01",amount_paise=100)
    for method,path,body in [('get',prefix,None),('post',prefix,payload),('post',prefix+'/1/confirm',None)]:assert getattr(client,method)(path,**({'json':body} if body else {})).status_code==401
    sign_in(client.app,SUBJECT)
    cross=f"/api/kosh/sellers/{other.id}/cash-events"
    assert client.get(cross).status_code==403 and client.post(cross,json=payload).status_code==403 and client.post(cross+'/1/confirm').status_code==403
    row=client.post(prefix,json=payload).json()
    assert client.post(cross+f"/{row['id']}/confirm").status_code==403
    db.rollback();member=db.scalar(select(SellerMembership).where(SellerMembership.user_id==user.id,SellerMembership.seller_id==seller.id));member.role='VIEWER';db.commit()
    assert client.post(prefix,json=payload).status_code==403
    assert client.post(prefix+f"/{row['id']}/confirm").status_code==403
    assert client.get(prefix).status_code==200
