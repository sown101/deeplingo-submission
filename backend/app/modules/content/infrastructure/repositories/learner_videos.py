from datetime import UTC, datetime
from uuid import UUID

from app.modules.content.domain.library import LearnerVideo
from app.platform.persistence import V3Repository


class LearnerVideoRepository(V3Repository):
    table_name = "learner_videos"

    def upsert_for_user(self, *, user_id: UUID, video_id: UUID) -> LearnerVideo:
        updated_at = datetime.now(UTC).isoformat()
        result = (
            self.table()
            .upsert(
                {
                    "user_id": str(user_id),
                    "video_id": str(video_id),
                    "updated_at": updated_at,
                },
                on_conflict="user_id,video_id",
            )
            .execute()
        )
        return LearnerVideo(**result.data[0])

    def get_for_user(self, *, library_item_id: UUID, user_id: UUID) -> LearnerVideo | None:
        result = (
            self.table()
            .select("*")
            .eq("id", str(library_item_id))
            .eq("user_id", str(user_id))
            .limit(1)
            .execute()
        )
        rows = result.data or []
        return LearnerVideo(**rows[0]) if rows else None

    def list_for_user(self, user_id: UUID, *, limit: int = 50) -> list[LearnerVideo]:
        result = (
            self.table()
            .select("*")
            .eq("user_id", str(user_id))
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        return [LearnerVideo(**row) for row in (result.data or [])]
