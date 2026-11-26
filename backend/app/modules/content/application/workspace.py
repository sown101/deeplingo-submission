"""M1 S1 video workspace: per-Library-item watch position and study region.

Every read and write resolves the learner's own Library item -> Video -> current original
transcript first; segment IDs from the client are selectors checked against that transcript
version, never proof of access. Nothing here creates Attempts, Evidence, mastery or review.

M1 S2: saving a region also asks for its learning preparation (`admit_region_preparation`,
budgeted per learner) and the view reports that region's readiness. Watching, Dictation,
Shadowing and word lookup never wait for it.

M1 S7: choosing a different region is reported to the practice log (best effort), where it starts
the learner's session.

M1 S6: the current region's comprehension questions are read here (with the answer key, for the
learning module that checks answers); the view only says whether they exist.
"""
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictInt

from app.kernel.region_ids import region_id
from app.modules.content.application.library import LearnerLibraryError
from app.modules.content.application.playback import original_track, owned_ready_video
from app.modules.content.application.store_ports import (
    LearnerVideoStore,
    LearnerVideoWorkspaceStore,
    RegionPreparationStore,
    RegionQuestionStore,
    TranscriptSegmentStore,
    VideoStore,
    VideoTranscriptStore,
)
from app.modules.content.domain.region_preparation import RegionAdmission, RegionPreparationStatus
from app.modules.content.domain.region_questions import RegionQuestion
from app.modules.content.domain.workspace import (
    MAX_POSITION_MS,
    MAX_REGION_SEGMENTS,
    LearnerVideoWorkspace,
    RegionRejected,
    clamp_position,
    region_bounds,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RegionPreparationPolicy:
    support_language_code: str
    preparation_version: str
    limit: int
    window_seconds: int


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


RegionPreparationState = Literal[
    "pending", "processing", "ready", "no_content", "failed",
    "budget_exhausted", "transcript_unavailable", "region_unavailable", "unavailable", "busy",
]


class RegionPreparationView(_Strict):
    """Readiness of the region's learning content; `unavailable` = could not be asked now."""
    status: RegionPreparationState
    usable_count: int = Field(default=0, ge=0)
    retryable: bool = False
    reset_at: datetime | None = None
    questions_status: Literal["ready", "none", "failed"] | None = None


class WatchPositionRequest(_Strict):
    position_ms: StrictInt = Field(ge=0, le=MAX_POSITION_MS)


class StudyRegionRequest(_Strict):
    start_segment_id: UUID
    end_segment_id: UUID


class StudyRegionView(_Strict):
    transcript_id: UUID
    start_segment_id: UUID
    end_segment_id: UUID
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)
    segment_count: int = Field(ge=1)
    preparation: RegionPreparationView | None = None


# M1 S7b: `not_prepared` = no preparation exists for this part (not asked, refused for budget or
# busy); only `preparing` means work is pending or running, so only it is worth polling.
CurrentQuestionsStatus = Literal["no_region", "not_prepared", "preparing", "ready", "none", "unavailable"]


@dataclass(frozen=True)
class CurrentRegionQuestions:
    """The questions of the learner's current region, answer keys included (server use only)."""

    status: CurrentQuestionsStatus
    transcript_id: UUID | None = None
    questions: tuple[RegionQuestion, ...] = ()
    region_id: str | None = None


class VideoWorkspaceView(_Strict):
    library_item_id: UUID
    position_ms: int | None = Field(default=None, ge=0)
    region: StudyRegionView | None = None
    updated_at: datetime | None = None


class ContinueLearningItem(_Strict):
    library_item_id: UUID
    title: str
    thumbnail_url: str | None = None
    duration_ms: int | None = Field(default=None, ge=0)
    position_ms: int | None = Field(default=None, ge=0)
    region: StudyRegionView | None = None
    updated_at: datetime | None = None


class ContinueLearningView(_Strict):
    """M2.2: where the learner left off, the most recently saved workspace of a video still in their
    Library and ready to watch; `item` is None when there is none. Opening the video resumes the saved
    position and study region (M1 S1)."""

    item: ContinueLearningItem | None = None


# Recent workspaces looked at to find one whose video is still owned and ready (most recent first).
CONTINUE_LEARNING_CANDIDATES = 5


class VideoWorkspaceService:
    def __init__(
        self,
        *,
        library: LearnerVideoStore,
        videos: VideoStore,
        transcripts: VideoTranscriptStore,
        segments: TranscriptSegmentStore,
        workspaces: LearnerVideoWorkspaceStore,
        regions: RegionPreparationStore | None = None,
        dispatcher=None,
        preparation_policy: RegionPreparationPolicy | None = None,
        questions: RegionQuestionStore | None = None,
    ):
        if (regions is None) != (preparation_policy is None):
            raise ValueError("Region preparation needs both its store and its policy")
        self.library = library
        self.videos = videos
        self.transcripts = transcripts
        self.segments = segments
        self.workspaces = workspaces
        self.regions = regions
        self.dispatcher = dispatcher
        self.preparation_policy = preparation_policy
        self.questions = questions

    def get(self, user, item_id: UUID) -> VideoWorkspaceView:
        video = owned_ready_video(self.library, self.videos, user, item_id)
        state = self.workspaces.get_for_user(library_item_id=item_id, user_id=user.id)
        return self._view(item_id, video, state)

    def continue_learning(self, user) -> ContinueLearningView:
        """The most recent workspace whose video is still in the learner's Library and ready, and that
        still has a place to resume: a position, or a region that matches the current transcript."""
        for state in self.workspaces.list_recent_for_user(user_id=user.id, limit=CONTINUE_LEARNING_CANDIDATES):
            if state.user_id != user.id or (state.position_ms is None and state.region_transcript_id is None):
                continue
            try:
                video = owned_ready_video(self.library, self.videos, user, state.library_item_id)
            except LearnerLibraryError:
                continue  # removed from the Library or no longer playable: look at the next one
            region = self._region(video, state)
            if state.position_ms is None and region is None:
                continue  # only a region of an older transcript version: nothing left to resume here
            return ContinueLearningView(item=ContinueLearningItem(
                library_item_id=state.library_item_id, title=video.title, thumbnail_url=video.thumbnail_url,
                duration_ms=video.duration_ms, position_ms=state.position_ms,
                region=region, updated_at=state.updated_at,
            ))
        return ContinueLearningView()

    def save_position(self, user, item_id: UUID, request: WatchPositionRequest) -> VideoWorkspaceView:
        video = owned_ready_video(self.library, self.videos, user, item_id)
        state = self.workspaces.save_position(
            library_item_id=item_id, user_id=user.id,
            position_ms=clamp_position(request.position_ms, video.duration_ms),
        )
        return self._view(item_id, video, state)

    def save_region(self, user, item_id: UUID, request: StudyRegionRequest) -> VideoWorkspaceView:
        video = owned_ready_video(self.library, self.videos, user, item_id)
        track = original_track(self.transcripts, video)
        start = self._segment_of(track.id, request.start_segment_id)
        end = self._segment_of(track.id, request.end_segment_id)
        try:
            start_ms, end_ms, count = region_bounds(start, end)
        except RegionRejected as exc:
            raise LearnerLibraryError(str(exc), status_code=422, code="region_invalid") from exc
        state = self.workspaces.save_region(
            library_item_id=item_id, user_id=user.id, transcript_id=track.id,
            start_segment_id=start.id, end_segment_id=end.id,
        )
        admission = self._admit(user, item_id, track.id, start.id, end.id)
        return self._view(item_id, video, state, admission=admission)

    def current_region_questions(self, user, item_id: UUID) -> CurrentRegionQuestions:
        """Ownership, current transcript version and region range are rechecked on every read."""
        video = owned_ready_video(self.library, self.videos, user, item_id)
        state = self.workspaces.get_for_user(library_item_id=item_id, user_id=user.id)
        region = self._region(video, state) if state is not None else None
        if region is None:
            return CurrentRegionQuestions(status="no_region")
        if self.regions is None or self.preparation_policy is None or self.questions is None:
            return CurrentRegionQuestions(status="unavailable", transcript_id=region.transcript_id)
        try:
            row = self.regions.find(
                transcript_id=region.transcript_id, start_segment_id=region.start_segment_id,
                end_segment_id=region.end_segment_id,
                support_language_code=self.preparation_policy.support_language_code,
                preparation_version=self.preparation_policy.preparation_version,
            )
            if row is None:
                return CurrentRegionQuestions(status="not_prepared", transcript_id=region.transcript_id)
            if row.status in (RegionPreparationStatus.PENDING, RegionPreparationStatus.PROCESSING):
                return CurrentRegionQuestions(status="preparing", transcript_id=region.transcript_id)
            if row.questions_status != "ready":
                status = "none" if row.questions_status == "none" else "unavailable"
                return CurrentRegionQuestions(status=status, transcript_id=region.transcript_id)
            questions = tuple(self.questions.list_for_region(row.id))
        except Exception:
            logger.warning("Region questions read unavailable library_item_id=%s", item_id)
            return CurrentRegionQuestions(status="unavailable", transcript_id=region.transcript_id)
        return CurrentRegionQuestions(status="ready" if questions else "none",
                                      transcript_id=region.transcript_id, questions=questions,
                                      region_id=region_id(region.start_segment_id, region.end_segment_id))

    def _admit(self, user, item_id: UUID, transcript_id: UUID, start_id: UUID, end_id: UUID) -> RegionAdmission | None:
        """Ask for this region's preparation. The region itself is already saved either way."""
        if self.regions is None or self.preparation_policy is None:
            return None
        policy = self.preparation_policy
        try:
            admission = self.regions.admit(
                user_id=user.id, library_item_id=item_id, transcript_id=transcript_id,
                start_segment_id=start_id, end_segment_id=end_id,
                support_language_code=policy.support_language_code,
                preparation_version=policy.preparation_version, max_segments=MAX_REGION_SEGMENTS,
                limit=policy.limit, window_seconds=policy.window_seconds,
            )
        except Exception:
            # Unknown outcome: the next read shows whatever was committed. Never a learner failure.
            logger.warning("Region preparation admission unavailable library_item_id=%s", item_id)
            return RegionAdmission(status="unavailable")
        if admission.dispatch_now and admission.intent_id is not None and self.dispatcher is not None:
            try:
                self.dispatcher.dispatch(admission.intent_id)
            except Exception:
                # Admission committed; the reconciler republishes due intents.
                logger.error("Region preparation immediate dispatch unavailable intent_id=%s", admission.intent_id)
        return admission

    def _segment_of(self, transcript_id: UUID, segment_id: UUID):
        segment = self.segments.get_by_id(segment_id)
        if segment is None or segment.transcript_id != transcript_id:
            # Same answer for unknown, foreign and old-version segments.
            raise LearnerLibraryError(
                "This part of the transcript is not available. Reload the transcript.",
                status_code=409, code="region_unavailable",
            )
        return segment

    def _view(self, item_id: UUID, video, state: LearnerVideoWorkspace | None, *,
              admission: RegionAdmission | None = None) -> VideoWorkspaceView:
        if state is None:
            return VideoWorkspaceView(library_item_id=item_id)
        return VideoWorkspaceView(
            library_item_id=item_id, position_ms=state.position_ms,
            region=self._region(video, state, admission), updated_at=state.updated_at,
        )

    def _preparation(self, transcript_id: UUID, start_id: UUID, end_id: UUID,
                     admission: RegionAdmission | None) -> RegionPreparationView | None:
        if self.regions is None or self.preparation_policy is None:
            return None
        if admission is not None:
            return RegionPreparationView(status=admission.status, usable_count=admission.usable_count,
                                         retryable=admission.retryable, reset_at=admission.reset_at)
        try:
            row = self.regions.find(
                transcript_id=transcript_id, start_segment_id=start_id, end_segment_id=end_id,
                support_language_code=self.preparation_policy.support_language_code,
                preparation_version=self.preparation_policy.preparation_version,
            )
        except Exception:
            logger.warning("Region preparation read unavailable transcript_id=%s", transcript_id)
            return RegionPreparationView(status="unavailable")
        if row is None:
            return None
        return RegionPreparationView(status=row.status.value, usable_count=row.usable_count, retryable=row.retryable,
                                     questions_status=row.questions_status)

    def _region(self, video, state: LearnerVideoWorkspace,
                admission: RegionAdmission | None = None) -> StudyRegionView | None:
        """The stored region if it still matches the current transcript version, else none."""
        if state.region_transcript_id is None or state.region_start_segment_id is None \
                or state.region_end_segment_id is None:
            return None
        try:
            track = original_track(self.transcripts, video)
        except LearnerLibraryError:
            return None
        if track.id != state.region_transcript_id:
            return None
        try:
            start = self._segment_of(track.id, state.region_start_segment_id)
            end = self._segment_of(track.id, state.region_end_segment_id)
            start_ms, end_ms, count = region_bounds(start, end)
        except (LearnerLibraryError, RegionRejected):
            return None
        return StudyRegionView(
            transcript_id=track.id, start_segment_id=start.id, end_segment_id=end.id,
            start_ms=start_ms, end_ms=end_ms, segment_count=count,
            preparation=self._preparation(track.id, start.id, end.id, admission),
        )
