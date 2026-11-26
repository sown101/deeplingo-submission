"""SEC-04: tokens with unknown `kid` must not refetch the JWKS on every request.

The real verifier and PyJWKClient run against an in-memory JWKS; no network is used.
"""
import io
import json
import urllib.request
from datetime import datetime, timedelta, timezone
from uuid import UUID

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from jwt.algorithms import ECAlgorithm

from app.modules.identity.contracts import AuthenticationError
from app.modules.identity.infrastructure.jwt_verifier import SupabaseJWTVerifier
from app.platform.config import Settings

USER = UUID("11111111-1111-1111-1111-111111111111")
ISSUER = "https://project.supabase.co/auth/v1"


@pytest.fixture
def signing_key():
    return ec.generate_private_key(ec.SECP256R1())


@pytest.fixture
def fetches(monkeypatch, signing_key):
    jwk = ECAlgorithm.to_jwk(signing_key.public_key(), as_dict=True)
    jwks = {"keys": [{**jwk, "kid": "current", "use": "sig", "alg": "ES256"}]}
    calls = []

    def fake_open(self, request, *args, **kwargs):
        calls.append(getattr(request, "full_url", request))
        return io.BytesIO(json.dumps(jwks).encode())

    # Both urlopen() and PyJWKClient's own opener go through OpenerDirector.open.
    monkeypatch.setattr(urllib.request.OpenerDirector, "open", fake_open)
    return calls


def _verifier() -> SupabaseJWTVerifier:
    return SupabaseJWTVerifier(Settings(
        SUPABASE_URL="https://project.supabase.co",
        SUPABASE_JWT_VERIFICATION_MODE="jwks",
    ))


def _token(key, kid: str) -> str:
    claims = {
        "sub": str(USER),
        "role": "authenticated",
        "iss": ISSUER,
        "aud": "authenticated",
        "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
    }
    return jwt.encode(claims, key, algorithm="ES256", headers={"kid": kid})


def test_valid_token_verifies_against_cached_jwks(signing_key, fetches):
    verifier = _verifier()

    assert verifier.verify(_token(signing_key, "current")).id == USER
    assert verifier.verify(_token(signing_key, "current")).id == USER
    assert len(fetches) == 1


def test_unknown_kids_do_not_refetch_jwks_per_request(signing_key, fetches):
    verifier = _verifier()
    verifier.verify(_token(signing_key, "current"))
    attacker_key = ec.generate_private_key(ec.SECP256R1())

    for index in range(6):
        with pytest.raises(AuthenticationError):
            verifier.verify(_token(attacker_key, f"unknown-{index}"))

    # One warm-up fetch; the refresh cooldown absorbs every unknown kid after it.
    assert len(fetches) == 1
