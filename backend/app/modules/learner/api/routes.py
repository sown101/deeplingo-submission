from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field
from app.platform.persistence import SelectTooLarge

from app.bootstrap.wiring.learner import (
    get_account_deletion_service,
    get_agent_signals_service,
    get_learner_data_export_service,
    get_learner_model_service,
    get_my_words_service,
    get_speech_transcripts_service,
    get_video_coverage_service,
    get_word_list_service,
)
from app.modules.identity.api.dependencies import (
    require_authenticated_user,
    require_self_scoped_user,
)
from app.modules.identity.contracts import CurrentUser
from app.modules.learner.application.account_deletion import AccountDeletionError, AccountDeletionService
from app.modules.learner.application.agent_signals import (
    AgentConsentView,
    AgentSignalsService,
    SignalsView,
)
from app.modules.learner.application.data_export import LearnerDataExportService
from app.modules.learner.application.speech_transcripts import (
    MAX_PAGE as MAX_TRANSCRIPT_PAGE,
    SpeechTranscriptService,
    TranscriptConsentView,
    TranscriptPageView,
)
from app.modules.learner.application.my_words import (
    MyWordsError,
    MyWordsService,
    MyWordsView,
    MyWordView,
    SaveWordRequest,
)
from app.modules.learner.application.video_coverage import (
    RecommendationView,
    VideoCoverageError,
    VideoCoverageService,
)
from app.modules.learner.application.word_lists import (
    ImportReport,
    ListDetailView,
    ListSummaryView,
    ListWordView,
    WordListError,
    WordListService,
)
from app.modules.learner.domain.word_targets import TargetStatus
from app.modules.learner.application.commands import (
    LearnerInitializationRequest,
    LearnerLanguageProfileUpdate,
)
from app.modules.learner.application.learner_model import LearnerModelError, LearnerModelService
from app.modules.learner.application.views import (
    LearnerInitializationResult,
    LearnerLanguageProfile,
)

router = APIRouter()


@router.get("/learner/me/language-profile", response_model=LearnerLanguageProfile)
def get_learner_language_profile(
    current_user: CurrentUser = Depends(require_self_scoped_user),
    service: LearnerModelService = Depends(get_learner_model_service),
) -> LearnerLanguageProfile:
    return service.get_language_profile(current_user)


@router.put("/learner/me/language-profile", response_model=LearnerLanguageProfile)
def update_learner_language_profile(
    request: LearnerLanguageProfileUpdate,
    current_user: CurrentUser = Depends(require_self_scoped_user),
    service: LearnerModelService = Depends(get_learner_model_service),
) -> LearnerLanguageProfile:
    try:
        return service.update_language_profile(current_user, request)
    except LearnerModelError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.post("/learner/me/initialize", response_model=LearnerInitializationResult)
def initialize_learner_model(
    request: LearnerInitializationRequest,
    current_user: CurrentUser = Depends(require_authenticated_user),
    service: LearnerModelService = Depends(get_learner_model_service),
) -> LearnerInitializationResult:
    try:
        return service.initialize(
            current_user,
            language_codes=request.language_codes,
            create_profile=request.create_profile,
        )
    except LearnerModelError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


# --- Agent: one revocable voice consent and personalization signals ---------

class AgentConsentUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    granted: bool


@router.get("/learner/me/agent/consent", response_model=AgentConsentView)
def read_agent_consent(
    current_user: CurrentUser = Depends(require_authenticated_user),
    service: AgentSignalsService = Depends(get_agent_signals_service),
) -> AgentConsentView:
    return service.consent(current_user.id)


@router.put("/learner/me/agent/consent", response_model=AgentConsentView)
def update_agent_consent(
    update: AgentConsentUpdate,
    current_user: CurrentUser = Depends(require_authenticated_user),
    service: AgentSignalsService = Depends(get_agent_signals_service),
) -> AgentConsentView:
    return service.set_consent(current_user.id, update.granted)


@router.get("/learner/me/agent/signals", response_model=SignalsView)
def read_agent_signals(
    current_user: CurrentUser = Depends(require_authenticated_user),
    service: AgentSignalsService = Depends(get_agent_signals_service),
) -> SignalsView:
    return service.signals(current_user.id)


@router.delete("/learner/me/agent/signals/{signal_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_agent_signal(
    signal_id: UUID,
    current_user: CurrentUser = Depends(require_authenticated_user),
    service: AgentSignalsService = Depends(get_agent_signals_service),
) -> None:
    if not service.delete_one(current_user.id, signal_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail={"code": "signal_not_found", "message": "Signal not found."})


@router.delete("/learner/me/agent/signals", status_code=status.HTTP_204_NO_CONTENT)
def delete_all_agent_signals(
    current_user: CurrentUser = Depends(require_authenticated_user),
    service: AgentSignalsService = Depends(get_agent_signals_service),
) -> None:
    service.delete_all(current_user.id)


# --- FR-3.11: separate consent to keep spoken turns as text, and the kept turns ---------

_NO_STORE = {"Cache-Control": "no-store"}


@router.get("/learner/me/agent/transcripts/consent", response_model=TranscriptConsentView)
def read_transcript_consent(
    response: Response,
    current_user: CurrentUser = Depends(require_authenticated_user),
    service: SpeechTranscriptService = Depends(get_speech_transcripts_service),
) -> TranscriptConsentView:
    response.headers.update(_NO_STORE)
    return service.consent(current_user.id)


@router.put("/learner/me/agent/transcripts/consent", response_model=TranscriptConsentView)
def update_transcript_consent(
    update: AgentConsentUpdate,
    response: Response,
    current_user: CurrentUser = Depends(require_authenticated_user),
    service: SpeechTranscriptService = Depends(get_speech_transcripts_service),
) -> TranscriptConsentView:
    response.headers.update(_NO_STORE)
    return service.set_consent(current_user.id, update.granted)


@router.get("/learner/me/agent/transcripts", response_model=TranscriptPageView)
def read_transcripts(
    response: Response,
    before: datetime | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=MAX_TRANSCRIPT_PAGE),
    current_user: CurrentUser = Depends(require_authenticated_user),
    service: SpeechTranscriptService = Depends(get_speech_transcripts_service),
) -> TranscriptPageView:
    response.headers.update(_NO_STORE)
    return service.page(current_user.id, before=before, limit=limit)


@router.delete("/learner/me/agent/transcripts/{transcript_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_transcript(
    transcript_id: UUID,
    current_user: CurrentUser = Depends(require_authenticated_user),
    service: SpeechTranscriptService = Depends(get_speech_transcripts_service),
) -> None:
    if not service.delete_one(current_user.id, transcript_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail={"code": "transcript_not_found", "message": "Transcript not found."})


@router.delete("/learner/me/agent/transcripts", status_code=status.HTTP_204_NO_CONTENT)
def delete_all_transcripts(
    current_user: CurrentUser = Depends(require_authenticated_user),
    service: SpeechTranscriptService = Depends(get_speech_transcripts_service),
) -> None:
    service.delete_all(current_user.id)


class AccountDeletionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirm: str


@router.post("/learner/me/account/delete", status_code=status.HTTP_204_NO_CONTENT)
def delete_my_account(
    request: AccountDeletionRequest,
    current_user: CurrentUser = Depends(require_authenticated_user),
    service: AccountDeletionService = Depends(get_account_deletion_service),
) -> Response:
    """Deletes the signed-in learner's own account and everything that belongs to it. The identity comes
    from the token only."""
    try:
        service.delete(current_user.id, request.confirm)
    except AccountDeletionError as exc:
        raise HTTPException(status_code=exc.status_code,
                            detail={"code": exc.code, "message": str(exc)}) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT, headers={"Cache-Control": "no-store"})


@router.get("/learner/me/export")
def export_learner_data(
    current_user: CurrentUser = Depends(require_authenticated_user),
    service: LearnerDataExportService = Depends(get_learner_data_export_service),
) -> JSONResponse:
    """Everything stored about the signed-in learner, as a downloadable JSON file."""
    try:
        document = service.export(current_user.id)
    except SelectTooLarge:
        raise HTTPException(413, {"code": "data_export_too_large", "message": "Your data export is too large."}) from None
    return JSONResponse(
        document,
        headers={"Content-Disposition": 'attachment; filename="deeplingo-my-data.json"',
                 "Cache-Control": "no-store"},
    )


def _words_call(operation, *args, **kwargs):
    try:
        return operation(*args, **kwargs)
    except MyWordsError as exc:
        raise HTTPException(exc.status_code, {"code": exc.code, "message": str(exc), **exc.extra}) from exc


@router.get("/learner/me/words", response_model=MyWordsView)
def list_my_words(
    language_code: str | None = Query(default=None, min_length=2, max_length=16),
    library_item_id: UUID | None = Query(default=None),
    recognition_only: bool = False,
    current_user: CurrentUser = Depends(require_authenticated_user),
    service: MyWordsService = Depends(get_my_words_service),
) -> MyWordsView:
    """The learner's saved words, optionally scoped to an owned Library video."""
    if recognition_only:
        return _words_call(service.list, current_user, language_code, library_item_id, recognition_only=True)
    if library_item_id is not None:
        return _words_call(service.list, current_user, language_code, library_item_id)
    return _words_call(service.list, current_user, language_code)


@router.post("/learner/me/words", response_model=MyWordView)
def save_my_word(
    request: SaveWordRequest,
    current_user: CurrentUser = Depends(require_authenticated_user),
    service: MyWordsService = Depends(get_my_words_service),
) -> MyWordView:
    """Saves a word the server resolves from a lookup, a dictionary sense or an occurrence.
    Saving never marks a word known and never changes mastery or review."""
    return _words_call(service.save, current_user, request)


class WordStatusUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: TargetStatus


@router.put("/learner/me/words/{concept_id}/status", response_model=MyWordView)
def set_my_word_status(
    concept_id: UUID,
    update: WordStatusUpdate,
    current_user: CurrentUser = Depends(require_authenticated_user),
    service: MyWordsService = Depends(get_my_words_service),
) -> MyWordView:
    """Pause or resume a word; legacy backlog requests mean active."""
    return _words_call(service.set_status, current_user, concept_id, update.status)


class WordPersonalUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    note: str | None = Field(default=None, max_length=1000)
    favorite: bool | None = None


@router.put("/learner/me/words/{concept_id}/personal", response_model=MyWordView)
def set_my_word_personal(
    concept_id: UUID,
    update: WordPersonalUpdate,
    current_user: CurrentUser = Depends(require_authenticated_user),
    service: MyWordsService = Depends(get_my_words_service),
) -> MyWordView:
    """Only the fields sent change. Sending null clears a note."""
    fields = update.model_dump(exclude_unset=True)
    if not fields or fields.get("favorite", True) is None:
        raise HTTPException(status_code=422, detail={"code": "nothing_to_update", "message": "Nothing to update."})
    return _words_call(service.set_personal, current_user, concept_id, fields)


@router.delete("/learner/me/words/{concept_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_my_word(
    concept_id: UUID,
    current_user: CurrentUser = Depends(require_authenticated_user),
    service: MyWordsService = Depends(get_my_words_service),
) -> None:
    _words_call(service.remove, current_user, concept_id)


# --- Named word lists and bulk import (L1b) ----------------------------------------------------------

class CreateListRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    language_code: str = Field(min_length=2, max_length=16)
    name: str = Field(min_length=1, max_length=60)
    description: str | None = Field(default=None, max_length=300)


class ImportListRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=8000)


class ChooseMeaningRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    entry_id: UUID
    sense_id: str = Field(min_length=1, max_length=80)


def _lists_call(operation, *args, **kwargs):
    try:
        return operation(*args, **kwargs)
    except WordListError as exc:
        raise HTTPException(exc.status_code, {"code": exc.code, "message": str(exc)}) from exc


@router.post("/learner/me/lists", response_model=ListSummaryView)
def create_word_list(
    request: CreateListRequest,
    current_user: CurrentUser = Depends(require_authenticated_user),
    service: WordListService = Depends(get_word_list_service),
) -> ListSummaryView:
    """L1b: a private named list of the learner's words."""
    return _lists_call(service.create, current_user, language_code=request.language_code, name=request.name,
                       description=request.description)


@router.get("/learner/me/lists", response_model=list[ListSummaryView])
def list_word_lists(
    language_code: str | None = Query(default=None, min_length=2, max_length=16),
    current_user: CurrentUser = Depends(require_authenticated_user),
    service: WordListService = Depends(get_word_list_service),
) -> list[ListSummaryView]:
    return _lists_call(service.list, current_user, language_code)


@router.get("/learner/me/lists/{list_id}", response_model=ListDetailView)
def get_word_list(
    list_id: UUID,
    current_user: CurrentUser = Depends(require_authenticated_user),
    service: WordListService = Depends(get_word_list_service),
) -> ListDetailView:
    return _lists_call(service.detail, current_user, list_id)


@router.delete("/learner/me/lists/{list_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_word_list(
    list_id: UUID,
    current_user: CurrentUser = Depends(require_authenticated_user),
    service: WordListService = Depends(get_word_list_service),
) -> None:
    """Deletes the list only; the learner's words stay."""
    _lists_call(service.delete, current_user, list_id)


@router.post("/learner/me/lists/{list_id}/import", response_model=ImportReport)
def import_word_list_batch(
    list_id: UUID,
    request: ImportListRequest,
    current_user: CurrentUser = Depends(require_authenticated_user),
    service: WordListService = Depends(get_word_list_service),
) -> ImportReport:
    """One word per line (optionally followed by the learner's own meaning). At most 50 lines are read per
    request; a longer list is sent in batches. The server resolves every word; the client chooses nothing."""
    return _lists_call(service.import_text, current_user, list_id, request.text)


@router.put("/learner/me/lists/{list_id}/lines/{line_id}", response_model=ListWordView)
def choose_list_line_meaning(
    list_id: UUID,
    line_id: UUID,
    request: ChooseMeaningRequest,
    current_user: CurrentUser = Depends(require_authenticated_user),
    service: WordListService = Depends(get_word_list_service),
) -> ListWordView:
    """Picks one of the meanings the server stored for a waiting line."""
    return _lists_call(service.choose_meaning, current_user, list_id, line_id,
                       entry_id=request.entry_id, sense_id=request.sense_id)


@router.delete("/learner/me/lists/{list_id}/lines/{line_id}", status_code=status.HTTP_204_NO_CONTENT)
def dismiss_list_line(
    list_id: UUID,
    line_id: UUID,
    current_user: CurrentUser = Depends(require_authenticated_user),
    service: WordListService = Depends(get_word_list_service),
) -> None:
    _lists_call(service.dismiss_line, current_user, list_id, line_id)


@router.put("/learner/me/lists/{list_id}/words/{concept_id}", status_code=status.HTTP_204_NO_CONTENT)
def add_word_to_list(
    list_id: UUID,
    concept_id: UUID,
    current_user: CurrentUser = Depends(require_authenticated_user),
    service: WordListService = Depends(get_word_list_service),
) -> None:
    _lists_call(service.add_word, current_user, list_id, concept_id)


class AddFromSetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    entry_ids: list[UUID] = Field(min_length=1, max_length=50)


@router.post("/learner/me/lists/{list_id}/from-set", response_model=ImportReport)
def add_words_from_set(
    list_id: UUID,
    request: AddFromSetRequest,
    current_user: CurrentUser = Depends(require_authenticated_user),
    service: WordListService = Depends(get_word_list_service),
) -> ImportReport:
    return _lists_call(service.add_from_set, current_user, list_id, request.entry_ids)


@router.delete("/learner/me/lists/{list_id}/words/{concept_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_word_from_list(
    list_id: UUID,
    concept_id: UUID,
    current_user: CurrentUser = Depends(require_authenticated_user),
    service: WordListService = Depends(get_word_list_service),
) -> None:
    _lists_call(service.remove_word, current_user, list_id, concept_id)


# --- Video coverage (L1c) ----------------------------------------------------------------------------

def _coverage_call(operation, *args, **kwargs):
    try:
        return operation(*args, **kwargs)
    except VideoCoverageError as exc:
        raise HTTPException(exc.status_code, {"code": exc.code, "message": str(exc)}) from exc


@router.get("/learner/me/video-coverage", response_model=list[RecommendationView])
def recommend_videos(
    current_user: CurrentUser = Depends(require_authenticated_user),
    service: VideoCoverageService = Depends(get_video_coverage_service),
) -> list[RecommendationView]:
    """L1c: the learner's own videos ordered by how close they are to the 95% comfort line (an estimate).
    Videos without a word profile yet are listed last; a few are profiled on each call."""
    return _coverage_call(service.recommendations, current_user)
