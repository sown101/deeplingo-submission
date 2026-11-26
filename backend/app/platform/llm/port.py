"""Vendor-neutral structured-LLM port shared by consuming modules."""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol, TypeVar

from pydantic import BaseModel

TStructuredResponse = TypeVar("TStructuredResponse", bound=BaseModel)


class LLMProviderFailureCategory(str, Enum):
    CONFIGURATION = "provider_configuration"
    TRANSPORT = "transport_failure"
    EMPTY_RESPONSE = "provider_empty_response"
    REFUSAL = "provider_refusal"
    SCHEMA_VIOLATION = "provider_schema_violation"
    INCOMPATIBLE_RESPONSE = "provider_incompatible_response"
    # M2.3c: the request was refused before it was sent, by the cost budget. Not a provider fault, not learner evidence.
    BUDGET_REFUSED = "provider_budget_refused"


class LLMProviderError(Exception):
    def __init__(
        self,
        message: str,
        *,
        category: LLMProviderFailureCategory = LLMProviderFailureCategory.TRANSPORT,
        http_status: int | None = None,
    ):
        super().__init__(message)
        self.category = category
        self.http_status = http_status


class LLMProvider(Protocol):
    provider_name: str
    model_name: str

    def generate_structured(
        self,
        prompt: str,
        response_model: type[TStructuredResponse],
        *,
        system_prompt: str | None = None,
        temperature: float = 0.2,
        max_tokens: int = 2000,
    ) -> TStructuredResponse:
        ...


# --- Native tool calling -----------------------------------------------------------------------

@dataclass(frozen=True)
class ToolDefinition:
    """A function the model may call: name, purpose and a JSON schema of its arguments."""

    name: str
    description: str
    parameters: dict


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: dict  # {} when the model sent arguments that are not a JSON object
    # Provider fields returned with the call (Gemini 3's thought signature), sent back unchanged on the next turn.
    provider_data: dict = field(default_factory=dict)


@dataclass(frozen=True)
class ChatReply:
    """One model turn: tool calls to run, or (when there are none) the final text."""

    text: str | None
    tool_calls: tuple[ToolCall, ...] = ()


class ToolCallingModel(Protocol):
    """Messages and tool definitions in, tool calls or final text out.

    Messages are plain dicts: `{"role": "system"|"user"|"assistant", "content": str}`, an assistant message that
    called tools adds `"tool_calls": [{"id", "name", "arguments": dict}]`, and a result is
    `{"role": "tool", "tool_call_id": str, "content": str}`. Failures raise `LLMProviderError`.
    """

    def generate_with_tools(self, messages: Sequence[dict], tools: Sequence[ToolDefinition], *,
                            temperature: float = 0.5, max_tokens: int = 1500,
                            timeout: float | None = None) -> ChatReply:
        """`timeout` overrides the HTTP client's timeout in seconds for this request."""
        ...
