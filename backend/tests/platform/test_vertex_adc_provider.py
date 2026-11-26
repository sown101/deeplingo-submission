import google.auth.exceptions
import httpx
import pytest
from pydantic import ValidationError

from app.platform.config import Settings, settings
from tests.platform.structured_result_model import LLMSemanticAssessment
from app.platform.llm import openai_compatible as providers_module
from app.platform.llm.openai_compatible import (
    GoogleADCAuth,
    OpenAICompatibleLLMProvider,
    ProviderCredentialsError,
)
from app.platform.llm.port import LLMProviderError, LLMProviderFailureCategory


VERTEX = {
    "AI_PROVIDER": "vertex",
    "VERTEX_PROJECT_ID": "deeplingo-dev-123",
    "VERTEX_LOCATION": "us-central1",
    "AI_MODEL_NAME": "google/gemini-test-model",
}


class FakeCredentials:
    def __init__(self, quota_project: str | None = None):
        self.refreshes = 0
        self.quota_project = quota_project

    def before_request(self, request, method, url, headers):
        self.refreshes += 1
        headers["authorization"] = f"Bearer adc-token-{self.refreshes}"
        if self.quota_project:
            headers["x-goog-user-project"] = self.quota_project


def fake_auth(credentials=None, *, failure: Exception | None = None):
    def load():
        if failure:
            raise failure
        return credentials

    return GoogleADCAuth(load_credentials=load, transport_request=lambda: object())


def test_vertex_derives_regional_endpoint_and_has_no_api_key() -> None:
    config = Settings(_env_file=None, ENVIRONMENT="development", GEMINI_API_KEY="legacy-key", **VERTEX)

    assert config.ai_uses_application_default_credentials
    assert config.ai_runtime_api_key == ""
    assert config.ai_runtime_base_url == (
        "https://us-central1-aiplatform.googleapis.com/v1/projects/deeplingo-dev-123"
        "/locations/us-central1/endpoints/openapi"
    )


def test_vertex_global_location_uses_global_host() -> None:
    config = Settings(_env_file=None, ENVIRONMENT="development", **{**VERTEX, "VERTEX_LOCATION": "global"})

    assert config.ai_runtime_base_url == (
        "https://aiplatform.googleapis.com/v1/projects/deeplingo-dev-123/locations/global/endpoints/openapi"
    )


def test_non_vertex_provider_keeps_configured_base_url() -> None:
    config = Settings(
        _env_file=None, ENVIRONMENT="development", AI_PROVIDER="gemini",
        AI_BASE_URL="https://provider.invalid/v1",
    )

    assert not config.ai_uses_application_default_credentials
    assert config.ai_runtime_base_url == "https://provider.invalid/v1"


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"VERTEX_PROJECT_ID": ""}, "VERTEX_PROJECT_ID"),
        ({"VERTEX_PROJECT_ID": "Bad_Project/../x"}, "VERTEX_PROJECT_ID"),
        ({"VERTEX_LOCATION": ""}, "VERTEX_LOCATION"),
        ({"VERTEX_LOCATION": "us-central1.evil.example"}, "VERTEX_LOCATION"),
        ({"AI_API_KEY": "should-not-be-used"}, "AI_API_KEY must be empty"),
        ({"AI_BASE_URL": "https://provider.invalid/v1"}, "AI_BASE_URL must not be set"),
        ({"AI_MODEL_NAME": ""}, "explicit AI_MODEL_NAME"),
    ],
)
def test_vertex_rejects_incomplete_or_ambiguous_configuration(overrides, message) -> None:
    with pytest.raises(ValidationError, match=message):
        Settings(_env_file=None, ENVIRONMENT="development", **{**VERTEX, **overrides})


def test_vertex_requires_explicit_model_name() -> None:
    fields = dict(VERTEX)
    fields.pop("AI_MODEL_NAME")

    with pytest.raises(ValidationError, match="explicit AI_MODEL_NAME"):
        Settings(_env_file=None, ENVIRONMENT="development", **fields)


@pytest.mark.parametrize("environment", ["staging", "production"])
def test_release_accepts_production_eligible_vertex_without_key_or_base_url(environment: str) -> None:
    config = Settings(
        _env_file=None, ENVIRONMENT=environment,
        AI_PROVIDER_DEPLOYMENT_CLASS="production_eligible", **VERTEX,
    )

    assert config.ai_provider_deployment_class == "production_eligible"


def test_release_still_requires_production_eligible_vertex() -> None:
    with pytest.raises(ValidationError, match="production-eligible semantic provider"):
        Settings(_env_file=None, ENVIRONMENT="production", **VERTEX)


def test_adc_auth_replaces_placeholder_header_and_adds_quota_project() -> None:
    credentials = FakeCredentials(quota_project="deeplingo-dev-123")
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers)
        return httpx.Response(200, json={})

    with httpx.Client(auth=fake_auth(credentials), transport=httpx.MockTransport(handler)) as client:
        client.post("https://vertex.invalid/v1", headers={"Authorization": "Bearer placeholder"})
        client.post("https://vertex.invalid/v1")

    assert [headers["authorization"] for headers in seen] == ["Bearer adc-token-1", "Bearer adc-token-2"]
    assert all(headers["x-goog-user-project"] == "deeplingo-dev-123" for headers in seen)


def test_adc_auth_loads_credentials_once() -> None:
    loads = []
    credentials = FakeCredentials()

    def load():
        loads.append(1)
        return credentials

    auth = GoogleADCAuth(load_credentials=load, transport_request=lambda: object())
    with httpx.Client(auth=auth, transport=httpx.MockTransport(lambda r: httpx.Response(200))) as client:
        client.get("https://vertex.invalid/a")
        client.get("https://vertex.invalid/b")

    assert len(loads) == 1
    assert credentials.refreshes == 2


@pytest.mark.parametrize(
    "failure",
    [
        google.auth.exceptions.DefaultCredentialsError("no ADC"),
        google.auth.exceptions.RefreshError("expired login"),
    ],
)
def test_adc_auth_failure_is_a_credentials_error(failure) -> None:
    with httpx.Client(auth=fake_auth(failure=failure), transport=httpx.MockTransport(lambda r: httpx.Response(200))) as client:
        with pytest.raises(ProviderCredentialsError):
            client.get("https://vertex.invalid/v1")


def configure_vertex(monkeypatch, auth: GoogleADCAuth, handler) -> None:
    for field, value in {**VERTEX, "AI_API_KEY": "", "AI_EXTRACTION_MODEL": ""}.items():
        monkeypatch.setattr(settings, field, value)
    monkeypatch.setattr(providers_module, "_application_default_auth", lambda: auth)
    monkeypatch.setattr(providers_module, "_adc_http_clients", {})  # the shared client per timeout starts empty
    original_client = httpx.Client

    class MockTransportClient(original_client):
        def __init__(self, **kwargs):
            super().__init__(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(providers_module.httpx, "Client", MockTransportClient)


def semantic_completion() -> dict:
    content = (
        '{"verdict":"correct","score":1,"confidence":0.93,'
        '"rationale":"Matches the intended meaning.","evidence_alignment":"Aligned with the target sense."}'
    )
    return {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "created": 0,
        "model": "google/gemini-test-model",
        "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": content}}],
    }


def test_vertex_provider_calls_derived_endpoint_with_adc_token(monkeypatch) -> None:
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=semantic_completion())

    configure_vertex(monkeypatch, fake_auth(FakeCredentials()), handler)
    provider = OpenAICompatibleLLMProvider()

    result = provider.generate_structured("prompt", LLMSemanticAssessment)

    assert result.verdict == "correct"
    assert provider.model_name == "google/gemini-test-model"
    assert str(requests[0].url) == (
        "https://us-central1-aiplatform.googleapis.com/v1/projects/deeplingo-dev-123"
        "/locations/us-central1/endpoints/openapi/chat/completions"
    )
    assert requests[0].headers["authorization"] == "Bearer adc-token-1"


def test_vertex_missing_credentials_fail_closed_as_configuration(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no request may be sent without credentials")

    configure_vertex(
        monkeypatch,
        fake_auth(failure=google.auth.exceptions.DefaultCredentialsError("no ADC")),
        handler,
    )
    provider = OpenAICompatibleLLMProvider()

    with pytest.raises(LLMProviderError) as captured:
        provider.generate_structured("prompt", LLMSemanticAssessment)

    assert captured.value.category == LLMProviderFailureCategory.CONFIGURATION


def test_vertex_rejected_token_is_configuration_not_learner_failure(monkeypatch) -> None:
    configure_vertex(
        monkeypatch, fake_auth(FakeCredentials()),
        lambda request: httpx.Response(403, json={"error": {"message": "denied"}}),
    )
    provider = OpenAICompatibleLLMProvider()

    with pytest.raises(LLMProviderError) as captured:
        provider.generate_structured("prompt", LLMSemanticAssessment)

    assert captured.value.category == LLMProviderFailureCategory.CONFIGURATION
    assert captured.value.http_status == 403


def test_explicit_api_key_bypasses_adc_even_when_vertex_is_configured(monkeypatch) -> None:
    def adc_must_not_be_used():
        raise AssertionError("explicit key must not use ADC")

    for field, value in VERTEX.items():
        monkeypatch.setattr(settings, field, value)
    monkeypatch.setattr(providers_module, "_application_default_auth", adc_must_not_be_used)

    provider = OpenAICompatibleLLMProvider(
        api_key="test-key", base_url="https://provider.invalid/v1", model_name="test-model",
    )

    assert provider.client.api_key == "test-key"
