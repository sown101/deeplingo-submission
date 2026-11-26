"""The learning log and study requests (PRD 8.10, TARGET_DESIGN §3-4).

One row per thing the learner did, in the language it was done in. Rows are only added; a retried
request carries the same `client_event_id` and is stored once. A study request is work the agent or
the system gave the learner; a correct result for the same item closes it.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

logger = logging.getLogger(__name__)

ActivityKind = Literal[
    "video_watched", "lookup", "word_saved", "dictation", "shadowing", "region_question", "flashcard", "choice",
    "cloze", "listening", "pronunciation", "writing", "grammar_lesson", "grammar_exercise", "speaking_turn",
    "speaking_session", "roleplay", "match", "order",
]
ItemType = Literal["concept", "grammar_point", "segment", "region"]
SourceType = Literal["video_region", "notebook", "review_deck", "agent_session"]
Outcome = Literal["correct", "incorrect", "partial", "done"]
StudyRequestKind = Literal["grammar_redo", "word_review", "pronunciation_retry", "region_practice"]
StudyRequestStatus = Literal["open", "done", "dismissed"]
StudyRequestCreator = Literal["agent", "system"]

ACTIVITY_KINDS: frozenset[str] = frozenset(ActivityKind.__args__)
STUDY_REQUEST_STATUSES: frozenset[str] = frozenset(StudyRequestStatus.__args__)
# The item each kind of study request is about.
STUDY_REQUEST_ITEMS: dict[str, str] = {
    "grammar_redo": "grammar_point", "word_review": "concept", "pronunciation_retry": "concept",
    "region_practice": "region",
}
# A correct result closes only the open study requests of the kind it answers: a flashcard never closes a
# pronunciation retry. Kinds not listed close nothing.
REQUEST_CLOSED_BY: dict[str, str] = {
    "grammar_exercise": "grammar_redo", "pronunciation": "pronunciation_retry",
    **dict.fromkeys(("flashcard", "choice", "listening", "cloze", "writing", "match", "order"), "word_review"),
    **dict.fromkeys(("dictation", "shadowing", "region_question"), "region_practice"),
}
MAX_KEY_CHARS = 200
MAX_DETAIL_BYTES = 1500  # the database allows 2048 bytes of jsonb; the JSON text stays well under it
MAX_REASON_CHARS = 300
STUDY_REQUEST_DEDUPE_DAYS = 7


class ActivityError(Exception):
    def __init__(self, message: str, *, status_code: int, code: str):
        super().__init__(message)
        self.status_code, self.code = status_code, code


class ActivityEntry(BaseModel):
    """One thing the learner did, as a flow reports it."""
    model_config = ConfigDict(extra="forbid", frozen=True)

    user_id: UUID
    language_code: str = Field(min_length=2, max_length=16)
    client_event_id: str = Field(min_length=1, max_length=MAX_KEY_CHARS)
    kind: ActivityKind
    outcome: Outcome
    item_type: ItemType | None = None
    item_id: str | None = Field(default=None, min_length=1, max_length=MAX_KEY_CHARS)
    source_type: SourceType | None = None
    source_id: str | None = Field(default=None, min_length=1, max_length=MAX_KEY_CHARS)
    score: float | None = Field(default=None, ge=0, le=100)
    detail: dict[str, Any] = Field(default_factory=dict)
    occurred_at: datetime | None = None

    @field_validator("detail")
    @classmethod
    def _small_detail(cls, value: dict[str, Any]) -> dict[str, Any]:
        if len(json.dumps(value, ensure_ascii=False, default=str).encode("utf-8")) > MAX_DETAIL_BYTES:
            raise ValueError("detail is too large")
        return value

    @model_validator(mode="after")
    def _pairs(self) -> "ActivityEntry":
        if (self.item_type is None) != (self.item_id is None):
            raise ValueError("item_type and item_id go together")
        if self.source_id is not None and self.source_type is None:
            raise ValueError("source_id needs source_type")
        return self


class ActivityRecord(BaseModel):
    """A stored log row as the learner and the agent read it."""
    model_config = ConfigDict(extra="ignore")

    id: UUID
    language_code: str
    kind: str
    item_type: str | None = None
    item_id: str | None = None
    source_type: str | None = None
    source_id: str | None = None
    outcome: str
    score: float | None = None
    detail: dict[str, Any] = Field(default_factory=dict)
    occurred_at: datetime


class StudyRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: UUID
    user_id: UUID
    language_code: str
    kind: str
    item_type: str
    item_id: str
    reason: str | None = None
    status: str
    created_by: str
    created_at: datetime
    closed_at: datetime | None = None


def log_activity(recorder, **fields) -> bool:
    """Record one entry without ever failing the learner's action: a bad entry or a store failure is logged
    (kind and error type only) and the caller carries on. `recorder` None means recording is not wired."""
    if recorder is None:
        return False
    try:
        return bool(recorder.record(ActivityEntry(**fields)))
    except Exception as exc:
        logger.warning("activity not recorded kind=%s error=%s", fields.get("kind"), type(exc).__name__)
        return False


def outcome_from_band(band: str) -> str:
    """A speaking score as a result, on the bands the learner already sees: good or excellent is correct."""
    return {"excellent": "correct", "good": "correct", "fair": "partial"}.get(str(getattr(band, "value", band)),
                                                                               "incorrect")
