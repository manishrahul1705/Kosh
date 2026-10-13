"""Derived candidates: requirements IMPLIED by another explicit fact.

Derivations only ever produce TRUE (an explicit amount / list entry / clause).
Absence never produces FALSE. Each derived candidate copies the provenance
(page/table/row/section/raw value) of the explicit candidate it came from.
"""

from __future__ import annotations

from dataclasses import replace

from app.fields.constants import EvidenceType, Strength, ValueType
from app.fields.evidence import Candidate
from app.fields.labels import label_key
from app.fields.normalizers import Normalized, normalize
from app.fields.registry import DOC_LIST_IMPLIES

# (target boolean field, source numeric/value field)
_POSITIVE_IMPLIES = (
    ("emd_required", "emd_amount"),
    ("epbg_required", "epbg_percentage"),
    ("past_performance_required", "past_performance_percentage"),
    ("experience_required", "experience_years"),
    ("bidder_turnover_required", "bidder_turnover_amount"),
    ("oem_turnover_required", "oem_turnover_amount"),
    ("warranty_required", "warranty_period"),
)
_DOC_LIST_CERTIFICATE_SKIP = ("oem authorization", "oem authorisation")


def _true(target: str, src: Candidate, rule: str, detail: str) -> Candidate:
    return replace(src, field_name=target, result=normalize(ValueType.BOOL.value, "Yes"),
                   evidence_type=EvidenceType.DERIVED.value, strength=Strength.DERIVED.value, rule=rule,
                   source_text=(f"{detail} <- {src.source_text or ''}")[:500])


def derived_candidates(cands: list[Candidate]) -> list[Candidate]:
    out: list[Candidate] = []
    by_field: dict[str, list[Candidate]] = {}
    for c in cands:
        by_field.setdefault(c.field_name, []).append(c)

    for target, source in _POSITIVE_IMPLIES:
        for c in by_field.get(source, []):
            if isinstance(c.result, Normalized) and (c.result.number or 0) > 0:
                out.append(_true(target, c, f"derived_from_{source}", f"{source}={c.result.text}"))

    for c in by_field.get("documents_required_from_seller", []):
        if not isinstance(c.result, Normalized):
            continue
        items = c.result.value
        keys = [label_key(i) for i in items]
        for target, phrases in DOC_LIST_IMPLIES.items():
            hit = next((items[i] for i, k in enumerate(keys) if any(f" {p} " in f" {k} " for p in phrases)), None)
            if hit:
                out.append(_true(target, c, "derived_from_documents_required", f"documents list item '{hit}'"))
        certs = [i for i, k in zip(items, keys) if "certificate" in k
                 and not any(s in k for s in _DOC_LIST_CERTIFICATE_SKIP)]
        if certs:
            from app.fields.normalizers import norm_list
            out.append(replace(c, field_name="certificate_requirements", result=norm_list(certs),
                               evidence_type=EvidenceType.DERIVED.value, strength=Strength.DERIVED.value,
                               rule="derived_from_documents_required",
                               source_text=(f"documents list item(s) {certs} <- {c.source_text or ''}")[:500]))
    return out
