from datetime import datetime, timedelta, timezone
from uuid import UUID

import jwt
import pytest
from fastapi.testclient import TestClient

from app.bootstrap.wiring.identity import get_jwt_verifier
from app.bootstrap.wiring.content import get_language_catalog_service
from app.bootstrap.wiring.learner import get_learner_model_service
from app.platform.config import Settings
from app.modules.identity.contracts import AuthenticationError, CurrentUser
from app.modules.identity.infrastructure.jwt_verifier import SupabaseJWTVerifier
from app.modules.content.domain.catalog import Language
from app.modules.learner.application.views import LearnerLanguageProfile
from app.main import app


USER_A = UUID("11111111-1111-1111-1111-111111111111")
USER_B = UUID("22222222-2222-2222-2222-222222222222")


class FakeVerifier:
    def __init__(self, user_id: UUID = USER_A, *, fail: bool = False):
        self.user_id = user_id
        self.fail = fail

    def verify(self, token: str) -> CurrentUser:
        if self.fail:
            raise AuthenticationError("invalid")
        return CurrentUser(
            id=self.user_id,
            role="authenticated",
            email="user@example.com",
            claims={"raw": "claim-value"},
        )


class FakeFoundationService:
    def list_languages(self):
        return [
            Language(
                code="en",
                name_en="English",
                name_native="English",
                script="Latin",
                is_active=True,
                display_order=1,
            )
        ]

    def __init__(self):
        self.seen_user = None

    def get_language_profile(self, current_user: CurrentUser):
        self.seen_user = current_user
        return LearnerLanguageProfile(learning_language="en", support_language="vi", is_complete=True)


@pytest.fixture(autouse=True)
def clear_overrides():
    app.dependency_overrides.clear()
    yield
    app.dependency_overrides.clear()


PROTECTED = "/api/v1/v3/learner/me/language-profile"
FOUNDATION = FakeFoundationService()


@pytest.fixture
def client():
    FOUNDATION.seen_user = None
    app.dependency_overrides[get_language_catalog_service] = lambda: FOUNDATION
    app.dependency_overrides[get_learner_model_service] = lambda: FOUNDATION
    return TestClient(app)


def authorize(verifier: FakeVerifier):
    app.dependency_overrides[get_jwt_verifier] = lambda: verifier


def test_missing_authorization_header_returns_401(client):
    response = client.get(PROTECTED)

    assert response.status_code == 401


def test_malformed_token_returns_401(client):
    authorize(FakeVerifier())

    response = client.get(PROTECTED, headers={"Authorization": "Bearer malformed"})

    assert response.status_code == 401


def test_invalid_bearer_token_returns_401(client):
    authorize(FakeVerifier(fail=True))

    response = client.get(PROTECTED, headers={"Authorization": "Bearer a.b.c"})

    assert response.status_code == 401


def test_expired_token_returns_401_from_verifier():
    secret = "unit-test-secret"
    config = Settings(
        SUPABASE_URL="https://project.supabase.co",
        SUPABASE_JWT_VERIFICATION_MODE="hs256",
        SUPABASE_JWT_SECRET=secret,
    )
    token = jwt.encode(
        {
            "sub": str(USER_A),
            "role": "authenticated",
            "iss": "https://project.supabase.co/auth/v1",
            "aud": "authenticated",
            "exp": datetime.now(timezone.utc) - timedelta(minutes=1),
        },
        secret,
        algorithm="HS256",
    )

    with pytest.raises(AuthenticationError):
        SupabaseJWTVerifier(config).verify(token)


def test_signed_valid_token_resolves_current_user_from_verifier():
    secret = "unit-test-secret"
    config = Settings(
        SUPABASE_URL="https://project.supabase.co",
        SUPABASE_JWT_VERIFICATION_MODE="hs256",
        SUPABASE_JWT_SECRET=secret,
    )
    token = jwt.encode(
        {
            "sub": str(USER_A),
            "role": "authenticated",
            "email": "user@example.com",
            "iss": "https://project.supabase.co/auth/v1",
            "aud": "authenticated",
            "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
        },
        secret,
        algorithm="HS256",
    )

    current_user = SupabaseJWTVerifier(config).verify(token)

    assert current_user.id == USER_A
    assert current_user.email == "user@example.com"


def test_invalid_signature_is_rejected_by_verifier():
    config = Settings(
        SUPABASE_URL="https://project.supabase.co",
        SUPABASE_JWT_VERIFICATION_MODE="hs256",
        SUPABASE_JWT_SECRET="expected-secret",
    )
    token = jwt.encode(
        {
            "sub": str(USER_A),
            "role": "authenticated",
            "iss": "https://project.supabase.co/auth/v1",
            "aud": "authenticated",
            "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
        },
        "wrong-secret",
        algorithm="HS256",
    )

    with pytest.raises(AuthenticationError):
        SupabaseJWTVerifier(config).verify(token)


def test_valid_token_resolves_current_user_and_does_not_return_raw_claims(client):
    authorize(FakeVerifier())

    response = client.get(PROTECTED, headers={"Authorization": "Bearer a.b.c"})

    assert response.status_code == 200
    assert FOUNDATION.seen_user.id == USER_A and FOUNDATION.seen_user.role == "authenticated"
    assert "claim-value" not in response.text and "service_role" not in response.text


def test_user_a_cannot_select_user_b_language_profile(client):
    authorize(FakeVerifier(USER_A))

    response = client.get(f"{PROTECTED}?user_id={USER_B}", headers={"Authorization": "Bearer a.b.c"})

    assert response.status_code == 422
    assert FOUNDATION.seen_user is None


def test_user_a_reads_user_a_language_profile(client):
    authorize(FakeVerifier(USER_A))

    response = client.get(PROTECTED, headers={"Authorization": "Bearer a.b.c"})

    assert response.status_code == 200
    assert FOUNDATION.seen_user.id == USER_A


def test_public_language_data_is_accessible_without_auth(client):
    response = client.get("/api/v1/v3/languages")

    assert response.status_code == 200
    assert response.json()[0]["code"] == "en"


def test_protected_profile_data_requires_authentication(client):
    response = client.get("/api/v1/v3/learner/me/language-profile")

    assert response.status_code == 401


def test_service_role_bearer_tokens_are_not_valid_user_auth():
    secret = "unit-test-secret"
    config = Settings(
        SUPABASE_URL="https://project.supabase.co",
        SUPABASE_JWT_VERIFICATION_MODE="hs256",
        SUPABASE_JWT_SECRET=secret,
    )
    token = jwt.encode(
        {
            "sub": str(USER_A),
            "role": "service_role",
            "iss": "https://project.supabase.co/auth/v1",
            "aud": "authenticated",
            "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
        },
        secret,
        algorithm="HS256",
    )

    with pytest.raises(AuthenticationError):
        SupabaseJWTVerifier(config).verify(token)
