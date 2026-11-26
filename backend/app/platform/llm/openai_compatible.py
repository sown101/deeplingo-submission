from __future__ import annotations

import base64
import json
import logging
import threading
from datetime import UTC, datetime
from collections.abc import Sequence
from typing import Callable

import httpx
from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI
from pydantic import BaseModel, ValidationError

from app.platform.config import settings
from app.platform.ai_budget import SpendReservation, daily_budget, text_cost
from app.platform.llm.ledger import record_usage
from app.platform.llm.tracing import observe_generation, trace_usage
from app.platform.llm.usage import current_usage_scope
from app.platform.llm.port import (
    ChatReply,
    LLMProviderError,
    LLMProviderFailureCategory,
    ToolCall,
    ToolDefinition,
    TStructuredResponse,
)

logger = logging.getLogger(__name__)


_CLOUD_PLATFORM_SCOPE = "https://www.googleapis.com/auth/cloud-platform"
# The OpenAI SDK requires a key; GoogleADCAuth replaces the header on every request.
_ADC_PLACEHOLDER_API_KEY = "application-default-credentials"


class ProviderCredentialsError(Exception):
    """Application Default Credentials are missing or could not be refreshed."""


def _load_google_default_credentials():
    import google.auth

    credentials, _ = google.auth.default(scopes=[_CLOUD_PLATFORM_SCOPE])
    return credentials


def _google_transport_request():
    from google.auth.transport.requests import Request

    return Request()


class GoogleADCAuth(httpx.Auth):
    """Attach a fresh Google OAuth access token from Application Default Credentials."""

    def __init__(
        self,
        load_credentials: Callable[[], object] = _load_google_default_credentials,
        transport_request: Callable[[], object] = _google_transport_request,
    ):
        self._load_credentials = load_credentials
        self._transport_request = transport_request
        self._credentials = None
        self._lock = threading.Lock()

    def auth_flow(self, request: httpx.Request):
        request.headers.update(self._authorization_headers(request))
        yield request

    def _authorization_headers(self, request: httpx.Request) -> dict[str, str]:
        import google.auth.exceptions

        headers: dict[str, str] = {}
        try:
            with self._lock:
                if self._credentials is None:
                    self._credentials = self._load_credentials()
                # Refreshes the token when it is missing or near expiry, and adds
                # the quota-project header for user credentials.
                self._credentials.before_request(
                    self._transport_request(), request.method, str(request.url), headers,
                )
        except google.auth.exceptions.GoogleAuthError as exc:
            raise ProviderCredentialsError("Application Default Credentials are unavailable") from exc
        return headers


_shared_adc_auth: GoogleADCAuth | None = None
_shared_adc_auth_lock = threading.Lock()


def _application_default_auth() -> GoogleADCAuth:
    global _shared_adc_auth
    with _shared_adc_auth_lock:
        if _shared_adc_auth is None:
            _shared_adc_auth = GoogleADCAuth()
        return _shared_adc_auth


_adc_http_clients: dict[float, httpx.Client] = {}
_adc_http_clients_lock = threading.Lock()


def _application_default_http_client(timeout: float) -> httpx.Client:
    """One connection pool per timeout for the whole process, not one per provider object."""
    with _adc_http_clients_lock:
        client = _adc_http_clients.get(timeout)
        if client is None:
            client = _adc_http_clients[timeout] = httpx.Client(auth=_application_default_auth(), timeout=timeout)
        return client


def create_openai_compatible_client(
    *,
    api_key: str | None = None,
    base_url: str | None = None,
    timeout_seconds: float | None = None,
) -> OpenAI:
    """Build the configured OpenAI-compatible client; Vertex authenticates via ADC."""
    resolved_base_url = base_url or settings.ai_runtime_base_url
    resolved_timeout = timeout_seconds or settings.AI_PROVIDER_TIMEOUT_SECONDS
    if settings.ai_uses_application_default_credentials and api_key is None:
        return OpenAI(
            api_key=_ADC_PLACEHOLDER_API_KEY,
            base_url=resolved_base_url,
            timeout=resolved_timeout,
            max_retries=0,
            http_client=_application_default_http_client(resolved_timeout),
        )
    return OpenAI(
        api_key=api_key or settings.ai_runtime_api_key,
        base_url=resolved_base_url,
        timeout=resolved_timeout,
        max_retries=0,
    )


class OpenAICompatibleLLMProvider:
    provider_name = "openai_compatible"

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model_name: str | None = None,
        timeout_seconds: float | None = None,
    ):
        if settings.AI_PROVIDER_MODE != "openai_compatible":
            raise LLMProviderError(
                "Configured AI provider mode is incompatible",
                category=LLMProviderFailureCategory.INCOMPATIBLE_RESPONSE,
            )
        if settings.AI_STRUCTURED_OUTPUT_MODE != "json_schema":
            raise LLMProviderError(
                "Configured structured-output mode is incompatible",
                category=LLMProviderFailureCategory.INCOMPATIBLE_RESPONSE,
            )
        uses_adc = settings.ai_uses_application_default_credentials and api_key is None
        resolved_api_key = api_key or settings.ai_runtime_api_key
        resolved_base_url = base_url or settings.ai_runtime_base_url
        resolved_model = model_name or settings.AI_EXTRACTION_MODEL or settings.AI_MODEL_NAME
        resolved_timeout = timeout_seconds or settings.AI_PROVIDER_TIMEOUT_SECONDS
        if (
            not (uses_adc or resolved_api_key) or not resolved_base_url
            or not resolved_model or resolved_timeout <= 0
        ):
            raise LLMProviderError(
                "AI provider configuration is incomplete",
                category=LLMProviderFailureCategory.CONFIGURATION,
            )
        self.model_name = resolved_model
        self._require_supported_parameters = settings.AI_PROVIDER == "openrouter"
        self.client = create_openai_compatible_client(
            api_key=api_key,
            base_url=resolved_base_url,
            timeout_seconds=resolved_timeout,
        )

    @observe_generation
    def generate_structured(
        self,
        prompt: str,
        response_model: type[TStructuredResponse],
        *,
        system_prompt: str | None = None,
        temperature: float = 0.2,
        max_tokens: int = 2000,
    ) -> TStructuredResponse:
        return self._parse_structured(
            [
                {
                    "role": "system",
                    "content": system_prompt
                    or "You extract source-grounded language-learning candidates and return JSON only.",
                },
                {"role": "user", "content": prompt},
            ],
            response_model,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    @observe_generation
    def generate_with_tools(
        self,
        messages: Sequence[dict],
        tools: Sequence[ToolDefinition],
        *,
        temperature: float = 0.5,
        max_tokens: int = 1500,
        timeout: float | None = None,
    ) -> ChatReply:
        """One chat turn with native function calling: the model answers in text or asks for tool calls.

        Usage is recorded through the same ledger hook as structured calls, under the label `tool_chat`.
        When supplied, `timeout` overrides the HTTP client's timeout for this call."""
        request: dict = {"model": self.model_name, "messages": [_wire_message(item) for item in messages],
                         "temperature": temperature, "max_tokens": max_tokens}
        if timeout is not None:
            request["timeout"] = timeout
        if tools:
            request["tools"] = [{"type": "function", "function": {
                "name": tool.name, "description": tool.description, "parameters": tool.parameters}}
                for tool in tools]
        if self._require_supported_parameters:
            request["extra_body"] = {"provider": {"require_parameters": True}}
        try:
            reservation = _reserve_budget(self.model_name, request, max_tokens=max_tokens)
            response = self.client.chat.completions.create(**request)
            _log_usage(response, provider=self, response_model=_TOOL_CHAT, reservation=reservation)
            if not response.choices:
                raise LLMProviderError("Provider returned no choices",
                                       category=LLMProviderFailureCategory.EMPTY_RESPONSE)
            message = response.choices[0].message
            if getattr(message, "refusal", None):
                raise LLMProviderError("Provider refused the request", category=LLMProviderFailureCategory.REFUSAL)
            calls = tuple(ToolCall(id=call.id, name=call.function.name,
                                   arguments=_json_object(call.function.arguments),
                                   provider_data=dict(getattr(call, "model_extra", None) or {}))
                          for call in (getattr(message, "tool_calls", None) or []))
            text = (getattr(message, "content", None) or "").strip() or None
            if not calls and text is None:
                raise LLMProviderError("Provider returned neither text nor tool calls",
                                       category=LLMProviderFailureCategory.EMPTY_RESPONSE)
            return ChatReply(text=text, tool_calls=calls)
        except LLMProviderError as exc:
            _log_provider_failure(exc, provider=self, response_model=_TOOL_CHAT)
            raise
        except Exception as exc:
            error = _provider_error(exc)
            _log_provider_failure(error, provider=self, response_model=_TOOL_CHAT,
                                  http_status=error.http_status)
            raise error from exc

    def generate_structured_with_audio(
        self,
        prompt: str,
        wav_audio: bytes,
        response_model: type[TStructuredResponse],
        *,
        system_prompt: str,
        temperature: float = 0.0,
        max_tokens: int = 1000,
    ) -> TStructuredResponse:
        """Structured generation over one WAV clip, with the same failure taxonomy."""
        if not wav_audio:
            raise LLMProviderError(
                "Audio input is empty",
                category=LLMProviderFailureCategory.INCOMPATIBLE_RESPONSE,
            )
        return self._parse_structured(
            [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "input_audio",
                            "input_audio": {"data": base64.b64encode(wav_audio).decode("ascii"), "format": "wav"},
                        },
                    ],
                },
            ],
            response_model,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    def _parse_structured(
        self,
        messages: list[dict],
        response_model: type[TStructuredResponse],
        *,
        temperature: float,
        max_tokens: int,
    ) -> TStructuredResponse:
        try:
            request_options = (
                {"extra_body": {"provider": {"require_parameters": True}}}
                if self._require_supported_parameters else {}
            )
            reservation = _reserve_budget(self.model_name, {
                "messages": messages, "schema": response_model.model_json_schema(),
            }, max_tokens=max_tokens)
            response = self.client.beta.chat.completions.parse(
                model=self.model_name,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                response_format=response_model,
                **request_options,
            )
            # Billed even when the result is later rejected, so record before validation.
            _log_usage(response, provider=self, response_model=response_model, reservation=reservation)
            if not response.choices:
                raise LLMProviderError(
                    "Provider returned no structured choices",
                    category=LLMProviderFailureCategory.EMPTY_RESPONSE,
                )
            message = response.choices[0].message
            refusal = getattr(message, "refusal", None)
            if refusal:
                raise LLMProviderError(
                    "Provider refused structured generation",
                    category=LLMProviderFailureCategory.REFUSAL,
                )
            parsed = getattr(message, "parsed", None)
            if parsed is None:
                raise LLMProviderError(
                    "Provider returned no parsed structured result",
                    category=LLMProviderFailureCategory.EMPTY_RESPONSE,
                )
            if isinstance(parsed, response_model):
                return parsed
            return response_model.model_validate(parsed)
        except (ValidationError, json.JSONDecodeError) as exc:
            error = LLMProviderError(
                "Provider result violated the canonical schema",
                category=LLMProviderFailureCategory.SCHEMA_VIOLATION,
            )
            _log_provider_failure(error, provider=self, response_model=response_model)
            raise error from exc
        except APIStatusError as exc:
            category = (
                LLMProviderFailureCategory.CONFIGURATION if exc.status_code in {401, 403}
                else LLMProviderFailureCategory.INCOMPATIBLE_RESPONSE
                if exc.status_code in {400, 422}
                else LLMProviderFailureCategory.TRANSPORT
            )
            error = LLMProviderError("Structured generation provider failed", category=category, http_status=exc.status_code)
            _log_provider_failure(
                error, provider=self, response_model=response_model,
                http_status=exc.status_code,
            )
            raise error from exc
        except (APITimeoutError, APIConnectionError) as exc:
            # Missing or unrefreshable credentials are a deployment fault, not a learner signal.
            error = LLMProviderError(
                "Structured generation provider failed",
                category=(
                    LLMProviderFailureCategory.CONFIGURATION
                    if isinstance(exc.__cause__, ProviderCredentialsError)
                    else LLMProviderFailureCategory.TRANSPORT
                ),
            )
            _log_provider_failure(error, provider=self, response_model=response_model)
            raise error from exc
        except Exception as exc:
            if isinstance(exc, LLMProviderError):
                _log_provider_failure(exc, provider=self, response_model=response_model)
                raise
            error = LLMProviderError(
                "Structured generation provider failed",
                category=LLMProviderFailureCategory.TRANSPORT,
            )
            _log_provider_failure(error, provider=self, response_model=response_model)
            raise error from exc


class _TOOL_CHAT:  # noqa: N801 - a label for the ledger and the logs, like a response model's name
    pass


def _wire_message(message: dict) -> dict:
    """The neutral message of `ToolCallingModel` in the OpenAI wire format."""
    calls = message.get("tool_calls")
    if not calls:
        return message
    return {"role": "assistant", "content": message.get("content"), "tool_calls": [{
        "id": call["id"], "type": "function",
        "function": {"name": call["name"], "arguments": json.dumps(call["arguments"], ensure_ascii=False)},
        **(call.get("provider_data") or {})}
        for call in calls]}


def _json_object(raw) -> dict:
    try:
        value = json.loads(raw) if isinstance(raw, str) and raw.strip() else {}
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _provider_error(exc: Exception) -> LLMProviderError:
    """The failure taxonomy of `_parse_structured`, for a call without a response schema."""
    if isinstance(exc, APIStatusError):
        category = (LLMProviderFailureCategory.CONFIGURATION if exc.status_code in {401, 403}
                    else LLMProviderFailureCategory.INCOMPATIBLE_RESPONSE if exc.status_code in {400, 422}
                    else LLMProviderFailureCategory.TRANSPORT)
        return LLMProviderError("Tool-calling provider failed", category=category, http_status=exc.status_code)
    if isinstance(exc, (APITimeoutError, APIConnectionError)) and isinstance(exc.__cause__, ProviderCredentialsError):
        return LLMProviderError("Tool-calling provider failed", category=LLMProviderFailureCategory.CONFIGURATION)
    return LLMProviderError("Tool-calling provider failed", category=LLMProviderFailureCategory.TRANSPORT)


def _reserve_budget(model: str, request: dict, *, max_tokens: int) -> SpendReservation:
    input_size = len(json.dumps(request, ensure_ascii=False).encode("utf-8"))
    for message in request["messages"]:
        content = message.get("content")
        if isinstance(content, list):
            for part in content:
                if part.get("type") == "input_audio":
                    # The provider tokenizes the audio, not the ASCII transport encoding.
                    size = len(part["input_audio"]["data"])
                    input_size -= size - (size + 31) // 32
    reservation = daily_budget().reserve(text_cost(model, input_size, max_tokens))
    if reservation is None:
        raise LLMProviderError("The daily AI budget is used up.", category=LLMProviderFailureCategory.BUDGET_REFUSED)
    return reservation


def _log_usage(response, *, provider, response_model: type[BaseModel],
               reservation: SpendReservation | None = None) -> None:
    """Token counts only: no prompt, output, learner or key material is logged. `scope` (M1 S7) names
    the region or Library item the call is spent on; `at` is UTC so it can be matched to sessions."""
    usage = getattr(response, "usage", None)
    if usage is None:
        return
    details = getattr(usage, "completion_tokens_details", None)
    logger.info(
        "llm_usage provider=%s model=%s response_model=%s prompt_tokens=%s completion_tokens=%s reasoning_tokens=%s"
        " scope=%s at=%s",
        provider.provider_name,
        provider.model_name,
        response_model.__name__,
        getattr(usage, "prompt_tokens", None),
        getattr(usage, "completion_tokens", None),
        getattr(details, "reasoning_tokens", None) if details is not None else None,
        current_usage_scope(),
        datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    record_usage(provider=provider.provider_name, model=provider.model_name, response_model=response_model.__name__,
                 scope=current_usage_scope(), prompt_tokens=getattr(usage, "prompt_tokens", None),
                 completion_tokens=getattr(usage, "completion_tokens", None),
                 reasoning_tokens=getattr(details, "reasoning_tokens", None) if details is not None else None)
    def tokens(value) -> int:
        return value if isinstance(value, int) and value > 0 else 0
    reasoning = getattr(details, "reasoning_tokens", None) if details is not None else None
    prompt = getattr(usage, "prompt_tokens", None)
    completion = getattr(usage, "completion_tokens", None)
    if isinstance(prompt, int) and isinstance(completion, int):
        cost = text_cost(provider.model_name, tokens(prompt), tokens(completion) + tokens(reasoning))
        daily_budget().charge(cost, reservation=reservation)
        trace_usage(tokens(prompt), tokens(completion), tokens(reasoning), cost)


def _log_provider_failure(
    error: LLMProviderError, *, provider, response_model: type[BaseModel],
    http_status: int | None = None,
) -> None:
    logger.warning(
        "structured_provider_failure category=%s provider=%s model=%s response_model=%s http_status=%s",
        error.category.value,
        provider.provider_name,
        provider.model_name,
        response_model.__name__,
        http_status,
    )
