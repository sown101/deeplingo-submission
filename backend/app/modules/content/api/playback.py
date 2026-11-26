import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from app.modules.identity.api.dependencies import require_authenticated_user
from app.modules.identity.contracts import CurrentUser
from app.modules.content.application.concept_interaction_views import ConceptInteractionView
from app.modules.content.application.playback_views import PlayableVideo, VideoTranscriptView
from app.modules.content.application.concept_interaction import (
    ConceptInteractionError,
    ConceptInteractionService,
)
from app.modules.content.application.library import LearnerLibraryError
from app.modules.content.application.playback import VideoPlaybackService
from app.modules.content.application.transcript_grammar import (
    TranscriptGrammarRequest, TranscriptGrammarService, TranscriptGrammarView,
)
from app.modules.content.application.transcript_parts import TranscriptPartsService, TranscriptPartsView
from app.modules.content.application.segment_translation import SegmentTranslationService, SegmentTranslationsView
from app.modules.content.application.example_sentences import ExampleSentenceService, ExampleSentencesView
from app.modules.content.application.word_concepts import (
    DictionarySearchEntryView,
    WordConceptService,
)
from app.modules.content.application.word_lookup import WordLookupRequest, WordLookupService, WordLookupView
from app.modules.content.application.workspace import (
    StudyRegionRequest,
    VideoWorkspaceService,
    VideoWorkspaceView,
    WatchPositionRequest,
)
from app.modules.content.application.word_reference import (
    MAX_IMAGES_PER_REQUEST,
    ConceptImageView,
    WordDetailsView,
    WordReferenceError,
    WordReferenceService,
    WordSetDetailView,
    WordSetView,
)
from pydantic import BaseModel, ConfigDict, Field

from app.platform.rate_limit import SlidingWindowLimiter
from app.bootstrap.wiring.content import (
    get_transcript_grammar_service,
    get_transcript_parts_service,
    get_segment_translation_service,
    get_concept_interaction_service,
    get_example_sentence_service,
    get_video_playback_service,
    get_video_workspace_limiter,
    get_video_workspace_service,
    get_word_concept_service,
    get_word_reference_service,
    get_word_lookup_limiter,
    get_word_lookup_service,
)

router = APIRouter()
logger = logging.getLogger(__name__)


def _safe_call(operation, user, item_id):
    try:
        return operation(user, item_id)
    except LearnerLibraryError as exc:
        raise HTTPException(exc.status_code, {"code": exc.code, "message": str(exc)}) from exc
    except Exception as exc:
        logger.exception("Video read failed")
        raise HTTPException(503, {"code": "video_service_unavailable", "message": "Video service is temporarily unavailable."}) from exc


@router.get("/learner/me/library/videos/{library_item_id}/playback", response_model=PlayableVideo)
def get_playable_video(library_item_id: UUID, user: CurrentUser = Depends(require_authenticated_user),
                       service: VideoPlaybackService = Depends(get_video_playback_service)):
    return _safe_call(service.playable, user, library_item_id)


@router.get("/learner/me/library/videos/{library_item_id}/transcript", response_model=VideoTranscriptView)
def get_video_transcript(library_item_id: UUID, user: CurrentUser = Depends(require_authenticated_user),
                         service: VideoPlaybackService = Depends(get_video_playback_service)):
    return _safe_call(service.transcript, user, library_item_id)


@router.post("/learner/me/library/videos/{library_item_id}/grammar-explanations", response_model=TranscriptGrammarView)
def explain_transcript_grammar(
    library_item_id: UUID,
    request: TranscriptGrammarRequest,
    user: CurrentUser = Depends(require_authenticated_user),
    service: TranscriptGrammarService = Depends(get_transcript_grammar_service),
    limiter: SlidingWindowLimiter = Depends(get_word_lookup_limiter),
):
    """An explicit grammar request, sharing the lookup rate budget; no learner-state recorder."""
    if not limiter.allow(str(user.id), "lookup"):
        raise HTTPException(429, {"code": "grammar_rate_limited", "message": "Please wait before requesting again."})
    try:
        return service.explain(user, library_item_id, request)
    except LearnerLibraryError as exc:
        raise HTTPException(exc.status_code, {"code": exc.code, "message": str(exc)}) from exc
    except Exception as exc:
        logger.warning("grammar_explanation_unavailable error=%s", type(exc).__name__)
        raise HTTPException(503, {"code": "grammar_explanation_unavailable",
                                  "message": "Grammar explanation is temporarily unavailable."}) from None


@router.post("/learner/me/library/videos/{library_item_id}/translations", response_model=SegmentTranslationsView)
def translate_transcript(
    library_item_id: UUID,
    user: CurrentUser = Depends(require_authenticated_user),
    service: SegmentTranslationService = Depends(get_segment_translation_service),
    limiter: SlidingWindowLimiter = Depends(get_word_lookup_limiter),
):
    """Translates the video's sentences into the learner's support language once; shared by language pair."""
    if not limiter.allow(str(user.id), "lookup"):
        raise HTTPException(429, {"code": "translation_rate_limited", "message": "Please wait before requesting again."})
    try:
        return service.ensure(user, library_item_id)
    except LearnerLibraryError as exc:
        raise HTTPException(exc.status_code, {"code": exc.code, "message": str(exc)}) from exc
    except Exception as exc:
        logger.warning("translation_unavailable error=%s", type(exc).__name__)
        raise HTTPException(503, {"code": "translation_unavailable",
                                  "message": "Translations are temporarily unavailable."}) from None


@router.get("/learner/me/library/videos/{library_item_id}/parts", response_model=TranscriptPartsView)
def get_transcript_parts(
    library_item_id: UUID,
    user: CurrentUser = Depends(require_authenticated_user),
    service: TranscriptPartsService = Depends(get_transcript_parts_service),
    limiter: SlidingWindowLimiter = Depends(get_word_lookup_limiter),
):
    """Study parts of an owned video, cut by AI once per transcript and shared (2026-11-05)."""
    if not limiter.allow(str(user.id), "lookup"):
        raise HTTPException(429, {"code": "parts_rate_limited", "message": "Please wait before requesting again."})
    try:
        return service.parts(user, library_item_id)
    except LearnerLibraryError as exc:
        raise HTTPException(exc.status_code, {"code": exc.code, "message": str(exc)}) from exc
    except Exception as exc:
        logger.warning("parts_unavailable error=%s", type(exc).__name__)
        raise HTTPException(503, {"code": "parts_unavailable",
                                  "message": "Study parts are temporarily unavailable."}) from None


@router.get("/learner/me/library/videos/{library_item_id}/workspace", response_model=VideoWorkspaceView)
def get_video_workspace(library_item_id: UUID, user: CurrentUser = Depends(require_authenticated_user),
                        service: VideoWorkspaceService = Depends(get_video_workspace_service)):
    """M1 S1: saved watch position and study region of an owned Library item."""
    return _safe_call(service.get, user, library_item_id)


@router.put("/learner/me/library/videos/{library_item_id}/workspace/position", response_model=VideoWorkspaceView)
def save_watch_position(library_item_id: UUID, request: WatchPositionRequest,
                        user: CurrentUser = Depends(require_authenticated_user),
                        service: VideoWorkspaceService = Depends(get_video_workspace_service),
                        limiter: SlidingWindowLimiter = Depends(get_video_workspace_limiter)):
    """Where to resume; the server bounds it to the video. Not Evidence or completion."""
    if not limiter.allow(str(user.id), "position"):
        raise HTTPException(429, {"code": "workspace_rate_limited",
                                  "message": "Too many saves. Please wait a moment."})
    return _safe_call(lambda u, i: service.save_position(u, i, request), user, library_item_id)


@router.put("/learner/me/library/videos/{library_item_id}/workspace/region", response_model=VideoWorkspaceView)
def save_study_region(library_item_id: UUID, request: StudyRegionRequest,
                      user: CurrentUser = Depends(require_authenticated_user),
                      service: VideoWorkspaceService = Depends(get_video_workspace_service),
                      limiter: SlidingWindowLimiter = Depends(get_video_workspace_limiter)):
    """The study region: a segment range of the current transcript of an owned video."""
    if not limiter.allow(str(user.id), "region"):
        raise HTTPException(429, {"code": "workspace_rate_limited",
                                  "message": "Too many saves. Please wait a moment."})
    return _safe_call(lambda u, i: service.save_region(u, i, request), user, library_item_id)


@router.get(
    "/learner/me/library/videos/{library_item_id}/learning-objects/{learning_object_id}/concept",
    response_model=ConceptInteractionView,
)
def get_concept_for_occurrence(
    library_item_id: UUID,
    learning_object_id: UUID,
    user: CurrentUser = Depends(require_authenticated_user),
    service: ConceptInteractionService = Depends(get_concept_interaction_service),
):
    try:
        return service.get(user, library_item_id, learning_object_id)
    except ConceptInteractionError as exc:
        raise HTTPException(exc.status_code, {"code": exc.code, "message": str(exc)}) from exc
    except Exception as exc:
        logger.exception("Concept interaction read failed")
        raise HTTPException(503, {"code": "concept_service_unavailable",
                                  "message": "Concept is temporarily unavailable."}) from exc


@router.post("/learner/me/library/videos/{library_item_id}/lookup", response_model=WordLookupView)
def lookup_word(
    library_item_id: UUID,
    request: WordLookupRequest,
    user: CurrentUser = Depends(require_authenticated_user),
    service: WordLookupService = Depends(get_word_lookup_service),
    limiter: SlidingWindowLimiter = Depends(get_word_lookup_limiter),
):
    """Meaning of any word or phrase the learner selects in the transcript."""
    if not limiter.allow(str(user.id), "lookup"):
        raise HTTPException(429, {"code": "lookup_rate_limited",
                                  "message": "Too many lookups. Please wait a moment."})
    try:
        return service.lookup(user, library_item_id, request)
    except LearnerLibraryError as exc:
        raise HTTPException(exc.status_code, {"code": exc.code, "message": str(exc)}) from exc
    except Exception as exc:
        logger.exception("Word lookup failed")
        raise HTTPException(503, {"code": "lookup_unavailable",
                                  "message": "Lookup is temporarily unavailable."}) from exc


@router.get("/learner/me/dictionary/search", response_model=list[DictionarySearchEntryView])
def search_dictionary(
    language_code: str = Query(min_length=2, max_length=16),
    q: str = Query(min_length=1, max_length=80),
    user: CurrentUser = Depends(require_authenticated_user),
    service: WordConceptService = Depends(get_word_concept_service),
    limiter: SlidingWindowLimiter = Depends(get_word_lookup_limiter),
):
    """Dictionary senses for adding a word by hand. Read-only reference data."""
    if not limiter.allow(str(user.id), "lookup"):
        raise HTTPException(429, {"code": "lookup_rate_limited",
                                  "message": "Too many lookups. Please wait a moment."})
    return service.search(language_code=language_code.strip().casefold(), query=q, user=user)


def _example_call(operation, user, concept_id, **kwargs):
    try:
        return operation(user, concept_id, **kwargs)
    except LearnerLibraryError as exc:
        raise HTTPException(exc.status_code, {"code": exc.code, "message": str(exc)}) from exc
    except Exception as exc:
        logger.exception("Example sentences failed")
        raise HTTPException(503, {"code": "example_unavailable",
                                  "message": "Examples are temporarily unavailable."}) from exc


class WordImagesRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    concept_ids: list[UUID] = Field(min_length=1, max_length=MAX_IMAGES_PER_REQUEST)
    refresh: UUID | None = None


def _reference_call(operation, *args, **kwargs):
    try:
        return operation(*args, **kwargs)
    except WordReferenceError as exc:
        raise HTTPException(exc.status_code, {"code": exc.code, "message": str(exc)}) from exc


@router.get("/learner/me/word-sets", response_model=list[WordSetView])
def list_word_sets(
    user: CurrentUser = Depends(require_authenticated_user),
    service: WordReferenceService = Depends(get_word_reference_service),
):
    """Ready-made sets by level, read from the dictionary. Nothing is saved by opening one."""
    return service.sets()


@router.get("/learner/me/word-sets/{key}", response_model=WordSetDetailView)
def read_word_set(
    key: str,
    offset: int = Query(default=0, ge=0),
    user: CurrentUser = Depends(require_authenticated_user),
    service: WordReferenceService = Depends(get_word_reference_service),
):
    return _reference_call(service.set_detail, key, offset=offset)


@router.get("/learner/me/words/{concept_id}/details", response_model=WordDetailsView)
def read_word_details(
    concept_id: UUID,
    user: CurrentUser = Depends(require_authenticated_user),
    service: WordReferenceService = Depends(get_word_reference_service),
):
    return _reference_call(service.details, concept_id)


@router.post("/learner/me/words/images", response_model=list[ConceptImageView])
def read_word_images(
    request: WordImagesRequest,
    user: CurrentUser = Depends(require_authenticated_user),
    service: WordReferenceService = Depends(get_word_reference_service),
):
    """A picture for each word; `refresh` asks for a different one for that word."""
    return service.images_for(request.concept_ids, refresh=request.refresh)


@router.get("/learner/me/words/{concept_id}/examples", response_model=ExampleSentencesView)
def list_word_examples(
    concept_id: UUID,
    read_only: bool = False,
    user: CurrentUser = Depends(require_authenticated_user),
    service: ExampleSentenceService = Depends(get_example_sentence_service),
):
    """Examples already stored for one of the learner's saved words."""
    return _example_call(service.list, user, concept_id, **({"read_only": True} if read_only else {}))


@router.post("/learner/me/words/{concept_id}/examples", response_model=ExampleSentencesView)
def write_word_examples(
    concept_id: UUID,
    user: CurrentUser = Depends(require_authenticated_user),
    service: ExampleSentenceService = Depends(get_example_sentence_service),
    limiter: SlidingWindowLimiter = Depends(get_word_lookup_limiter),
):
    """Writes an example for a saved word that has none. The learner sends no content."""
    if not limiter.allow(str(user.id), "example"):
        raise HTTPException(429, {"code": "example_rate_limited",
                                  "message": "Too many examples requested. Please wait a moment."})
    return _example_call(service.generate, user, concept_id)
