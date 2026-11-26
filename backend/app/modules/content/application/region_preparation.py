"""M1 S2: learning preparation of one claimed study region.

Runs the same trusted extraction, resolution and enrichment services as Video preparation,
on the region's segments only (neighbors are read as context). Segments already prepared by a
finished region of the same transcript, support language and version are not extracted again;
existing enrichment of an occurrence is reused by the enrichment service. All shared-content
writes go through the claim-fenced stores, which reject occurrences outside the region.

M1 S6: a region that did not fail then gets its comprehension questions (best effort).
"""
import logging
from uuid import UUID

from app.modules.content.application.enrichment import (
    DictionarySenseMismatch,
    LearningObjectEnrichmentError,
    LearningObjectEnrichmentService,
)
from app.modules.content.application.knowledge_resolution import V3CandidateResolutionService
from app.modules.content.application.preparation import LearningPreparationOutcome
from app.modules.content.domain.occurrence_spans import (
    MAX_PREPARED_OCCURRENCES_PER_CONCEPT,
    first_occurrences_per_concept,
    is_trusted_occurrence,
)
from app.modules.content.application.prompts import (
    CANDIDATE_EXTRACTION_PROMPT_VERSION,
    LEARNING_OBJECT_ENRICHMENT_PROMPT_VERSION,
)
from app.modules.content.application.region_questions import (
    REGION_QUESTIONS_GENERATION_VERSION,
    RegionQuestionGenerationService,
)
from app.modules.content.application.store_ports import (
    LearningObjectStore,
    RegionPreparationStore,
    TranscriptSegmentStore,
    VideoStore,
    VideoTranscriptStore,
)
from app.modules.content.domain.region_preparation import (
    PARTIAL_PREPARATION,
    RegionPreparationStatus,
    covered_sequences,
)
from app.modules.content.domain.region_questions import RegionSentence
from app.modules.content.domain.work_claims import ContentClaim
from app.platform.llm.port import LLMProviderError, LLMProviderFailureCategory

logger = logging.getLogger(__name__)

# Part of the region key: a new version is a new region row, never a rewrite of an old one.
# M1 S6 changed the prepared output (questions), so regions prepared before it are not reused.
REGION_PREPARATION_VERSION = (
    f"m1s6-1/{CANDIDATE_EXTRACTION_PROMPT_VERSION}/{LEARNING_OBJECT_ENRICHMENT_PROMPT_VERSION}"
    f"/{REGION_QUESTIONS_GENERATION_VERSION}"
)


class RegionPreparationService:
    def __init__(
        self, *, videos: VideoStore, transcripts: VideoTranscriptStore,
        segments: TranscriptSegmentStore, learning_objects: LearningObjectStore,
        regions: RegionPreparationStore, resolution: V3CandidateResolutionService,
        enrichment: LearningObjectEnrichmentService, propagate_failures: bool = False,
        questions: RegionQuestionGenerationService | None = None,
    ):
        self.videos = videos
        self.transcripts = transcripts
        self.segments = segments
        self.learning_objects = learning_objects
        self.regions = regions
        self.resolution = resolution
        self.enrichment = enrichment
        self.propagate_failures = propagate_failures
        self.questions = questions

    def prepare_claimed(self, claim: ContentClaim) -> LearningPreparationOutcome:
        """Call only after `claim_leased_content_work` returned this region claim."""
        if claim.stage != "region_preparation" or claim.region_preparation_id is None:
            raise ValueError("Region preparation requires a region claim")
        region = self.regions.get_by_id(claim.region_preparation_id)
        if (region is None or region.video_id != claim.video_id
                or region.status != RegionPreparationStatus.PROCESSING):
            raise ValueError("Region preparation is not claimed")
        video = self.videos.get_by_id(region.video_id)
        transcript = self.transcripts.get_by_id(region.transcript_id)
        if (video is None or transcript is None or transcript.id is None or not transcript.is_original
                or transcript.video_id != video.id or transcript.language_code != video.original_language_code):
            raise ValueError("Region transcript is unavailable")
        ordered = sorted(self.segments.list_for_transcript(transcript.id), key=lambda row: row.sequence_number)
        indexes = [index for index, row in enumerate(ordered) if region.covers(row.sequence_number)]
        if not indexes or ordered[indexes[0]].id != region.start_segment_id \
                or ordered[indexes[-1]].id != region.end_segment_id:
            raise ValueError("Region segments are unavailable")

        covered = covered_sequences(self.regions.list_for_transcript(
            transcript_id=transcript.id, support_language_code=region.support_language_code,
            preparation_version=region.preparation_version,
        ), exclude=region.id)
        region_segment_ids = {ordered[index].id for index in indexes}

        def trusted(row) -> bool:
            return (row.transcript_segment_id in region_segment_ids
                    and is_trusted_occurrence(row, video_id=video.id, transcript_id=transcript.id,
                                              segment_for=self.segments.get_by_id))

        rows: dict[UUID, object] = {}
        failures = 0
        extracted = 0
        for index in indexes:
            segment = ordered[index]
            if segment.sequence_number in covered:
                continue
            previous = ordered[index - 1].text if index > 0 else None
            following = ordered[index + 1].text if index + 1 < len(ordered) else None
            result = self.resolution.extract_and_resolve_by_segment_id(
                segment.id, previous_context=previous, next_context=following,
            )
            extracted += 1
            if result is None:
                failures += 1
                continue
            failures += len(result.errors)
            for resolved in result.resolved:
                if trusted(resolved.learning_object):
                    rows[resolved.learning_object.id] = resolved.learning_object
        for row in self.learning_objects.list_for_video(video.id):
            if trusted(row):
                rows[row.id] = row

        usable = 0
        for object_id in first_occurrences_per_concept(rows.values(), MAX_PREPARED_OCCURRENCES_PER_CONCEPT):
            try:
                prepared = self.enrichment.enrich(object_id, target_language_code=region.support_language_code)
                if prepared is None or not prepared.contextual_meaning.strip():
                    failures += 1
                else:
                    usable += 1
            except DictionarySenseMismatch:
                # Excluded from practice and recorded for review; not a preparation failure.
                logger.info("LearningObject excluded: no dictionary sense fits region_id=%s object_id=%s",
                            region.id, object_id)
            except LearningObjectEnrichmentError as exc:
                if self.propagate_failures and not _malformed_model_reply(exc):
                    raise
                failures += 1
                logger.warning("LearningObject enrichment failed region_id=%s object_id=%s", region.id, object_id)

        if usable:
            # M1 S7b: a part with failed sentences is usable but not "covered": another part over
            # the same sentences extracts them again (PARTIAL_PREPARATION is excluded from coverage).
            outcome = LearningPreparationOutcome("ready", usable, PARTIAL_PREPARATION if failures else None,
                                                 partial_failures=failures)
        elif failures:
            outcome = LearningPreparationOutcome("failed", 0, "preparation_incomplete", failures)
        else:
            outcome = LearningPreparationOutcome("no_content", 0)
        questions_status = None
        if outcome.status != "failed" and self.questions is not None:
            questions_status = self.questions.generate(
                sentences=[RegionSentence(ref=f"s{number}", segment_id=ordered[index].id, text=ordered[index].text)
                           for number, index in enumerate(indexes, start=1)],
                source_language=transcript.language_code, support_language=region.support_language_code,
            )
        logger.info(
            "Region preparation outcome region_id=%s status=%s usable=%s extracted_segments=%s "
            "skipped_segments=%s partial_failures=%s questions=%s version=%s",
            region.id, outcome.status, usable, extracted, len(indexes) - extracted, failures,
            questions_status, region.preparation_version,
        )
        return outcome


# A reply the model got wrong for one occurrence (unparseable, empty, refused) fails that word only; a
# transport, configuration or budget failure still propagates so the claimed region is retried as a whole.
_PER_OCCURRENCE_CATEGORIES = frozenset({
    LLMProviderFailureCategory.SCHEMA_VIOLATION, LLMProviderFailureCategory.EMPTY_RESPONSE,
    LLMProviderFailureCategory.REFUSAL, LLMProviderFailureCategory.INCOMPATIBLE_RESPONSE,
})


def _malformed_model_reply(exc: LearningObjectEnrichmentError) -> bool:
    cause = exc.__cause__
    return isinstance(cause, LLMProviderError) and cause.category in _PER_OCCURRENCE_CATEGORIES

