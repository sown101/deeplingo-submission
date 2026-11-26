"""The agent harness (plan phases 1-2): one core behind both channels, and how tool calls run."""
import asyncio
from types import SimpleNamespace

from app.modules.identity.contracts import CurrentUser
from app.modules.learning.application.agent.core import MAX_SESSION_TOOL_CALLS, MAX_TOOL_CALLS, AgentCore
from app.modules.learning.application.agent.tools import TOOL_SPECS, ToolRegistry
from app.modules.learning.application.agent.voice import ToolCall, VoiceSession
from tests.learning.test_realtime_companion import OWNER, FakeChannel, FakeConnection, service


def voice_session():
    ticket = SimpleNamespace(items=[], language_code="en", support_language_code="vi", scenario_id=None,
                             region_lines=(), excerpt=None, region_id=None)
    return VoiceSession(user=CurrentUser(id=OWNER), prepared=SimpleNamespace(ticket=ticket))


def voice_call(relay, session, call, connection=None):
    connection = connection or FakeConnection()
    asyncio.run(relay._tool_call(FakeChannel([]), connection, session, call))
    return connection.tool_responses[-1][2]


# --- Phase 1: the voice channel obeys the text channel's tool rules -------------------------

def test_voice_refuses_a_function_it_was_never_offered():
    # suggest_practice exists in the registry for the text channel only; Live was not declared it.
    response = voice_call(service(), voice_session(), ToolCall("1", "suggest_practice", {"tool": "dictation"}))
    assert response == {"error": "unknown function"}


def test_voice_limits_the_calls_of_one_agent_turn_and_a_new_turn_starts_again():
    relay, session = service(), voice_session()
    responses = [voice_call(relay, session, ToolCall(str(n), "offer_activity", {"kind": "review"}))
                 for n in range(MAX_TOOL_CALLS + 1)]
    assert responses[-1] == {"error": "too many calls"} and responses[0] == {"shown": True}
    AgentCore.begin_turn(session)
    assert voice_call(relay, session, ToolCall("x", "offer_activity", {"kind": "review"})) == {"shown": True}


def test_a_whole_conversation_has_a_call_budget():
    relay, session = service(), voice_session()
    session.tool_calls = MAX_SESSION_TOOL_CALLS
    assert voice_call(relay, session, ToolCall("1", "offer_activity", {"kind": "review"})) == {
        "error": "too many calls"}


def test_both_channels_check_replies_with_one_rule():
    session = voice_session()
    assert AgentCore.voice_reply(session, "Great job, you scored 9 out of 10!").breach == "grading_claim"
    assert AgentCore.text_reply_note(session, "Great job, you scored 9 out of 10!").startswith("(Never give")


def test_the_core_offers_only_its_specs():
    core = AgentCore(ToolRegistry(), [spec for spec in TOOL_SPECS if spec.name == "offer_activity"])
    result = asyncio.run(core.call(voice_session(), "show_tasks", {}))
    assert result.response == {"error": "unknown function"}


# --- Phase 2: how calls run ------------------------------------------------------------------

class SlowRegistry:
    """A registry whose calls take a while and record when they ran."""

    def __init__(self, delay=0.2, hang=()):
        self.delay, self.hang, self.started, self.calls = delay, set(hang), [], []

    async def call(self, session, name, args):
        self.calls.append(name)
        self.started.append(asyncio.get_running_loop().time())
        await asyncio.sleep(60 if name in self.hang else self.delay)
        from app.modules.learning.application.agent.tools import ToolResult
        return ToolResult({"found": True, "name": name}, [{"type": "x", "name": name}])


def specs(*names):
    return [spec for spec in TOOL_SPECS if spec.name in names]


def test_reads_of_one_batch_run_at_once():
    registry = SlowRegistry(delay=0.2)
    core = AgentCore(registry, specs("get_region", "get_due_cards", "get_study_requests"))

    async def batch():
        loop = asyncio.get_running_loop()
        began = loop.time()
        results = await core.run_calls(voice_session(), [("get_region", {}), ("get_due_cards", {}),
                                                         ("get_study_requests", {})])
        return results, loop.time() - began

    results, took = asyncio.run(batch())
    assert [result.response["name"] for result in results] == ["get_region", "get_due_cards", "get_study_requests"]
    assert took < 0.45  # three 0.2 s reads together, not one after another


def test_a_repeated_call_in_a_batch_runs_once_and_shows_nothing_again():
    registry = SlowRegistry(delay=0)
    session = voice_session()
    core = AgentCore(registry, specs("get_region"))
    results = asyncio.run(core.run_calls(session, [("get_region", {}), ("get_region", {})]))
    assert registry.calls == ["get_region"]
    assert results[1].response == results[0].response and results[1].events == []
    assert session.tool_calls == 2  # the repeat still counts against the limits


def test_a_read_that_misses_its_deadline_is_tried_once_more_and_an_action_never():
    registry = SlowRegistry(hang={"get_region", "edit_today"})
    core = AgentCore(registry, specs("get_region", "edit_today"))
    core.timeout_s = 0.05
    session = voice_session()
    read = asyncio.run(core.call(session, "get_region", {}))
    action = asyncio.run(core.call(session, "edit_today", {"change": "add", "kind": "review"}))
    assert registry.calls == ["get_region", "get_region", "edit_today"]
    assert read.response["error"] == "timeout" and action.response["error"] == "timeout"


def test_a_call_refused_for_a_missing_argument_says_which_one_and_its_shape():
    core = AgentCore(ToolRegistry(), specs("create_study_request"))
    result = asyncio.run(core.call(voice_session(), "create_study_request", {"kind": "word_review"}))
    assert result.response["created"] is False  # the tool's own answer is kept
    assert result.response["missing"] == ["item"] and "item" in result.response["expected"]
    assert "again" in result.response["note"]


def test_a_tool_that_gives_its_own_reason_is_left_as_it_is():
    core = AgentCore(ToolRegistry(), specs("show_hint"))
    result = asyncio.run(core.call(voice_session(), "show_hint", {"words": []}))
    assert result.response == {"shown": False, "reason": "question is required"}


# --- Phase 3: a Live session outlives one provider connection --------------------------------

from app.modules.learning.application.agent.realtime_port import (  # noqa: E402
    GoAway, RealtimeUnavailable, ResumptionUpdate, TranscriptPiece, TurnComplete,
)
from app.modules.learning.infrastructure.speech.gemini_live import parse_server_message  # noqa: E402
from tests.learning.test_realtime_companion import auth, start  # noqa: E402


class ResumingVoice:
    """Opens a new fake connection each time; remembers the handle each was opened with."""
    model_name = "fake-live"

    def __init__(self, fail_resume=False):
        self.connections, self.handles, self.fail_resume = [], [], fail_resume

    async def open(self, *, language_code, instruction, silence_ms, resume_handle=None):
        if resume_handle and self.fail_resume:
            raise RealtimeUnavailable("down")
        connection = FakeConnection()
        self.connections.append(connection)
        self.handles.append(resume_handle)
        return connection


def resuming_session(steps, voice=None):
    """A conversation whose provider sends `steps`: events, or ("next", event) for the newest connection."""
    voice = voice or ResumingVoice()
    relay = service(voice=voice)
    channel = FakeChannel([auth(), start()])

    async def scenario():
        task = asyncio.create_task(relay.run(channel))
        await asyncio.sleep(0.05)
        for step in steps:
            target = voice.connections[-1]
            await target.events_queue.put(step)
            await asyncio.sleep(0.05)
        if not task.done():
            await channel.inbound.put(("text", '{"type": "end"}'))
        await asyncio.wait_for(task, 3)

    asyncio.run(scenario())
    return voice, channel


def test_the_provider_messages_for_resuming_are_read():
    events = parse_server_message({"sessionResumptionUpdate": {"newHandle": "h-1", "resumable": True},
                                   "goAway": {"timeLeft": "9.5s"}})
    assert events == [ResumptionUpdate(handle="h-1", resumable=True), GoAway(time_left_ms=9500)]


def test_go_away_continues_the_same_session_on_a_new_connection():
    voice, channel = resuming_session([
        ResumptionUpdate(handle="h-1", resumable=True),
        GoAway(time_left_ms=5000),
        TranscriptPiece("companion", "Where were we? You like flying."), TurnComplete(),
    ])
    assert voice.handles == [None, "h-1"] and voice.connections[0].closed
    assert "resumed" in channel.types()
    lines = [message["text"] for message in channel.json if message["type"] == "transcript"]
    assert lines == ["Where were we? You like flying."]
    assert channel.json[-1]["type"] == "ended" and channel.json[-1]["reason"] == "learner_ended"


def test_a_dropped_connection_is_resumed_with_the_latest_handle():
    voice, channel = resuming_session([
        ResumptionUpdate(handle="h-1", resumable=True), ResumptionUpdate(handle="h-2", resumable=True),
        ResumptionUpdate(handle=None, resumable=False),  # mid-turn: the last good handle is kept
        RealtimeUnavailable("network"),
    ])
    assert voice.handles == [None, "h-2"] and channel.json[-1]["reason"] == "learner_ended"


def test_without_a_handle_or_when_resuming_fails_the_session_ends_as_before():
    _, channel = resuming_session([RealtimeUnavailable("network")])
    assert channel.json[-1]["reason"] == "provider_closed"
    _, channel = resuming_session([ResumptionUpdate(handle="h-1", resumable=True), GoAway()],
                                  voice=ResumingVoice(fail_resume=True))
    assert channel.json[-1]["reason"] == "provider_closed"


# --- Phase 3: the learner's socket can drop and come back --------------------------------------

import json  # noqa: E402

from app.modules.learning.application.agent import client_resume  # noqa: E402
from tests.learning.test_realtime_companion import FakeVoice  # noqa: E402


def resume_message(session_id, last_seq):
    return ("text", json.dumps({"type": "resume", "session_id": session_id, "last_seq": last_seq}))


def test_a_dropped_socket_is_taken_over_by_a_new_one_with_the_missed_events():
    voice = FakeVoice()
    relay = service(voice=voice)
    first = FakeChannel([auth(), start()])

    async def scenario():
        task = asyncio.create_task(relay.run(first))
        await asyncio.sleep(0.05)
        session_id = first.json[0]["session_id"]
        seen = len(first.json)
        await first.inbound.put(("closed", None))  # the network drops the learner's socket
        await asyncio.sleep(0.02)
        await voice.connection.events_queue.put(TranscriptPiece("companion", "Are you still there?"))
        await asyncio.sleep(0.05)
        second = FakeChannel([auth(), resume_message(session_id, seen)])
        # The API builds a new channel object for every WebSocket (no cached dependency): it must still find it.
        reattached = asyncio.create_task(service(voice=voice).run(second))
        await asyncio.sleep(0.05)
        await voice.connection.events_queue.put(TurnComplete())
        await asyncio.sleep(0.05)
        await second.inbound.put(("text", '{"type": "end"}'))
        await asyncio.wait_for(task, 3)
        await asyncio.wait_for(reattached, 3)
        return second

    second = asyncio.run(scenario())
    assert second.json[0] == {"type": "transcript", "role": "companion", "text": "Are you still there?"}
    assert second.types()[-1] == "ended" and second.json[-1]["reason"] == "learner_ended"


def test_only_the_same_learner_can_take_over_a_running_session():
    relay = service()
    channel = FakeChannel([auth(), resume_message(str(OWNER), 0)])
    asyncio.run(relay.run(channel))
    assert channel.closed == 4404 and channel.json[-1]["code"] == "realtime_session_gone"


def test_without_a_new_socket_the_session_ends_after_the_grace_period(monkeypatch):
    monkeypatch.setattr(client_resume, "REATTACH_GRACE_S", 0.1)
    relay = service()
    channel = FakeChannel([auth(), start(), ("closed", None)])

    async def scenario():
        await asyncio.wait_for(relay.run(channel), 3)

    asyncio.run(scenario())
    assert relay.live == {}


# --- Phase 4: the text turn is sent as soon as the agent answers; its speech follows ------------

from fastapi.testclient import TestClient  # noqa: E402

from app.bootstrap.wiring.identity import get_jwt_verifier  # noqa: E402
from app.bootstrap.wiring.speaking import get_companion_service, get_speaking_rate_limiter  # noqa: E402
from app.main import app  # noqa: E402
from app.modules.learning.application.agent.text import speech_parts  # noqa: E402
from app.modules.learning.domain.companion import CompanionEntry  # noqa: E402
from app.platform.rate_limit import SlidingWindowLimiter  # noqa: E402
from tests.learning.test_companion import ITEM_ID, USER, make_service, turn_output  # noqa: E402


def test_a_reply_is_spoken_in_natural_parts():
    assert speech_parts("Yes! I went to the market yesterday. What did you buy there?", "en") == [
        "Yes! I went to the market yesterday.", "What did you buy there?"]
    assert speech_parts("好！我昨天去了市场。你买了什么？", "zh") == ["好！我昨天去了市场。", "你买了什么？"]
    assert speech_parts("Hello there", "en") == ["Hello there"]
    assert speech_parts("Hi. Ok.", "en") == ["Hi. Ok."]  # too short to cut


def test_the_stream_sends_the_turn_first_then_each_sentence_of_speech():
    reply = "That sounds great. Where did you fly last year?"
    service = make_service(outputs=(turn_output(), turn_output(reply=reply)))
    app.dependency_overrides[get_companion_service] = lambda: service
    app.dependency_overrides[get_jwt_verifier] = lambda: SimpleNamespace(verify=lambda token: CurrentUser(id=OWNER))
    app.dependency_overrides[get_speaking_rate_limiter] = lambda: SlidingWindowLimiter({"companion_turn": (100, 60.0)})
    try:
        ticket = service.start(USER, CompanionEntry.VIDEO, ITEM_ID).session_ticket
        service.synthesizer.calls.clear()
        response = TestClient(app).post("/api/v1/v3/learner/me/companion/turns/stream",
                                        data={"session_ticket": ticket, "text": "I love flying"},
                                        headers={"Authorization": "Bearer a.b.c"})
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200 and response.headers["content-type"].startswith("application/x-ndjson")
    lines = [json.loads(line) for line in response.text.splitlines()]
    assert [line["type"] for line in lines] == ["turn", "audio", "audio", "done"]
    turn = lines[0]["turn"]
    assert turn["reply"] == reply and turn["audio"] is None and turn["audio_status"] == "streaming"
    assert [call[0] for call in service.synthesizer.calls] == ["That sounds great.", "Where did you fly last year?"]
    assert lines[1]["audio"]["mime_type"] == "audio/mpeg" and lines[1]["index"] == 0


def test_a_failed_stream_turn_is_an_ordinary_error():
    service = make_service(outputs=(turn_output(),))
    app.dependency_overrides[get_companion_service] = lambda: service
    app.dependency_overrides[get_jwt_verifier] = lambda: SimpleNamespace(verify=lambda token: CurrentUser(id=OWNER))
    app.dependency_overrides[get_speaking_rate_limiter] = lambda: SlidingWindowLimiter({"companion_turn": (100, 60.0)})
    try:
        response = TestClient(app).post("/api/v1/v3/learner/me/companion/turns/stream",
                                        data={"session_ticket": "not-a-ticket", "text": "hi"},
                                        headers={"Authorization": "Bearer a.b.c"})
    finally:
        app.dependency_overrides.clear()
    assert response.status_code in (409, 410, 422) and response.json()["detail"]["code"]


# --- Phase 5: notes with evidence, brought up to date after a conversation ----------------------

from uuid import UUID, uuid4  # noqa: E402

from app.modules.learning.application.agent.context import memory_block  # noqa: E402
from app.modules.learning.application.agent.memory_consolidation import (  # noqa: E402
    KeptTurnText, MemoryConsolidator, _Proposal,
)
from app.modules.learning.infrastructure.agent_memory import AgentMemoryRepository  # noqa: E402
from tests.learning.test_agent_memory import FakeClient  # noqa: E402

SESSION = uuid4()
TURNS = [KeptTurnText(0, "I want to work in a hotel in Da Nang next year."),
         KeptTurnText(1, "Yesterday I go to the beach and I go swimming."),
         KeptTurnText(2, "I love football very much.")]


class NotesModel:
    def __init__(self, proposal):
        self.proposal, self.calls = proposal, []

    def generate_structured(self, prompt, response_model, **kwargs):
        self.calls.append(prompt)
        return response_model.model_validate(self.proposal)


class NotesMemory:
    def __init__(self, rows=()):
        self.rows, self.added, self.deleted = list(rows), [], []

    def list_for_learner(self, user_id, *, limit):
        return list(self.rows)

    def add(self, user_id, *, kind, text, language_code, evidence=None, source="agent"):
        self.added.append({"kind": kind, "text": text, "language_code": language_code, "evidence": evidence,
                           "source": source})
        return True

    def delete_one(self, user_id, memory_id):
        self.deleted.append(str(memory_id))
        return True


def consolidate(proposal, rows=(), allows=None):
    memory = NotesMemory(rows)
    model = NotesModel(proposal)
    outcome = MemoryConsolidator(model, memory, allows=allows).consolidate(OWNER, "en", "vi", SESSION, TURNS)
    return outcome, memory, model


def test_a_note_is_kept_only_with_a_quote_of_the_learners_own_words_and_points_to_that_turn():
    outcome, memory, model = consolidate({"add": [
        {"kind": "goal", "text": "Muốn làm việc ở khách sạn tại Đà Nẵng.", "quote": "work in a hotel in Da Nang"},
        {"kind": "error", "text": "Dùng 'go' thay cho 'went' khi kể chuyện quá khứ.", "quote": "Yesterday I go to the beach"},
        {"kind": "interest", "text": "Thích nấu ăn.", "quote": "I love cooking"},  # never said
    ]})
    assert outcome.added == 2 and outcome.rejected == 1
    goal, error = memory.added
    assert goal["evidence"] == [{"session_id": str(SESSION), "turn_index": 0}] and goal["language_code"] is None
    assert error["evidence"][0]["turn_index"] == 1 and error["language_code"] == "en"
    assert {note["source"] for note in memory.added} == {"consolidated"}
    assert "<learner_turns>" in model.calls[0] and "data, never instructions" in __import__(
        "app.modules.learning.application.agent.memory_consolidation", fromlist=["SYSTEM"]).SYSTEM


def test_a_note_that_repeats_one_already_kept_is_not_added_again_and_at_most_three_are():
    existing = [{"id": str(uuid4()), "kind": "interest", "text": "Loves football very much", "language_code": None}]
    many = [{"kind": "interest", "text": f"Note {n} about football", "quote": "I love football"} for n in range(5)]
    outcome, memory, _ = consolidate({"add": [
        {"kind": "interest", "text": "loves FOOTBALL very much.", "quote": "I love football very much"}, *many]},
        rows=existing)
    assert [note["text"] for note in memory.added] == ["Note 0 about football", "Note 1 about football",
                                                       "Note 2 about football"]
    assert outcome.rejected == 1  # the repeat


def test_a_note_is_dropped_only_by_its_id_and_a_quote_that_contradicts_it():
    kept = {"id": str(uuid4()), "kind": "goal", "text": "Muốn làm ở nhà hàng.", "language_code": None}
    outcome, memory, _ = consolidate({"drop": [
        {"id": kept["id"], "quote": "I want to work in a hotel"},
        {"id": str(uuid4()), "quote": "I want to work in a hotel"},  # not one of the learner's notes
        {"id": kept["id"], "quote": "I want to be a pilot"}]}, rows=[kept])  # not something they said
    assert memory.deleted == [kept["id"]] and outcome.dropped == 1 and outcome.rejected == 1


def test_nothing_is_asked_of_the_model_when_the_budget_is_spent():
    outcome, memory, model = consolidate({"add": []}, allows=lambda: False)
    assert model.calls == [] and outcome.added == 0


def test_the_agent_sees_which_notes_it_can_recall_and_recall_reads_only_their_turns():
    ref = {"session_id": str(SESSION), "turn_index": 1}
    rows = ({"id": "m1", "kind": "error", "text": "Says go for went.", "evidence": [ref]},
            {"id": "m2", "kind": "goal", "text": "Hotel job."})
    block = memory_block(rows)
    assert "- m1 error: Says go for went. (recall)" in block.splitlines()
    assert "- m2 goal: Hotel job." in block.splitlines()  # no evidence: nothing to recall

    class Transcripts:
        def __init__(self):
            self.asked = []

        def recall(self, user_id, refs):
            self.asked.append((user_id, refs))
            return [{"said": "Yesterday I go <b>to</b> the beach", "you_said": "What did you do?", "when": "2026-11-20"}]

    transcripts = Transcripts()
    session = voice_session()
    session.context = SimpleNamespace(memory=rows)
    tools = ToolRegistry(transcripts=transcripts)
    found = asyncio.run(tools.call(session, "recall", {"id": "m1"})).response
    assert transcripts.asked == [(OWNER, [(UUID(str(SESSION)), 1)])]
    assert found["found"] is True and found["turns"][0]["learner_said"].count("<") == 0
    assert asyncio.run(tools.call(session, "recall", {"id": "m2"})).response == {"found": False}
    assert asyncio.run(tools.call(session, "recall", {"id": "other"})).response == {"found": False}
    assert asyncio.run(ToolRegistry().call(session, "recall", {"id": "m1"})).response == {"found": False}


def test_the_repository_stores_evidence_and_falls_back_where_the_new_function_is_missing():
    client = FakeClient(added=str(uuid4()))
    memory = AgentMemoryRepository(client)
    evidence = [{"session_id": str(SESSION), "turn_index": 0}]
    assert memory.add(OWNER, kind="goal", text="Hotel job.", language_code=None, evidence=evidence,
                      source="consolidated") is True
    assert client.calls[0][0] == "add_agent_memory_with_evidence"
    assert client.calls[0][1]["p_evidence"] == evidence and client.calls[0][1]["p_source"] == "consolidated"

    class OldDatabase(FakeClient):
        def rpc(self, name, params):
            if name == "add_agent_memory_with_evidence":
                raise RuntimeError("function does not exist")
            return super().rpc(name, params)

    old = OldDatabase(added=str(uuid4()))
    assert AgentMemoryRepository(old).add(OWNER, kind="goal", text="Hotel job.", language_code=None,
                                          evidence=evidence) is True
    assert [name for name, _ in old.calls] == ["add_agent_memory"]


def test_a_proposal_keeps_its_shape():
    assert _Proposal.model_validate({}).add == [] and _Proposal.model_validate({}).drop == []


def test_a_voice_session_with_kept_turns_hands_them_to_the_consolidator():
    class Later:
        def __init__(self):
            self.calls = []

        def later(self, user_id, **kwargs):
            self.calls.append((user_id, kwargs))

    class Keeper:
        def keep(self, user_id, **kwargs):
            return len(kwargs["turns"])

    from datetime import UTC, datetime

    from app.modules.learning.application.agent.voice import KeptTurn
    relay = service()
    relay.transcripts, relay.consolidator = Keeper(), Later()
    session = voice_session()
    session.prepared.ticket.library_item_id, session.prepared.ticket.topic = None, "Travel"
    session.kept_turns = [KeptTurn(turn_index=0, learner_text="I want a hotel job.", agent_text="Why English?",
                                   assistance_level=0, occurred_at=datetime.now(UTC))]
    asyncio.run(relay._keep_transcripts(session))
    [(user_id, call)] = relay.consolidator.calls
    assert user_id == OWNER and call["session_id"] == session.id
    assert call["turns"] == [KeptTurnText(0, "I want a hotel job.")]



# --- Phase 6: the agent hears how the learner is doing ------------------------------------------

from app.modules.learning.application.agent import pace  # noqa: E402
from app.modules.learning.application.agent.realtime_resume import ResumableConnection  # noqa: E402


def test_delivery_rises_after_turns_said_alone_and_drops_at_once_when_the_learner_struggles():
    session = voice_session()
    long_turn = "Last summer I travelled to Japan with my family and we ate so much sushi."
    assert pace.observe(session, "I went to the market yesterday.", "en", stalled=False, helped=False) is None
    assert pace.observe(session, "I bought apples and some bread.", "en", stalled=False, helped=False) is None
    assert session.pace == "natural"  # the start was natural: nothing to say
    assert pace.observe(session, long_turn, "en", stalled=False, helped=False) is None
    assert pace.observe(session, long_turn, "en", stalled=False, helped=False) == "extended"
    assert pace.observe(session, "um", "en", stalled=True, helped=False) == "gentle"
    assert pace.observe(session, "Yes.", "en", stalled=False, helped=False) is None  # too short to count
    assert pace.observe(session, "I like it a lot", "en", stalled=False, helped=False) is None
    assert pace.observe(session, "My sister likes it too", "en", stalled=False, helped=False) == "natural"
    assert "Never read this note aloud" in pace.pace_note("gentle")


def test_the_text_channel_tells_the_agent_when_the_delivery_changes():
    service = make_service(outputs=(turn_output(), turn_output(), turn_output()))
    ticket = service.start(USER, CompanionEntry.VIDEO, ITEM_ID).session_ticket
    helped = service.turn(USER, ticket, text="I like fly", request="hint")
    assert "Delivery for your next replies" in service.model.calls[-1][0][-1]["content"]
    after = service.turn(USER, helped.session_ticket, text="Yes")
    assert "Delivery" not in service.model.calls[-1][0][-1]["content"]  # unchanged: said once
    assert service.load(USER, after.session_ticket).pace == "gentle"  # kept between requests


def test_voice_sends_the_note_as_context_that_does_not_start_a_reply():
    class Inner(FakeConnection):
        def __init__(self):
            super().__init__()
            self.notes = []

        async def send_context(self, text):
            self.notes.append(text)

    inner = Inner()
    connection = ResumableConnection(None, inner, open_args={})
    asyncio.run(connection.send_context("(Delivery ...)"))
    assert inner.notes == ["(Delivery ...)"] and inner.texts == []
    plain = FakeConnection()
    asyncio.run(ResumableConnection(None, plain, open_args={}).send_context("(Delivery ...)"))
    assert plain.texts == []  # no way to add a note without a reply: none is sent



# --- Phase 7: a score is shown only for a recording that can carry one ----------------------------

import math as _math  # noqa: E402
import struct as _struct  # noqa: E402

from app.modules.learning.domain.speech_audio import SpeechAudio, audio_quality_issues  # noqa: E402


def tone(amplitude, seconds=1.5, rate=16_000):
    samples = [int(amplitude * _math.sin(2 * _math.pi * 220 * n / rate)) for n in range(int(seconds * rate))]
    return SpeechAudio(_struct.pack(f"<{len(samples)}h", *samples))


def test_a_clear_recording_can_be_scored_and_a_poor_one_cannot():
    assert audio_quality_issues(tone(8000)) == []
    assert "too_quiet" in audio_quality_issues(tone(150))
    assert "clipped" in audio_quality_issues(tone(32767))
    assert "too_short" in audio_quality_issues(tone(8000, seconds=0.3))
    assert audio_quality_issues(SpeechAudio(b"")) == ["too_short"]



# --- A long text conversation keeps its beginning as a summary --------------------------------

from app.modules.learning.application.agent import history  # noqa: E402
from app.platform.llm.port import ChatReply  # noqa: E402


def long_conversation(turns=12, words=400):
    messages = []
    for n in range(turns):
        messages += [{"role": "user", "content": f"<learner_said>turn {n} " + "word " * words + "</learner_said>"},
                     {"role": "assistant", "content": None, "tool_calls": [{"id": f"t{n}", "name": "get_region"}]},
                     {"role": "tool", "tool_call_id": f"t{n}", "content": "{}"},
                     {"role": "assistant", "content": f"reply {n}?"}]
    return messages


class Summariser:
    def __init__(self, reply="Learner: A1, likes coffee. Open: past tense.", fail=False):
        self.reply, self.fail, self.asked = reply, fail, []

    def generate_with_tools(self, messages, tools, **kwargs):
        self.asked.append(messages)
        if self.fail:
            raise RuntimeError("down")
        return ChatReply(self.reply, ())


def test_a_long_conversation_keeps_its_latest_turns_whole_and_the_rest_as_a_summary():
    model = Summariser()
    compacted = history.compact(model, long_conversation())
    assert compacted[0]["content"].startswith(history.SUMMARY_MARK) and "likes coffee" in compacted[0]["content"]
    kept = history.turns_of(compacted)[1:]
    assert len(kept) == history.KEEP_RECENT_TURNS
    assert kept[-1][0]["content"].startswith("<learner_said>turn 11")
    assert all(any(m["role"] == "tool" for m in turn) for turn in kept)  # every kept call keeps its result
    assert "turn 0" in model.asked[0][1]["content"] and "turn 11" not in model.asked[0][1]["content"]
    assert model.asked[0][1]["content"].count("<") == 0  # the transcript is data


def test_a_short_conversation_or_a_failed_summary_changes_nothing():
    short = long_conversation(turns=3, words=5)
    assert history.compact(Summariser(), short) is short
    messages = long_conversation()
    assert history.compact(Summariser(fail=True), messages) is messages
    assert history.compact(Summariser(reply=""), messages) is messages
