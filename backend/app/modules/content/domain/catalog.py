from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class Language(BaseModel):
    code: str
    name_en: str
    name_native: str
    script: str
    is_active: bool
    display_order: int


class Channel(BaseModel):
    id: UUID | None = None
    source: str = "youtube"
    external_channel_id: str
    channel_name: str
    channel_url: str | None = None
    description: str | None = None
    thumbnail_url: str | None = None
    subscriber_count: int | None = None
    category: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class Video(BaseModel):
    id: UUID | None = None
    source: str = "youtube"
    external_video_id: str
    channel_id: UUID | None = None
    original_language_code: str
    title: str
    description: str | None = None
    thumbnail_url: str | None = None
    duration_ms: int | None = None
    published_at: datetime | None = None
    processing_status: str = "pending"
    processing_error: str | None = None
    processing_error_code: str | None = None
    processing_retryable: bool = False
    processing_started_at: datetime | None = None
    processing_completed_at: datetime | None = None
    learning_status: str = "not_started"
    learning_object_count: int = 0
    learning_prepared_language_code: str | None = None
    learning_preparation_version: str | None = None
    learning_failure_code: str | None = None
    learning_retryable: bool = False
    learning_started_at: datetime | None = None
    learning_completed_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None
    updated_at: datetime | None = None


class VideoTranscript(BaseModel):
    id: UUID | None = None
    video_id: UUID
    language_code: str
    source: str = "caption_track"
    is_original: bool = False
    provider_metadata: dict[str, Any] = Field(default_factory=dict)


class TranscriptSegment(BaseModel):
    id: UUID | None = None
    transcript_id: UUID
    sequence_number: int
    start_ms: int
    end_ms: int
    text: str
    created_at: datetime | None = None
    updated_at: datetime | None = None


class SegmentTranslation(BaseModel):
    transcript_segment_id: UUID
    language_code: str
    text: str
    source: str = "caption_track"
    confidence: float | None = None
    provider_metadata: dict[str, Any] = Field(default_factory=dict)


class RomanizationSystem(BaseModel):
    id: UUID
    language_code: str
    code: str
    name: str
    standard_status: str
    notes: str | None = None
    is_active: bool = True


class SegmentRomanization(BaseModel):
    transcript_segment_id: UUID
    romanization_system_id: UUID
    text: str
    source: str = "hybrid"
    confidence: float | None = None
