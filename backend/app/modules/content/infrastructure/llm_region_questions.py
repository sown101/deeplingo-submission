from __future__ import annotations

from app.modules.content.domain.region_questions import LLMRegionQuestionSet
from app.platform.config import settings
from app.platform.llm.openai_compatible import OpenAICompatibleLLMProvider


class OpenAICompatibleRegionQuestionProvider:
    """M1 S6: the configured extraction model proposes region comprehension questions."""

    provider_name = "openai_compatible"

    def __init__(self, api_key: str | None = None, base_url: str | None = None, model_name: str | None = None):
        self.provider = OpenAICompatibleLLMProvider(
            api_key=api_key,
            base_url=base_url,
            model_name=model_name or settings.AI_EXTRACTION_MODEL or settings.AI_MODEL_NAME,
        )
        self.model_name = self.provider.model_name

    def generate(self, prompt: str) -> LLMRegionQuestionSet:
        return self.provider.generate_structured(
            prompt,
            LLMRegionQuestionSet,
            system_prompt="You write grounded comprehension questions about a video excerpt and return JSON only.",
            temperature=0.2,
            max_tokens=1600,
        )
