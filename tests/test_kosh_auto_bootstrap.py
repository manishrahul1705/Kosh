"""Fresh development startup, restart preservation and production exclusion."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from fastapi.testclient import TestClient
from sqlalchemy import select, func
from app.core.config import Settings
from app.core.bootstrap import bootstrap_workspace
from app.database.session import build_engine, build_session_factory, run_migrations
from app.database.models import Seller
from app.database.kosh_models import KoshOperationRecord
from app.main import create_app
from scripts.kosh_data_coverage import check_pages


def test_empty_start_signin_all_pages_and_restart_preserves_data(tmp_path, capsys):
    path=tmp_path/'kosh_work.db'
    assert not path.exists()
    settings=Settings(_env_file=None,database_url=f"sqlite:///{path.as_posix()}",
                      document_storage_path=str(tmp_path/'tenders'),dev_login_enabled=True,
                      scheduler_enabled=False,auto_migrate=False,collect_on_startup=False,
                      startup_recovery_enabled=False,kosh_as_of_date='2026-10-13')
    with TestClient(create_app(settings)) as client:
        response=client.post('/api/dev/login',json={'email':'startup.reviewer@example.org'})
        assert response.status_code==200
        headers={'Authorization':'Bearer '+response.json()['access_token']}
        def get(route):
            response=client.get(route,headers=headers)
            assert response.status_code==200,(route,response.text)
            return response.json()
        seller=next(s['id'] for s in get('/api/sellers') if s['name']=='Meenakshi Precision Components')
        check_pages(get,seller)
        base=f'/api/kosh/sellers/{seller}'
        assert get(base+'/forecast/latest')['weeks'][5]['prob_below_buffer']==.7995
        plan=get(base+'/plans/latest')
        assert (plan['total_cost_paise'],plan['baseline_cost_paise'])==(1540710,8412814)
        assert all(prob<=.20 for prob in plan['after_probabilities'])
        totals=get(base+'/ledger')['totals']
        assert (totals['open_payables_paise'],totals['held_for_review_payables_paise'])==(380397322,96000000)
    engine=build_engine(settings.resolved_database_url)
    with build_session_factory(engine)() as db:
        before=db.scalar(select(func.count()).select_from(KoshOperationRecord))
    with TestClient(create_app(settings)) as restarted:
        assert restarted.get('/health').status_code==200
    with build_session_factory(engine)() as db:
        assert db.scalar(select(func.count()).select_from(KoshOperationRecord))==before
    engine.dispose()
    assert capsys.readouterr().out.count('Kosh workspace ready: Meenakshi Precision Components')==1


def test_production_never_bootstraps_even_when_explicitly_enabled(tmp_path):
    path=tmp_path/'production.db'
    settings=Settings(_env_file=None,app_env='production',database_url=f'sqlite:///{path.as_posix()}',
                      dev_login_enabled=False,auto_migrate=False,kosh_approval_secret='p'*32,
                      kosh_auto_bootstrap=True)
    assert bootstrap_workspace(settings) is False
    assert not path.exists()


def test_development_defaults_need_no_dotenv(monkeypatch):
    for key in ('APP_ENV','DATABASE_URL','DEV_LOGIN_ENABLED','KOSH_AUTO_BOOTSTRAP'):
        monkeypatch.delenv(key,raising=False)
    settings=Settings(_env_file=None)
    assert settings.database_url=='sqlite:///./kosh_work.db'
    assert settings.dev_login_enabled and settings.kosh_auto_bootstrap


def test_two_empty_database_starts_only_seed_once(tmp_path,monkeypatch):
    import scripts.kosh_setup
    path=tmp_path/'concurrent.db'
    path.touch()  # Covers an existing zero-byte database as well as two starters.
    settings=Settings(_env_file=None,database_url=f'sqlite:///{path.as_posix()}')
    calls=[]
    def minimal_seed(url,**kwargs):
        calls.append(url)
        run_migrations(url)
        engine=build_engine(url)
        try:
            with build_session_factory(engine)() as db:
                db.add(Seller(name='Meenakshi Precision Components'));db.commit()
        finally:engine.dispose()
    monkeypatch.setattr(scripts.kosh_setup,'setup',minimal_seed)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda _:bootstrap_workspace(settings),range(2)))
    assert sorted(results)==[False,True] and len(calls)==1
