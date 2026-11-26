from __future__ import annotations

from app.platform.config import settings
from app.modules.content.domain.knowledge import LLMLearningObjectEnrichment
from app.platform.llm.openai_compatible import OpenAICompatibleLLMProvider


class OpenAICompatibleLearningObjectEnrichmentProvider:
    provider_name = "openai_compatible"

    def __init__(self, api_key: str | None = None, base_url: str | None = None, model_name: str | None = None):
        self.provider = OpenAICompatibleLLMProvider(
            api_key=api_key,
            base_url=base_url,
            model_name=model_name or settings.AI_EXTRACTION_MODEL or settings.AI_MODEL_NAME,
        )
        self.model_name = self.provider.model_name

    def enrich(self, prompt: str) -> LLMLearningObjectEnrichment:
        return self.provider.generate_structured(
            prompt,
            LLMLearningObjectEnrichment,
            system_prompt="You enrich existing source-grounded language LearningObjects and return JSON only.",
            temperature=0.2,
            max_tokens=1600,
        )
