"""Review-deck and grammar-progress persistence. Service-role access with the learner named on every call; each
write is one SQL function so that the grade, the schedule and the learning-log row commit together."""
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from app.platform.persistence import V3Repository, fetch_pages


def _uuid(value) -> UUID:
    return value if isinstance(value, UUID) else UUID(str(value))


def _time(value) -> datetime | None:
    if value is None or isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


class ReviewDeckRepository(V3Repository):
    table_name = "review_states"

    def _rpc(self, name: str, params: dict[str, Any]):
        return self.client.schema(self.schema).rpc(name, params).execute().data

    def deck_counts(self, user_id: UUID) -> list[dict[str, Any]]:
        rows = self._rpc("review_deck_counts", {"p_user_id": str(user_id)}) or []
        return [{"language_code": row["language_code"], "due_count": int(row["due_count"]),
                 "new_count": int(row["new_count"]), "total_count": int(row["total_count"])} for row in rows]

    def deck_cards(self, user_id: UUID, language_code: str, *, limit: int,
                   concept_ids: list[UUID] | None) -> list[dict[str, Any]]:
        rows = self._rpc("review_deck_cards", {
            "p_user_id": str(user_id), "p_language_code": language_code, "p_limit": limit,
            "p_concept_ids": [str(value) for value in concept_ids] if concept_ids else None,
        }) or []
        return [{"concept_id": _uuid(row["concept_id"]), "due_at": _time(row.get("due_at")),
                 "is_new": bool(row["is_new"])} for row in rows]

    def answer_context(self, user_id: UUID, concept_id: UUID, pass_id: str | None) -> dict[str, Any] | None:
        data = self._rpc("review_answer_context", {"p_user_id": str(user_id), "p_concept_id": str(concept_id),
                                                   "p_pass_id": pass_id})
        if data is not None and not isinstance(data, dict):
            raise RuntimeError("Invalid review answer context")
        return data

    def submit_answer(self, user_id: UUID, concept_id: UUID, transition: dict | None, log: dict) -> dict[str, Any]:
        data = self._rpc("submit_review_answer", {"p_user_id": str(user_id), "p_concept_id": str(concept_id),
                                                  "p_transition": transition, "p_log": log})
        if not isinstance(data, dict):
            raise RuntimeError("Invalid review answer result")
        return data

    def latest_pronunciation(self, user_id: UUID, concept_id: UUID) -> dict[str, Any] | None:
        """The newest pronunciation row of one saved word in the learning log (written by submit_review_answer)."""
        rows = (self.client.schema(self.schema).table("learner_activity_log")
                .select("score,outcome,detail,occurred_at").eq("user_id", str(user_id)).eq("kind", "pronunciation")
                .eq("item_type", "concept").eq("item_id", str(concept_id))
                .order("occurred_at", desc=True).limit(1).execute().data or [])
        return rows[0] if rows else None


class GrammarProgressRepository(V3Repository):
    table_name = "learner_grammar_progress"

    def for_language(self, user_id: UUID, language_code: str) -> dict[str, dict[str, Any]]:
        rows = fetch_pages(self.table().select("grammar_key,lesson_learned_at,attempts,correct_count,last_attempt_at,"
                                               "last_correct_at").eq("user_id", str(user_id))
                           .eq("language_code", language_code).order("grammar_key"), 2000)
        return {row["grammar_key"]: row for row in rows}

    def record_answer(self, user_id: UUID, language_code: str, grammar_key: str, log: dict) -> dict[str, Any]:
        data = self.client.schema(self.schema).rpc("record_grammar_answer", {
            "p_user_id": str(user_id), "p_language_code": language_code, "p_grammar_key": grammar_key, "p_log": log,
        }).execute().data
        if not isinstance(data, dict):
            raise RuntimeError("Invalid grammar answer result")
        return data

    def record_lesson(self, user_id: UUID, language_code: str, grammar_key: str, client_event_id: str) -> dict:
        data = self.client.schema(self.schema).rpc("record_grammar_lesson", {
            "p_user_id": str(user_id), "p_language_code": language_code, "p_grammar_key": grammar_key,
            "p_client_event_id": client_event_id,
        }).execute().data
        if not isinstance(data, dict):
            raise RuntimeError("Invalid grammar lesson result")
        return data
