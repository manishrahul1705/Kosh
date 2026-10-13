"""Rules over Stage 3A page text and sections (weaker than tables; always bounded).

* page_label_candidates  "<English label> <value>" lines (EXACT_LABEL) for
                         registry fields marked text_label=True.
* identity_candidates    Stage 2 metadata (SYSTEM_METADATA) + "Bid Number:" /
                         "Dated:" printed on the document.
* section_candidates     facts that only exist inside known sections:
                         item title before "Technical Specifications", Buyer-added
                         ATC presence/clauses, warranty clause, certificates
                         (ISO / BIS) and manufacturer authorization - ONLY inside
                         the Buyer-added ATC span (never from the GeM disclaimer).
* regex_candidates       bounded GeM boilerplate patterns anywhere (REGEX_FALLBACK):
                         past-performance %, experience years, EMD exemption clause.
"""

from __future__ import annotations

import re

from app.fields.constants import EvidenceType, Strength, ValueType
from app.fields.evidence import Candidate, SectionRef, Source
from app.fields.labels import alias_regex, english_label
from app.fields.normalizers import Normalized, clean, norm_list, normalize
from app.fields.registry import (
    ATC_END_SECTIONS,
    ATC_START_SECTIONS,
    FIELDS,
    TECH_SECTIONS,
)

MAX_LABEL_VALUE_CHARS = 80


def _c(field: str, result, raw, etype: EvidenceType, strength: Strength, rule: str, *, label=None, page=None,
       section: SectionRef | None = None, text: str | None = None) -> Candidate:
    return Candidate(field, result, raw, etype.value, strength.value, rule, label, page, None, None, None,
                     section.id if section else None, section.normalized if section else None,
                     clean(text)[:500] if text else None)


# ---------------------------------------------------------------------------
def page_label_candidates(src: Source, zone: str) -> list[Candidate]:
    specs = [f for f in FIELDS if f.text_label]
    out: list[Candidate] = []
    for page in src.pages:
        for line in page.text.split("\n"):
            eng = english_label(line)
            if not eng:
                continue
            for spec in specs:
                for alias in spec.aliases:
                    if alias.mode != "exact" or len(alias.key.split()) < 2:
                        continue
                    m = alias_regex(alias).match(eng)
                    if not m:
                        continue
                    value = eng[m.end():].strip(" :-")
                    if not value or len(value) > MAX_LABEL_VALUE_CHARS:
                        continue
                    result = normalize(spec.value_type, value, zone=zone, default_unit=spec.default_unit)
                    out.append(_c(spec.name, result, value, EvidenceType.PAGE_TEXT, Strength.EXACT_LABEL,
                                  "page_text_label", label=alias.text, page=page.page_number, text=line))
                    break
    return out


# ---------------------------------------------------------------------------
_BID_NO = re.compile(r"Bid\s*Number\s*:\s*(GEM/\d{4}/[A-Z]+/\d+)", re.I)
_DATED = re.compile(r"\bDated\s*:\s*(\d{1,2}-\d{1,2}-\d{4})\b", re.I)


def identity_candidates(src: Source, zone: str) -> list[Candidate]:
    meta = [
        ("bid_number", src.bid_number, ValueType.TEXT),
        ("document_version_id", str(src.document_version_id), ValueType.INTEGER),
        ("document_type", src.document_type, ValueType.TEXT),
        ("document_version_number", str(src.version_number), ValueType.INTEGER),
    ]
    out = [Candidate(name, normalize(vt.value, raw), raw, EvidenceType.METADATA.value,
                     Strength.SYSTEM_METADATA.value, "stage2_metadata", source_label=name,
                     source_text=f"Stage 2 record; Stage 3A extraction {src.stage3a_extraction_id}")
           for name, raw, vt in meta]
    first = src.pages[0] if src.pages else None
    if first is not None:
        m = _BID_NO.search(first.text)
        if m:
            out.append(_c("bid_number", normalize(ValueType.TEXT.value, m.group(1)), m.group(1),
                          EvidenceType.PAGE_TEXT, Strength.EXACT_LABEL, "document_bid_number",
                          label="Bid Number", page=first.page_number, text=m.group(0)))
        m = _DATED.search(first.text)
        if m:
            out.append(_c("bid_document_date", normalize(ValueType.DATE.value, m.group(1), zone=zone), m.group(1),
                          EvidenceType.PAGE_TEXT, Strength.EXACT_LABEL, "document_dated",
                          label="Dated", page=first.page_number, text=m.group(0)))
    return out


# ---------------------------------------------------------------------------
_WARRANTY = re.compile(r"\bwarranty\s+period\b[^.\n]{0,120}?\b(\d+(?:\.\d+)?)\s*(years?|months?|days?)\b", re.I)
_ISO = re.compile(r"\bISO\s*[-:]?\s*(\d{3,5})(?:\s*[:\-]\s*(\d{4}))?\b")
_BIS = re.compile(r"\bBIS\b")
_CERT_WORD = re.compile(r"certif|licen[cs]e|\bmark", re.I)
_MAF = re.compile(r"\bManufacturer'?s?\s+Authori[sz]ation\s*(?:Form|Certificate)?\s*:", re.I)
_TEXT_ATC = re.compile(r"Buyer Added text based ATC clauses", re.I)


def _atc_start(src: Source) -> SectionRef | None:
    return next((s for s in src.sections if s.normalized in ATC_START_SECTIONS), None)


def section_candidates(src: Source) -> list[Candidate]:
    out: list[Candidate] = []
    # item title(s): a font-size heading immediately followed by "Technical Specifications"
    titles = []
    for prev, nxt in zip(src.sections, src.sections[1:]):
        if nxt.normalized in TECH_SECTIONS and prev.method == "font_size":
            titles.append(prev)
    if titles:
        out.append(Candidate("item_description", norm_list([t.heading for t in titles]),
                             " | ".join(t.heading for t in titles), EvidenceType.SECTION_TEXT.value,
                             Strength.SECTION_CONTEXT.value, "item_title_before_technical_specifications",
                             "Technical Specifications", titles[0].page_number, None, None, None, titles[0].id,
                             titles[0].normalized, " | ".join(t.heading for t in titles)[:500]))

    start = _atc_start(src)
    if start is None:
        return out
    out.append(_c("buyer_added_atc_present", normalize(ValueType.BOOL.value, "Yes"), start.heading,
                  EvidenceType.SECTION_TEXT, Strength.SECTION_CONTEXT, "atc_section_heading",
                  label=start.heading, page=start.page_number, section=start, text=start.heading))
    idx = src.sections.index(start)
    clauses = []
    for s in src.sections[idx + 1:]:
        if s.normalized in ATC_END_SECTIONS:
            break
        if s.method == "numbered":
            clauses.append({"title": s.heading, "normalized": s.normalized, "page": s.page_number})
    if clauses:
        res = norm_list([c["title"] for c in clauses])
        if isinstance(res, Normalized):
            res.value = clauses
        out.append(_c("buyer_added_atc_clauses", res, " | ".join(c["title"] for c in clauses),
                      EvidenceType.SECTION_TEXT, Strength.SECTION_CONTEXT, "atc_numbered_clauses",
                      label=start.heading, page=start.page_number, section=start,
                      text=" | ".join(c["title"] for c in clauses)))

    for page_no, lo, piece in src.section_span(start, ATC_END_SECTIONS):
        flat = piece.replace("\n", " ")
        for m in _WARRANTY.finditer(flat):
            # A duration for repair/service during a warranty is a different
            # obligation, not the length of the warranty itself.
            prefix=m.group(0).rsplit(m.group(1),1)[0]
            if re.search(r'\b(?:rectification|rectify|repairs?|response|respond|service|attend)\b',prefix,re.I):
                continue
            sec = src.section_at(page_no, lo + m.start())
            out.append(_c("warranty_period", normalize(ValueType.DURATION.value, f"{m.group(1)} {m.group(2)}"),
                          m.group(0), EvidenceType.SECTION_TEXT, Strength.SECTION_CONTEXT, "atc_warranty_clause",
                          label="Warranty period", page=page_no, section=sec, text=m.group(0)))
        for m in _ISO.finditer(flat):
            name = f"ISO {m.group(1)}" + (f":{m.group(2)}" if m.group(2) else "")
            sec = src.section_at(page_no, lo + m.start())
            sentence = flat[max(0, m.start() - 80): m.end() + 120]
            out.append(_c("certificate_requirements", norm_list([name]), m.group(0), EvidenceType.SECTION_TEXT,
                          Strength.SECTION_CONTEXT, "atc_iso_certificate", label="ISO", page=page_no,
                          section=sec, text=sentence))
        for sentence in re.split(r"(?<=\.)\s+", flat):
            if _BIS.search(sentence) and _CERT_WORD.search(sentence):
                sec = src.section_at(page_no, lo + flat.find(sentence))
                out.append(_c("certificate_requirements", norm_list(["BIS"]), sentence[:200],
                              EvidenceType.SECTION_TEXT, Strength.SECTION_CONTEXT, "atc_bis_certificate",
                              label="BIS", page=page_no, section=sec, text=sentence))
        for m in _MAF.finditer(flat):
            sec = src.section_at(page_no, lo + m.start())
            out.append(_c("manufacturer_authorization_required", normalize(ValueType.BOOL.value, "Yes"),
                          m.group(0), EvidenceType.SECTION_TEXT, Strength.SECTION_CONTEXT,
                          "atc_manufacturer_authorization", label="Manufacturer Authorization", page=page_no,
                          section=sec, text=flat[m.start(): m.start() + 200]))
    return out


# ---------------------------------------------------------------------------
_PAST_PERF = re.compile(r"Past Performance\s*:.{0,300}?\bfor\s+(\d+(?:\.\d+)?)\s*%\s*of\s+bid\s+quantity", re.I | re.S)
_EXPERIENCE = re.compile(r"Experience Criteria\s*:.{0,400}?\bfor\s+(\d+)\s+years?\s+before\s+the\s+bid\s+opening",
                         re.I | re.S)
_EMD_EXEMPT = re.compile(r"EMD EXEMPTION\s*:\s*The bidder seeking EMD exemption", re.I)


def regex_candidates(src: Source) -> list[Candidate]:
    out: list[Candidate] = []
    for page in src.pages:
        flat = page.text.replace("\n", " ")
        for m in _PAST_PERF.finditer(flat):
            out.append(_c("past_performance_percentage", normalize(ValueType.PERCENT.value, m.group(1)),
                          m.group(1) + " %", EvidenceType.PAGE_TEXT, Strength.REGEX_FALLBACK,
                          "past_performance_clause", label="Past Performance", page=page.page_number,
                          section=src.section_at(page.page_number, m.start()), text=m.group(0)))
        for m in _EXPERIENCE.finditer(flat):
            out.append(_c("experience_years", normalize(ValueType.DURATION.value, m.group(1) + " years"),
                          m.group(1) + " years", EvidenceType.PAGE_TEXT, Strength.REGEX_FALLBACK,
                          "experience_criteria_clause", label="Experience Criteria", page=page.page_number,
                          section=src.section_at(page.page_number, m.start()), text=m.group(0)))
        for m in _EMD_EXEMPT.finditer(flat):
            out.append(_c("emd_exemption_allowed", normalize(ValueType.BOOL.value, "Yes"), m.group(0),
                          EvidenceType.PAGE_TEXT, Strength.REGEX_FALLBACK, "emd_exemption_clause",
                          label="EMD EXEMPTION", page=page.page_number,
                          section=src.section_at(page.page_number, m.start()), text=flat[m.start(): m.start() + 300]))
        for m in _TEXT_ATC.finditer(flat):
            out.append(_c("buyer_added_atc_present", normalize(ValueType.BOOL.value, "Yes"), m.group(0),
                          EvidenceType.PAGE_TEXT, Strength.REGEX_FALLBACK, "atc_text_clauses_marker",
                          label="Buyer Added text based ATC clauses", page=page.page_number,
                          section=src.section_at(page.page_number, m.start()), text=m.group(0)))
    return out
