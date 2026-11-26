"""Durable derived events and a separate, non-persistent Redis store for transient text."""
from datetime import timedelta
from uuid import UUID

from app.modules.learning.application.session_events import SessionText, TEXT_TTL_SECONDS
from app.platform.persistence import V3Repository


class SpeakingSessionRepository(V3Repository):
    table_name = "speaking_sessions"

    def create(self, data: SessionText) -> bool:
        result = self.table().upsert({
            "id": str(data.id), "user_id": str(data.user_id), "language_code": data.language_code,
            "library_item_id": str(data.library_item_id) if data.library_item_id else None,
            "context_key": data.context_key, "occurred_at": data.ended_at.isoformat(),
            "expires_at": (data.ended_at + timedelta(seconds=TEXT_TTL_SECONDS)).isoformat(),
            "targets": [{"concept_id": str(word.concept_id), "text": word.text} for word in data.targets],
        }, on_conflict="id", ignore_duplicates=True).execute()
        return bool(result.data)

    def get(self, session_id: UUID, user_id: UUID | None = None) -> dict | None:
        query = self.table().select("id,user_id,status,expires_at,events").eq("id", str(session_id))
        if user_id is not None:
            query = query.eq("user_id", str(user_id))
        rows = query.limit(1).execute().data or []
        return rows[0] if rows else None

    def claim(self, session_id: UUID) -> bool:
        return bool(self.table().update({"status": "processing"}).eq("id", str(session_id))
                    .eq("status", "queued").execute().data)

    def fail(self, session_id: UUID, code: str) -> None:
        self.table().update({"status": "expired" if code == "expired" else "failed", "error_code": code}) \
            .eq("id", str(session_id)).in_("status", ["queued", "processing", "projecting"]).execute()

    def projected(self, session_id: UUID) -> None:
        self.table().update({"status": "completed"}).eq("id", str(session_id)).eq("status", "projecting").execute()

    def complete(self, session_id: UUID, uses: list[dict], model: str) -> list[dict]:
        return self.client.rpc("complete_speaking_session", {
            "p_session_id": str(session_id), "p_uses": uses, "p_model": model,
        }).execute().data or []


def require_transient_redis(client) -> None:
    """Raw learner text goes only to a Redis that keeps nothing on disk and has no replica."""
    # A different DB number on the persistent broker would still be written to its AOF/RDB.
    config = client.config_get("appendonly", "save")
    replication = client.info("replication")
    if config.get("appendonly") != "no" or config.get("save") != "" \
            or replication.get("role") != "master" or replication.get("connected_slaves", 0) != 0:
        raise RuntimeError("transient_redis_required")


class RedisSessionText:
    def __init__(self, client):
        self.client = client

    def _safe(self):
        require_transient_redis(self.client)

    @staticmethod
    def key(session_id):
        return "deeplingo:speaking-text:" + str(session_id)

    def put(self, session_id, text, ttl):
        self._safe()
        if not 0 < ttl <= TEXT_TTL_SECONDS:
            raise ValueError("invalid_text_retention")
        if not self.client.set(self.key(session_id), text, ex=ttl, nx=True):
            raise RuntimeError("speaking_text_already_exists")

    def get(self, session_id):
        self._safe()
        return self.client.get(self.key(session_id))

    def delete(self, session_id):
        self.client.delete(self.key(session_id))
