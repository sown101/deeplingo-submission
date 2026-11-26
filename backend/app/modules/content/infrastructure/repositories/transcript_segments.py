from uuid import UUID

from app.modules.content.domain.catalog import TranscriptSegment
from app.platform.persistence import V3Repository, cached_read


class TranscriptSegmentRepository(V3Repository):
    table_name = "transcript_segments"

    def upsert_many(self, segments: list[dict]) -> list[TranscriptSegment]:
        if not segments:
            return []
        result = (
            self.table()
            .upsert(segments, on_conflict="transcript_id,sequence_number")
            .execute()
        )
        rows = result.data or []
        return sorted(
            [TranscriptSegment(**row) for row in rows],
            key=lambda item: item.sequence_number,
        )

    @cached_read
    def list_for_transcript(self, transcript_id: UUID) -> list[TranscriptSegment]:
        result = (
            self.table()
            .select("*")
            .eq("transcript_id", str(transcript_id))
            .order("sequence_number")
            .execute()
        )
        return [TranscriptSegment(**row) for row in (result.data or [])]

    @cached_read
    def list_head_for_transcript(self, transcript_id: UUID, *, limit: int) -> list[TranscriptSegment]:
        """The first ``limit`` segments in order, without reading the whole transcript."""
        result = (
            self.table()
            .select("*")
            .eq("transcript_id", str(transcript_id))
            .order("sequence_number")
            .limit(limit)
            .execute()
        )
        return [TranscriptSegment(**row) for row in (result.data or [])]

    def list_by_ids(self, segment_ids: list[UUID]) -> list[TranscriptSegment]:
        if not segment_ids:
            return []
        result = self.table().select("*").in_("id", [str(segment_id) for segment_id in segment_ids]).execute()
        return [TranscriptSegment(**row) for row in (result.data or [])]

    @cached_read
    def get_by_id(self, segment_id: UUID) -> TranscriptSegment | None:
        result = self.table().select("*").eq("id", str(segment_id)).limit(1).execute()
        rows = result.data or []
        return TranscriptSegment(**rows[0]) if rows else None

    def get_neighbor(
        self,
        *,
        transcript_id: UUID,
        sequence_number: int,
        offset: int,
    ) -> TranscriptSegment | None:
        target_sequence = sequence_number + offset
        if target_sequence < 1:
            return None
        result = (
            self.table()
            .select("*")
            .eq("transcript_id", str(transcript_id))
            .eq("sequence_number", target_sequence)
            .limit(1)
            .execute()
        )
        rows = result.data or []
        return TranscriptSegment(**rows[0]) if rows else None
