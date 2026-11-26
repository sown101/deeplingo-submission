"""The learner's own progress: one read, filtered by language. The client sends a filter and a display offset only."""
from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.bootstrap.wiring.progress import get_progress_service
from app.modules.identity.api.dependencies import require_authenticated_user
from app.modules.identity.contracts import CurrentUser
from app.modules.progress.application.service import MAX_UTC_OFFSET_MINUTES, ProgressError, ProgressService
from app.modules.progress.domain.models import ProgressView

router = APIRouter()
LANGUAGE = r"^[a-z]{2,3}(-[A-Za-z0-9]{1,8})?$"


@router.get("/learner/me/progress", response_model=ProgressView)
def get_my_progress(
    language: str | None = Query(default=None, min_length=2, max_length=16, pattern=LANGUAGE),
    utc_offset_minutes: int = Query(default=0, ge=-MAX_UTC_OFFSET_MINUTES, le=MAX_UTC_OFFSET_MINUTES),
    user: CurrentUser = Depends(require_authenticated_user),
    service: ProgressService = Depends(get_progress_service),
) -> ProgressView:
    """Streak, heatmap, cards by state, accuracy, pronunciation, grammar, regions and speaking time of the
    signed-in learner, for one language or all. The offset only buckets days for display."""
    try:
        return service.progress(user.id, language=language, utc_offset_minutes=utc_offset_minutes)
    except ProgressError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
