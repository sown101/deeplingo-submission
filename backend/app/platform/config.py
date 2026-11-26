import re
from typing import Literal
from urllib.parse import urlparse

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings


EnvironmentName = Literal["development", "test", "staging", "production"]
AIProviderName = Literal["gemini", "openrouter", "custom", "vertex", "fake"]
ProviderDeploymentClass = Literal["development_only", "production_eligible"]


_RELEASE_ENVIRONMENTS = {"staging", "production"}
# Languages whose Gemini transcription passed the benchmark. Add a language only
# together with its benchmark evidence in the ADR (Japanese and Korean are next).
GEMINI_TRANSCRIPTION_QUALIFIED_LANGUAGES = frozenset({"en", "zh"})
_VERTEX_PROJECT_ID = re.compile(r"^[a-z][a-z0-9-]{4,28}[a-z0-9]$")
_VERTEX_LOCATION = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
_AZURE_SPEECH_REGION = re.compile(r"^[a-z0-9]{3,40}$")


def _valid_http_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _is_free_router_model(model: str) -> bool:
    slug = model.strip().casefold()
    return slug.endswith(":free") or slug == "openrouter/free"


class Settings(BaseSettings):
    # Server
    PROJECT_NAME: str = "DeepLingo API"
    API_V1_STR: str = "/api/v1"
    ENVIRONMENT: EnvironmentName = "development"
    PORT: int = 8000
    # The Celery broker. When set, the API also keeps the request rate limits and the voice limits (counts only,
    # never learner text) there, shared by every API process and kept across restarts; when empty they are per process.
    REDIS_URL: str = ""
    # Owner 2026-11-18: a daily cap on estimated paid AI spend for the whole system (app/platform/ai_budget.py).
    # 2 USD covers the busiest development day seen (about 0.44 USD of text) plus one long Live session with
    # scoring (about 1 USD), and keeps the ~40 USD credit for at least 20 days. 0 turns the guard off.
    AI_DAILY_BUDGET_USD: float = Field(default=2.0, ge=0, le=1000)
    # Per-IO producer bounds, isolated from Worker/Beat connection policy.
    CONTENT_PUBLISH_CONNECT_TIMEOUT_SECONDS: float = Field(default=2.0, gt=0, le=10)
    CONTENT_PUBLISH_SOCKET_TIMEOUT_SECONDS: float = Field(default=2.0, gt=0, le=10)
    # Static ownership window: strictly longer than the explicit V3 hard limit.
    CONTENT_WORK_LEASE_SECONDS: int = Field(default=2100, ge=1, le=86400)
    CONTENT_WORK_SHORT_LEASE_PROOF: bool = False

    # Browser (Web) CORS policy. Comma-separated explicit production origins,
    # e.g. "https://app.example.com". When unset, a narrow local-development
    # default (Vite dev server origins) is used; wildcard is never a default.
    BACKEND_CORS_ORIGINS: str = ""

    
    # Supabase
    SUPABASE_URL: str = ""
    SUPABASE_KEY: str = ""
    SUPABASE_SERVICE_ROLE_KEY: str = ""
    SUPABASE_JWT_ISSUER: str = ""
    SUPABASE_JWT_AUDIENCE: str = "authenticated"
    SUPABASE_JWT_JWKS_URL: str = ""
    SUPABASE_JWT_VERIFICATION_MODE: str = "jwks"
    SUPABASE_JWT_SECRET: str = ""
    
    # AI
    AI_PROVIDER: AIProviderName = "gemini"
    AI_PROVIDER_DEPLOYMENT_CLASS: ProviderDeploymentClass | None = None
    AI_API_KEY: str = ""
    GEMINI_API_KEY: str = ""
    # No default endpoint: the API key is sent only to the endpoint configured here (empty = no text provider).
    AI_BASE_URL: str = ""
    AI_MODEL_NAME: str = "gemini-2.5-flash"
    AI_EXTRACTION_MODEL: str = ""
    AI_EXTRACTION_MAX_CANDIDATES_PER_SEGMENT: int = 8
    AI_EXTRACTION_MAX_RETRIES: int = 2
    AI_PREPARATION_SUPPORT_LANGUAGE: str = "vi"
    AI_PREPARATION_MAX_SEGMENTS: int = Field(default=20, ge=1, le=100)
    # O12: videos a learner may import per rolling window when they still need AI work.
    # 2026-11-05: raised from 5 to measure real use and cost while building (owner: ~$40 budget).
    NEW_VIDEO_IMPORT_LIMIT: int = Field(default=20, ge=1, le=1000)
    NEW_VIDEO_IMPORT_WINDOW_HOURS: int = Field(default=24, ge=1, le=720)
    # M1 S2: new study regions a learner may send to AI preparation per rolling window.
    # 2026-11-05: raised from 20; opening a video now opens an AI study part, which asks for its preparation.
    REGION_PREPARATION_LIMIT: int = Field(default=60, ge=1, le=1000)
    REGION_PREPARATION_WINDOW_HOURS: int = Field(default=24, ge=1, le=720)
    AI_PREPARATION_MAX_CANDIDATES_PER_SEGMENT: int = Field(default=2, ge=1, le=8)
    AI_ACTIVITY_GENERATION_MODEL: str = ""
    AI_SEMANTIC_ASSESSMENT_MODEL: str = ""
    AI_PROVIDER_MODE: Literal["openai_compatible"] = "openai_compatible"
    AI_STRUCTURED_OUTPUT_MODE: Literal["json_schema"] = "json_schema"
    # 2026-11-05: token counts of every structured model call go to v3.ai_usage_events (no learner data).
    AI_USAGE_LEDGER_ENABLED: bool = True
    LANGFUSE_ENABLED: bool = False
    LANGFUSE_HOST: str = ""
    LANGFUSE_PUBLIC_KEY: SecretStr = Field(default=SecretStr(""), repr=False)
    LANGFUSE_SECRET_KEY: SecretStr = Field(default=SecretStr(""), repr=False)
    LANGFUSE_CAPTURE_CONTENT: bool = False
    AI_PROVIDER_TIMEOUT_SECONDS: float = Field(default=30.0, gt=0, le=120)
    # Vertex AI authenticates with Application Default Credentials, never an API key.
    VERTEX_PROJECT_ID: str = ""
    VERTEX_LOCATION: str = ""

    # Content transcript source. Exactly one source per deployment, no fallback.
    CONTENT_TRANSCRIPT_SOURCE: Literal["caption_track", "gemini_youtube"] = "caption_track"
    AI_TRANSCRIPTION_MODEL: str = ""
    YOUTUBE_DATA_API_KEY: str = ""
    CONTENT_TRANSCRIPTION_LANGUAGES: str = "en"
    # M2: 20 minutes by default since 2026-10-21 (owner decision on benchmark
    # phases A, B and C-local; accuracy measured in English only). Up to 60 minutes only where configured to
    # benchmark; 60 minutes has not passed the accuracy gate. A live environment keeps 900 until C-dev passes.
    CONTENT_MAX_VIDEO_SECONDS: int = Field(default=1200, ge=60, le=3600)
    AI_TRANSCRIPTION_TIMEOUT_SECONDS: float = Field(default=180.0, gt=0, le=300)
    AI_TRANSCRIPTION_DEADLINE_SECONDS: float = Field(default=900.0, gt=0, le=1200)
    # Empty keeps the model's default thinking; a level must be benchmarked first.
    AI_TRANSCRIPTION_THINKING_LEVEL: Literal["", "minimal", "low", "medium", "high"] = ""

    # Speaking practice. Speech credentials stay server-side.
    AZURE_SPEECH_KEY: str = ""
    AZURE_SPEECH_REGION: str = ""
    SPEAKING_TRANSCRIPTION_MODEL: str = ""
    SPEAKING_COACH_MODEL: str = ""
    SPEAKING_TICKET_SECRET: str = ""

    # Voice companion. Speech synthesis is replaceable by configuration; "azure"
    # reuses the Azure Speech key above, empty disables reply audio (text only).
    COMPANION_MODEL: str = ""
    COMPANION_TTS_PROVIDER: Literal["", "azure"] = "azure"
    COMPANION_TTS_RATE: str = Field(default="-15%", pattern=r"^[+-]\d{1,2}%$")
    # The agent's channels (comma-separated): "text" (turn-based, /learner/me/companion/*) and "voice" (Gemini Live
    # on Vertex AI, ADC only). Voice is refused outside development and test and limited to the listed learner IDs
    # (comma-separated UUIDs). The agent's behaviour (profile brief, approved grammar points, tools) has no switches.
    AGENT_CHANNELS: str = Field(default="text", pattern=r"^\s*(text|voice)(\s*,\s*(text|voice))*\s*$")
    # A separate non-persistent Redis for raw session text. When set, post-session word-use extraction runs and the
    # text channel keeps its conversations there between turns; when empty, conversations live in the memory of one
    # API process (a second process would not find them).
    COMPANION_SESSION_TEXT_REDIS_URL: str = ""
    COMPANION_SESSION_EVENTS_MODEL: str = ""
    COMPANION_REALTIME_ALLOWED_USERS: str = ""
    COMPANION_REALTIME_PROJECT: str = ""
    COMPANION_REALTIME_REGION: str = Field(default="us-central1", pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$")
    COMPANION_REALTIME_MODEL: str = Field(default="gemini-3.8-live", pattern=r"^[a-z0-9][a-z0-9.\-]{1,62}$")
    COMPANION_REALTIME_MAX_SESSION_SECONDS: int = Field(default=600, ge=30, le=1800)
    COMPANION_REALTIME_DAILY_SECONDS: int = Field(default=1800, ge=60, le=14400)
    COMPANION_REALTIME_MAX_CONCURRENT: int = Field(default=3, ge=1, le=50)
    COMPANION_REALTIME_SILENCE_MS: int = Field(default=1000, ge=200, le=5000)

    @property
    def ai_runtime_api_key(self) -> str:
        if self.AI_PROVIDER == "vertex":
            return ""
        return self.AI_API_KEY or (self.GEMINI_API_KEY if self.AI_PROVIDER == "gemini" else "")

    @property
    def ai_uses_application_default_credentials(self) -> bool:
        return self.AI_PROVIDER == "vertex"

    @property
    def ai_runtime_base_url(self) -> str:
        if self.AI_PROVIDER != "vertex":
            return self.AI_BASE_URL
        host = (
            "aiplatform.googleapis.com" if self.VERTEX_LOCATION == "global"
            else f"{self.VERTEX_LOCATION}-aiplatform.googleapis.com"
        )
        return (
            f"https://{host}/v1/projects/{self.VERTEX_PROJECT_ID}"
            f"/locations/{self.VERTEX_LOCATION}/endpoints/openapi"
        )

    @property
    def content_transcription_language_list(self) -> list[str]:
        return [code.strip().lower() for code in self.CONTENT_TRANSCRIPTION_LANGUAGES.split(",") if code.strip()]

    @property
    def cors_origin_list(self) -> list[str]:
        return [
            origin.strip()
            for origin in self.BACKEND_CORS_ORIGINS.split(",")
            if origin.strip()
        ]

    @property
    def ai_provider_deployment_class(self) -> ProviderDeploymentClass | None:
        if self.AI_PROVIDER == "fake":
            return "development_only"
        if self.AI_PROVIDER == "openrouter" and any(
            _is_free_router_model(model) for model in self._configured_models()
        ):
            return "development_only"
        return self.AI_PROVIDER_DEPLOYMENT_CLASS

    def _configured_models(self) -> tuple[str, ...]:
        return tuple(
            model for model in (
                self.AI_MODEL_NAME,
                self.AI_EXTRACTION_MODEL,
                self.AI_ACTIVITY_GENERATION_MODEL,
                self.AI_SEMANTIC_ASSESSMENT_MODEL,
                self.SPEAKING_TRANSCRIPTION_MODEL,
                self.SPEAKING_COACH_MODEL,
            ) if model.strip()
        )

    @model_validator(mode="after")
    def validate_semantic_provider_policy(self) -> "Settings":
        environment = self.ENVIRONMENT
        provider = self.AI_PROVIDER

        if self.CONTENT_WORK_SHORT_LEASE_PROOF and environment not in {"development", "test"}:
            raise ValueError("Short Content lease proof is development/test-only")
        if self.CONTENT_WORK_LEASE_SECONDS < 2100 and not self.CONTENT_WORK_SHORT_LEASE_PROOF:
            raise ValueError("Content lease must cover the 1800-second hard limit plus 300-second margin")

        if provider == "fake" and self.AI_PROVIDER_DEPLOYMENT_CLASS == "production_eligible":
            raise ValueError("The fake AI provider cannot be marked production-eligible")
        if provider == "fake" and environment != "test":
            raise ValueError("The fake AI provider is allowed only when ENVIRONMENT=test")
        if provider == "openrouter":
            parsed = urlparse(self.AI_BASE_URL)
            if not self.AI_API_KEY:
                raise ValueError("OpenRouter requires AI_API_KEY")
            if ("AI_BASE_URL" not in self.model_fields_set or parsed.scheme != "https"
                    or parsed.hostname != "openrouter.ai" or parsed.path.rstrip("/") != "/api/v1"):
                raise ValueError("OpenRouter requires the official HTTPS AI_BASE_URL")
            if "AI_MODEL_NAME" not in self.model_fields_set or not self.AI_MODEL_NAME.strip():
                raise ValueError("OpenRouter requires an explicit AI_MODEL_NAME")
            if self.AI_MODEL_NAME.strip().casefold() == "openrouter/auto":
                raise ValueError("OpenRouter requires an explicit model, not the auto router")
        if self.AZURE_SPEECH_KEY and not _AZURE_SPEECH_REGION.fullmatch(self.AZURE_SPEECH_REGION):
            raise ValueError("Azure speech requires a valid AZURE_SPEECH_REGION")
        if self.SPEAKING_TICKET_SECRET and len(self.SPEAKING_TICKET_SECRET) < 32:
            raise ValueError("SPEAKING_TICKET_SECRET must be at least 32 characters")
        if self.CONTENT_TRANSCRIPT_SOURCE == "gemini_youtube":
            if environment in _RELEASE_ENVIRONMENTS:
                raise ValueError("Gemini YouTube transcription is accepted for development only")
            if not self.GEMINI_API_KEY:
                raise ValueError("Gemini YouTube transcription requires GEMINI_API_KEY")
            if not self.AI_TRANSCRIPTION_MODEL.strip():
                raise ValueError("Gemini YouTube transcription requires an explicit AI_TRANSCRIPTION_MODEL")
            if not self.YOUTUBE_DATA_API_KEY:
                raise ValueError("Gemini YouTube transcription requires YOUTUBE_DATA_API_KEY")
            languages = self.content_transcription_language_list
            if not languages or not set(languages) <= GEMINI_TRANSCRIPTION_QUALIFIED_LANGUAGES:
                raise ValueError("CONTENT_TRANSCRIPTION_LANGUAGES must list only languages qualified "
                                 "for Gemini transcription")
        if provider == "vertex":
            if not _VERTEX_PROJECT_ID.fullmatch(self.VERTEX_PROJECT_ID):
                raise ValueError("Vertex requires a valid VERTEX_PROJECT_ID")
            if not _VERTEX_LOCATION.fullmatch(self.VERTEX_LOCATION):
                raise ValueError("Vertex requires a valid VERTEX_LOCATION")
            if self.AI_API_KEY:
                raise ValueError("Vertex uses Application Default Credentials; AI_API_KEY must be empty")
            if "AI_BASE_URL" in self.model_fields_set:
                raise ValueError("Vertex derives its endpoint; AI_BASE_URL must not be set")
            if "AI_MODEL_NAME" not in self.model_fields_set or not self.AI_MODEL_NAME.strip():
                raise ValueError("Vertex requires an explicit AI_MODEL_NAME")
        if provider == "openrouter" and self.ai_provider_deployment_class == "development_only" and (
            environment in _RELEASE_ENVIRONMENTS
            or self.AI_PROVIDER_DEPLOYMENT_CLASS == "production_eligible"
        ):
            raise ValueError(
                "OpenRouter free models are development-only and cannot be marked production-eligible"
            )

        if environment not in _RELEASE_ENVIRONMENTS:
            return self

        if "AI_PROVIDER" not in self.model_fields_set:
            raise ValueError(f"AI_PROVIDER must be explicitly configured when ENVIRONMENT={environment}")
        if self.ai_provider_deployment_class != "production_eligible":
            raise ValueError(
                f"A production-eligible semantic provider is required when ENVIRONMENT={environment}"
            )
        resolved_api_key = self.ai_runtime_api_key
        if not resolved_api_key and not self.ai_uses_application_default_credentials:
            raise ValueError(f"A semantic provider API key is required when ENVIRONMENT={environment}")
        if not self.ai_uses_application_default_credentials and (
            "AI_BASE_URL" not in self.model_fields_set or not _valid_http_url(self.AI_BASE_URL)
        ):
            raise ValueError(
                f"An explicit valid AI_BASE_URL is required when ENVIRONMENT={environment}"
            )
        explicit_model = (
            self.AI_SEMANTIC_ASSESSMENT_MODEL
            if "AI_SEMANTIC_ASSESSMENT_MODEL" in self.model_fields_set
            else self.AI_MODEL_NAME if "AI_MODEL_NAME" in self.model_fields_set else ""
        )
        if not explicit_model.strip():
            raise ValueError(
                f"An explicit semantic provider model is required when ENVIRONMENT={environment}"
            )
        return self

    class Config:
        env_file = ".env"
        extra = "ignore"
        case_sensitive = True  # Thêm dòng này

settings = Settings()
