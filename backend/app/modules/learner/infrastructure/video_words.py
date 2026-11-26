"""Private video-word links. The database also enforces video and saved-word ownership."""
from uuid import UUID

from app.platform.persistence import V3Repository

PAGE = 1000
MAX_PAGES = 20


class VideoWordRepository(V3Repository):
    table_name = "learner_video_words"

    def for_video(self, user_id: UUID, library_item_id: UUID) -> set[UUID] | None:
        owned = (self.client.schema("v3").table("learner_videos").select("id")
                 .eq("id", str(library_item_id)).eq("user_id", str(user_id)).limit(1).execute().data or [])
        if not owned:
            return None
        result = set()
        for page in range(MAX_PAGES):
            rows = (self.table().select("concept_id").eq("user_id", str(user_id))
                    .eq("library_item_id", str(library_item_id)).order("concept_id")
                    .range(page * PAGE, (page + 1) * PAGE - 1).execute().data or [])
            result.update(UUID(row["concept_id"]) for row in rows)
            if len(rows) < PAGE:
                return result
        raise RuntimeError("video_words_read_truncated")

    def add(self, user_id: UUID, library_item_id: UUID, concept_id: UUID) -> None:
        self.table().upsert({"user_id": str(user_id), "library_item_id": str(library_item_id),
                             "concept_id": str(concept_id)},
                            on_conflict="user_id,library_item_id,concept_id", ignore_duplicates=True).execute()
