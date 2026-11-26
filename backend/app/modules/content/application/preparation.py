"""Global, bounded orchestration of existing trusted V3 learning services."""

import logging
from dataclasses import dataclass
from uuid import UUID

from app.modules.content.application.knowledge_resolution import V3CandidateResolutionService
from app.modules.content.application.enrichment import (
    DictionarySenseMismatch,
    LearningObjectEnrichmentError,
    LearningObjectEnrichmentService,
)
from app.modules.content.domain.occurrence_spans import (
    MAX_PREPARED_OCCURRENCES_PER_CONCEPT,
    first_occurrences_per_concept,
    is_trusted_occurrence,
)
from app.modules.content.application.prompts import (
    CANDIDATE_EXTRACTION_PROMPT_VERSION,
    LEARNING_OBJECT_ENRICHMENT_PROMPT_VERSION,
)
from app.modules.content.application.store_ports import (
    LearningObjectStore,
    TranscriptSegmentStore,
    VideoStore,
    VideoTranscriptStore,
)

logger = logging.getLogger(__name__)
LEARNING_PREPARATION_VERSION = (
    f"v6a6-1/{CANDIDATE_EXTRACTION_PROMPT_VERSION}/"
    f"{LEARNING_OBJECT_ENRICHMENT_PROMPT_VERSION}"
)


@dataclass(frozen=True)
class LearningPreparationOutcome:
    status: str
    usable_count: int
    failure_code: str | None = None
    partial_failures: int = 0


class LearningContentPreparationService:
    def __init__(
        self, *, videos: VideoStore, transcripts: VideoTranscriptStore,
        segments: TranscriptSegmentStore, learning_objects: LearningObjectStore,
        resolution: V3CandidateResolutionService,
        enrichment: LearningObjectEnrichmentService,
        support_language_code: str, max_segments: int,
        propagate_failures: bool = False,
    ):
        if not support_language_code.strip() or max_segments < 1:
            raise ValueError("Learning preparation configuration is invalid")
        self.videos = videos
        self.transcripts = transcripts
        self.segments = segments
        self.learning_objects = learning_objects
        self.resolution = resolution
        self.enrichment = enrichment
        self.support_language_code = support_language_code.strip().casefold()
        self.max_segments = max_segments
        self.propagate_failures = propagate_failures

    def prepare_claimed(self, video_id: UUID, *, persist_terminal: bool = True) -> LearningPreparationOutcome:
        """Call only after VideoStore's atomic global claim succeeds."""
        video = self.videos.get_by_id(video_id)
        if video is None or video.learning_status != "processing":
            raise ValueError("Video learning preparation is not claimed")
        transcript = next(
            (row for row in self.transcripts.list_for_video(video_id)
             if row.is_original and row.language_code == video.original_language_code),
            None,
        )
        if transcript is None or transcript.id is None:
            raise ValueError("Original persisted transcript is unavailable")
        segments = self.segments.list_for_transcript(transcript.id)[: self.max_segments]
        if not segments:
            raise ValueError("Original transcript has no persisted segments")

        def trusted(row) -> bool:
            return is_trusted_occurrence(row, video_id=video_id, transcript_id=transcript.id,
                                         segment_for=self.segments.get_by_id)

        rows: dict[UUID, object] = {
            row.id: row for row in self.learning_objects.list_for_video(video_id)
            if trusted(row)
        }
        failures = 0
        for index, segment in enumerate(segments):
            previous = segments[index - 1].text if index > 0 else None
            following = segments[index + 1].text if index + 1 < len(segments) else None
            result = self.resolution.extract_and_resolve_by_segment_id(
                segment.id, previous_context=previous, next_context=following,
            )
            if result is None:
                failures += 1
                continue
            failures += len(result.errors)
            for resolved in result.resolved:
                row = resolved.learning_object
                if trusted(row):
                    rows[row.id] = row

        object_ids = first_occurrences_per_concept(rows.values(), MAX_PREPARED_OCCURRENCES_PER_CONCEPT)
        usable = 0
        for object_id in object_ids:
            try:
                prepared = self.enrichment.enrich(
                    object_id, target_language_code=self.support_language_code,
                )
                if prepared is None or not prepared.contextual_meaning.strip():
                    failures += 1
                else:
                    usable += 1
            except DictionarySenseMismatch:
                # Excluded from practice and recorded for review; not a preparation failure.
                logger.info("LearningObject excluded: no dictionary sense fits video_id=%s object_id=%s",
                            video_id, object_id)
            except LearningObjectEnrichmentError as exc:
                if self.propagate_failures:
                    raise
                failures += 1
                logger.warning("LearningObject enrichment failed video_id=%s object_id=%s", video_id, object_id)

        if usable:
            outcome = LearningPreparationOutcome("ready", usable, partial_failures=failures)
        elif failures:
            outcome = LearningPreparationOutcome("failed", 0, "preparation_incomplete", failures)
        else:
            outcome = LearningPreparationOutcome("no_content", 0)
        if not persist_terminal:
            return outcome
        saved = self.videos.finish_learning_preparation(
            video_id, status=outcome.status, usable_count=outcome.usable_count,
            support_language_code=self.support_language_code if usable else None,
            failure_code=outcome.failure_code, retryable=outcome.status == "failed",
        )
        if saved is None:
            raise RuntimeError("Claimed learning preparation could not be finalized")
        logger.info(
            "Learning preparation terminal video_id=%s status=%s usable=%s partial_failures=%s version=%s",
            video_id, outcome.status, usable, failures, LEARNING_PREPARATION_VERSION,
        )
        return outcome

