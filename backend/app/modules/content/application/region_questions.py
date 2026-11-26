"""M1 S6: comprehension questions of one claimed study region, generated once and shared.

The last step of region preparation. One model call proposes the questions; the validator keeps the
grounded ones and the claim-fenced write stores them with the region (`ready`), or records that the
region has none (`none`) or that generation failed (`failed`). A failed generation never fails the
region's vocabulary preparation and is never a learner failure.
"""
from __future__ import annotations

import logging
from collections import Counter

from pydantic import ValidationError

from app.modules.content.application.ports import RegionQuestionProvider
from app.modules.content.application.prompts import REGION_QUESTIONS_PROMPT_VERSION, build_region_questions_prompt
from app.modules.content.application.store_ports import ClaimedRegionQuestionWriter
from app.modules.content.domain.region_questions import (
    MAX_REGION_QUESTIONS,
    REGION_QUESTION_VALIDATION_VERSION,
    RegionSentence,
    validate_region_questions,
)
from app.platform.llm.port import LLMProviderError

logger = logging.getLogger(__name__)

REGION_QUESTIONS_GENERATION_VERSION = f"{REGION_QUESTIONS_PROMPT_VERSION}/{REGION_QUESTION_VALIDATION_VERSION}"


class RegionQuestionGenerationService:
    def __init__(self, *, provider: RegionQuestionProvider, writer: ClaimedRegionQuestionWriter):
        self.provider = provider
        self.writer = writer

    def generate(self, *, sentences: list[RegionSentence], source_language: str, support_language: str) -> str:
        """Generate, validate and store; returns the stored status. Stale claims propagate."""
        prompt = build_region_questions_prompt(
            source_language=source_language, support_language=support_language,
            sentences=[(sentence.ref, sentence.text) for sentence in sentences], max_questions=MAX_REGION_QUESTIONS,
        )
        try:
            proposed = self.provider.generate(prompt)
        except (LLMProviderError, ValidationError, ValueError) as exc:
            # Fail closed: no questions for this region rather than unchecked ones.
            logger.warning("Region questions not generated error=%s", type(exc).__name__)
            self.writer.write(status="failed", questions=[])
            return "failed"
        rejected: Counter = Counter()
        questions = validate_region_questions(
            proposed, sentences, generation_version=REGION_QUESTIONS_GENERATION_VERSION, rejected=rejected,
        )
        status = "ready" if questions else "none"
        self.writer.write(status=status, questions=questions)
        logger.info("Region questions status=%s proposed=%s kept=%s rejected=%s version=%s", status,
                    len(proposed.questions), len(questions),
                    ",".join(f"{reason}:{count}" for reason, count in sorted(rejected.items())) or "-",
                    REGION_QUESTIONS_GENERATION_VERSION)
        return status
