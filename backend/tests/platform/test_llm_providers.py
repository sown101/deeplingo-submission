import json
from types import SimpleNamespace

import httpx
import pytest
from openai import APIStatusError

from tests.platform.structured_result_model import LLMSemanticAssessment
from app.platform.config import settings
from app.platform.llm import openai_compatible as providers_module
from app.modules.content.infrastructure import llm_enrichment as enrichment_module
from app.platform.llm.port import LLMProviderError, LLMProviderFailureCategory
from app.platform.llm.openai_compatible import OpenAICompatibleLLMProvider


def canonical_result(**overrides):
    payload = {
        "verdict": "correct",
        "score": 1,
        "confidence": 0.93,
        "rationale": "The response matches the intended contextual meaning.",
        "evidence_alignment": "The response aligns with the selected target sense.",
    }
    payload.update(overrides)
    return payload


class FakeParsedCompletions:
    def __init__(self, *, parsed=None, refusal=None, failure=None):
        self.parsed = parsed
        self.refusal = refusal
        self.failure = failure
        self.calls = []

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        if self.failure:
            raise self.failure
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(parsed=self.parsed, refusal=self.refusal),
                )
            ]
        )


def provider_with(completions):
    provider = OpenAICompatibleLLMProvider(
        api_key="test-key",
        base_url="https://provider.invalid/v1",
        model_name="test-model",
    )
    provider.client = SimpleNamespace(
        beta=SimpleNamespace(
            chat=SimpleNamespace(completions=completions),
        )
    )
    return provider


def test_openai_compatible_provider_transmits_canonical_json_schema_model():
    parsed = LLMSemanticAssessment.model_validate(canonical_result())
    completions = FakeParsedCompletions(parsed=parsed)
    provider = provider_with(completions)

    result = provider.generate_structured(
        "controlled prompt",
        LLMSemanticAssessment,
        system_prompt="controlled system prompt",
        temperature=0,
        max_tokens=900,
    )

    assert result == parsed
    assert completions.calls[0]["response_format"] is LLMSemanticAssessment
    assert completions.calls[0]["model"] == "test-model"
    assert completions.calls[0]["temperature"] == 0


def test_provider_transport_disables_sdk_retries_and_bounds_timeout():
    provider = OpenAICompatibleLLMProvider(
        api_key="test-key",
        base_url="https://provider.invalid/v1",
        model_name="test-model",
        timeout_seconds=7,
    )

    assert provider.client.max_retries == 0
    assert provider.client.timeout == 7


def test_missing_runtime_credentials_fail_as_configuration(monkeypatch):
    monkeypatch.setattr(settings, "AI_API_KEY", "")
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "")

    with pytest.raises(LLMProviderError) as caught:
        OpenAICompatibleLLMProvider(
            base_url="https://provider.invalid/v1",
            model_name="test-model",
        )

    assert caught.value.category == LLMProviderFailureCategory.CONFIGURATION


def test_generic_api_key_takes_precedence_over_legacy_gemini_key(monkeypatch):
    captured = {}

    class FakeOpenAI:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(providers_module, "OpenAI", FakeOpenAI)
    monkeypatch.setattr(settings, "AI_API_KEY", "generic-key")
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "legacy-key")

    OpenAICompatibleLLMProvider(
        base_url="https://provider.invalid/v1",
        model_name="test-model",
    )

    assert captured["api_key"] == "generic-key"


def test_openrouter_provider_adds_no_identity_headers(monkeypatch):
    captured = {}

    class FakeOpenAI:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(providers_module, "OpenAI", FakeOpenAI)
    monkeypatch.setattr(settings, "AI_PROVIDER", "openrouter")

    OpenAICompatibleLLMProvider(
        api_key="test-key",
        base_url="https://openrouter.ai/api/v1",
        model_name="example/model:free",
    )

    assert "default_headers" not in captured


def test_openrouter_structured_request_requires_supported_parameters(monkeypatch):
    monkeypatch.setattr(settings, "AI_PROVIDER", "openrouter")
    completions = FakeParsedCompletions(
        parsed=LLMSemanticAssessment.model_validate(canonical_result()),
    )
    provider = provider_with(completions)

    provider.generate_structured("controlled prompt", LLMSemanticAssessment)

    assert completions.calls[0]["extra_body"] == {"provider": {"require_parameters": True}}


def test_non_openrouter_request_has_no_provider_routing_override(monkeypatch):
    monkeypatch.setattr(settings, "AI_PROVIDER", "gemini")
    completions = FakeParsedCompletions(
        parsed=LLMSemanticAssessment.model_validate(canonical_result()),
    )
    provider = provider_with(completions)

    provider.generate_structured("controlled prompt", LLMSemanticAssessment)

    assert "extra_body" not in completions.calls[0]


def test_non_gemini_provider_cannot_fall_back_to_gemini_credential(monkeypatch):
    monkeypatch.setattr(settings, "AI_PROVIDER", "openrouter")
    monkeypatch.setattr(settings, "AI_API_KEY", "")
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "legacy-gemini-key")

    with pytest.raises(LLMProviderError) as caught:
        OpenAICompatibleLLMProvider(base_url="https://openrouter.ai/api/v1", model_name="example/model:free")

    assert caught.value.category == LLMProviderFailureCategory.CONFIGURATION


def test_provider_boundary_rejects_extra_authority_fields():
    completions = FakeParsedCompletions(
        parsed=canonical_result(review_rating="GOOD", mastery=1),
    )
    provider = provider_with(completions)

    with pytest.raises(LLMProviderError) as caught:
        provider.generate_structured("prompt", LLMSemanticAssessment)

    assert caught.value.category == LLMProviderFailureCategory.SCHEMA_VIOLATION


@pytest.mark.parametrize(
    ("status", "category"),
    [
        (401, LLMProviderFailureCategory.CONFIGURATION),
        (403, LLMProviderFailureCategory.CONFIGURATION),
        (429, LLMProviderFailureCategory.TRANSPORT),
        (500, LLMProviderFailureCategory.TRANSPORT),
        (400, LLMProviderFailureCategory.INCOMPATIBLE_RESPONSE),
    ],
)
def test_provider_status_errors_are_safely_classified(status, category):
    request = httpx.Request("POST", "https://provider.invalid/v1/chat/completions")
    response = httpx.Response(status, request=request)
    error = APIStatusError("upstream detail must not leak", response=response, body=None)
    provider = provider_with(FakeParsedCompletions(failure=error))

    with pytest.raises(LLMProviderError) as caught:
        provider.generate_structured("prompt", LLMSemanticAssessment)

    assert caught.value.category == category
    assert "upstream detail" not in str(caught.value)


def test_malformed_json_is_schema_violation():
    provider = provider_with(FakeParsedCompletions(failure=json.JSONDecodeError("invalid", "{", 0)))

    with pytest.raises(LLMProviderError) as caught:
        provider.generate_structured("prompt", LLMSemanticAssessment)

    assert caught.value.category == LLMProviderFailureCategory.SCHEMA_VIOLATION


def test_enrichment_reuses_strict_structured_provider(monkeypatch):
    calls = []

    class FakeProvider:
        model_name = "test-model"

        def __init__(self, **kwargs):
            calls.append(("init", kwargs))

        def generate_structured(self, *args, **kwargs):
            calls.append(("generate", args, kwargs))
            return "enriched"

    monkeypatch.setattr(enrichment_module, "OpenAICompatibleLLMProvider", FakeProvider)
    provider = enrichment_module.OpenAICompatibleLearningObjectEnrichmentProvider(model_name="test-model")

    assert provider.enrich("source-grounded prompt") == "enriched"
    assert calls[1][1][1] is enrichment_module.LLMLearningObjectEnrichment


@pytest.mark.parametrize(
    ("completions", "category"),
    [
        (
            FakeParsedCompletions(parsed=None),
            LLMProviderFailureCategory.EMPTY_RESPONSE,
        ),
        (
            FakeParsedCompletions(parsed=None, refusal="cannot comply"),
            LLMProviderFailureCategory.REFUSAL,
        ),
        (
            FakeParsedCompletions(failure=TimeoutError("timed out")),
            LLMProviderFailureCategory.TRANSPORT,
        ),
    ],
)
def test_provider_failures_are_safely_classified(completions, category):
    provider = provider_with(completions)

    with pytest.raises(LLMProviderError) as caught:
        provider.generate_structured("prompt", LLMSemanticAssessment)

    assert caught.value.category == category


class UsageCompletions(FakeParsedCompletions):
    def __init__(self, *, parsed=None, usage=None):
        super().__init__(parsed=parsed)
        self.usage = usage

    def parse(self, **kwargs):
        response = super().parse(**kwargs)
        response.usage = self.usage
        return response


def billed_usage(prompt=812, completion=230, reasoning=40):
    return SimpleNamespace(prompt_tokens=prompt, completion_tokens=completion,
                           completion_tokens_details=SimpleNamespace(reasoning_tokens=reasoning))


def test_usage_is_logged_with_counts_only(caplog):
    parsed = LLMSemanticAssessment.model_validate(canonical_result())
    provider = provider_with(UsageCompletions(parsed=parsed, usage=billed_usage()))
    with caplog.at_level("INFO", logger=providers_module.logger.name):
        provider.generate_structured("secret learner answer", LLMSemanticAssessment,
                                     system_prompt="hidden rubric", temperature=0, max_tokens=900)
    lines = [r.getMessage() for r in caplog.records if "llm_usage" in r.getMessage()]
    assert len(lines) == 1
    assert "model=test-model response_model=LLMSemanticAssessment" in lines[0]
    assert "prompt_tokens=812 completion_tokens=230 reasoning_tokens=40" in lines[0]
    assert "secret learner answer" not in lines[0] and "hidden rubric" not in lines[0] and "test-key" not in lines[0]


def test_usage_is_logged_even_when_the_result_is_rejected(caplog):
    provider = provider_with(UsageCompletions(parsed=None, usage=billed_usage(prompt=5, completion=7, reasoning=None)))
    with caplog.at_level("INFO", logger=providers_module.logger.name), pytest.raises(LLMProviderError):
        provider.generate_structured("p", LLMSemanticAssessment, temperature=0, max_tokens=10)
    assert any("prompt_tokens=5 completion_tokens=7" in r.getMessage() for r in caplog.records)


def test_missing_usage_is_not_an_error():
    parsed = LLMSemanticAssessment.model_validate(canonical_result())
    provider = provider_with(UsageCompletions(parsed=parsed, usage=None))
    assert provider.generate_structured("p", LLMSemanticAssessment, temperature=0, max_tokens=10) == parsed
