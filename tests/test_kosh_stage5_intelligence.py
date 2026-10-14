"""Evidence-backed delay enrichment and reproducible cash scenarios."""
from datetime import date
from app.finance.forecast import load_inputs,simulate
from tests.test_kosh_stage4_intents import planned_line,SUBJECT
from tests.conftest import sign_in

def test_history_owner_confirmation_and_exact_off(client,db):
    seller,user,invoice,_=planned_line(db);sign_in(client.app,SUBJECT);prefix=f'/api/kosh/sellers/{seller.id}/intelligence'
    args=dict(as_of=date(2026,10,13),n_paths=30,seed=42,include_forecast_sales=False,buffer_paise=0)
    base=simulate(load_inputs(db,seller.id,args['as_of']),**args)
    history=client.post(prefix+'/history',json={'counterparty_id':invoice.counterparty_id,'observed_date':'2026-10-01','delay_days':[0,1,2,3,4],'evidence_ref':'customer-history:receipts'}).json()
    db.rollback();assert simulate(load_inputs(db,seller.id,args['as_of'],include_customer_history=True),**args)==base
    assert client.post(prefix+f"/history/{history['id']}/confirm").status_code==200
    db.rollback();changed=simulate(load_inputs(db,seller.id,args['as_of'],include_customer_history=True),**args)
    assert changed!=base and simulate(load_inputs(db,seller.id,args['as_of'],include_customer_history=False),**args)==base
    listing=client.get(prefix).json();assert listing['items'][0]['credit_signal']=='REVIEW_REQUIRED'

def test_customer_and_steel_scenarios_same_seed_and_owned_exposure(client,db):
    seller,user,invoice,_=planned_line(db);sign_in(client.app,SUBJECT);prefix=f'/api/kosh/sellers/{seller.id}'
    client.post(prefix+'/forecast/run',json={'seed':42,'n_paths':30,'include_forecast_sales':False})
    payload={'counterparty_id':invoice.counterparty_id,'delay_shift_days':15}
    first=client.post(prefix+'/intelligence/whatif',json=payload).json();second=client.post(prefix+'/intelligence/whatif',json=payload).json()
    assert first==second and first['seed']==42 and first['scenario_only'] is True
    po=client.post(prefix+'/operations/orders',json={'direction':'PO','counterparty_id':invoice.counterparty_id,'amount_paise':10000,'payment_date':'2026-10-16','material_code':'STEEL','evidence_ref':'po:steel'}).json();client.post(prefix+f"/operations/orders/{po['id']}/confirm")
    base=client.post(prefix+'/intelligence/whatif',json={}).json()
    steel=client.post(prefix+'/intelligence/whatif',json={'purchase_order_id':po['id'],'price_change_percent':'8'}).json()
    assert steel['weeks'][0]['p50_closing_balance_paise']==base['weeks'][0]['p50_closing_balance_paise']-800
    assert client.post(prefix+'/intelligence/whatif',json={'price_change_percent':'8'}).status_code==422
    assert client.post(prefix+'/intelligence/whatif',json={'counterparty_id':99999,'delay_shift_days':15}).status_code==404
