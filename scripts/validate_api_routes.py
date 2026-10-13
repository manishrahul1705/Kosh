"""Route-wide anonymous/auth checks with real JWT signatures and disposable tenants."""
import json, re, sys, inspect
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import jwt
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient
from sqlalchemy import select
from app.core.config import Settings
from app.database.session import build_engine, build_session_factory, run_migrations
from app.core.supabase_auth import SupabaseTokenVerifier
from app.api.auth import get_token_verifier
from app.main import create_app
from app.matching.service import MatchingService
from app.utils.dates import utcnow
from tests.matching_factories import make_seller, make_tender


def main():
    out = ROOT / "validation/routes-complete"
    out.mkdir(exist_ok=True)
    db_path = out / "staging.db"
    if db_path.exists():
        raise ValueError("Preserve earlier route evidence; use a new staging path")
    cfg = Settings(_env_file=None, database_url="sqlite:///" + db_path.as_posix(),
        auto_migrate=False, scheduler_enabled=False, startup_recovery_enabled=False,
        collect_on_startup=False, app_env="production", dev_login_enabled=False,
        supabase_url="https://route-tests.supabase.co", lock_file=str(out / "collection.lock"),
        document_storage_path=str(out / "documents"), debug_dir=str(out / "debug"), ai_provider="mock")
    run_migrations(cfg.resolved_database_url)
    engine = build_engine(cfg.resolved_database_url)
    factory = build_session_factory(engine)
    with factory() as db:
        tender = make_tender(db, bid="GEM/2026/B/9800001")
        a = make_seller(db, name="Route A", owner_subject="aaaaaaaa-1111-1111-1111-111111111111")
        b = make_seller(db, name="Route B", owner_subject="bbbbbbbb-1111-1111-1111-111111111111")
        aid, bid, tid = a.id, b.id, tender.id
        MatchingService(db).recalculate(now=utcnow())
    key = ec.generate_private_key(ec.SECP256R1())
    verifier = SupabaseTokenVerifier(cfg.supabase_url)
    verifier.client.get_signing_key_from_jwt = lambda _: SimpleNamespace(key=key.public_key())
    app = create_app(cfg, session_factory=factory)
    app.dependency_overrides[get_token_verifier] = lambda: verifier
    def token(**changes):
        now = datetime.now(timezone.utc)
        claims = {"sub": "aaaaaaaa-1111-1111-1111-111111111111", "role": "authenticated",
            "aud": "authenticated", "iss": verifier.issuer, "iat": now, "exp": now + timedelta(minutes=10)}
        claims.update(changes)
        return jwt.encode(claims, key, algorithm="ES256", headers={"kid": "disposable-route-key"})
    def dependency_names(d):
        return [getattr(x.call, "__name__", "") for x in d.dependencies] + [
            name for x in d.dependencies for name in dependency_names(x)]
    evidence = {"routes": [], "tenant_cases": [], "token_cases": [], "failures": []}
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/openapi.json").status_code == 200
        for route_path, operations in app.openapi()["paths"].items():
            names = []
            protected = any(operation.get("security") for method, operation in operations.items()
                            if method.lower() in ("get", "post", "put", "patch", "delete"))
            category = "public"
            if protected:
                category = "authenticated seller" if "/portal/" in route_path or "/sellers" in route_path else "authenticated"
                if any(prefix in route_path for prefix in ("/collection", "/documents", "/extractions", "/tender-fields", "/ai-analysis", "/corpus")):
                    category = "operator/permission protected"
            checks = []
            methods = [m.upper() for m in operations if m.lower() in ("get", "post", "put", "patch", "delete")]
            for method in sorted(methods):
                if method in ("HEAD", "OPTIONS"):
                    continue
                path = re.sub(r"\{[^}]+\}", "1", route_path)
                if protected:
                    for bearer in (None, "forged-token"):
                        headers = {"Authorization": "Bearer " + bearer} if bearer else {}
                        response = client.request(method, path, headers=headers, json={} if method != "GET" else None)
                        checks.append({"method": method, "auth": "forged" if bearer else "missing",
                                       "status": response.status_code})
                        if response.status_code != 401:
                            evidence["failures"].append({"path": path, "method": method, "status": response.status_code})
            evidence["routes"].append({"path": route_path, "category": category,
                "methods": sorted(methods), "dependencies": names, "checks": checks})
        for label, bearer in [("expired", token(exp=datetime.now(timezone.utc)-timedelta(minutes=5))),
            ("wrong issuer", token(iss="https://wrong.invalid/auth/v1")),
            ("wrong audience", token(aud="wrong")), ("wrong role", token(role="anon")), ("malformed", "broken")]:
            status = client.get("/api/tenders", headers={"Authorization": "Bearer " + bearer}).status_code
            evidence["token_cases"].append({"case": label, "status": status})
            assert status == 401
        headers = {"Authorization": "Bearer " + token()}
        for method, path in [("GET", f"/api/sellers/{bid}"),
            ("POST", f"/api/sellers/{bid}/attributes"),
            ("GET", f"/api/portal/sellers/{bid}/summary"),
            ("GET", f"/api/portal/sellers/{bid}/tenders"),
            ("GET", f"/api/portal/sellers/{bid}/tenders/{tid}"),
            ("POST", f"/api/portal/sellers/{bid}/matches/refresh"),
            ("GET", f"/api/portal/sellers/{bid}/tenders/{tid}/documents/1/versions/1/download")]:
            response = client.request(method, path, headers=headers,
                data={"key": "annual_turnover", "value_type": "NUMBER", "value_number": "1"} if method == "POST" else None)
            evidence["tenant_cases"].append({"method": method, "path": path, "status": response.status_code})
            assert response.status_code == 403
        assert client.get("/api/tenders", headers=headers, params={"search": "' OR 1=1 --"}).json()["total"] == 0
        assert client.post("/api/dev/login", json={"email": "test@example.invalid"}).status_code == 404
        evidence["sql_injection"] = "PASS: literal query produces zero matches"
        evidence["production_dev_login"] = "PASS: route absent"
    evidence["protected_route_count"] = sum(r["category"] != "public" for r in evidence["routes"])
    evidence["anonymous_and_forged_checks"] = sum(len(r["checks"]) for r in evidence["routes"])
    assert evidence["protected_route_count"] > 0 and evidence["anonymous_and_forged_checks"] > 0
    (out / "results.json").write_text(json.dumps(evidence, indent=2))
    print(json.dumps({k: v for k, v in evidence.items() if k != "routes"}))
    engine.dispose()
    return bool(evidence["failures"])


if __name__ == "__main__":
    raise SystemExit(main())
