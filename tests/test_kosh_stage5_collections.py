"""MSMED monthly rests, unknown facts and native T2 message gate."""
from datetime import date,timedelta
from decimal import Decimal,ROUND_HALF_UP
from sqlalchemy import select,func
from app.finance.collections import msmed_interest
from app.database.kosh_models import KoshSandboxOutbox
from app.actions.approvals import approve
from app.actions.execution import execute
from app.actions.addons import create_from_draft
from tests.test_kosh_stage4_intents import planned_line,SUBJECT
from tests.conftest import sign_in
import pytest
@pytest.mark.parametrize("agreement,days,period",[("NONE",None,15),("AGREED",0,0),("AGREED",44,44),("AGREED",45,45),("AGREED",46,45)])
def test_payment_period_and_due_boundary(agreement,days,period):
    accepted=date(2026,1,1);due=accepted+timedelta(days=period)
    result=msmed_interest(100000,accepted,due,agreement_status=agreement,agreed_days=days,supplier_mse=True,bank_rate="5.75")
    assert result['annual_rate']=='0.1725' and result['payment_period_days']==period and result['interest_paise']==0
    assert msmed_interest(100000,accepted,due+timedelta(days=1),agreement_status=agreement,agreed_days=days,supplier_mse=True)['interest_paise']>0

def test_monthly_rests_and_unknown_evidence():
    result=msmed_interest(10000000,date(2026,1,1),date(2026,3,16),agreement_status="NONE",supplier_mse=True)
    expected=int((Decimal(10000000)*((1+Decimal('.1725')/12)**2-1)).quantize(Decimal(1),rounding=ROUND_HALF_UP))
    assert result['monthly_rests']==2 and result['stub_days']==0 and result['interest_paise']==expected
    assert msmed_interest(100,None,date(2026,10,13))['status']=='REVIEW_REQUIRED'
    assert msmed_interest(100,date(2026,1,1),date(2026,10,13),agreement_status='NONE',supplier_mse=False)['status']=='NOT_APPLICABLE'

def test_native_reminder_needs_t2_approval_before_outbox(client,db):
    seller,user,invoice,line=planned_line(db);sign_in(client.app,SUBJECT)
    prefix=f'/api/kosh/sellers/{seller.id}/collections'
    response=client.post(prefix+'/drafts',json={'invoice_id':invoice.id,'tone':'GENTLE'})
    assert response.status_code==200;draft=response.json();assert draft['tier']=='T1' and 'INR 1,000.00' in draft['body']
    intent_response=client.post(prefix+f"/drafts/{draft['id']}/intent");assert intent_response.status_code==200
    assert db.scalar(select(func.count()).select_from(KoshSandboxOutbox))==0
    db.rollback();row=create_from_draft(db,seller_id=seller.id,draft_id=draft['id'],creator_id=user.id);db.commit()
    assert row.tier=='T2' and row.plan_line_id is None
    from app.actions.approvals import ActionError
    with pytest.raises(ActionError):
        execute(db,seller_id=seller.id,intent_id=row.id,actor_id=user.id,token="unapproved.token")
    assert db.scalar(select(func.count()).select_from(KoshSandboxOutbox))==0
    _,token=approve(db,seller_id=seller.id,intent_id=row.id,actor_id=user.id);db.commit()
    executed=execute(db,seller_id=seller.id,intent_id=row.id,actor_id=user.id,token=token);db.commit()
    assert executed.status=='SETTLED' and executed.result['before_probabilities']==executed.result['after_probabilities']
    out=db.scalar(select(KoshSandboxOutbox));assert out.body==draft['body'] and out.status=='SUBMITTED'


def test_month_end_rest_keeps_original_anniversary():
    result=msmed_interest(100000,date(2026,1,16),date(2026,3,30),agreement_status="NONE",supplier_mse=True)
    assert result['due_date']=='2026-01-31' and result['monthly_rests']==1 and result['stub_days']==30
