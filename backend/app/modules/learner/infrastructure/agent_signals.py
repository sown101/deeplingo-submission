"""Persistence for the agent's voice consent and personalization signals. Service-role writes
with an explicit learner filter on every query; RLS additionally limits direct reads to the owner."""
from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from app.modules.learner.domain.agent_signals import AgentConsent, PersonalizationSignal, SignalKind
from app.platform.persistence import V3Repository


def _now() -> datetime:
    return datetime.now(UTC)


class AgentConsentRepository(V3Repository):
    table_name = "learner_agent_consent"

    def get(self, user_id: UUID) -> AgentConsent | None:
        rows = self.table().select("*").eq("user_id", str(user_id)).limit(1).execute().data or []
        return AgentConsent(**rows[0]) if rows else None

    def set(self, user_id: UUID, granted: bool) -> AgentConsent:
        now = _now().isoformat()
        result = self.table().upsert(
            {"user_id": str(user_id), "voice_consent": granted, "decided_at": now, "updated_at": now},
            on_conflict="user_id",
        ).execute()
        return AgentConsent(**result.data[0])

    def set_transcripts(self, user_id: UUID, granted: bool) -> AgentConsent:
        """FR-3.11: only the transcript columns; the voice consent is left as it is."""
        now = _now().isoformat()
        result = self.table().upsert(
            {"user_id": str(user_id), "transcript_consent": granted, "transcript_decided_at": now, "updated_at": now},
            on_conflict="user_id",
        ).execute()
        return AgentConsent(**result.data[0])


class PersonalizationSignalRepository(V3Repository):
    table_name = "learner_personalization_signals"

    def list_all(self, user_id: UUID) -> list[PersonalizationSignal]:
        result = (
            self.table().select("*").eq("user_id", str(user_id))
            .order("updated_at", desc=True).limit(500).execute()
        )
        return [PersonalizationSignal(**row) for row in (result.data or [])]

    def record(self, user_id: UUID, *, language_code: str, kind: SignalKind, code: str,
               replace_kind: bool) -> None:
        """Count one more sighting of the code, or (``replace_kind``) make it the only value of its kind."""
        self.client.schema(self.schema).rpc("record_personalization_signal", {
            "p_user_id": str(user_id), "p_language_code": language_code, "p_kind": kind.value,
            "p_code": code, "p_replace_kind": replace_kind,
        }).execute()

    def delete_one(self, user_id: UUID, signal_id: UUID) -> bool:
        result = self.table().delete().eq("user_id", str(user_id)).eq("id", str(signal_id)).execute()
        return bool(result.data)

    def delete_all(self, user_id: UUID) -> None:
        self.table().delete().eq("user_id", str(user_id)).execute()
