"""Persistence for kept spoken turns (FR-3.11). Service-role only, with an explicit learner filter on every
query; the table has no grant for anon or authenticated. Rows are never logged."""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from app.modules.learner.domain.speech_transcripts import StoredTranscript, TranscriptTurn
from app.platform.persistence import V3Repository


class SpeechTranscriptRepository(V3Repository):
    table_name = "learner_speech_transcripts"

    def add_many(self, user_id: UUID, turns: list[TranscriptTurn]) -> int:
        if not turns:
            return 0
        rows = [{**turn.model_dump(mode="json"), "user_id": str(user_id)} for turn in turns]
        result = self.table().upsert(rows, on_conflict="user_id,session_id,turn_index").execute()
        return len(result.data or [])

    def list_page(self, user_id: UUID, *, since: datetime, before: datetime | None, limit: int) -> list[StoredTranscript]:
        query = (self.table().select("*").eq("user_id", str(user_id)).gt("occurred_at", since.isoformat()))
        if before is not None:
            query = query.lt("occurred_at", before.isoformat())
        result = query.order("occurred_at", desc=True).order("turn_index", desc=True).limit(limit).execute()
        return [StoredTranscript(**row) for row in (result.data or [])]

    def list_recent(self, user_id: UUID, *, language_code: str, since: datetime, limit: int) -> list[StoredTranscript]:
        result = (self.table().select("*").eq("user_id", str(user_id)).eq("language_code", language_code)
                  .gt("occurred_at", since.isoformat()).order("occurred_at", desc=True).limit(limit).execute())
        return [StoredTranscript(**row) for row in (result.data or [])]

    def list_turns(self, user_id: UUID, *, session_id: UUID, turn_indexes: list[int],
                   since: datetime) -> list[StoredTranscript]:
        """This learner's kept turns of one conversation, by turn index (the evidence of an agent note)."""
        if not turn_indexes:
            return []
        result = (self.table().select("*").eq("user_id", str(user_id)).eq("session_id", str(session_id))
                  .in_("turn_index", sorted(set(turn_indexes))).gt("occurred_at", since.isoformat()).execute())
        return [StoredTranscript(**row) for row in (result.data or [])]

    def delete_one(self, user_id: UUID, transcript_id: UUID) -> bool:
        result = self.table().delete().eq("user_id", str(user_id)).eq("id", str(transcript_id)).execute()
        return bool(result.data)

    def delete_all(self, user_id: UUID) -> None:
        self.table().delete().eq("user_id", str(user_id)).execute()
