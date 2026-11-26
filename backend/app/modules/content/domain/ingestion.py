from typing import Any

from pydantic import BaseModel, Field

from app.modules.content.domain.catalog import TranscriptSegment, Video, VideoTranscript


class SourceVideoMetadata(BaseModel):
    source: str = "youtube"
    external_video_id: str
    watch_url: str
    title: str
    description: str | None = None
    thumbnail_url: str | None = None
    duration_ms: int | None = None
    published_at: str | None = None
    original_language_code: str = "en"
    external_channel_id: str | None = None
    channel_name: str | None = None
    channel_url: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class SourceTranscriptSegment(BaseModel):
    sequence_number: int | None = None
    start_seconds: float
    duration_seconds: float
    text: str


class SourceTranscriptTrack(BaseModel):
    language_code: str
    source: str = "caption_track"
    is_original: bool = False
    provider_metadata: dict[str, Any] = Field(default_factory=dict)
    segments: list[SourceTranscriptSegment]


class NormalizedTranscriptSegment(BaseModel):
    sequence_number: int
    start_ms: int
    end_ms: int
    text: str


class ContentIngestionResult(BaseModel):
    video: Video
    transcript: VideoTranscript
    segments: list[TranscriptSegment]
    translation_count: int = 0
    romanization_count: int = 0
