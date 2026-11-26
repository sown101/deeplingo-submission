from uuid import UUID

from app.modules.content.domain.knowledge import LearningObject
from app.platform.persistence import V3Repository, cached_read


class LearningObjectRepository(V3Repository):
    table_name = "learning_objects"

    @cached_read
    def list_for_video(self, video_id: UUID) -> list[LearningObject]:
        result = self.table().select("*").eq("video_id", str(video_id)).execute()
        return [LearningObject(**row) for row in (result.data or [])]

    def list_for_videos(self, video_ids: list[UUID]) -> list[LearningObject]:
        """All occurrences of several videos in one round trip."""
        if not video_ids:
            return []
        result = self.table().select("*").in_("video_id", [str(video_id) for video_id in video_ids]).execute()
        return [LearningObject(**row) for row in (result.data or [])]

    def list_for_videos_concepts(self, video_ids: list[UUID], concept_ids: list[UUID]) -> list[LearningObject]:
        """Occurrences of these Concepts in these videos only, in one round trip."""
        if not video_ids or not concept_ids:
            return []
        result = (
            self.table().select("*")
            .in_("video_id", [str(video_id) for video_id in video_ids])
            .in_("concept_id", [str(concept_id) for concept_id in concept_ids])
            .execute()
        )
        return [LearningObject(**row) for row in (result.data or [])]

    @cached_read
    def get_by_id(self, learning_object_id: UUID) -> LearningObject | None:
        result = self.table().select("*").eq("id", str(learning_object_id)).limit(1).execute()
        rows = result.data or []
        return LearningObject(**rows[0]) if rows else None

    def list_for_concept(self, concept_id: UUID) -> list[LearningObject]:
        result = self.table().select("*").eq("concept_id", str(concept_id)).execute()
        return [LearningObject(**row) for row in (result.data or [])]

    def get_by_occurrence(
        self,
        *,
        concept_id: UUID,
        transcript_segment_id: UUID,
        occurrence_index: int,
    ) -> LearningObject | None:
        result = (
            self.table()
            .select("*")
            .eq("concept_id", str(concept_id))
            .eq("transcript_segment_id", str(transcript_segment_id))
            .eq("occurrence_index", occurrence_index)
            .limit(1)
            .execute()
        )
        rows = result.data or []
        return LearningObject(**rows[0]) if rows else None

    def list_for_segment_concept(self, *, concept_id: UUID, transcript_segment_id: UUID) -> list[LearningObject]:
        result = (
            self.table()
            .select("*")
            .eq("concept_id", str(concept_id))
            .eq("transcript_segment_id", str(transcript_segment_id))
            .execute()
        )
        return [LearningObject(**row) for row in (result.data or [])]

    def get_by_span(
        self, *, concept_id: UUID, transcript_segment_id: UUID,
        start_codepoint: int, end_codepoint: int,
    ) -> LearningObject | None:
        result = (
            self.table()
            .select("*")
            .eq("concept_id", str(concept_id))
            .eq("transcript_segment_id", str(transcript_segment_id))
            .eq("start_codepoint", start_codepoint)
            .eq("end_codepoint", end_codepoint)
            .limit(1)
            .execute()
        )
        rows = result.data or []
        return LearningObject(**rows[0]) if rows else None

    def upsert_by_occurrence(self, data: dict) -> LearningObject:
        start, end = data.get("start_codepoint"), data.get("end_codepoint")
        if (not isinstance(start, int) or not isinstance(end, int)
                or start < 0 or end <= start or not data.get("evidence_text")):
            raise ValueError("New LearningObject requires a valid occurrence span")
        existing = self.get_by_occurrence(
            concept_id=UUID(str(data["concept_id"])),
            transcript_segment_id=UUID(str(data["transcript_segment_id"])),
            occurrence_index=data["occurrence_index"],
        )
        if existing is not None and (
            existing.start_codepoint != start or existing.end_codepoint != end
            or existing.evidence_text != data["evidence_text"]
        ):
            raise ValueError("Cannot move an existing LearningObject occurrence")
        result = (
            self.table()
            .upsert(data, on_conflict="concept_id,transcript_segment_id,occurrence_index")
            .execute()
        )
        return LearningObject(**result.data[0])

    def update_enrichment(self, learning_object_id: UUID, data: dict) -> LearningObject:
        result = (
            self.table()
            .update(data)
            .eq("id", str(learning_object_id))
            .execute()
        )
        rows = result.data or []
        return LearningObject(**rows[0]) if rows else None

    def record_sense_review(self, learning_object_id: UUID, *, target_language_code: str, review: dict,
                            raw_ai_diagnostics: dict) -> LearningObject | None:
        return self.update_enrichment(learning_object_id, {"raw_ai_diagnostics": raw_ai_diagnostics})
