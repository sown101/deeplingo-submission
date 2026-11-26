"""M1 S6: comprehension questions of the learner's current study region (practice only).

The questions are global content prepared once per region. The learner sees them without the answer
key, sends only the chosen option, and the server checks it and returns the key with its quote and
explanation. The answer is kept as one practice-log fact; it never becomes an Attempt, Evidence,
mastery, a skill or review scheduling.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictInt

from app.modules.activity.contracts import log_activity
from app.modules.learning.application.practice_log import PracticeLogError

QuestionsStatus = Literal["no_region", "not_prepared", "preparing", "ready", "none", "unavailable"]


@dataclass(frozen=True)
class RegionQuestionItem:
    id: UUID
    position: int
    question: str
    options: tuple[str, ...]
    correct_index: int
    evidence_segment_id: UUID
    evidence_quote: str
    explanation: str


@dataclass(frozen=True)
class CurrentRegionQuestionSet:
    status: QuestionsStatus
    transcript_id: UUID | None = None
    questions: tuple[RegionQuestionItem, ...] = ()
    region_id: str | None = None  # the learner's current study region, for the learning log


class RegionQuestionReader(Protocol):
    def current(self, user, library_item_id: UUID) -> CurrentRegionQuestionSet:
        """Rechecks ownership and the current region; raises PracticeLogError for no access."""
        ...


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RegionQuestionView(_Strict):
    id: UUID
    position: int
    question: str
    options: list[str]


class RegionQuestionsView(_Strict):
    status: QuestionsStatus
    questions: list[RegionQuestionView] = Field(default_factory=list)


class RegionQuestionAnswerRequest(_Strict):
    id: UUID  # the client's event UUID: a retried request is stored once
    selected_option: StrictInt = Field(ge=0, le=3)


class RegionQuestionAnswerView(_Strict):
    id: UUID
    question_id: UUID
    status: Literal["created", "reused"]
    selected_option: int
    correct: bool
    correct_index: int
    evidence_segment_id: UUID
    evidence_quote: str
    explanation: str


class RegionQuestionService:
    def __init__(self, *, questions: RegionQuestionReader, transcripts=None, learning_log=None):
        self.questions = questions
        self.transcripts = transcripts  # gives the language of the region's transcript for the learning log
        self.learning_log = learning_log

    def list(self, user, library_item_id: UUID) -> RegionQuestionsView:
        current = self.questions.current(user, library_item_id)
        return RegionQuestionsView(status=current.status, questions=[
            RegionQuestionView(id=item.id, position=item.position, question=item.question, options=list(item.options))
            for item in current.questions
        ])

    def answer(self, user, library_item_id: UUID, question_id: UUID,
               request: RegionQuestionAnswerRequest) -> RegionQuestionAnswerView:
        current = self.questions.current(user, library_item_id)
        if current.status != "ready" or current.transcript_id is None:
            raise PracticeLogError(409, "questions_unavailable", "Questions for this part are not available.")
        item = next((row for row in current.questions if row.id == question_id), None)
        if item is None:
            # Same answer for unknown questions and those of another region or video.
            raise PracticeLogError(404, "question_not_found", "Question not found.")
        created = self._log(user, library_item_id, current, item, request)
        return RegionQuestionAnswerView(
            id=request.id, question_id=item.id, status="created" if created else "reused",
            selected_option=request.selected_option, correct=request.selected_option == item.correct_index,
            correct_index=item.correct_index, evidence_segment_id=item.evidence_segment_id,
            evidence_quote=item.evidence_quote, explanation=item.explanation,
        )

    def _log(self, user, library_item_id: UUID, current: CurrentRegionQuestionSet, item: RegionQuestionItem,
             request: RegionQuestionAnswerRequest) -> bool:
        if self.learning_log is None or self.transcripts is None:
            return False
        try:
            language = self.transcripts.get_by_id(current.transcript_id).language_code
        except Exception:
            return False
        return log_activity(
            self.learning_log, user_id=user.id, language_code=language, client_event_id=f"region_question:{request.id}",
            kind="region_question", outcome="correct" if request.selected_option == item.correct_index else "incorrect",
            item_type="segment", item_id=str(item.evidence_segment_id), source_type="video_region",
            source_id=current.region_id or str(library_item_id), detail={"question_id": str(item.id)})
