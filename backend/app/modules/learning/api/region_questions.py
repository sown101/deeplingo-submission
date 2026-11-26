"""M1 S6 region comprehension questions: list without answer keys, answer by option index.

The server checks the answer and keeps it as practice only: no Attempt, Evidence, mastery,
skill or review.
"""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from app.bootstrap.wiring.speaking import get_practice_log_limiter, get_region_question_service
from app.modules.identity.api.dependencies import require_authenticated_user
from app.modules.identity.contracts import CurrentUser
from app.modules.learning.application.practice_log import PracticeLogError
from app.modules.learning.application.region_questions import (
    RegionQuestionAnswerRequest,
    RegionQuestionAnswerView,
    RegionQuestionService,
    RegionQuestionsView,
)
from app.platform.rate_limit import SlidingWindowLimiter

router = APIRouter()


def _call(operation):
    try:
        return operation()
    except PracticeLogError as exc:
        raise HTTPException(exc.status_code, {"code": exc.code, "message": exc.message}) from exc


@router.get("/learner/me/library/videos/{library_item_id}/region-questions", response_model=RegionQuestionsView)
def list_region_questions(library_item_id: UUID,
                          user: CurrentUser = Depends(require_authenticated_user),
                          service: RegionQuestionService = Depends(get_region_question_service)):
    """The current study region's questions, without answer keys."""
    return _call(lambda: service.list(user, library_item_id))


@router.post("/learner/me/library/videos/{library_item_id}/region-questions/{question_id}/answer",
             response_model=RegionQuestionAnswerView)
def answer_region_question(library_item_id: UUID, question_id: UUID, request: RegionQuestionAnswerRequest,
                           user: CurrentUser = Depends(require_authenticated_user),
                           service: RegionQuestionService = Depends(get_region_question_service),
                           limiter: SlidingWindowLimiter = Depends(get_practice_log_limiter)):
    """Checks the chosen option on the server. Practice only."""
    if not limiter.allow(str(user.id), "practice_event"):
        raise HTTPException(429, {"code": "practice_rate_limited", "message": "Too many requests. Please wait a moment."})
    return _call(lambda: service.answer(user, library_item_id, question_id, request))
