from collections import defaultdict
import hashlib
import json
from sqlalchemy import select
from app.database.models import (
    Tender,
    TenderDocument,
    DocumentVersion,
    DocumentExtraction,
    DocumentPage,
    DocumentTable,
    DocumentSection,
    TenderFieldExtraction,
    TenderFieldValue,
    TenderFieldEvidence,
    DocumentReference,
    DocumentReferenceScan,
)
from app.documents.reference_security import canonical_url
from app.documents.references import RULES_VERSION


def canonical(value):
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def row_value(row, names):
    return {n: getattr(row, n) for n in names}


def semantic_extraction(s, e, f):
    """Semantic content only: never row IDs, timestamps, paths, metrics or job IDs."""
    a = None
    b = None
    if e:
        a = {
            "extractor": e.extractor_version,
            "parser": e.parser_version,
            "status": e.status,
            "quality": e.quality_status,
            "pages": [
                row_value(x, ["page_number", "normalized_text", "text_source", "error_code"])
                for x in s.scalars(
                    select(DocumentPage)
                    .where(DocumentPage.extraction_id == e.id)
                    .order_by(DocumentPage.page_number)
                )
            ],
            "tables": [
                row_value(x, ["page_number", "table_index", "table_json", "bbox_json"])
                for x in s.scalars(
                    select(DocumentTable)
                    .where(DocumentTable.extraction_id == e.id)
                    .order_by(DocumentTable.page_number, DocumentTable.table_index)
                )
            ],
            "sections": [
                row_value(
                    x,
                    [
                        "page_number",
                        "sequence",
                        "heading",
                        "normalized_heading",
                        "char_offset",
                    ],
                )
                for x in s.scalars(
                    select(DocumentSection)
                    .where(DocumentSection.extraction_id == e.id)
                    .where(DocumentSection.detection_method != 'OCR_METADATA')
                    .order_by(DocumentSection.sequence)
                )
            ],
        }
    if f:
        b = {
            "extractor": f.extractor_version,
            "status": f.status,
            "values": [
                row_value(
                    x,
                    [
                        "field_name",
                        "status",
                        "tri_state",
                        "value_text",
                        "value_number",
                        "value_json",
                        "unit",
                        "evidence_strength",
                    ],
                )
                for x in s.scalars(
                    select(TenderFieldValue)
                    .where(TenderFieldValue.field_extraction_id == f.id)
                    .order_by(TenderFieldValue.field_name)
                )
            ],
            "evidence": sorted(
                [
                    row_value(
                        x,
                        [
                            "field_name",
                            "page_number",
                            "table_index",
                            "row_index",
                            "section_heading",
                            "evidence_type",
                            "strength",
                            "rule",
                            "source_label",
                            "raw_value",
                            "source_text",
                            "normalized_json",
                            "value_key",
                            "disposition",
                        ],
                    )
                    for x in s.scalars(
                        select(TenderFieldEvidence).where(
                            TenderFieldEvidence.field_extraction_id == f.id
                        )
                    )
                ],
                key=canonical,
            ),
        }
        # Metadata IDs are provenance, never semantic tender fields.
        b["values"] = [
            v
            for v in b["values"]
            if v["field_name"]
            not in {
                "document_version_id",
                "stage3a_extraction_id",
                "stage3b_extraction_id",
            }
        ]
        for evidence in b["evidence"]:
            if evidence["evidence_type"] == "METADATA":
                evidence["source_text"] = None
        b["evidence"] = [
            v
            for v in b["evidence"]
            if v["field_name"]
            not in {
                "document_version_id",
                "stage3a_extraction_id",
                "stage3b_extraction_id",
            }
        ]
    return digest(a) if a else None, digest(b) if b else None


def aggregate(s, documents):
    fields = defaultdict(list)
    skip = {
        "bid_number",
        "document_version_id",
        "document_type",
        "document_version_number",
        "consignee_details",
        "buyer_added_atc_clauses",
    }
    for d in documents:
        fid = d["stage3b_extraction_id"]
        if not fid:
            continue
        evidence = defaultdict(list)
        for e in s.scalars(
            select(TenderFieldEvidence).where(
                TenderFieldEvidence.field_extraction_id == fid
            )
        ):
            evidence[e.field_name].append(
                row_value(
                    e,
                    [
                        "id",
                        "page_number",
                        "table_id",
                        "section_id",
                        "section_heading",
                        "raw_value",
                        "source_text",
                        "strength",
                        "disposition",
                        "normalized_json",
                    ],
                )
            )
        for v in s.scalars(
            select(TenderFieldValue)
            .where(TenderFieldValue.field_extraction_id == fid)
            .order_by(TenderFieldValue.field_name)
        ):
            if v.field_name in skip:
                continue
            fields[v.field_name].append(
                {
                    **row_value(
                        v,
                        [
                            "status",
                            "tri_state",
                            "value_text",
                            "value_number",
                            "value_json",
                            "unit",
                            "evidence_strength",
                        ],
                    ),
                    "document_id": d["document_id"],
                    "document_type": d["document_type"],
                    "document_version_id": d["document_version_id"],
                    "version_number": d["version_number"],
                    "stage3b_extraction_id": fid,
                    "evidence": evidence[v.field_name],
                }
            )
    out = {}
    conflicts = []
    for name, candidates in sorted(fields.items()):
        known = [c for c in candidates if c["status"] == "RESOLVED"]

        def key(c):
            return (
                canonical([c["tri_state"], c["value_number"], c["unit"]])
                if c["value_number"] is not None
                else canonical([c["tri_state"], c["value_json"] or c["value_text"]])
            )

        conflict = len({key(c) for c in known}) > 1 or any(
            c["status"] == "CONFLICT" for c in candidates
        )
        out[name] = {
            "candidates": candidates,
            "status": "CONFLICT" if conflict else "RESOLVED" if known else "UNKNOWN",
            "primary": None,
            "precedence": "No cross-document legal precedence inferred; all candidates retained",
        }
        if conflict:
            conflicts.append(
                {
                    "field": name,
                    "candidates": candidates,
                    "severity": "HIGH",
                    "review_required": True,
                }
            )
    return out, conflicts


def build_corpus(s, tender_id):
    tender = s.get(Tender, tender_id)
    if tender is None:
        raise ValueError("Tender not found")
    all_docs = list(
        s.scalars(select(TenderDocument).where(TenderDocument.tender_id == tender_id))
    )
    docs = [d for d in all_docs if d.is_active and d.document_type != "UNKNOWN"]

    def identity(d):
        try:
            url = canonical_url(d.source_url or "")
        except ValueError:
            url = d.source_url or ""
        return [d.document_type, url]

    docs.sort(key=lambda d: canonical(identity(d)))
    current_ids = {d.current_version_id for d in docs if d.current_version_id}
    refs = list(
        s.scalars(
            select(DocumentReference)
            .where(DocumentReference.tender_id == tender_id)
            .order_by(DocumentReference.id)
        )
    )
    active_refs = [r for r in refs if r.source_version_id in current_ids]
    reasons = []
    if any(d.is_active and d.document_type == 'UNKNOWN' for d in all_docs):
        reasons.append({'state':'INCOMPLETE_UNCLASSIFIED_DOCUMENT'})
    documents = []
    stable_docs = []
    for d in docs:
        v = (
            s.get(DocumentVersion, d.current_version_id)
            if d.current_version_id
            else None
        )
        e = (
            s.scalar(
                select(DocumentExtraction)
                .where(
                    DocumentExtraction.document_version_id == v.id,
                    DocumentExtraction.is_current.is_(True),
                )
                .order_by(DocumentExtraction.id.desc())
                .limit(1)
            )
            if v
            else None
        )
        f = (
            s.scalar(
                select(TenderFieldExtraction)
                .where(
                    TenderFieldExtraction.stage3a_extraction_id == e.id,
                    TenderFieldExtraction.is_current.is_(True),
                )
                .order_by(TenderFieldExtraction.id.desc())
                .limit(1)
            )
            if e
            else None
        )
        scan = s.get(DocumentReferenceScan, v.id) if v else None
        state = "READY"
        if not v or v.validation_status != "VALID":
            state = "INCOMPLETE_MISSING_DOCUMENT"
        elif v.extension not in {"pdf","docx","xlsx","csv","txt","png","jpg","jpeg","html"}:
            state = "INCOMPLETE_UNSUPPORTED"
        elif not scan or scan.rules_version != RULES_VERSION:
            state = "INCOMPLETE_PENDING"
        elif scan.status != "COMPLETE":
            state = "INCOMPLETE_DISCOVERY"
        if state == "READY":
            if e and e.status=='OCR_REQUIRED':
                state='INCOMPLETE_OCR_FAILED' if e.error_code in {'OCR_FAILED','OCR_TIMEOUT','OCR_EMPTY'} else 'INCOMPLETE_OCR_PENDING'
            elif e and e.status=='UNSUPPORTED':state='INCOMPLETE_UNSUPPORTED'
            elif not e or not f:
                state = "INCOMPLETE_PENDING"
            elif e.status not in {"SUCCESS", "PARTIAL_SUCCESS"} or f.status not in {
                "SUCCESS",
                "PARTIAL_SUCCESS",
            }:
                state = "INCOMPLETE_EXTRACTION_FAILED"
            elif e.status == "PARTIAL_SUCCESS":
                state = "INCOMPLETE_EXTRACTION_PARTIAL"
        if state != "READY":
            reasons.append({"document_id": d.id, "state": state})
        a, b = semantic_extraction(s, e, f)
        documents.append(
            {
                "document_id": d.id,
                "document_type": d.document_type,
                "source_url": d.source_url,
                "document_version_id": v.id if v else None,
                "version_number": v.version_number if v else None,
                "sha256": v.sha256 if v else None,
                "stage3a_extraction_id": e.id if e else None,
                "stage3b_extraction_id": f.id if f else None,
                "stage3a_digest": a,
                "stage3b_digest": b,
                "state": state,
                "usable": bool(
                    e
                    and f
                    and e.status in {"SUCCESS", "PARTIAL_SUCCESS"}
                    and f.status in {"SUCCESS", "PARTIAL_SUCCESS"}
                ),
            }
        )
        stable_docs.append(
            {
                "identity": identity(d),
                "version": v.version_number if v else None,
                "sha256": v.sha256 if v else None,
                "extraction": a,
                "fields": b,
                "state": state,
            }
        )
    missing = []
    stable_refs = []
    byid = {d.id: d for d in all_docs}
    for r in active_refs:
        if not r.corpus_relevant:
            continue
        target = byid.get(r.target_document_id)
        if (
            r.status != "ACQUIRED"
            or not target
            or not target.is_active
            or not target.current_version_id
        ):
            missing.append(r.id)
            reasons.append(
                {
                    "reference_id": r.id,
                    "state": "INCOMPLETE_DOWNLOAD_FAILED"
                    if r.status == "DOWNLOAD_FAILED"
                    else "INCOMPLETE_UNSUPPORTED" if r.status=='UNSUPPORTED'
                    else "INCOMPLETE_MISSING_DOCUMENT",
                }
            )
        source = byid[r.source_document_id]
        stable_refs.append(
            {
                "source": identity(source),
                "page": r.page_number,
                "url": r.canonical_url,
                "type": r.document_type,
                "status": r.status,
            }
        )
    if not any(d.document_type == "MAIN_BID" for d in docs):
        reasons.append({"state": "INCOMPLETE_MISSING_DOCUMENT"})
    if any(r.category == "UNKNOWN_REFERENCE" for r in active_refs):
        reasons.append({"state": "INCOMPLETE_UNCLASSIFIED_REFERENCE"})
    completeness = (
        "COMPLETE" if not reasons else sorted({r["state"] for r in reasons})[0]
    )
    fields, conflicts = aggregate(s, documents)
    fingerprint = digest(
        {
            "rules": RULES_VERSION,
            "documents": sorted(stable_docs, key=canonical),
            "references": sorted(stable_refs, key=canonical),
            "completeness": completeness,
        }
    )
    return {
        "tender_id": tender.id,
        "bid_number": tender.bid_number,
        "fingerprint": fingerprint,
        "complete": not reasons,
        "completeness": completeness,
        "reasons": reasons,
        "documents": documents,
        "relevant_document_count": len(documents),
        "missing_reference_count": len(missing),
        "excluded_generic_reference_count": sum(
            r.category in {"POLICY_REFERENCE", "GTC_REFERENCE"} for r in active_refs
        ),
        "missing_references": missing,
        "references": [
            row_value(
                r,
                [
                    "id",
                    "source_document_id",
                    "source_version_id",
                    "page_number",
                    "anchor_text",
                    "context",
                    "original_url",
                    "canonical_url",
                    "category",
                    "document_type",
                    "corpus_relevant",
                    "target_document_id",
                    "target_version_id",
                    "discovery_method",
                    "depth",
                    "status",
                    "reason",
                ],
            )
            for r in active_refs
        ],
        "fields": fields,
        "conflicts": conflicts,
    }
