from uuid import UUID

from app.modules.content.domain.catalog import SegmentTranslation
from app.platform.persistence import V3Repository, cached_read


class SegmentTranslationRepository(V3Repository):
    table_name = "segment_translations"

    @cached_read
    def get_by_segment_language(self, transcript_segment_id, language_code: str) -> SegmentTranslation | None:
        result = (
            self.table()
            .select("*")
            .eq("transcript_segment_id", str(transcript_segment_id))
            .eq("language_code", language_code)
            .limit(1)
            .execute()
        )
        rows = result.data or []
        return SegmentTranslation(**rows[0]) if rows else None

    def translated_segment_ids(self, segment_ids: list, language_code: str) -> set:
        """The given segments that already have a translation in this language."""
        found: set = set()
        for start in range(0, len(segment_ids), 100):
            chunk = [str(item) for item in segment_ids[start:start + 100]]
            rows = (self.table().select("transcript_segment_id").eq("language_code", language_code)
                    .in_("transcript_segment_id", chunk).execute().data or [])
            found.update(UUID(row["transcript_segment_id"]) for row in rows)
        return found

    def upsert_many(self, translations: list[dict]) -> list[SegmentTranslation]:
        if not translations:
            return []
        result = (
            self.table()
            .upsert(translations, on_conflict="transcript_segment_id,language_code")
            .execute()
        )
        return [SegmentTranslation(**row) for row in (result.data or [])]
