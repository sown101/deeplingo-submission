from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class SafePlaybackModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PlayableVideo(SafePlaybackModel):
    library_item_id: UUID
    video_id: UUID
    provider: Literal["youtube"]
    external_video_id: str = Field(pattern=r"^[A-Za-z0-9_-]{11}$")
    title: str
    language_code: str
    duration_ms: int | None = Field(default=None, ge=0)


class SegmentTranslationView(SafePlaybackModel):
    language_code: str
    text: str


class SegmentRomanizationView(SafePlaybackModel):
    system: str
    text: str


class LearningObjectOccurrenceView(SafePlaybackModel):
    learning_object_id: UUID
    start_codepoint: int = Field(ge=0)
    end_codepoint: int = Field(gt=0)

    @model_validator(mode="after")
    def nonempty(self):
        if self.end_codepoint <= self.start_codepoint:
            raise ValueError("Invalid occurrence span")
        return self


class GrammarOccurrenceView(LearningObjectOccurrenceView):
    grammar_key: str = Field(pattern=r"^[a-z]{2,3}\.[a-z0-9_.]+$", max_length=80)


class TranscriptSegmentView(SafePlaybackModel):
    segment_id: UUID
    sequence: int = Field(ge=1)
    text: str = Field(min_length=1)
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)
    translation: SegmentTranslationView | None = None
    romanizations: list[SegmentRomanizationView] = Field(default_factory=list)
    learning_objects: list[GrammarOccurrenceView | LearningObjectOccurrenceView] = Field(default_factory=list)

    @model_validator(mode="after")
    def valid_timing(self):
        if self.end_ms <= self.start_ms or not self.text.strip():
            raise ValueError("Invalid transcript segment")
        if any(item.end_codepoint > len(self.text) for item in self.learning_objects):
            raise ValueError("Occurrence extends beyond transcript segment")
        return self


class VideoTranscriptView(SafePlaybackModel):
    library_item_id: UUID
    language_code: str
    translation_language_code: str | None = None
    segments: list[TranscriptSegmentView]
