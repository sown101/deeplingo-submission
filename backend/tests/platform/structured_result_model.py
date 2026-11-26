"""A structured-output model for the provider adapter tests (kept from the removed AI grader; test-only)."""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SemanticAssessmentVerdict(str, Enum):
    CORRECT = "correct"
    PARTIALLY_CORRECT = "partially_correct"
    INCORRECT = "incorrect"
    UNCERTAIN = "uncertain"


class LLMSemanticAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verdict: SemanticAssessmentVerdict
    score: float = Field(ge=0, le=1, allow_inf_nan=False)
    confidence: float = Field(ge=0, le=1, allow_inf_nan=False)
    rationale: str = Field(
        description=(
            "Brief abstract judgment reason. Never quote or repeat the learner response, "
            "semantic target, contextual meaning, rubric, or reference answer."
        )
    )
    evidence_alignment: str = Field(
        description=(
            "Brief abstract alignment statement. Describe alignment with the selected target "
            "sense without quoting any trusted or learner text."
        )
    )

    @field_validator("rationale", "evidence_alignment")
    @classmethod
    def require_concise_text(cls, value: str) -> str:
        text = " ".join((value or "").strip().split())
        if not text:
            raise ValueError("semantic assessment text fields must be non-empty")
        if len(text) > 600:
            raise ValueError("semantic assessment text fields must be concise")
        return text
