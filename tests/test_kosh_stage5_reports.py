"""Private one-page reports and consent/OTP-bound immutable sharing."""
from datetime import datetime,timedelta
from io import BytesIO
from decimal import Decimal
import pdfplumber
from sqlalchemy import select
from app.policy.controls import editable_control
from app.consent.sharing import grant,revoke
from app.actions.approvals import recheck,approve,ActionError
from app.actions.step_up import request,inbox,verify
from app.actions.execution import execute
from app.database.kosh_models import KoshOperationRecord,KoshActionIntent
from tests.test_kosh_stage4_intents import planned_line,SUBJECT
from tests.conftest import sign_in
import pytest

def test_private_report_one_page_and_t3_scoped_sharing(client,db,tmp_path):
    seller,user,_,_=planned_line(db);sign_in(client.app,SUBJECT);prefix=f'/api/kosh/sellers/{seller.id}'
    client.post(prefix+'/forecast/run',json={'seed':42,'n_paths':10,'include_forecast_sales':False})
    generated=client.post(prefix+'/reports');assert generated.status_code==200;report=generated.json();assert report['tier']=='T1'
    pdf=client.get(prefix+f"/reports/{report['id']}/pdf");assert pdf.status_code==200
    with pdfplumber.open(BytesIO(pdf.content)) as reader:
        assert len(reader.pages)==1; text=reader.pages[0].extract_text()
    assert 'KOSH' in text and 'Audit snapshot' in text and 'MUDRA_LOAN' in text
    (tmp_path/'report.pdf').write_bytes(pdf.content)
    db.rollback();control=editable_control(db,seller.id);control.allowlist=[*control.allowlist,{'key':'recipient:CGTMSE_BACKED_WC_LOAN','added_at':(datetime.utcnow()-timedelta(days=2)).isoformat()+'Z'}];db.commit()
    shared=client.post(prefix+f"/reports/{report['id']}/share",json={'recipient_id':'CGTMSE_BACKED_WC_LOAN'}).json()
    assert shared['tier']=='T3' and shared['status']=='BLOCKED' and 'CONSENT_SCOPE' in shared['policy_decision']['rule_ids']
    db.rollback();consent=grant(db,seller_id=seller.id,actor_id=user.id,purpose='SHARE_DATA_PACK',recipient_id='CGTMSE_BACKED_WC_LOAN',fields=['cash_report_pdf','forecast','plan','options','audit_hash'],expires_at=datetime.now(__import__('datetime').timezone.utc)+timedelta(days=3));db.commit()
    row=recheck(db,seller_id=seller.id,intent_id=shared['id'],actor_id=user.id);db.commit()
    request(db,seller_id=seller.id,intent_id=row.id,actor_id=user.id);db.commit();code=inbox(db,seller_id=seller.id,actor_id=user.id)[0]['payload']['code'];assert verify(db,seller_id=seller.id,intent_id=row.id,actor_id=user.id,code=code)
    _,token=approve(db,seller_id=seller.id,intent_id=row.id,actor_id=user.id,otp_verified=True);db.commit()
    revoke(db,seller_id=seller.id,consent_id=consent.id,actor_id=user.id);db.commit()
    with pytest.raises(ActionError,match='consent|Consent'):execute(db,seller_id=seller.id,intent_id=row.id,actor_id=user.id,token=token)
