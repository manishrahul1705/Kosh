"""HTTP-level tests for the Supabase authentication dependency."""

from unittest.mock import Mock

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.api.auth import get_current_user, get_token_verifier
from app.core.supabase_auth import AuthenticatedIdentity


@pytest.fixture
def client_and_verifier():
    app = FastAPI()

    verifier = Mock()

    app.dependency_overrides[get_token_verifier] = lambda: verifier

    @app.get("/protected")
    def protected(
        user: AuthenticatedIdentity = Depends(get_current_user),
    ):
        return {"user_id": user.subject}

    with TestClient(app) as client:
        yield client, verifier


def test_missing_token_returns_401(client_and_verifier):
    client, verifier = client_and_verifier

    response = client.get("/protected")

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    verifier.verify.assert_not_called()


def test_invalid_token_returns_401(client_and_verifier):
    client, verifier = client_and_verifier
    verifier.verify.side_effect = ValueError("Invalid token")

    response = client.get(
        "/protected",
        headers={"Authorization": "Bearer invalid-token"},
    )

    assert response.status_code == 401


def test_valid_token_returns_identity(client_and_verifier):
    client, verifier = client_and_verifier

    verifier.verify.return_value = AuthenticatedIdentity(
        subject="test-user-123",
        email="test@example.com",
        claims={"role": "authenticated"},
    )

    response = client.get(
        "/protected",
        headers={"Authorization": "Bearer valid-test-token"},
    )

    assert response.status_code == 200
    assert response.json() == {"user_id": "test-user-123"}
    verifier.verify.assert_called_once_with("valid-test-token")


@pytest.mark.parametrize(
    "authorization",
    [
        "Basic abc123",
        "Bearer",
        "Bearer ",
    ],
)
def test_malformed_authorization_returns_401(
    client_and_verifier,
    authorization,
):
    client, verifier = client_and_verifier

    response = client.get(
        "/protected",
        headers={"Authorization": authorization},
    )

    assert response.status_code == 401
    verifier.verify.assert_not_called()
