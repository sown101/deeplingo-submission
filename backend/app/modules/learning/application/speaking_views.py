"""Learner-facing speaking-practice projections. No grading authority, no internals."""
from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.modules.learning.domain.speaking import FeedbackBand, PronunciationErrorType


class _View(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SpeakingPhonemeView(_View):
    phoneme: str
    accuracy: float = Field(ge=0, le=100)


class SpeakingWordView(_View):
    word: str
    accuracy: float = Field(ge=0, le=100)
    error_type: PronunciationErrorType
    start_ms: int | None = Field(default=None, ge=0)
    end_ms: int | None = Field(default=None, ge=0)
    phonemes: list[SpeakingPhonemeView] = Field(default_factory=list)


class SpeakingScoresView(_View):
    pronunciation: float = Field(ge=0, le=100)
    accuracy: float = Field(ge=0, le=100)
    fluency: float = Field(ge=0, le=100)
    completeness: float = Field(ge=0, le=100)
    prosody: float | None = Field(default=None, ge=0, le=100)


class ShadowingAssessmentView(_View):
    library_item_id: UUID
    segment_id: UUID
    language_code: str
    reference_text: str
    recognized_text: str
    band: FeedbackBand
    scores: SpeakingScoresView
    words: list[SpeakingWordView]
    attempt_duration_ms: int = Field(ge=0)
    reference_duration_ms: int = Field(ge=0)
    spoken_duration_ms: int | None = Field(default=None, ge=0)
