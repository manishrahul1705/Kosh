"""Every API call made by the frontend must target a route the backend actually serves."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CALL = re.compile(r"apiClient\s*\.\s*(get|post|put|patch|delete)\s*(?:<[^>]*>)?\s*\(\s*[`'\"]([^`'\"]+)[`'\"]",
                  re.S)


def _frontend_calls() -> set[tuple[str, str]]:
    calls = set()
    for f in (ROOT / "frontend" / "src").rglob("*.ts*"):
        if "/test/" in f.as_posix():
            continue
        for method, path in CALL.findall(f.read_text(encoding="utf-8")):
            path = re.sub(r"\$\{[^}]+\}", "{}", path)
            calls.add((method.upper(), "/api" + path))
    return calls


def _normalize(path: str) -> str:
    return re.sub(r"\{[^}]+\}", "{}", path).rstrip("/")


def test_frontend_calls_exist_in_backend(client):
    spec = client.app.openapi()
    served = {(m.upper(), _normalize(p)) for p, ops in spec["paths"].items() for m in ops}
    calls = _frontend_calls()
    assert calls, "no frontend API calls found"
    missing = sorted(c for c in calls if (c[0], _normalize(c[1])) not in served)
    assert missing == []


def test_no_out_of_scope_ui_remains():
    src = ROOT / "frontend" / "src"
    text = " ".join(p.read_text(encoding="utf-8").lower() for p in src.rglob("*.ts*"))
    for word in ("financial", "invoice", "cash-flow", "bid workspace", "orders & fulfillment", "profitability"):
        assert word not in text, word
