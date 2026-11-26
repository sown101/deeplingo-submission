from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.modules.identity.api.dependencies import require_authenticated_user
from app.modules.identity.contracts import CurrentUser
from app.modules.content.domain.library import (
    LearnerVideoImportRequest,
    LearnerVideoImportResponse,
    LibraryVideoDetail,
    LibraryVideoSummary,
)
from app.modules.content.application.ingestion import ContentIngestionError
from app.modules.content.application.library import LearnerLibraryError, LearnerLibraryService
from app.bootstrap.wiring.content import get_learner_library_service, get_library_import_limiter
from app.platform.rate_limit import SlidingWindowLimiter


router = APIRouter()


@router.post(
    "/learner/me/library/videos",
    response_model=LearnerVideoImportResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def import_library_video(
    request: LearnerVideoImportRequest,
    current_user: CurrentUser = Depends(require_authenticated_user),
    service: LearnerLibraryService = Depends(get_learner_library_service),
    limiter: SlidingWindowLimiter = Depends(get_library_import_limiter),
) -> LearnerVideoImportResponse:
    if not limiter.allow(str(current_user.id), "import"):
        raise HTTPException(
            status_code=429, headers={"Retry-After": "60"},
            detail={"code": "import_rate_limited", "message": "Too many import requests. Please wait a moment."},
        )
    try:
        return service.import_video(current_user, request.url)
    except ContentIngestionError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"code": exc.code.value, "message": exc.public_message},
        ) from exc
    except LearnerLibraryError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"code": exc.code, "message": str(exc)},
            headers={"Retry-After": str(exc.retry_after_seconds)} if exc.retry_after_seconds else None,
        ) from exc


@router.get(
    "/learner/me/library/videos",
    response_model=list[LibraryVideoSummary],
)
def list_library_videos(
    current_user: CurrentUser = Depends(require_authenticated_user),
    service: LearnerLibraryService = Depends(get_learner_library_service),
) -> list[LibraryVideoSummary]:
    return service.list_videos(current_user)


@router.get(
    "/learner/me/library/videos/{library_item_id}",
    response_model=LibraryVideoDetail,
)
def get_library_video(
    library_item_id: UUID,
    current_user: CurrentUser = Depends(require_authenticated_user),
    service: LearnerLibraryService = Depends(get_learner_library_service),
) -> LibraryVideoDetail:
    try:
        return service.get_video(current_user, library_item_id)
    except LearnerLibraryError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc


@router.post(
    "/learner/me/library/videos/{library_item_id}/retry",
    response_model=LearnerVideoImportResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def retry_library_video(
    library_item_id: UUID,
    current_user: CurrentUser = Depends(require_authenticated_user),
    service: LearnerLibraryService = Depends(get_learner_library_service),
) -> LearnerVideoImportResponse:
    try:
        return service.retry_video(current_user, library_item_id)
    except LearnerLibraryError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc


@router.post(
    "/learner/me/library/videos/{library_item_id}/learning/retry",
    response_model=LearnerVideoImportResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def retry_library_learning_preparation(
    library_item_id: UUID,
    current_user: CurrentUser = Depends(require_authenticated_user),
    service: LearnerLibraryService = Depends(get_learner_library_service),
) -> LearnerVideoImportResponse:
    try:
        return service.retry_learning(current_user, library_item_id)
    except LearnerLibraryError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc
