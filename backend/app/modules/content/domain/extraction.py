from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class CandidateType(str, Enum):
    WORD = "WORD"
    PHRASE = "PHRASE"
    COLLOCATION = "COLLOCATION"
    PHRASAL_VERB = "PHRASAL_VERB"
    IDIOM = "IDIOM"
    GRAMMAR_PATTERN = "GRAMMAR_PATTERN"
    OTHER = "OTHER"


class LearningUnit(str, Enum):
    """Model judgment of whether a span is worth learning (DEBT A20); only REUSABLE is kept."""

    REUSABLE = "reusable"
    PROPER_NAME = "proper_name"
    TITLE_OR_BRAND = "title_or_brand"
    FREE_COMBINATION = "free_combination"
    FILLER = "filler"


class GrammarCatalogueItem(BaseModel):
    """One curriculum grammar point offered to extraction by key."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    key: str
    title: str
    pattern: str
    forms: tuple[str, ...] = ()


class Candidate(BaseModel):
    surface_form: str
    normalized_form: str
    sense_gloss: str
    sense_evidence: str
    candidate_type: CandidateType
    evidence_start: int | None = None
    evidence_end: int | None = None
    surface_occurrence_index: int | None = Field(default=None, ge=1)
    source_segment_id: UUID
    confidence: float = Field(ge=0, le=1)
    rationale: str | None = None
    context: str | None = None
    # Set by the server from the grammar catalogue, never by the model.
    grammar_key: str | None = None
    grammar_label: str | None = None

    @field_validator("surface_form")
    @classmethod
    def preserve_exact_surface(cls, value: str) -> str:
        if not value or not value.strip() or len(value) > 500:
            raise ValueError("Candidate surface_form must be non-empty and concise")
        return value

    @field_validator("normalized_form", "sense_gloss", "sense_evidence")
    @classmethod
    def require_non_empty(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("Candidate text fields must be non-empty")
        return value


class CandidateExtractionResult(BaseModel):
    source_segment_id: UUID
    candidates: list[Candidate] = Field(default_factory=list)
    model_metadata: dict[str, Any] = Field(default_factory=dict)
    extraction_metadata: dict[str, Any] = Field(default_factory=dict)
    errors: list[str] = Field(default_factory=list)


class LLMCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    surface_form: str
    normalized_form: str
    sense_gloss: str
    sense_evidence: str
    candidate_type: CandidateType
    learning_unit: LearningUnit
    surface_occurrence_index: int | None = Field(default=None, ge=1)
    confidence: float = Field(ge=0, le=1)
    rationale: str | None = None
    context: str | None = None

    @field_validator("surface_form")
    @classmethod
    def preserve_exact_surface(cls, value: str) -> str:
        if not value or not value.strip() or len(value) > 500:
            raise ValueError("Candidate surface_form must be non-empty and concise")
        return value

    @field_validator("normalized_form", "sense_gloss", "sense_evidence")
    @classmethod
    def require_non_empty(cls, value: str) -> str:
        text = " ".join((value or "").strip().split())
        if not text:
            raise ValueError("Candidate text fields must be non-empty")
        if len(text) > 500:
            raise ValueError("Candidate text fields must be concise")
        return text


class LLMCandidateResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidates: list[LLMCandidate] = Field(default_factory=list)


class GrammarSpanStatus(str, Enum):
    """Whether a grammar use is fully inside the target segment (subtitles split sentences)."""

    COMPLETE = "complete"
    SPLIT = "split"


class LLMGrammarUse(BaseModel):
    """One catalogue grammar point the model sees in the target segment (`grammar_selection_v1`)."""

    model_config = ConfigDict(extra="forbid")

    grammar_key: str = Field(min_length=1, max_length=80)
    surface_form: str = Field(min_length=1, max_length=200)
    sense_evidence: str = Field(min_length=1, max_length=500)
    span_status: GrammarSpanStatus
    confidence: float = Field(ge=0, le=1)


class LLMGrammarResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    uses: list[LLMGrammarUse] = Field(default_factory=list)
