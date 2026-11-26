"""A text turn's limits hold for the provider too: a timed-out model call is cut and the learner does not wait for it,
and one ticket runs the model once even when two requests carry it at the same time. No live AI."""
import asyncio
import threading
import time

from app.modules.learning.application.agent import text as text_module
from app.modules.learning.application.agent.loop import AgentLoop, AgentLoopError
from app.modules.learning.application.agent.tools import TOOL_SPECS, ToolRegistry
from app.modules.learning.domain.companion import CompanionEntry
from app.platform.llm.port import ChatReply
from tests.learning.test_agent_harness import long_conversation
from tests.learning.test_agent_loop import make_session
from tests.learning.test_companion import ITEM_ID, USER, make_service, turn_output


class SlowModel:
    def __init__(self, seconds):
        self.seconds, self.timeouts = seconds, []

    def generate_with_tools(self, messages, tools, *, timeout=None, **kwargs):
        self.timeouts.append(timeout)
        time.sleep(self.seconds)
        return ChatReply("Hello?", ())


def test_the_model_call_gets_the_turns_remaining_time_as_its_own_deadline():
    model = SlowModel(0)
    asyncio.run(AgentLoop(model, ToolRegistry(), max_seconds=5).run(
        make_session(), "system", [{"role": "user", "content": "hi"}], TOOL_SPECS))
    assert model.timeouts and 0 < model.timeouts[0] <= 5


def test_a_timed_out_turn_returns_at_its_budget_not_when_the_model_call_ends():
    loop = AgentLoop(SlowModel(1.5), ToolRegistry(), max_seconds=0.3)
    started = time.perf_counter()
    try:
        text_module._run(loop.run(make_session(), "system", [{"role": "user", "content": "hi"}], TOOL_SPECS))
    except AgentLoopError as exc:
        assert exc.reason == "timeout"
    assert time.perf_counter() - started < 1.0  # before: 1.5 s, the request waited for the abandoned call


def test_two_requests_with_one_ticket_run_the_model_once():
    service = make_service(outputs=(turn_output(), turn_output(), turn_output()))
    ticket = service.start(USER, CompanionEntry.VIDEO, ITEM_ID).session_ticket
    before = len(service.model.calls)
    real = service.model.generate_with_tools
    inside, second_done = threading.Event(), threading.Event()

    def held(messages, tools, **kwargs):
        inside.set()
        second_done.wait(timeout=3)  # the first request is in the model while the second arrives
        return real(messages, tools, **kwargs)

    service.model.generate_with_tools = held
    results = {}

    def take(name):
        try:
            results[name] = service.turn(USER, ticket, text="I like flying").turn
        except Exception as exc:
            results[name] = getattr(exc, "code", type(exc).__name__)
        finally:
            if name == "second":
                second_done.set()

    first = threading.Thread(target=take, args=("first",))
    first.start()
    assert inside.wait(timeout=3)
    second = threading.Thread(target=take, args=("second",))
    second.start()
    second.join(timeout=5)
    first.join(timeout=5)
    assert results == {"first": 1, "second": "companion_session_invalid"}
    assert len(service.model.calls) - before == 1  # the refused request never reached the model


def test_a_turn_that_fails_leaves_its_ticket_usable_for_a_retry():
    from app.platform.llm.port import LLMProviderError
    service = make_service(outputs=(turn_output(), LLMProviderError("down"), turn_output()))
    ticket = service.start(USER, CompanionEntry.VIDEO, ITEM_ID).session_ticket
    try:
        service.turn(USER, ticket, text="I like flying")
    except Exception as exc:
        assert getattr(exc, "code", "") == "companion_turn_unavailable"
    assert service.turn(USER, ticket, text="I like flying").turn == 1


def test_a_long_text_turn_uses_one_deadline_for_the_summary_and_the_reply(monkeypatch):
    service = make_service(outputs=(turn_output(), ChatReply("Earlier notes", ()), turn_output()))
    opening = service.start(USER, CompanionEntry.VIDEO, ITEM_ID)
    session = service.load(USER, opening.session_ticket)
    session.messages = long_conversation()
    ticket, _ = service.save(session)
    timeouts = []
    now = [10.0]
    generate = service.model.generate_with_tools
    monkeypatch.setattr(text_module, "AgentLoop", lambda model, tools: AgentLoop(model, tools, clock=lambda: now[0]))

    def record_timeout(messages, tools, *, timeout=None, **kwargs):
        timeouts.append(timeout)
        if len(timeouts) == 1:
            now[0] += 1.5
        return generate(messages, tools, **kwargs)

    service.model.generate_with_tools = record_timeout
    assert service.turn(USER, ticket, text="I like flying").turn == 1
    assert timeouts == [2.0, 10.5]
