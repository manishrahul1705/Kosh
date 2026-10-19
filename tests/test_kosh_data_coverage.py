"""A fresh arbitrary dev identity sees populated business pages, with stable cash."""
from datetime import date
from decimal import Decimal
from fastapi.testclient import TestClient
from sqlalchemy import select
from app.main import create_app
from app.database.kosh_models import KoshCashEvent, KoshOperationRecord, KoshModuleFlag
from app.finance.modules import MODULES
from scripts.kosh_generate_demo import generate
from scripts.kosh_seed_demo import seed
from scripts.kosh_seed_full import seed_full
from scripts.kosh_data_coverage import check_pages


def test_every_business_page_is_populated_without_changed_cash(settings, session_factory, source, tmp_path):
    data=tmp_path/'inputs';storage=tmp_path/'private'
    generate(42,data,date(2026,10,13))
    result=seed(settings.resolved_database_url,data,storage)
    seller=result['seller_id']
    with session_factory() as db:
        seed_full(db,seller,settings.resolved_document_storage_path)
        count=len(list(db.scalars(select(KoshOperationRecord))))
        seed_full(db,seller,settings.resolved_document_storage_path)
        assert len(list(db.scalars(select(KoshOperationRecord))))==count
        assert all(row.status=='PROPOSED' for row in db.scalars(select(KoshCashEvent)))
        assert len(list(db.scalars(select(KoshModuleFlag))))==len(MODULES)
    app=create_app(settings.model_copy(update={'dev_login_enabled':True,'kosh_as_of_date':'2026-10-13'}),
                   session_factory=session_factory,collector_factory=source)
    with TestClient(app) as client:
        login=client.post('/api/dev/login',json={'email':'finance.judge@example.org'})
        assert login.status_code==200
        headers={'Authorization':'Bearer '+login.json()['access_token']}
        def get(path):
            response=client.get(path,headers=headers)
            assert response.status_code==200,(path,response.text)
            return response.json()
        check_pages(get,seller)
        base=f'/api/kosh/sellers/{seller}'
        ledger=get(base+'/ledger')['totals']
        assert ledger['open_payables_paise']==380397322
        assert ledger['held_for_review_payables_paise']==96000000
        forecast=get(base+'/forecast/latest')
        assert Decimal(str(forecast['weeks'][5]['prob_below_buffer']))==Decimal('.7995')
        plan=get(base+'/plans/latest')
        assert plan['total_cost_paise']==1540710 and plan['baseline_cost_paise']==8412814
        assert all(Decimal(str(p))<=Decimal('.20') for p in plan['after_probabilities'])
        intents=get(base+'/actions/intents')['items']
        assert {'T2','T3'} <= {i['tier'] for i in intents if i['status']=='PROPOSED'}
        assert {'SUCCEEDED','BLOCKED'} <= {i['status'] for i in intents}
        collections=get(base+'/collections')['items']
        assert any(item['interest']['monthly_rests']>0 and item['interest']['interest_paise']>0 for item in collections if item['interest']['status']=='COMPUTED')
        dashboard=get(base+'/operations/dashboard')
        assert any(item['shortage_units']>0 for item in dashboard['inventory'])
        assert any(item.get('recommended') is False for item in dashboard['quotes'])
        assert {'COMPLETED','APPROVAL_PAUSED'} <= {w['status'] for w in dashboard['workflows']}
        assert len(get(base+'/chat/history')['items'])==4
        assert len(get(f'/api/portal/sellers/{seller}/tenders')['items'])==10
        assert get(base+'/audit/verify')['valid']
        assert client.get(f'/api/kosh/sellers/{seller+999}/chat/history',headers=headers).status_code==403
