"""Content module object graph, worker factories and FastAPI dependency providers."""
from functools import lru_cache

from app.modules.content.application.language_catalog import LanguageCatalogService
from app.platform.supabase import supabase, supabase_service
from app.modules.content.infrastructure.repositories.languages import LanguageRepository
from fastapi import HTTPException, status
from app.modules.content.application.ingestion import ContentIngestionService
from app.modules.content.infrastructure.repositories.transcript_segments import (
    TranscriptSegmentRepository,
)
from app.modules.content.infrastructure.repositories.video_transcripts import (
    VideoTranscriptRepository,
)
from app.modules.content.application.candidate_extraction import (
    CandidateExtractionService,
    V3CandidateExtractionService,
)
from app.modules.content.application.grammar_selection import GrammarSelectionService
from app.modules.content.application.word_lookup import WordLookupService
from app.platform.rate_limit import SlidingWindowLimiter
from app.bootstrap.wiring.clients import request_limiter
from app.platform.llm.openai_compatible import OpenAICompatibleLLMProvider
from app.modules.content.application.knowledge_resolution import (
    CandidateResolutionService,
    V3CandidateResolutionService,
)
from app.modules.content.infrastructure.repositories.concept_dictionary_links import (
    ConceptDictionaryLinkRepository,
)
from app.modules.content.infrastructure.repositories.concepts import ConceptRepository
from app.modules.content.infrastructure.repositories.curriculum import GrammarPointRepository
from app.modules.content.infrastructure.repositories.dictionary_entries import (
    DictionaryEntryRepository,
)
from app.modules.content.infrastructure.repositories.learning_objects import (
    LearningObjectRepository,
)
from app.modules.content.application.enrichment import LearningObjectEnrichmentService
from app.modules.content.infrastructure.repositories.segment_translations import (
    SegmentTranslationRepository,
)
from app.modules.content.infrastructure.llm_enrichment import (
    OpenAICompatibleLearningObjectEnrichmentProvider,
)
from app.modules.content.application.library import LearnerLibraryService
from app.modules.content.infrastructure.repositories.learner_videos import LearnerVideoRepository
from app.modules.content.infrastructure.repositories.video_work_intents import (
    VideoWorkIntentRepository,
)
from app.modules.content.worker.dispatch import ContentWorkDispatcher
from app.modules.content.infrastructure.repositories.new_video_import_budget import NewVideoImportBudgetRepository
from app.modules.content.application.concept_interaction import ConceptInteractionService
from app.modules.content.application.playback import VideoPlaybackService
from app.modules.content.infrastructure.repositories.playback_transcripts import (
    PlaybackTranscriptRepository,
)
from app.modules.learner.infrastructure.user_language_preferences import (
    UserLanguagePreferenceRepository,
)
from app.modules.content.infrastructure.repositories.videos import VideoRepository
from app.modules.content.infrastructure.repositories.channels import ChannelRepository
from app.modules.content.infrastructure.repositories.romanization_systems import (
    RomanizationSystemRepository,
)
from app.modules.content.infrastructure.repositories.segment_romanizations import (
    SegmentRomanizationRepository,
)
from app.modules.content.domain.normalizer import TranscriptNormalizer
from app.modules.content.infrastructure.sources import (
    LocalRomanizationProvider,
    YouTubeContentProvider,
)
from app.platform.config import settings
from app.modules.content.application.preparation import LearningContentPreparationService


def get_language_catalog_service() -> LanguageCatalogService:
    return LanguageCatalogService(languages=LanguageRepository(supabase))


def get_learner_library_service() -> LearnerLibraryService:
    if not supabase_service:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Server-side content service is not configured",
        )
    ingestion = build_content_ingestion_service(supabase_service)
    intents = VideoWorkIntentRepository(supabase_service)
    return LearnerLibraryService(
        library=LearnerVideoRepository(supabase_service),
        videos=ingestion.videos,
        transcripts=ingestion.transcripts,
        ingestion=ingestion,
        work_intents=intents,
        dispatcher=ContentWorkDispatcher(intents),
        import_budget=NewVideoImportBudgetRepository(
            supabase_service, limit=settings.NEW_VIDEO_IMPORT_LIMIT,
            window_seconds=settings.NEW_VIDEO_IMPORT_WINDOW_HOURS * 3600),
    )


def get_transcript_grammar_service():
    from app.modules.content.application.transcript_grammar import TranscriptGrammarService
    from app.modules.content.infrastructure.repositories.transcript_grammar import TranscriptGrammarCache
    if not supabase_service:
        raise HTTPException(503, "Grammar service is temporarily unavailable.")
    return TranscriptGrammarService(
        library=LearnerVideoRepository(supabase_service), videos=VideoRepository(supabase_service),
        transcripts=VideoTranscriptRepository(supabase_service), aggregate=PlaybackTranscriptRepository(supabase_service),
        preferences=UserLanguagePreferenceRepository(supabase_service),
        romanization_provider=LocalRomanizationProvider(),
        romanization_systems=RomanizationSystemRepository(supabase_service),
        grammar_points=GrammarPointRepository(supabase_service), cache=TranscriptGrammarCache(supabase_service),
        provider=OpenAICompatibleLLMProvider(),
    )


def get_transcript_parts_service():
    from app.modules.content.application.transcript_parts import TranscriptPartsService
    from app.modules.content.infrastructure.repositories.transcript_parts import TranscriptPartsCache
    if not supabase_service:
        raise HTTPException(503, "Video service is temporarily unavailable.")
    return TranscriptPartsService(
        library=LearnerVideoRepository(supabase_service), videos=VideoRepository(supabase_service),
        transcripts=VideoTranscriptRepository(supabase_service), segments=TranscriptSegmentRepository(supabase_service),
        preferences=UserLanguagePreferenceRepository(supabase_service), cache=TranscriptPartsCache(supabase_service),
        provider=OpenAICompatibleLLMProvider(),
    )


def get_segment_translation_service():
    from app.modules.content.application.segment_translation import SegmentTranslationService
    if not supabase_service:
        raise HTTPException(503, "Video service is temporarily unavailable.")
    return SegmentTranslationService(
        library=LearnerVideoRepository(supabase_service), videos=VideoRepository(supabase_service),
        transcripts=VideoTranscriptRepository(supabase_service), segments=TranscriptSegmentRepository(supabase_service),
        preferences=UserLanguagePreferenceRepository(supabase_service),
        translations=SegmentTranslationRepository(supabase_service), provider=OpenAICompatibleLLMProvider(),
    )


def get_video_playback_service():
    if not supabase_service:
        raise HTTPException(503, "Video service is temporarily unavailable.")
    return VideoPlaybackService(
        library=LearnerVideoRepository(supabase_service), videos=VideoRepository(supabase_service),
        transcripts=VideoTranscriptRepository(supabase_service), aggregate=PlaybackTranscriptRepository(supabase_service),
        preferences=UserLanguagePreferenceRepository(supabase_service),
    )


def get_video_workspace_service():
    """M1 S1: watch position and study region per Library item; S2: region preparation; S6: questions."""
    from app.modules.content.application.region_preparation import REGION_PREPARATION_VERSION
    from app.modules.content.application.workspace import RegionPreparationPolicy, VideoWorkspaceService
    from app.modules.content.infrastructure.repositories.learner_video_workspaces import (
        LearnerVideoWorkspaceRepository,
    )
    from app.modules.content.infrastructure.repositories.region_questions import RegionQuestionRepository
    from app.modules.content.infrastructure.repositories.video_region_preparations import (
        VideoRegionPreparationRepository,
    )
    if not supabase_service:
        raise HTTPException(503, "Video service is temporarily unavailable.")
    intents = VideoWorkIntentRepository(supabase_service)
    return VideoWorkspaceService(
        library=LearnerVideoRepository(supabase_service), videos=VideoRepository(supabase_service),
        transcripts=VideoTranscriptRepository(supabase_service),
        segments=TranscriptSegmentRepository(supabase_service),
        workspaces=LearnerVideoWorkspaceRepository(supabase_service),
        regions=VideoRegionPreparationRepository(supabase_service),
        dispatcher=ContentWorkDispatcher(intents),
        preparation_policy=RegionPreparationPolicy(
            support_language_code=settings.AI_PREPARATION_SUPPORT_LANGUAGE.strip().casefold(),
            preparation_version=REGION_PREPARATION_VERSION,
            limit=settings.REGION_PREPARATION_LIMIT,
            window_seconds=settings.REGION_PREPARATION_WINDOW_HOURS * 3600,
        ),
        questions=RegionQuestionRepository(supabase_service),
    )


# The player saves its position every few seconds while playing; bound runaway client loops.
VIDEO_WORKSPACE_LIMITS = {"position": (720, 3600.0), "region": (120, 3600.0)}


@lru_cache(maxsize=1)
def get_video_workspace_limiter() -> SlidingWindowLimiter:
    return request_limiter(VIDEO_WORKSPACE_LIMITS)


# Importing a video fetches YouTube metadata even when it is refused later; bound the request rate.
LIBRARY_IMPORT_LIMITS = {"import": (30, 3600.0)}


@lru_cache(maxsize=1)
def get_library_import_limiter() -> SlidingWindowLimiter:
    return request_limiter(LIBRARY_IMPORT_LIMITS)


# Lookups call the model once each; generous for reading, bounded against loops.
WORD_LOOKUP_LIMITS = {"lookup": (120, 3600.0), "example": (20, 3600.0)}


@lru_cache(maxsize=1)
def get_word_lookup_limiter() -> SlidingWindowLimiter:
    return request_limiter(WORD_LOOKUP_LIMITS)


def get_library_lexical_profiles():
    """L1c: the word profile of a learner's own Library video (built once, then cached)."""
    from app.modules.content.application.lexical_profile import LexicalProfileService, LibraryLexicalProfiles
    from app.modules.content.infrastructure.repositories.dictionary_entries import DictionaryEntryRepository
    from app.modules.content.infrastructure.repositories.lexical_profiles import (
        LexicalProfileRepository,
        SegmentTextRepository,
    )
    if not supabase_service:
        raise HTTPException(503, "Video coverage is temporarily unavailable.")
    profiles = LexicalProfileService(
        store=LexicalProfileRepository(supabase_service), segments=SegmentTextRepository(supabase_service),
        dictionary=DictionaryEntryRepository(supabase_service))
    return LibraryLexicalProfiles(
        library=LearnerVideoRepository(supabase_service), videos=VideoRepository(supabase_service),
        transcripts=VideoTranscriptRepository(supabase_service), profiles=profiles)


def get_word_lookup_service():
    if not supabase_service:
        raise HTTPException(503, "Lookup is temporarily unavailable.")
    return WordLookupService(
        library=LearnerVideoRepository(supabase_service), videos=VideoRepository(supabase_service),
        transcripts=VideoTranscriptRepository(supabase_service), segments=TranscriptSegmentRepository(supabase_service),
        preferences=UserLanguagePreferenceRepository(supabase_service),
        dictionary=DictionaryEntryRepository(supabase_service), provider=OpenAICompatibleLLMProvider(),
        translations=_sense_translations(),
    )


def _sense_translations():
    from app.modules.content.infrastructure.repositories.sense_translations import SenseTranslationRepository
    return SenseTranslationRepository(supabase_service)


def get_word_concept_service():
    """Concepts for saved words, from a trusted lookup, a dictionary sense or an occurrence."""
    from app.modules.content.application.word_concepts import WordConceptService
    from app.modules.content.infrastructure.repositories.concept_dictionary_links import (
        ConceptDictionaryLinkRepository,
    )
    if not supabase_service:
        raise HTTPException(503, "Words are temporarily unavailable.")
    return WordConceptService(
        lookup=get_word_lookup_service(), learning_objects=LearningObjectRepository(supabase_service),
        concepts=ConceptRepository(supabase_service), dictionary=DictionaryEntryRepository(supabase_service),
        links=ConceptDictionaryLinkRepository(supabase_service),
    )


@lru_cache(maxsize=1)
def _openverse_http_client():
    """One client (one connection pool) for the whole process; the image search itself is cheap to rebuild."""
    import httpx
    return httpx.Client(timeout=8.0)


def get_word_reference_service():
    """Ready-made word sets, a word's dictionary details and its picture."""
    from app.modules.content.application.word_reference import WordReferenceService
    from app.modules.content.infrastructure.openverse import OpenverseImageSearch
    from app.modules.content.infrastructure.repositories.concept_images import ConceptImageRepository
    from app.modules.content.infrastructure.repositories.concepts import ConceptRepository
    from app.modules.content.infrastructure.repositories.dictionary_entries import DictionaryEntryRepository
    client = supabase_service
    return WordReferenceService(dictionary=DictionaryEntryRepository(client), concepts=ConceptRepository(client),
                                images=ConceptImageRepository(client),
                                image_search=OpenverseImageSearch(_openverse_http_client()))


def get_example_sentence_service():
    """Dictionary and AI-written examples for a learner's saved word."""
    from app.modules.content.application.example_sentences import ExampleSentenceService
    from app.modules.content.infrastructure.repositories.corpus_sentences import CorpusSentenceRepository
    from app.modules.content.infrastructure.repositories.example_sentences import ExampleSentenceRepository
    from app.modules.content.infrastructure.repositories.saved_concepts import SavedConceptRepository
    if not supabase_service:
        raise HTTPException(503, "Examples are temporarily unavailable.")
    return ExampleSentenceService(
        saved=SavedConceptRepository(supabase_service), concepts=ConceptRepository(supabase_service),
        dictionary=DictionaryEntryRepository(supabase_service),
        examples=ExampleSentenceRepository(supabase_service),
        preferences=UserLanguagePreferenceRepository(supabase_service), provider=OpenAICompatibleLLMProvider(),
        corpus=CorpusSentenceRepository(supabase_service),
    )


def get_concept_interaction_service():
    if not supabase_service:
        raise HTTPException(503, "Concept service is temporarily unavailable.")
    return ConceptInteractionService(
        library=LearnerVideoRepository(supabase_service),
        learning_objects=LearningObjectRepository(supabase_service),
        segments=TranscriptSegmentRepository(supabase_service),
        transcripts=VideoTranscriptRepository(supabase_service),
        concepts=ConceptRepository(supabase_service),
        preferences=UserLanguagePreferenceRepository(supabase_service),
    )


def build_content_ingestion_service(supabase_client, *, claim=None) -> ContentIngestionService:
    from app.modules.content.infrastructure.repositories.content_claims import (
        ClaimedTranscripts,
        ClaimedSegments,
        ClaimedRomanizations,
    )
    provider = _content_source_provider(LanguageRepository(supabase_client))
    return ContentIngestionService(
        video_provider=provider,
        transcript_provider=provider,
        romanization_provider=LocalRomanizationProvider(),
        normalizer=TranscriptNormalizer(),
        languages=LanguageRepository(supabase_client),
        channels=ChannelRepository(supabase_client),
        videos=VideoRepository(supabase_client),
        transcripts=ClaimedTranscripts(supabase_client, claim) if claim else VideoTranscriptRepository(supabase_client),
        segments=ClaimedSegments(supabase_client, claim) if claim else TranscriptSegmentRepository(supabase_client),
        translations=SegmentTranslationRepository(supabase_client),
        romanization_systems=RomanizationSystemRepository(supabase_client),
        romanizations=ClaimedRomanizations(supabase_client, claim) if claim else SegmentRomanizationRepository(supabase_client),
        work_intents=VideoWorkIntentRepository(supabase_client),
    )


def _content_source_provider(languages: LanguageRepository):
    """Select the one configured transcript source; there is no fallback."""
    if settings.CONTENT_TRANSCRIPT_SOURCE != "gemini_youtube":
        return YouTubeContentProvider()
    from app.modules.content.infrastructure.gemini_transcription import (
        GeminiYouTubeContentProvider,
        GeminiYouTubeTranscriber,
    )
    from app.modules.content.infrastructure.youtube_data_api import YouTubeDataApiClient
    return GeminiYouTubeContentProvider(
        data_api=YouTubeDataApiClient(settings.YOUTUBE_DATA_API_KEY),
        transcriber=GeminiYouTubeTranscriber(
            api_key=settings.GEMINI_API_KEY,
            model=settings.AI_TRANSCRIPTION_MODEL,
            catalog_languages=lambda: [language.code for language in languages.list_active()],
            timeout_seconds=settings.AI_TRANSCRIPTION_TIMEOUT_SECONDS,
            deadline_seconds=settings.AI_TRANSCRIPTION_DEADLINE_SECONDS,
            thinking_level=settings.AI_TRANSCRIPTION_THINKING_LEVEL or None,
        ),
        allowed_languages=settings.content_transcription_language_list,
        max_duration_seconds=settings.CONTENT_MAX_VIDEO_SECONDS,
    )


def _preparation_collaborators(supabase_client, claim):
    """Stores and AI services shared by Video and region preparation; claim-fenced when claimed."""
    from app.modules.content.infrastructure.repositories.content_claims import (
        ClaimedConcepts,
        ClaimedLearningObjects,
        ClaimedDictionaryEntries,
        ClaimedConceptLinks,
    )
    videos = VideoRepository(supabase_client)
    transcripts = VideoTranscriptRepository(supabase_client)
    segments = TranscriptSegmentRepository(supabase_client)
    learning_objects = ClaimedLearningObjects(supabase_client, claim) if claim else LearningObjectRepository(supabase_client)
    concepts = ClaimedConcepts(supabase_client, claim) if claim else ConceptRepository(supabase_client)
    entries = ClaimedDictionaryEntries(supabase_client) if claim else DictionaryEntryRepository(supabase_client)
    links = ClaimedConceptLinks(supabase_client, claim) if claim else ConceptDictionaryLinkRepository(supabase_client)
    extraction = V3CandidateExtractionService(
        segments=segments,
        transcripts=transcripts,
        extraction=CandidateExtractionService(
            provider=OpenAICompatibleLLMProvider(),
            max_candidates_per_segment=settings.AI_PREPARATION_MAX_CANDIDATES_PER_SEGMENT,
            max_retries=0 if claim else settings.AI_EXTRACTION_MAX_RETRIES,
            propagate_failures=claim is not None,
            grammar_selection=GrammarSelectionService(
                provider=OpenAICompatibleLLMProvider(), catalogue=GrammarPointRepository(supabase_client),
                max_retries=0 if claim else settings.AI_EXTRACTION_MAX_RETRIES,
                propagate_failures=claim is not None,
            ),
        ),
    )
    resolution = V3CandidateResolutionService(
        segments=segments,
        transcripts=transcripts,
        extraction=extraction,
        resolution=CandidateResolutionService(
            concepts=concepts,
            dictionary_entries=entries,
            concept_dictionary_links=links,
            learning_objects=learning_objects,
        ),
    )
    enrichment = LearningObjectEnrichmentService(
        learning_objects=learning_objects,
        concepts=concepts,
        segments=segments,
        transcripts=transcripts,
        translations=SegmentTranslationRepository(supabase_client),
        concept_dictionary_links=links,
        dictionary_entries=entries,
        provider=OpenAICompatibleLearningObjectEnrichmentProvider(),
    )
    return videos, transcripts, segments, learning_objects, resolution, enrichment


def build_learning_content_preparation_service(supabase_client, *, claim=None) -> LearningContentPreparationService:
    videos, transcripts, segments, learning_objects, resolution, enrichment = _preparation_collaborators(
        supabase_client, claim)
    return LearningContentPreparationService(
        videos=videos, transcripts=transcripts, segments=segments,
        learning_objects=learning_objects, resolution=resolution,
        enrichment=enrichment,
        support_language_code=settings.AI_PREPARATION_SUPPORT_LANGUAGE,
        max_segments=settings.AI_PREPARATION_MAX_SEGMENTS,
        propagate_failures=claim is not None,
    )


def build_region_preparation_service(supabase_client, *, claim):
    """M1 S2 worker path: always claim-fenced."""
    from app.modules.content.application.region_preparation import RegionPreparationService
    from app.modules.content.application.region_questions import RegionQuestionGenerationService
    from app.modules.content.infrastructure.llm_region_questions import OpenAICompatibleRegionQuestionProvider
    from app.modules.content.infrastructure.repositories.content_claims import ClaimedRegionQuestions
    from app.modules.content.infrastructure.repositories.video_region_preparations import (
        VideoRegionPreparationRepository,
    )
    if claim is None or claim.stage != "region_preparation":
        raise ValueError("Region preparation requires a region claim")
    videos, transcripts, segments, learning_objects, resolution, enrichment = _preparation_collaborators(
        supabase_client, claim)
    return RegionPreparationService(
        videos=videos, transcripts=transcripts, segments=segments, learning_objects=learning_objects,
        regions=VideoRegionPreparationRepository(supabase_client), resolution=resolution,
        enrichment=enrichment, propagate_failures=True,
        questions=RegionQuestionGenerationService(
            provider=OpenAICompatibleRegionQuestionProvider(),
            writer=ClaimedRegionQuestions(supabase_client, claim),
        ),
    )


def build_work_intents(supabase_client) -> VideoWorkIntentRepository:
    return VideoWorkIntentRepository(supabase_client)
