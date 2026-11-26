from app.modules.content.domain.catalog import SegmentRomanization
from app.platform.persistence import V3Repository


class SegmentRomanizationRepository(V3Repository):
    table_name = "segment_romanizations"

    def upsert_many(self, romanizations: list[dict]) -> list[SegmentRomanization]:
        if not romanizations:
            return []
        result = (
            self.table()
            .upsert(romanizations, on_conflict="transcript_segment_id,romanization_system_id")
            .execute()
        )
        return [SegmentRomanization(**row) for row in (result.data or [])]
