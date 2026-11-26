from uuid import UUID

from app.modules.learner.domain.models import UserLanguagePreference
from app.platform.persistence import V3Repository


class UserLanguagePreferenceRepository(V3Repository):
    table_name = "user_language_preferences"

    def list_for_user(self, user_id: UUID) -> list[UserLanguagePreference]:
        result = (
            self.table()
            .select("*")
            .eq("user_id", str(user_id))
            .order("is_primary", desc=True)
            .execute()
        )
        return [UserLanguagePreference(**row) for row in (result.data or [])]

    def get_for_user(self, preference_id: UUID, user_id: UUID) -> UserLanguagePreference | None:
        result = (
            self.table()
            .select("*")
            .eq("id", str(preference_id))
            .eq("user_id", str(user_id))
            .limit(1)
            .execute()
        )
        rows = result.data or []
        return UserLanguagePreference(**rows[0]) if rows else None

    def get_by_language_for_user(self, *, user_id: UUID, language_code: str) -> UserLanguagePreference | None:
        result = (
            self.table()
            .select("*")
            .eq("user_id", str(user_id))
            .eq("language_code", language_code)
            .limit(1)
            .execute()
        )
        rows = result.data or []
        return UserLanguagePreference(**rows[0]) if rows else None

    def get_profile_for_user(self, user_id: UUID) -> UserLanguagePreference | None:
        primary = (
            self.table()
            .select("*")
            .eq("user_id", str(user_id))
            .eq("is_primary", True)
            .limit(1)
            .execute()
        )
        rows = primary.data or []
        if rows:
            return UserLanguagePreference(**rows[0])
        preferences = self.list_for_user(user_id)
        return preferences[0] if preferences else None

    def upsert_profile_for_user(
        self,
        *,
        user_id: UUID,
        learning_language: str,
        support_language: str,
        extra: dict | None = None,
    ) -> UserLanguagePreference:
        result = self.client.schema(self.schema).rpc("upsert_language_profile", {
            "p_user_id": str(user_id), "p_learning_language": learning_language,
            "p_support_language": support_language, "p_extra": extra or {},
        }).execute()
        return UserLanguagePreference(**result.data[0])
