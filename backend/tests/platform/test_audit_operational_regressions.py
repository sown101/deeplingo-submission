from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from fastapi.testclient import TestClient
from jwt.exceptions import PyJWKClientConnectionError, PyJWKClientError

from app.main import app
from app.modules.identity.api.dependencies import get_current_user
from app.modules.identity.infrastructure.jwt_verifier import SupabaseJWTVerifier
from app.platform.config import settings
from app.platform.rate_limit import MemoryWindowStore


def test_memory_rate_limiter_expires_inactive_subjects_with_their_own_windows():
    store = MemoryWindowStore()
    assert store.hit("short", limit=1, window=5, now=0)
    assert store.hit("long", limit=1, window=120, now=0)
    assert store.hit("sweep", limit=1, window=5, now=60)
    assert "short" not in store._events
    assert not store.hit("long", limit=1, window=120, now=60)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure,status", [(PyJWKClientConnectionError, 503), (PyJWKClientError, 401)])
async def test_auth_outage_and_unknown_key_are_distinguished(failure, status):
    def get_key(_):
        raise failure("synthetic JWKS error")

    verifier = SupabaseJWTVerifier(settings.model_copy(update={"SUPABASE_JWT_VERIFICATION_MODE": "jwks"}))
    verifier._jwks_client = SimpleNamespace(get_signing_key_from_jwt=get_key)
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="one.two.three")
    with pytest.raises(HTTPException) as raised:
        await get_current_user(credentials, verifier)
    assert raised.value.status_code == status


def test_health_checks_the_database_with_a_short_read_timeout(monkeypatch):
    monkeypatch.setattr(settings, "SUPABASE_URL", "https://database.example.invalid")
    monkeypatch.setattr(settings, "SUPABASE_SERVICE_ROLE_KEY", "synthetic")
    calls = []

    def read(url, *, timeout, **_):
        calls.append((url, timeout))
        raise httpx.ConnectError("synthetic DB failure")

    monkeypatch.setattr(httpx, "get", read)
    response = TestClient(app).get("/health")
    assert response.status_code == 503
    assert response.json()["services"]["supabase"] == "disconnected"
    assert calls and 0 < calls[0][1] < 3
