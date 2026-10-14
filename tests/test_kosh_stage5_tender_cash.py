"""Matched tender capital dates, missing facts and same-seed scenario."""
from sqlalchemy import select
from app.database.models import SellerRevision
from app.database.matching_models import SellerTenderMatch
from tests.test_kosh_stage4_intents import planned_line,SUBJECT
from tests.matching_factories import make_tender
from tests.conftest import sign_in

def test_tender_scenario_requires_evidence_and_preserves_review_financing(client,db):
    seller,user,_,_=planned_line(db);tender=make_tender(db,bid='GEM/T8/CASH')
    revision=db.scalar(select(SellerRevision).where(SellerRevision.seller_id==seller.id,SellerRevision.is_active.is_(True)))
    match=SellerTenderMatch(seller_id=seller.id,tender_id=tender.id,seller_revision_id=revision.id,relevance_status='RELEVANT',eligibility_status='ELIGIBLE',match_status='MATCHED',tender_state_fingerprint='test',matcher_version='test');db.add(match);db.commit();sign_in(client.app,SUBJECT)
    prefix=f'/api/kosh/sellers/{seller.id}/tender-to-cash/{tender.id}'
    missing=client.post(prefix,json={'evidence_ref':'owner:scenario'}).json();assert missing['status']=='REVIEW_REQUIRED' and 'production_cost_paise' in missing['missing']
    client.post(f'/api/kosh/sellers/{seller.id}/forecast/run',json={'seed':42,'n_paths':10,'include_forecast_sales':False})
    payload={'emd_paise':10000,'emd_date':'2026-10-16','performance_security_cash_paise':20000,'security_date':'2026-10-20','production_cost_paise':50000,'production_date':'2026-10-21','contract_receivable_paise':120000,'government_payment_date':'2026-12-01','emd_refund_paise':10000,'emd_refund_date':'2026-12-02','cpse_buyer':True,'evidence_ref':'owner:documented-scenario'}
    result=client.post(prefix,json=payload).json();assert result['working_capital_needed_paise']==80000 and result['seed']==42
    assert result['base_weeks']!=result['scenario_weeks']
    assert all(p['status']=='REVIEW_REQUIRED' for p in result['financing_suggestions'])
    assert 'CPSE buyer' in result['financing_suggestions'][1]['reason']
    db.rollback();match=db.get(SellerTenderMatch,match.id);match.match_status='REVIEW_REQUIRED';db.commit()
    assert client.post(prefix,json=payload).status_code==409
