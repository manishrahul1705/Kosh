"""Native orders, price deltas and sandbox-only RFQs."""
from datetime import date
from sqlalchemy import select,func
from app.finance.forecast import load_inputs,simulate
from app.database.kosh_models import KoshCashEvent,KoshSandboxOutbox
from app.actions.approvals import approve
from app.actions.execution import execute
from tests.test_kosh_stage4_intents import planned_line,SUBJECT
from tests.conftest import sign_in

def test_order_and_po_cash_direction_owner_confirmation_and_price_changes(client,db):
    seller,user,invoice,_=planned_line(db);sign_in(client.app,SUBJECT);prefix=f'/api/kosh/sellers/{seller.id}/operations'
    args=dict(as_of=date(2026,10,13),n_paths=10,seed=42,include_forecast_sales=False,buffer_paise=0)
    base=simulate(load_inputs(db,seller.id,args['as_of'],include_addon_events=False),**args)
    payload=dict(direction='SALE',counterparty_id=invoice.counterparty_id,amount_paise=100000,payment_date='2026-10-16',material_code='STEEL',evidence_ref='sales:ABC-01')
    sale=client.post(prefix+'/orders',json=payload);assert sale.status_code==200;sale=sale.json()
    db.rollback();assert simulate(load_inputs(db,seller.id,args['as_of']),**args)==base
    assert client.post(prefix+f"/orders/{sale['id']}/confirm").status_code==200
    db.rollback();higher=simulate(load_inputs(db,seller.id,args['as_of']),**args);assert higher['weeks'][0]['p50_closing_balance_paise']==base['weeks'][0]['p50_closing_balance_paise']+100000
    payload.update(direction='PO',amount_paise=20000,evidence_ref='po:STEEL-01')
    po=client.post(prefix+'/orders',json=payload).json()
    assert client.post(prefix+'/pricing',json={'purchase_order_id':po['id'],'change_percent':'8','evidence_ref':'sample:steel-8'}).status_code==409
    client.post(prefix+f"/orders/{po['id']}/confirm")
    price=client.post(prefix+'/pricing',json={'purchase_order_id':po['id'],'change_percent':'8','evidence_ref':'sample:steel-8'}).json();assert price['data']['delta_paise']==1600
    client.post(prefix+f"/orders/{price['id']}/confirm")
    db.rollback();result=simulate(load_inputs(db,seller.id,args['as_of']),**args);assert result['weeks'][0]['expected_outflow_addon_paise']==21600
    decrease=client.post(prefix+'/pricing',json={'purchase_order_id':po['id'],'change_percent':'-3','evidence_ref':'sample:steel-decrease'}).json();client.post(prefix+f"/orders/{decrease['id']}/confirm")
    db.rollback();latest=simulate(load_inputs(db,seller.id,args['as_of']),**args);assert latest['weeks'][0]['expected_inflow_addon_paise']==100600 and latest['weeks'][0]['expected_outflow_addon_paise']==20000
    assert simulate(load_inputs(db,seller.id,args['as_of'],include_addon_events=False),**args)==base

def test_rfq_outbox_only_after_approval(client,db):
    seller,user,invoice,_=planned_line(db);sign_in(client.app,SUBJECT);prefix=f'/api/kosh/sellers/{seller.id}/operations'
    draft=client.post(prefix+'/rfqs',json={'counterparty_id':invoice.counterparty_id,'material_code':'STEEL','quantity':20,'needed_date':'2026-11-01','evidence_ref':'rfq:20'}).json()
    assert draft['tier']=='T1' and draft['external_delivery'] is False
    response=client.post(prefix+f"/drafts/{draft['id']}/intent");assert response.status_code==200;intent=response.json()
    db.rollback();assert db.scalar(select(func.count()).select_from(KoshSandboxOutbox))==0
    _,token=approve(db,seller_id=seller.id,intent_id=intent['id'],actor_id=user.id);db.commit()
    execute(db,seller_id=seller.id,intent_id=intent['id'],actor_id=user.id,token=token);db.commit()
    assert db.scalar(select(KoshSandboxOutbox)).body==draft['body']
