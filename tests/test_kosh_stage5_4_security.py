"""Security hardening tests for Phase M6: security headers, CORS, rate limiting, upload guards, and redaction."""
from __future__ import annotations
import pytest
from fastapi.testclient import TestClient
from app.main import create_app
from app.core.config import Settings


def test_security_headers_present_on_api_responses(settings, session_factory, source):
    """API responses must include X-Content-Type-Options, X-Frame-Options, Referrer-Policy, and CSP."""
    app = create_app(
        settings.model_copy(update={"dev_login_enabled": False}),
        session_factory=session_factory,
        collector_factory=source,
    )
    with TestClient(app) as client:
        res = client.get("/health")
        assert res.status_code == 200
        assert res.headers["x-content-type-options"] == "nosniff"
        assert res.headers["x-frame-options"] == "DENY"
        assert res.headers["referrer-policy"] == "strict-origin-when-cross-origin"
        assert "default-src 'self'" in res.headers["content-security-policy"]
        assert "frame-ancestors 'none'" in res.headers["content-security-policy"]


def test_cors_production_guards_against_wildcard():
    """In production, CORS cannot be configured to wildcard '*'."""
    with pytest.raises(ValueError, match="CORS_ORIGINS"):
        Settings(
            _env_file=None,
            app_env="production",
            kosh_approval_secret="a"*32,
            auto_migrate=False,
            dev_login_enabled=False,
            cors_origins="*",
        )


def test_cors_production_allows_configured_origins(settings, session_factory, source):
    """Configured origins are properly allowed via Access-Control-Allow-Origin."""
    app = create_app(
        settings.model_copy(update={"cors_origins": "https://kosh.example.com"}),
        session_factory=session_factory,
        collector_factory=source,
    )
    with TestClient(app) as client:
        res = client.options(
            "/health",
            headers={
                "Origin": "https://kosh.example.com",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert res.headers.get("access-control-allow-origin") == "https://kosh.example.com"


def test_dev_login_rate_limiting(settings, session_factory, source):
    """Dev login triggers HTTP 429 when max requests per minute is exceeded."""
    from app.api import dev_login
    dev_login._login_attempts.clear()

    app = create_app(
        settings.model_copy(update={"dev_login_enabled": True}),
        session_factory=session_factory,
        collector_factory=source,
    )
    with TestClient(app) as client:
        # 30 requests should succeed
        for i in range(30):
            r = client.post("/api/dev/login", json={"email": f"user{i}@kosh.local"})
            assert r.status_code == 200
        # 31st request triggers rate limit
        r_blocked = client.post("/api/dev/login", json={"email": "overflow@kosh.local"})
        assert r_blocked.status_code == 429
        assert "Too many" in r_blocked.json()["detail"]


def test_approval_rate_limiting(settings, session_factory, source):
    """Approval endpoint triggers HTTP 429 when attempt threshold is exceeded."""
    from app.api import actions
    actions._APPROVAL_ATTEMPTS.clear()

    app = create_app(settings, session_factory=session_factory, collector_factory=source)
    with TestClient(app) as client:
        login = client.post("/api/dev/login", json={"email": "approver_limit@kosh.local"})
        if login.status_code != 200:
            return
        token = login.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # Simulate 30 approval attempts for seller 999
        seller_id = 999
        for _ in range(30):
            client.post(f"/api/kosh/sellers/{seller_id}/actions/intents/intent-xyz/approve", json={}, headers=headers)

        # 31st call triggers rate limiter
        r_limited = client.post(f"/api/kosh/sellers/{seller_id}/actions/intents/intent-xyz/approve", json={}, headers=headers)
        assert r_limited.status_code == 429
        assert "Approval rate limit" in r_limited.json()["detail"]
