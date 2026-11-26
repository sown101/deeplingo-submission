from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.bootstrap.wiring.identity import get_jwt_verifier
from app.bootstrap.wiring.learner import get_learner_model_service
from app.modules.identity.contracts import CurrentUser
from app.modules.learner.domain.models import Profile, UserLanguagePreference
from app.modules.learner.application.commands import LearnerInitializationRequest
from app.modules.content.domain.catalog import Language
from app.modules.learner.application.learner_model import LearnerModelService
from app.main import app


USER_A = UUID("11111111-1111-1111-1111-111111111111")
USER_B = UUID("22222222-2222-2222-2222-222222222222")
CONCEPT_ID = UUID("33333333-3333-3333-3333-333333333333")


def current_user(user_id=USER_A):
    return CurrentUser(id=user_id, role="authenticated", claims={"app_metadata": {}})


class FakeProfiles:
    def __init__(self):
        self.rows = {
            USER_A: Profile(id=USER_A, display_name="A"),
            USER_B: Profile(id=USER_B, display_name="B"),
        }
        self.upserts = 0

    def get_by_user_id(self, user_id):
        return self.rows.get(user_id)

    def upsert_current_user(self, user_id, data=None):
        self.upserts += 1
        self.rows[user_id] = self.rows.get(user_id) or Profile(id=user_id, **(data or {}))
        return self.rows[user_id]


class FakeLanguages:
    def __init__(self):
        self.rows = {
            "en": Language(code="en", name_en="English", name_native="English", script="Latn", is_active=True, display_order=1),
            "ja": Language(code="ja", name_en="Japanese", name_native="日本語", script="Jpan", is_active=True, display_order=2),
        }

    def get_active(self, code):
        return self.rows.get(code)

    def list_active(self):
        return list(self.rows.values())


class FakePreferences:
    def __init__(self):
        self.rows = {
            (USER_A, "en"): UserLanguagePreference(id=uuid4(), user_id=USER_A, language_code="en", is_primary=True),
            (USER_B, "ja"): UserLanguagePreference(id=uuid4(), user_id=USER_B, language_code="ja", is_primary=True),
        }

    def list_for_user(self, user_id):
        return [row for (owner, _), row in self.rows.items() if owner == user_id]

    def upsert_for_user(self, *, user_id, language_code, data):
        row = UserLanguagePreference(
            id=self.rows.get((user_id, language_code), UserLanguagePreference(user_id=user_id, language_code=language_code)).id,
            user_id=user_id,
            language_code=language_code,
            **data,
        )
        self.rows[(user_id, language_code)] = row
        return row


def make_service():
    parts = {
        "profiles": FakeProfiles(),
        "languages": FakeLanguages(),
        "language_preferences": FakePreferences(),
    }
    return LearnerModelService(**parts), parts


def test_user_isolation_for_profile():
    service, _ = make_service()

    assert service.get_profile(current_user(USER_A)).id == USER_A
    assert service.get_profile(current_user(USER_B)).id == USER_B


def test_initialization_creates_missing_profile_only_for_current_user():
    service, parts = make_service()
    new_user_id = uuid4()

    result = service.initialize(current_user(new_user_id), language_codes=[], create_profile=True)

    assert result.profile_status == "created"
    assert parts["profiles"].rows[new_user_id].id == new_user_id


def test_request_models_reject_user_id_and_body_identity_injection():
    with pytest.raises(ValidationError):
        LearnerInitializationRequest.model_validate({"language_codes": ["en"], "user_id": str(USER_B)})


def test_get_requests_have_no_learner_state_side_effects():
    service, parts = make_service()

    service.get_profile(current_user(USER_A))

    assert parts["profiles"].upserts == 0


class AuthVerifier:
    def __init__(self, user_id=USER_A):
        self.user_id = user_id

    def verify(self, token: str):
        if token == "expired":
            from app.modules.identity.contracts import AuthenticationError

            raise AuthenticationError("expired")
        return current_user(self.user_id)


def test_learner_endpoint_requires_authentication():
    app.dependency_overrides.clear()
    client = TestClient(app)

    response = client.get("/api/v1/v3/learner/me/language-profile")

    assert response.status_code == 401
    app.dependency_overrides.clear()


def test_learner_endpoint_rejects_invalid_or_expired_token():
    app.dependency_overrides.clear()
    app.dependency_overrides[get_jwt_verifier] = lambda: AuthVerifier()
    client = TestClient(app)

    invalid = client.get("/api/v1/v3/learner/me/language-profile", headers={"Authorization": "Bearer not-a-jwt"})
    expired = client.get("/api/v1/v3/learner/me/language-profile", headers={"Authorization": "Bearer expired"})

    assert invalid.status_code == 401
    assert expired.status_code == 401
    app.dependency_overrides.clear()


class FakeEndpointService:
    def __init__(self):
        self.service, _ = make_service()

    def get_profile(self, current_user):
        return self.service.get_profile(current_user)

    def initialize(self, current_user, *, language_codes, create_profile=True):
        return self.service.initialize(current_user, language_codes=language_codes, create_profile=create_profile)


def test_endpoint_initialization_is_idempotent_carries_no_skill_states_and_rejects_unknown_language():
    app.dependency_overrides.clear()
    fake = FakeEndpointService()
    app.dependency_overrides[get_jwt_verifier] = lambda: AuthVerifier(USER_A)
    app.dependency_overrides[get_learner_model_service] = lambda: fake
    client = TestClient(app)

    first = client.post(
        "/api/v1/v3/learner/me/initialize",
        json={"language_codes": ["en"]},
        headers={"Authorization": "Bearer a.b.c"},
    )
    second = client.post(
        "/api/v1/v3/learner/me/initialize",
        json={"language_codes": ["en"]},
        headers={"Authorization": "Bearer a.b.c"},
    )
    unknown = client.post(
        "/api/v1/v3/learner/me/initialize",
        json={"language_codes": ["xx"]},
        headers={"Authorization": "Bearer a.b.c"},
    )

    assert first.status_code == 200
    assert first.json()["profile_status"] == second.json()["profile_status"] == "reused"
    assert set(first.json()) == {"user_id", "profile_status"}
    assert unknown.status_code == 422
    app.dependency_overrides.clear()
