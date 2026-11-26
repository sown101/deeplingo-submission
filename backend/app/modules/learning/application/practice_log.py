"""M1 S4: the learner's practice log for one Library video (learning-owned, practice only).

Every write resolves the learner's own Library item -> Video -> current original transcript and
checks the sentence belongs to it. The client sends selectors and its raw Dictation answer; the
server re-checks the answer and writes only a summary to the learning log (owner 2026-11-18: one log).
Each client event carries a UUID so a retried request is logged once. Nothing here creates Attempts,
Evidence, mastery or review.
"""
from __future__ import annotations

import logging
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.modules.activity.contracts import log_activity
from app.modules.learning.application.region_source import region_source
from app.modules.learning.domain.practice_log import (
    MAX_ANSWER_CHARS,
    MAX_LOOKUP_CHARS,
    dictation_summary,
    is_unspaced,
)

logger = logging.getLogger(__name__)
READY_VIDEO_STATES = {"transcript_ready", "learning_objects_ready"}


class PracticeLogError(Exception):
    def __init__(self, status_code: int, code: str, message: str):
        super().__init__(message)
        self.status_code, self.code, self.message = status_code, code, message




class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DictationEventRequest(_Strict):
    id: UUID
    segment_id: UUID
    level: Literal["easy", "hard"]
    answer: str = Field(max_length=MAX_ANSWER_CHARS)
    hint_shown: bool = False
    region_id: str | None = Field(default=None, max_length=80)  # the study region practised in (for the learning log)


class LookupEventRequest(_Strict):
    id: UUID
    segment_id: UUID
    start_codepoint: int = Field(ge=0)
    end_codepoint: int = Field(gt=0)
    region_id: str | None = Field(default=None, max_length=80)


class PracticeEventView(_Strict):
    id: UUID
    kind: str
    status: Literal["created", "reused"]
    total: int | None = None
    correct: int | None = None
    missed: list[str] = Field(default_factory=list)


class PracticeLogService:
    def __init__(self, *, library, videos, transcripts, segments, learning_log=None):
        self.learning_log = learning_log  # the learning log (activity module); None = not recording
        self.library = library
        self.videos = videos
        self.transcripts = transcripts
        self.segments = segments

    def record_dictation(self, user, library_item_id: UUID, request: DictationEventRequest) -> PracticeEventView:
        track, segment = self._sentence(user, library_item_id, request.segment_id)
        summary = dictation_summary(segment.text, request.answer, unspaced=is_unspaced(track.language_code),
                                    level=request.level, hint_shown=request.hint_shown)
        total, correct = summary.get("total") or 0, summary.get("correct") or 0
        created = log_activity(
            self.learning_log, user_id=user.id, language_code=track.language_code,
            client_event_id=f"dictation:{request.id}", kind="dictation",
            outcome="correct" if total and correct == total and not summary.get("extra")
            else "partial" if correct else "incorrect",
            item_type="segment", item_id=str(segment.id), source_type="video_region",
            source_id=region_source(self.segments, segment, library_item_id, request.region_id),
            score=round(100 * correct / total, 1) if total else None,
            detail={"total": total, "correct": correct, "missed": list(summary.get("missed", [])),
                    "level": summary.get("level")})
        return PracticeEventView(id=request.id, kind="dictation_checked", status="created" if created else "reused",
                                 total=summary.get("total"), correct=summary.get("correct"),
                                 missed=list(summary.get("missed", [])))

    def record_lookup(self, user, library_item_id: UUID, request: LookupEventRequest) -> PracticeEventView:
        track, segment = self._sentence(user, library_item_id, request.segment_id)
        if request.end_codepoint > len(segment.text) or request.end_codepoint <= request.start_codepoint \
                or request.end_codepoint - request.start_codepoint > MAX_LOOKUP_CHARS:
            raise PracticeLogError(422, "lookup_span_invalid", "That part of the sentence cannot be recorded.")
        text = " ".join(segment.text[request.start_codepoint:request.end_codepoint].split())
        if not text:
            raise PracticeLogError(422, "lookup_span_invalid", "That part of the sentence cannot be recorded.")
        created = log_activity(
            self.learning_log, user_id=user.id, language_code=track.language_code,
            client_event_id=f"lookup:{request.id}", kind="lookup", outcome="done", item_type="segment",
            item_id=str(segment.id), source_type="video_region",
            source_id=region_source(self.segments, segment, library_item_id, request.region_id),
            detail={"text": text})
        return PracticeEventView(id=request.id, kind="word_lookup", status="created" if created else "reused")

    def _sentence(self, user, library_item_id: UUID, segment_id: UUID):
        association = self.library.get_for_user(library_item_id=library_item_id, user_id=user.id)
        video = self.videos.get_by_id(association.video_id) if association is not None else None
        if video is None:
            raise PracticeLogError(404, "library_item_not_found", "Library item not found.")
        if video.processing_status not in READY_VIDEO_STATES:
            raise PracticeLogError(409, "video_not_ready", "This video is not ready yet.")
        segment = self.segments.get_by_id(segment_id)
        track = self.transcripts.get_by_id(segment.transcript_id) if segment is not None else None
        if (segment is None or track is None or track.video_id != video.id or not track.is_original
                or track.language_code != video.original_language_code):
            # Same answer for unknown, foreign and old-version sentences.
            raise PracticeLogError(404, "segment_not_found", "Sentence not found.")
        return track, segment
