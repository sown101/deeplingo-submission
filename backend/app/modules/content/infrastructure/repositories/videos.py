from datetime import UTC, datetime
from uuid import UUID

from app.modules.content.domain.catalog import Video
from app.platform.persistence import V3Repository, cached_read


class VideoRepository(V3Repository):
    table_name = "videos"

    def upsert_by_source_external(self, data: dict) -> Video:
        result = (
            self.table()
            .upsert(data, on_conflict="source,external_video_id")
            .execute()
        )
        return Video(**result.data[0])

    def create_pending_by_source_external(self, data: dict) -> tuple[Video, bool]:
        payload = {
            **data,
            "processing_status": "pending",
            "processing_error": None,
            "processing_error_code": None,
            "processing_retryable": False,
            "processing_started_at": None,
            "processing_completed_at": None,
        }
        try:
            result = self.table().insert(payload).execute()
            return Video(**result.data[0]), True
        except Exception:
            existing = self.get_by_source_external(
                payload["source"],
                payload["external_video_id"],
            )
            if existing is not None:
                return existing, False
            raise

    @cached_read
    def get_by_id(self, video_id: UUID) -> Video | None:
        result = self.table().select("*").eq("id", str(video_id)).limit(1).execute()
        rows = result.data or []
        return Video(**rows[0]) if rows else None

    def get_many_by_ids(self, video_ids: list[UUID]) -> dict[UUID, Video]:
        if not video_ids:
            return {}
        result = self.table().select("*").in_("id", [str(video_id) for video_id in video_ids]).execute()
        videos = [Video(**row) for row in result.data or []]
        return {video.id: video for video in videos}

    def get_by_source_external(self, source: str, external_video_id: str) -> Video | None:
        result = (
            self.table()
            .select("*")
            .eq("source", source)
            .eq("external_video_id", external_video_id)
            .limit(1)
            .execute()
        )
        rows = result.data or []
        return Video(**rows[0]) if rows else None

    def update_status(
        self,
        video_id: UUID,
        status: str,
        *,
        failure_code: str | None = None,
        retryable: bool = False,
        expected_status: str | None = None,
    ) -> Video | None:
        now = datetime.now(UTC).isoformat()
        data = {
            "processing_status": status,
            "processing_error": None,
            "processing_error_code": failure_code,
            "processing_retryable": retryable,
            "updated_at": now,
        }
        if status == "pending":
            data.update({"processing_started_at": None, "processing_completed_at": None})
        elif status == "processing":
            data.update({"processing_started_at": now, "processing_completed_at": None})
        elif status in {"transcript_ready", "learning_objects_ready", "failed"}:
            data["processing_completed_at"] = now
        query = self.table().update(data).eq("id", str(video_id))
        if expected_status is not None:
            query = query.eq("processing_status", expected_status)
        result = query.execute()
        rows = result.data or []
        return Video(**rows[0]) if rows else None

    def finish_learning_preparation(
        self, video_id: UUID, *, status: str, usable_count: int,
        support_language_code: str | None, failure_code: str | None = None,
        retryable: bool = False,
    ) -> Video | None:
        if status not in {"ready", "no_content", "failed"}:
            raise ValueError("Invalid terminal learning status")
        if status == "ready" and (usable_count < 1 or not support_language_code):
            raise ValueError("Ready learning content requires enriched objects and a support language")
        if status == "no_content" and usable_count != 0:
            raise ValueError("No-content status requires zero usable objects")
        now = datetime.now(UTC).isoformat()
        result = (
            self.table()
            .update({
                "learning_status": status,
                "learning_object_count": usable_count,
                "learning_prepared_language_code": support_language_code,
                "learning_failure_code": failure_code,
                "learning_retryable": retryable,
                "learning_completed_at": now,
                "updated_at": now,
            })
            .eq("id", str(video_id))
            .eq("learning_status", "processing")
            .execute()
        )
        rows = result.data or []
        return Video(**rows[0]) if rows else None

