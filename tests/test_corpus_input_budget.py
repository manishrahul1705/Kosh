"""Bounded, source-balanced evidence selection; no provider/network calls."""
import json
from types import SimpleNamespace
import pytest
from sqlalchemy import select
from app.ai.chunker import Chunk
from app.corpus.input_selection import MaterialGroup, select_balanced, coverage_metrics, serialized_request_characters
from app.corpus.analysis import prepare_corpus, CORPUS_PROMPT_VERSION
from app.ai.service import AnalysisService
from app.ai.providers.mock import MockProvider
from app.ai.providers.base import AIResponse
from app.ai.grounding import ground
from app.ai.schema import parse_envelope


def groups(types, counts=None, lengths=None):
    result=[];sequence=0
    for i, dtype in enumerate(types):
        chunks=[]
        for j in range((counts or [8]*len(types))[i]):
            sequence+=1
            chunks.append(Chunk(f'D{i+1}-C{j+1}',sequence,'CLAUSE_TEXT','SECTION_TEXT',j+1,j+1,
                'The supplier shall provide warranty. '+('x'*(lengths or [100]*len(types))[i])))
        result.append(MaterialGroup(i+1,i+101,dtype,'pdf',i+1,chunks))
    return result


def cost(chunks):
    return 200+len(json.dumps([{'id':c.key,'page':c.page_number,'text':c.text} for c in chunks]))


def choose(gs,budget=1500,max_chunks=100,include_boilerplate=False):
    return select_balanced(gs,max_chunks=max_chunks,max_chars=budget,cost=cost,include_boilerplate=include_boilerplate)


@pytest.mark.parametrize('types,counts,lengths',[
    (['MAIN_BID','SPECIFICATION'],[20,2],[200,20]),
    (['MAIN_BID','ATC'],[20,2],[200,20]),
    (['MAIN_BID','BOQ','SPECIFICATION'],[20,2,3],[200,20,50]),
    (['MAIN_BID','ATC','BOQ','SPECIFICATION'],[6]*4,[60]*4),
    (['MAIN_BID','SPECIFICATION'],[20,1],[1000,1]),
    (['MAIN_BID'],[20],[100]),
])
def test_required_sources_are_represented(types,counts,lengths):
    gs=groups(types,counts,lengths);selected=choose(gs,budget=2400)
    assert all(any(c.sent for c in g.chunks) for g in gs)
    assert cost(selected.sent)<=2400
    assert [c.sequence for c in selected.sent]==sorted(c.sequence for c in selected.sent)
    assert all(c.text.startswith('The supplier') for c in selected.sent)


def test_later_atc_beats_early_incidental_content():
    gs=groups(['MAIN_BID','SPECIFICATION'],[10,1],[200,50])
    for c in gs[0].chunks:c.text='Introductory metadata. '+'x'*200
    late=gs[0].chunks[-1];late.kind='BUYER_ATC';late.text='The bidder must submit OEM authorization.'
    selected=choose(gs,650)
    assert late in selected.sent and gs[1].chunks[0] in selected.sent


def test_boilerplate_does_not_consume_reservations():
    gs=groups(['MAIN_BID','SPECIFICATION'],[12,1],[50,30])
    for c in gs[0].chunks[:-1]:c.kind='BOILERPLATE'
    selected=choose(gs,650);metrics=coverage_metrics(gs,selected)
    assert all(any(c.sent for c in g.chunks) for g in gs)
    assert metrics['coverage']=='FULL_AI_COVERAGE' and not metrics['budget_limited']
    assert metrics['documents'][0]['omission_reasons']=={'BOILERPLATE':11}


@pytest.mark.parametrize('budget,max_chunks',[(201,100),(1500,1),(0,100)])
def test_impossible_reservation_is_partial_not_complete(budget,max_chunks):
    gs=groups(['MAIN_BID','SPECIFICATION'],[2,2],[100,100]);selected=choose(gs,budget,max_chunks)
    metrics=coverage_metrics(gs,selected)
    assert metrics['coverage']=='PARTIAL_AI_COVERAGE' and metrics['documents_omitted']>0
    assert not selected.sent or cost(selected.sent)<=budget


def test_exact_budget_boundary_and_repeat_determinism():
    gs=groups(['MAIN_BID','SPECIFICATION'],[1,1],[20,20]);boundary=cost([g.chunks[0] for g in gs])
    first=choose(gs,boundary);m=coverage_metrics(gs,first)
    assert len(first.sent)==2 and cost(first.sent)==boundary
    second=choose(gs,boundary);assert coverage_metrics(gs,second)==m
    assert len(choose(gs,boundary-1).sent)==1


def test_changed_source_changes_selection_fingerprint():
    gs=groups(['MAIN_BID','SPECIFICATION'],[1,1],[20,20]);a=coverage_metrics(gs,choose(gs))
    gs[1].chunks[0].text+=' Updated mandatory clause.'
    b=coverage_metrics(gs,choose(gs));assert a['selection_fingerprint']!=b['selection_fingerprint']


def test_oversized_chunk_is_not_truncated_to_fit():
    gs=groups(['MAIN_BID','SPECIFICATION'],[1,1],[10000,20]);original=gs[0].chunks[0].text
    selected=choose(gs,700);metrics=coverage_metrics(gs,selected)
    assert not gs[0].chunks[0].sent and gs[1].chunks[0].sent
    assert gs[0].chunks[0].text==original and metrics['coverage']=='PARTIAL_AI_COVERAGE'


def test_missing_required_source_is_partial_even_if_usable_source_fits():
    gs=groups(['MAIN_BID','SPECIFICATION'],[1,0],[20,20]);metrics=coverage_metrics(gs,choose(gs))
    assert metrics['documents_omitted']==1 and metrics['coverage']=='PARTIAL_AI_COVERAGE'
    assert metrics['documents'][1]['representation_reason']=='NO_USABLE_CHUNKS'


def test_unsent_and_wrong_source_evidence_cannot_ground():
    gs=groups(['MAIN_BID','SPECIFICATION'],[1,1],[20,20]);selected=choose(gs,450,max_chunks=1)
    absent=next(c for g in gs for c in g.chunks if not c.sent)
    envelope=parse_envelope(json.dumps({'summary':'Tender terms.','requirements':[{
        'requirement_type':'WARRANTY','title':'Warranty','summary':'Warranty required.',
        'obligation':'Supplier shall provide warranty.','obligation_level':'MANDATORY',
        'applies_to':'BIDDER','evidence':[{'chunk_id':absent.key,'quote':absent.text}]}]}))
    output=ground(envelope,selected.sent)
    assert not output.requirements and output.rejected[0]['reason'].startswith('UNKNOWN_EVIDENCE_ID')


def test_mixed_logical_provenance_is_not_rewritten():
    gs=groups(['MAIN_BID','BOQ','SPECIFICATION'],[1]*3,[20]*3)
    gs[1].file_type='xlsx';cell=gs[1].chunks[0];cell.page_number=cell.page_end=0;cell.source_location={'sheet':'Items','cells':['B4']}
    gs[2].file_type='html';selected=choose(gs,1500)
    assert cell in selected.sent and cell.source_location=={'sheet':'Items','cells':['B4']}
    assert cell.page_number==0 and cell.key=='D2-C1'


def test_serialized_envelope_accounts_for_escaped_text():
    prompt=SimpleNamespace(system='Instructions "quoted"\n',user='{"text":"\\n"}')
    cfg=SimpleNamespace(ai_temperature=0,ai_max_output_tokens=8192)
    assert serialized_request_characters(prompt,cfg)>len(prompt.system)+len(prompt.user)+150


def test_actual_prompt_limit_persistence_and_version_staleness(db,settings,tmp_path,session_factory):
    from tests.test_corpus import seed,extract_all
    from tests.pdf_factory import PdfBuilder
    from app.documents.references import ReferenceDiscovery
    from app.documents.documents_service import DocumentsService
    from app.database.models import AIAnalysisRun
    from app.api.portal import _analysis
    from app.api.ai_analysis import get_analysis
    from app.corpus.queue import enqueue_corpus
    b=PdfBuilder()
    for i in range(12):
        page=b.page();page.text(40,40,'Bid Number: GEM/2026/B/8124821')
        page.text(40,70,f'Warranty: Supplier shall provide warranty for {i+1} months.')
        page.text(40,100,'Mandatory documents: Supplier must submit certificates. '+('Required evidence. '*30))
    cfg,t,v=seed(db,tmp_path,settings,b.build())
    ReferenceDiscovery(DocumentsService(cfg)).run(db,t,acquire=False)
    extract_all(db,cfg,session_factory,t.id)
    full=prepare_corpus(AnalysisService(cfg,session_factory,provider_factory=MockProvider),t.id)
    limit=serialized_request_characters(full.prompt,cfg)-1
    cfg=cfg.model_copy(update={'ai_max_input_characters':limit})
    service=AnalysisService(cfg,session_factory,provider_factory=MockProvider)
    p=prepare_corpus(service,t.id)
    assert p.prompt and serialized_request_characters(p.prompt,cfg)<=limit
    assert p.input_coverage['coverage']=='PARTIAL_AI_COVERAGE'
    # Existing mock provider/test setup, no external request.
    call=service.call(p);it=service.interpret(p,call.response)
    assert it.status=='PARTIAL_SUCCESS'
    db.rollback()
    with session_factory() as s:
        rid=service.persist(s,p,call,it);s.commit()
    db.expire_all();run=db.get(AIAnalysisRun,rid)
    assert json.loads(run.corpus_snapshot_json)['ai_input_coverage']==p.input_coverage
    assert _analysis(db,t.id,{})['analysis_status']=='PARTIAL_SUCCESS'
    run.prompt_version='corpus-prompt-v6';db.commit()
    assert _analysis(db,t.id,{})['analysis_status']=='STALE'
    assert not get_analysis(rid,db)['current_for_corpus']
    queued=enqueue_corpus(db,t.id,cfg);assert queued.created and queued.job.prompt_version==CORPUS_PROMPT_VERSION
    from tests.matching_factories import make_seller
    from app.eligibility.service import EligibilityService
    seller=make_seller(db,name='Budget regression seller',terms='Warranty',turnover=1000000)
    old=EligibilityService(db).evaluate_tender(t.id,seller.id)
    assert old.ai_analysis_run_id is None
    run.prompt_version=CORPUS_PROMPT_VERSION;db.commit()
    current=EligibilityService(db).evaluate_tender(t.id,seller.id)
    assert current.ai_analysis_run_id==rid and current.id!=old.id
