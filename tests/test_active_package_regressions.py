"""Defects reproduced from real active packages; entirely offline fixtures."""
import pytest
from tests.stage3a_rows import make_stage3a,BASE_PAGES
from tests.test_stage3b_fields import fields_of,val

@pytest.mark.parametrize('obligation',[
 'During the warranty period, Seller has to complete the required Service / Rectification within 5 days.',
 'During the warranty period, repairs must be completed within 7 days.',
 'During the warranty period, the response time is 2 days.',
])
def test_rectification_deadline_is_not_warranty_duration(db,obligation):
 pages={**BASE_PAGES,4:BASE_PAGES[4].replace('Warranty period of the supplied products shall be 5 years from the date of final acceptance.',obligation+' Warranty period:30 Months.')}
 r=fields_of(db,make_stage3a(db,pages=pages).id)
 assert r['warranty_period'].status=='RESOLVED'
 assert val(r,'warranty_period')=={'value':30.0,'unit':'MONTHS'}

def test_service_only_warranty_mention_leaves_duration_unknown(db):
 pages={**BASE_PAGES,4:BASE_PAGES[4].replace('Warranty period of the supplied products shall be 5 years from the date of final acceptance.','During the warranty period, rectification must be completed within 5 days.')}
 r=fields_of(db,make_stage3a(db,pages=pages).id)
 assert r['warranty_period'].status=='UNKNOWN'

def test_portal_fields_use_latest_package_field_identity(db):
 from sqlalchemy import select
 from app.api.portal import _fields
 from app.database.models import TenderFieldExtraction,TenderFieldValue
 from tests.matching_factories import make_tender
 t=make_tender(db,bid='GEM/2026/B/8999001',fields={'warranty_period':('TRUE',5)})
 old=db.scalar(select(TenderFieldExtraction).where(TenderFieldExtraction.tender_id==t.id))
 new=TenderFieldExtraction(stage3a_extraction_id=old.stage3a_extraction_id,document_version_id=old.document_version_id,document_id=old.document_id,tender_id=t.id,bid_number=t.bid_number,document_type='MAIN_BID',version_number=1,extractor_name='gem-fields',extractor_version='stage3b-v6',status='SUCCESS',is_current=True)
 db.add(new);db.flush();db.add(TenderFieldValue(field_extraction_id=new.id,tender_id=t.id,field_name='warranty_period',field_group='WARRANTY',value_type='DURATION',status='RESOLVED',value_number=30,unit='MONTHS'));db.commit()
 fields=_fields(db,t.id)
 assert len(fields)==1 and fields[0]['number']==30
