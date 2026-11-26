"""Composition of speaking-practice services and the voice companion.

Routers reference these factories; tests override the same function objects.
Provider construction failures leave the capability unavailable (fail closed)
instead of failing unrelated API startup.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
from datetime import UTC, datetime
from functools import lru_cache
from uuid import UUID

import httpx
from fastapi import HTTPException, status

from app.bootstrap.wiring.activity import build_activity_service
from app.platform.rate_limit import SlidingWindowLimiter
from app.bootstrap.wiring.clients import redis_client, request_limiter
from app.platform.config import settings
from app.platform.supabase import supabase_service
from app.bootstrap.wiring.content import get_word_concept_service
from app.modules.learning.application.agent.ports import DictionarySense, DictionaryWord
from app.modules.learning.domain.companion import RegionLine, StudyRegionContext
from app.modules.content.domain.workspace import MAX_REGION_SEGMENTS
from app.modules.content.infrastructure.repositories.learner_video_workspaces import (
    LearnerVideoWorkspaceRepository,
)
from app.modules.learning.application.agent.text import TextChannel
from app.modules.learning.application.study_plan import ConversationFollowUpService
from app.modules.learning.infrastructure.study_plans import StudyPlanRepository
from app.modules.learning.application.learned_items import LearnedItemCatalog
from app.modules.learning.application.shadowing import ShadowingPracticeService
from app.modules.learning.application.speech_transcription import SpeechTranscriber
from app.modules.content.infrastructure.repositories.concepts import ConceptRepository
from app.modules.content.infrastructure.repositories.learner_videos import LearnerVideoRepository
from app.modules.content.infrastructure.repositories.learning_objects import (
    LearningObjectRepository,
)
from app.modules.content.infrastructure.repositories.transcript_segments import (
    TranscriptSegmentRepository,
)
from app.modules.learner.infrastructure.user_language_preferences import (
    UserLanguagePreferenceRepository,
)
from app.modules.content.infrastructure.repositories.video_transcripts import (
    VideoTranscriptRepository,
)
from app.modules.content.infrastructure.repositories.videos import VideoRepository
from app.platform.llm.openai_compatible import OpenAICompatibleLLMProvider
from app.modules.learning.infrastructure.speaking_activity import PronunciationScoreRepository
from app.modules.learning.infrastructure.speech.azure_pronunciation import (
    AzurePronunciationAssessor,
)
from app.modules.learning.infrastructure.speech.azure_tts import AzureSpeechSynthesizer
from app.modules.learning.infrastructure.speech.companion_tickets import SignedCompanionTicketCodec
from app.modules.review.infrastructure.review_states import ReviewStateRepository

logger = logging.getLogger(__name__)

SPEAKING_LIMITS = {
    "shadowing": (30, 300.0),
    "companion_start": (30, 3600.0),
    "companion_turn": (200, 3600.0),
    # A word read aloud (dictionary or saved card). The notebook can read a page of words in a row.
    "word_audio": (120, 300.0),
}


def _require_database():
    if not supabase_service:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail={"code": "speech_service_unavailable",
                                    "message": "Speech practice is temporarily unavailable."})
    return supabase_service


@lru_cache(maxsize=1)
def _pronunciation_assessor() -> AzurePronunciationAssessor | None:
    if not settings.AZURE_SPEECH_KEY or not settings.AZURE_SPEECH_REGION:
        return None
    return AzurePronunciationAssessor(
        key=settings.AZURE_SPEECH_KEY, region=settings.AZURE_SPEECH_REGION,
        client=httpx.Client(timeout=20.0),
    )


def _language_model(model_name: str) -> OpenAICompatibleLLMProvider | None:
    try:
        return OpenAICompatibleLLMProvider(model_name=model_name or settings.AI_MODEL_NAME)
    except Exception as exc:
        logger.warning("speaking language model unavailable error=%s", type(exc).__name__)
        return None


def speaking_ticket_secret() -> bytes | None:
    if settings.SPEAKING_TICKET_SECRET:
        return settings.SPEAKING_TICKET_SECRET.encode("utf-8")
    if settings.SUPABASE_SERVICE_ROLE_KEY:
        # Domain-separated derivation; the service key itself never signs tickets.
        # The label keeps its historical name: changing it would change the companion ticket key.
        return hmac.new(settings.SUPABASE_SERVICE_ROLE_KEY.encode("utf-8"),
                        b"deeplingo/speaking-jam-ticket/v1", hashlib.sha256).digest()
    return None


@lru_cache(maxsize=1)
def get_speaking_rate_limiter() -> SlidingWindowLimiter:
    return request_limiter(SPEAKING_LIMITS)


def _practice_log(client):
    """M1 S4: the learner's practice log (learning-owned)."""
    from app.modules.learning.application.practice_log import PracticeLogService
    return PracticeLogService(
        library=LearnerVideoRepository(client), videos=VideoRepository(client),
        transcripts=VideoTranscriptRepository(client), segments=TranscriptSegmentRepository(client),
        learning_log=build_activity_service(client),
    )


def get_practice_log_service():
    return _practice_log(_require_database())


class _RegionQuestions:
    """M1 S6: read-only adapter over the current region's questions (content data, keys included)."""

    def __init__(self, workspace):
        self.workspace = workspace

    def current(self, user, library_item_id: UUID):
        from app.modules.content.application.library import LearnerLibraryError
        from app.modules.learning.application.practice_log import PracticeLogError
        from app.modules.learning.application.region_questions import CurrentRegionQuestionSet, RegionQuestionItem
        try:
            current = self.workspace.current_region_questions(user, library_item_id)
        except LearnerLibraryError as exc:
            raise PracticeLogError(exc.status_code, exc.code, str(exc)) from exc
        return CurrentRegionQuestionSet(
            status=current.status, transcript_id=current.transcript_id, region_id=current.region_id,
            questions=tuple(RegionQuestionItem(
                id=row.id, position=row.position, question=row.question, options=tuple(row.options),
                correct_index=row.correct_index, evidence_segment_id=row.evidence_segment_id,
                evidence_quote=row.evidence_quote, explanation=row.explanation,
            ) for row in current.questions),
        )


def _study_regions(client) -> "_StudyRegions":
    return _StudyRegions(
        workspaces=LearnerVideoWorkspaceRepository(client), library=LearnerVideoRepository(client),
        videos=VideoRepository(client), transcripts=VideoTranscriptRepository(client),
        segments=TranscriptSegmentRepository(client),
    )


def get_region_result_service():
    """The result card of a study region, read back from the learning log."""
    from app.modules.learning.application.region_result import RegionResultService
    client = _require_database()
    return RegionResultService(library=LearnerVideoRepository(client), activity=build_activity_service(client))


def get_region_question_service():
    """M1 S6: region comprehension questions; answers go to the practice log only."""
    from app.bootstrap.wiring.content import get_video_workspace_service
    from app.modules.learning.application.region_questions import RegionQuestionService
    client = _require_database()
    return RegionQuestionService(questions=_RegionQuestions(get_video_workspace_service()),
                                 transcripts=VideoTranscriptRepository(client),
                                 learning_log=build_activity_service(client))


# Dictation checks and lookups are small; bound runaway client loops only.
PRACTICE_LOG_LIMITS = {"practice_event": (600, 3600.0)}


@lru_cache(maxsize=1)
def get_practice_log_limiter() -> SlidingWindowLimiter:
    return request_limiter(PRACTICE_LOG_LIMITS)


def get_shadowing_practice_service() -> ShadowingPracticeService:
    from app.bootstrap.wiring.learner import get_agent_signals_service
    client = _require_database()
    return ShadowingPracticeService(
        library=LearnerVideoRepository(client),
        videos=VideoRepository(client),
        transcripts=VideoTranscriptRepository(client),
        segments=TranscriptSegmentRepository(client),
        assessor=_pronunciation_assessor(),
        scores=PronunciationScoreRepository(client),
        consent=get_agent_signals_service(), learning_log=build_activity_service(client),
    )


def get_word_speech_service():
    """A dictionary word read aloud, and one attempt at saying it. The service holds the audio cache."""
    return _word_speech_service()


@lru_cache(maxsize=1)
def _word_speech_service():
    from app.bootstrap.wiring.learner import get_agent_signals_service
    from app.modules.content.infrastructure.repositories.dictionary_entries import DictionaryEntryRepository
    from app.modules.learning.application.word_speech import WordSpeechService
    client = _require_database()
    return WordSpeechService(dictionary=DictionaryEntryRepository(client), synthesizer=_speech_synthesizer(),
                             assessor=_pronunciation_assessor(), consent=get_agent_signals_service(),
                             scores=PronunciationScoreRepository(client), learning_log=build_activity_service(client))


def companion_ticket_secret() -> bytes | None:
    base_secret = speaking_ticket_secret()
    if base_secret is None:
        return None
    # Domain-separated from the base speaking secret so the two can never be confused.
    return hmac.new(base_secret, b"deeplingo/speaking-companion-ticket/v1", hashlib.sha256).digest()


@lru_cache(maxsize=1)
def _companion_ticket_codec() -> SignedCompanionTicketCodec | None:
    secret = companion_ticket_secret()
    return SignedCompanionTicketCodec(secret, ttl_seconds=900) if secret else None


@lru_cache(maxsize=1)
def companion_sessions():
    """Where text conversations live between turns. They hold learner text, so only the transient Redis of
    COMPANION_SESSION_TEXT_REDIS_URL may keep them (the store refuses one that writes to disk); without it, this
    process's memory (one API process only: a second process would not see the conversation)."""
    from app.modules.learning.application.agent.conversation import MemorySessionStore
    from app.modules.learning.infrastructure.agent_state import RedisSessionStore
    if settings.COMPANION_SESSION_TEXT_REDIS_URL:
        return RedisSessionStore(redis_client(settings.COMPANION_SESSION_TEXT_REDIS_URL))
    return MemorySessionStore()


@lru_cache(maxsize=1)
def _speech_synthesizer() -> AzureSpeechSynthesizer | None:
    if settings.COMPANION_TTS_PROVIDER != "azure" or not settings.AZURE_SPEECH_KEY or not settings.AZURE_SPEECH_REGION:
        return None
    return AzureSpeechSynthesizer(
        key=settings.AZURE_SPEECH_KEY, region=settings.AZURE_SPEECH_REGION,
        client=httpx.Client(timeout=15.0), rate=settings.COMPANION_TTS_RATE,
    )


class _DictionaryLookup:
    """Adapter: the content module's dictionary search (no translation call)."""

    def __init__(self, words):
        self.words = words

    def lookup(self, word: str, *, language_code: str) -> list[DictionaryWord]:
        return [DictionaryWord(
            headword=entry.headword,
            senses=tuple(DictionarySense(text=sense.text, part_of_speech=sense.part_of_speech, sense_id=sense.sense_id)
                         for sense in entry.senses),
            source_name=entry.source_name, source_license=entry.source_license, source_url=entry.source_url,
            entry_id=entry.entry_id,
        ) for entry in self.words.search(language_code=language_code, query=word)]


class _DueInLanguage:
    """Review items due now whose Concept is in the learning language (two reads)."""

    def __init__(self, states: ReviewStateRepository, concepts: ConceptRepository):
        self.states = states
        self.concepts = concepts

    def ready_count(self, user, *, language_code: str) -> int:
        # Filtered by language in the query: due cards of another language must not fill the limit.
        rows = self.states.list_due_for_user(user_id=user.id, due_at=datetime.now(UTC), limit=50,
                                             language_code=language_code)
        ids = list(dict.fromkeys(row.concept_id for row in rows))
        if not ids:
            return 0
        in_language = {concept.id for concept in self.concepts.list_by_ids(ids) if concept.language_code == language_code}
        return sum(1 for row in rows if row.concept_id in in_language)


class _StudyRegions:
    """M1 S3: read-only adapter over the learner's saved study region (content data).

    Rechecks Library ownership, resolves the current original transcript and returns the region's
    lines only when the stored range still matches it, like the workspace view does.
    """

    def __init__(self, *, workspaces, library, videos, transcripts, segments):
        self.workspaces = workspaces
        self.library = library
        self.videos = videos
        self.transcripts = transcripts
        self.segments = segments

    def for_learner(self, user_id: UUID, library_item_id: UUID) -> StudyRegionContext | None:
        association = self.library.get_for_user(library_item_id=library_item_id, user_id=user_id)
        state = self.workspaces.get_for_user(library_item_id=library_item_id, user_id=user_id) if association else None
        if state is None or state.region_transcript_id is None or state.region_start_segment_id is None                 or state.region_end_segment_id is None:
            return None
        video = self.videos.get_by_id(association.video_id)
        track = next((row for row in self.transcripts.list_for_video(video.id)
                      if row.is_original and row.language_code == video.original_language_code), None) if video else None
        if track is None or track.id != state.region_transcript_id:
            return None
        rows = sorted(self.segments.list_for_transcript(track.id), key=lambda row: row.sequence_number)
        index = {row.id: position for position, row in enumerate(rows)}
        first, last = index.get(state.region_start_segment_id), index.get(state.region_end_segment_id)
        if first is None or last is None or last < first or last - first + 1 > MAX_REGION_SEGMENTS:
            return None
        lines = tuple(RegionLine(ref=f"s{number}", segment_id=str(row.id), start_ms=row.start_ms,
                                 end_ms=row.end_ms, text=row.text)
                      for number, row in enumerate(rows[first:last + 1], start=1))
        return StudyRegionContext(
            lines=lines, before=rows[first - 1].text if first > 0 else None,
            after=rows[last + 1].text if last + 1 < len(rows) else None,
        )


class _DueConcepts:
    """Read-only adapter over review data for the companion's review entry point."""

    def __init__(self, states: ReviewStateRepository):
        self.states = states

    def due_concept_ids(self, user_id: UUID, *, language_code: str, limit: int) -> list[str]:
        rows = self.states.list_due_for_user(user_id=user_id, due_at=datetime.now(UTC), limit=limit,
                                             language_code=language_code)
        return list(dict.fromkeys(str(row.concept_id) for row in rows))


class _VideoTopics:
    """The title of the newest Library video in which each word occurs: a temporary topic for due words that
    are in no notebook (read-only, best effort)."""

    MAX_VIDEOS = 50

    def __init__(self, library, videos, objects):
        self.library, self.videos, self.objects = library, videos, objects

    def titles_for(self, user_id, concept_ids):
        wanted = [UUID(value) for value in concept_ids]
        associations = self.library.list_for_user(user_id, limit=self.MAX_VIDEOS)  # newest first
        video_ids = list(dict.fromkeys(item.video_id for item in associations))
        if not video_ids or not wanted:
            return {}
        titles = {video_id: video.title for video_id, video in self.videos.get_many_by_ids(video_ids).items()
                  if (video.title or "").strip()}
        rank = {video_id: index for index, video_id in enumerate(video_ids)}
        found: dict[str, tuple[int, str]] = {}
        for occurrence in self.objects.list_for_videos_concepts(video_ids, wanted):
            title = titles.get(occurrence.video_id)
            if title is None:
                continue
            key, order = str(occurrence.concept_id), rank[occurrence.video_id]
            if key not in found or order < found[key][0]:
                found[key] = (order, title)
        return {key: title for key, (_, title) in found.items()}


def get_companion_service() -> TextChannel:
    from app.bootstrap.wiring.learner import get_agent_signals_service
    from app.bootstrap.wiring.session_events import get_session_events_service
    from app.modules.learning.application.selected_targets import SelectedTargetCatalog
    from app.modules.content.application.library_occurrences import LibraryOccurrenceService
    from app.modules.content.infrastructure.repositories.saved_concepts import SavedConceptRepository
    from app.modules.content.infrastructure.repositories.sense_translations import SenseTranslationRepository
    from app.modules.learner.infrastructure.word_groups import WordGroupItemRepository, WordGroupRepository
    from app.modules.learning.application.focus_words import FocusWordChooser
    client = _require_database()
    audio_model = _language_model(settings.SPEAKING_TRANSCRIPTION_MODEL)
    target_catalog = SelectedTargetCatalog(
        targets=SavedConceptRepository(client),
        concepts=ConceptRepository(client), meanings=SenseTranslationRepository(client),
        occurrences=LibraryOccurrenceService(
            library=LearnerVideoRepository(client), videos=VideoRepository(client),
            transcripts=VideoTranscriptRepository(client), objects=LearningObjectRepository(client),
            segments=TranscriptSegmentRepository(client),
        ),
    )
    from app.bootstrap.wiring.agent import (
        agent_channels, get_agent_memory, get_context_builder, get_learner_facts,
        lazy_plan_editor, lazy_text_turn_tracing, lazy_video_regions,
    )
    return TextChannel(
        consent=get_agent_signals_service(), session_events=get_session_events_service(),
        pronunciation=_pronunciation_assessor(),
        preferences=UserLanguagePreferenceRepository(client),
        target_catalog=target_catalog,
        focus=FocusWordChooser(
            due=_DueConcepts(ReviewStateRepository(client)), groups=WordGroupRepository(client),
            group_items=WordGroupItemRepository(client), targets=SavedConceptRepository(client),
            catalog=target_catalog,
            video_topics=_VideoTopics(LearnerVideoRepository(client), VideoRepository(client),
                                      LearningObjectRepository(client)),
        ),
        catalog=LearnedItemCatalog(
            library=LearnerVideoRepository(client),
            videos=VideoRepository(client),
            learning_objects=LearningObjectRepository(client),
            concepts=ConceptRepository(client),
        ),
        library=LearnerVideoRepository(client),
        videos=VideoRepository(client),
        transcripts=VideoTranscriptRepository(client),
        segments=TranscriptSegmentRepository(client),
        due=_DueConcepts(ReviewStateRepository(client)),
        model=_language_model(settings.COMPANION_MODEL or settings.SPEAKING_COACH_MODEL),
        transcriber=SpeechTranscriber(audio_model) if audio_model is not None else None,
        synthesizer=_speech_synthesizer(),
        tickets=_companion_ticket_codec(), sessions=companion_sessions(),
        word_lookup=_DictionaryLookup(get_word_concept_service()),
        facts=get_learner_facts(), memory=get_agent_memory(), context_builder=get_context_builder(), enabled="text" in agent_channels(),
        plan=lazy_plan_editor(), video_regions=lazy_video_regions(), tracing=lazy_text_turn_tracing(),
        follow_ups=ConversationFollowUpService(
            preferences=UserLanguagePreferenceRepository(client), library=LearnerVideoRepository(client),
            videos=VideoRepository(client),
            reviews=_DueInLanguage(ReviewStateRepository(client), ConceptRepository(client)),
            store=StudyPlanRepository(client),
        ),
        regions=_study_regions(client),
        learning_log=build_activity_service(client),
    )
