"""Bounded, annotation-only reference discovery using the existing pdfplumber stack."""

from collections import deque
from dataclasses import dataclass
import hashlib
import re
from pathlib import Path
from urllib.parse import urlsplit
import pdfplumber
from sqlalchemy import select, func
from app.database.models import (
    DocumentReference,
    DocumentReferenceScan,
    DocumentVersion,
    TenderDocument,
)
from app.documents.classifier import classify_document
from app.documents.reference_security import (
    AutomaticURLPolicy,
    canonical_url,
    contains_credentials,
    fulfilment_attachment,
)
from app.documents.downloader import DocumentDownloader, URLValidationError
from app.schemas.documents import DocumentCandidate, DocumentType
from app.utils.dates import utcnow

RULES_VERSION = "document-uri-v5"


@dataclass
class Link:
    page: int
    url: str
    anchor: str
    context: str


def pdf_links(path, limit):
    """Return at most limit links plus an overflow marker. No plain-text URL following."""
    links = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            for a in page.hyperlinks:
                uri = a.get("uri")
                if not isinstance(uri, str) or not uri:
                    continue
                if len(links) >= limit:
                    return links, True
                box = (
                    max(0, a["x0"] - 2),
                    max(0, a["top"] - 2),
                    min(page.width, a["x1"] + 2),
                    min(page.height, a["bottom"] + 2),
                )
                anchor = page.crop(box).extract_text() or ""
                context = (
                    page.crop(
                        (
                            0,
                            max(0, a["top"] - 85),
                            page.width,
                            min(page.height, a["bottom"] + 25),
                        )
                    ).extract_text()
                    or ""
                )
                links.append(Link(page.page_number, uri, anchor[:1000], context[:4000]))
    return links, False


def classify_reference(url, anchor="", context=""):
    """Explicit conservative rules; extension alone never confers corpus membership."""
    try:
        p = urlsplit(url)
        host = (p.hostname or "").lower().rstrip(".")
        path = p.path.lower()
    except ValueError:
        return "BLOCKED_REFERENCE", "UNKNOWN", False
    wording = anchor + " " + context
    attachment=fulfilment_attachment(url)
    if attachment and not re.search(r'\b(?:comparison|unrelated|example)\b',wording,re.I):
        if re.search(r'\bATC\b|buyer added|terms\s*(?:&|and)\s*conditions|\bBOQ\b|specification|corrigend|annexure|quality assurance',wording,re.I):
            typ=classify_document(wording,attachment['filename']).value
            # Nearby boilerplate can mention "the bid document" before an explicit
            # buyer-uploaded ATC label. This endpoint always names an attachment.
            if re.search(r'\bATC\b|buyer\s+(?:added|uploaded)|additional\s+terms',wording,re.I):typ='ATC'
            if typ not in {'UNKNOWN','MAIN_BID'}:return 'TENDER_DOCUMENT',typ,True
    if host=='bidplus.gem.gov.in' and re.fullmatch(r'/resources/upload_nas/[^/]+/bidding/excel/bid-\d+/[a-z0-9_.-]+\.xlsx',path) and not re.search(r'\b(?:example|comparison|unrelated)\b',wording,re.I):
        if re.search(r'excel\s+upload\s+required|price\s+breakup|\bBOQ\b|bill\s+of\s+quantit',wording,re.I):
            return 'TENDER_DOCUMENT','BOQ',True
    if host=='bidplus.gem.gov.in' and re.fullmatch(r'/bidding/bid/showcatalogue/[a-z0-9_-]{10,}',path) and re.search(r'specification|technical|catalogue|catalog',wording,re.I):
        if re.search(r'for reference only|not part of bid requirements|general product catalogue',wording,re.I) and not re.search(r'bid requirement|technical specifications|as per',wording,re.I):
            return 'POLICY_REFERENCE','UNKNOWN',False
        return 'TENDER_DOCUMENT','SPECIFICATION',True
    if host == "bidplus.gem.gov.in" and re.fullmatch(
        r"/resources/upload_nas/[^/]+/bidding/biddoc/bid-\d+/[^/]+\.(?:pdf|docx|xlsx|csv|txt|png|jpe?g|doc|xls|zip)", path
    ):
        typ = classify_document(wording, Path(path).name).value
        if re.search(r"quality\s+assurance\s+plan", wording, re.I):
            typ = "TECHNICAL_DOCUMENT"
        if typ not in ("UNKNOWN", "MAIN_BID"):
            return "TENDER_DOCUMENT", typ, True
    if (
        host == "bidplus.gem.gov.in"
        and re.fullmatch(r"/showbiddocument/\d+/?", path)
        and re.search(r"\bGEM/\d{4}/B/\d+\b", wording, re.I)
        and re.search(
            r"refer(?:red)?\s+to|\bsee\b|\bcontains?\b|\bprovides?\b|"
            r"(?:available|provided|specified|contained)\s+in", wording, re.I
        )
        and re.search(
            r"technical\s+specification|eligibility|terms\s*(?:&|and)\s*conditions|"
            r"\bBOQ\b|\bATC\b|corrigend|annexure", wording, re.I
        )
    ):
        return "TENDER_DOCUMENT", "MAIN_BID", True
    if (
        host == "bidplus.gem.gov.in"
        and path.rstrip("/") == "/bidding/downloadomppdfile"
    ):
        return "POLICY_REFERENCE", "UNKNOWN", False
    if host == "admin.gem.gov.in" and path.rstrip("/") == "/apis/v1/gtc/pdfbydate":
        return "GTC_REFERENCE", "UNKNOWN", False
    if host == "mkp.gem.gov.in" and path.startswith(
        "/catalog_data/catalog_support_document/buyer_documents/"
    ):
        if "/catalogattrs/specificationdocument/" in path:
            return "TENDER_DOCUMENT", "SPECIFICATION", True
        typ = classify_document(anchor + " " + context, Path(path).name).value
        if typ not in ("UNKNOWN", "MAIN_BID"):
            return "TENDER_DOCUMENT", typ, True
        return "UNKNOWN_REFERENCE", "UNKNOWN", False
    # Other links need operator review; never infer a separate ATC from embedded text.
    if host not in {"bidplus.gem.gov.in", "mkp.gem.gov.in", "admin.gem.gov.in", "fulfilment.gem.gov.in"}:
        return "EXTERNAL_REFERENCE", "UNKNOWN", False
    return "UNKNOWN_REFERENCE", "UNKNOWN", False


class ReferenceDiscovery:
    def __init__(self, service, *, resolver=None):
        self.service = service
        self.settings = service.settings
        self.policy = AutomaticURLPolicy(self.settings, resolver)
        self.downloader = DocumentDownloader(
            self.settings,
            transport=service.downloader._transport,
            sleep=service.downloader._sleep,
            url_policy=self.policy,
        )

    def run(
        self, db, tender, *, acquire=True, retry_failed=False, refresh_existing=False
    ):
        cfg = self.settings
        if not cfg.document_reference_discovery_enabled:
            return {"status": "DISABLED", "acquisitions": 0}
        from app.database.session import reserve_sqlite_writer
        reserve_sqlite_writer(db, renew_read=True)
        # BFS and visited source versions prevent cycles. Existing roots include all active
        # supported tender documents so reference refresh never requires re-extraction.
        docs = list(
            db.scalars(
                select(TenderDocument).where(
                    TenderDocument.tender_id == tender.id,
                    TenderDocument.is_active.is_(True),
                )
            )
        )
        targeted = set(
            db.scalars(
                select(DocumentReference.target_document_id).where(
                    DocumentReference.tender_id == tender.id,
                    DocumentReference.target_document_id.is_not(None),
                )
            )
        )
        roots = [d for d in docs if d.id not in targeted]
        if not roots:
            roots = docs
        queue = deque((d.current_version_id, 0) for d in roots if d.current_version_id)
        visited = set()
        attempted = set()
        acquisitions = 0
        while queue:
            from app.database.session import reserve_sqlite_writer
            reserve_sqlite_writer(db)
            vid, depth = queue.popleft()
            if vid in visited:
                continue
            visited.add(vid)
            v = db.get(DocumentVersion, vid)
            d = db.get(TenderDocument, v.document_id)
            if not d.is_active or d.current_version_id != vid:
                continue
            scan = db.get(DocumentReferenceScan, vid)
            if scan is None:
                scan = DocumentReferenceScan(
                    document_version_id=vid,
                    status="PENDING",
                    rules_version=RULES_VERSION,
                )
                db.add(scan)
            scan.scanned_at = utcnow()
            scan.rules_version = RULES_VERSION
            path = self.service._resolve_storage_path(v.storage_path or "")
            if (
                not path
                or not path.is_file()
                or self.service._sha256_of(path) != v.sha256
            ):
                scan.status = "FAILED"
                scan.reason = "Source missing or integrity mismatch"
                db.commit()
                continue
            try:
                if v.extension=='pdf':links,overflow=pdf_links(path,cfg.document_reference_max_per_document)
                elif v.extension in {'docx','xlsx','csv','txt','png','jpg','jpeg','html'}:
                    from app.documents.formats import inspect_document
                    kind=inspect_document(path,expected=v.extension)
                    links=[];overflow=False
                    if kind in {'docx','xlsx','csv','txt'}:
                        from app.extraction.supporting import extract_supporting
                        record=extract_supporting(path,kind,cfg)
                        for page in record.pages:
                            for m in re.finditer(r'https?://[^\s<>"\x27]+',page.normalized_text):
                                if len(links)>=cfg.document_reference_max_per_document:overflow=True;break
                                links.append(Link(0,m.group(),m.group(),page.normalized_text[max(0,m.start()-300):m.end()+300]))
                else:
                    scan.status='UNSUPPORTED';scan.reason='UNSUPPORTED_DOCUMENT_TYPE';db.commit();continue
            except Exception:
                scan.status = "FAILED"
                scan.reason = "PDF annotation parsing failed"
                db.commit()
                continue
            scan.status = "LIMIT_REACHED" if overflow else "COMPLETE"
            scan.reason = "Per-document reference limit reached" if overflow else None
            db.commit()
            for link in links:
                reserve_sqlite_writer(db)
                category, typ, relevant = classify_reference(
                    link.url, link.anchor, link.context
                )
                attachment=fulfilment_attachment(link.url)
                if attachment and attachment['bid']!=tender.bid_number:
                    parents=db.scalars(select(DocumentReference).where(DocumentReference.target_document_id==d.id,DocumentReference.tender_id==tender.id)).all()
                    if not any(attachment['bid'].lower() in ((p.anchor_text or '')+' '+(p.context or '')).lower() for p in parents):
                        category,typ,relevant='UNKNOWN_REFERENCE','UNKNOWN',False
                blocked = False
                try:
                    url = canonical_url(link.url)
                    if relevant:
                        self.policy.validate(link.url, resolve=False)
                except (ValueError, URLValidationError):
                    url = link.url
                    blocked = True
                # Userinfo is never persisted; store a hash for audit, not credentials.
                try:
                    unsafe_info = contains_credentials(url)
                except ValueError:
                    unsafe_info = True
                if unsafe_info:
                    url = "redacted:" + hashlib.sha256(url.encode()).hexdigest()
                    blocked = True
                key = hashlib.sha256(url.encode()).hexdigest()
                r = db.scalar(
                    select(DocumentReference).where(
                        DocumentReference.source_version_id == vid,
                        DocumentReference.page_number == link.page,
                        DocumentReference.url_sha256 == key,
                    )
                )
                if r is None:
                    count = db.scalar(
                        select(func.count())
                        .select_from(DocumentReference)
                        .where(DocumentReference.tender_id == tender.id)
                    )
                    if count >= cfg.document_reference_max_per_tender:
                        scan.status = "LIMIT_REACHED"
                        scan.reason = "Per-tender reference limit reached"
                        db.commit()
                        break
                    r = DocumentReference(
                        tender_id=tender.id,
                        source_document_id=d.id,
                        source_version_id=vid,
                        page_number=link.page,
                        anchor_text=link.anchor,
                        context=link.context,
                        original_url=url if unsafe_info else link.url,
                        canonical_url=url,
                        url_sha256=key,
                        category=category,
                        document_type=typ,
                        corpus_relevant=relevant,
                        depth=depth + 1,
                        status="PENDING" if relevant else "EXCLUDED",
                        reason=None if relevant else category,
                    )
                    db.add(r)
                else:
                    # Re-evaluate old exclusions when classifier rules change, retaining
                    # the same provenance row and successful acquisition pointers.
                    changed = (r.category, r.document_type, r.corpus_relevant) != (
                        category, typ, relevant
                    )
                    r.category, r.document_type, r.corpus_relevant = category, typ, relevant
                    r.anchor_text, r.context = link.anchor, link.context
                    if changed:
                        r.status = "PENDING" if relevant else "EXCLUDED"
                        r.reason = None if relevant else category
                r.last_seen_at = utcnow()
                db.commit()
                if not relevant:
                    continue
                if blocked:
                    r.status = "BLOCKED"
                    r.reason = "URL security policy"
                    db.commit()
                    continue
                target = db.scalar(
                    select(TenderDocument).where(
                        TenderDocument.tender_id == tender.id,
                        TenderDocument.source_url == url,
                    )
                )
                if (
                    target
                    and target.current_version_id
                    and target.is_active
                    and (not refresh_existing or url in attempted)
                ):
                    r.target_document_id = target.id
                    r.target_version_id = target.current_version_id
                    r.status = "ACQUIRED"
                    r.reason = None
                    if (
                        depth >= cfg.document_reference_max_depth
                        and target.current_version_id not in visited
                    ):
                        r.status = "LIMIT_REACHED"
                        r.reason = "Maximum discovery depth"
                        db.commit()
                        continue
                    db.commit()
                    queue.append((target.current_version_id, depth + 1))
                    continue
                if depth >= cfg.document_reference_max_depth:
                    r.status = "LIMIT_REACHED"
                    r.reason = "Maximum discovery depth"
                    db.commit()
                    continue
                if not acquire:
                    continue
                if (
                    r.status in {"DOWNLOAD_FAILED", "BLOCKED", "UNSUPPORTED"}
                    and not retry_failed
                ):
                    continue
                if url in attempted:
                    continue
                if acquisitions >= cfg.document_reference_max_acquisitions:
                    r.status = "LIMIT_REACHED"
                    r.reason = "Maximum acquisitions per invocation"
                    db.commit()
                    continue
                acquired_count = db.scalar(
                    select(func.count())
                    .select_from(TenderDocument)
                    .where(
                        TenderDocument.tender_id == tender.id,
                        TenderDocument.document_key.like("ref_%"),
                    )
                )
                if (
                    acquired_count >= cfg.document_reference_max_acquisitions
                    and target is None
                ):
                    r.status = "LIMIT_REACHED"
                    r.reason = "Maximum reference document acquisitions per tender"
                    db.commit()
                    continue
                attempted.add(url)
                acquisitions += 1
                candidate = DocumentCandidate(
                    document_type=DocumentType(typ),
                    display_name=typ.replace("_", " "),
                    source_url=url,
                    document_key="ref_" + key[:48],
                    original_filename=attachment['filename'] if attachment else ('catalogue.html' if '/bidding/bid/showCatalogue/' in url else Path(urlsplit(url).path).name or None),
                )
                # Reuse Stage 2 validation, atomic storage, dedup, events and Stage 3A queue.
                old = self.service.downloader
                self.service.downloader = self.downloader
                try:
                    outcome = self.service._process_document_candidate(
                        db, tender, candidate
                    )
                finally:
                    self.service.downloader = old
                target = db.scalar(
                    select(TenderDocument).where(
                        TenderDocument.tender_id == tender.id,
                        TenderDocument.document_key == candidate.document_key,
                    )
                )
                if target:
                    r.target_document_id = target.id
                if outcome.kind != "FAILED" and target and target.current_version_id:
                    r.target_version_id = target.current_version_id
                    r.status = (
                        "ACQUIRED"
                        if db.get(DocumentVersion, target.current_version_id).extension
                        in {"pdf","docx","xlsx","csv","txt","png","jpg","jpeg","html"}
                        else "UNSUPPORTED"
                    )
                    r.reason = (
                        None
                        if r.status == "ACQUIRED"
                        else "UNSUPPORTED_DOCUMENT_TYPE"
                    )
                    queue.append((target.current_version_id, depth + 1))
                else:
                    r.status = (
                        "BLOCKED"
                        if outcome.failure_class == "BLOCKED"
                        else "DOWNLOAD_FAILED"
                    )
                    r.reason = (
                        "Secure Stage 2 acquisition failed; inspect document events"
                    )
                db.commit()
        from app.corpus.queue import queue_tender_after_commit

        queue_tender_after_commit(db, tender.id, self.settings)
        return {
            "status": "SCANNED",
            "acquisitions": acquisitions,
            "versions_scanned": len(visited),
        }
