from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.bootstrap.wiring.identity import get_jwt_verifier
from app.bootstrap.wiring.learner import get_learner_model_service
from app.modules.identity.contracts import CurrentUser
from app.modules.learner.application.views import LearnerLanguageProfile
from app.modules.learner.application.commands import LearnerLanguageProfileUpdate
from app.modules.content.domain.catalog import Language
from app.modules.learner.domain.models import UserLanguagePreference
from app.modules.learner.application.learner_model import LearnerModelError, LearnerModelService
from app.main import app


USER_A = UUID("11111111-1111-1111-1111-111111111111")
USER_B = UUID("22222222-2222-2222-2222-222222222222")


class FakeVerifier:
    def __init__(self, user_id: UUID = USER_A):
        self.user_id = user_id

    def verify(self, token: str) -> CurrentUser:
        return CurrentUser(id=self.user_id, role="authenticated", claims={})


class FakeLanguages:
    active = {"en", "vi", "zh", "ja", "ko", "th", "ar", "hi", "ru"}

    def get_active(self, code: str):
        if code not in self.active:
            return None
        return Language(
            code=code,
            name_en=code,
            name_native=code,
            script="test",
            is_active=True,
            display_order=1,
        )


class FakePreferences:
    def __init__(self):
        self.rows: dict[tuple[UUID, str], UserLanguagePreference] = {}

    def get_profile_for_user(self, user_id: UUID):
        owned = [row for (owner, _), row in self.rows.items() if owner == user_id]
        primary = next((row for row in owned if row.is_primary), None)
        return primary or (owned[0] if owned else None)

    def upsert_profile_for_user(
        self,
        *,
        user_id: UUID,
        learning_language: str,
        support_language: str,
    ):
        for key, row in list(self.rows.items()):
            if key[0] == user_id and row.is_primary:
                self.rows[key] = row.model_copy(update={"is_primary": False})
        key = (user_id, learning_language)
        row = self.rows.get(
            key,
            UserLanguagePreference(
                id=uuid4(),
                user_id=user_id,
                language_code=learning_language,
            ),
        ).model_copy(
            update={
                "support_language_code": support_language,
                "is_primary": True,
            }
        )
        self.rows[key] = row
        return row


def make_service(preferences: FakePreferences | None = None) -> tuple[LearnerModelService, FakePreferences]:
    preferences = preferences or FakePreferences()
    return (
        LearnerModelService(
            profiles=None,
            languages=FakeLanguages(),
            language_preferences=preferences,
        ),
        preferences,
    )


def current_user(user_id: UUID = USER_A) -> CurrentUser:
    return CurrentUser(id=user_id, role="authenticated", claims={})


def test_existing_learning_language_is_preserved_as_incomplete_profile():
    service, preferences = make_service()
    preferences.rows[(USER_A, "ja")] = UserLanguagePreference(
        id=uuid4(),
        user_id=USER_A,
        language_code="ja",
        is_primary=True,
    )

    profile = service.get_language_profile(current_user())

    assert profile == LearnerLanguageProfile(
        learning_language="ja",
        support_language=None,
        is_complete=False,
    )


def test_save_is_repeatable_and_support_language_can_equal_learning_language():
    service, preferences = make_service()
    request = LearnerLanguageProfileUpdate(learning_language=" JA ", support_language="ja")

    first = service.update_language_profile(current_user(), request)
    second = service.update_language_profile(current_user(), request)

    assert first == second
    assert second.is_complete is True
    assert len(preferences.rows) == 1


def test_changes_preserve_old_learning_rows_and_do_not_cross_users():
    service, preferences = make_service()
    service.update_language_profile(
        current_user(USER_A),
        LearnerLanguageProfileUpdate(learning_language="ja", support_language="vi"),
    )
    service.update_language_profile(
        current_user(USER_B),
        LearnerLanguageProfileUpdate(learning_language="ko", support_language="en"),
    )
    changed_support = service.update_language_profile(
        current_user(USER_A),
        LearnerLanguageProfileUpdate(learning_language="ja", support_language="en"),
    )
    changed_learning = service.update_language_profile(
        current_user(USER_A),
        LearnerLanguageProfileUpdate(learning_language="zh", support_language="vi"),
    )

    assert changed_support.support_language == "en"
    assert changed_learning.learning_language == "zh"
    assert (USER_A, "ja") in preferences.rows
    assert service.get_language_profile(current_user(USER_B)).learning_language == "ko"


def test_invalid_or_inactive_language_is_rejected():
    service, _ = make_service()

    with pytest.raises(LearnerModelError, match="Unknown or inactive language"):
        service.update_language_profile(
            current_user(),
            LearnerLanguageProfileUpdate(learning_language="xx", support_language="vi"),
        )


class FakeLanguageProfileService:
    def __init__(self):
        self.profiles: dict[UUID, LearnerLanguageProfile] = {}
        self.last_user: UUID | None = None

    def get_language_profile(self, user: CurrentUser):
        self.last_user = user.id
        return self.profiles.get(user.id, LearnerLanguageProfile())

    def update_language_profile(self, user: CurrentUser, request: LearnerLanguageProfileUpdate):
        self.last_user = user.id
        profile = LearnerLanguageProfile(
            learning_language=request.learning_language,
            support_language=request.support_language,
            is_complete=True,
        )
        self.profiles[user.id] = profile
        return profile


@pytest.fixture(autouse=True)
def clear_overrides():
    app.dependency_overrides.clear()
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def api():
    service = FakeLanguageProfileService()
    app.dependency_overrides[get_learner_model_service] = lambda: service
    return TestClient(app), service


def authorize(user_id: UUID = USER_A):
    app.dependency_overrides[get_jwt_verifier] = lambda: FakeVerifier(user_id)


def test_language_profile_requires_authentication(api):
    client, _ = api

    response = client.get("/api/v1/v3/learner/me/language-profile")

    assert response.status_code == 401


def test_api_uses_current_user_and_rejects_cross_user_query(api):
    client, service = api
    authorize(USER_A)

    response = client.put(
        "/api/v1/v3/learner/me/language-profile",
        headers={"Authorization": "Bearer a.b.c"},
        json={"learning_language": "ja", "support_language": "vi"},
    )
    forbidden = client.get(
        f"/api/v1/v3/learner/me/language-profile?user_id={USER_B}",
        headers={"Authorization": "Bearer a.b.c"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "learning_language": "ja",
        "support_language": "vi",
        "is_complete": True,
        # L1a added two additive fields to the language profile.
        "declared_level": None,
        "daily_new_limit": 10,
    }
    assert service.last_user == USER_A
    assert forbidden.status_code == 422


def test_api_rejects_body_user_id_and_cross_user_read_is_isolated(api):
    client, service = api
    authorize(USER_A)
    rejected = client.put(
        "/api/v1/v3/learner/me/language-profile",
        headers={"Authorization": "Bearer a.b.c"},
        json={
            "user_id": str(USER_B),
            "learning_language": "ja",
            "support_language": "vi",
        },
    )
    service.profiles[USER_B] = LearnerLanguageProfile(
        learning_language="ko",
        support_language="en",
        is_complete=True,
    )
    read = client.get(
        "/api/v1/v3/learner/me/language-profile",
        headers={"Authorization": "Bearer a.b.c"},
    )

    assert rejected.status_code == 422
    assert read.status_code == 200
    assert read.json()["learning_language"] is None
