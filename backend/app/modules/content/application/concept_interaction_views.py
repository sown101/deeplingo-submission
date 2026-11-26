"""Learner-safe Concept-in-one-occurrence projection."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class DictionarySenseView(BaseModel):
    """The dictionary sense a meaning was translated from, with the credit its licence requires."""

    model_config = ConfigDict(extra="forbid")

    headword: str = Field(min_length=1, max_length=500)
    reading: str | None = Field(default=None, max_length=200)
    part_of_speech: str | None = Field(default=None, max_length=50)
    definition: str = Field(min_length=1, max_length=1000)
    source_name: str = Field(min_length=1, max_length=100)
    source_url: str = Field(min_length=1, max_length=500)
    license_name: str = Field(min_length=1, max_length=100)
    license_url: str = Field(min_length=1, max_length=500)


class ConceptInteractionView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    library_item_id: UUID
    learning_object_id: UUID
    expression: str = Field(min_length=1, max_length=500)
    occurrence_text: str = Field(min_length=1)
    source_segment_text: str = Field(min_length=1)
    start_codepoint: int = Field(ge=0)
    end_codepoint: int = Field(gt=0)
    learning_language_code: str = Field(min_length=1)
    support_language_code: str = Field(min_length=1)
    contextual_meaning: str = Field(min_length=1, max_length=600)
    explanation: str | None = Field(default=None, max_length=600)
    # "dictionary" only when the meaning was translated from a credited dictionary sense.
    meaning_provenance: Literal["dictionary", "unverified"] = "unverified"
    dictionary_sense: DictionarySenseView | None = None

    @model_validator(mode="after")
    def exact_occurrence(self):
        if not 0 <= self.start_codepoint < self.end_codepoint <= len(self.source_segment_text):
            raise ValueError("Occurrence span is outside its source segment")
        if self.source_segment_text[self.start_codepoint:self.end_codepoint] != self.occurrence_text:
            raise ValueError("Occurrence text differs from its source segment")
        if not self.contextual_meaning.strip() or (self.explanation is not None and not self.explanation.strip()):
            raise ValueError("Concept context must be meaningful")
        if (self.meaning_provenance == "dictionary") != (self.dictionary_sense is not None):
            raise ValueError("Dictionary provenance requires its dictionary sense")
        return self
