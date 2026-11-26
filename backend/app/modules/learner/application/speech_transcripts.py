"""The learner's separate consent to keep spoken turns as text, and those turns (PRD FR-3.11).

The consent is default off, asked once and revocable. Turns are stored only while both this consent and the
voice consent (FR-3.4) are granted; the server rechecks both at the moment it stores. The learner can list and
delete the kept turns at any time, whatever the consents say. Revoking stops new turns from being kept and does
not delete the ones already kept; the learner deletes them in Profile or they expire after 12 months (Q18, decided
2026-11-07). While both consents stand, the agent may read a bounded number of the learner's own recent turns as
memory of earlier conversations (Q18, decided 2026-11-07).
"""
from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.modules.learner.domain.agent_signals import may_keep_transcripts, transcript_consent_status
from app.modules.learner.domain.speech_transcripts import (
    GrammarError,
    StoredTranscript,
    TranscriptTurn,
    WordScore,
    retention_cutoff,
)

DEFAULT_PAGE = 50
MAX_PAGE = 100
# What the agent may read back per conversation: the newest turns in the language being practised.
AGENT_MEMORY_TURNS = 8


class TranscriptConsentView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str  # "ask" | "granted" | "revoked"
    decided_at: str | None
    # Whether turns are kept right now: this consent and the voice consent are both granted.
    active: bool


class TranscriptView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    session_id: UUID
    turn_index: int
    language_code: str
    library_item_id: UUID | None
    topic: str | None
    assistance_level: int
    agent_text: str | None
    learner_text: str
    recognized_text: str | None
    word_scores: list[WordScore]
    grammar_errors: list[GrammarError]
    occurred_at: str


class TranscriptPageView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    transcripts: list[TranscriptView]
    next_before: str | None


def _view(row: StoredTranscript) -> TranscriptView:
    return TranscriptView(
        id=row.id, session_id=row.session_id, turn_index=row.turn_index, language_code=row.language_code,
        library_item_id=row.library_item_id, topic=row.topic, assistance_level=row.assistance_level,
        agent_text=row.agent_text, learner_text=row.learner_text, recognized_text=row.recognized_text,
        word_scores=row.word_scores, grammar_errors=row.grammar_errors, occurred_at=row.occurred_at.isoformat(),
    )


class SpeechTranscriptService:
    def __init__(self, *, consents, transcripts, clock=lambda: datetime.now(UTC)):
        self.consents = consents
        self.store = transcripts
        self.clock = clock

    def consent(self, user_id: UUID) -> TranscriptConsentView:
        row = self.consents.get(user_id)
        return TranscriptConsentView(
            status=transcript_consent_status(row),
            decided_at=row.transcript_decided_at.isoformat() if row and row.transcript_decided_at else None,
            active=may_keep_transcripts(row))

    def set_consent(self, user_id: UUID, granted: bool) -> TranscriptConsentView:
        self.consents.set_transcripts(user_id, granted)
        return self.consent(user_id)

    def may_keep(self, user_id: UUID) -> bool:
        return may_keep_transcripts(self.consents.get(user_id))

    def keep(self, user_id: UUID, turns: list[TranscriptTurn]) -> int:
        """Store the turns of one conversation; 0 (and nothing stored) unless both consents are granted now."""
        if not turns or not self.may_keep(user_id):
            return 0
        return self.store.add_many(user_id, turns)

    def recent_for_agent(self, user_id: UUID, *, language_code: str,
                         limit: int = AGENT_MEMORY_TURNS) -> list[StoredTranscript]:
        """The learner's own newest kept turns in this language, oldest first; nothing unless both consents stand."""
        if not self.may_keep(user_id):
            return []
        limit = max(1, min(limit, AGENT_MEMORY_TURNS))
        rows = self.store.list_recent(user_id, language_code=language_code, since=retention_cutoff(self.clock()),
                                      limit=limit)
        return sorted(rows, key=lambda row: (row.occurred_at, row.turn_index))

    def turns_for_agent(self, user_id: UUID, refs: list[tuple[UUID, int]]) -> list[StoredTranscript]:
        """The learner's own kept turns an agent note points to (agent harness plan, phase 5); nothing unless both
        consents stand; a deleted or expired turn is simply not found."""
        if not refs or not self.may_keep(user_id):
            return []
        found: list[StoredTranscript] = []
        for session_id in dict.fromkeys(session for session, _ in refs):
            indexes = [index for session, index in refs if session == session_id]
            found += self.store.list_turns(user_id, session_id=session_id, turn_indexes=indexes,
                                           since=retention_cutoff(self.clock()))
        return sorted(found, key=lambda row: (row.occurred_at, row.turn_index))

    def page(self, user_id: UUID, *, before: datetime | None = None, limit: int = DEFAULT_PAGE) -> TranscriptPageView:
        # Shown whatever the consents say, so a learner who revoked can still look and delete.
        limit = max(1, min(limit, MAX_PAGE))
        rows = self.store.list_page(user_id, since=retention_cutoff(self.clock()), before=before, limit=limit + 1)
        more = len(rows) > limit
        rows = rows[:limit]
        return TranscriptPageView(transcripts=[_view(row) for row in rows],
                                  next_before=rows[-1].occurred_at.isoformat() if more and rows else None)

    def delete_one(self, user_id: UUID, transcript_id: UUID) -> bool:
        return self.store.delete_one(user_id, transcript_id)

    def delete_all(self, user_id: UUID) -> None:
        self.store.delete_all(user_id)
