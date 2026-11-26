from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ProductVideoProcessingStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


class LearningPreparationStatus(str, Enum):
    NOT_STARTED = "not_started"
    PROCESSING = "processing"
    READY = "ready"
    NO_CONTENT = "no_content"
    FAILED = "failed"


class ContentProcessingFailureCode(str, Enum):
    INVALID_VIDEO_URL = "invalid_video_url"
    VIDEO_UNAVAILABLE = "video_unavailable"
    TRANSCRIPT_UNAVAILABLE = "transcript_unavailable"
    UNSUPPORTED_CONTENT = "unsupported_content"
    PROCESSING_FAILED = "processing_failed"


class LearnerVideoImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str = Field(min_length=1, max_length=2048)

    @field_validator("url")
    @classmethod
    def normalize_url(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("url is required")
        return normalized


class LearnerVideo(BaseModel):
    id: UUID
    user_id: UUID
    video_id: UUID
    created_at: datetime
    updated_at: datetime


class LibraryVideoFailure(BaseModel):
    code: ContentProcessingFailureCode
    retryable: bool
    message: str


class LibraryVideoSummary(BaseModel):
    library_item_id: UUID
    video_id: UUID
    title: str
    thumbnail_url: str | None = None
    duration_ms: int | None = Field(default=None, ge=0)
    source: str
    processing_status: ProductVideoProcessingStatus
    learning_status: LearningPreparationStatus = LearningPreparationStatus.NOT_STARTED
    learning_object_count: int = Field(default=0, ge=0)
    learning_prepared_language_code: str | None = None
    language_code: str
    added_at: datetime
    failure: LibraryVideoFailure | None = None


class LibraryVideoDetail(LibraryVideoSummary):
    description: str | None = None
    transcript_available: bool


class LearnerVideoImportResponse(BaseModel):
    command_status: str
    item: LibraryVideoDetail


@dataclass(frozen=True)
class LibraryOccurrence:
    """One trusted occurrence of a word in a video of the learner's own Library (M1 S7b)."""

    learning_object_id: UUID
    transcript_segment_id: UUID  # the execution path rechecks the full source chain
    sentence: str
    target_form: str
    library_item_id: UUID | None = None  # the learner's own Library item, for "Xem ngữ cảnh"
    start_ms: int | None = None
    meaning: str | None = None  # in the support language, translated from the dictionary sense
    part_of_speech: str | None = None
