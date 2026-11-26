from uuid import UUID
from unittest.mock import Mock

from app.modules.content.infrastructure.repositories.languages import LanguageRepository
from app.modules.learner.infrastructure.profiles import ProfileRepository
from app.modules.learner.infrastructure.user_language_preferences import (
    UserLanguagePreferenceRepository,
)


USER_ID = UUID("11111111-1111-1111-1111-111111111111")


class Result:
    def __init__(self, data):
        self.data = data


class FakeQuery:
    def __init__(self, data):
        self.data = data
        self.calls = []

    def select(self, value):
        self.calls.append(("select", value))
        return self

    def update(self, value):
        self.calls.append(("update", value))
        return self

    def insert(self, value):
        self.calls.append(("insert", value))
        return self

    def upsert(self, value, **kwargs):
        self.calls.append(("upsert", value, kwargs))
        return self

    def eq(self, field, value):
        self.calls.append(("eq", field, value))
        return self

    def order(self, field, **kwargs):
        self.calls.append(("order", field, kwargs))
        return self

    def limit(self, value):
        self.calls.append(("limit", value))
        return self

    def execute(self):
        return Result(self.data)


class FakeSupabaseClient:
    def __init__(self, data):
        self.data = data
        self.schema_name = None
        self.table_name = None
        self.query = None
        self.queries = []

    def schema(self, name):
        self.schema_name = name
        return self

    def table(self, name):
        self.table_name = name
        self.query = FakeQuery(self.data)
        self.queries.append(self.query)
        return self.query


def test_language_repository_targets_v3_schema_and_maps_rows():
    client = FakeSupabaseClient(
        [
            {
                "code": "en",
                "name_en": "English",
                "name_native": "English",
                "script": "Latin",
                "is_active": True,
                "display_order": 1,
            }
        ]
    )
    repo = LanguageRepository(client)

    rows = repo.list_active()

    assert repo.qualified_table_name == "v3.languages"
    assert client.schema_name == "v3"
    assert client.table_name == "languages"
    assert rows[0].code == "en"
    assert ("eq", "is_active", True) in client.query.calls


def test_profile_repository_scopes_lookup_to_authenticated_user_id():
    client = FakeSupabaseClient(
        [
            {
                "id": str(USER_ID),
                "display_name": "Ada",
                "timezone": "UTC",
            }
        ]
    )
    repo = ProfileRepository(client)

    profile = repo.get_by_user_id(USER_ID)

    assert client.schema_name == "v3"
    assert client.table_name == "profiles"
    assert ("eq", "id", str(USER_ID)) in client.query.calls
    assert profile.id == USER_ID


def test_language_preference_repository_enforces_user_ownership_in_query():
    preference_id = UUID("33333333-3333-3333-3333-333333333333")
    client = FakeSupabaseClient(
        [
            {
                "id": str(preference_id),
                "user_id": str(USER_ID),
                "language_code": "en",
                "is_primary": True,
                "preferences": {},
            }
        ]
    )
    repo = UserLanguagePreferenceRepository(client)

    preference = repo.get_for_user(preference_id, USER_ID)

    assert client.schema_name == "v3"
    assert client.table_name == "user_language_preferences"
    assert ("eq", "id", str(preference_id)) in client.query.calls
    assert ("eq", "user_id", str(USER_ID)) in client.query.calls
    assert preference.user_id == USER_ID


def test_language_profile_upsert_uses_one_transaction_for_the_authenticated_user():
    client = Mock()
    schema = client.schema.return_value
    schema.rpc.return_value.execute.return_value = Result([{
        "id": "33333333-3333-3333-3333-333333333333",
        "user_id": str(USER_ID), "language_code": "ja", "support_language_code": "vi",
        "is_primary": True, "preferences": {},
    }])
    repo = UserLanguagePreferenceRepository(client)

    profile = repo.upsert_profile_for_user(
        user_id=USER_ID,
        learning_language="ja",
        support_language="vi",
    )

    client.schema.assert_called_once_with("v3")
    schema.table.assert_not_called()
    schema.rpc.assert_called_once_with("upsert_language_profile", {
        "p_user_id": str(USER_ID), "p_learning_language": "ja", "p_support_language": "vi", "p_extra": {},
    })
    assert profile.support_language_code == "vi"


