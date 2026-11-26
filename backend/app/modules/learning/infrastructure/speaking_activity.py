"""Speaking reads and pronunciation scores (PRD FR-4.2). Never audio or anything the learner said."""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from app.platform.persistence import V3Repository


class SpeakingSessions:
    """The learner's speaking sessions for the "yesterday" line, read from the learning log (owner 2026-11-18: one
    log): when, seconds spoken, turns and reused word names, nothing the learner said."""

    def __init__(self, log):
        self.log = log  # ActivityService

    def rows_between(self, user_id: UUID, start: datetime, end: datetime, *, language_code: str) -> list[dict]:
        rows = self.log.recent(user_id, language_code=language_code, since=start, kinds=["speaking_session"],
                               limit=200)
        return [{"occurred_at": row.occurred_at.isoformat(), "seconds": row.detail.get("seconds") or 0,
                 "turns": row.detail.get("turns") or 0, "reuse_words": row.detail.get("reuse_words") or []}
                for row in rows if row.occurred_at < end]


class PronunciationScoreRepository(V3Repository):
    """Average Azure scores and weak words per practice. Never audio or what was said; backend-only table."""
    table_name = "learner_pronunciation_scores"

    def record(self, user_id: UUID, *, language_code: str, source: str, pronunciation: float, accuracy: float,
               fluency: float, weak_words: list[str], completeness: float | None = None, prosody: float | None = None) -> None:
        self.table().insert({"user_id": str(user_id), "language_code": language_code, "source": source,
                             "pronunciation": pronunciation, "accuracy": accuracy, "fluency": fluency,
                             "completeness": completeness, "prosody": prosody,
                             "weak_words": [str(word)[:80] for word in weak_words[:10]]}).execute()
