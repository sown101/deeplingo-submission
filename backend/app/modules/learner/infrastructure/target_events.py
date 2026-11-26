"""Append-only evidence for the usage ladder (`v3.target_events`, L1a).

Rows are inserted once per `(user, event_key)`; a repeated key is ignored, so a retried request or a
re-run analysis never counts twice. The application never updates or deletes them."""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from app.platform.persistence import V3Repository

MAX_EVENTS = 1000


class TargetEventRepository(V3Repository):
    table_name = "target_events"

    def record(self, user_id: UUID, *, concept_id: UUID, kind: str, outcome: str, event_key: str,
               occurred_at: datetime, context_key: str | None = None, quote: str | None = None,
               error_type: str | None = None, judge: dict | None = None) -> None:
        self.table().upsert(
            {
                "user_id": str(user_id), "concept_id": str(concept_id), "kind": kind, "outcome": outcome,
                "event_key": event_key, "context_key": context_key, "quote": quote, "error_type": error_type,
                "judge": judge or {}, "occurred_at": occurred_at.isoformat(),
            },
            on_conflict="user_id,event_key", ignore_duplicates=True,
        ).execute()

    def list_for_concept(self, user_id: UUID, concept_id: UUID) -> list[dict]:
        return (self.table().select("kind,outcome,occurred_at,context_key,quote,error_type")
                .eq("user_id", str(user_id)).eq("concept_id", str(concept_id))
                .order("occurred_at").limit(MAX_EVENTS).execute().data or [])
