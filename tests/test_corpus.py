"""Offline acceptance of provenance -> acquisition -> extraction -> corpus -> mock AI."""

import hashlib, json, socket, sqlite3, shutil
from pathlib import Path
import httpx, pytest
from sqlalchemy import select, func
from app.core.config import Settings
from app.database.models import *
from app.documents.documents_service import DocumentsService
from app.documents.references import (
    ReferenceDiscovery,
    pdf_links,
    classify_reference,
    RULES_VERSION,
)
from app.documents.reference_security import AutomaticURLPolicy, canonical_url
from app.documents.downloader import (
    DocumentDownloader,
    URLValidationError,
    DownloadError,
)
from app.corpus.service import build_corpus
from app.corpus.queue import enqueue_corpus
from app.corpus.analysis import prepare_corpus
from app.ai.service import AnalysisService
from app.ai.job_worker import AIAnalysisJobWorker
from app.ai.providers.mock import MockProvider
from app.extraction.service import ExtractionService
from app.fields.service import FieldExtractionService
from app.utils.dates import utcnow
from tests.pdf_factory import PdfBuilder, text_pdf

MAIN = "https://bidplus.gem.gov.in/showbidDocument/9994214"
SPEC = "https://mkp.gem.gov.in/catalog_data/catalog_support_document/buyer_documents/a/CatalogAttrs/SpecificationDocument/spec.pdf"
OM = "https://bidplus.gem.gov.in/bidding/downloadOmppdfile/"
GTC = "https://admin.gem.gov.in/apis/v1/gtc/pdfByDate/?date=20261006"


def public_dns(*a, **k):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443))]


def source_pdf(links=(SPEC, OM, GTC)):
    b = PdfBuilder()
    for n in range(1, 7):
        p = b.page()
        p.text(40, 40, "Bid Number: GEM/2026/B/8124821")
        p.text(40, 60, "The supplier shall provide warranty for 1 year.")
        if n in (3, 6):
            p.text(40, 80, "Technical Specifications - Buyer Specification Document")
            for i, url in enumerate(url for url in links if (url == GTC) == (n == 6)):
                p.text(40, 110 + i * 40, "Download" if url == SPEC else "Reference")
                p.link(url, top=110 + i * 40)
    return b.build()


def seed(db, tmp_path, settings, content=None):
    cfg = settings.model_copy(
        update={
            "document_storage_path": str(tmp_path / "tenders"),
            "ai_provider": "mock",
            "ai_analysis_auto_queue": False,
            "document_request_delay_seconds": 0,
            "document_max_retries": 0,
            "ai_max_input_characters": 100000,
            "ai_max_chunks_per_analysis": 100,
        }
    )
    t = Tender(
        bid_number="GEM/2026/B/8124821",
        source_url=MAIN,
        status="ACTIVE",
        source_fingerprint="x",
        first_seen_at=utcnow(),
        last_seen_at=utcnow(),
    )
    db.add(t)
    db.flush()
    d = TenderDocument(
        tender_id=t.id,
        document_key="main_bid",
        document_type="MAIN_BID",
        source_url=MAIN,
    )
    db.add(d)
    db.flush()
    data = content or source_pdf()
    root = cfg.resolved_document_storage_path
    root.mkdir(parents=True)
    (root / "main.pdf").write_bytes(data)
    v = DocumentVersion(
        document_id=d.id,
        version_number=1,
        sha256=hashlib.sha256(data).hexdigest(),
        file_size=len(data),
        extension="pdf",
        mime_type="application/pdf",
        storage_path="main.pdf",
        source_url=MAIN,
        validation_status="VALID",
    )
    db.add(v)
    db.flush()
    d.current_version_id = v.id
    db.commit()
    return cfg, t, v


def extract_all(db, cfg, factory, tid):
    ids = list(
        db.scalars(
            select(DocumentVersion.id)
            .join(TenderDocument, DocumentVersion.document_id == TenderDocument.id)
            .where(TenderDocument.tender_id == tid)
        )
    )
    db.commit()
    for vid in ids:
        a = ExtractionService(cfg, factory).extract_version(vid)
        assert a.extraction_id
        assert (
            FieldExtractionService(cfg, factory)
            .extract(a.extraction_id)
            .field_extraction_id
        )
    db.expire_all()


def test_annotation_anchor_context_and_classification(tmp_path):
    p = tmp_path / "main.pdf"
    p.write_bytes(source_pdf())
    links, over = pdf_links(p, 10)
    assert not over and len(links) == 3
    spec = next(l for l in links if l.url == SPEC)
    assert (
        spec.page == 3
        and "Download" in spec.anchor
        and "Buyer Specification Document" in spec.context
    )
    assert classify_reference(SPEC)[0:2] == ("TENDER_DOCUMENT", "SPECIFICATION")
    assert classify_reference(OM)[0] == "POLICY_REFERENCE"
    assert classify_reference(GTC)[0] == "GTC_REFERENCE"
    assert next(l.page for l in links if l.url == GTC) == 6
    assert not classify_reference("https://example.com/unknown.pdf")[2]


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost/a",
        "https://127.0.0.1/a",
        "https://[::1]/a",
        "https://10.1.2.3/a",
        "https://172.16.0.1/a",
        "https://192.168.1.1/a",
        "https://169.254.1.1/a",
        "file:///a",
        "ftp://mkp.gem.gov.in/a",
        "javascript:alert(1)",
        "https://user:password@mkp.gem.gov.in/a",
        "https://evilgem.gov.in/a",
        "https://gem.gov.in.attacker.com/a",
        "https://mkp.gem.gov.in.attacker.com/a",
        "https://example.com/a",
        "http://mkp.gem.gov.in/a",
        "https://mkp.gem.gov.in:8443/a",
    ],
)
def test_automatic_url_rejects(url, settings):
    with pytest.raises(URLValidationError):
        AutomaticURLPolicy(settings, public_dns).validate(url)


@pytest.mark.parametrize(
    "ip",
    [
        "127.0.0.1",
        "10.0.0.1",
        "172.16.0.1",
        "192.168.0.1",
        "169.254.0.1",
        "::1",
        "fe80::1",
        "fc00::1",
        "0.0.0.0",
        "224.0.0.1",
        "240.0.0.1",
    ],
)
def test_dns_nonpublic_rejected(ip, settings):
    dns = lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 443))]
    with pytest.raises(URLValidationError):
        AutomaticURLPolicy(settings, dns).validate(SPEC)


def test_public_allowlist_fragment(settings):
    assert AutomaticURLPolicy(settings, public_dns).validate(SPEC + "#page=2") == SPEC
    assert canonical_url(SPEC + "#x") == canonical_url(SPEC + "#y")


@pytest.mark.parametrize(
    "target",
    ["https://example.com/a", "https://127.0.0.1/a", "https://mkp.gem.gov.in/private"],
)
def test_redirect_validation(target, settings, tmp_path):
    calls = []

    def handler(r):
        calls.append(str(r.url))
        return httpx.Response(302, headers={"Location": target})

    dns = lambda host, *a, **k: (
        public_dns()
        if host == "bidplus.gem.gov.in"
        else [(2, 1, 6, "", ("10.0.0.1", 443))]
    )
    dl = DocumentDownloader(
        settings,
        transport=httpx.MockTransport(handler),
        url_policy=AutomaticURLPolicy(settings, dns),
        sleep=lambda x: None,
    )
    with pytest.raises(URLValidationError):
        dl.fetch(MAIN, tmp_path)
    assert calls == [MAIN]


@pytest.mark.parametrize("mode", ["loop", "chain", "oversize", "signature"])
def test_download_limits(mode, settings, tmp_path):
    count = []

    def handler(r):
        count.append(1)
        if mode in {"loop", "chain"}:
            return httpx.Response(
                302,
                headers={
                    "Location": MAIN
                    if mode == "loop"
                    else MAIN + "?n=" + str(len(count))
                },
            )
        if mode == "oversize":
            return httpx.Response(
                200,
                content=b"%PDF-1.4",
                headers={
                    "content-length": "999999999",
                    "content-type": "application/pdf",
                },
            )
        return httpx.Response(
            200, content=b"not PDF", headers={"content-type": "application/pdf"}
        )

    dl = DocumentDownloader(
        settings,
        transport=httpx.MockTransport(handler),
        url_policy=AutomaticURLPolicy(settings, public_dns),
        sleep=lambda x: None,
    )
    with pytest.raises(DownloadError):
        dl.fetch(MAIN, tmp_path, filename_hint="a.pdf")
    assert len(count) <= 6


def test_complete_multi_document_mock(db, settings, session_factory, tmp_path):
    cfg, t, v = seed(db, tmp_path, settings)
    requested = []

    def handler(r):
        requested.append(str(r.url))
        return httpx.Response(
            200,
            content=text_pdf(
                [
                    [
                        "Technical Specifications",
                        "The supplier shall provide warranty for 3 years.",
                    ]
                ]
            ),
            headers={"content-type": "application/pdf"},
        )

    svc = DocumentsService(
        cfg, transport=httpx.MockTransport(handler), sleep=lambda x: None
    )
    discovery = ReferenceDiscovery(svc, resolver=public_dns)
    discovery.run(db, t)
    assert requested == [SPEC]
    refs = list(db.scalars(select(DocumentReference)))
    assert len(refs) == 3
    ref = next(r for r in refs if r.corpus_relevant)
    assert (
        ref.source_version_id == v.id
        and ref.page_number == 3
        and ref.status == "ACQUIRED"
    )
    assert (
        db.get(TenderDocument, ref.target_document_id).document_type == "SPECIFICATION"
    )
    assert db.scalar(
        select(ExtractionJob.id).where(
            ExtractionJob.document_version_id == ref.target_version_id
        )
    )
    discovery.run(db, t)
    assert (
        requested == [SPEC]
        and db.scalar(select(func.count()).select_from(DocumentReference)) == 3
    )
    extract_all(db, cfg, session_factory, t.id)
    corpus = build_corpus(db, t.id)
    assert (
        corpus["complete"]
        and len(corpus["documents"]) == 2
        and corpus["excluded_generic_reference_count"] == 2
    )
    fp = corpus["fingerprint"]
    db.commit()
    mock = MockProvider()
    ai = AnalysisService(cfg, session_factory, provider_factory=lambda: mock)
    p = prepare_corpus(ai, t.id)
    assert len(p.sources) == 2 and len({c.key for c in p.chunks.chunks}) == len(
        p.chunks.chunks
    )
    assert any(c.key.startswith("D2-") for c in p.chunks.sent)
    call = ai.call(p)
    assert call.error is None
    it = ai.interpret(p, call.response)
    with session_factory() as s:
        rid = ai.persist(s, p, call, it)
        s.commit()
    db.expire_all()
    run = db.get(AIAnalysisRun, rid)
    assert run.analysis_scope == "TENDER_CORPUS" and run.corpus_fingerprint == fp
    chunks = list(
        db.scalars(
            select(AIEvidenceChunk).where(AIEvidenceChunk.analysis_run_id == rid)
        )
    )
    assert len({c.document_version_id for c in chunks}) == 2
    assert (
        db.scalar(
            select(func.count())
            .select_from(AIAnalysisRunSource)
            .where(AIAnalysisRunSource.analysis_run_id == rid)
        )
        == 2
    )
    assert any(
        f.flag_type == "CROSS_DOCUMENT_CONFLICT"
        for f in db.scalars(
            select(AIAnalysisFlag).where(AIAnalysisFlag.analysis_run_id == rid)
        )
    )
    assert not enqueue_corpus(db, t.id, cfg).created
    from app.api.ai_analysis import get_analysis
    from app.api.corpus import inspect_corpus

    output = get_analysis(rid, db)
    assert output["current_for_corpus"] is True
    for requirement in output["requirements"]:
        for evidence in requirement["evidence"]:
            chunk = next(c for c in chunks if c.chunk_key == evidence["chunk_id"])
            assert evidence["document_version_id"] == chunk.document_version_id
            assert evidence["stage3b_extraction_id"] is not None
    assert inspect_corpus(t.id, db)["analyses"][0]["current_for_corpus"]


def test_missing_document_flags_and_idempotency(
    db, settings, session_factory, tmp_path
):
    cfg, t, v = seed(db, tmp_path, settings)
    svc = DocumentsService(
        cfg,
        transport=httpx.MockTransport(lambda r: httpx.Response(403)),
        sleep=lambda x: None,
    )
    discovery = ReferenceDiscovery(svc, resolver=public_dns)
    discovery.run(db, t)
    extract_all(db, cfg, session_factory, t.id)
    corpus = build_corpus(db, t.id)
    assert not corpus["complete"] and corpus["missing_reference_count"] == 1
    a = enqueue_corpus(db, t.id, cfg)
    db.commit()
    assert a.created
    assert not enqueue_corpus(db, t.id, cfg).created
    db.commit()
    batch = AIAnalysisJobWorker(cfg, session_factory).run_batch(job_id=a.job_id)
    assert batch.jobs[0].status == "PARTIAL_SUCCESS"
    db.expire_all()
    rid = batch.jobs[0].analysis_run_id
    flags = {
        f.flag_type
        for f in db.scalars(
            select(AIAnalysisFlag).where(AIAnalysisFlag.analysis_run_id == rid)
        )
    }
    assert {"MISSING_REFERENCED_DOCUMENT", "ANALYSIS_INCOMPLETE"} <= flags
    db.commit()
    assert not enqueue_corpus(db, t.id, cfg).created


def test_fingerprint_metadata_stability_and_relevant_changes(
    db, settings, session_factory, tmp_path
):
    cfg, t, v = seed(db, tmp_path, settings)
    ReferenceDiscovery(DocumentsService(cfg), resolver=public_dns).run(
        db, t, acquire=False
    )
    extract_all(db, cfg, session_factory, t.id)
    one = build_corpus(db, t.id)["fingerprint"]
    generic = db.scalar(
        select(DocumentReference).where(
            DocumentReference.category == "POLICY_REFERENCE"
        )
    )
    generic.reason = "extra audit note"
    generic.status = "AUDITED"
    generic.last_seen_at = utcnow()
    db.commit()
    assert build_corpus(db, t.id)["fingerprint"] == one
    relevant = db.scalar(
        select(DocumentReference).where(DocumentReference.corpus_relevant.is_(True))
    )
    relevant.status = "DOWNLOAD_FAILED"
    db.commit()
    two = build_corpus(db, t.id)["fingerprint"]
    assert two != one
    page = db.scalar(select(DocumentPage))
    page.normalized_text += "\nThe supplier must deliver within 10 days."
    db.commit()
    assert build_corpus(db, t.id)["fingerprint"] != two


def test_recursion_cycle_and_depth(db, settings, tmp_path):
    # B links to itself and another buyer document; no repeated work.
    second = SPEC.replace("spec.pdf", "annex.pdf")
    cfg, t, v = seed(db, tmp_path, settings, source_pdf((SPEC,)))
    calls = []

    def handler(r):
        url = str(r.url)
        calls.append(url)
        return httpx.Response(
            200,
            content=source_pdf((SPEC, second)) if url == SPEC else source_pdf((SPEC,)),
            headers={"content-type": "application/pdf"},
        )

    d = ReferenceDiscovery(
        DocumentsService(
            cfg, transport=httpx.MockTransport(handler), sleep=lambda x: None
        ),
        resolver=public_dns,
    )
    d.run(db, t)
    assert calls == [SPEC, second]
    assert db.scalar(select(func.count()).select_from(DocumentVersion)) == 3


@pytest.mark.parametrize(
    "setting,value",
    [
        ("document_reference_max_depth", 0),
        ("document_reference_max_per_document", 1),
        ("document_reference_max_per_tender", 1),
        ("document_reference_max_acquisitions", 1),
    ],
)
def test_limits_never_complete(setting, value, db, settings, tmp_path):
    cfg, t, v = seed(
        db,
        tmp_path,
        settings,
        source_pdf((SPEC, OM, GTC, SPEC.replace("spec.pdf", "two.pdf"))),
    )
    cfg = cfg.model_copy(update={setting: value})
    d = ReferenceDiscovery(
        DocumentsService(
            cfg,
            transport=httpx.MockTransport(
                lambda r: httpx.Response(
                    200,
                    content=text_pdf([["Technical specification"]]),
                    headers={"content-type": "application/pdf"},
                )
            ),
            sleep=lambda x: None,
        ),
        resolver=public_dns,
    )
    d.run(db, t)
    assert not build_corpus(db, t.id)["complete"]
    if setting in {
        "document_reference_max_per_document",
        "document_reference_max_per_tender",
    }:
        assert db.get(DocumentReferenceScan, v.id).status == "LIMIT_REACHED"
    else:
        assert any(
            r.status == "LIMIT_REACHED" for r in db.scalars(select(DocumentReference))
        )


def test_hindi_and_network_guard():
    from app.ai.chunker import clean_line

    assert (
        clean_line("विक्रेता को तीन वर्ष की वारंटी देनी होगी।")
        == "विक्रेता को तीन वर्ष की वारंटी देनी होगी।"
    )
    assert clean_line("3 / 6") == ""
    a, b = socket.socketpair()
    a.close()
    b.close()
    with socket.socket() as s, pytest.raises(AssertionError):
        s.connect(("8.8.8.8", 443))
    with pytest.raises(AssertionError):
        socket.getaddrinfo("example.com", 443)


def test_0007_fresh_and_existing_database_integrity(tmp_path):
    """Upgrading an existing pre-0007 database to head preserves every existing row and
    column and leaves no dangling foreign keys. Fresh databases also survive a
    downgrade/upgrade cycle. (Built from fixtures; never copies a real database.)"""
    from alembic import command
    from tests.test_stage2b_migration_cli import alembic_cfg, seed_0002

    existing = tmp_path / "existing.db"
    seed_0002(existing)                                   # Stage 1/2 rows written at revision 0002
    command.upgrade(alembic_cfg(existing), "0006_stage3c_ai_analysis")
    con = sqlite3.connect(existing)
    names = [r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name != 'alembic_version'")]
    before = {name: con.execute(f'SELECT * FROM "{name}"').fetchall() for name in names}
    cols = {name: [r[1] for r in con.execute(f'PRAGMA table_info("{name}")')] for name in names}
    con.close()
    assert sum(len(rows) for rows in before.values()) > 0

    command.upgrade(alembic_cfg(existing), "head")
    con = sqlite3.connect(existing)
    for name in names:
        columns = ",".join('"' + n + '"' for n in cols[name])
        assert con.execute(f'SELECT {columns} FROM "{name}"').fetchall() == before[name], name
    assert con.execute("PRAGMA foreign_key_check").fetchall() == []
    con.close()

    fresh = tmp_path / "fresh.db"
    cfg = alembic_cfg(fresh)
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "0006_stage3c_ai_analysis")
    command.upgrade(cfg, "head")


def test_reanalysis_when_reference_state_changes(
    db, settings, session_factory, tmp_path
):
    cfg, t, v = seed(db, tmp_path, settings)
    ReferenceDiscovery(DocumentsService(cfg), resolver=public_dns).run(
        db, t, acquire=False
    )
    extract_all(db, cfg, session_factory, t.id)
    one = enqueue_corpus(db, t.id, cfg)
    db.commit()
    r = db.scalar(
        select(DocumentReference).where(DocumentReference.corpus_relevant.is_(True))
    )
    r.status = "DOWNLOAD_FAILED"
    db.commit()
    two = enqueue_corpus(db, t.id, cfg)
    db.commit()
    assert two.created and one.job_id != two.job_id
    w = AIAnalysisJobWorker(cfg, session_factory)
    old = w.run_batch(job_id=one.job_id)
    assert old.jobs[0].error_code == "CORPUS_SUPERSEDED"
    new = w.run_batch(job_id=two.job_id)
    assert new.jobs[0].analysis_run_id


def test_hallucinated_corpus_evidence_rejected(db, settings, session_factory, tmp_path):
    from app.ai.providers.base import AIResponse
    from tests.test_stage3c_ai import envelope, req

    cfg, t, v = seed(db, tmp_path, settings, source_pdf(()))
    ReferenceDiscovery(DocumentsService(cfg), resolver=public_dns).run(
        db, t, acquire=False
    )
    extract_all(db, cfg, session_factory, t.id)
    db.commit()
    ai = AnalysisService(cfg, session_factory)
    p = prepare_corpus(ai, t.id)
    text = envelope(
        req(
            "ISO",
            "MANDATORY",
            "D999-C1",
            "The bidder must have ISO 9001 certification.",
        )
    )
    # Use provider's response constructor to retain its normal metadata shape.
    response = ai.call(p).response
    response.text = json.dumps(text)
    it = ai.interpret(p, response)
    assert not it.grounded.requirements and it.grounded.rejected


def test_no_complete_claim_before_scan(db, settings, session_factory, tmp_path):
    cfg, t, v = seed(db, tmp_path, settings, source_pdf(()))
    extract_all(db, cfg, session_factory, t.id)
    assert not build_corpus(db, t.id)["complete"]
    ReferenceDiscovery(DocumentsService(cfg), resolver=public_dns).run(
        db, t, acquire=False
    )
    assert build_corpus(db, t.id)["complete"]


def test_equivalent_content_with_different_row_ids_has_same_fingerprint(
    db, settings, session_factory
):
    from tests.stage3a_rows import make_stage3a

    cfg = settings.model_copy(update={"ai_analysis_auto_queue": False})

    def make():
        e = make_stage3a(db)
        v = db.get(DocumentVersion, e.document_version_id)
        v.extension = "pdf"
        d = db.get(TenderDocument, e.document_id)
        d.current_version_id = v.id
        db.add(
            DocumentReferenceScan(
                document_version_id=v.id, status="COMPLETE", rules_version=RULES_VERSION
            )
        )
        db.commit()
        FieldExtractionService(cfg, session_factory).extract(e.id)
        db.expire_all()
        return d

    first = make()
    before = build_corpus(db, first.tender_id)["fingerprint"]
    db.commit()
    first.is_active = False
    db.commit()
    second = make()
    assert second.id != first.id
    assert build_corpus(db, second.tender_id)["fingerprint"] == before


def test_reference_refresh_creates_new_version_without_overwriting(
    db, settings, tmp_path
):
    cfg, t, v = seed(db, tmp_path, settings, source_pdf((SPEC,)))
    data = [text_pdf([["The supplier shall provide warranty for 1 year."]])]
    discovery = ReferenceDiscovery(
        DocumentsService(
            cfg,
            transport=httpx.MockTransport(
                lambda r: httpx.Response(
                    200, content=data[0], headers={"content-type": "application/pdf"}
                )
            ),
            sleep=lambda x: None,
        ),
        resolver=public_dns,
    )
    discovery.run(db, t)
    r = db.scalar(
        select(DocumentReference).where(DocumentReference.corpus_relevant.is_(True))
    )
    old = db.get(DocumentVersion, r.target_version_id)
    old_path = cfg.resolved_document_storage_path / old.storage_path
    old_bytes = old_path.read_bytes()
    data[0] = text_pdf([["The supplier shall provide warranty for 3 years."]])
    discovery.run(db, t, refresh_existing=True)
    db.expire_all()
    new = db.get(DocumentVersion, r.target_version_id)
    assert (
        new.id != old.id
        and new.version_number == 2
        and old_path.read_bytes() == old_bytes
    )


def test_unsupported_reference_is_visible(db, settings, tmp_path):
    import io, zipfile

    url = SPEC.replace(".pdf", ".xls")
    cfg, t, v = seed(db, tmp_path, settings, source_pdf((url,)))
    blob = io.BytesIO(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1legacy fixture")
    svc = DocumentsService(
        cfg,
        transport=httpx.MockTransport(
            lambda r: httpx.Response(
                200,
                content=blob.getvalue(),
                headers={
                    "content-type": "application/vnd.ms-excel"
                },
            )
        ),
        sleep=lambda x: None,
    )
    ReferenceDiscovery(svc, resolver=public_dns).run(db, t)
    corpus = build_corpus(db, t.id)
    assert not corpus["complete"]
    assert any(d["state"] == "INCOMPLETE_UNSUPPORTED" for d in corpus["documents"])


def test_deterministic_cross_document_values_retained(
    db, settings, session_factory, tmp_path
):
    cfg, t, v = seed(db, tmp_path, settings)
    svc = DocumentsService(
        cfg,
        transport=httpx.MockTransport(
            lambda r: httpx.Response(
                200,
                content=text_pdf([["Delivery period: 30 days"]]),
                headers={"content-type": "application/pdf"},
            )
        ),
        sleep=lambda x: None,
    )
    ReferenceDiscovery(svc, resolver=public_dns).run(db, t)
    extract_all(db, cfg, session_factory, t.id)
    runs = list(
        db.scalars(select(TenderFieldExtraction).order_by(TenderFieldExtraction.id))
    )
    for f, value in zip(runs, [15, 30]):
        row = db.scalar(
            select(TenderFieldValue).where(
                TenderFieldValue.field_extraction_id == f.id,
                TenderFieldValue.field_name == "delivery_days",
            )
        )
        if row is None:
            row = TenderFieldValue(
                field_extraction_id=f.id,
                tender_id=t.id,
                field_name="delivery_days",
                field_group="DELIVERY",
                value_type="NUMBER",
                status="RESOLVED",
            )
            db.add(row)
        row.status = "RESOLVED"
        row.value_text = str(value)
        row.value_number = value
        row.value_json = str(value)
        row.unit = "DAYS"
    db.commit()
    corpus = build_corpus(db, t.id)
    conflict = next(c for c in corpus["conflicts"] if c["field"] == "delivery_days")
    assert {c["value_number"] for c in conflict["candidates"]} == {15, 30}
    assert corpus["fields"]["delivery_days"]["primary"] is None
