import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from app.modules.identity.contracts import CurrentUser
from app.modules.content.domain.library import (
    ContentProcessingFailureCode,
    LearnerVideoImportResponse,
    LibraryVideoDetail,
    LibraryVideoFailure,
    LibraryVideoSummary,
    LearningPreparationStatus,
    ProductVideoProcessingStatus,
)
from app.modules.content.domain.catalog import Video
from app.modules.content.application.ingestion import ContentIngestionService
from app.modules.content.application.store_ports import (
    ContentWorkAdmissionConflict,
    ContentWorkBackpressure,
    LearnerVideoStore,
    VideoStore,
    VideoTranscriptStore,
    VideoWorkIntentStore,
)


logger = logging.getLogger(__name__)


_FAILURE_MESSAGES = {
    ContentProcessingFailureCode.INVALID_VIDEO_URL: "Enter a valid YouTube video URL.",
    ContentProcessingFailureCode.VIDEO_UNAVAILABLE: "This YouTube video is unavailable.",
    ContentProcessingFailureCode.TRANSCRIPT_UNAVAILABLE: "A usable transcript is not available for this video.",
    ContentProcessingFailureCode.UNSUPPORTED_CONTENT: "This video is not supported for learning yet.",
    ContentProcessingFailureCode.PROCESSING_FAILED: "Video processing failed. Try again later.",
}


class LearnerLibraryError(ValueError):
    def __init__(self, message: str, *, status_code: int, code: str, retry_after_seconds: int | None = None):
        self.status_code = status_code
        self.code = code
        self.retry_after_seconds = retry_after_seconds
        super().__init__(message)


@dataclass(frozen=True)
class ImportBudgetDecision:
    allowed: bool
    charged: bool
    used: int
    limit: int
    reset_at: datetime | None


class NewVideoImportBudget(Protocol):
    """O12: charges a learner one slot for a video that still needs AI work (idempotent per video)."""

    def charge(self, *, user_id: UUID, video_id: UUID) -> ImportBudgetDecision: ...


class LearnerLibraryService:
    def __init__(
        self,
        *,
        library: LearnerVideoStore,
        videos: VideoStore,
        transcripts: VideoTranscriptStore,
        ingestion: ContentIngestionService,
        work_intents: VideoWorkIntentStore,
        dispatcher,
        import_budget: NewVideoImportBudget,
    ):
        self.import_budget = import_budget
        self.library = library
        self.videos = videos
        self.transcripts = transcripts
        self.ingestion = ingestion
        self.work_intents = work_intents
        self.dispatcher = dispatcher

    def import_video(self, current_user: CurrentUser, url: str) -> LearnerVideoImportResponse:
        video, _ = self.ingestion.prepare_video(url)
        if video.id is None:
            raise LearnerLibraryError(
                "Video preparation did not return persistent identity.",
                status_code=503,
                code="video_identity_unavailable",
            )
        self._charge_import(current_user, video)
        admitted = self._admit(
            user_id=current_user.id, video_id=video.id, action="import",
        )
        if admitted.dispatch_now:
            self._dispatch_best_effort(admitted.intent_id)
        return LearnerVideoImportResponse(
            command_status=admitted.command_status,
            item=self._detail(admitted.association, admitted.video),
        )

    def retry_video(
        self,
        current_user: CurrentUser,
        library_item_id: UUID,
    ) -> LearnerVideoImportResponse:
        association = self._association_for_user(current_user, library_item_id)
        video = self._video(association.video_id)
        if video.processing_status != "failed" or not video.processing_retryable:
            raise LearnerLibraryError(
                "This Library item cannot be retried.",
                status_code=409,
                code="video_not_retryable",
            )
        try:
            admitted = self._admit(
                user_id=current_user.id, video_id=video.id,
                action="retry_transcript", library_item_id=association.id,
            )
        except ContentWorkAdmissionConflict as exc:
            raise LearnerLibraryError(
                "This Library item cannot be retried.", status_code=409, code="video_not_retryable",
            ) from exc
        if admitted.dispatch_now:
            self._dispatch_best_effort(admitted.intent_id)
        return LearnerVideoImportResponse(
            command_status=admitted.command_status,
            item=self._detail(admitted.association, admitted.video),
        )

    def list_videos(self, current_user: CurrentUser) -> list[LibraryVideoSummary]:
        summaries: list[LibraryVideoSummary] = []
        associations = self.library.list_for_user(current_user.id)
        videos = self.videos.get_many_by_ids([association.video_id for association in associations])
        for association in associations:
            video = videos.get(association.video_id)
            if video is not None:
                summaries.append(self._summary(association, video))
        return summaries

    def get_video(self, current_user: CurrentUser, library_item_id: UUID) -> LibraryVideoDetail:
        association = self._association_for_user(current_user, library_item_id)
        return self._detail(association, self._video(association.video_id))

    def retry_learning(self, current_user: CurrentUser, library_item_id: UUID) -> LearnerVideoImportResponse:
        association = self._association_for_user(current_user, library_item_id)
        video = self._video(association.video_id)
        if video.processing_status not in {"transcript_ready", "learning_objects_ready"}:
            raise LearnerLibraryError(
                "Video transcript is not ready.", status_code=409, code="content_not_ready",
            )
        if video.learning_status != "failed" or not video.learning_retryable:
            raise LearnerLibraryError(
                "Learning preparation cannot be retried.", status_code=409, code="learning_not_retryable",
            )
        try:
            admitted = self._admit(
                user_id=current_user.id, video_id=video.id,
                action="retry_preparation", library_item_id=association.id,
            )
        except ContentWorkAdmissionConflict as exc:
            raise LearnerLibraryError(
                "Learning preparation cannot be retried.", status_code=409, code="learning_not_retryable",
            ) from exc
        if admitted.dispatch_now:
            self._dispatch_best_effort(admitted.intent_id)
        return LearnerVideoImportResponse(
            command_status=admitted.command_status,
            item=self._detail(admitted.association, admitted.video),
        )

    def _charge_import(self, current_user: CurrentUser, video: Video) -> None:
        """O12: a video nobody has prepared yet costs AI work, so it spends the learner's budget."""
        if video.learning_status == "ready":
            return
        decision = self.import_budget.charge(user_id=current_user.id, video_id=video.id)
        if decision.allowed:
            return
        wait = None
        if decision.reset_at is not None:
            wait = max(1, int((decision.reset_at - datetime.now(UTC)).total_seconds()))
        raise LearnerLibraryError(
            f"You have imported {decision.used} new videos recently, which is the limit for now. "
            "Videos that are already prepared are not counted. Please try again later.",
            status_code=429, code="new_video_budget_exhausted", retry_after_seconds=wait,
        )

    def _admit(self, **parameters):
        try:
            return self.work_intents.admit(**parameters)
        except ContentWorkBackpressure as exc:
            raise LearnerLibraryError("Content is busy. Try again later.",
                status_code=503, code="content_backlog_full") from exc

    def _association_for_user(self, current_user: CurrentUser, library_item_id: UUID):
        association = self.library.get_for_user(
            library_item_id=library_item_id,
            user_id=current_user.id,
        )
        if association is None:
            raise LearnerLibraryError(
                "Library item not found.",
                status_code=404,
                code="library_item_not_found",
            )
        return association

    def _video(self, video_id: UUID) -> Video:
        video = self.videos.get_by_id(video_id)
        if video is None:
            raise LearnerLibraryError(
                "Library item not found.",
                status_code=404,
                code="library_item_not_found",
            )
        return video

    def _dispatch_best_effort(self, intent_id: UUID | None) -> None:
        if intent_id is None:
            return
        try:
            self.dispatcher.dispatch(intent_id)
        except Exception:
            # Admission already committed: broker or dispatch-metadata failure
            # cannot turn accepted work into a failed/forgotten business state.
            logger.error("Content work immediate dispatch unavailable intent_id=%s", intent_id)

    def _detail(self, association, video: Video) -> LibraryVideoDetail:
        summary = self._summary(association, video)
        transcript_available = bool(self.transcripts.list_for_video(video.id))
        return LibraryVideoDetail(
            **summary.model_dump(),
            description=video.description,
            transcript_available=transcript_available,
        )

    def _summary(self, association, video: Video) -> LibraryVideoSummary:
        return LibraryVideoSummary(
            library_item_id=association.id,
            video_id=video.id,
            title=video.title,
            thumbnail_url=video.thumbnail_url,
            duration_ms=video.duration_ms,
            source=video.source,
            processing_status=_product_status(video.processing_status),
            learning_status=LearningPreparationStatus(video.learning_status),
            learning_object_count=video.learning_object_count,
            learning_prepared_language_code=video.learning_prepared_language_code,
            language_code=video.original_language_code,
            added_at=association.created_at,
            failure=_safe_failure(video),
        )


def _product_status(status: str) -> ProductVideoProcessingStatus:
    if status == "pending":
        return ProductVideoProcessingStatus.PENDING
    if status == "processing":
        return ProductVideoProcessingStatus.PROCESSING
    if status in {"transcript_ready", "learning_objects_ready"}:
        return ProductVideoProcessingStatus.READY
    if status == "failed":
        return ProductVideoProcessingStatus.FAILED
    raise LearnerLibraryError(
        "Video processing state is unavailable.",
        status_code=503,
        code="processing_state_unavailable",
    )


def _safe_failure(video: Video) -> LibraryVideoFailure | None:
    if video.processing_status != "failed":
        return None
    try:
        code = ContentProcessingFailureCode(
            video.processing_error_code or ContentProcessingFailureCode.PROCESSING_FAILED.value
        )
    except ValueError:
        code = ContentProcessingFailureCode.PROCESSING_FAILED
    return LibraryVideoFailure(
        code=code,
        retryable=video.processing_retryable,
        message=_FAILURE_MESSAGES[code],
    )
