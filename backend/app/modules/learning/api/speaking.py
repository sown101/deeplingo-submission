"""Learner speaking practice: shadowing; the agent's turn-based text channel.

Learners submit only selectors and raw audio. The backend chooses references,
calls speech providers and returns non-evidential practice feedback.
"""
import json
import logging
from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from app.modules.identity.api.dependencies import require_authenticated_user
from app.bootstrap.wiring.speaking import (
    get_companion_service,
    get_shadowing_practice_service,
    get_word_speech_service,
    get_speaking_rate_limiter,
)
from app.platform.rate_limit import SlidingWindowLimiter
from app.modules.identity.contracts import CurrentUser
from app.modules.learning.application.agent.text import HELP_REQUESTS, TextChannel
from app.modules.learning.application.agent.views import CompanionFinishView, CompanionTurnView, CompanionScenarioView
from app.modules.learning.application.shadowing import ShadowingPracticeService
from app.modules.learning.application.word_speech import WordPronunciationView, WordSpeechService
from app.modules.learning.application.speaking_ports import SpeakingPracticeError
from app.modules.learning.application.speaking_views import (
    ShadowingAssessmentView,
)
from app.modules.learning.domain.companion import MAX_COMPANION_TICKET_CHARS, CompanionEntry
from app.modules.learning.domain.speech_audio import SpeechAudio, SpeechAudioError, parse_wav

router = APIRouter()
logger = logging.getLogger(__name__)
NEWLINE = "\n"  # ends each line of an NDJSON stream

MAX_UPLOAD_BYTES = 2_600_000
SHADOWING_MAX_MS = 60_000
WORD_MAX_MS = 8_000
COMPANION_TURN_MAX_MS = 15_000
_STATUS = {"not_found": 404, "conflict": 409, "unsupported": 422, "invalid_input": 422, "unavailable": 503}


class CompanionStartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    entry: CompanionEntry
    library_item_id: UUID | None = None
    segment_id: UUID | None = None
    topic_id: UUID | None = None
    scenario_id: str | None = Field(default=None, min_length=1, max_length=40)
    swap_roles: bool = False
    text_only: bool = False


def _read_audio(upload: UploadFile, *, max_duration_ms: int, min_duration_ms: int = 300) -> SpeechAudio:
    data = upload.file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, {"code": "audio_too_large", "message": "The recording is too large."})
    try:
        return parse_wav(data, max_duration_ms=max_duration_ms, min_duration_ms=min_duration_ms)
    except SpeechAudioError as exc:
        raise HTTPException(422, {"code": exc.code, "message": str(exc)}) from exc


def _limit(limiter: SlidingWindowLimiter, user: CurrentUser, action: str) -> None:
    if not limiter.allow(str(user.id), action):
        raise HTTPException(429, {"code": "speaking_rate_limited",
                                  "message": "Too many speaking requests. Please wait a moment."})


def _call(operation):
    try:
        return operation()
    except SpeakingPracticeError as exc:
        raise HTTPException(_STATUS.get(exc.kind, 503), {"code": exc.code, "message": str(exc)}) from exc
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Speaking practice failed")
        raise HTTPException(503, {"code": "speech_service_unavailable",
                                  "message": "Speech practice is temporarily unavailable."}) from exc


@router.post(
    "/learner/me/library/videos/{library_item_id}/shadowing/assessments",
    response_model=ShadowingAssessmentView,
)
def assess_shadowing_attempt(
    library_item_id: UUID,
    segment_id: UUID = Form(...),
    region_id: str | None = Form(default=None, max_length=80),
    audio: UploadFile = File(...),
    user: CurrentUser = Depends(require_authenticated_user),
    service: ShadowingPracticeService = Depends(get_shadowing_practice_service),
    limiter: SlidingWindowLimiter = Depends(get_speaking_rate_limiter),
):
    _limit(limiter, user, "shadowing")
    parsed = _read_audio(audio, max_duration_ms=SHADOWING_MAX_MS)
    return _call(lambda: service.assess(user, library_item_id, segment_id, parsed, region_id))


@router.get("/learner/me/dictionary/audio")
def read_word_audio(
    language_code: str = Query(min_length=2, max_length=16),
    text: str = Query(min_length=1, max_length=60),
    user: CurrentUser = Depends(require_authenticated_user),
    service: WordSpeechService = Depends(get_word_speech_service),
    limiter: SlidingWindowLimiter = Depends(get_speaking_rate_limiter),
):
    _limit(limiter, user, "word_audio")
    data = _call(lambda: service.audio(language_code.strip().casefold(), text))
    return Response(content=data, media_type="audio/mpeg", headers={"Cache-Control": "private, max-age=2592000"})


@router.post("/learner/me/dictionary/pronunciation", response_model=WordPronunciationView)
def assess_word_pronunciation(
    language_code: str = Form(min_length=2, max_length=16),
    text: str = Form(min_length=1, max_length=60),
    audio: UploadFile = File(...),
    user: CurrentUser = Depends(require_authenticated_user),
    service: WordSpeechService = Depends(get_word_speech_service),
    limiter: SlidingWindowLimiter = Depends(get_speaking_rate_limiter),
):
    _limit(limiter, user, "shadowing")
    parsed = _read_audio(audio, max_duration_ms=WORD_MAX_MS)
    return _call(lambda: service.assess(user, language_code.strip().casefold(), text, parsed))


@router.post("/learner/me/companion/sessions", response_model=CompanionTurnView)
def start_companion_session(
    request: CompanionStartRequest,
    user: CurrentUser = Depends(require_authenticated_user),
    service: TextChannel = Depends(get_companion_service),
    limiter: SlidingWindowLimiter = Depends(get_speaking_rate_limiter),
):
    _limit(limiter, user, "companion_start")
    options = {"scenario_id": request.scenario_id, "swap_roles": request.swap_roles} if request.scenario_id else {}
    if request.text_only:
        options["text_only"] = True
    return _call(lambda: service.start(user, request.entry, request.library_item_id,
                                       request.segment_id, request.topic_id, **options))


@router.get("/learner/me/companion/scenarios", response_model=list[CompanionScenarioView])
def list_companion_scenarios(
    user: CurrentUser = Depends(require_authenticated_user),
    service: TextChannel = Depends(get_companion_service),
):
    return _call(lambda: service.scenarios(user))


@router.post("/learner/me/companion/turns", response_model=CompanionTurnView)
def take_companion_turn(
    session_ticket: str = Form(..., min_length=1, max_length=MAX_COMPANION_TICKET_CHARS),
    audio: UploadFile | None = File(None, description="The spoken turn (WAV); or send `text` instead"),
    text: str | None = Form(None, max_length=300, description="A typed turn, when the microphone is unavailable"),
    day: date | None = Form(None, description="The learner's local date; names the plan for follow-ups and edits"),
    request: str | None = Form(None, max_length=16, description="A help button pressed: hint, explain, natural or "
                               "suggest. Words or audio may come with it, or nothing else."),
    user: CurrentUser = Depends(require_authenticated_user),
    service: TextChannel = Depends(get_companion_service),
    limiter: SlidingWindowLimiter = Depends(get_speaking_rate_limiter),
):
    _limit(limiter, user, "companion_turn")
    if request is not None and request not in HELP_REQUESTS:
        raise HTTPException(422, {"code": "companion_request_invalid", "message": "Choose one of the help buttons."})
    if (audio is None) == (text is None) and not (request is not None and audio is None and text is None):
        raise HTTPException(422, {"code": "companion_turn_input_invalid", "message": "Send either audio or text."})
    if audio is None:
        return _call(lambda: service.turn(user, session_ticket, text=text, day=day, request=request))
    parsed = _read_audio(audio, max_duration_ms=COMPANION_TURN_MAX_MS, min_duration_ms=300)
    return _call(lambda: service.turn(user, session_ticket, parsed, day=day, request=request))


@router.post("/learner/me/companion/turns/stream", response_class=StreamingResponse,
             responses={200: {"content": {"application/x-ndjson": {}},
                              "description": "One JSON object per line: {type: turn, turn: <CompanionTurnView>}, then "
                                             "{type: audio, index, audio: {mime_type, base64}} per sentence, then "
                                             "{type: done}."}})
def stream_companion_turn(
    session_ticket: str = Form(..., min_length=1, max_length=MAX_COMPANION_TICKET_CHARS),
    audio: UploadFile | None = File(None, description="The spoken turn (WAV); or send `text` instead"),
    text: str | None = Form(None, max_length=300),
    day: date | None = Form(None),
    request: str | None = Form(None, max_length=16),
    user: CurrentUser = Depends(require_authenticated_user),
    service: TextChannel = Depends(get_companion_service),
    limiter: SlidingWindowLimiter = Depends(get_speaking_rate_limiter),
):
    """The same turn as /turns, sent as soon as the agent has answered; its speech follows sentence by sentence
    (agent harness plan, phase 4). Errors before the reply are ordinary JSON errors, as on /turns."""
    _limit(limiter, user, "companion_turn")
    if request is not None and request not in HELP_REQUESTS:
        raise HTTPException(422, {"code": "companion_request_invalid", "message": "Choose one of the help buttons."})
    if (audio is None) == (text is None) and not (request is not None and audio is None and text is None):
        raise HTTPException(422, {"code": "companion_turn_input_invalid", "message": "Send either audio or text."})
    if audio is None:
        view = _call(lambda: service.turn(user, session_ticket, text=text, day=day, request=request, speak=False))
    else:
        parsed = _read_audio(audio, max_duration_ms=COMPANION_TURN_MAX_MS, min_duration_ms=300)
        view = _call(lambda: service.turn(user, session_ticket, parsed, day=day, request=request, speak=False))

    def lines():
        yield json.dumps({"type": "turn", "turn": view.model_dump(mode="json")}, ensure_ascii=False) + NEWLINE
        try:
            for index, part in enumerate(service.speak_parts(view)):
                yield json.dumps({"type": "audio", "index": index, "audio": part.model_dump(mode="json")}) + NEWLINE
        except Exception:
            logger.warning("companion speech stream stopped")  # the reply text is already with the learner
        yield json.dumps({"type": "done"}) + NEWLINE

    return StreamingResponse(lines(), media_type="application/x-ndjson")


@router.post("/learner/me/companion/finish", response_model=CompanionFinishView)
def finish_companion_session(
    session_ticket: str = Form(..., min_length=1, max_length=MAX_COMPANION_TICKET_CHARS),
    day: date | None = Form(None, description="The learner's local date; names the plan for follow-ups"),
    user: CurrentUser = Depends(require_authenticated_user),
    service: TextChannel = Depends(get_companion_service),
    limiter: SlidingWindowLimiter = Depends(get_speaking_rate_limiter),
):
    _limit(limiter, user, "companion_start")
    return _call(lambda: service.finish(user, session_ticket, day=day))
