"""The learner's own study requests: dismissing one.

The client sends a selector only; nothing here writes a log row or decides a result.
"""
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict

from app.bootstrap.wiring.activity import get_activity_service
from app.modules.activity.application.service import ActivityService
from app.modules.activity.domain.models import ActivityError
from app.modules.identity.api.dependencies import require_authenticated_user
from app.modules.identity.contracts import CurrentUser

router = APIRouter()


class StudyRequestView(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID
    language_code: str
    kind: str
    item_type: str
    item_id: str
    reason: str | None
    status: str
    created_by: str
    created_at: datetime
    closed_at: datetime | None


def _request_view(request) -> StudyRequestView:
    return StudyRequestView(**request.model_dump(exclude={"user_id"}))


@router.post("/learner/me/study-requests/{request_id}/dismiss", response_model=StudyRequestView)
def dismiss_my_study_request(
    request_id: UUID,
    user: CurrentUser = Depends(require_authenticated_user),
    service: ActivityService = Depends(get_activity_service),
) -> StudyRequestView:
    """The learner sets aside one of their own open requests; a closed one is returned unchanged."""
    try:
        return _request_view(service.dismiss(user.id, request_id))
    except ActivityError as exc:
        raise HTTPException(exc.status_code, {"code": exc.code, "message": str(exc)}) from exc
