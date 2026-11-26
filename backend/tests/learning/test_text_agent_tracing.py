"""Text tracing end to end with fake provider responses and a fake Langfuse client."""
import json
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID, uuid4

import httpx
import pytest
import requests
from pydantic import BaseModel, SecretStr

from app.bootstrap.wiring.agent import get_text_turn_tracing, lazy_text_turn_tracing
from app.modules.learning.application.speaking_ports import SpeakingPracticeError
from app.modules.learning.domain.companion import CompanionEntry
from app.platform import ai_budget
from app.platform.config import Settings, settings
from app.platform.llm.port import LLMProviderFailureCategory
from app.platform.observability import langfuse
from app.platform.observability.port import trace_turn
from tests.learning.test_companion import USER, make_service, turn_output
from tests.platform.test_llm_tool_calling import USAGE, message, provider_with


class FakeSpan:
    def __init__(self, fields, fail):
        self.fields = fields
        self.fail = fail
        self.updates = {}
        self.children = []
        self.ended = False

    def start_observation(self, **fields):
        if self.fail == "child":
            raise TimeoutError("private diagnostic")
        child = FakeSpan(fields, self.fail)
        self.children.append(child)
        return child

    def update(self, **fields):
        if self.fail == "update":
            raise TimeoutError("private diagnostic")
        self.updates.update(fields)

    def end(self):
        self.ended = True
        if self.fail == "end":
            raise TimeoutError("private diagnostic")


class FakeClient:
    def __init__(self, fail=None):
        self.fail = fail
        self.children = []

    def start_observation(self, **fields):
        if self.fail == "root":
            raise TimeoutError("private diagnostic")
        root = FakeSpan(fields, self.fail)
        self.children.append(root)
        return root


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    get_text_turn_tracing.cache_clear()
    network = Mock(side_effect=AssertionError("network is forbidden in tracing tests"))
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", network)
    monkeypatch.setattr(requests.Session, "send", network)
    yield
    get_text_turn_tracing.cache_clear()
    network.assert_not_called()


def configure_tracing(monkeypatch, *, enabled=True, capture=False, fail=None):
    client = FakeClient(fail)
    create = Mock(return_value=client)
    if fail == "init":
        create.side_effect = TimeoutError("private diagnostic")
    monkeypatch.setattr(langfuse, "create_client", create)
    monkeypatch.setattr(settings, "LANGFUSE_ENABLED", enabled)
    monkeypatch.setattr(settings, "LANGFUSE_CAPTURE_CONTENT", capture)
    monkeypatch.setattr(settings, "LANGFUSE_HOST", "https://trace.invalid")
    monkeypatch.setattr(settings, "LANGFUSE_PUBLIC_KEY", SecretStr(uuid4().hex))
    monkeypatch.setattr(settings, "LANGFUSE_SECRET_KEY", SecretStr(uuid4().hex))
    return client, create


def service_with(*messages):
    completions = Mock()
    completions.create.side_effect = [SimpleNamespace(choices=[SimpleNamespace(message=item)], usage=USAGE)
                                      for item in messages]
    service = make_service()
    service.model = provider_with(completions)
    service.tracing = lazy_text_turn_tracing()
    return service


def opening():
    return message(content=turn_output().text)


def start(service):
    return service.start(USER, CompanionEntry.HOME, None, text_only=True)


def test_disabled_tracing_never_constructs_a_client(monkeypatch):
    defaults = Settings(_env_file=None)
    assert not defaults.LANGFUSE_ENABLED and not defaults.LANGFUSE_CAPTURE_CONTENT
    client, create = configure_tracing(monkeypatch, enabled=False)
    assert start(service_with(opening())).reply == turn_output().reply
    create.assert_not_called()
    assert not client.children


def test_text_turn_exports_metadata_for_calls_and_counts_tool_rounds(monkeypatch):
    client, create = configure_tracing(monkeypatch)
    learner_text = "Please give me a trace test hint."
    hint_text = "a private hint"
    reply_text = "Can you say more about it?"
    service = service_with(
        opening(),
        message(calls=[("one", "show_hint", json.dumps({"question": hint_text})),
                       ("two", "learner email person@example.invalid", "{}")]),
        message(content=turn_output(reply=reply_text).text),
    )

    create.assert_not_called()
    started = start(service)
    reply = service.turn(USER, started.session_ticket, text=learner_text, speak=False)
    assert reply.reply == reply_text
    assert len(client.children) == 2
    create.assert_called_once()
    root = client.children[1]
    trace_id = root.fields["trace_context"]["trace_id"]
    assert UUID(trace_id).version == 4 and trace_id != client.children[0].fields["trace_context"]["trace_id"]
    assert root.ended and root.fields["as_type"] == "agent"
    assert root.updates["metadata"] | {"latency_ms": 0} == {
        "status": "ok", "phase": "turn", "tool_rounds": 1, "latency_ms": 0}
    assert root.updates["metadata"]["latency_ms"] >= 0
    generation, tool, refused, final = root.children
    assert tool.fields == {"name": "show_hint", "as_type": "tool"}
    assert tool.updates["metadata"]["status"] == "ok"
    assert tool.updates["metadata"]["latency_ms"] >= 0
    assert refused.fields["name"] == "unknown" and refused.updates["metadata"]["status"] == "refused"
    for span in (generation, final):
        assert span.fields == {"as_type": "generation", "name": "generate_with_tools", "model": "test-model"}
        assert span.updates["usage_details"] == {"input": 120, "output": 9, "reasoning": 0, "total": 129}
        assert span.updates["cost_details"] == {"total": ai_budget.text_cost("test-model", 120, 9)}
        assert span.updates["metadata"]["status"] == "ok"
    for span in [root, *root.children]:
        assert span.ended
        sent = json.dumps([span.fields, span.updates])
        assert {"input", "output"}.isdisjoint(span.fields)
        assert {"input", "output"}.isdisjoint(span.updates)
        assert all(value not in sent for value in (learner_text, hint_text, reply_text, str(USER.id), "person@"))


def test_provider_failure_is_categorized_without_exporting_the_error_body(monkeypatch):
    client, _ = configure_tracing(monkeypatch, capture=True)
    service = service_with(message(refusal="private provider refusal detail"))
    with pytest.raises(SpeakingPracticeError) as error:
        start(service)
    assert error.value.code == "companion_turn_unavailable"
    root = client.children[0]
    failure = root.children[0].updates
    assert failure["level"] == "ERROR"
    assert failure["metadata"]["failure_category"] == LLMProviderFailureCategory.REFUSAL.value
    assert failure["metadata"]["status"] == root.updates["metadata"]["status"] == "error"
    assert failure["usage_details"]["total"] == 129
    assert "private provider refusal detail" not in json.dumps(failure)


@pytest.mark.parametrize("failure", ["init", "root", "child", "update", "end"])
def test_tracing_failures_leave_the_turn_result_intact(monkeypatch, caplog, failure):
    configure_tracing(monkeypatch, fail=failure)
    assert start(service_with(opening())).reply == turn_output().reply
    assert "Langfuse" in caplog.text
    assert "private diagnostic" not in caplog.text


def test_content_is_redacted_before_reaching_langfuse(monkeypatch):
    class Answer(BaseModel):
        value: str

    client, _ = configure_tracing(monkeypatch, capture=True)
    service = service_with(opening())
    reply = Answer(value="Reply from learner@example.invalid")
    service.model.client.beta.chat.completions = Mock()
    service.model.client.beta.chat.completions.parse.return_value = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(parsed=reply, refusal=None))], usage=USAGE)

    with trace_turn(service.tracing, "turn"):
        result = service.model.generate_structured("Call (+84) 912-345-678", Answer,
                                                   system_prompt="Bearer temporary-test-value")
        service.model.generate_with_tools(
            [{"role": "user", "content": "Mail learner@example.invalid"}], [])

    assert result is reply
    structured, chat = client.children[0].children
    assert structured.fields["name"] == "generate_structured"
    sent = structured.updates
    assert sent["input"] == ["[redacted]", "Call [redacted]"]
    assert json.loads(sent["output"]) == {"value": "Reply from [redacted]"}
    assert chat.updates["input"] == ["Mail [redacted]"] and chat.updates["output"] == turn_output().text


@pytest.mark.parametrize("private", [
    "friend+tag@example.invalid", "(415) 555-0100", "+84 912 345 678",
    "Bearer short-example", "eyJhbGci.eyJzdWI.c2ln", '"access_token":"short-example"',
    "syntheticOpaqueValue0123456789", "data:image/png;base64,AAAA",
])
def test_redaction_matches_common_contact_and_token_formats(private):
    assert private not in langfuse.redact(f"Keep this text: {private}")
    assert "Keep this text: " in langfuse.redact(f"Keep this text: {private}")
