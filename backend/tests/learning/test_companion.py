"""Voice companion, phase 1: context, strict turn contract, tickets, synthesis, API."""
import base64
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from app.bootstrap.wiring.identity import get_jwt_verifier
from app.bootstrap.wiring.speaking import get_companion_service, get_speaking_rate_limiter
from app.main import app
from app.modules.identity.contracts import CurrentUser
from app.modules.learning.application.agent.text import TextChannel
from app.modules.learning.application.agent.ports import (
    CompanionTicket,
    InvalidCompanionTicket,
    SpeechSynthesisUnavailable,
    SynthesizedSpeech,
)
from app.modules.learning.application.learned_items import LearnedItem
from app.modules.learning.application.speaking_ports import SpeakingPracticeError, SpeechProviderFailure
from app.modules.learning.application.speech_transcription import SpeechTranscript
from app.modules.learning.domain.companion import MAX_TURNS, CompanionEntry, CompanionItem
from app.modules.learning.domain.speech_audio import SpeechAudio
from app.modules.learning.infrastructure.speech.azure_tts import AzureSpeechSynthesizer
from app.modules.learning.infrastructure.speech.companion_tickets import SignedCompanionTicketCodec
from app.platform.llm.port import ChatReply, ToolCall
from app.platform.rate_limit import SlidingWindowLimiter
from tests.learning.speaking_fixtures import pcm_silence, pcm_tone, speech_like_wav

OWNER, OTHER = uuid4(), uuid4()
ITEM_ID, VIDEO_ID = uuid4(), uuid4()
FLY = LearnedItem("11111111-1111-1111-1111-111111111111", "fly", "vocabulary", "đi máy bay", "from_video",
                  ("fly", "flying"))
AIRPORT = LearnedItem("22222222-2222-2222-2222-222222222222", "airport", "vocabulary", "sân bay", "practiced",
                      ("airport",))


class Turn:
    """One scripted agent turn: tool calls (one model call), then the final text (the next model call)."""

    def __init__(self, reply, support=None, calls=(), end=False):
        self.reply, self.support, self.calls, self.end = reply, support, list(calls), end

    @property
    def text(self):
        text = self.reply if self.support is None else f"{self.reply}\n---\n{self.support}"
        return text + "\n[end]" if self.end else text


def turn_output(**overrides):
    """The agent's turn as a script. `correction`, `hint_*` and `suggest_practice` overrides become tool calls."""
    reply = overrides.pop("reply", "Do you like flying?")
    support = overrides.pop("reply_support", "Bạn có thích đi máy bay không?")
    calls = []
    correction = overrides.pop("correction", None)
    if correction:
        calls.append(("show_correction", {"quote": correction["quote"], "suggestion": correction["suggestion"],
                                          "note": correction["note_support"],
                                          "grammar_point": correction.get("grammar_point")}))
    if any(key.startswith("hint_") for key in overrides):
        frame = overrides.get("hint_frame")
        calls.append(("show_hint", {
            "question": overrides.get("hint_question_support", "Bạn thích hay không thích? Vì sao?"),
            "words": [item.text for item in (FLY, AIRPORT) if item.concept_id in overrides.get("hint_item_ids", [])],
            "frame": frame["frame"] if frame else None, "frame_reason": frame["reason_support"] if frame else None,
            "model_sentence": overrides.get("hint_model_sentence")}))
    if overrides.get("suggest_practice"):
        suggestion = overrides["suggest_practice"]
        calls.append(("suggest_practice", {"tool": suggestion["tool"], "segment_ref": suggestion["segment_ref"],
                                           "reason": suggestion["reason_support"]}))
    return Turn(reply, support, calls, end=overrides.get("next") == "close")


class FakeModel:
    """A scripted `ToolCallingModel`: each entry is a `Turn` (its tool calls, then its text), a `ChatReply`, or an
    exception to raise on that model call."""

    provider_name, model_name = "fake", "fake-companion"

    def __init__(self, outputs):
        self.queue = []
        for item in outputs:
            if isinstance(item, Turn):
                if item.calls:
                    self.queue.append(ChatReply(None, tuple(ToolCall(f"c{index}", name, args)
                                                            for index, (name, args) in enumerate(item.calls))))
                self.queue.append(ChatReply(item.text))
            else:
                self.queue.append(item)
        self.calls = []  # (messages, tool names) of every model call

    @property
    def outputs(self):
        return self.queue

    @property
    def prompts(self):
        """The text the model saw on each call: the system prompt and every message."""
        return ["\n".join(str(message.get("content")) for message in messages) for messages, _ in self.calls]

    def generate_with_tools(self, messages, tools, **kwargs):
        self.calls.append((list(messages), [tool.name for tool in tools]))
        value = self.queue.pop(0)
        if isinstance(value, Exception):
            raise value
        return value


class FakeTranscriber:
    def __init__(self, texts=()):
        self.texts = list(texts)

    def transcribe(self, audio, *, language_code):
        value = self.texts.pop(0)
        if isinstance(value, Exception):
            raise value
        return SpeechTranscript(text=value, model="fake")


class FakeSynthesizer:
    provider_name = "fake"

    def __init__(self, fail=False):
        self.fail, self.calls = fail, []

    def supports(self, language_code):
        return language_code in {"en", "zh"}

    def synthesize(self, text, *, language_code):
        self.calls.append((text, language_code))
        if self.fail:
            raise SpeechSynthesisUnavailable("down")
        return SynthesizedSpeech(audio=b"ID3mp3", mime_type="audio/mpeg", characters=len(text))


class FakeCatalog:
    def __init__(self, items=(FLY, AIRPORT)):
        self.items, self.calls = list(items), []

    def for_learner(self, user_id, **kwargs):
        self.calls.append(kwargs)
        return list(self.items)


def make_service(*, outputs=(turn_output(),), texts=(), synthesizer=None, video_status="ready",
                 due=(AIRPORT.concept_id,), items=(FLY, AIRPORT), codec=None):
    preferences = Mock()
    preferences.get_profile_for_user.return_value = SimpleNamespace(language_code="en", support_language_code="vi")
    library = Mock()
    library.get_for_user.side_effect = lambda library_item_id, user_id: (
        SimpleNamespace(video_id=VIDEO_ID) if (library_item_id, user_id) == (ITEM_ID, OWNER) else None)
    video = SimpleNamespace(id=VIDEO_ID, title="I enjoy flying but airports are stressful",
                            original_language_code="en", learning_status=video_status)
    videos = Mock()
    videos.get_by_id.side_effect = lambda video_id: video if video_id == VIDEO_ID else None
    transcript_id = uuid4()
    transcripts = Mock()
    transcripts.list_for_video.return_value = [SimpleNamespace(id=transcript_id, is_original=True, language_code="en")]
    segments = Mock()
    segments.list_head_for_transcript.return_value = [SimpleNamespace(text="I love flying."),
                                                      SimpleNamespace(text="Airports are stressful.")]
    due_reader = Mock()
    due_reader.due_concept_ids.return_value = list(due)
    service = TextChannel(
        preferences=preferences, catalog=FakeCatalog(items), library=library, videos=videos,
        transcripts=transcripts, segments=segments, due=due_reader, model=FakeModel(outputs),
        transcriber=FakeTranscriber(texts), synthesizer=synthesizer or FakeSynthesizer(),
        tickets=codec or SignedCompanionTicketCodec(b"k" * 32),
        consent=SimpleNamespace(has_consent=lambda _: True),
    )
    return service


def speech(ms=2000):
    return SpeechAudio(pcm_tone(ms))


def error_of(callable_):
    with pytest.raises(SpeakingPracticeError) as raised:
        callable_()
    return raised.value.kind, raised.value.code


USER = CurrentUser(id=OWNER)


# --- Start: context and entry points ------------------------------------------------

def test_video_entry_uses_only_that_owned_video_and_returns_a_spoken_opening():
    service = make_service()

    view = service.start(USER, CompanionEntry.VIDEO, ITEM_ID)

    assert [video.id for video in service.catalog.calls[0]["owned_videos"]] == [VIDEO_ID]
    prompt = service.model.prompts[0]
    assert "<topic>I enjoy flying but airports are stressful</topic>" in prompt
    assert "I love flying. Airports are stressful." in prompt
    assert "- fly | meaning: đi máy bay | new from the video" in prompt
    assert "just opened the conversation" in prompt
    assert view.turn == 0 and view.max_turns == MAX_TURNS and not view.finished and view.session_ticket
    assert view.learner_transcript is None and view.reply == "Do you like flying?"
    assert view.hints.question is None and view.auto_hint_level is None  # the opening shows no help
    assert service.model.calls[0][1] == []  # and needs no tools
    assert view.audio_status == "ready" and base64.b64decode(view.audio.base64) == b"ID3mp3"
    assert service.synthesizer.calls == [("Do you like flying?", "en")]


def test_video_entry_rechecks_ownership_readiness_and_selectors():
    assert error_of(lambda: make_service().start(CurrentUser(id=OTHER), CompanionEntry.VIDEO, ITEM_ID)) == (
        "not_found", "companion_video_not_found")
    assert error_of(lambda: make_service(video_status="processing").start(USER, CompanionEntry.VIDEO, ITEM_ID)) == (
        "conflict", "companion_video_not_ready")
    assert error_of(lambda: make_service().start(USER, CompanionEntry.VIDEO, None))[1] == "companion_video_required"
    assert error_of(lambda: make_service().start(USER, CompanionEntry.HOME, ITEM_ID))[1] == \
        "companion_selector_unexpected"


def test_review_entry_offers_only_due_items_and_home_offers_recent_items():
    review = make_service()
    review.start(USER, CompanionEntry.REVIEW, None)
    assert "- airport |" in review.model.prompts[0] and "- fly |" not in review.model.prompts[0]

    home = make_service()
    home.start(USER, CompanionEntry.HOME, None)
    assert "video_ids" not in home.catalog.calls[0]
    assert "- fly |" in home.model.prompts[0] and "- airport |" in home.model.prompts[0]


def test_no_prepared_items_means_no_conversation():
    assert error_of(lambda: make_service(due=()).start(USER, CompanionEntry.REVIEW, None)) == (
        "conflict", "companion_no_items")
    assert error_of(lambda: make_service(items=()).start(USER, CompanionEntry.HOME, None))[1] == "companion_no_items"


# --- Turns ---------------------------------------------------------------------------

def started(service):
    return service.start(USER, CompanionEntry.VIDEO, ITEM_ID).session_ticket


def test_turn_transcribes_validates_and_carries_history_in_a_new_ticket():
    reply = turn_output(
        reply="Great! Why do you like the airport?",
        correction={"quote": "I like fly", "suggestion": "I like flying",
                    "note_support": "Thử nói lại với 'flying' nhé."},
        used_item_ids=[AIRPORT.concept_id], next="retry")  # `used_item_ids` and `next` are no longer the model's
    service = make_service(outputs=(turn_output(), reply), texts=["I like fly to the airport"])
    ticket = started(service)

    view = service.turn(USER, ticket, speech())

    assert view.learner_transcript == "I like fly to the airport" and view.turn == 1 and view.next == "retry"
    assert view.correction.quote == "I like fly" and view.correction.suggestion == "I like flying"
    assert [item.text for item in view.used_items] == ["fly", "airport"]  # detected by the server, offered only
    messages = service.model.calls[1][0]
    assert messages[-1] == {"role": "user", "content": "<learner_said>I like fly to the airport</learner_said>"}
    assert messages[-2] == {"role": "assistant", "content": "Do you like flying?"}  # the history, as messages
    history = service.load(USER, view.session_ticket).history
    assert [message.role for message in history] == ["companion", "learner", "companion"]


def test_a_turn_rechecks_ownership_with_one_read_and_reuses_the_signed_excerpt():
    service = make_service(outputs=(turn_output(), turn_output()), texts=["I like flying"])
    ticket = started(service)
    assert service.load(USER, ticket).ticket.excerpt == "I love flying. Airports are stressful."
    service.transcripts.reset_mock()
    service.segments.reset_mock()
    service.videos.reset_mock()
    service.library.get_for_user.reset_mock()

    service.turn(USER, ticket, speech())

    assert "I love flying. Airports are stressful." in service.model.prompts[1]
    service.library.get_for_user.assert_called_once_with(library_item_id=ITEM_ID, user_id=OWNER)
    service.transcripts.list_for_video.assert_not_called()
    service.segments.list_head_for_transcript.assert_not_called()
    service.videos.get_by_id.assert_not_called()


def test_a_video_removed_from_the_library_ends_the_conversation_on_the_next_turn():
    service = make_service(outputs=(turn_output(), turn_output()), texts=["I like flying"])
    ticket = started(service)
    service.library.get_for_user.side_effect = lambda library_item_id, user_id: None

    assert error_of(lambda: service.turn(USER, ticket, speech())) == ("not_found", "companion_video_not_found")


def test_the_whole_session_stays_in_the_history_the_model_sees():
    turns = 12
    service = make_service(outputs=tuple(turn_output() for _ in range(turns + 1)),
                           texts=["I have a cat"] + [f"Answer {index}" for index in range(1, turns)])
    ticket = started(service)
    for _ in range(turns):
        ticket = service.turn(USER, ticket, speech()).session_ticket
    # Said in turn 1, known in 12: the conversation keeps each turn as the model saw it.
    assert {"role": "user", "content": "<learner_said>I have a cat</learner_said>"} in service.model.calls[-1][0]
    assert len(service.load(USER, ticket).history) == 2 * turns + 1


def test_a_ticket_is_single_use_and_bound_to_its_learner():
    service = make_service(outputs=(turn_output(), turn_output(), turn_output()), texts=["Yes", "Yes"])
    ticket = started(service)
    service.turn(USER, ticket, speech())
    assert error_of(lambda: service.turn(USER, ticket, speech())) == ("invalid_input", "companion_session_invalid")
    other = make_service()
    assert error_of(lambda: other.turn(CurrentUser(id=OTHER), started(other), speech()))[1] == \
        "companion_session_invalid"
    assert error_of(lambda: service.turn(USER, ticket[:-4] + "abcd", speech()))[1] == "companion_session_invalid"


def test_an_answer_that_keeps_breaking_the_level_policy_fails_closed_without_spending_the_ticket():
    bad = turn_output(reply="Yes " * 25)
    service = make_service(outputs=(turn_output(), *[bad] * 6, turn_output()), texts=["I like fly", "I like fly"])
    ticket = started(service)

    assert error_of(lambda: service.turn(USER, ticket, speech())) == ("unavailable", "companion_turn_unavailable")
    assert service.turn(USER, ticket, speech()).turn == 1  # the same ticket still works after a failure


@pytest.mark.parametrize("bad", [
    turn_output(hint_frame={"frame": "I like flying.", "reason_support": "no blank"}),  # a frame without a blank
    turn_output(correction={"quote": "I liked flying", "suggestion": "x", "note_support": "y"}),  # not what was said
])
def test_a_tool_call_the_server_refuses_is_dropped_and_the_turn_still_answers(bad):
    service = make_service(outputs=(turn_output(), bad), texts=["I like fly"])
    view = service.turn(USER, started(service), speech())
    assert view.correction is None and view.next == "continue" and view.hints.frame is None
    assert view.auto_hint_level is None


def test_a_valid_retry_is_used_after_one_invalid_output():
    service = make_service(outputs=(turn_output(), turn_output(reply="Yes " * 25), turn_output(reply="Nice!")),
                           texts=["I like flying"])
    assert service.turn(USER, started(service), speech()).reply == "Nice!"


def test_silence_and_provider_failure_are_not_learner_failure_and_keep_the_ticket():
    service = make_service(outputs=(turn_output(), turn_output()),
                           texts=[SpeechProviderFailure("transcription_unavailable"), "Hello"])
    ticket = started(service)
    assert error_of(lambda: service.turn(USER, ticket, SpeechAudio(pcm_silence(2000))))[1] == "no_speech_detected"
    kind, _ = error_of(lambda: service.turn(USER, ticket, speech()))
    assert kind == "unavailable"
    assert service.turn(USER, ticket, speech()).learner_transcript == "Hello"


def test_the_turn_limit_ends_the_session_without_a_new_ticket():
    service = make_service(outputs=(turn_output(), turn_output()), texts=["Yes"])
    session = service.load(USER, started(service))
    session.turn = MAX_TURNS - 1
    near_end, _ = service.save(session)
    view = service.turn(USER, near_end, speech())
    assert view.turn == MAX_TURNS and view.finished and view.session_ticket is None
    assert service.sessions.get(session.id, OWNER) is None  # a finished conversation is not kept


def test_synthesis_failure_still_returns_the_text_turn():
    service = make_service(synthesizer=FakeSynthesizer(fail=True))
    view = service.start(USER, CompanionEntry.VIDEO, ITEM_ID)
    assert view.audio is None and view.audio_status == "unavailable" and view.reply


def test_missing_configuration_makes_the_companion_unavailable():
    service = make_service()
    service.model = None
    assert error_of(lambda: service.start(USER, CompanionEntry.HOME, None)) == ("unavailable", "companion_unavailable")


# --- Tickets ---------------------------------------------------------------------------

def ticket(**overrides):
    data = dict(user_id=OWNER, language_code="en", support_language_code="vi", entry=CompanionEntry.VIDEO,
                library_item_id=ITEM_ID, topic="Flying",
                items=(CompanionItem(FLY.concept_id, "fly", "đi máy bay", ("fly", "flying"), False),))
    data.update(overrides)
    return CompanionTicket(**data)


def test_ticket_is_a_short_signed_reference_and_rejects_tampering_and_expiry(monkeypatch):
    from datetime import UTC, datetime, timedelta
    codec = SignedCompanionTicketCodec(b"k" * 32)
    conversation, began = uuid4(), datetime.now(UTC)
    token, issued = codec.issue(conversation, OWNER, started_at=began)
    read = codec.read(token)
    assert (read.conversation_id, read.user_id, read.token_id) == (conversation, OWNER, issued.token_id)
    assert len(token) < 400 and "Flying" not in token  # no conversation content travels to the client
    # It expires with the conversation: at most 15 minutes after it started, whatever the ticket lifetime.
    assert read.expires_at <= began + timedelta(seconds=900)
    assert codec.issue(conversation, OWNER, started_at=began)[1].token_id != issued.token_id  # one id per turn
    with pytest.raises(InvalidCompanionTicket):
        SignedCompanionTicketCodec(b"x" * 32).read(token)
    with pytest.raises(InvalidCompanionTicket):
        codec.read(token[:-4] + "abcd")
    old = SignedCompanionTicketCodec(b"k" * 32, clock=lambda: datetime.now(UTC) - timedelta(hours=1))
    with pytest.raises(InvalidCompanionTicket):
        codec.read(old.issue(conversation, OWNER, started_at=began - timedelta(hours=1))[0])
    monkeypatch.setattr("app.platform.config.settings.SPEAKING_TICKET_SECRET", "s" * 32)
    from app.bootstrap.wiring import speaking
    assert speaking.companion_ticket_secret() != speaking.speaking_ticket_secret()


# --- Azure synthesis adapter --------------------------------------------------------------

def test_azure_tts_posts_escaped_ssml_with_the_server_key():
    seen = {}

    def handler(request: httpx.Request):
        seen.update(url=str(request.url), headers=request.headers, body=request.content.decode("utf-8"))
        return httpx.Response(200, content=b"ID3audio")

    tts = AzureSpeechSynthesizer(key="server-key", region="southeastasia",
                                 client=httpx.Client(transport=httpx.MockTransport(handler)))
    speech_out = tts.synthesize("Tom & Jerry <say> 'hi'", language_code="en")

    assert seen["url"] == "https://southeastasia.tts.speech.microsoft.com/cognitiveservices/v1"
    assert seen["headers"]["Ocp-Apim-Subscription-Key"] == "server-key"
    assert "Tom &amp; Jerry &lt;say&gt;" in seen["body"] and "en-US-JennyNeural" in seen["body"]
    assert "rate=\"-15%\"" in seen["body"] or "rate='-15%'" in seen["body"]
    assert (speech_out.audio, speech_out.mime_type, speech_out.characters) == (b"ID3audio", "audio/mpeg", 22)
    assert tts.supports("zh-CN") and not tts.supports("ko")


@pytest.mark.parametrize("response", [httpx.Response(401), httpx.Response(200, content=b"")])
def test_azure_tts_failures_are_synthesis_unavailable(response):
    tts = AzureSpeechSynthesizer(key="k", region="r", client=httpx.Client(transport=httpx.MockTransport(
        lambda request: response)))
    with pytest.raises(SpeechSynthesisUnavailable):
        tts.synthesize("Hello", language_code="en")
    with pytest.raises(SpeechSynthesisUnavailable):
        tts.synthesize("Hello", language_code="ko")


# --- API -----------------------------------------------------------------------------------

@pytest.fixture
def api():
    verifier = Mock()
    verifier.verify.side_effect = lambda token: CurrentUser(id=OWNER)
    service = make_service(outputs=(turn_output(), turn_output(reply="Nice!")), texts=["I like flying"])
    limiter = SlidingWindowLimiter({"companion_start": (1, 60), "companion_turn": (5, 60)})
    app.dependency_overrides[get_jwt_verifier] = lambda: verifier
    app.dependency_overrides[get_companion_service] = lambda: service
    app.dependency_overrides[get_speaking_rate_limiter] = lambda: limiter
    try:
        yield SimpleNamespace(client=TestClient(app), service=service, headers={"Authorization": "Bearer owner.test.jwt"})
    finally:
        app.dependency_overrides.clear()


def test_companion_endpoints_round_trip_the_ticket_and_reject_client_authority(api):
    url = "/api/v1/v3/learner/me/companion"
    assert api.client.post(f"{url}/sessions", json={"entry": "home"}).status_code == 401
    forged = api.client.post(f"{url}/sessions", headers=api.headers,
                             json={"entry": "video", "library_item_id": str(ITEM_ID), "items": ["x"]})
    assert forged.status_code == 422
    started_view = api.client.post(f"{url}/sessions", headers=api.headers,
                                   json={"entry": "video", "library_item_id": str(ITEM_ID)})
    assert started_view.status_code == 200
    body = started_view.json()
    assert body["entry"] == "video" and body["audio"]["mime_type"] == "audio/mpeg"
    for hidden in ("item_id=", "sense_id", "prompt", "score", "mastery"):
        assert hidden not in str(body)
    turn = api.client.post(f"{url}/turns", headers=api.headers, data={"session_ticket": body["session_ticket"]},
                           files={"audio": ("t.wav", speech_like_wav(2000), "audio/wav")})
    assert turn.status_code == 200 and turn.json()["reply"] == "Nice!"
    too_long = api.client.post(f"{url}/turns", headers=api.headers, data={"session_ticket": body["session_ticket"]},
                               files={"audio": ("t.wav", speech_like_wav(16_000), "audio/wav")})
    assert too_long.status_code == 422
    assert api.client.post(f"{url}/sessions", headers=api.headers, json={"entry": "home"}).status_code == 429


def test_learned_item_catalog_can_be_limited_to_one_video():
    from app.modules.learning.application.learned_items import LearnedItemCatalog
    keep, skip = uuid4(), uuid4()
    library = Mock()
    library.list_for_user.return_value = [SimpleNamespace(video_id=skip), SimpleNamespace(video_id=keep)]
    videos = Mock()
    videos.get_many_by_ids.side_effect = lambda ids: {video_id: SimpleNamespace(
        id=video_id, original_language_code="en", learning_status="ready") for video_id in ids}
    objects = Mock()
    objects.list_for_videos.return_value = []
    catalog = LearnedItemCatalog(library=library, videos=videos, learning_objects=objects,
                                 concepts=Mock())

    assert catalog.for_learner(OWNER, language_code="en", support_language_code="vi", video_ids={keep}) == []
    assert videos.get_many_by_ids.call_args.args[0] == [keep]  # one batched read, the selected video only
    assert objects.list_for_videos.call_args.args[0] == [keep]


def test_learned_item_catalog_uses_caller_resolved_videos_without_listing_the_library():
    from app.modules.learning.application.learned_items import LearnedItemCatalog
    video = SimpleNamespace(id=uuid4(), original_language_code="en", learning_status="ready")
    library, videos, objects = Mock(), Mock(), Mock()
    objects.list_for_videos.return_value = []
    catalog = LearnedItemCatalog(library=library, videos=videos, learning_objects=objects,
                                 concepts=Mock())

    assert catalog.for_learner(OWNER, language_code="en", support_language_code="vi", owned_videos=[video]) == []
    library.list_for_user.assert_not_called()
    videos.get_many_by_ids.assert_not_called()
    assert objects.list_for_videos.call_args.args[0] == [video.id]


def test_items_with_the_same_text_are_offered_once():
    twin = LearnedItem("33333333-3333-3333-3333-333333333333", "Fly", "vocabulary", "con ruồi", "from_video", ("fly",))
    service = make_service(items=(FLY, twin, AIRPORT))
    service.start(USER, CompanionEntry.HOME, None)
    assert "con ruồi" not in service.model.prompts[0] and "- fly |" in service.model.prompts[0]


# --- Learner profile brief ---------------------------------------------------------------

class FakeFacts:
    """The learner's own data as the agent reads it (AgentFacts), all empty unless a test fills it."""

    def __init__(self, *, brief="", recent=(), region=(), due=None, requests=(), menu=None, created="created",
                 level=None):
        self.level = level
        self.brief, self.recent, self.region, self.due = brief, list(recent), list(region), due or {}
        self.requests, self.menu, self.created, self.calls = list(requests), menu, created, []

    def profile_brief(self, user_id, language_code):
        self.calls.append(("profile_brief", user_id, language_code))
        return self.brief

    def declared_level(self, user_id, language_code):
        return self.level

    def recent_activity(self, user_id, language_code, *, kind, since, limit):
        self.calls.append(("recent_activity", user_id, language_code, kind, since))
        return self.recent[:limit]

    def region_activity(self, user_id, region_id, *, limit):
        self.calls.append(("region_activity", user_id, region_id))
        return self.region[:limit]

    def due_counts(self, user_id):
        return self.due

    def due_cards(self, user_id, language_code, *, limit):
        return []

    def study_requests(self, user_id, language_code, *, limit):
        return self.requests[:limit]

    def create_request(self, user_id, language_code, support_language_code, *, kind, item_id, reason):
        self.calls.append(("create_request", user_id, language_code, kind, item_id))
        return self.created

    def grammar_menu(self, user_id, language_code, support_language_code):
        return self.menu


def test_the_profile_brief_is_added_to_the_prompt_for_this_learner_and_language():
    service = make_service()
    service.facts = FakeFacts(brief="LEARNER PROFILE (test)")

    service.start(USER, CompanionEntry.VIDEO, ITEM_ID)

    assert ("profile_brief", OWNER, "en") in service.facts.calls
    assert "LEARNER PROFILE (test)" in service.model.prompts[0] and "<learner>" in service.model.prompts[0]


def test_a_failing_profile_brief_never_fails_the_turn_or_changes_the_prompt():
    plain = make_service()
    plain.start(USER, CompanionEntry.VIDEO, ITEM_ID)
    broken = make_service()

    def explode(user_id, language):
        raise RuntimeError("learner text must not be logged")

    broken.profile_brief = explode
    broken.start(USER, CompanionEntry.VIDEO, ITEM_ID)

    assert broken.model.prompts[0] == plain.model.prompts[0]


def test_without_a_profile_brief_the_prompt_has_no_profile_section():
    service = make_service()
    service.start(USER, CompanionEntry.VIDEO, ITEM_ID)
    assert "LEARNER PROFILE" not in service.model.prompts[0]


def test_the_reply_policy_follows_the_declared_level_and_defaults_to_beginner():
    from app.modules.learning.domain.companion import level_policy, reply_within_policy

    assert level_policy("en").band == "A1" and level_policy("zh").band == "HSK1"
    assert level_policy("en", "B1").band == "B1" and level_policy("en", "B1+").band == "B1"
    assert level_policy("en", "C1").band == "B2" and level_policy("en", "bogus").band == "A1"
    assert level_policy("zh", "HSK3").band == "HSK3" and level_policy("zh", "HSK6").band == "HSK4"
    long_reply = " ".join(["word"] * 25)
    assert not reply_within_policy(long_reply, "en") and reply_within_policy(long_reply, "en", "B1")


def test_the_voice_instruction_uses_the_declared_level_and_only_the_learning_language():
    from app.modules.learning.application.agent.prompts import build_voice_instruction

    declared = build_voice_instruction(mode="open", learning_language="en", topic="", items=[], excerpt=None,
                                       declared_level="B1")
    unknown = build_voice_instruction(mode="open", learning_language="en", topic="", items=[], excerpt=None)
    # PRD 8.12 point 2: the same policy text as the text loop; from B1 only English, below it Vietnamese may explain.
    assert "declared level B1 in English" in declared and "speak only English" in declared
    assert "level is not known" in unknown and "declared level" not in unknown
    assert "You may explain in Vietnamese" in unknown and "You may explain" not in declared
