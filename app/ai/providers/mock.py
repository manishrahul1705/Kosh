"""Offline, deterministic MOCK provider (AI_PROVIDER=mock). No network, no cost.

Default behaviour: a transparent keyword reader over the evidence chunks it is
given. It is NOT an AI and its interpretations are crude - it exists so the
whole Stage 3C pipeline (chunking -> prompt -> structured output -> grounding
-> flags -> persistence -> jobs/API) can be verified without a paid provider.

Tests can script it: ``MockProvider(responses=[...])`` where each item is a raw
response string, a dict (serialized to JSON), an exception instance to raise,
or a callable ``(AIRequest) -> str | dict``. Every request is recorded in
``.requests`` so tests can assert what would have been sent.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable

from app.ai.providers.base import AIProvider, AIRequest, AIResponse

DEFAULT_MOCK_MODEL = "mock-deterministic-v1"

_TYPE_RULES = [
    (r"\bwarranty|guarantee\b", "WARRANTY"),
    (r"\biso\s*\d{3,5}", "ISO"),
    (r"\boem\b.*\bauthori[sz]ation|\bauthori[sz]ation\b.*\boem\b", "OEM_AUTHORIZATION"),
    (r"\bmanufacturer'?s? authori[sz]ation", "MANUFACTURER_AUTHORIZATION"),
    (r"\bcertificat", "CERTIFICATE"),
    (r"\btrain(er|ing)\b", "TRAINING"),
    (r"\binstallation|commissioning\b", "INSTALLATION"),
    (r"\bdeliver", "DELIVERY"),
    (r"\bpast performance|have supplied\b", "PAST_PERFORMANCE"),
    (r"\bturnover\b", "TURNOVER"),
    (r"\bexperience\b", "EXPERIENCE"),
    (r"\bemd\b|earnest money", "EMD"),
    (r"\bepbg\b|performance (security|bank guarantee)", "EPBG"),
    (r"\bsample", "SAMPLE_REQUIREMENT"),
    (r"\binspection\b", "INSPECTION"),
    (r"\bpayment\b", "PAYMENT"),
    (r"\bservice cent(re|er)|after sales\b", "SERVICE_SUPPORT"),
    (r"\bmse\b|micro and small", "MSE"),
    (r"\bstart-?up\b", "STARTUP"),
    (r"\bdeclar", "DECLARATION"),
    (r"\bundertak", "UNDERTAKING"),
    (r"\bcomply|compliance\b", "COMPLIANCE"),
    (r"\bupload|submit", "DOCUMENT_SUBMISSION"),
]
_MANDATORY = re.compile(r"\b(must|shall|required|mandatory|has to|need to|needs to|to be (submitted|uploaded|delivered))\b",
                        re.I)
_SHOULD = re.compile(r"\bshould\b", re.I)
_OPTIONAL = re.compile(r"\b(may|optional|reserves the right)\b", re.I)
_CONDITION = re.compile(r"^\s*(if|in case|where)\b|\b(if|in case)\b", re.I)
_VALUE = re.compile(r"(\d+(?:\.\d+)?)\s*(%|percent|years?|months?|weeks?|days?)\b", re.I)
_SENT = re.compile(r"(?<=[.!?])\s+")


def _sentences(text: str) -> list[str]:
    flat = " ".join(text.split())
    return [s.strip() for s in _SENT.split(flat) if len(s.strip()) >= 12]


def _unit(u: str) -> str:
    u = u.lower()
    if u in ("%", "percent"):
        return "PERCENT"
    return {"y": "YEARS", "m": "MONTHS", "w": "WEEKS", "d": "DAYS"}[u[0]]


def heuristic_response(request: AIRequest) -> dict:
    reqs, ambiguities = [], []
    for ch in request.chunks:
        if ch.get("kind") == "TABLE":
            continue  # bid-detail tables are Stage 3B's domain
        for sent in _sentences(ch["text"]):
            low = sent.lower()
            rtype = next((t for pat, t in _TYPE_RULES if re.search(pat, low)), None)
            mand, should, opt = _MANDATORY.search(sent), _SHOULD.search(sent), _OPTIONAL.search(sent)
            if not (mand or should or opt):
                continue
            if rtype is None:
                rtype = "BUYER_ATC" if ch.get("kind") == "BUYER_ATC" else "OTHER"
            if opt and not mand:
                level, amb = "OPTIONAL", None
            elif should and not mand:
                level, amb = "UNKNOWN", "Uses 'should' - unclear whether this is mandatory."
            elif _CONDITION.search(sent):
                level, amb = "CONDITIONAL", None
            else:
                level, amb = "MANDATORY", None
            m = _VALUE.search(sent)
            applies = ("BIDDER_OR_OEM" if re.search(r"bidder or (the |its )?oem", low) else
                       "SUCCESSFUL_BIDDER" if "successful bidder" in low else
                       "OEM" if re.search(r"\boem\b", low) else
                       "SELLER" if "seller" in low else
                       "BUYER" if re.search(r"\b(purchaser|buyer)\b", low) and opt else
                       "BIDDER" if "bidder" in low else "UNKNOWN")
            reqs.append({
                "requirement_type": rtype,
                "title": sent[:80],
                "summary": f"Mock reading of chunk {ch['chunk_id']}: {sent[:200]}",
                "obligation": sent[:300],
                "obligation_level": level,
                "condition": sent[:200] if level == "CONDITIONAL" else None,
                "value": float(m.group(1)) if m else None,
                "unit": _unit(m.group(2)) if m else None,
                "applies_to": applies,
                "risk_flags": ["BRAND_SPECIFIC"] if re.search(r"specific (brand|make|model)", low) else [],
                "ambiguity": amb,
                "evidence": [{"chunk_id": ch["chunk_id"], "quote": sent[:300]}],
            })
            if len(reqs) >= 60:
                break
    summary = (f"Mock (non-AI) reading of {len(request.chunks)} evidence chunk(s): "
               f"{len(reqs)} obligation sentence(s) detected by keyword rules.")
    return {"summary": summary, "requirements": reqs, "ambiguities": ambiguities}


class MockProvider(AIProvider):
    name = "mock"

    def __init__(self, model: str = "", *, responses: list | None = None) -> None:
        super().__init__(model or DEFAULT_MOCK_MODEL)
        self.responses = list(responses) if responses is not None else None
        self.requests: list[AIRequest] = []

    def generate(self, request: AIRequest) -> AIResponse:
        self.requests.append(request)
        if self.responses is None:
            item: object = heuristic_response(request)
        elif not self.responses:
            raise AssertionError("MockProvider: no scripted response left")
        else:
            item = self.responses.pop(0)
        if isinstance(item, BaseException):
            raise item
        if callable(item):
            item = item(request)
        text = item if isinstance(item, str) else json.dumps(item)
        n_in = (len(request.system) + len(request.user)) // 4
        n_out = len(text) // 4
        return AIResponse(text=text, input_tokens=n_in, output_tokens=n_out, total_tokens=n_in + n_out,
                          finish_reason="STOP", model=self.model)


ScriptItem = str | dict | BaseException | Callable[[AIRequest], object]
