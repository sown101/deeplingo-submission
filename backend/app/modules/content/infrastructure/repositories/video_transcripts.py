from uuid import UUID

from app.modules.content.domain.catalog import VideoTranscript
from app.platform.persistence import V3Repository, cached_read


class VideoTranscriptRepository(V3Repository):
    table_name = "video_transcripts"

    def upsert_track(self, data: dict) -> VideoTranscript:
        result = (
            self.table()
            .upsert(data, on_conflict="video_id,language_code,source")
            .execute()
        )
        return VideoTranscript(**result.data[0])

    @cached_read
    def list_for_video(self, video_id: UUID) -> list[VideoTranscript]:
        result = self.table().select("*").eq("video_id", str(video_id)).execute()
        return [VideoTranscript(**row) for row in (result.data or [])]

    def list_for_videos(self, video_ids: list[UUID]) -> list[VideoTranscript]:
        if not video_ids:
            return []
        result = self.table().select("*").in_("video_id", [str(video_id) for video_id in video_ids]).execute()
        return [VideoTranscript(**row) for row in (result.data or [])]

    @cached_read
    def get_by_id(self, transcript_id: UUID) -> VideoTranscript | None:
        result = self.table().select("*").eq("id", str(transcript_id)).limit(1).execute()
        rows = result.data or []
        return VideoTranscript(**rows[0]) if rows else None
