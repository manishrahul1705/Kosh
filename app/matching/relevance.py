"""Deterministic product/service relevance between a seller profile and a tender.

Relevance is NOT eligibility. Relevance answers "does this seller deal in what
the tender is buying?". Eligibility (turnover, experience, certificates, ...)
is decided separately by app.eligibility.

Seller terms come from these profile attributes (plain text, comma/semicolon/
newline separated, or a JSON list): product_category, products, services,
keywords.

Tender text = GeM category + tender title.

A seller term matches when every significant token of the term appears in
the tender text (singular/plural folded). Example: term "laptop" matches the
category "Laptop - Notebook". The term "office chair" needs both "office" and
"chair". No AI is involved.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

RELEVANCE_ATTRIBUTE_KEYS = ("product_category", "products", "services", "keywords")

_STOPWORDS = frozenset({
    "a", "an", "and", "as", "at", "by", "for", "from", "in", "into", "of", "on", "or", "the", "to",
    "with", "without", "per", "each", "item", "items", "supply", "procurement", "purchase", "goods",
    "service", "services", "product", "products", "type", "other", "others", "etc", "misc",
    "gem", "bid", "tender", "q1", "q2", "q3",
})
_TOKEN_RE = re.compile(r"[a-z0-9]+")
MAX_TERMS = 200
MAX_TERM_CHARS = 120


def _fold(token: str) -> str:
    """Very small, predictable plural folding (no external stemmer)."""
    if len(token) > 4 and token.endswith("ies"):
        return token[:-3] + "y"
    if len(token) > 4 and token.endswith(("ches", "shes", "sses", "xes")):
        return token[:-2]
    if len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def tokenize(text: str | None) -> frozenset[str]:
    if not text:
        return frozenset()
    return frozenset(_fold(t) for t in _TOKEN_RE.findall(text.lower()) if t not in _STOPWORDS and len(t) > 1)


def parse_terms(raw_values: list[str | None]) -> list[str]:
    """Split attribute values into distinct, bounded terms (order preserved)."""
    terms: list[str] = []
    seen: set[str] = set()
    for raw in raw_values:
        if not raw:
            continue
        items: list[str]
        text = raw.strip()
        if text.startswith("["):
            try:
                loaded = json.loads(text)
                items = [str(x) for x in loaded] if isinstance(loaded, list) else [text]
            except (ValueError, TypeError):
                items = re.split(r"[,;\n]", text)
        else:
            items = re.split(r"[,;\n]", text)
        for item in items:
            term = " ".join(item.split())[:MAX_TERM_CHARS]
            key = term.lower()
            if term and key not in seen and tokenize(term):
                seen.add(key)
                terms.append(term)
            if len(terms) >= MAX_TERMS:
                return terms
    return terms


@dataclass(frozen=True)
class RelevanceResult:
    status: str                      # RELEVANT | NOT_RELEVANT | UNKNOWN
    matched_terms: list[str] = field(default_factory=list)
    reason: str = ""


def evaluate_relevance(seller_terms: list[str], tender_category: str | None,
                       tender_title: str | None) -> RelevanceResult:
    if not seller_terms:
        return RelevanceResult("UNKNOWN", [], "Seller profile lists no products, services or keywords")
    tender_tokens = tokenize(tender_category) | tokenize(tender_title)
    if not tender_tokens:
        return RelevanceResult("UNKNOWN", [], "Tender has no category or title to compare")
    matched = [t for t in seller_terms if tokenize(t) and tokenize(t) <= tender_tokens]
    if matched:
        return RelevanceResult("RELEVANT", matched,
                               "Tender category/title matches seller offering: " + ", ".join(matched[:10]))
    return RelevanceResult("NOT_RELEVANT", [], "No seller product, service or keyword appears in the "
                                                "tender category or title")
