"""Every registered native module route enforces identity and seller boundaries."""
import re,importlib,importlib.util
from sqlalchemy import select
from app.database.auth_models import SellerMembership
from tests.test_kosh_stage4_intents import planned_line,SUBJECT
from tests.conftest import sign_in

MODULES={"app.api.cash_events","app.api.collections","app.api.native_operations","app.api.intelligence","app.api.revenue","app.api.kosh_chat","app.api.cash_reports","app.api.tender_cash","app.api.modules"}
def routes(app,seller_id):
    paths=app.openapi()['paths']
    for module in sorted(MODULES):
        if importlib.util.find_spec(module) is None:continue
        for route in importlib.import_module(module).router.routes:
            assert route.path in paths,route.path
            path=route.path.replace('{seller_id}',str(seller_id));path=re.sub(r'\{[^}]+\}','1',path)
            for method in sorted(route.methods-{'HEAD','OPTIONS'}):yield method,path

def test_every_native_route_rejects_unauthenticated_and_wrong_seller(client,db,monkeypatch):
    from app.api.auth import get_token_verifier
    monkeypatch.setenv('SUPABASE_URL','https://kosh-tests.supabase.co');get_token_verifier.cache_clear()
    seller,user,_,_=planned_line(db)
    other,_,_,_=planned_line(db,name='Other native modules',subject='eeeeeeee-0000-0000-0000-000000000055')
    entries=list(routes(client.app,seller.id));assert entries
    for method,path in entries:
        response=client.request(method,path,**({'json':{}} if method!='GET' else {}))
        assert response.status_code==401,(method,path,response.text)
    sign_in(client.app,SUBJECT)
    for method,path in routes(client.app,other.id):
        response=client.request(method,path,**({'json':{}} if method!='GET' else {}))
        assert response.status_code==403,(method,path,response.text)
    db.rollback();member=db.scalar(select(SellerMembership).where(SellerMembership.user_id==user.id,SellerMembership.seller_id==seller.id));member.role='VIEWER';db.commit()
    for method,path in entries:
        if method=='GET':continue
        response=client.request(method,path,json={});assert response.status_code==403,(method,path,response.text)
