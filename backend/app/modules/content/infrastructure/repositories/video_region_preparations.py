from typing import Any
from uuid import UUID

from app.modules.content.domain.region_preparation import RegionAdmission, RegionPreparation
from app.platform.persistence import V3Repository


def _row(data: Any) -> dict[str, Any] | None:
    if isinstance(data, list):
        data = data[0] if data else None
    return data if isinstance(data, dict) else None


class VideoRegionPreparationRepository(V3Repository):
    """M1 S2 region readiness. Writes happen only in the admission RPC and fenced worker RPCs."""

    table_name = "video_region_preparations"

    def admit(
        self, *, user_id: UUID, library_item_id: UUID, transcript_id: UUID,
        start_segment_id: UUID, end_segment_id: UUID, support_language_code: str,
        preparation_version: str, max_segments: int, limit: int, window_seconds: int,
    ) -> RegionAdmission:
        result = self.client.rpc("admit_region_preparation", {
            "p_user_id": str(user_id),
            "p_library_item_id": str(library_item_id),
            "p_transcript_id": str(transcript_id),
            "p_start_segment_id": str(start_segment_id),
            "p_end_segment_id": str(end_segment_id),
            "p_support_language_code": support_language_code,
            "p_preparation_version": preparation_version,
            "p_max_segments": max_segments,
            "p_limit": limit,
            "p_window_seconds": window_seconds,
        }).execute()
        row = _row(result.data)
        if row is None:
            raise RuntimeError("Region preparation admission returned no row")
        return RegionAdmission.from_row(row)

    def find(
        self, *, transcript_id: UUID, start_segment_id: UUID, end_segment_id: UUID,
        support_language_code: str, preparation_version: str,
    ) -> RegionPreparation | None:
        result = (
            self.table().select("*")
            .eq("transcript_id", str(transcript_id))
            .eq("start_segment_id", str(start_segment_id))
            .eq("end_segment_id", str(end_segment_id))
            .eq("support_language_code", support_language_code)
            .eq("preparation_version", preparation_version)
            .limit(1).execute()
        )
        row = _row(result.data)
        return RegionPreparation(**row) if row else None

    def get_by_id(self, region_preparation_id: UUID) -> RegionPreparation | None:
        result = self.table().select("*").eq("id", str(region_preparation_id)).limit(1).execute()
        row = _row(result.data)
        return RegionPreparation(**row) if row else None

    def list_for_transcript(
        self, *, transcript_id: UUID, support_language_code: str, preparation_version: str,
    ) -> list[RegionPreparation]:
        result = (
            self.table().select("*")
            .eq("transcript_id", str(transcript_id))
            .eq("support_language_code", support_language_code)
            .eq("preparation_version", preparation_version)
            .execute()
        )
        return [RegionPreparation(**row) for row in result.data or []]
