"""Named word lists (`word_groups`), their items and the imported lines still waiting (L1b).

Service-role writes with an explicit learner filter. A list item points at a target
(`saved_concepts.id`); deleting a list never deletes the learner's words."""
from __future__ import annotations

from uuid import UUID

from app.modules.learner.domain.word_lists import MAX_GROUPS_PER_LEARNER, MAX_LIST_ROWS
from app.platform.persistence import IN_CHUNK, V3Repository, fetch_pages

MAX_LISTED = 2000
GROUP_COLUMNS = "id,language_code,name,description,color,created_at,updated_at"


class WordGroupRepository(V3Repository):
    table_name = "word_groups"

    def create(self, user_id: UUID, *, language_code: str, name: str, description: str | None) -> dict:
        rows = self.table().insert({
            "user_id": str(user_id), "language_code": language_code, "name": name, "description": description,
        }).execute().data or []
        if not rows:
            raise RuntimeError("word list was not stored")
        return rows[0]

    def list_for_user(self, user_id: UUID, *, language_code: str | None = None) -> list[dict]:
        query = self.table().select(GROUP_COLUMNS).eq("user_id", str(user_id))
        if language_code:
            query = query.eq("language_code", language_code)
        return query.order("created_at", desc=True).limit(MAX_LISTED).execute().data or []

    def get(self, user_id: UUID, group_id: UUID) -> dict | None:
        rows = (self.table().select(GROUP_COLUMNS).eq("user_id", str(user_id)).eq("id", str(group_id))
                .limit(1).execute().data or [])
        return rows[0] if rows else None

    def delete(self, user_id: UUID, group_id: UUID) -> bool:
        return bool(self.table().delete().eq("user_id", str(user_id)).eq("id", str(group_id)).execute().data)


class WordGroupItemRepository(V3Repository):
    table_name = "word_group_items"

    def add(self, group_id: UUID, saved_concept_id: UUID) -> bool:
        """True when the word was added; False when it was already in the list."""
        if saved_concept_id in set(self.saved_ids(group_id)):
            return False
        self.table().upsert(
            {"group_id": str(group_id), "saved_concept_id": str(saved_concept_id)},
            on_conflict="group_id,saved_concept_id", ignore_duplicates=True,
        ).execute()
        return True

    def saved_ids(self, group_id: UUID) -> list[UUID]:
        rows = (self.table().select("saved_concept_id").eq("group_id", str(group_id))
                .order("added_at").limit(MAX_LISTED).execute().data or [])
        return [UUID(str(row["saved_concept_id"])) for row in rows]

    def remove(self, group_id: UUID, saved_concept_id: UUID) -> bool:
        result = (self.table().delete().eq("group_id", str(group_id))
                  .eq("saved_concept_id", str(saved_concept_id)).execute())
        return bool(result.data)

    def counts(self, group_ids: list[UUID]) -> dict[UUID, int]:
        return _counts(self, group_ids)


class ImportRowRepository(V3Repository):
    table_name = "word_group_import_rows"

    def add(self, group_id: UUID, user_id: UUID, *, position: int, raw_text: str, user_gloss: str | None,
            resolution: str, candidates: list[dict]) -> dict:
        rows = self.table().insert({
            "group_id": str(group_id), "user_id": str(user_id), "position": position, "raw_text": raw_text,
            "user_gloss": user_gloss, "resolution": resolution, "candidates": candidates,
        }).execute().data or []
        if not rows:
            raise RuntimeError("import row was not stored")
        return rows[0]

    def list(self, group_id: UUID) -> list[dict]:
        return (self.table().select("id,position,raw_text,user_gloss,resolution,candidates")
                .eq("group_id", str(group_id)).order("position").limit(MAX_LISTED).execute().data or [])

    def get(self, group_id: UUID, row_id: UUID) -> dict | None:
        rows = (self.table().select("id,position,raw_text,user_gloss,resolution,candidates")
                .eq("group_id", str(group_id)).eq("id", str(row_id)).limit(1).execute().data or [])
        return rows[0] if rows else None

    def delete(self, group_id: UUID, row_id: UUID) -> bool:
        return bool(self.table().delete().eq("group_id", str(group_id)).eq("id", str(row_id)).execute().data)

    def counts(self, group_ids: list[UUID]) -> dict[UUID, int]:
        return _counts(self, group_ids)

    def next_position(self, group_id: UUID) -> int:
        rows = (self.table().select("position").eq("group_id", str(group_id)).order("position", desc=True)
                .limit(1).execute().data or [])
        return int(rows[0]["position"]) + 1 if rows else 1

    def raw_words(self, group_id: UUID) -> set[str]:
        return {str(row["raw_text"]).casefold() for row in self.list(group_id)}


def _counts(repository: V3Repository, group_ids: list[UUID]) -> dict[UUID, int]:
    if not group_ids:
        return {}
    # Read in pages: PostgREST returns at most 1000 rows per request, and a learner's lists hold more.
    rows: list[dict] = []
    for start in range(0, len(group_ids), IN_CHUNK):
        chunk = [str(item) for item in group_ids[start:start + IN_CHUNK]]
        rows += fetch_pages(repository.table().select("group_id").in_("group_id", chunk).order("group_id"),
                            MAX_GROUPS_PER_LEARNER * MAX_LIST_ROWS)
    counts: dict[UUID, int] = {item: 0 for item in group_ids}
    for row in rows:
        key = UUID(str(row["group_id"]))
        counts[key] = counts.get(key, 0) + 1
    return counts
