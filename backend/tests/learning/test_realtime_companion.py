"""The realtime relay - authentication, owner-only switch, limits, relay, checks."""
import asyncio
import base64
import json
import threading
import time
from types import SimpleNamespace
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.bootstrap.wiring.agent import get_voice_agent_service
from app.main import app
from app.modules.learning.application.agent import voice as realtime_module
from app.modules.identity.contracts import CurrentUser
from app.modules.learning.application.agent.ports import DictionarySense, DictionaryWord
from app.modules.learning.application.agent.voice import (
    AudioOut,
    Interrupted,
    VoiceChannel,
    RealtimeGate,
    VoicePolicy,
    RealtimeUnavailable,
    ToolCall,
    TranscriptPiece,
    TurnComplete,
)
from app.modules.learning.domain.companion import CompanionEntry
from app.modules.learning.domain.realtime import (
    RealtimeLimits,
    clean_transcript,
    hint_items,
    transcript_breach,
    valid_audio_frame,
    valid_correction,
    valid_hint,
)
from app.modules.learning.infrastructure.speech.gemini_live import parse_server_message
from tests.learning.test_companion import ITEM_ID, OWNER, make_service

TOKEN = "header.payload.signature"
FRAME = b"\x01\x00" * 1600  # 100 ms of 16 kHz audio


# --- Domain ---------------------------------------------------------------------------------

@pytest.mark.parametrize("reply, language, code", [
    ("Coffee is great! Do you drink it with milk?", "en", None),
    ("我也喜欢喝茶。你喜欢什么茶？", "zh", None),
    ("Great job, your score is ten out of ten!", "en", "grading_claim"),
    ("你得了满分！", "zh", "grading_claim"),
    # "point" is ordinary speech; counted points and a level claimed for the learner are not (PRD principle 3).
    ("Good point! Tell me more.", "en", None),
    ("That grammar point is useful.", "en", None),
    ("This word is B1. Do you know it?", "en", None),
    ("Are you preparing for IELTS?", "en", None),
    ("You got 8 points!", "en", "grading_claim"),
    ("You are B2 level now.", "en", "grading_claim"),
    ("Your IELTS band is 7.", "en", "grading_claim"),
    ("这是HSK1的词。", "zh", None),
    ("你的HSK水平是三级。", "zh", "grading_claim"),
    ("你已经达到HSK3了！", "zh", "grading_claim"),
    ("Neighbour means hàng xóm.", "en", "support_language"),
    ("邻居 línjū 很好。", "zh", "support_language"),
    ("Hello, how are you?", "zh", "wrong_language"),
    ("你好! How are you?", "en", "wrong_language"),
    ("   ", "en", None),
])
def test_transcript_breach(reply, language, code):
    assert transcript_breach(reply, language) == code


def test_audio_frames_are_whole_samples_and_bounded():
    assert valid_audio_frame(FRAME)
    assert not valid_audio_frame(b"")
    assert not valid_audio_frame(b"\x00" * 3)
    assert not valid_audio_frame(b"\x00" * 32002)


def test_provider_messages_map_to_relay_events():
    message = {"serverContent": {
        "modelTurn": {"parts": [{"inlineData": {"mimeType": "audio/pcm;rate=24000",
                                                "data": base64.b64encode(b"\x01\x02").decode()}}]},
        "inputTranscription": {"text": "I like coffee"}, "outputTranscription": {"text": "Nice!"},
        "interrupted": True, "turnComplete": True}}
    events = parse_server_message(message)
    assert events == [AudioOut(pcm=b"\x01\x02", sample_rate=24000), TranscriptPiece("learner", "I like coffee"),
                      TranscriptPiece("companion", "Nice!"), Interrupted(), TurnComplete()]
    assert parse_server_message({"usageMetadata": {"promptTokenCount": 3}}) == []


def test_gate_limits_concurrency_and_daily_seconds():
    gate = RealtimeGate(RealtimeLimits(max_session_seconds=600, daily_seconds_per_learner=900,
                                       max_concurrent_sessions=1),
                        clock=lambda: datetime(2026, 10, 17, tzinfo=UTC))
    assert gate.acquire(OWNER) == 600
    assert gate.acquire(OWNER) is None  # one session at a time
    gate.release(OWNER, 600)
    assert gate.acquire(OWNER) == 300  # what is left today
    gate.release(OWNER, 290)
    assert gate.acquire(OWNER) is None  # under 30 s left


# --- Relay ----------------------------------------------------------------------------------

class FakeChannel:
    def __init__(self, inbound):
        self.inbound: asyncio.Queue = asyncio.Queue()
        for item in inbound:
            self.inbound.put_nowait(item)
        self.json, self.audio, self.closed = [], [], None

    async def receive(self):
        return await self.inbound.get()

    async def send_json(self, message):
        self.json.append(message)

    async def send_bytes(self, data):
        self.audio.append(data)

    async def close(self, code):
        self.closed = code

    def types(self):
        return [message["type"] for message in self.json]


class FakeConnection:
    def __init__(self):
        self.sent, self.events_queue, self.closed = [], asyncio.Queue(), False
        self.tool_responses, self.texts = [], []

    async def send_audio(self, pcm):
        self.sent.append(pcm)

    async def send_tool_response(self, call_id, name, response):
        self.tool_responses.append((call_id, name, response))

    async def send_text(self, text):
        self.texts.append(text)

    async def events(self):
        while True:
            event = await self.events_queue.get()
            if event is None:
                return
            if isinstance(event, Exception):
                raise event
            yield event

    async def close(self):
        self.closed = True


class FakeVoice:
    model_name = "fake-live"

    def __init__(self, fail=False):
        self.connection, self.fail, self.opened = FakeConnection(), fail, []

    async def open(self, *, language_code, instruction, silence_ms):
        if self.fail:
            raise RealtimeUnavailable("down")
        self.opened.append((language_code, instruction, silence_ms))
        return self.connection


class FakeVerifier:
    def verify(self, token):
        if token != TOKEN:
            raise ValueError("bad token")
        return CurrentUser(id=OWNER)


_DEFAULT = object()


class GrantedConsent:
    """The learner's stored voice consent, granted (the server checks it before any voice session)."""

    def has_consent(self, user_id):
        return True


def service(*, voice=_DEFAULT, enabled=True, allowed=(OWNER,), limits=None):
    limits = limits or RealtimeLimits()
    return VoiceChannel(
        setup=make_service(), voice=FakeVoice() if voice is _DEFAULT else voice,
        gate=RealtimeGate(limits), verifier=FakeVerifier(), consent=GrantedConsent(),
        policy=VoicePolicy(enabled=enabled, allowed_user_ids=frozenset(allowed), limits=limits))


def auth(token=TOKEN):
    return ("text", json.dumps({"type": "auth", "token": token}))


def start(**extra):
    return ("text", json.dumps({"type": "start", "entry": "video", "library_item_id": str(ITEM_ID), **extra}))


def run(coroutine):
    return asyncio.run(coroutine)


@pytest.mark.parametrize("inbound, code, error", [
    ([auth("not-a-jwt")], 4401, "authentication_required"),
    ([auth("other.token.value")], 4401, "authentication_required"),
    ([("bytes", FRAME)], 4401, "authentication_required"),
    ([auth(), ("text", '{"type": "start", "entry": "anywhere"}')], 4400, "realtime_start_invalid"),
    ([auth(), ("text", json.dumps({"type": "start", "entry": "video", "library_item_id": str(ITEM_ID),
                                   "user_id": str(uuid4())}))], 4400, "realtime_start_invalid"),
])
def test_refused_before_any_provider_session(inbound, code, error):
    relay = service()
    channel = FakeChannel(inbound)
    run(relay.run(channel))
    assert channel.closed == code and channel.json[-1]["code"] == error
    assert relay.voice.opened == []


def test_only_listed_learners_with_the_switch_on():
    for relay in (service(enabled=False), service(allowed=(uuid4(),)), service(voice=None)):
        channel = FakeChannel([auth(), start()])
        run(relay.run(channel))
        assert channel.closed == 4403 and channel.json[-1]["code"] == "realtime_not_available"


def test_limit_reached_and_wrong_video_are_refused_without_a_provider_session():
    relay = service(limits=RealtimeLimits(max_concurrent_sessions=1))
    relay.gate.acquire(OWNER)  # another session is running
    channel = FakeChannel([auth(), start()])
    run(relay.run(channel))
    assert channel.closed == 4429 and relay.voice.opened == []

    relay = service()
    channel = FakeChannel([auth(), ("text", json.dumps({"type": "start", "entry": "video",
                                                         "library_item_id": str(uuid4())}))])
    run(relay.run(channel))
    assert channel.closed == 4400 and channel.json[-1]["code"] == "companion_video_not_found"
    assert relay.gate.acquire(OWNER) is not None  # the slot was released


def test_provider_failure_is_not_learner_failure():
    relay = service(voice=FakeVoice(fail=True))
    channel = FakeChannel([auth(), start()])
    run(relay.run(channel))
    assert channel.closed == 1011 and channel.json[-1]["code"] == "realtime_unavailable"


def test_a_conversation_relays_audio_and_transcripts_and_ends_with_follow_ups():
    voice = FakeVoice()
    relay = service(voice=voice)
    channel = FakeChannel([auth(), start(day="2026-10-17")])
    ended = []
    relay.setup.end_conversation = lambda user, prepared, history, day: (
        ended.append((user.id, [(m.role, m.text) for m in history], day)) or [])

    async def scenario():
        task = asyncio.create_task(relay.run(channel))
        await asyncio.sleep(0.05)
        assert channel.json[0]["type"] == "ready" and channel.json[0]["input_sample_rate"] == 16000
        assert voice.opened[0][0] == "en" and "the conversation is in English" in voice.opened[0][1]
        await channel.inbound.put(("bytes", FRAME))
        for event in (TranscriptPiece("learner", "I like "), TranscriptPiece("learner", "flying."),
                      AudioOut(pcm=b"\x05\x06", sample_rate=24000),
                      TranscriptPiece("companion", "Flying is fun! Where do you fly?"), TurnComplete()):
            await voice.connection.events_queue.put(event)
        await asyncio.sleep(0.05)
        await channel.inbound.put(("text", '{"type": "end"}'))
        await task

    run(scenario())
    assert voice.connection.sent == [FRAME] and channel.audio == [b"\x05\x06"]
    assert {"type": "audio_format", "sample_rate": 24000, "encoding": "pcm_s16le", "channels": 1} in channel.json
    assert [m for m in channel.json if m["type"] == "transcript"][-1]["text"] == "Flying is fun! Where do you fly?"
    assert channel.types()[-1] == "ended" and channel.json[-1]["reason"] == "learner_ended"
    assert "remembered" not in channel.json[-1] and channel.closed == 1000 and voice.connection.closed
    assert ended[0][1] == [("learner", "I like flying."), ("companion", "Flying is fun! Where do you fly?")]
    assert str(ended[0][2]) == "2026-10-17"


def test_the_blocking_store_calls_of_a_session_run_off_the_event_loop(monkeypatch):
    voice = FakeVoice()
    relay = service(voice=voice)
    loop_thread, threads = threading.get_ident(), {}

    def on(name, inner=None):
        def call(*args, **kwargs):
            threads[name] = threading.get_ident()
            return inner(*args, **kwargs) if inner else True
        return call

    relay.gate.acquire = on("acquire", relay.gate.acquire)
    relay.gate.release = on("release", relay.gate.release)
    relay.learning_log = SimpleNamespace(record=on("log"))
    relay.setup.end_conversation = lambda user, prepared, history, day: []
    budget = SimpleNamespace(allows=on("allows"), reserve=on("reserve"), charge=on("charge"))
    monkeypatch.setattr(realtime_module, "daily_budget", lambda: budget)
    channel = FakeChannel([auth(), start()])

    async def scenario():
        task = asyncio.create_task(relay.run(channel))
        await asyncio.sleep(0.05)
        for event in (TranscriptPiece("learner", "I like flying."),
                      TranscriptPiece("companion", "Flying is fun!"), TurnComplete()):
            await voice.connection.events_queue.put(event)
        await asyncio.sleep(0.05)
        await channel.inbound.put(("text", '{"type": "end"}'))
        await task

    run(scenario())
    assert set(threads) == {"allows", "acquire", "reserve", "release", "charge", "log"}
    assert all(ident != loop_thread for ident in threads.values()), threads


def test_a_policy_breach_ends_the_session():
    voice = FakeVoice()
    relay = service(voice=voice)
    channel = FakeChannel([auth(), start()])

    async def scenario():
        task = asyncio.create_task(relay.run(channel))
        await asyncio.sleep(0.05)
        for event in (TranscriptPiece("companion", "Great, your score is 10/10!"), TurnComplete()):
            await voice.connection.events_queue.put(event)
        await asyncio.wait_for(task, 2)

    run(scenario())
    assert channel.json[-1]["type"] == "ended" and channel.json[-1]["reason"] == "policy"
    assert voice.connection.closed


def test_invalid_audio_and_the_time_limit_end_the_session():
    relay = service()
    channel = FakeChannel([auth(), start(), ("bytes", b"\x00" * 3)])
    run(asyncio.wait_for(relay.run(channel), 2))
    assert channel.json[-1]["reason"] == "invalid_audio"

    relay = service(limits=RealtimeLimits(max_session_seconds=30, daily_seconds_per_learner=1800))
    relay.gate.acquire = lambda user_id: 1  # one second left
    channel = FakeChannel([auth(), start()])
    run(asyncio.wait_for(relay.run(channel), 3))
    assert channel.json[-1]["reason"] == "time_limit"


def test_the_provider_closing_ends_the_session():
    voice = FakeVoice()
    relay = service(voice=voice)
    channel = FakeChannel([auth(), start()])

    async def scenario():
        task = asyncio.create_task(relay.run(channel))
        await asyncio.sleep(0.05)
        await voice.connection.events_queue.put(RealtimeUnavailable("closed"))
        await asyncio.wait_for(task, 2)

    run(scenario())
    assert channel.json[-1]["reason"] == "provider_closed"


# --- WebSocket route --------------------------------------------------------------------------

def test_websocket_route_speaks_the_protocol():
    relay = service()
    app.dependency_overrides[get_voice_agent_service] = lambda: relay
    try:
        with TestClient(app).websocket_connect("/api/v1/v3/learner/me/companion/realtime") as socket:
            socket.send_text(json.dumps({"type": "auth", "token": TOKEN}))
            socket.send_text(json.dumps({"type": "start", "entry": "video", "library_item_id": str(ITEM_ID)}))
            assert socket.receive_json()["type"] == "ready"
            socket.send_bytes(FRAME)
            socket.send_text(json.dumps({"type": "end"}))
            assert socket.receive_json()["type"] == "ended"
        with TestClient(app).websocket_connect("/api/v1/v3/learner/me/companion/realtime") as socket:
            socket.send_text(json.dumps({"type": "auth", "token": "bad"}))
            assert socket.receive_json()["code"] == "authentication_required"
    finally:
        app.dependency_overrides.clear()


# --- G6.3: functions, help, clean transcripts ------------------------------------------------

def test_transcripts_lose_markdown_and_function_arguments_follow_the_turn_contract():
    assert clean_transcript("Yesterday, I **went** to the `market`.") == "Yesterday, I went to the market."
    items = make_service().prepare(CurrentUser(id=OWNER), CompanionEntry.VIDEO, ITEM_ID).ticket.items
    assert [item.text for item in hint_items(["Fly", "airport"], items)] == ["fly", "airport"]
    assert hint_items(["helicopter", "fly"], items) == [items[0]]  # unknown words are dropped
    assert valid_hint(question="Bạn thích đi đâu?", frame="I like ___.", frame_reason="Dùng like.",
                      model_sentence="I like flying.", language_code="en")
    assert not valid_hint(question=None, frame=None, frame_reason=None, model_sentence=None, language_code="en")
    assert not valid_hint(question=None, frame="I like flying.", frame_reason="x", model_sentence=None,
                          language_code="en")  # a frame needs a blank
    assert not valid_hint(question=None, frame=None, frame_reason=None, model_sentence="Bay là fly.",
                          language_code="en")  # Vietnamese in the model sentence
    assert valid_correction(quote="I go", suggestion="I went", note="Thử lại nhé.", learner_said="Yesterday I go there")
    assert not valid_correction(quote="I goes", suggestion="I went", note="x", learner_said="Yesterday I go there")


def test_provider_tool_calls_are_parsed():
    events = parse_server_message({"toolCall": {"functionCalls": [
        {"id": "c1", "name": "show_hint", "args": {"words": ["fly"]}}, {"name": "missing id"}]}})
    assert events == [ToolCall(id="c1", name="show_hint", args={"words": ["fly"]})]


class FakeLookup:
    def __init__(self):
        self.calls = []

    def lookup(self, word, *, language_code):
        self.calls.append((word, language_code))
        return [DictionaryWord(headword="market", senses=(DictionarySense(text="A place to buy food.", part_of_speech="noun"),),
                               source_name="Wiktionary", source_license="CC BY-SA 4.0")]


def test_functions_are_validated_before_the_learner_sees_them():
    voice = FakeVoice()
    relay = service(voice=voice)
    relay.setup.word_lookup = FakeLookup()
    channel = FakeChannel([auth(), start()])

    async def scenario():
        task = asyncio.create_task(relay.run(channel))
        await asyncio.sleep(0.05)
        for event in (
            TranscriptPiece("learner", "Yesterday I go to the market. What does market mean?"),
            ToolCall("1", "show_correction", {"quote": "I go", "suggestion": "I went", "note": "Thử nói lại nhé."}),
            ToolCall("2", "show_correction", {"quote": "I goes", "suggestion": "x", "note": "y"}),
            ToolCall("3", "show_hint", {"words": ["fly", "airport"], "frame": "I like ___.", "frame_reason": "Dùng like.",
                                         "question": "Bạn thích gì?", "model_sentence": "I like flying."}),
            ToolCall("4", "show_hint", {"words": ["helicopter"], "frame": "I like flying."}),  # no blank
            ToolCall("5", "lookup_word", {"word": "market"}),
            ToolCall("6", "lookup_word", {"word": "fly"}),  # an offered item: not looked up
            ToolCall("7", "delete_account", {}),
        ):
            await voice.connection.events_queue.put(event)
        await asyncio.sleep(0.1)
        await channel.inbound.put(("text", '{"type": "end"}'))
        await task

    run(scenario())
    shown = {call_id: response for call_id, _, response in voice.connection.tool_responses}
    assert shown["1"] == {"shown": True} and shown["2"] == {"shown": False}
    assert shown["3"] == {"shown": True, "words_shown": ["fly", "airport"]} and shown["4"]["shown"] is False
    assert shown["5"]["found"] is True and shown["5"]["entries"][0]["headword"] == "market"
    assert shown["6"] == {"found": False} and shown["7"] == {"error": "unknown function"}
    events = [message for message in channel.json if message["type"] in ("correction", "hint", "looked_up")]
    assert [message["type"] for message in events] == ["correction", "hint", "looked_up"]
    assert events[0]["quote"] == "I go" and [item["text"] for item in events[1]["items"]] == ["fly", "airport"]
    assert events[2]["entries"][0]["source_license"] == "CC BY-SA 4.0"
    assert relay.setup.word_lookup.calls == [("market", "en")]


def test_help_asks_the_model_for_a_hint_and_markdown_never_reaches_the_learner():
    voice = FakeVoice()
    relay = service(voice=voice)
    channel = FakeChannel([auth(), start()])

    async def scenario():
        task = asyncio.create_task(relay.run(channel))
        await asyncio.sleep(0.05)
        await channel.inbound.put(("text", '{"type": "help"}'))
        await channel.inbound.put(("text", '{"type": "something else"}'))
        await voice.connection.events_queue.put(TranscriptPiece("companion", "I **went** too."))
        await asyncio.sleep(0.05)
        await channel.inbound.put(("text", '{"type": "end"}'))
        await task

    run(scenario())
    assert len(voice.connection.texts) == 1 and "show_hint" in voice.connection.texts[0]
    assert [m["text"] for m in channel.json if m["type"] == "transcript"] == ["I went too."]


def test_sessions_opened_together_cannot_spend_more_than_the_daily_allowance():
    gate = RealtimeGate(RealtimeLimits(max_session_seconds=600, daily_seconds_per_learner=60,
                                       max_concurrent_sessions=3),
                        clock=lambda: datetime(2026, 10, 17, tzinfo=UTC))
    assert gate.acquire(OWNER) == 60
    assert gate.acquire(OWNER) is None  # the first session already holds the whole allowance
    gate.release(OWNER, 20)
    assert gate.acquire(OWNER) == 40  # only what the first session really used is spent


def test_revoking_consent_during_a_conversation_ends_it_and_stops_the_audio(monkeypatch):
    monkeypatch.setattr(realtime_module, "CONSENT_RECHECK_S", 0.02)
    consent = type("Consent", (), {"granted": True, "has_consent": lambda self, user_id: self.granted})()
    voice = FakeVoice()
    relay = service(voice=voice)
    relay.consent = consent
    channel = FakeChannel([auth(), start()])

    async def scenario():
        task = asyncio.create_task(relay.run(channel))
        await asyncio.sleep(0.05)
        await channel.inbound.put(("bytes", FRAME))
        await asyncio.sleep(0.05)
        consent.granted = False
        await asyncio.wait_for(task, 2)

    run(scenario())
    assert voice.connection.sent == [FRAME] and voice.connection.closed
    assert channel.json[-1]["type"] == "ended" and channel.json[-1]["reason"] == "consent_revoked"


def test_a_revoked_consent_stops_scoring_the_turn_in_progress(monkeypatch):
    monkeypatch.setattr(realtime_module, "CONSENT_RECHECK_S", 0.01)
    relay = service()
    relay.consent = type("Consent", (), {"has_consent": lambda self, user_id: False})()
    session = SimpleNamespace(user=CurrentUser(id=OWNER), end_reason=None, score_speech=True)
    run(asyncio.wait_for(relay._watch_consent(session), 2))
    assert session.score_speech is False and session.end_reason == "consent_revoked"


def test_a_slow_dictionary_does_not_hold_up_the_conversation(monkeypatch):
    from app.modules.learning.application.agent import tools as tools_module
    monkeypatch.setattr(tools_module, "LOOKUP_TIMEOUT_S", 0.05)
    relay = service()
    relay.setup.word_lookup = SimpleNamespace(lookup=lambda word, *, language_code: time.sleep(1) or [])
    session = _tool_session()
    session.learner_turn = ["what does market mean"]

    async def scenario():
        began = time.monotonic()
        result = await relay.tools.call(session, "lookup_word", {"word": "market"})
        return result.response, time.monotonic() - began

    response, took = run(scenario())
    assert response == {"found": False} and took < 0.5


def _tool_session():
    from app.modules.learning.application.agent.session import AgentSession
    ticket = SimpleNamespace(items=[], language_code="en", support_language_code="vi", scenario_id=None,
                             region_lines=(), excerpt=None, region_id=None)
    return AgentSession(user=CurrentUser(id=OWNER), prepared=SimpleNamespace(ticket=ticket))


def handle(relay, channel, session, call):
    """One function call as the relay handles it: events to the learner, the response to the model."""
    async def scenario():
        result = await relay.tools.call(session, call.name, call.args)
        for event in result.events:
            await channel.send_json(event)
        return result.response
    return run(scenario())


def test_the_agent_shows_todays_tasks_once():
    relay = service()
    relay.tasks = lambda user, day: [{"kind": "review"}]
    session, channel = _tool_session(), FakeChannel([])
    first = handle(relay, channel, session, ToolCall("1", "show_tasks", {}))
    second = handle(relay, channel, session, ToolCall("2", "show_tasks", {}))
    assert first == {"shown": True, "tasks": ["review"]} and second == {"shown": False}
    assert channel.json == [{"type": "tasks", "items": [{"kind": "review"}]}]


def test_tasks_that_could_not_be_read_can_be_shown_on_a_later_call():
    relay = service()
    answers = [RuntimeError("down"), [{"kind": "review"}]]

    def tasks(user, day):
        value = answers.pop(0)
        if isinstance(value, Exception):
            raise value
        return value

    relay.tasks = tasks
    session, channel = _tool_session(), FakeChannel([])
    assert handle(relay, channel, session, ToolCall("1", "show_tasks", {})) == {"shown": False}
    assert handle(relay, channel, session, ToolCall("2", "show_tasks", {})) == {"shown": True, "tasks": ["review"]}


def test_a_roleplay_starts_inside_the_conversation_and_unknown_ones_do_not():
    relay = service()
    session, channel = _tool_session(), FakeChannel([])
    started = handle(relay, channel, session, ToolCall("1", "start_roleplay", {"scenario": "hotel"}))
    assert started["started"] is True and "ROLEPLAY" in started["instruction"]
    assert channel.json[0]["type"] == "roleplay" and session.mode == "roleplay"
    refused = handle(relay, channel, session, ToolCall("2", "start_roleplay", {"scenario": "nope"}))
    assert refused == {"started": False} and len(channel.json) == 1


def test_only_known_activities_are_offered():
    relay = service()
    session, channel = _tool_session(), FakeChannel([])
    assert handle(relay, channel, session, ToolCall("1", "offer_activity", {"kind": "grammar"})) == {"shown": True}
    assert handle(relay, channel, session, ToolCall("2", "offer_activity", {"kind": "payments"})) == {"shown": False}
    assert channel.json == [{"type": "offer", "kind": "grammar"}]


# --- Provider markers are not speech ----------------------------------------------------------

@pytest.mark.parametrize("raw, shown", [
    ("<no speech>{pause}", ""), ("<noise>", ""), ("  {pause} ", ""), ("[Silence]", ""),
    ("Hello <noise> there", "Hello  there"), ("I like it.", "I like it."), ("3 < 5 and 7 > 4", "3 < 5 and 7 > 4"),
])
def test_provider_markers_never_become_text(raw, shown):
    assert clean_transcript(raw) == shown


def test_a_silence_marker_makes_no_line_and_no_turn_even_when_it_arrives_in_pieces():
    voice = FakeVoice()
    relay = service(voice=voice)
    channel = FakeChannel([auth(), start()])

    async def scenario():
        task = asyncio.create_task(relay.run(channel))
        await asyncio.sleep(0.05)
        for event in (TranscriptPiece("companion", "<no speech>{pause}"), TranscriptPiece("learner", "<noi"),
                      TranscriptPiece("learner", "se>"), TranscriptPiece("companion", "<no sp"),
                      TranscriptPiece("companion", "eech>{pause}"), TurnComplete(),
                      TranscriptPiece("learner", "I like it."), TurnComplete()):
            await voice.connection.events_queue.put(event)
        await asyncio.sleep(0.05)
        await channel.inbound.put(("text", '{"type": "end"}'))
        await task

    run(scenario())
    assert [(m["role"], m["text"]) for m in channel.json if m["type"] == "transcript"] == [("learner", "I like it.")]
    assert channel.json[-1]["summary"]["spoken_turns"] == 1


# --- Opening without a topic: the agent asks and offers choices, it picks nothing ----------------

def home(**extra):
    return ("text", json.dumps({"type": "start", "entry": "home", **extra}))


def open_session(inbound_after=(), *, start_message=None, voice=None):
    voice = voice or FakeVoice()
    relay = service(voice=voice)
    channel = FakeChannel([auth(), start_message or home()])

    async def scenario():
        task = asyncio.create_task(relay.run(channel))
        await asyncio.sleep(0.05)
        for message in inbound_after:
            await channel.inbound.put(("text", json.dumps(message)))
            await asyncio.sleep(0.02)
        await channel.inbound.put(("text", '{"type": "end"}'))
        await task

    run(scenario())
    return voice, channel


def test_opening_from_home_asks_what_the_learner_wants_and_offers_choices():
    voice, channel = open_session()
    instruction = voice.opened[0][1]
    assert "has not chosen what to talk about" in instruction and "Do not pick a topic" in instruction
    assert "Start from this topic" not in instruction and "show_tasks" not in instruction
    ready, choices = channel.json[0], channel.json[1]
    assert ready["type"] == "ready" and ready["mode"] == "open"
    assert choices["type"] == "choices" and {"roleplay", "free"} <= {item["id"] for item in choices["items"]}


def test_a_video_topic_or_roleplay_start_is_not_an_open_start():
    voice, channel = open_session()
    assert "choices" in channel.types()
    voice, channel = open_session(start_message=start())
    assert "choices" not in channel.types() and "has not chosen" not in voice.opened[0][1]


def test_tapping_a_choice_cues_the_agent_once_and_an_unknown_choice_does_nothing():
    voice, channel = open_session([{"type": "choose", "id": "bogus"}, {"type": "choose", "id": "free"},
                                   {"type": "choose", "id": "roleplay"}])
    assert len(voice.connection.texts) == 1 and "do not pick one" in voice.connection.texts[0]


def test_nothing_is_hinted_while_the_learner_has_not_chosen(monkeypatch):
    monkeypatch.setattr(realtime_module, "SCAFFOLD_TICK_S", 0.01)
    voice = FakeVoice()
    relay = service(voice=voice)
    channel = FakeChannel([auth(), home()])

    async def scenario():
        task = asyncio.create_task(relay.run(channel))
        await asyncio.sleep(0.05)
        await voice.connection.events_queue.put(TranscriptPiece("companion", "Hi! What would you like to do today?"))
        await voice.connection.events_queue.put(TurnComplete())
        await asyncio.sleep(0.1)
        await channel.inbound.put(("text", '{"type": "end"}'))
        await task

    relay.monotonic = iter(range(0, 10_000, 10)).__next__  # every clock read is ten seconds later
    run(scenario())
    assert voice.connection.texts == []
