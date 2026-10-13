"""Credential redaction for anything that may be logged or stored (error messages)."""

from __future__ import annotations

import re

_PATTERNS = [
    re.compile(r"(?i)(authorization\s*[:=]\s*)(bearer\s+)?[^\s,;'\"]+"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]{8,}"),
    re.compile(r"(?i)(x-goog-api-key|api[-_]?key|key)\s*[:=]\s*['\"]?[A-Za-z0-9._\-]{8,}"),
    re.compile(r"\bAIza[0-9A-Za-z_\-]{20,}"),          # Google API key shape
    re.compile(r"\bsk-[A-Za-z0-9_\-]{12,}"),           # OpenAI-style key shape
]


def redact(text: str | None, *secrets: str | None, limit: int = 1000) -> str:
    """Remove known secrets and credential-looking tokens; truncate."""
    if not text:
        return ""
    out = str(text)
    for s in secrets:
        if s and len(s) >= 4:
            for form in {s, s.strip(), repr(s)[1:-1], s.encode("unicode_escape").decode("ascii", "replace")}:
                if form and len(form) >= 4:
                    out = out.replace(form, "[REDACTED]")
    for p in _PATTERNS:
        out = p.sub("[REDACTED]", out)
    return out[:limit]


def mask_key(key: str | None) -> str:
    """For status displays: only whether a key is present - never any part of it."""
    return "configured" if key else "missing"
