"""The result card of a study region: the learner's own log rows of that region, summed."""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from app.bootstrap.wiring.speaking import get_region_result_service
from app.modules.activity.contracts import RegionResult
from app.modules.identity.api.dependencies import require_authenticated_user
from app.modules.identity.contracts import CurrentUser
from app.modules.learning.application.practice_log import PracticeLogError
from app.modules.learning.application.region_result import RegionResultService

router = APIRouter()


@router.get("/learner/me/library/videos/{library_item_id}/regions/{region}/result", response_model=RegionResult)
def get_region_result(library_item_id: UUID, region: str,
                      user: CurrentUser = Depends(require_authenticated_user),
                      service: RegionResultService = Depends(get_region_result_service)):
    """Dictation accuracy, shadowing average, questions right and words saved in one study region."""
    try:
        return service.result(user, library_item_id, region)
    except PracticeLogError as exc:
        raise HTTPException(exc.status_code, {"code": exc.code, "message": exc.message}) from exc
