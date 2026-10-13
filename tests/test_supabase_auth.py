"""Isolated security tests for Supabase JWT verification."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec

from app.core.supabase_auth import SupabaseTokenVerifier


@pytest.fixture
def auth_setup():
    private_key = ec.generate_private_key(ec.SECP256R1())

    verifier = SupabaseTokenVerifier(
        "https://xralyhnyoifdnlyqbokz.supabase.co"
    )

    class SigningKey:
        key = private_key.public_key()

    verifier.client.get_signing_key_from_jwt = (
        lambda token: SigningKey()
    )

    now = datetime.now(timezone.utc)

    claims = {
        "sub": str(uuid4()),
        "role": "authenticated",
        "aud": "authenticated",
        "iss": verifier.issuer,
        "iat": now,
        "exp": now + timedelta(minutes=10),
    }

    return verifier, private_key, claims


def make_token(claims, key):
    return jwt.encode(
        claims,
        key,
        algorithm="ES256",
        headers={"kid": "test-key"},
    )


def test_valid_authenticated_token(auth_setup):
    verifier, key, claims = auth_setup
    identity = verifier.verify(make_token(claims, key))
    assert identity.subject == claims["sub"]


@pytest.mark.parametrize("role", ["anon", "service_role", None])
def test_reject_non_user_roles(auth_setup, role):
    verifier, key, claims = auth_setup
    claims["role"] = role

    with pytest.raises(ValueError):
        verifier.verify(make_token(claims, key))


def test_reject_expired_token(auth_setup):
    verifier, key, claims = auth_setup
    claims["exp"] = datetime.now(timezone.utc) - timedelta(minutes=5)

    with pytest.raises(ValueError):
        verifier.verify(make_token(claims, key))


def test_reject_wrong_issuer(auth_setup):
    verifier, key, claims = auth_setup
    claims["iss"] = "https://invalid.example/auth/v1"

    with pytest.raises(ValueError):
        verifier.verify(make_token(claims, key))


def test_reject_wrong_audience(auth_setup):
    verifier, key, claims = auth_setup
    claims["aud"] = "other"

    with pytest.raises(ValueError):
        verifier.verify(make_token(claims, key))


def test_reject_missing_subject(auth_setup):
    verifier, key, claims = auth_setup
    del claims["sub"]

    with pytest.raises(ValueError):
        verifier.verify(make_token(claims, key))


def test_reject_invalid_signature(auth_setup):
    verifier, _, claims = auth_setup
    attacker_key = ec.generate_private_key(ec.SECP256R1())

    with pytest.raises(ValueError):
        verifier.verify(make_token(claims, attacker_key))


def test_reject_missing_token(auth_setup):
    verifier, _, _ = auth_setup

    with pytest.raises(ValueError):
        verifier.verify("")


def test_reject_hs256_token(auth_setup):
    verifier, _, claims = auth_setup

    token = jwt.encode(
        claims,
        "untrusted-test-secret-that-is-at-least-32-bytes-long",
        algorithm="HS256",
    )

    with pytest.raises(ValueError):
        verifier.verify(token)
