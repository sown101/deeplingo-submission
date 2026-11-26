from uuid import UUID

from app.modules.learner.domain.models import Profile
from app.platform.persistence import V3Repository


class ProfileRepository(V3Repository):
    table_name = "profiles"

    def get_by_user_id(self, user_id: UUID) -> Profile | None:
        result = self.table().select("*").eq("id", str(user_id)).limit(1).execute()
        rows = result.data or []
        return Profile(**rows[0]) if rows else None

    def upsert_current_user(self, user_id: UUID, data: dict | None = None) -> Profile:
        payload = {"id": str(user_id), **(data or {})}
        result = self.table().upsert(payload, on_conflict="id").execute()
        return Profile(**result.data[0])
