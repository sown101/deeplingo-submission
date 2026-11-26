"""The notebook's review decks and grammar (TARGET_DESIGN 5).

The client sends selectors and the learner's own input only (an option it was shown, typed text, a self-rating,
audio); the server grades, schedules and logs.
"""
import re
from datetime import datetime
from typing import Any, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile
from pydantic import BaseModel, ConfigDict, Field

from app.bootstrap.wiring.practice import get_grammar_service, get_review_service, get_review_speech
from app.bootstrap.wiring.speaking import get_speaking_rate_limiter
from app.modules.identity.api.dependencies import require_authenticated_user
from app.modules.identity.contracts import CurrentUser
from app.modules.learning.contracts import SpeakingPracticeError, SpeechAudioError, parse_wav
from app.modules.practice.application.grammar import GrammarService
from app.modules.practice.application.review import PracticeError, ReviewAnswer, ReviewService

router = APIRouter()
LANGUAGE = r"^[a-z]{2,3}(-[A-Za-z0-9]{1,8})?$"
EVENT_ID = r"^[A-Za-z0-9_.:-]{1,100}$"
MAX_UPLOAD_BYTES = 2_600_000
WORD_MAX_MS = 8_000
_SPEECH_STATUS = {"not_found": 404, "conflict": 409, "unsupported": 422, "invalid_input": 422, "unavailable": 503}


def _fail(exc: PracticeError) -> HTTPException:
    return HTTPException(exc.status_code, {"code": exc.code, "message": str(exc)})


# --- Review decks ------------------------------------------------------------------------------------------------

class DeckView(BaseModel):
    model_config = ConfigDict(extra="forbid")
    language_code: str
    due_count: int
    new_count: int
    total_count: int


class DecksView(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decks: list[DeckView]


class ExerciseView(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: str
    prompt: dict[str, Any]


class DueCardView(BaseModel):
    model_config = ConfigDict(extra="forbid")
    concept_id: UUID
    text: str
    reading: str | None
    is_new: bool
    due_at: datetime | None
    exercise: ExerciseView


class DueView(BaseModel):
    model_config = ConfigDict(extra="forbid")
    language_code: str
    due_count: int
    new_count: int
    cards: list[DueCardView]


class AnswerInput(BaseModel):
    """What the learner did: the option shown to them, their typed text, their own rating, or "I don't know"."""
    model_config = ConfigDict(extra="forbid")
    option: str | None = Field(default=None, min_length=1, max_length=300)
    dont_know: bool = False
    text: str | None = Field(default=None, max_length=300)
    rating: Literal["again", "hard", "good", "easy"] | None = None
    mistakes: int | None = Field(default=None, ge=0, le=999)


class ReviewAnswerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    client_event_id: str = Field(pattern=EVENT_ID)
    pass_id: str | None = Field(default=None, pattern=EVENT_ID)
    concept_id: UUID
    language_code: str = Field(pattern=LANGUAGE)
    exercise_type: Literal["flashcard", "choice", "listening", "cloze", "writing", "match", "order"]
    answer: AnswerInput
    hint_used: bool = False
    response_ms: int | None = Field(default=None, ge=0, le=3_600_000)


class ReviewAnswerView(BaseModel):
    model_config = ConfigDict(extra="forbid")
    client_event_id: str
    concept_id: UUID
    exercise_type: str
    outcome: str | None
    correct: bool
    grade: str | None
    scheduled: bool
    next_review_at: datetime | None
    expected: str
    duplicate: bool
    # Pronunciation only: Azure's whole result (scores, each word with its error type and phonemes).
    assessment: dict[str, Any] | None = None


class LatestPronunciationView(BaseModel):
    model_config = ConfigDict(extra="forbid")
    concept_id: UUID
    latest: dict[str, Any] | None


@router.get("/learner/me/review/decks", response_model=DecksView)
def list_review_decks(user: CurrentUser = Depends(require_authenticated_user),
                      service: ReviewService = Depends(get_review_service)) -> DecksView:
    """One deck per language the learner has saved words in, with how many cards are due and new."""
    return DecksView(decks=[DeckView(**deck) for deck in service.decks(user.id)])


@router.get("/learner/me/review/{language}/due", response_model=DueView)
def read_due_cards(
    language: str,
    mode: Literal["mixed", "flashcard", "choice", "listening", "cloze", "pronunciation", "writing", "match",
                  "order"] = "mixed",
    limit: int = Query(default=20, ge=1, le=50),
    concept_ids: list[UUID] | None = Query(default=None, max_length=50),
    types: str | None = Query(default=None, max_length=120, pattern=r"^[a-z]+(,[a-z]+)*$"),
    user: CurrentUser = Depends(require_authenticated_user),
    service: ReviewService = Depends(get_review_service),
) -> DueView:
    """The cards of one review pass in one language, each with its exercise (no answer keys). `types` is the
    notebook's review settings: the chosen exercise types, taken in turn."""
    _check_language(language)
    try:
        return DueView(**service.due(user.id, language, mode=mode, limit=limit, concept_ids=concept_ids,
                                     types=types.split(",") if types else None))
    except PracticeError as exc:
        raise _fail(exc) from exc


@router.post("/learner/me/review/answers", response_model=ReviewAnswerView)
def answer_review_card(body: ReviewAnswerRequest, user: CurrentUser = Depends(require_authenticated_user),
                       service: ReviewService = Depends(get_review_service)) -> ReviewAnswerView:
    """Grades one answer, moves the schedule at most once per pass and logs it, in one transaction."""
    try:
        return ReviewAnswerView(**service.answer(ReviewAnswer(
            user_id=user.id, concept_id=body.concept_id, language_code=body.language_code,
            exercise_type=body.exercise_type, client_event_id=body.client_event_id, pass_id=body.pass_id,
            answer=body.answer.model_dump(exclude_none=True), hint_used=body.hint_used,
            response_ms=body.response_ms)))
    except PracticeError as exc:
        raise _fail(exc) from exc


@router.post("/learner/me/review/answers/pronunciation", response_model=ReviewAnswerView)
def answer_review_pronunciation(
    client_event_id: str = Form(pattern=EVENT_ID),
    concept_id: UUID = Form(...),
    language_code: str = Form(pattern=LANGUAGE),
    pass_id: str | None = Form(default=None, pattern=EVENT_ID),
    audio: UploadFile = File(...),
    user: CurrentUser = Depends(require_authenticated_user),
    service: ReviewService = Depends(get_review_service),
    speech=Depends(get_review_speech),
    limiter=Depends(get_speaking_rate_limiter),
) -> ReviewAnswerView:
    """The learner says the word; Azure's score grades it (no audio is kept). Practice only: the schedule never moves.
    The response and the log row carry Azure's whole result."""
    if not limiter.allow(str(user.id), "shadowing"):
        raise HTTPException(429, {"code": "speaking_rate_limited",
                                  "message": "Too many speaking requests. Please wait a moment."})
    request = ReviewAnswer(user_id=user.id, concept_id=concept_id, language_code=language_code,
                           exercise_type="pronunciation", client_event_id=client_event_id, pass_id=pass_id)
    try:
        text = service.pronunciation_text(request)
        parsed = _read_audio(audio)
        _, scored_band, result = _speech(lambda: speech.assess_result(user, language_code, text, parsed, saved=True))
        band = str(getattr(scored_band, "value", scored_band))
        assessment = _assessment(band, result)
        view = service.answer_pronunciation(request, band=band, score=result.scores.pronunciation,
                                            assessment=assessment)
        return ReviewAnswerView(**view, assessment=assessment)
    except PracticeError as exc:
        raise _fail(exc) from exc


@router.get("/learner/me/review/cards/{concept_id}/audio")
def read_card_audio(concept_id: UUID, user: CurrentUser = Depends(require_authenticated_user),
                    service: ReviewService = Depends(get_review_service), speech=Depends(get_review_speech),
                    limiter=Depends(get_speaking_rate_limiter)) -> Response:
    """A saved word read aloud, chosen by id so a listening question does not show its answer."""
    if not limiter.allow(str(user.id), "word_audio"):
        raise HTTPException(429, {"code": "speaking_rate_limited", "message": "Too many requests."})
    try:
        card = service.card(user.id, concept_id)
    except PracticeError as exc:
        raise _fail(exc) from exc
    data = _speech(lambda: speech.audio(card.language_code, card.text, saved=True))
    return Response(content=data, media_type="audio/mpeg", headers={"Cache-Control": "private, max-age=86400"})


@router.get("/learner/me/words/{concept_id}/pronunciation", response_model=LatestPronunciationView)
def read_latest_pronunciation(concept_id: UUID, user: CurrentUser = Depends(require_authenticated_user),
                              service: ReviewService = Depends(get_review_service)) -> LatestPronunciationView:
    """The learner's latest pronunciation result for one word, or none yet."""
    row = service.latest_pronunciation(user.id, concept_id)
    if row is None:
        return LatestPronunciationView(concept_id=concept_id, latest=None)
    detail = row.get("detail") or {}
    return LatestPronunciationView(concept_id=concept_id, latest={
        "score": row.get("score"), "band": detail.get("band"), "occurred_at": row.get("occurred_at"),
        "assessment": detail.get("assessment")})


def _assessment(band: str, result) -> dict[str, Any]:
    scores = result.scores
    return {
        "band": band, "recognized_text": result.recognized_text,
        "scores": {"pronunciation": scores.pronunciation, "accuracy": scores.accuracy, "fluency": scores.fluency,
                   "completeness": scores.completeness, "prosody": scores.prosody},
        "words": [{"word": word.word, "accuracy": word.accuracy,
                   "error_type": str(getattr(word.error_type, "value", word.error_type)),
                   "phonemes": [{"phoneme": item.phoneme, "accuracy": item.accuracy} for item in word.phonemes]}
                  for word in result.words],
    }


def _check_language(language: str) -> None:
    if not re.fullmatch(LANGUAGE, language):
        raise HTTPException(422, {"code": "language_invalid", "message": "Unknown language."})


def _read_audio(upload: UploadFile):
    data = upload.file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, {"code": "audio_too_large", "message": "The recording is too large."})
    try:
        return parse_wav(data, max_duration_ms=WORD_MAX_MS, min_duration_ms=300)
    except SpeechAudioError as exc:
        raise HTTPException(422, {"code": exc.code, "message": str(exc)}) from exc


def _speech(operation):
    try:
        return operation()
    except SpeakingPracticeError as exc:
        raise HTTPException(_SPEECH_STATUS.get(exc.kind, 503), {"code": exc.code, "message": str(exc)}) from exc


# --- Grammar -----------------------------------------------------------------------------------------------------

class GrammarAnswerBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    language_code: str = Field(pattern=LANGUAGE)
    exercise_id: str = Field(min_length=1, max_length=120)
    option_id: str = Field(min_length=1, max_length=20)
    client_event_id: str = Field(pattern=EVENT_ID)


class GrammarLessonBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    language_code: str = Field(pattern=LANGUAGE)
    grammar_key: str = Field(min_length=1, max_length=80)
    client_event_id: str = Field(pattern=EVENT_ID)


@router.get("/learner/me/grammar/{language}", response_model=dict)
def read_grammar(language: str, level: str | None = Query(default=None, max_length=8),
                 user: CurrentUser = Depends(require_authenticated_user),
                 service: GrammarService = Depends(get_grammar_service)) -> dict:
    """Levels, points with their lessons and the learner's results, and the "redo" list, in one language."""
    _check_language(language)
    try:
        return service.overview(user.id, language, level=level)
    except PracticeError as exc:
        raise _fail(exc) from exc


@router.get("/learner/me/grammar/{language}/exercises", response_model=dict)
def read_grammar_exercises(language: str, level: str | None = Query(default=None, max_length=8),
                           grammar_key: str | None = Query(default=None, max_length=80),
                           user: CurrentUser = Depends(require_authenticated_user),
                           service: GrammarService = Depends(get_grammar_service)) -> dict:
    _check_language(language)
    try:
        return service.exercises(user.id, language, level=level, grammar_key=grammar_key)
    except PracticeError as exc:
        raise _fail(exc) from exc


@router.post("/learner/me/grammar/answers", response_model=dict)
def answer_grammar(body: GrammarAnswerBody, user: CurrentUser = Depends(require_authenticated_user),
                   service: GrammarService = Depends(get_grammar_service)) -> dict:
    try:
        return service.answer(user.id, body.language_code, exercise_id=body.exercise_id, option_id=body.option_id,
                              client_event_id=body.client_event_id)
    except PracticeError as exc:
        raise _fail(exc) from exc


@router.post("/learner/me/grammar/lessons", response_model=dict)
def learn_grammar_lesson(body: GrammarLessonBody, user: CurrentUser = Depends(require_authenticated_user),
                         service: GrammarService = Depends(get_grammar_service)) -> dict:
    try:
        return service.lesson_learned(user.id, body.language_code, grammar_key=body.grammar_key,
                                      client_event_id=body.client_event_id)
    except PracticeError as exc:
        raise _fail(exc) from exc


# --- Notebook flashcard rating ------------------------------------------------------------------------------------

class MemoryRatingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rating: Literal["not_yet", "unsure", "remembered"]
    client_event_id: UUID | None = None  # a retry of the same rating is stored once


@router.post("/learner/me/words/{concept_id}/memory-rating")
def rate_word_memory(concept_id: UUID, request: MemoryRatingRequest,
                     user: CurrentUser = Depends(require_authenticated_user),
                     service: ReviewService = Depends(get_review_service)) -> dict:
    """The notebook flashcard's own rating, through the review engine as a flashcard answer."""
    try:
        return {"next_review_at": service.rate_memory(user.id, concept_id, request.rating,
                                                      str(request.client_event_id or uuid4()))}
    except PracticeError as exc:
        raise _fail(exc) from exc
