"""Deterministic corpus-only selection using the exact assembled request cost.

Reserve a feasible chunk per material source first, upgrade reservations by
requirement value, then fill important and remaining chunks round-robin. Final
evidence stays in source order. No evidence is shortened or renumbered.
"""
from dataclasses import dataclass
import hashlib
import json
import re
from collections import Counter
from app.ai.chunker import Chunk, ChunkSet
from app.ai.constants import CHUNK_PRIORITY

INPUT_SELECTION_VERSION = "corpus-input-v1"
_LABELS = re.compile(r"\b(?:eligibility|qualification|experience|turnover|certificate|OEM|MSE|startup|warranty|delivery|scope|mandatory|technical specification|bid requirement|terms and conditions|ATC)\b", re.I)


@dataclass
class MaterialGroup:
    document_id: int
    document_version_id: int
    document_type: str
    file_type: str
    source_order: int
    chunks: list[Chunk]
    material: bool = True


def priority(chunk):
    # Metadata dominates; bounded labels break ties, never execute source content.
    heading = chunk.section_heading or ""
    important = chunk.kind in {"BUYER_ATC", "TECHNICAL"} or bool(_LABELS.search(heading))
    signals = min(3, len(_LABELS.findall(chunk.text[:2000])))
    return (0 if important else 1 if signals else 2,
            CHUNK_PRIORITY.get(chunk.kind, 9), -signals, chunk.sequence, chunk.key)


def select_balanced(groups, *, max_chunks, max_chars, cost, include_boilerplate=False):
    """cost(selected) includes system, serialized user data and request envelope.

    If the cheapest usable representative of each source jointly fits, every
    source is guaranteed a chunk. Otherwise best-effort reservation is explicit
    partial coverage. This includes the chunk-count constraint.
    """
    groups = sorted(groups, key=lambda g: (g.source_order, g.document_id, g.document_version_id))
    all_chunks = [c for g in groups for c in g.chunks]
    eligible = {}
    for g in groups:
        local = []
        for c in g.chunks:
            c.sent = False
            c.exclusion_reason = "OTHER" if not g.material else "BOILERPLATE" if c.kind == "BOILERPLATE" and not include_boilerplate else "CHAR_LIMIT"
            if g.material and (c.kind != "BOILERPLATE" or include_boilerplate):
                local.append(c)
        eligible[g.document_version_id] = sorted(local, key=priority)
    selected = []
    order = lambda chunks: sorted(chunks, key=lambda c: (c.sequence, c.key))
    fits = lambda chunks: len(chunks) <= max_chunks and cost(order(chunks)) <= max_chars
    # Cheapest representatives establish feasibility before high-value upgrades.
    for g in groups:
        candidates = eligible[g.document_version_id]
        cheapest = sorted(candidates, key=lambda c: (cost([c]), c.sequence, c.key))
        for c in cheapest:
            if fits(selected + [c]):
                selected.append(c)
                break
    for g in groups:
        current = next((c for c in g.chunks if c in selected), None)
        if current is None:
            continue
        for c in eligible[g.document_version_id]:
            trial = [x for x in selected if x is not current] + [c]
            if fits(trial):
                selected = trial
                break
    # Important sections first; each document gets one opportunity per round.
    for important_only in (True, False):
        queues = [[c for c in eligible[g.document_version_id]
                   if c not in selected and (not important_only or priority(c)[0] < 2
                       or g.document_type in {"SPECIFICATION", "ATC", "BOQ", "ANNEXURE", "CORRIGENDUM"})]
                  for g in groups]
        while any(queues):
            for queue in queues:
                if not queue:
                    continue
                c = queue.pop(0)
                if c not in selected and fits(selected + [c]):
                    selected.append(c)
    for c in all_chunks:
        if c in selected:
            c.sent, c.exclusion_reason = True, None
        elif c.exclusion_reason == "CHAR_LIMIT" and len(selected) >= max_chunks:
            c.exclusion_reason = "CHUNK_LIMIT"
    return ChunkSet(order(all_chunks))


def coverage_metrics(groups, chunk_set):
    docs = []
    for g in sorted(groups, key=lambda g: g.source_order):
        selected = [c for c in g.chunks if c.sent]
        omitted = [c for c in g.chunks if not c.sent]
        material_omitted = [c for c in omitted if c.exclusion_reason != "BOILERPLATE"] if g.material else []
        docs.append({"document_id": g.document_id, "document_version_id": g.document_version_id,
                     "document_type": g.document_type, "file_type": g.file_type,
                     "material": g.material, "source_order": g.source_order,
                     "source_types": sorted({c.source_type for c in g.chunks}),
                     "chunks_total": len(g.chunks), "chunks_selected": len(selected),
                     "chunks_omitted": len(omitted), "chars_total": sum(c.char_count for c in g.chunks),
                     "chars_selected": sum(c.char_count for c in selected),
                     "chars_omitted": sum(c.char_count for c in omitted),
                     "representation_reason": None if selected else "NO_USABLE_CHUNKS" if not g.chunks else "INPUT_LIMIT",
                     "omission_reasons": dict(sorted(Counter(c.exclusion_reason for c in omitted).items())),
                     "material_chunks_omitted": len(material_omitted)})
    partial = any(d["material"] and (not d["chunks_selected"] or d["material_chunks_omitted"]) for d in docs)
    budget_limited = any(c.exclusion_reason in {"CHAR_LIMIT", "CHUNK_LIMIT"} for c in chunk_set.chunks)
    fingerprint = hashlib.sha256(json.dumps({"identity": INPUT_SELECTION_VERSION,
        "chunks": [(c.key, c.sha256, c.sent, c.exclusion_reason) for c in chunk_set.chunks],
        "sources": [(g.document_id, g.document_version_id, g.document_type, g.file_type, g.material) for g in groups]}, sort_keys=True).encode()).hexdigest()
    return {"selection_version": INPUT_SELECTION_VERSION,
            "coverage": "PARTIAL_AI_COVERAGE" if partial else "FULL_AI_COVERAGE",
            "budget_limited": budget_limited, "selection_fingerprint": fingerprint,
            "documents_total": len(docs), "documents_represented": sum(d["chunks_selected"] > 0 for d in docs),
            "documents_omitted": sum(d["chunks_selected"] == 0 for d in docs),
            "chunks_total": len(chunk_set.chunks), "chunks_selected": len(chunk_set.sent),
            "chunks_omitted": len(chunk_set.chunks) - len(chunk_set.sent),
            "chars_total": sum(c.char_count for c in chunk_set.chunks),
            "chars_selected": chunk_set.sent_characters,
            "chars_omitted": sum(c.char_count for c in chunk_set.chunks if not c.sent),
            "omission_reasons": dict(sorted(Counter(c.exclusion_reason for c in chunk_set.chunks if not c.sent).items())),
            "documents": docs}


def serialized_request_characters(prompt, settings):
    # Matches the current Gemini JSON envelope. Also conservative for content-only
    # provider budgeting. Count characters, not tokens or UTF-8 bytes.
    body = {"systemInstruction": {"parts": [{"text": prompt.system}]},
            "contents": [{"role": "user", "parts": [{"text": prompt.user}]}],
            "generationConfig": {"temperature": settings.ai_temperature,
                "maxOutputTokens": settings.ai_max_output_tokens, "responseMimeType": "application/json"}}
    return len(json.dumps(body, ensure_ascii=False, separators=(",", ":")))
