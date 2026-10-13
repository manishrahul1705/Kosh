"""Local test sign-in (DEV_LOGIN_ENABLED): off by default, never in production, local only."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


def _app(settings, session_factory, source, **over):
    return create_app(settings.model_copy(update=over), session_factory=session_factory, collector_factory=source)


def test_disabled_by_default(settings, session_factory, source):
    with TestClient(_app(settings, session_factory, source)) as c:
        assert c.post("/api/dev/login", json={"email": "a@b.co"}).status_code == 404


def test_refused_in_production(settings, session_factory, source):
    with pytest.raises(ValueError, match="DEV_LOGIN_ENABLED"):
        _app(settings, session_factory, source, dev_login_enabled=True, app_env="production", auto_migrate=False)


def test_login_gives_working_token_and_one_demo_seller(settings, session_factory, source):
    with TestClient(_app(settings, session_factory, source, dev_login_enabled=True)) as c:
        r = c.post("/api/dev/login", json={"email": "Demo@Example.com"})
        assert r.status_code == 200
        h = {"Authorization": f"Bearer {r.json()['access_token']}"}
        assert c.post("/api/auth/provision", headers=h).status_code == 200
        sellers = c.get("/api/sellers", headers=h).json()
        assert len(sellers) == 1 and "demo@example.com" in sellers[0]["name"]
        sid = sellers[0]["id"]
        assert c.get(f"/api/portal/sellers/{sid}/summary", headers=h).status_code == 200
        # signing in again does not create another seller
        h2 = {"Authorization": f"Bearer {c.post('/api/dev/login', json={'email': 'demo@example.com'}).json()['access_token']}"}
        assert [s["id"] for s in c.get("/api/sellers", headers=h2).json()] == [sid]


def test_users_are_isolated(settings, session_factory, source):
    with TestClient(_app(settings, session_factory, source, dev_login_enabled=True)) as c:
        ta = c.post("/api/dev/login", json={"email": "a@x.co"}).json()["access_token"]
        tb = c.post("/api/dev/login", json={"email": "b@x.co"}).json()["access_token"]
        ha, hb = ({"Authorization": f"Bearer {t}"} for t in (ta, tb))
        sid_a = c.get("/api/sellers", headers=ha).json()[0]["id"]
        assert c.get(f"/api/portal/sellers/{sid_a}/summary", headers=hb).status_code == 403


def test_forged_or_missing_token_rejected(settings, session_factory, source):
    import jwt
    forged = jwt.encode({"sub": "x", "aud": "authenticated", "iss": "gem-local-dev-login", "role": "authenticated",
                         "iat": 1, "exp": 4102444800}, b"w" * 32, algorithm="HS256")
    with TestClient(_app(settings, session_factory, source, dev_login_enabled=True)) as c:
        assert c.get("/api/sellers", headers={"Authorization": f"Bearer {forged}"}).status_code == 401
        assert c.get("/api/sellers").status_code == 401


def test_remote_client_refused(settings, session_factory, source):
    app = _app(settings, session_factory, source, dev_login_enabled=True)
    with TestClient(app, client=("203.0.113.5", 50000)) as c:
        assert c.post("/api/dev/login", json={"email": "a@b.co"}).status_code == 403


def test_bad_email_rejected(settings, session_factory, source):
    with TestClient(_app(settings, session_factory, source, dev_login_enabled=True)) as c:
        assert c.post("/api/dev/login", json={"email": "not-an-email"}).status_code == 422
