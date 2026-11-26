"""The learner's daily study plan.

Learners send only their local date and the choice for a proposal; the server composes the plan
from its own data and rechecks ownership when a proposal is accepted.
"""
from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from app.bootstrap.wiring.study_plan import get_study_plan_service
from app.modules.identity.api.dependencies import require_authenticated_user
from app.modules.identity.contracts import CurrentUser
from app.modules.learning.application.study_plan import (
    PlanEditBody,
    StudyPlanError,
    StudyPlanItemView,
    StudyPlanService,
    StudyPlanView,
)
from app.modules.learning.domain.study_plan import PlanItemStatus

router = APIRouter()

_STATUS = {"not_found": 404, "conflict": 409, "invalid_input": 422, "unavailable": 503}


def _call(action):
    try:
        return action()
    except StudyPlanError as exc:
        raise HTTPException(status_code=_STATUS.get(exc.kind, 503),
                            detail={"code": exc.code, "message": str(exc)}) from exc


@router.get("/learner/me/plan", response_model=StudyPlanView)
def get_study_plan(
    day: date = Query(..., description="The learner's local date"),
    utc_offset_minutes: int = Query(0, ge=-840, le=840, description="The learner's offset from UTC, to find yesterday"),
    user: CurrentUser = Depends(require_authenticated_user),
    service: StudyPlanService = Depends(get_study_plan_service),
):
    return _call(lambda: service.today(user, day, utc_offset_minutes))


@router.post("/learner/me/plan/items/{item_id}/accept", response_model=StudyPlanItemView)
def accept_plan_item(
    item_id: UUID,
    user: CurrentUser = Depends(require_authenticated_user),
    service: StudyPlanService = Depends(get_study_plan_service),
):
    return _call(lambda: service.decide(user, item_id, PlanItemStatus.ACCEPTED))


@router.post("/learner/me/plan/items/{item_id}/dismiss", response_model=StudyPlanItemView)
def dismiss_plan_item(
    item_id: UUID,
    user: CurrentUser = Depends(require_authenticated_user),
    service: StudyPlanService = Depends(get_study_plan_service),
):
    return _call(lambda: service.decide(user, item_id, PlanItemStatus.DISMISSED))


@router.post("/learner/me/plan/items/{item_id}/undo", response_model=StudyPlanItemView)
def undo_plan_edit(
    item_id: UUID,
    body: PlanEditBody,
    user: CurrentUser = Depends(require_authenticated_user),
    service: StudyPlanService = Depends(get_study_plan_service),
):
    """Reverses one edit the agent made to today's tasks: `added` dismisses the task, `removed` opens it again."""
    return _call(lambda: service.undo_edit(user, item_id, body.change))
