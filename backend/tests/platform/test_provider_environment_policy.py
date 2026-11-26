import pytest
from pydantic import ValidationError

from app.platform.config import Settings


PRODUCTION_PROVIDER = {
    "AI_PROVIDER": "custom",
    "AI_PROVIDER_DEPLOYMENT_CLASS": "production_eligible",
    "AI_API_KEY": "test-placeholder-key",
    "AI_BASE_URL": "https://provider.invalid/v1",
    "AI_MODEL_NAME": "production-contract-model",
    "AI_PROVIDER_MODE": "openai_compatible",
    "AI_STRUCTURED_OUTPUT_MODE": "json_schema",
    "AI_PROVIDER_TIMEOUT_SECONDS": 30,
}


OPENROUTER_FREE = {
    "AI_PROVIDER": "openrouter",
    "AI_API_KEY": "test-placeholder-key",
    "AI_BASE_URL": "https://openrouter.ai/api/v1",
    "AI_MODEL_NAME": "vendor/structured-model:free",
}


def test_development_allows_explicit_openrouter_free_model() -> None:
    config = Settings(
        _env_file=None,
        ENVIRONMENT="development",
        **OPENROUTER_FREE,
    )

    assert config.ai_provider_deployment_class == "development_only"


@pytest.mark.parametrize("environment", ["staging", "production"])
def test_release_environments_reject_openrouter_free_model(environment: str) -> None:
    with pytest.raises(ValidationError, match="OpenRouter free models are development-only"):
        Settings(
            _env_file=None,
            ENVIRONMENT=environment,
            **OPENROUTER_FREE,
        )


@pytest.mark.parametrize("environment", ["development", "staging", "production"])
@pytest.mark.parametrize("provider", ["opencode", "opencode_go"])
def test_opencode_runtime_provider_is_unsupported(environment: str, provider: str) -> None:
    with pytest.raises(ValidationError, match="AI_PROVIDER"):
        Settings(_env_file=None, ENVIRONMENT=environment, AI_PROVIDER=provider)


@pytest.mark.parametrize("environment", ["staging", "production"])
def test_release_accepts_explicit_paid_openrouter_provider(environment: str) -> None:
    config = Settings(
        _env_file=None,
        ENVIRONMENT=environment,
        **{
            **OPENROUTER_FREE,
            "AI_MODEL_NAME": "vendor/production-funded-model",
            "AI_PROVIDER_DEPLOYMENT_CLASS": "production_eligible",
        },
    )

    assert config.ai_provider_deployment_class == "production_eligible"


@pytest.mark.parametrize("field", ["AI_EXTRACTION_MODEL", "AI_ACTIVITY_GENERATION_MODEL", "AI_SEMANTIC_ASSESSMENT_MODEL",
                                   "SPEAKING_TRANSCRIPTION_MODEL", "SPEAKING_COACH_MODEL"])
def test_release_rejects_free_override_model(field: str) -> None:
    with pytest.raises(ValidationError, match="OpenRouter free models are development-only"):
        Settings(
            _env_file=None,
            ENVIRONMENT="production",
            **{
                **OPENROUTER_FREE,
                "AI_MODEL_NAME": "vendor/production-funded-model",
                "AI_PROVIDER_DEPLOYMENT_CLASS": "production_eligible",
                field: "vendor/override:free",
            },
        )


@pytest.mark.parametrize("environment", ["staging", "production"])
def test_release_rejects_free_router_alias_in_override(environment: str) -> None:
    with pytest.raises(ValidationError, match="OpenRouter free models are development-only"):
        Settings(
            _env_file=None,
            ENVIRONMENT=environment,
            **{
                **OPENROUTER_FREE,
                "AI_MODEL_NAME": "vendor/production-funded-model",
                "AI_EXTRACTION_MODEL": "openrouter/free",
                "AI_PROVIDER_DEPLOYMENT_CLASS": "production_eligible",
            },
        )


def test_development_cannot_mark_free_model_production_eligible() -> None:
    with pytest.raises(ValidationError, match="OpenRouter free models are development-only"):
        Settings(_env_file=None, ENVIRONMENT="development", **{
            **OPENROUTER_FREE, "AI_PROVIDER_DEPLOYMENT_CLASS": "production_eligible",
        })


@pytest.mark.parametrize("field", ["AI_API_KEY", "AI_BASE_URL", "AI_MODEL_NAME"])
def test_openrouter_development_requires_explicit_transport_and_model(field: str) -> None:
    config = dict(OPENROUTER_FREE)
    config.pop(field)
    with pytest.raises(ValidationError, match="OpenRouter requires"):
        Settings(_env_file=None, ENVIRONMENT="development", **config)


def test_production_requires_explicit_provider_selection() -> None:
    fields = dict(PRODUCTION_PROVIDER)
    fields.pop("AI_PROVIDER")

    with pytest.raises(ValidationError, match="AI_PROVIDER must be explicitly configured"):
        Settings(_env_file=None, ENVIRONMENT="production", **fields)


def test_production_accepts_explicit_production_eligible_provider() -> None:
    config = Settings(_env_file=None, ENVIRONMENT="production", **PRODUCTION_PROVIDER)

    assert config.AI_PROVIDER == "custom"
    assert config.ai_provider_deployment_class == "production_eligible"


def test_staging_accepts_explicit_production_eligible_provider() -> None:
    config = Settings(_env_file=None, ENVIRONMENT="staging", **PRODUCTION_PROVIDER)

    assert config.ai_provider_deployment_class == "production_eligible"


def test_test_environment_allows_fake_provider_without_credentials() -> None:
    config = Settings(_env_file=None, ENVIRONMENT="test", AI_PROVIDER="fake")

    assert config.ai_provider_deployment_class == "development_only"


def test_development_rejects_fake_provider() -> None:
    with pytest.raises(ValidationError, match="allowed only when ENVIRONMENT=test"):
        Settings(_env_file=None, ENVIRONMENT="development", AI_PROVIDER="fake")


@pytest.mark.parametrize("case", ["api_key", "base_url", "model"])
def test_production_rejects_incomplete_provider_configuration(
    case: str,
) -> None:
    fields = dict(PRODUCTION_PROVIDER)
    if case == "api_key":
        fields["AI_API_KEY"] = ""
        fields["GEMINI_API_KEY"] = ""
        message = "API key is required"
    elif case == "base_url":
        fields["AI_BASE_URL"] = "not-a-url"
        message = "valid AI_BASE_URL is required"
    else:
        fields["AI_MODEL_NAME"] = ""
        fields["AI_SEMANTIC_ASSESSMENT_MODEL"] = ""
        message = "provider model is required"

    with pytest.raises(ValidationError, match=message):
        Settings(_env_file=None, ENVIRONMENT="production", **fields)


def test_invalid_structured_output_mode_fails_configuration() -> None:
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            ENVIRONMENT="production",
            **{**PRODUCTION_PROVIDER, "AI_STRUCTURED_OUTPUT_MODE": "freeform"},
        )


def test_invalid_provider_timeout_fails_configuration() -> None:
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            ENVIRONMENT="production",
            **{**PRODUCTION_PROVIDER, "AI_PROVIDER_TIMEOUT_SECONDS": 0},
        )


def test_no_text_provider_endpoint_is_assumed_so_a_key_never_leaves_for_a_default_host(monkeypatch) -> None:
    from app.platform.llm import openai_compatible
    from app.platform.llm.port import LLMProviderError, LLMProviderFailureCategory
    config = Settings(_env_file=None, ENVIRONMENT="development", AI_PROVIDER="gemini", GEMINI_API_KEY="test-key")
    assert config.AI_BASE_URL == "" and config.ai_runtime_base_url == ""
    monkeypatch.setattr(openai_compatible, "settings", config)
    with pytest.raises(LLMProviderError) as error:
        openai_compatible.OpenAICompatibleLLMProvider()
    assert error.value.category == LLMProviderFailureCategory.CONFIGURATION
