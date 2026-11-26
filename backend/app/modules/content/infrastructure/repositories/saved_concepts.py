"""The learner's own Concept saves and targets (`saved_concepts`, My words, L1a). Service-role
writes with an explicit learner filter; a save is a priority request, never learner state.

Since L1a the same row is the learner's target: `status` (backlog, active, suspended), `priority`,
`level_label`, `activated_at` and the ladder `rung`. The table name is historical."""
from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from app.platform.persistence import V3Repository, fetch_pages

MAX_LISTED = 2000
TARGET_COLUMNS = ("id,concept_id,save_source,created_at,status,explicit,priority,level_label,rung,activated_at,"
                  "language_code,note,favorite")


class SavedConceptRepository(V3Repository):
    table_name = "saved_concepts"

    def list_for_user(self, user_id: UUID, *, language_code: str | None = None, status: str | None = None) -> list[dict]:
        query = self.table().select(TARGET_COLUMNS).eq("user_id", str(user_id))
        if language_code:
            query = query.eq("language_code", language_code)
        if status:
            query = query.eq("status", status)
        return fetch_pages(query.order("created_at", desc=True), MAX_LISTED)

    def update_personal(self, user_id: UUID, *, concept_id: UUID, fields: dict) -> dict | None:
        rows = (self.table().update(fields).eq("user_id", str(user_id)).eq("concept_id", str(concept_id))
                .execute().data or [])
        return rows[0] if rows else None

    def get(self, user_id: UUID, concept_id: UUID) -> dict | None:
        rows = (self.table().select(TARGET_COLUMNS).eq("user_id", str(user_id))
                .eq("concept_id", str(concept_id)).limit(1).execute().data or [])
        return rows[0] if rows else None

    def concept_ids_for(self, user_id: UUID, concept_ids: list[UUID]) -> set[UUID]:
        if not concept_ids:
            return set()
        rows = (
            self.table().select("concept_id").eq("user_id", str(user_id))
            .in_("concept_id", [str(item) for item in dict.fromkeys(concept_ids)]).execute().data or []
        )
        return {UUID(str(row["concept_id"])) for row in rows}

    def save(self, user_id: UUID, *, concept_id: UUID, save_source: str,
             source_learning_object_id: UUID | None = None, language_code: str | None = None,
             level_label: str | None = None, priority: int = 100, explicit: bool = True) -> dict:
        """Idempotent: saving a word again keeps the first row (its status and source) but may raise its
        priority and turns an automatic queueing into an explicit save."""
        uid, cid = str(user_id), str(concept_id)
        now = datetime.now(UTC).isoformat()
        self.table().upsert(
            {
                "user_id": uid, "concept_id": cid, "save_source": save_source, "status": "active",
                "explicit": explicit, "priority": priority, "language_code": language_code,
                "level_label": level_label,
                "source_learning_object_id": str(source_learning_object_id) if source_learning_object_id else None,
                "activated_at": now, "updated_at": now,
            },
            on_conflict="user_id,concept_id", ignore_duplicates=True,
        ).execute()
        self.table().update({"priority": priority}).eq("user_id", uid).eq("concept_id", cid).lt("priority", priority).execute()
        if explicit:
            self.table().update({"explicit": True}).eq("user_id", uid).eq("concept_id", cid).eq("explicit", False).execute()
        row = self.get(user_id, concept_id)
        if row is None:
            raise RuntimeError("saved concept was not stored")
        return row

    def set_status(self, user_id: UUID, *, concept_id: UUID, status: str, now: datetime,
                   only_from: str | None = None) -> dict | None:
        """Moves a target to `status`; with `only_from` it is a compare-and-set that returns None when the
        row was not in that status (another request got there first)."""
        changes: dict = {"status": status, "updated_at": now.isoformat()}
        if status == "active":
            changes["activated_at"] = now.isoformat()
        query = self.table().update(changes).eq("user_id", str(user_id)).eq("concept_id", str(concept_id))
        if only_from:
            query = query.eq("status", only_from)
        rows = query.execute().data or []
        return rows[0] if rows else None

    def count_activated_since(self, user_id: UUID, *, language_code: str, since: datetime) -> int:
        rows = (self.table().select("concept_id").eq("user_id", str(user_id)).eq("language_code", language_code)
                .gte("activated_at", since.isoformat()).limit(MAX_LISTED).execute().data or [])
        return len(rows)

    def set_rung(self, user_id: UUID, *, concept_id: UUID, rung: int) -> None:
        (self.table().update({"rung": rung}).eq("user_id", str(user_id)).eq("concept_id", str(concept_id))
         .neq("rung", rung).execute())

    def remove(self, user_id: UUID, *, concept_id: UUID) -> bool:
        result = self.table().delete().eq("user_id", str(user_id)).eq("concept_id", str(concept_id)).execute()
        return bool(result.data)
