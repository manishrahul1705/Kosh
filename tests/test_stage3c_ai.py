"""Stage 3C: AI-assisted tender requirement interpretation.

Everything here runs OFFLINE: the deterministic MockProvider (scripted or keyword
mode) or the real HTTP provider classes against httpx.MockTransport. A guard
fixture makes any real socket connection fail the test.
"""

from __future__ import annotations

import ast
import hashlib
import json
import logging
import socket
import sys
from datetime import timedelta
from pathlib import Path

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import func, select, text

from app.ai import job_queue as aq
from app.ai.chunker import build_chunks, clean_line, select_chunks
from app.ai.constants import (
    CATEGORY_BY_TYPE,
    PROMPT_VERSION,
    REQUIREMENT_TYPES,
    SCHEMA_VERSION,
    AIJobReason,
)
from app.ai.grounding import quote_in_chunk
from app.ai.job_queue import backfill_ai_jobs, enqueue_ai_analysis
from app.ai.job_worker import SKIP_BLOCKED, SKIP_DAILY_LIMIT, SKIP_NOT_CONFIGURED, AIAnalysisJobWorker
from app.ai.providers import build_provider, provider_configured
from app.ai.providers.base import (
    AIProvider,
    AIRequest,
    NotConfigured,
    ProviderAuthError,
    ProviderConfigError,
    ProviderRateLimited,
    ProviderResponseError,
    ProviderTimeout,
    ProviderUnavailable,
)
from app.ai.providers.gemini import GeminiProvider
from app.ai.providers.mock import MockProvider
from app.ai.providers.openai_compatible import OpenAICompatibleProvider
from app.ai.schema import ResponseInvalid, map_requirement_type, parse_envelope
from app.ai.service import ALREADY, ANALYZED, NOT_READY, PROVIDER_FAILED, RESPONSE_INVALID, AnalysisService
from app.core.config import PROJECT_ROOT, Settings
from app.database.models import (
    AIAnalysisFlag,
    AIAnalysisJob,
    AIAnalysisRun,
    AIEvidenceChunk,
    AIRequirement,
    AIRequirementEvidence,
    TenderFieldExtraction,
    TenderFieldValue,
)
from app.fields.evidence import load_source
from app.fields.service import FieldExtractionService
from app.services.integrity import stage3a_digest, stage3b_digest
from app.utils.dates import utcnow
from tests.stage3a_rows import make_stage3a

SECRET = "AIzaSyTESTSECRETKEY0123456789abcdef"


# ---------------------------------------------------------------------------
class Clock:
    def __init__(self):
        self.now = utcnow()

    def __call__(self):
        return self.now

    def advance(self, **kw):
        self.now += timedelta(**kw)




@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def asettings(settings: Settings, tmp_path: Path) -> Settings:
    return settings.model_copy(update={
        "document_storage_path": str(tmp_path / "tenders"), "ai_provider": "mock", "ai_model": "",
        "ai_analysis_scope": "DOCUMENT", "ai_analysis_auto_queue": False, "ai_max_retries": 1, "ai_retry_base_delay_seconds": 0.0,
        "ai_analysis_max_attempts": 3, "ai_analysis_retry_backoff_minutes": 10.0})


def fresh(db):
    db.commit()
    db.expire_all()


def stage3b_run(db, settings, session_factory, **kw) -> int:
    e = make_stage3a(db, **kw)
    out = FieldExtractionService(settings, session_factory).extract(e.id)
    assert out.field_extraction_id
    return out.field_extraction_id


def service(asettings, session_factory, clock, provider=None, sleeps=None) -> AnalysisService:
    return AnalysisService(asettings, session_factory, provider_factory=(lambda: provider) if provider else None,
                           clock=clock, sleep=(sleeps.append if sleeps is not None else (lambda s: None)))


def chunk_key(svc: AnalysisService, s3b: int, needle: str) -> str:
    p = svc.prepare(s3b, force=True)
    for c in p.chunks.sent:
        if needle in c.text:
            return c.key
    raise AssertionError(f"no sent chunk contains {needle!r}")


def req(rtype, level, chunk_id, quote, **kw) -> dict:
    d = {"requirement_type": rtype, "title": kw.pop("title", f"{rtype} requirement"), "summary": "s",
         "obligation": "o", "obligation_level": level, "evidence": [{"chunk_id": chunk_id, "quote": quote}]}
    d.update(kw)
    return d


def envelope(*reqs, summary="Supply of paintball gun sets with ATC obligations.", ambiguities=()) -> dict:
    return {"summary": summary, "requirements": list(reqs), "ambiguities": list(ambiguities)}


WARRANTY_Q = "Warranty period of the supplied products shall be 5 years"
ISO_Q = "must have ISO 9001 certification"


def analyze_with(asettings, session_factory, clock, db, responses, s3b=None, **kw):
    s3b = s3b or stage3b_run(db, asettings, session_factory)
    mock = MockProvider(responses=responses)
    svc = service(asettings, session_factory, clock, mock, **kw)
    return svc, mock, s3b, svc.analyze(s3b)


def reqs_of(db, run_id) -> list[AIRequirement]:
    fresh(db)
    return list(db.scalars(select(AIRequirement).where(AIRequirement.analysis_run_id == run_id)
                           .order_by(AIRequirement.sequence)))


def flags_of(db, run_id) -> list[AIAnalysisFlag]:
    fresh(db)
    return list(db.scalars(select(AIAnalysisFlag).where(AIAnalysisFlag.analysis_run_id == run_id)))


# ===========================================================================
# 3-5. provider abstraction, mock provider, no network
# ===========================================================================
def test_provider_factory_and_abstraction(asettings):
    assert isinstance(build_provider(asettings), MockProvider)
    g = build_provider(asettings.model_copy(update={"ai_provider": "gemini", "ai_model": "models/gemini-x",
                                                    "ai_api_key": SecretStr(SECRET)}))
    assert isinstance(g, GeminiProvider) and g.model == "gemini-x" and isinstance(g, AIProvider)
    o = build_provider(asettings.model_copy(update={"ai_provider": "openai_compatible", "ai_model": "m",
                                                    "ai_api_key": "sk-abcdefghijklmnop"}))
    assert isinstance(o, OpenAICompatibleProvider)
    local = build_provider(asettings.model_copy(update={"ai_provider": "openai_compatible", "ai_model": "llama",
                                                        "ai_base_url": "http://localhost:11434/v1"}))
    assert isinstance(local, OpenAICompatibleProvider)          # keyless local server allowed
    for bad in ({"ai_provider": ""}, {"ai_provider": "gemini", "ai_model": "x"},
                {"ai_provider": "gemini", "ai_api_key": SecretStr(SECRET)}, {"ai_provider": "skynet"}):
        with pytest.raises(ProviderConfigError):
            build_provider(asettings.model_copy(update={"ai_model": "", **bad}))
    assert provider_configured(asettings) and not provider_configured(asettings.model_copy(update={"ai_provider": ""}))
    # the analysis pipeline depends on the abstraction only, never on a vendor module
    for mod in ("service.py", "job_worker.py", "grounding.py", "flags.py", "chunker.py", "prompt.py"):
        tree = ast.parse((PROJECT_ROOT / "app" / "ai" / mod).read_text(encoding="utf-8"))
        names = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
        assert not {"app.ai.providers.gemini", "app.ai.providers.openai_compatible", "app.ai.providers.mock"} & names
    # no vendor SDK dependency
    reqs = (PROJECT_ROOT / "requirements.txt").read_text().lower()
    assert not any(sdk in reqs for sdk in ("openai", "google-generativeai", "google-genai", "anthropic", "groq"))


def test_mock_provider_keyword_mode_and_script(asettings, session_factory, clock, db):
    s3b = stage3b_run(db, asettings, session_factory)
    out = service(asettings, session_factory, clock).analyze(s3b)        # keyword mode via factory (AI_PROVIDER=mock)
    assert out.outcome == ANALYZED and out.requirements >= 2
    fresh(db)
    run = db.get(AIAnalysisRun, out.analysis_run_id)
    assert (run.provider, run.model) == ("mock", "mock-deterministic-v1")
    types = {q.requirement_type for q in reqs_of(db, run.id)}
    assert {"WARRANTY", "ISO"} <= types
    m = MockProvider(responses=['{"summary": "x", "requirements": [], "ambiguities": []}', RuntimeError("boom")])
    r = AIRequest(system="s", user="u", max_output_tokens=10)
    assert json.loads(m.generate(r).text)["summary"] == "x"
    with pytest.raises(RuntimeError):
        m.generate(r)
    assert len(m.requests) == 2


# ===========================================================================
# 6-8, 20, 24. schema, malformed JSON, taxonomy
# ===========================================================================
def test_strict_envelope_and_malformed_json():
    assert parse_envelope('```json\n{"summary": "ok", "requirements": []}\n```').summary == "ok"
    for bad, code in (("not json", "MALFORMED_JSON"), ('{"summary": "x"', "MALFORMED_JSON"),
                      ("[1, 2]", "SCHEMA_VALIDATION_FAILED"), ('{"requirements": []}', "SCHEMA_VALIDATION_FAILED"),
                      ('{"summary": "x", "verdict": "PASS"}', "SCHEMA_VALIDATION_FAILED"), ("  ", "EMPTY_RESPONSE")):
        with pytest.raises(ResponseInvalid) as exc:
            parse_envelope(bad)
        assert exc.value.code == code, bad


def test_item_validation_taxonomy_and_unknown_type(asettings, session_factory, clock, db):
    s3b = stage3b_run(db, asettings, session_factory)
    svc0 = service(asettings, session_factory, clock)
    w, iso = chunk_key(svc0, s3b, WARRANTY_Q), chunk_key(svc0, s3b, ISO_Q)
    resp = envelope(
        req("Warranty", "mandatory", w, WARRANTY_Q, value=5, unit="YEARS"),          # case-insensitive mapping
        req("ISO_CERTIFICATION", "MANDATORY", iso, ISO_Q),                          # synonym -> ISO
        req("QUANTUM_ENTANGLEMENT", "MANDATORY", iso, ISO_Q),                       # unknown -> OTHER (8)
        {**req("ISO", "MANDATORY", iso, ISO_Q), "eligible": True},                  # extra field -> rejected (6)
        {k: v for k, v in req("ISO", "MANDATORY", iso, ISO_Q).items() if k != "evidence"},  # no evidence (20)
        {**req("ISO", "MANDATORY", iso, ISO_Q), "evidence": []},                    # empty evidence (20)
    )
    _, _, _, out = analyze_with(asettings, session_factory, clock, db, [resp], s3b=s3b)
    assert out.outcome == ANALYZED and out.status == "PARTIAL_SUCCESS" and out.error_code == "EVIDENCE_REJECTED"
    rows = reqs_of(db, out.analysis_run_id)
    assert [(q.requirement_type, q.model_requirement_type) for q in rows] == [
        ("WARRANTY", None), ("ISO", "ISO_CERTIFICATION"), ("OTHER", "QUANTUM_ENTANGLEMENT")]
    run = db.get(AIAnalysisRun, out.analysis_run_id)
    rejected = json.loads(run.rejected_json)
    assert [r["reason"] for r in rejected] == ["SCHEMA_INVALID"] * 3 and run.rejected_count == 3
    assert sum(f.flag_type == "EVIDENCE_REJECTED" for f in flags_of(db, run.id)) == 3
    # 24. taxonomy: required types present, every type has a category, unknown maps to OTHER
    required = {"EXPERIENCE", "TURNOVER", "PAST_PERFORMANCE", "OEM_AUTHORIZATION", "MANUFACTURER_AUTHORIZATION",
                "CERTIFICATE", "ISO", "TECHNICAL_SPECIFICATION", "WARRANTY", "DELIVERY", "INSTALLATION",
                "INSPECTION", "SAMPLE_REQUIREMENT", "DEMONSTRATION", "SERVICE_SUPPORT", "AMC", "PAYMENT", "EMD",
                "EPBG", "MSE", "STARTUP", "MII", "LOCAL_CONTENT", "DOCUMENT_SUBMISSION", "DECLARATION",
                "UNDERTAKING", "COMPLIANCE", "BUYER_ATC", "OTHER"}
    assert required <= set(REQUIREMENT_TYPES) and set(REQUIREMENT_TYPES) == set(CATEGORY_BY_TYPE)
    assert map_requirement_type("gst registration") == ("OTHER", "gst registration")


def test_malformed_and_invalid_responses_fail_without_retry(asettings, session_factory, clock, db):
    s3b = stage3b_run(db, asettings, session_factory)
    for raw, code in (("I think the tender needs ISO.", "MALFORMED_JSON"),
                      ({"summary": "x", "requirements": "nope"}, "SCHEMA_VALIDATION_FAILED")):
        mock = MockProvider(responses=[raw])
        svc = service(asettings, session_factory, clock, mock)
        assert svc.analyze(s3b).outcome == RESPONSE_INVALID
        res = enqueue_ai_analysis(db, s3b, AIJobReason.MANUAL, asettings)
        db.commit()
        mock.responses = [raw]
        j = AIAnalysisJobWorker(asettings, session_factory, svc, clock=clock).run_batch().jobs[0]
        assert (j.status, j.error_code) == ("FAILED", code) and len(mock.requests) == 2   # no automatic retry
        assert res.job_id == j.job_id
    fresh(db)
    assert db.scalar(select(func.count()).select_from(AIAnalysisRun)) == 0


# ===========================================================================
# 9-13. obligation levels (wording guards)
# ===========================================================================
def test_obligation_level_classification(asettings, session_factory, clock, db):
    s3b = stage3b_run(db, asettings, session_factory)
    svc0 = service(asettings, session_factory, clock)
    w, iso = chunk_key(svc0, s3b, WARRANTY_Q), chunk_key(svc0, s3b, ISO_Q)
    opt = chunk_key(svc0, s3b, "reserves the right")
    resp = envelope(
        req("ISO", "MANDATORY", iso, ISO_Q),                                                   # 9 kept (must)
        req("BUYER_ATC", "OPTIONAL", opt, "The Purchaser reserves the right."),                # 10
        req("WARRANTY", "CONDITIONAL", w, WARRANTY_Q, condition="from the date of final acceptance"),  # 11
        req("BUYER_ATC", "INFORMATIONAL", opt, "OPTION CLAUSE: The Purchaser reserves the right"),                 # 12
        req("WARRANTY", "UNKNOWN", w, "Warranty period of the supplied products", ambiguity="start date unclear"),  # 13
        req("BUYER_ATC", "MANDATORY", opt, "OPTION CLAUSE: The Purchaser reserves the right."),  # no wording
        req("BUYER_ATC", "CONDITIONAL", opt, "OPTION CLAUSE: The Purchaser reserves the right"),                   # no condition
        req("BUYER_ATC", "SOMETIMES", opt, "OPTION CLAUSE: The Purchaser reserves the right"),                     # unrecognized
    )
    _, _, _, out = analyze_with(asettings, session_factory, clock, db, [resp], s3b=s3b)
    rows = reqs_of(db, out.analysis_run_id)
    got = [(q.obligation_level, q.model_obligation_level, q.level_adjustment) for q in rows]
    assert got == [("MANDATORY", "MANDATORY", None), ("OPTIONAL", "OPTIONAL", None),
                   ("CONDITIONAL", "CONDITIONAL", None), ("INFORMATIONAL", "INFORMATIONAL", None),
                   ("UNKNOWN", "UNKNOWN", None),
                   ("UNKNOWN", "MANDATORY", "NO_OBLIGATION_WORDING"),      # ATC position alone is not "mandatory"
                   ("UNKNOWN", "CONDITIONAL", "NO_CONDITION_STATED"),
                   ("UNKNOWN", "SOMETIMES", "UNRECOGNIZED_LEVEL")]
    assert rows[2].condition_text == "from the date of final acceptance"
    review = [f for f in flags_of(db, out.analysis_run_id) if f.flag_type == "REVIEW_REQUIRED"]
    assert len(review) == 3


# ===========================================================================
# 14-17. chunking
# ===========================================================================
def test_chunk_generation_provenance_and_dedup(db, asettings, session_factory):
    e = make_stage3a(db)
    src = load_source(db, e.id)
    db.rollback()
    chunks = build_chunks(src, max_chunk_chars=3000)
    assert [c.key for c in chunks] == [f"C{i}" for i in range(1, len(chunks) + 1)]                 # 14
    kinds = {c.kind for c in chunks}
    assert {"BUYER_ATC", "TABLE", "BOILERPLATE"} <= kinds
    atc = [c for c in chunks if c.kind == "BUYER_ATC"]
    assert any(WARRANTY_Q in c.text for c in atc) and all(c.page_number == 4 and c.section_id for c in atc)
    boiler = [c for c in chunks if c.kind == "BOILERPLATE"]
    assert boiler and all("Disclaimer" in (c.section_heading or "") for c in boiler)
    # 15. dedup: table facts appear once (table chunk), not again as interleaved page text
    allt = "\n".join(c.text for c in chunks)
    assert allt.count("Two Packet Bid") == 1 and allt.count("Total Quantity") == 1
    norms = [" ".join(c.text.lower().split()) for c in chunks]
    assert len(norms) == len(set(norms))
    # Footer and contact redaction; meaningful Hindi is retained (tested separately).
    assert clean_line("3 / 6") == "" and clean_line("x@nic.in 9876543210 ok") == \
    "[email] [phone] ok"
    sel = select_chunks(chunks, max_chunks=40, max_chars=100000, include_boilerplate=False)
    assert all(not c.sent and c.exclusion_reason == "BOILERPLATE" for c in sel.chunks if c.kind == "BOILERPLATE")
    assert not sel.truncated
    with_bp = select_chunks(build_chunks(src, max_chunk_chars=3000), max_chunks=40, max_chars=100000,
                            include_boilerplate=True)
    assert all(c.sent for c in with_bp.chunks)
    # long text is split at clause boundaries within the limit
    small = build_chunks(src, max_chunk_chars=200)
    assert all(c.char_count <= 200 for c in small) and len(small) > len(chunks)


def test_chunk_and_character_limits(asettings, session_factory, clock, db):
    s3b = stage3b_run(db, asettings, session_factory)
    lim = asettings.model_copy(update={"ai_max_chunks_per_analysis": 2})
    mock = MockProvider()
    out = AnalysisService(lim, session_factory, provider_factory=lambda: mock, clock=clock).analyze(s3b)
    assert out.status == "PARTIAL_SUCCESS" and out.error_code == "INPUT_TRUNCATED"                   # 16
    sent = mock.requests[0].chunks
    assert len(sent) == 2 and {c["kind"] for c in sent} == {"BUYER_ATC"}            # priority: ATC first
    fresh(db)
    rows = db.scalars(select(AIEvidenceChunk).where(AIEvidenceChunk.analysis_run_id == out.analysis_run_id)).all()
    assert sum(r.sent for r in rows) == 2 and {r.exclusion_reason for r in rows if not r.sent} >= {"CHUNK_LIMIT",
                                                                                                    "BOILERPLATE"}
    assert any(f.flag_type == "INPUT_TRUNCATED" for f in flags_of(db, out.analysis_run_id))
    # 17. character budget: the chunk text actually sent never exceeds AI_MAX_INPUT_CHARACTERS
    full = service(asettings, session_factory, clock, MockProvider()).prepare(s3b, force=True).prompt.characters
    limit = full - 300
    lim2 = asettings.model_copy(update={"ai_max_input_characters": limit})
    mock2 = MockProvider()
    p = AnalysisService(lim2, session_factory, provider_factory=lambda: mock2, clock=clock).prepare(s3b, force=True)
    assert p.prompt is not None and p.prompt.characters <= limit and p.chunks.truncated   # WHOLE prompt bounded
    assert any(c.exclusion_reason == "CHAR_LIMIT" for c in p.chunks.chunks)
    assert [c.text for c in p.chunks.sent] == [c["text"] for c in json.loads(p.prompt.user)["evidence_chunks"]]
    assert not any(c.text[:40] in p.prompt.user for c in p.chunks.chunks if not c.sent and len(c.text) > 40)


# ===========================================================================
# 18-19. evidence grounding
# ===========================================================================
def test_evidence_ids_validated_and_fabrication_rejected(asettings, session_factory, clock, db):
    s3b = stage3b_run(db, asettings, session_factory)
    svc0 = service(asettings, session_factory, clock)
    p = svc0.prepare(s3b, force=True)
    iso = next(c.key for c in p.chunks.sent if ISO_Q in c.text)
    not_sent = next(c.key for c in p.chunks.chunks if not c.sent)
    resp = envelope(
        req("ISO", "MANDATORY", iso, "The bidder or the OEM of the offered products must have ISO 9001"),  # 18 ok
        req("ISO", "MANDATORY", iso.lower(), ISO_Q),                                     # id case-insensitive
        req("ISO", "MANDATORY", "C999", ISO_Q, title="fabricated id"),                   # 19 unknown id
        req("ISO", "MANDATORY", not_sent, "ISO 14001", title="not sent chunk"),          # 19 not sent -> unknown
        req("TURNOVER", "MANDATORY", iso, "Annual turnover of Rs 5 crore", title="invented quote"),  # 19
        req("ISO", "MANDATORY", iso, "must have ISO 9001 ... certification"),            # ellipsis fragments ok
        {**req("GST", "MANDATORY", iso, ISO_Q, title="mixed"),
         "evidence": [{"chunk_id": iso, "quote": ISO_Q}, {"chunk_id": "C404", "quote": "x"}]},  # any unknown id
    )
    _, _, _, out = analyze_with(asettings, session_factory, clock, db, [resp], s3b=s3b)
    rows = reqs_of(db, out.analysis_run_id)
    assert len(rows) == 3
    run = db.get(AIAnalysisRun, out.analysis_run_id)
    reasons = sorted(r["reason"].split(":")[0] for r in json.loads(run.rejected_json))
    assert reasons == ["QUOTE_NOT_IN_EVIDENCE", "UNKNOWN_EVIDENCE_ID", "UNKNOWN_EVIDENCE_ID", "UNKNOWN_EVIDENCE_ID"]
    ev = db.scalars(select(AIRequirementEvidence).where(AIRequirementEvidence.analysis_run_id == run.id)).all()
    chunks = {c.id: c for c in db.scalars(select(AIEvidenceChunk).where(AIEvidenceChunk.analysis_run_id == run.id))}
    for e in ev:                                       # every stored link resolves to a SENT chunk containing it
        c = chunks[e.chunk_id]
        assert c.sent and c.chunk_key == e.chunk_key and quote_in_chunk(e.quote, c.text) is not None
        assert e.page_number == c.page_number == 4 and e.section_id == c.section_id
    assert all(r.is_buyer_atc for r in rows)


# ===========================================================================
# 21-23. Stage 3B interaction and flags
# ===========================================================================
def test_stage3b_preserved_and_disagreements_flagged(asettings, session_factory, clock, db):
    s3b = stage3b_run(db, asettings, session_factory)
    fx = db.get(TenderFieldExtraction, s3b)
    before3a, before3b = stage3a_digest(db, fx.stage3a_extraction_id), stage3b_digest(db, s3b)
    db.rollback()
    svc0 = service(asettings, session_factory, clock)
    w, iso = chunk_key(svc0, s3b, WARRANTY_Q), chunk_key(svc0, s3b, ISO_Q)
    pp = chunk_key(svc0, s3b, "should have supplied")
    resp = envelope(
        req("EMD", "MANDATORY", iso, ISO_Q, title="EMD read into ATC"),                        # vs emd_required FALSE
        req("WARRANTY", "MANDATORY", w, WARRANTY_Q, value="3", unit="YEARS"),                  # vs 5 YEARS
        req("WARRANTY", "MANDATORY", w, WARRANTY_Q, value=5, unit="years"),                    # agrees
        req("PAST_PERFORMANCE", "UNKNOWN", pp, "should have supplied same or similar Category Products",
            ambiguity="'should' may or may not be binding"),
        req("ISO", "MANDATORY", iso, ISO_Q, risk_flags=["brand_specific", "weird"]),
        ambiguities=[{"description": "Option clause scope unclear",
                      "evidence": [{"chunk_id": chunk_key(svc0, s3b, "reserves the right"),
                                    "quote": "The Purchaser reserves the right"}]}],
    )
    _, _, _, out = analyze_with(asettings, session_factory, clock, db, [resp], s3b=s3b)
    assert out.status == "PARTIAL_SUCCESS" and out.error_code == "REVIEW_FLAGS"      # HIGH flag present
    flags = flags_of(db, out.analysis_run_id)
    conflict = [f for f in flags if f.flag_type == "AI_DETERMINISTIC_CONFLICT"]
    assert {(f.severity, f.stage3b_field_name, f.stage3b_value) for f in conflict} == {
        ("HIGH", "emd_required", "FALSE"), ("WARNING", "warranty_period", "5 YEARS")}               # 22
    assert all(f.requirement_id and json.loads(f.chunk_keys_json) for f in conflict)
    assert any(f.flag_type == "CONTRADICTORY_REQUIREMENT" for f in flags)        # 3 vs 5 years, both mandatory
    assert any(f.flag_type == "AMBIGUOUS_ATC" and f.requirement_id is None for f in flags)                  # 23
    assert any(f.flag_type == "REVIEW_REQUIRED" and "should" in f.message for f in flags)  # non-ATC ambiguity
    assert any(f.flag_type == "RESTRICTIVE_CLAUSE" for f in flags)
    iso_row = [q for q in reqs_of(db, out.analysis_run_id) if q.requirement_type == "ISO"][0]
    assert json.loads(iso_row.risk_flags_json) == ["BRAND_SPECIFIC", "OTHER"]
    run = db.get(AIAnalysisRun, out.analysis_run_id)
    assert run.conflicts_count == 3 and run.ambiguities_count == 2
    # 21. Stage 3B (and 3A) untouched: same digests, emd_required still FALSE
    assert stage3b_digest(db, s3b) == before3b and stage3a_digest(db, fx.stage3a_extraction_id) == before3a
    emd = db.scalar(select(TenderFieldValue).where(TenderFieldValue.field_extraction_id == s3b,
                                                   TenderFieldValue.field_name == "emd_required"))
    assert (emd.tri_state, emd.status) == ("FALSE", "RESOLVED")


def test_unknown_stage3b_field_supplemented_not_overwritten(asettings, session_factory, clock, db):
    s3b = stage3b_run(db, asettings, session_factory)
    svc0 = service(asettings, session_factory, clock)
    pp = chunk_key(svc0, s3b, "should have supplied")
    q = "should have supplied same or similar Category Products for 10% of bid quantity, in at least one of the last" \
        " three Financial years"
    resp = envelope(req("EXPERIENCE", "MANDATORY", pp, q, value=3, unit="YEARS"))
    _, _, _, out = analyze_with(asettings, session_factory, clock, db, [resp], s3b=s3b)
    f = [x for x in flags_of(db, out.analysis_run_id) if x.flag_type == "AI_SUPPLEMENTS_UNKNOWN"]
    assert f and f[0].severity == "INFO" and f[0].stage3b_value is None
    exp = db.scalar(select(TenderFieldValue).where(TenderFieldValue.field_extraction_id == s3b,
                                                   TenderFieldValue.field_name == "experience_years"))
    assert exp.status == "UNKNOWN" and exp.value_text is None


# ===========================================================================
# 25-29. provider failures, retries, BLOCKED
# ===========================================================================
def _gemini(handler, settings) -> GeminiProvider:
    return GeminiProvider("gemini-test", SECRET, transport=httpx.MockTransport(handler))


def _gemini_ok(body: dict, usage=True):
    payload = {"candidates": [{"content": {"parts": [{"text": json.dumps(body)}]}, "finishReason": "STOP"}],
               "modelVersion": "gemini-test-001"}
    if usage:
        payload["usageMetadata"] = {"promptTokenCount": 1200, "candidatesTokenCount": 300, "totalTokenCount": 1500}
    return payload


def test_http_providers_request_shape_and_error_mapping():
    seen = {}

    def ok(request: httpx.Request):
        seen.update(url=str(request.url), headers=dict(request.headers), body=json.loads(request.content))
        return httpx.Response(200, json=_gemini_ok({"summary": "s", "requirements": []}))

    g = GeminiProvider("gemini-test", SECRET, transport=httpx.MockTransport(ok))
    r = g.generate(AIRequest(system="SYS", user="USER", max_output_tokens=777))
    assert SECRET not in seen["url"] and seen["headers"]["x-goog-api-key"] == SECRET    # key only in header
    assert seen["url"].endswith("/models/gemini-test:generateContent")
    assert seen["body"]["generationConfig"]["maxOutputTokens"] == 777
    assert (r.input_tokens, r.output_tokens, r.total_tokens, r.model) == (1200, 300, 1500, "gemini-test-001")

    def status(code, body=None, headers=None):
        return lambda req: httpx.Response(code, json=body or {"error": {"message": f"bad key {SECRET}"}},
                                          headers=headers or {})

    cases = [(status(401), ProviderAuthError), (status(403), ProviderAuthError),
             (status(404), ProviderConfigError), (status(400), ProviderConfigError),
             (status(429, headers={"retry-after": "7"}), ProviderRateLimited), (status(503), ProviderUnavailable)]
    for handler, cls in cases:
        with pytest.raises(cls) as exc:
            GeminiProvider("m", SECRET, transport=httpx.MockTransport(handler)).generate(
                AIRequest(system="s", user="u", max_output_tokens=10))
        assert SECRET not in str(exc.value)                                           # redacted
    with pytest.raises(ProviderRateLimited) as exc:
        GeminiProvider("m", SECRET, transport=httpx.MockTransport(cases[4][0])).generate(
            AIRequest(system="s", user="u", max_output_tokens=10))
    assert exc.value.retry_after == 7.0

    def timeout(req):
        raise httpx.ReadTimeout("slow", request=req)

    with pytest.raises(ProviderTimeout):
        GeminiProvider("m", SECRET, transport=httpx.MockTransport(timeout)).generate(
            AIRequest(system="s", user="u", max_output_tokens=10))

    def truncated(req):
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": '{"summary": "x'}]},
                                                         "finishReason": "MAX_TOKENS"}]})

    for handler, code in ((truncated, "RESPONSE_TRUNCATED"),
                          (lambda req: httpx.Response(200, json={"candidates": []}), "EMPTY_RESPONSE"),
                          (lambda req: httpx.Response(200, json={"promptFeedback": {"blockReason": "SAFETY"}}),
                           "RESPONSE_BLOCKED")):
        with pytest.raises(ProviderResponseError) as exc:
            GeminiProvider("m", SECRET, transport=httpx.MockTransport(handler)).generate(
                AIRequest(system="s", user="u", max_output_tokens=10))
        assert exc.value.code == code
    # OpenAI-compatible
    def oai(req):
        seen.update(headers=dict(req.headers), body=json.loads(req.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"summary": "s"}'},
                                                      "finish_reason": "stop"}],
                                         "usage": {"prompt_tokens": 5, "completion_tokens": 6, "total_tokens": 11}})

    o = OpenAICompatibleProvider("gpt-x", "sk-abcdefghijklmnop", transport=httpx.MockTransport(oai))
    r = o.generate(AIRequest(system="S", user="U", max_output_tokens=50))
    assert seen["headers"]["authorization"] == "Bearer sk-abcdefghijklmnop"
    assert seen["body"]["response_format"] == {"type": "json_object"} and seen["body"]["max_tokens"] == 50
    assert (r.input_tokens, r.output_tokens, r.total_tokens) == (5, 6, 11)
    o2 = OpenAICompatibleProvider("gpt-x", "k" * 20, transport=httpx.MockTransport(
        lambda req: httpx.Response(200, json={"choices": [{"message": {"content": "{"}, "finish_reason": "length"}]})))
    with pytest.raises(ProviderResponseError) as exc:
        o2.generate(AIRequest(system="S", user="U", max_output_tokens=50))
    assert exc.value.code == "RESPONSE_TRUNCATED"


def test_timeout_and_rate_limit_retry_then_job_retry_then_failed(asettings, session_factory, clock, db):
    s3b = stage3b_run(db, asettings, session_factory)
    sleeps: list[float] = []
    mock = MockProvider(responses=[ProviderTimeout("t1"), ProviderRateLimited("r", retry_after=7.0)] * 3)
    svc = service(asettings, session_factory, clock, mock, sleeps=sleeps)
    worker = AIAnalysisJobWorker(asettings, session_factory, svc, clock=clock)
    res = enqueue_ai_analysis(db, s3b, AIJobReason.MANUAL, asettings)
    db.commit()
    j = worker.run_batch().jobs[0]
    assert (j.status, j.error_code) == ("RETRY", "PROVIDER_RATE_LIMITED")                        # 25, 26, 28
    assert len(mock.requests) == 2 and sleeps == [0.0]          # timeout -> immediate retry (base delay 0)
    assert j.next_retry_at == clock.now + timedelta(minutes=10)
    assert worker.run_batch().processed == 0                                       # next_retry_at respected
    clock.advance(minutes=11)
    assert worker.run_batch().jobs[0].status == "RETRY"
    assert sleeps[-1] == 0.0
    clock.advance(minutes=21)
    j3 = worker.run_batch().jobs[0]
    assert (j3.status, j3.error_code) == ("FAILED", "RETRIES_EXHAUSTED") and len(mock.requests) == 6
    fresh(db)
    job = db.get(AIAnalysisJob, res.job_id)
    assert job.attempt_count == 3 and "PROVIDER_RATE_LIMITED" in job.error_message
    direct = service(asettings, session_factory, clock, MockProvider(responses=[ProviderUnavailable("503")] * 2))
    o = direct.analyze(s3b)
    assert (o.outcome, o.error_code, o.transient, o.blocking) == (PROVIDER_FAILED, "PROVIDER_UNAVAILABLE", True, False)
    # rate limit retry-after honoured inside the call (capped at 30 s)
    sleeps.clear()
    mock2 = MockProvider(responses=[ProviderRateLimited("r", retry_after=99.0), envelope()])
    out = service(asettings, session_factory, clock, mock2, sleeps=sleeps).analyze(s3b)
    assert out.outcome == ANALYZED and sleeps == [30.0]
    fresh(db)
    assert db.get(AIAnalysisRun, out.analysis_run_id).provider_attempts == 2


def test_auth_failure_blocks_without_retry_and_pauses_worker(asettings, session_factory, clock, db, caplog):
    caplog.set_level(logging.DEBUG)
    a, b = (stage3b_run(db, asettings, session_factory, bid=f"GEM/2026/B/91000{i}") for i in (1, 2))
    gs = asettings.model_copy(update={"ai_provider": "gemini", "ai_model": "gemini-test", "ai_api_key": SecretStr(SECRET)})
    calls = []

    def unauthorized(req):
        calls.append(req)
        return httpx.Response(401, json={"error": {"message": f"API key not valid: {SECRET}"}})

    svc = AnalysisService(gs, session_factory, clock=clock, sleep=lambda s: None,
                          provider_factory=lambda: GeminiProvider("gemini-test", SECRET,
                                                                  transport=httpx.MockTransport(unauthorized)))
    for i in (a, b):
        enqueue_ai_analysis(db, i, AIJobReason.MANUAL, gs)
    db.commit()
    worker = AIAnalysisJobWorker(gs, session_factory, svc, clock=clock)
    batch = worker.run_batch(max_jobs=5)
    assert [(j.status, j.error_code) for j in batch.jobs] == [("BLOCKED", "PROVIDER_AUTH_FAILED")]      # 27
    assert len(calls) == 1                                       # no retry, second job not attempted
    nxt = worker.run_batch()
    assert nxt.processed == 0 and nxt.skipped_reason == SKIP_BLOCKED and len(calls) == 1                  # 29
    clock.advance(minutes=61)
    assert worker.run_batch().jobs[0].status == "BLOCKED" and len(calls) == 2
    fresh(db)
    msgs = [j.error_message for j in db.scalars(select(AIAnalysisJob))]
    assert all(SECRET not in (m or "") for m in msgs) and any("[REDACTED]" in (m or "") for m in msgs)
    assert SECRET not in caplog.text                                                                      # 37
    # BLOCKED is not a queued status: the run can be re-queued explicitly after fixing the key
    assert enqueue_ai_analysis(db, a, AIJobReason.MANUAL, gs).created


def test_not_configured_claims_nothing_and_daily_limit(asettings, session_factory, clock, db):
    s3b = stage3b_run(db, asettings, session_factory)
    none = asettings.model_copy(update={"ai_provider": ""})
    res = enqueue_ai_analysis(db, s3b, AIJobReason.MANUAL, none)
    db.commit()
    w = AIAnalysisJobWorker(none, session_factory, AnalysisService(none, session_factory, clock=clock), clock=clock)
    batch = w.run_batch()
    assert batch.processed == 0 and batch.skipped_reason == SKIP_NOT_CONFIGURED and "AI_NOT_CONFIGURED" in \
        batch.skipped_detail                                                                              # 29
    fresh(db)
    assert db.get(AIAnalysisJob, res.job_id).status == "PENDING"
    capped = asettings.model_copy(update={"ai_max_analyses_per_day": 0})
    w2 = AIAnalysisJobWorker(capped, session_factory, service(capped, session_factory, clock, MockProvider()),
                             clock=clock)
    b2 = w2.run_batch()
    assert b2.processed == 0 and b2.skipped_reason == SKIP_DAILY_LIMIT
    with pytest.raises(NotConfigured):
        build_provider(none)


# ===========================================================================
# 30-37. idempotency, force, history, versions, secrets
# ===========================================================================
def test_idempotency_force_history_and_versions(asettings, session_factory, clock, db):
    s3b = stage3b_run(db, asettings, session_factory)
    mock = MockProvider()
    svc = service(asettings, session_factory, clock, mock)
    first = svc.analyze(s3b)
    assert first.outcome == ANALYZED
    again = svc.analyze(s3b)
    assert (again.outcome, again.analysis_run_id) == (ALREADY, first.analysis_run_id) and len(mock.requests) == 1  # 30
    assert enqueue_ai_analysis(db, s3b, AIJobReason.MANUAL, asettings).skipped_reason == "already_analyzed"
    forced = svc.analyze(s3b, force=True)                                                                  # 31
    assert forced.outcome == ANALYZED and forced.analysis_run_id != first.analysis_run_id
    fresh(db)
    runs = db.scalars(select(AIAnalysisRun).order_by(AIAnalysisRun.id)).all()
    assert [r.is_current for r in runs] == [False, True]                                                   # 32
    assert reqs_of(db, runs[0].id) and reqs_of(db, runs[1].id)               # history keeps its requirements
    r = runs[1]
    assert (r.prompt_version, r.schema_version) == (PROMPT_VERSION, SCHEMA_VERSION) == \
        ("stage3c-prompt-v6", "stage3c-schema-v1")                                                         # 33, 34
    assert (r.provider, r.model, r.analyzer_name, r.chunker_version) == (
        "mock", "mock-deterministic-v1", "gem-ai-analysis", "stage3c-chunks-v2")                          # 35
    assert len(r.request_sha256) == 64 and r.input_tokens and r.latency_ms is not None
    # a different model is a different current analysis (both current)
    other = AnalysisService(asettings.model_copy(update={"ai_model": "mock-v2"}), session_factory,
                            clock=clock).analyze(s3b)
    assert other.outcome == ANALYZED
    fresh(db)
    assert db.scalar(select(func.count()).select_from(AIAnalysisRun).where(AIAnalysisRun.is_current.is_(True))) == 2
    # DB enforces one current run per (stage3b, provider, model, prompt, schema)
    with session_factory() as s, pytest.raises(Exception, match="UNIQUE"):
        s.execute(text("UPDATE ai_analysis_runs SET is_current = 1"))
        s.commit()


def test_no_api_key_persisted_or_logged(asettings, session_factory, clock, db, caplog):
    caplog.set_level(logging.DEBUG)
    s3b = stage3b_run(db, asettings, session_factory)
    gs = asettings.model_copy(update={"ai_provider": "gemini", "ai_model": "gemini-test", "ai_api_key": SecretStr(SECRET)})
    validated = Settings(_env_file=None, ai_provider="gemini", ai_api_key=SECRET)
    for st in (gs, validated):
        assert SECRET not in repr(st) and SECRET not in str(st.model_dump()) and st.ai_api_key_value() == SECRET
    svc0 = service(asettings, session_factory, clock)
    iso = chunk_key(svc0, s3b, ISO_Q)
    body = envelope(req("ISO", "MANDATORY", iso, ISO_Q))
    svc = AnalysisService(gs, session_factory, clock=clock, provider_factory=lambda: GeminiProvider(
        "gemini-test", SECRET, transport=httpx.MockTransport(lambda r: httpx.Response(200, json=_gemini_ok(body))))
    )
    out = svc.analyze(s3b)
    assert out.outcome == ANALYZED
    fresh(db)
    run = db.get(AIAnalysisRun, out.analysis_run_id)
    assert (run.provider, run.model, run.input_tokens, run.output_tokens) == ("gemini", "gemini-test", 1200, 300)
    dump = []
    for (name,) in db.execute(text("SELECT name FROM sqlite_master WHERE type='table'")).all():
        for row in db.execute(text(f'SELECT * FROM "{name}"')).all():
            dump.append(repr(tuple(row)))
    blob = "\n".join(dump)
    assert SECRET not in blob and "x-goog-api-key" not in blob                                             # 36
    assert SECRET not in caplog.text and "ai_provider_call" in caplog.text                                # 37
    assert "Warranty period of the supplied" not in caplog.text   # tender content not dumped into logs


# ===========================================================================
# 38-43. hook, queue failure, worker lifecycle, recovery, backfill
# ===========================================================================
def test_stage3b_to_stage3c_hook_and_queue_failure(asettings, session_factory, clock, db, monkeypatch, caplog):
    on = asettings.model_copy(update={"ai_analysis_auto_queue": True})
    e = make_stage3a(db)
    out = FieldExtractionService(on, session_factory).extract(e.id)
    fresh(db)
    jobs = db.scalars(select(AIAnalysisJob)).all()
    assert [(j.stage3b_extraction_id, j.reason, j.status) for j in jobs] == [
        (out.field_extraction_id, "STAGE3B_COMPLETED", "PENDING")]                                       # 38
    assert db.scalar(select(func.count()).select_from(AIAnalysisRun)) == 0      # queued only, nothing analyzed

    def boom(*a, **k):
        raise RuntimeError("stage 3c queue down")

    monkeypatch.setattr(aq, "enqueue_ai_analysis", boom)
    caplog.set_level(logging.ERROR)
    e2 = make_stage3a(db, bid="GEM/2026/B/5550001")
    out2 = FieldExtractionService(on, session_factory).extract(e2.id)
    assert out2.outcome == "EXTRACTED"
    fresh(db)
    assert db.get(TenderFieldExtraction, out2.field_extraction_id).is_current                              # 39
    assert any("ai_analysis_job_queue_failed" in r.getMessage() for r in caplog.records)
    from app.services.ai_status import ai_analysis_status
    assert ai_analysis_status(db, settings=on)["stage3b_runs_unqueued"] == 1
    monkeypatch.undo()
    assert backfill_ai_jobs(db, on, limit=5) == [out2.field_extraction_id]                     # recoverable
    # Stage 3B worker path also queues (separate commit)
    from app.fields.job_queue import enqueue_field_extraction
    from app.fields.job_worker import FieldExtractionJobWorker
    e3 = make_stage3a(db, bid="GEM/2026/B/5550002")
    enqueue_field_extraction(db, e3.id, "MANUAL")
    db.commit()
    r3 = FieldExtractionJobWorker(on, session_factory).run_batch().jobs[0]
    fresh(db)
    assert db.scalar(select(AIAnalysisJob).where(AIAnalysisJob.stage3b_extraction_id == r3.field_extraction_id))


def test_worker_lifecycle_atomic_finish_and_no_db_lock_during_call(asettings, session_factory, clock, db):
    s3b = stage3b_run(db, asettings, session_factory)
    res = enqueue_ai_analysis(db, s3b, AIJobReason.MANUAL, asettings)
    db.commit()
    seen = {}

    def during_call(request):
        with session_factory() as other:
            row = other.get(AIAnalysisJob, res.job_id)
            seen.update(status=row.status, locked_by=row.locked_by, provider=row.provider)
            other.execute(text("PRAGMA busy_timeout=200"))
            other.execute(text("UPDATE tenders SET title='write during provider call'"))
            other.commit()                                   # no SQLite write lock held while the provider runs
        return envelope()

    mock = MockProvider(responses=[during_call])
    worker = AIAnalysisJobWorker(asettings, session_factory, service(asettings, session_factory, clock, mock),
                                 clock=clock)
    j = worker.run_batch().jobs[0]
    assert seen == {"status": "RUNNING", "locked_by": worker.worker_id, "provider": "mock"}               # 40
    fresh(db)
    job = db.get(AIAnalysisJob, res.job_id)
    assert (j.status, job.status, job.locked_by, job.analysis_run_id, job.model) == (
        "SUCCESS", "SUCCESS", None, j.analysis_run_id, "mock-deterministic-v1")
    assert worker.run_batch().processed == 0


def test_stale_running_recovered_live_untouched(asettings, session_factory, clock, db):
    a = stage3b_run(db, asettings, session_factory, bid="GEM/2026/B/1200001")
    b = stage3b_run(db, asettings, session_factory, bid="GEM/2026/B/1200002")
    with session_factory() as s:
        s.add_all([AIAnalysisJob(id=50, stage3b_extraction_id=a, status="RUNNING", attempt_count=1,
                                 started_at=clock.now, locked_by=f"{socket.gethostname()}:1:dead"),
                   AIAnalysisJob(id=51, stage3b_extraction_id=b, status="RUNNING", attempt_count=1,
                                 started_at=clock.now, locked_by="other-host:2:live")])
        s.commit()
    worker = AIAnalysisJobWorker(asettings, session_factory, service(asettings, session_factory, clock,
                                                                      MockProvider()), clock=clock)
    batch = worker.run_batch(max_jobs=5)
    fresh(db)
    assert batch.recovered_stale == 1 and db.get(AIAnalysisJob, 50).status == "SUCCESS"                   # 41
    assert db.get(AIAnalysisJob, 51).status == "RUNNING"
    clock.advance(minutes=31)
    assert worker.recover_stale_jobs() == 1
    fresh(db)
    assert db.get(AIAnalysisJob, 51).status == "RETRY"


def test_backfill_bounded_and_dry_run(asettings, session_factory, db):
    ids = [stage3b_run(db, asettings, session_factory, bid=f"GEM/2026/B/80000{i}") for i in range(4)]
    assert backfill_ai_jobs(db, asettings, limit=2, dry_run=True) == [ids[3], ids[2]]                     # 43
    db.rollback()
    fresh(db)
    assert db.scalar(select(func.count()).select_from(AIAnalysisJob)) == 0
    first = backfill_ai_jobs(db, asettings, limit=2)
    db.commit()
    second = backfill_ai_jobs(db, asettings, limit=5)
    db.commit()
    assert first == [ids[3], ids[2]] and second == [ids[1], ids[0]]                                       # 42
    assert backfill_ai_jobs(db, asettings, limit=5) == []
    fresh(db)
    assert db.scalar(select(func.count()).select_from(AIAnalysisRun)) == 0    # backfill never analyzes


def test_not_ready_sources_are_never_faked(asettings, session_factory, clock, db):
    s3b = stage3b_run(db, asettings, session_factory)
    svc = service(asettings, session_factory, clock, MockProvider())
    assert svc.analyze(999999).error_code == "STAGE3B_NOT_FOUND"
    with session_factory() as s:
        s.execute(text("UPDATE tender_field_extractions SET is_current = 0 WHERE id = :i"), {"i": s3b})
        s.commit()
    out = svc.analyze(s3b)
    assert (out.outcome, out.error_code) == (NOT_READY, "STAGE3B_NOT_CURRENT")
    assert enqueue_ai_analysis(db, s3b, AIJobReason.MANUAL, asettings).skipped_reason == "not_ready"
    db.add(AIAnalysisJob(stage3b_extraction_id=s3b, status="PENDING", reason="MANUAL"))
    db.commit()
    j = AIAnalysisJobWorker(asettings, session_factory, svc, clock=clock).run_batch().jobs[0]
    assert (j.status, j.error_code) == ("SKIPPED", "STAGE3B_NOT_CURRENT")
    assert svc.analyze(s3b).outcome == NOT_READY


# ===========================================================================
# 44-51. scheduler, API, health, stats
# ===========================================================================
def test_scheduler_disabled_by_default(asettings, session_factory):
    from app.scheduler.scheduler import AI_ANALYSIS_WORKER_JOB_ID, CollectionScheduler
    assert Settings(_env_file=None).ai_analysis_worker_enabled is False                                  # 44
    assert Settings(_env_file=None).ai_provider == ""
    worker = AIAnalysisJobWorker(asettings, session_factory)
    s = CollectionScheduler(asettings.model_copy(update={"collect_on_startup": False}), runner=None,
                            ai_analysis_worker=worker)
    s.start()
    try:
        assert not s.ai_analysis_jobs_enabled and s._scheduler.get_job(AI_ANALYSIS_WORKER_JOB_ID) is None
    finally:
        s.shutdown()
    s2 = CollectionScheduler(asettings.model_copy(update={"collect_on_startup": False,
                                                          "ai_analysis_worker_enabled": True}),
                             runner=None, ai_analysis_worker=worker)
    s2.start()
    try:
        assert s2._scheduler.get_job(AI_ANALYSIS_WORKER_JOB_ID) is not None
    finally:
        s2.shutdown()
    env = (PROJECT_ROOT / ".env.example").read_text()
    assert "AI_ANALYSIS_WORKER_ENABLED=false" in env and "AI_API_KEY=\n" in env


@pytest.fixture
def api(asettings, session_factory, source):
    from fastapi.testclient import TestClient

    from app.main import create_app

    with TestClient(create_app(asettings, session_factory=session_factory, collector_factory=source)) as c:
        yield c


def test_api_static_routes_not_swallowed(authorized_ai_api):
    api = authorized_ai_api
    schema = api.get("/openapi.json").json()
    static = [p for p in schema["paths"] if p.startswith("/api/ai-analysis") and "{" not in p]
    assert {"/api/ai-analysis", "/api/ai-analysis/jobs", "/api/ai-analysis/worker"} <= set(static)
    for path in static:                                                                                  # 45
        r = api.get(path)
        assert r.status_code == 200, path
        assert not any(d.get("loc", [None])[0] == "path" for d in (r.json().get("detail") or [])
                       if isinstance(d, dict)), path
    assert api.get("/api/ai-analysis/not-a-number").status_code == 422
    assert api.get("/api/ai-analysis/999").status_code == 404



@pytest.fixture
def authorized_ai_api(api, session_factory):
    """Authorized AI-analysis operator in the temporary test database."""
    from uuid import uuid4
    from app.api.auth import get_current_user
    from app.core.supabase_auth import AuthenticatedIdentity
    from app.database.auth_models import AppUser
    from app.database.platform_auth_models import PlatformOperatorGrant

    subject = str(uuid4())

    with session_factory() as db:
        user = AppUser(supabase_user_id=subject)
        db.add(user)
        db.flush()

        db.add(
            PlatformOperatorGrant(
                user_id=user.id,
                granted_by_user_id=user.id,
                permission="AI_ANALYSIS_MANAGE",
                status="ACTIVE",
            )
        )
        db.add(PlatformOperatorGrant(user_id=user.id, granted_by_user_id=user.id, permission="TENDER_ANALYSIS_READ", status="ACTIVE"))
        db.commit()

    identity = AuthenticatedIdentity(
        subject=subject,
        email="stage3c-test@example.com",
        claims={"sub": subject, "role": "authenticated"},
    )

    api.app.dependency_overrides[get_current_user] = lambda: identity

    try:
        yield api
    finally:
        api.app.dependency_overrides.pop(get_current_user, None)


def test_api_list_detail_requirements_evidence_flags(authorized_ai_api, asettings, session_factory, clock, db):
    s3b = stage3b_run(db, asettings, session_factory)
    q1 = authorized_ai_api.post(f"/api/ai-analysis/stage3b/{s3b}/queue").json()
    q2 = authorized_ai_api.post(f"/api/ai-analysis/stage3b/{s3b}/queue").json()
    assert q1["queued"] is True and q2["reason"] == "already_queued" and q2["job_id"] == q1["job_id"]
    fresh(db)
    assert db.scalar(select(func.count()).select_from(AIAnalysisRun)) == 0     # API never calls a provider
    svc0 = service(asettings, session_factory, clock)
    w, iso = chunk_key(svc0, s3b, WARRANTY_Q), chunk_key(svc0, s3b, ISO_Q)
    resp = envelope(req("WARRANTY", "MANDATORY", w, WARRANTY_Q, value=5, unit="YEARS"),
                    req("EMD", "MANDATORY", iso, ISO_Q), req("ISO", "CONDITIONAL", iso, ISO_Q, condition="if OEM"))
    worker = AIAnalysisJobWorker(asettings, session_factory, service(asettings, session_factory, clock,
                                                                      MockProvider(responses=[resp])), clock=clock)
    rid = worker.run_batch().jobs[0].analysis_run_id
    lst = authorized_ai_api.get("/api/ai-analysis").json()
    assert lst["total"] == 1 and lst["items"][0]["provider"] == "mock"                                    # 46
    assert authorized_ai_api.get("/api/ai-analysis", params={"flag_type": "AI_DETERMINISTIC_CONFLICT"}).json()["total"] == 1
    assert authorized_ai_api.get("/api/ai-analysis", params={"requirement_type": "WARRANTY",
                                               "obligation_level": "MANDATORY"}).json()["total"] == 1
    assert authorized_ai_api.get("/api/ai-analysis", params={"requirement_type": "AMC"}).json()["total"] == 0
    assert authorized_ai_api.get("/api/ai-analysis", params={"obligation_level": "MAYBE"}).status_code == 422
    d = authorized_ai_api.get(f"/api/ai-analysis/{rid}").json()
    assert d["source"]["stage3b_extraction_id"] == s3b and d["prompt_version"] == PROMPT_VERSION
    assert len(d["outputs"]["mandatory_requirements"]) == 2 and len(d["outputs"]["conditional_requirements"]) == 1
    assert d["outputs"]["deterministic_disagreements"][0]["stage3b_field_name"] == "emd_required"
    assert len(d["outputs"]["important_atc_clauses"]) == 3 and d["outputs"]["delivery_warranty_obligations"]
    assert all(r["evidence"] for r in d["requirements"])                          # evidence for every result
    rq = authorized_ai_api.get(f"/api/ai-analysis/{rid}/requirements", params={"obligation_level": "CONDITIONAL"}).json()
    assert [r["requirement_type"] for r in rq["items"]] == ["ISO"] and rq["items"][0]["mandatory"] is None  # 47
    ev = authorized_ai_api.get(f"/api/ai-analysis/{rid}/evidence", params={"include_chunks": True}).json()
    assert ev["items"][0]["page_number"] == 4 and ev["items"][0]["document_version_id"] and \
        ev["items"][0]["stage3a_extraction_id"] and ev["items"][0]["section_heading"]                    # 48
    assert any(not c["sent"] and c["exclusion_reason"] == "BOILERPLATE" for c in ev["chunks"])
    fl = authorized_ai_api.get(f"/api/ai-analysis/{rid}/flags", params={"severity": "HIGH"}).json()["items"]
    assert [f["flag_type"] for f in fl] == ["AI_DETERMINISTIC_CONFLICT"]                                  # 49
    by_bid = authorized_ai_api.get("/api/ai-analysis/bid/GEM/2026/B/8124821").json()
    assert by_bid["items"][0]["id"] == rid and by_bid["items"][0]["is_latest_version"]
    re = authorized_ai_api.post(f"/api/ai-analysis/stage3b/{s3b}/reanalyze").json()
    assert re["queued"] is True and re["force"] is True
    hist = authorized_ai_api.get(f"/api/ai-analysis/stage3b/{s3b}").json()
    assert hist["current"][0]["id"] == rid and len(hist["history"]) == 1
    assert authorized_ai_api.post("/api/ai-analysis/stage3b/999999/queue").status_code == 404
    assert authorized_ai_api.get(f"/api/ai-analysis/jobs/{q1['job_id']}").json()["status"] == "PARTIAL_SUCCESS"  # HIGH flag


def test_health_and_stats_never_expose_key(asettings, session_factory, source, clock, db):
    from fastapi.testclient import TestClient

    from app.main import create_app
    from app.api.auth import get_current_user
    from app.core.supabase_auth import AuthenticatedIdentity
    from app.database.auth_models import AppUser
    from app.database.platform_auth_models import PlatformOperatorGrant
    from uuid import uuid4

    subject = str(uuid4())

    with session_factory() as db_session:
        operator = AppUser(supabase_user_id=subject)
        db_session.add(operator)
        db_session.flush()
        db_session.add(
            PlatformOperatorGrant(
                user_id=operator.id,
                granted_by_user_id=operator.id,
                permission="AI_ANALYSIS_MANAGE",
                status="ACTIVE",
            )
        )
        db_session.commit()

    identity = AuthenticatedIdentity(
        subject=subject,
        email="health-security-test@example.com",
        claims={"sub": subject, "role": "authenticated"},
    )

    gs = asettings.model_copy(update={"ai_provider": "gemini", "ai_model": "gemini-test", "ai_api_key": SecretStr(SECRET)})
    with TestClient(create_app(gs, session_factory=session_factory, collector_factory=source)) as c:
        h = c.get("/health").json()["ai_analysis_worker"]
        assert h["ai_provider_configured"] is True and h["ai_provider"] == "gemini"                      # 50
        assert h["ai_analysis_worker_enabled"] is False and "ai_analysis_jobs_blocked" in h
        from tests.conftest import sign_in
        sign_in(c.app)
        st = c.get("/api/stats").json()
        c.app.dependency_overrides.clear()
        assert st["ai_provider_configured"] is True and st["ai_analysis"]["ai_model"] == "gemini-test"   # 51
        assert "total_tenders" in st and "field_extraction" in st          # existing contract intact
        c.app.dependency_overrides[get_current_user] = lambda: identity
        try:
            worker_response = c.get("/api/ai-analysis/worker")
            assert worker_response.status_code == 200
            w = worker_response.json()
        finally:
            c.app.dependency_overrides.pop(get_current_user, None)
        for body in (json.dumps(h), json.dumps(st), json.dumps(w)):
            assert SECRET not in body and "api_key" not in body.lower()
    with TestClient(create_app(asettings.model_copy(update={"ai_provider": ""}), session_factory=session_factory,
                               collector_factory=source)) as c:
        assert c.get("/health").json()["ai_analysis_worker"]["ai_provider_configured"] is False


# ===========================================================================
# 52-56. end-to-end source immutability, no network, no seller eligibility
# ===========================================================================
def test_end_to_end_pdf_to_stage3c_sources_untouched(asettings, session_factory, clock, db):
    """Generated PDF -> Stage 3A -> hook -> Stage 3B worker -> hook -> Stage 3C worker (mock)."""
    from app.extraction.service import ExtractionService
    from app.fields.job_worker import FieldExtractionJobWorker
    from tests.pdf_factory import gem_like_pdf
    from tests.test_stage3a_extraction import store_version

    on = asettings.model_copy(update={"ai_analysis_auto_queue": True})
    v = store_version(db, on, gem_like_pdf())
    pdf = on.resolved_document_storage_path / v.storage_path
    sha_before = hashlib.sha256(pdf.read_bytes()).hexdigest()
    out3a = ExtractionService(on, session_factory, use_default_ocr=False).extract_version(v.id)
    s3b = FieldExtractionJobWorker(on, session_factory).run_batch().jobs[0].field_extraction_id
    fresh(db)
    d3a, d3b = stage3a_digest(db, out3a.extraction_id), stage3b_digest(db, s3b)
    db.rollback()
    mock = MockProvider()
    j = AIAnalysisJobWorker(on, session_factory, service(on, session_factory, clock, mock), clock=clock).run_batch()
    assert j.jobs[0].status in ("SUCCESS", "PARTIAL_SUCCESS") and j.jobs[0].analysis_run_id
    assert hashlib.sha256(pdf.read_bytes()).hexdigest() == sha_before == v.sha256                         # 52
    assert stage3a_digest(db, out3a.extraction_id) == d3a                                                 # 53
    assert stage3b_digest(db, s3b) == d3b                                                                 # 54
    sent = mock.requests[0]
    for forbidden in (str(on.resolved_document_storage_path), str(PROJECT_ROOT), "sqlite", v.storage_path):
        assert forbidden not in sent.user and forbidden not in sent.system          # privacy: no paths / DB info


def test_no_seller_eligibility_verdicts(asettings, session_factory, clock, db):
    s3b = stage3b_run(db, asettings, session_factory)
    svc0 = service(asettings, session_factory, clock)
    iso = chunk_key(svc0, s3b, ISO_Q)
    resp = envelope(
        req("ISO", "MANDATORY", iso, ISO_Q, summary="You are not eligible because you lack ISO 9001."),
        req("ISO", "MANDATORY", iso, ISO_Q, title="Seller is eligible."),
        req("ISO", "MANDATORY", iso, ISO_Q, title="ISO 9001 certification required for bidder or OEM"),
        summary="Eligibility result: FAIL")
    _, _, _, out = analyze_with(asettings, session_factory, clock, db, [resp], s3b=s3b)
    rows = reqs_of(db, out.analysis_run_id)
    assert [r.title for r in rows] == ["ISO 9001 certification required for bidder or OEM"]               # 56
    run = db.get(AIAnalysisRun, out.analysis_run_id)
    assert "withheld" in run.summary
    assert [r["reason"] for r in json.loads(run.rejected_json)].count("SELLER_ELIGIBILITY_VERDICT") == 3
    cols = {c.name for m in (AIAnalysisRun, AIRequirement, AIAnalysisFlag) for c in m.__table__.columns}
    assert not any(w in c for c in cols for w in ("eligible", "pass", "fail", "verdict", "score", "rank"))
    from app.ai.prompt import SYSTEM_PROMPT
    assert "must NOT judge any bidder" in SYSTEM_PROMPT and "Use ONLY the supplied evidence_chunks" in SYSTEM_PROMPT


# ===========================================================================
# Hardening (independent review findings)
# ===========================================================================
def test_quote_rules_tiny_and_fragmented_quotes_never_ground():
    chunk = "The bidder shall provide the documents listed below within 10 days of award."
    assert quote_in_chunk("the", chunk) is None                                   # tiny quote
    assert quote_in_chunk("bidder shall", chunk) is None                         # < 20 chars / 4 words
    assert quote_in_chunk("The bidder shall provide the documents", chunk) == 0
    assert quote_in_chunk("bidder shall provide ... within 10 days of award", chunk) is not None
    assert quote_in_chunk("bidder shall provide ... the ... within 10 days", chunk) is None   # short fragment
    assert quote_in_chunk("a b ... c d ... e f ... g h ... i j", chunk) is None              # too many fragments
    assert quote_in_chunk("Required: No", "[EMD Detail]\nRequired: No") is not None   # covers a tiny chunk
    assert quote_in_chunk("the documents listed below within 10 days of award. Extra", chunk) is None


def test_grounding_hardening_table_wording_and_verdict_fields(asettings, session_factory, clock, db):
    s3b = stage3b_run(db, asettings, session_factory)
    svc0 = service(asettings, session_factory, clock)
    table = chunk_key(svc0, s3b, "Bid to RA enabled")
    iso = chunk_key(svc0, s3b, ISO_Q)
    resp = envelope(
        req("OTHER", "MANDATORY", table, "Bid to RA enabled: No", title="RA"),   # table line has no obligation word
        req("ISO", "MANDATORY", iso, "the", title="tiny"),                       # tiny quote -> rejected
        req("ISO", "CONDITIONAL", iso, ISO_Q, condition="You are not eligible unless certified."),
        req("ISO", "MANDATORY", iso, ISO_Q, ambiguity="Your firm is ineligible."),
        ambiguities=[{"description": "You are not eligible.", "evidence": [{"chunk_id": iso, "quote": ISO_Q}]}])
    _, _, _, out = analyze_with(asettings, session_factory, clock, db, [resp], s3b=s3b)
    rows = reqs_of(db, out.analysis_run_id)
    assert [(r.title, r.obligation_level, r.level_adjustment) for r in rows] == [
        ("RA", "UNKNOWN", "NO_OBLIGATION_WORDING")]
    reasons = [r["reason"] for r in json.loads(db.get(AIAnalysisRun, out.analysis_run_id).rejected_json)]
    assert reasons.count("SELLER_ELIGIBILITY_VERDICT") == 3 and "QUOTE_NOT_IN_EVIDENCE" in reasons


def test_bad_key_or_base_url_is_configuration_not_retried(asettings, session_factory, clock, db, caplog):
    caplog.set_level(logging.DEBUG)
    stripped = asettings.model_copy(update={"ai_provider": "gemini", "ai_model": "m",
                                            "ai_api_key": SecretStr("  myGeminiSecret12345\n")})
    assert build_provider(stripped)._key == "myGeminiSecret12345"            # surrounding whitespace removed
    for bad in ({"ai_api_key": SecretStr("myGemini\nSecret12345")}, {"ai_api_key": SecretStr("ключ-секрет-123")},
                {"ai_api_key": SecretStr(SECRET), "ai_base_url": "generativelanguage.googleapis.com"},
                {"ai_api_key": SecretStr(SECRET), "ai_base_url": "ftp://example.org/v1"}):
        st = asettings.model_copy(update={"ai_provider": "gemini", "ai_model": "gemini-test", **bad})
        with pytest.raises(ProviderConfigError):
            build_provider(st)
        assert not provider_configured(st)
    s3b = stage3b_run(db, asettings, session_factory)
    st = asettings.model_copy(update={"ai_provider": "gemini", "ai_model": "m", "ai_api_key": SecretStr("x" * 12),
                                      "ai_base_url": "ftp://bad"})
    enqueue_ai_analysis(db, s3b, AIJobReason.MANUAL, st)
    db.commit()
    b = AIAnalysisJobWorker(st, session_factory, AnalysisService(st, session_factory, clock=clock),
                            clock=clock).run_batch()
    assert b.processed == 0 and b.skipped_reason == SKIP_NOT_CONFIGURED       # nothing claimed, nothing called
    from app.ai.redact import redact
    msg = "Illegal header value b'myGeminiSecret12345\\n'"
    assert "myGeminiSecret12345" not in redact(msg, "myGeminiSecret12345\n")
    assert "myGeminiSecret12345" not in caplog.text


def test_non_finite_and_hostile_json_rejected():
    for raw in ('{"summary": "x", "requirements": [{"value": NaN}]}', "[" * 100000,
                '{"summary": "x", "n": ' + "9" * 5000 + "}"):
        with pytest.raises(ResponseInvalid) as exc:
            parse_envelope(raw)
        assert exc.value.code == "MALFORMED_JSON"


def test_zone_markers_when_headings_are_not_placed(db):
    from tests.stage3a_rows import BASE_SECTIONS
    no_atc_heading = [s for s in BASE_SECTIONS if s[3] not in ("buyer added bid specific terms and conditions",
                                                               "disclaimer")]
    e = make_stage3a(db, sections=no_atc_heading)
    src = load_source(db, e.id)
    db.rollback()
    chunks = build_chunks(src, max_chunk_chars=3000)
    atc = [c for c in chunks if c.kind == "BUYER_ATC"]
    boiler = [c for c in chunks if c.kind == "BOILERPLATE"]
    assert any(WARRANTY_Q in c.text for c in atc) and any(ISO_Q in c.text for c in atc)
    assert boiler and all("ISO 14001" not in c.text for c in atc)     # GeM disclaimer never joins the ATC
    assert any("ISO 14001" in c.text for c in boiler)


def test_daily_cap_counts_every_provider_call(asettings, session_factory, clock, db):
    from app.database.models import AIProviderCall
    s3b = stage3b_run(db, asettings, session_factory)
    capped = asettings.model_copy(update={"ai_max_analyses_per_day": 2, "ai_max_retries": 3})
    mock = MockProvider(responses=[ProviderTimeout("t")] * 10)
    svc = service(capped, session_factory, clock, mock)
    res = enqueue_ai_analysis(db, s3b, AIJobReason.MANUAL, capped)
    db.commit()
    w = AIAnalysisJobWorker(capped, session_factory, svc, clock=clock)
    j = w.run_batch().jobs[0]
    assert len(mock.requests) == 2 and (j.status, j.error_code) == ("RETRY", "DAILY_LIMIT_REACHED")
    fresh(db)
    calls = db.scalars(select(AIProviderCall)).all()
    assert [(c.job_id, c.attempt, c.status) for c in calls] == [(res.job_id, 1, "PROVIDER_TIMEOUT"),
                                                                (res.job_id, 2, "PROVIDER_TIMEOUT")]
    clock.advance(minutes=11)
    b = w.run_batch()
    assert b.processed == 0 and b.skipped_reason == SKIP_DAILY_LIMIT and len(mock.requests) == 2
    clock.advance(hours=25)
    mock.responses = [envelope()]
    assert w.run_batch().jobs[0].status == "SUCCESS"


def test_blocked_cooldown_persists_across_processes_but_explicit_run_allowed(asettings, session_factory, clock,
                                                                              db):
    a = stage3b_run(db, asettings, session_factory, bid="GEM/2026/B/9300001")
    b = stage3b_run(db, asettings, session_factory, bid="GEM/2026/B/9300002")
    for i in (a, b):
        enqueue_ai_analysis(db, i, AIJobReason.MANUAL, asettings)
    db.commit()
    first = AIAnalysisJobWorker(asettings, session_factory, service(
        asettings, session_factory, clock, MockProvider(responses=[ProviderAuthError("401")])), clock=clock)
    assert first.run_batch().jobs[0].status == "BLOCKED"
    mock = MockProvider(responses=[envelope()])
    second = AIAnalysisJobWorker(asettings, session_factory, service(asettings, session_factory, clock, mock),
                                 clock=clock)                                    # e.g. the next CLI process
    batch = second.run_batch()
    assert batch.processed == 0 and batch.skipped_reason == SKIP_BLOCKED and not mock.requests
    fresh(db)
    pending = db.scalar(select(AIAnalysisJob).where(AIAnalysisJob.status == "PENDING"))
    j = second.run_batch(job_id=pending.id).jobs[0]                             # explicit request by a person
    assert j.status == "SUCCESS" and len(mock.requests) == 1


def test_persist_failure_never_leaves_job_running(asettings, session_factory, clock, db, monkeypatch):
    s3b = stage3b_run(db, asettings, session_factory)
    res = enqueue_ai_analysis(db, s3b, AIJobReason.MANUAL, asettings)
    db.commit()
    svc = service(asettings, session_factory, clock, MockProvider(responses=[envelope()]))

    def broken(*a, **k):
        raise RuntimeError("disk full")

    monkeypatch.setattr(svc, "persist", broken)
    j = AIAnalysisJobWorker(asettings, session_factory, svc, clock=clock).run_batch().jobs[0]
    fresh(db)
    job = db.get(AIAnalysisJob, res.job_id)
    assert (j.status, job.status, job.locked_by, job.error_code) == ("RETRY", "RETRY", None, "ENGINE_ERROR")
    assert db.scalar(select(func.count()).select_from(AIAnalysisRun)) == 0


def test_analyses_of_superseded_stage3b_runs_are_not_listed_as_current(authorized_ai_api, asettings, session_factory, clock, db):
    api = authorized_ai_api
    fx = FieldExtractionService(asettings, session_factory)
    e = make_stage3a(db)
    old = fx.extract(e.id).field_extraction_id
    assert service(asettings, session_factory, clock).analyze(old).outcome == ANALYZED
    assert api.get("/api/ai-analysis").json()["total"] == 1
    new = fx.extract(e.id, force=True).field_extraction_id                      # Stage 3B re-extracted
    assert new != old
    assert api.get("/api/ai-analysis").json()["total"] == 0
    assert api.get("/api/ai-analysis", params={"current_only": False}).json()["total"] == 1
    assert api.get("/api/ai-analysis/bid/GEM/2026/B/8124821").json()["items"] == []
    st = api.get("/api/ai-analysis/worker").json()
    assert st["ai_analyses_total"] == 0 and st["stage3b_runs_without_analysis"] == 1
