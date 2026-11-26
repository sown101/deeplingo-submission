"""M1 S4 practice log: the learner reports a checked Dictation answer or a word lookup.

Selectors and raw input only. The server re-checks Dictation against its transcript, keeps a
bounded summary and never turns it into an Attempt, Evidence, mastery or review.
"""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from app.bootstrap.wiring.speaking import (
    get_practice_log_limiter,
    get_practice_log_service,
)
from app.modules.identity.api.dependencies import require_authenticated_user
from app.modules.identity.contracts import CurrentUser
from app.modules.learning.application.practice_log import (
    DictationEventRequest,
    LookupEventRequest,
    PracticeEventView,
    PracticeLogError,
    PracticeLogService,
)
from app.platform.rate_limit import SlidingWindowLimiter

router = APIRouter()


def _call(user: CurrentUser, limiter: SlidingWindowLimiter, operation):
    if not limiter.allow(str(user.id), "practice_event"):
        raise HTTPException(429, {"code": "practice_rate_limited", "message": "Too many requests. Please wait a moment."})
    try:
        return operation()
    except PracticeLogError as exc:
        raise HTTPException(exc.status_code, {"code": exc.code, "message": exc.message}) from exc


@router.post("/learner/me/library/videos/{library_item_id}/practice-events/dictation",
             response_model=PracticeEventView)
def record_dictation(library_item_id: UUID, request: DictationEventRequest,
                     user: CurrentUser = Depends(require_authenticated_user),
                     service: PracticeLogService = Depends(get_practice_log_service),
                     limiter: SlidingWindowLimiter = Depends(get_practice_log_limiter)):
    """A checked Dictation answer, re-checked by the server. Practice only."""
    return _call(user, limiter, lambda: service.record_dictation(user, library_item_id, request))


@router.post("/learner/me/library/videos/{library_item_id}/practice-events/lookup",
             response_model=PracticeEventView)
def record_lookup(library_item_id: UUID, request: LookupEventRequest,
                  user: CurrentUser = Depends(require_authenticated_user),
                  service: PracticeLogService = Depends(get_practice_log_service),
                  limiter: SlidingWindowLimiter = Depends(get_practice_log_limiter)):
    """A word the learner looked up in a sentence of this video. Practice only."""
    return _call(user, limiter, lambda: service.record_lookup(user, library_item_id, request))
