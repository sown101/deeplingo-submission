from datetime import datetime
from uuid import UUID

from app.modules.review.domain.models import (
    ReviewMode,
    ReviewState,
)
from app.platform.persistence import V3Repository


class ReviewStateRepository(V3Repository):
    table_name = "review_states"

    def get_for_user(
        self,
        *,
        user_id: UUID,
        concept_id: UUID,
        review_mode: ReviewMode = ReviewMode.CONCEPT_TO_MEANING,
    ) -> ReviewState | None:
        result = (
            self.table()
            .select("*")
            .eq("user_id", str(user_id))
            .eq("concept_id", str(concept_id))
            .eq("review_mode", review_mode.value)
            .limit(1)
            .execute()
        )
        rows = result.data or []
        return ReviewState(**rows[0]) if rows else None

    def next_due_by_concept(self, *, user_id: UUID, concept_ids: list[UUID],
                            recognition_only: bool = False) -> dict[UUID, datetime]:
        """Earliest due per Concept; Familiarize can select the same mode as graded Quick review."""
        if not concept_ids:
            return {}
        query = (
            self.table().select("concept_id,due_at").eq("user_id", str(user_id))
            .in_("concept_id", [str(item) for item in dict.fromkeys(concept_ids)])
        )
        if recognition_only:
            query = query.eq("review_mode", ReviewMode.CONCEPT_TO_MEANING.value)
        rows = query.execute().data or []
        due: dict[UUID, datetime] = {}
        for row in rows:
            if not row.get("due_at"):
                continue
            concept_id = UUID(str(row["concept_id"]))
            value = datetime.fromisoformat(str(row["due_at"]).replace("Z", "+00:00"))
            if concept_id not in due or value < due[concept_id]:
                due[concept_id] = value
        return due

    def list_due_for_user(
        self,
        *,
        user_id: UUID,
        due_at: datetime,
        limit: int = 50,
        review_mode: ReviewMode | None = None,
        concept_ids: list[UUID] | None = None,
        language_code: str | None = None,
    ) -> list[ReviewState]:
        """Due cards, earliest first; only one ReviewMode or language when given (the limit then counts those only)."""
        if concept_ids == []:
            return []
        query = self.table().select("*").eq("user_id", str(user_id)).lte("due_at", due_at.isoformat())
        if language_code is not None:
            query = query.eq("language_code", language_code)
        if review_mode is not None:
            query = query.eq("review_mode", review_mode.value)
        if concept_ids is not None:
            query = query.in_("concept_id", [str(concept_id) for concept_id in concept_ids])
        result = query.order("due_at").limit(limit).execute()
        return [ReviewState(**row) for row in (result.data or [])]

