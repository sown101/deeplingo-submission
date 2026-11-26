"""Learning-log and study-request persistence. Service-role access with the learner named on every query;
both tables are backend-only (RLS on, no grants to learners)."""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from app.modules.activity.domain.models import ActivityEntry, ActivityRecord, StudyRequest
from app.platform.persistence import V3Repository

_LOG_COLUMNS = "id,language_code,kind,item_type,item_id,source_type,source_id,outcome,score,detail,occurred_at"


class ActivityLogRepository(V3Repository):
    table_name = "learner_activity_log"

    def insert_once(self, entry: ActivityEntry) -> bool:
        row = {
            "user_id": str(entry.user_id), "language_code": entry.language_code,
            "client_event_id": entry.client_event_id, "kind": entry.kind, "outcome": entry.outcome,
            "item_type": entry.item_type, "item_id": entry.item_id, "source_type": entry.source_type,
            "source_id": entry.source_id, "score": round(entry.score, 1) if entry.score is not None else None,
            "detail": entry.detail,
        }
        if entry.occurred_at is not None:
            row["occurred_at"] = entry.occurred_at.isoformat()
        # ON CONFLICT DO NOTHING: only a newly inserted row comes back.
        result = self.table().upsert(row, on_conflict="user_id,client_event_id", ignore_duplicates=True).execute()
        return bool(result.data)

    def recent(self, *, user_id: UUID, language_code: str, since: datetime | None, kinds: list[str] | None,
               limit: int) -> list[ActivityRecord]:
        query = self.table().select(_LOG_COLUMNS).eq("user_id", str(user_id)).eq("language_code", language_code)
        if since is not None:
            query = query.gte("occurred_at", since.isoformat())
        if kinds:
            query = query.in_("kind", kinds)
        rows = query.order("occurred_at", desc=True).limit(limit).execute().data or []
        return [ActivityRecord(**row) for row in rows]

    def for_source(self, *, user_id: UUID, source_type: str, source_id: str, limit: int) -> list[ActivityRecord]:
        rows = (self.table().select(_LOG_COLUMNS).eq("user_id", str(user_id)).eq("source_type", source_type)
                .eq("source_id", source_id).order("occurred_at", desc=True).limit(limit).execute().data or [])
        return [ActivityRecord(**row) for row in rows]


class StudyRequestRepository(V3Repository):
    table_name = "learner_study_requests"

    def open_for_item(self, *, user_id: UUID, language_code: str, kind: str, item_type: str, item_id: str,
                      created_after: datetime) -> StudyRequest | None:
        rows = (self.table().select("*").eq("user_id", str(user_id)).eq("language_code", language_code)
                .eq("kind", kind).eq("item_type", item_type).eq("item_id", item_id).eq("status", "open")
                .gte("created_at", created_after.isoformat()).order("created_at", desc=True).limit(1)
                .execute().data or [])
        return StudyRequest(**rows[0]) if rows else None

    def create(self, *, user_id: UUID, language_code: str, kind: str, item_type: str, item_id: str,
               reason: str | None, created_by: str) -> StudyRequest:
        rows = self.table().insert({
            "user_id": str(user_id), "language_code": language_code, "kind": kind, "item_type": item_type,
            "item_id": item_id, "reason": reason, "created_by": created_by,
        }).execute().data or []
        if not rows:
            raise RuntimeError("study request was not stored")
        return StudyRequest(**rows[0])

    def list(self, *, user_id: UUID, language_code: str, status: str | None, limit: int) -> list[StudyRequest]:
        query = self.table().select("*").eq("user_id", str(user_id)).eq("language_code", language_code)
        if status is not None:
            query = query.eq("status", status)
        return [StudyRequest(**row) for row in query.order("created_at", desc=True).limit(limit).execute().data or []]

    def close_open_for_item(self, *, user_id: UUID, language_code: str, item_type: str, item_id: str,
                            closed_at: datetime, kind: str | None = None) -> int:
        query = (self.table().update({"status": "done", "closed_at": closed_at.isoformat()})
                 .eq("user_id", str(user_id)).eq("language_code", language_code).eq("item_type", item_type)
                 .eq("item_id", item_id).eq("status", "open"))
        if kind is not None:
            query = query.eq("kind", kind)
        return len(query.execute().data or [])

    def dismiss(self, *, user_id: UUID, request_id: UUID, closed_at: datetime) -> StudyRequest | None:
        rows = (self.table().update({"status": "dismissed", "closed_at": closed_at.isoformat()})
                .eq("id", str(request_id)).eq("user_id", str(user_id)).eq("status", "open").execute().data or [])
        if rows:
            return StudyRequest(**rows[0])
        rows = (self.table().select("*").eq("id", str(request_id)).eq("user_id", str(user_id)).limit(1)
                .execute().data or [])
        return StudyRequest(**rows[0]) if rows else None
