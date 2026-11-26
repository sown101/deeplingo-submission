"""Content-owned persistence ports: only the repository methods the content application calls."""
from __future__ import annotations

from typing import Protocol
from uuid import UUID

from app.modules.content.domain.extraction import GrammarCatalogueItem
from app.modules.content.domain.catalog import (
    Channel,
    Language,
    RomanizationSystem,
    SegmentRomanization,
    SegmentTranslation,
    TranscriptSegment,
    Video,
    VideoTranscript,
)
from app.modules.content.domain.knowledge import Concept, ConceptDictionaryLink, DictionaryEntry, LearningObject
from app.modules.content.domain.library import LearnerVideo
from app.modules.content.domain.region_questions import RegionQuestion
from app.modules.content.domain.workspace import LearnerVideoWorkspace
from app.modules.content.domain.work_claims import ContentClaim
from app.modules.content.domain.work_intents import AdmittedVideoWork, VideoWorkIntent


class ContentWorkAdmissionConflict(ValueError):
    """A concurrent admission or changed product state made a retry ineligible."""


class ContentWorkBackpressure(ValueError):
    """The server-controlled durable Content admission budget is full."""


class ChannelStore(Protocol):
    def upsert_by_source_external(self, data: dict) -> Channel: ...


class ConceptDictionaryLinkStore(Protocol):
    def list_for_concept(self, concept_id: UUID) -> list[ConceptDictionaryLink]: ...

    def get_by_ids(self, concept_id: UUID, dictionary_entry_id: UUID) -> ConceptDictionaryLink | None: ...

    def upsert_link(
        self,
        *,
        concept_id: UUID,
        dictionary_entry_id: UUID,
        relation_type: str = "supports",
    ) -> ConceptDictionaryLink: ...


class ConceptStore(Protocol):
    def get_by_id(self, concept_id) -> Concept | None: ...

    def find_by_identity(
        self,
        *,
        language_code: str,
        concept_type: str,
        normalized_text: str,
        sense_key: str,
    ) -> Concept | None: ...

    def upsert_by_identity(self, data: dict) -> Concept: ...


class DictionaryEntryStore(Protocol):
    def get_by_id(self, dictionary_entry_id) -> DictionaryEntry | None: ...

    def get_many_by_ids(self, entry_ids: list[UUID]) -> dict[UUID, DictionaryEntry]: ...

    def get_by_normalized(
        self,
        *,
        language_code: str,
        normalized_headword: str,
        part_of_speech: str = "",
    ) -> DictionaryEntry | None: ...

    def list_by_headwords(self, *, language_code: str, normalized_headwords: list[str]) -> list[DictionaryEntry]: ...

    def upsert_by_lookup(self, data: dict) -> DictionaryEntry: ...


class GrammarCatalogueStore(Protocol):
    """Curriculum grammar points offered to extraction."""

    def catalogue_for_language(self, language_code: str) -> list[GrammarCatalogueItem]: ...


class LanguageStore(Protocol):
    def get_active(self, code: str) -> Language | None: ...


class LearnerVideoStore(Protocol):
    def get_for_user(self, *, library_item_id: UUID, user_id: UUID) -> LearnerVideo | None: ...

    def list_for_user(self, user_id: UUID, *, limit: int = 50) -> list[LearnerVideo]: ...


class LearnerVideoWorkspaceStore(Protocol):
    def get_for_user(self, *, library_item_id: UUID, user_id: UUID) -> LearnerVideoWorkspace | None: ...

    def list_recent_for_user(self, *, user_id: UUID, limit: int) -> list[LearnerVideoWorkspace]: ...

    def save_position(self, *, library_item_id: UUID, user_id: UUID, position_ms: int) -> LearnerVideoWorkspace: ...

    def save_region(
        self,
        *,
        library_item_id: UUID,
        user_id: UUID,
        transcript_id: UUID,
        start_segment_id: UUID,
        end_segment_id: UUID,
    ) -> LearnerVideoWorkspace: ...


class RegionPreparationStore(Protocol):
    """M1 S2: region readiness rows and their admission RPC."""

    def admit(
        self, *, user_id: UUID, library_item_id: UUID, transcript_id: UUID,
        start_segment_id: UUID, end_segment_id: UUID, support_language_code: str,
        preparation_version: str, max_segments: int, limit: int, window_seconds: int,
    ) -> RegionAdmission: ...

    def find(
        self, *, transcript_id: UUID, start_segment_id: UUID, end_segment_id: UUID,
        support_language_code: str, preparation_version: str,
    ) -> RegionPreparation | None: ...

    def get_by_id(self, region_preparation_id: UUID) -> RegionPreparation | None: ...

    def list_for_transcript(
        self, *, transcript_id: UUID, support_language_code: str, preparation_version: str,
    ) -> list[RegionPreparation]: ...


class RegionQuestionStore(Protocol):
    """M1 S6: a prepared region's questions. Reads only; the worker writes through its claim."""

    def list_for_region(self, region_preparation_id: UUID) -> list[RegionQuestion]: ...


class ClaimedRegionQuestionWriter(Protocol):
    def write(self, *, status: str, questions: list[dict]) -> int: ...


class LearningObjectStore(Protocol):
    def list_for_video(self, video_id: UUID) -> list[LearningObject]: ...

    def list_for_videos_concepts(self, video_ids: list[UUID], concept_ids: list[UUID]) -> list[LearningObject]: ...

    def get_by_id(self, learning_object_id: UUID) -> LearningObject | None: ...

    def list_for_segment_concept(self, *, concept_id: UUID, transcript_segment_id: UUID) -> list[LearningObject]: ...

    def get_by_span(
        self, *, concept_id: UUID, transcript_segment_id: UUID,
        start_codepoint: int, end_codepoint: int,
    ) -> LearningObject | None: ...

    def upsert_by_occurrence(self, data: dict) -> LearningObject: ...

    def update_enrichment(self, learning_object_id: UUID, data: dict) -> LearningObject: ...

    def record_sense_review(
        self, learning_object_id: UUID, *, target_language_code: str, review: dict, raw_ai_diagnostics: dict,
    ) -> LearningObject | None:
        """Withdraw this language's meaning and record that no offered sense fits.

        `raw_ai_diagnostics` is the caller's prepared result; a claimed store ignores it and merges
        `review` into the locked row instead (A26).
        """
        ...


class RomanizationSystemStore(Protocol):
    def get_by_language_and_code(
        self,
        language_code: str,
        code: str,
    ) -> RomanizationSystem | None: ...


class SegmentRomanizationStore(Protocol):
    def upsert_many(self, romanizations: list[dict]) -> list[SegmentRomanization]: ...


class SegmentTranslationStore(Protocol):
    def get_by_segment_language(self, transcript_segment_id, language_code: str) -> SegmentTranslation | None: ...

    def translated_segment_ids(self, segment_ids: list[UUID], language_code: str) -> set[UUID]: ...

    def upsert_many(self, translations: list[dict]) -> list[SegmentTranslation]: ...


class TranscriptSegmentStore(Protocol):
    def upsert_many(self, segments: list[dict]) -> list[TranscriptSegment]: ...

    def list_for_transcript(self, transcript_id: UUID) -> list[TranscriptSegment]: ...

    def get_by_id(self, segment_id: UUID) -> TranscriptSegment | None: ...

    def list_by_ids(self, segment_ids: list[UUID]) -> list[TranscriptSegment]: ...

    def get_neighbor(
        self,
        *,
        transcript_id: UUID,
        sequence_number: int,
        offset: int,
    ) -> TranscriptSegment | None: ...


class VideoStore(Protocol):
    def create_pending_by_source_external(self, data: dict) -> tuple[Video, bool]: ...

    def get_by_id(self, video_id: UUID) -> Video | None: ...

    def get_many_by_ids(self, video_ids: list[UUID]) -> dict[UUID, Video]: ...

    def get_by_source_external(self, source: str, external_video_id: str) -> Video | None: ...

    def update_status(
        self,
        video_id: UUID,
        status: str,
        *,
        failure_code: str | None = None,
        retryable: bool = False,
        expected_status: str | None = None,
    ) -> Video | None: ...

    def finish_learning_preparation(
        self, video_id: UUID, *, status: str, usable_count: int,
        support_language_code: str | None, failure_code: str | None = None,
        retryable: bool = False,
    ) -> Video | None: ...


class VideoTranscriptStore(Protocol):
    def upsert_track(self, data: dict) -> VideoTranscript: ...

    def list_for_video(self, video_id: UUID) -> list[VideoTranscript]: ...

    def list_for_videos(self, video_ids: list[UUID]) -> list[VideoTranscript]: ...

    def get_by_id(self, transcript_id: UUID) -> VideoTranscript | None: ...


class VideoWorkIntentStore(Protocol):
    def get(self, intent_id: UUID) -> VideoWorkIntent | None: ...

    def due(self, *, limit: int = 50) -> list[VideoWorkIntent]: ...

    def record_dispatch(self, intent_id: UUID, *, accepted: bool) -> None: ...

    def admit(
        self, *, user_id: UUID, video_id: UUID, action: str,
        library_item_id: UUID | None = None,
    ) -> AdmittedVideoWork: ...

    def complete_transcript(self, claim: ContentClaim) -> tuple[Video, UUID | None]: ...
