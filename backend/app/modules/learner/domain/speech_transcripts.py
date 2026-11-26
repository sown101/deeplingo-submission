"""Kept spoken turns for level calibration and the learner's own review (PRD FR-3.11).

Only with the learner's separate transcript consent, and only while the voice consent stands too. Text and
scores, never audio. Kept 12 months from the turn. Under the same two consents the agent may read a bounded number
of the learner's own recent turns back (Q18). Nothing here is read by grading, the usage ladder, review or
progression, and nothing here is ever logged.
"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

MAX_TEXT_CHARS = 2000
MAX_TOPIC_CHARS = 200
MAX_TURNS_PER_SESSION = 200
MAX_WORD_SCORES = 120
MAX_GRAMMAR_ERRORS = 10


def retention_cutoff(now: datetime) -> datetime:
    """Turns at or before this moment are past the 12 months and are no longer shown or exported."""
    try:
        return now.replace(year=now.year - 1)
    except ValueError:  # 29 February
        return now.replace(year=now.year - 1, day=28)


def _clip(value: str | None, limit: int) -> str | None:
    if value is None:
        return None
    collapsed = " ".join(value.split())
    return collapsed[:limit] or None


class WordScore(BaseModel):
    model_config = ConfigDict(extra="forbid")

    word: str = Field(min_length=1, max_length=80)
    accuracy: float = Field(ge=0, le=100)
    error_type: str = Field(min_length=1, max_length=40)


class GrammarError(BaseModel):
    model_config = ConfigDict(extra="forbid")

    quote: str = Field(min_length=1, max_length=MAX_TEXT_CHARS)
    suggestion: str = Field(min_length=1, max_length=MAX_TEXT_CHARS)
    note: str | None = Field(default=None, max_length=MAX_TEXT_CHARS)
    error_type: str | None = Field(default=None, max_length=40)


class TranscriptTurn(BaseModel):
    """One learner turn as the voice conversation hands it over; text is clipped, never rejected for length."""
    model_config = ConfigDict(extra="forbid")

    session_id: UUID
    turn_index: int = Field(ge=0, lt=MAX_TURNS_PER_SESSION)
    language_code: str = Field(min_length=2, max_length=16)
    library_item_id: UUID | None = None
    topic: str | None = None
    assistance_level: int = Field(default=0, ge=0, le=3)
    agent_text: str | None = None
    learner_text: str
    recognized_text: str | None = None
    word_scores: list[WordScore] = Field(default_factory=list, max_length=MAX_WORD_SCORES)
    grammar_errors: list[GrammarError] = Field(default_factory=list, max_length=MAX_GRAMMAR_ERRORS)
    occurred_at: datetime

    @field_validator("agent_text", "learner_text", "recognized_text", mode="before")
    @classmethod
    def _clip_text(cls, value):
        return _clip(value, MAX_TEXT_CHARS) if isinstance(value, str) else value

    @field_validator("topic", mode="before")
    @classmethod
    def _clip_topic(cls, value):
        return _clip(value, MAX_TOPIC_CHARS) if isinstance(value, str) else value

    @field_validator("learner_text")
    @classmethod
    def _not_empty(cls, value):
        if not value:
            raise ValueError("a kept turn needs the learner's words")
        return value


class StoredTranscript(TranscriptTurn):
    model_config = ConfigDict(extra="ignore")

    id: UUID
    user_id: UUID
    created_at: datetime | None = None
