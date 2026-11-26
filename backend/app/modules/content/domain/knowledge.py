from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.modules.content.domain.extraction import Candidate


class ConceptType(str, Enum):
    VOCABULARY = "vocabulary"
    GRAMMAR = "grammar"
    EXPRESSION = "expression"
    PHRASAL_VERB = "phrasal_verb"
    IDIOM = "idiom"
    COLLOCATION = "collocation"
    PRONUNCIATION = "pronunciation"
    PRAGMATICS = "pragmatics"
    CULTURAL_NOTE = "cultural_note"


class DictionaryEntry(BaseModel):
    id: UUID | None = None
    language_code: str
    headword: str
    normalized_headword: str
    part_of_speech: str = ""
    pronunciation: str | None = None
    definitions: list[dict[str, Any]] = Field(default_factory=list)
    examples: list[dict[str, Any]] = Field(default_factory=list)
    provider: str | None = None
    provider_metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None
    updated_at: datetime | None = None


class Concept(BaseModel):
    id: UUID | None = None
    language_code: str
    type: ConceptType
    canonical_text: str
    normalized_text: str
    sense_key: str = Field(min_length=1, max_length=500)
    difficulty_level: str | None = None
    difficulty_score: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ConceptDictionaryLink(BaseModel):
    concept_id: UUID
    dictionary_entry_id: UUID
    relation_type: str = "supports"
    created_at: datetime | None = None


class LearningObject(BaseModel):
    id: UUID | None = None
    concept_id: UUID
    video_id: UUID
    transcript_segment_id: UUID
    occurrence_index: int = 1
    evidence_text: str
    start_codepoint: int | None = Field(default=None, ge=0)
    end_codepoint: int | None = Field(default=None, gt=0)
    previous_context: str | None = None
    next_context: str | None = None
    start_ms: int
    end_ms: int
    difficulty_score: float | None = None
    learning_value_score: float | None = None
    ai_confidence: float | None = None
    extraction_status: str = "candidate"
    source: str = "ai"
    supported_activity_types: list[str] = Field(default_factory=list)
    raw_ai_diagnostics: dict[str, Any] | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @model_validator(mode="after")
    def paired_occurrence_span(self):
        if (self.start_codepoint is None) != (self.end_codepoint is None):
            raise ValueError("LearningObject occurrence offsets must be paired")
        if self.start_codepoint is not None and self.end_codepoint <= self.start_codepoint:
            raise ValueError("LearningObject occurrence span must be non-empty")
        return self


class DictionaryEntryDraft(BaseModel):
    headword: str
    normalized_headword: str
    part_of_speech: str = ""
    pronunciation: str | None = None
    definitions: list[dict[str, Any]] = Field(default_factory=list)
    examples: list[dict[str, Any]] = Field(default_factory=list)
    provider: str
    provider_metadata: dict[str, Any] = Field(default_factory=dict)


class ResolvedCandidate(BaseModel):
    candidate: Candidate
    dictionary_entry: DictionaryEntry | None = None
    concept: Concept
    learning_object: LearningObject
    concept_dictionary_link: ConceptDictionaryLink | None = None
    status: dict[str, str] = Field(default_factory=dict)


class CandidateResolutionResult(BaseModel):
    source_segment_id: UUID
    language_code: str
    resolved: list[ResolvedCandidate] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class EnrichmentDifficulty(BaseModel):
    model_config = ConfigDict(extra="forbid")

    framework: str
    level: str | None = None
    score: float = Field(ge=0, le=1)
    confidence: float = Field(ge=0, le=1)
    provenance: str = "ai"


class EnrichmentLearningValue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    score: float = Field(ge=0, le=1)
    confidence: float = Field(ge=0, le=1)
    rationale: str | None = None


DICTIONARY_SENSE_ID_PATTERN = r"^[a-z]+:[0-9a-f]{16}$"


class LLMLearningObjectEnrichment(BaseModel):
    """Structured enrichment output.

    `sense_id` is required and nullable: the model names one offered dictionary sense or
    explicitly none. Whether the ID was actually offered is checked by the application.
    """

    model_config = ConfigDict(extra="forbid")

    sense_id: str | None = Field(pattern=DICTIONARY_SENSE_ID_PATTERN)
    contextual_meaning: str
    explanation: str
    difficulty: EnrichmentDifficulty
    learning_value: EnrichmentLearningValue
    confidence: float = Field(ge=0, le=1)

    @field_validator("contextual_meaning", "explanation")
    @classmethod
    def validate_text(cls, value: str) -> str:
        text = " ".join((value or "").strip().split())
        if not text:
            raise ValueError("Enrichment text fields must be non-empty")
        if len(text) > 600:
            raise ValueError("Enrichment text fields must be concise")
        return text


class LearningObjectEnrichmentResult(BaseModel):
    learning_object_id: UUID
    concept_id: UUID
    transcript_segment_id: UUID
    source_language_code: str
    target_language_code: str
    contextual_meaning: str
    explanation: str
    translation: str | None = None
    translation_source: str | None = None
    difficulty: EnrichmentDifficulty
    learning_value: EnrichmentLearningValue
    confidence: float = Field(ge=0, le=1)
    provider: str
    model: str
    prompt_version: str
    status: str
    diagnostics: dict[str, Any] = Field(default_factory=dict)
