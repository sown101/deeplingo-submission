from datetime import UTC, datetime
from uuid import UUID

from app.modules.content.domain.workspace import LearnerVideoWorkspace
from app.platform.persistence import V3Repository


class LearnerVideoWorkspaceRepository(V3Repository):
    """One row per Library item (M1 S1). Each save writes only its own columns."""

    table_name = "learner_video_workspaces"

    def get_for_user(self, *, library_item_id: UUID, user_id: UUID) -> LearnerVideoWorkspace | None:
        result = (
            self.table()
            .select("*")
            .eq("library_item_id", str(library_item_id))
            .eq("user_id", str(user_id))
            .limit(1)
            .execute()
        )
        rows = result.data or []
        return LearnerVideoWorkspace(**rows[0]) if rows else None

    def list_recent_for_user(self, *, user_id: UUID, limit: int) -> list[LearnerVideoWorkspace]:
        """The learner's workspaces, most recently saved first."""
        result = (
            self.table()
            .select("*")
            .eq("user_id", str(user_id))
            .order("updated_at", desc=True)
            .limit(limit)
            .execute()
        )
        return [LearnerVideoWorkspace(**row) for row in (result.data or [])]

    def save_position(self, *, library_item_id: UUID, user_id: UUID, position_ms: int) -> LearnerVideoWorkspace:
        return self._upsert(library_item_id, user_id, {"position_ms": position_ms})

    def save_region(
        self,
        *,
        library_item_id: UUID,
        user_id: UUID,
        transcript_id: UUID,
        start_segment_id: UUID,
        end_segment_id: UUID,
    ) -> LearnerVideoWorkspace:
        return self._upsert(library_item_id, user_id, {
            "region_transcript_id": str(transcript_id),
            "region_start_segment_id": str(start_segment_id),
            "region_end_segment_id": str(end_segment_id),
        })

    def _upsert(self, library_item_id: UUID, user_id: UUID, columns: dict) -> LearnerVideoWorkspace:
        # PostgREST merge-duplicates updates only the columns sent, so a position save
        # keeps the region and the reverse. The composite foreign key pins user_id to the
        # Library item's owner.
        result = (
            self.table()
            .upsert(
                {
                    "library_item_id": str(library_item_id),
                    "user_id": str(user_id),
                    **columns,
                    "updated_at": datetime.now(UTC).isoformat(),
                },
                on_conflict="library_item_id",
            )
            .execute()
        )
        return LearnerVideoWorkspace(**result.data[0])
