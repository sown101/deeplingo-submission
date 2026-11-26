"""Native tool calling of the OpenAI-compatible provider: messages and tools in, tool calls or text out. No live AI."""
import json
from types import SimpleNamespace

import httpx
import pytest
from openai import APIStatusError
from pydantic import BaseModel

from app.platform.llm.openai_compatible import OpenAICompatibleLLMProvider
from app.platform.llm.port import ChatReply, LLMProviderError, LLMProviderFailureCategory, ToolCall, ToolDefinition

TOOLS = [ToolDefinition("show_hint", "Show a hint.", {"type": "object", "properties": {"question": {"type": "string"}}})]
USAGE = SimpleNamespace(prompt_tokens=120, completion_tokens=9, completion_tokens_details=None)


class FakeCompletions:
    def __init__(self, *, message=None, failure=None, choices=True):
        self.message, self.failure, self.choices, self.calls = message, failure, choices, []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.failure:
            raise self.failure
        return SimpleNamespace(choices=[SimpleNamespace(message=self.message)] if self.choices else [], usage=USAGE)


def message(content=None, calls=(), refusal=None):
    return SimpleNamespace(content=content, refusal=refusal, tool_calls=[
        SimpleNamespace(id=call_id, function=SimpleNamespace(name=name, arguments=arguments))
        for call_id, name, arguments in calls] or None)


def provider_with(completions):
    provider = OpenAICompatibleLLMProvider(api_key="test-key", base_url="https://provider.invalid/v1",
                                           model_name="test-model")
    provider.client = SimpleNamespace(chat=SimpleNamespace(completions=completions),
                                      beta=SimpleNamespace(chat=SimpleNamespace(completions=None)))
    return provider


def test_tool_calls_and_definitions_use_the_wire_format_and_usage_goes_to_the_ledger_hook(monkeypatch):
    rows = []
    monkeypatch.setattr("app.platform.llm.openai_compatible.record_usage", lambda **fields: rows.append(fields))
    completions = FakeCompletions(message=message(calls=[("call_1", "show_hint", '{"question": "Bạn thích gì?"}')]))
    history = [{"role": "system", "content": "s"}, {"role": "user", "content": "hi"},
               {"role": "assistant", "content": None, "tool_calls": [
                   {"id": "call_0", "name": "get_region", "arguments": {"a": "b"}}]},
               {"role": "tool", "tool_call_id": "call_0", "content": '{"found": false}'}]

    reply = provider_with(completions).generate_with_tools(history, TOOLS, temperature=0.3, max_tokens=800)

    assert reply == ChatReply(None, (ToolCall("call_1", "show_hint", {"question": "Bạn thích gì?"}),))
    sent = completions.calls[0]
    assert sent["model"] == "test-model" and sent["temperature"] == 0.3 and sent["max_tokens"] == 800
    assert sent["tools"] == [{"type": "function", "function": {
        "name": "show_hint", "description": "Show a hint.", "parameters": TOOLS[0].parameters}}]
    assert sent["messages"][2] == {"role": "assistant", "content": None, "tool_calls": [{
        "id": "call_0", "type": "function", "function": {"name": "get_region", "arguments": json.dumps({"a": "b"})}}]}
    assert sent["messages"][3] == history[3]
    assert rows[0]["prompt_tokens"] == 120 and rows[0]["response_model"] == "_TOOL_CHAT"


def test_a_final_answer_is_text_and_without_tools_none_are_offered():
    completions = FakeCompletions(message=message(content="  Nice! Why?  "))
    reply = provider_with(completions).generate_with_tools([{"role": "user", "content": "hi"}], [])
    assert reply == ChatReply("Nice! Why?", ())
    assert "tools" not in completions.calls[0]


@pytest.mark.parametrize("arguments, expected", [("not json", {}), ("[1, 2]", {}), ("", {}), ('{"a": 1}', {"a": 1})])
def test_arguments_that_are_not_a_json_object_become_empty_so_the_registry_refuses_them(arguments, expected):
    completions = FakeCompletions(message=message(calls=[("c", "show_hint", arguments)]))
    assert provider_with(completions).generate_with_tools([], TOOLS).tool_calls[0].arguments == expected


@pytest.mark.parametrize("completions, category", [
    (FakeCompletions(message=message()), LLMProviderFailureCategory.EMPTY_RESPONSE),
    (FakeCompletions(choices=False), LLMProviderFailureCategory.EMPTY_RESPONSE),
    (FakeCompletions(message=message(refusal="no")), LLMProviderFailureCategory.REFUSAL),
    (FakeCompletions(failure=APIStatusError("x", response=httpx.Response(
        401, request=httpx.Request("POST", "https://x")), body=None)), LLMProviderFailureCategory.CONFIGURATION),
    (FakeCompletions(failure=APIStatusError("x", response=httpx.Response(
        500, request=httpx.Request("POST", "https://x")), body=None)), LLMProviderFailureCategory.TRANSPORT),
    (FakeCompletions(failure=RuntimeError("boom")), LLMProviderFailureCategory.TRANSPORT),
])
def test_failures_use_the_same_taxonomy_as_structured_calls(completions, category):
    with pytest.raises(LLMProviderError) as raised:
        provider_with(completions).generate_with_tools([{"role": "user", "content": "hi"}], TOOLS)
    assert raised.value.category == category


def test_structured_generation_still_works_next_to_tool_calling():
    class Answer(BaseModel):
        word: str

    class Parsed:
        def parse(self, **kwargs):
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
                parsed=Answer(word="ok"), refusal=None))], usage=USAGE)

    provider = provider_with(FakeCompletions())
    provider.client.beta.chat.completions = Parsed()
    assert provider.generate_structured("p", Answer).word == "ok"


SIGNATURE = {"extra_content": {"google": {"thought_signature": "sig-abc"}}}


def test_a_tool_call_keeps_the_provider_thought_signature_from_the_reply():
    """Gemini 3 returns a thought signature with each function call and rejects the next turn without it (HTTP 400)."""
    call = SimpleNamespace(id="call_1", function=SimpleNamespace(name="show_hint", arguments="{}"), model_extra=SIGNATURE)
    provider = provider_with(FakeCompletions(message=SimpleNamespace(content=None, refusal=None, tool_calls=[call])))
    reply = provider.generate_with_tools([{"role": "user", "content": "hi"}], TOOLS)
    assert reply.tool_calls[0].provider_data == SIGNATURE


def test_the_signature_is_sent_back_on_the_assistant_tool_call_of_the_next_turn():
    completions = FakeCompletions(message=message(content="Try again."))
    provider = provider_with(completions)
    history = [{"role": "user", "content": "hi"},
               {"role": "assistant", "content": None, "tool_calls": [
                   {"id": "call_1", "name": "show_hint", "arguments": {}, "provider_data": SIGNATURE}]},
               {"role": "tool", "tool_call_id": "call_1", "content": "{}"}]
    provider.generate_with_tools(history, TOOLS)
    sent = completions.calls[0]["messages"][1]["tool_calls"][0]
    assert sent["extra_content"] == SIGNATURE["extra_content"]
    assert sent["id"] == "call_1" and sent["function"]["name"] == "show_hint"
