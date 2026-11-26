"""M1 S1 video workspace values: watch position and the study region of one Library item.

A study region is a contiguous segment range of one transcript version. Its bounds keep a
region the size of a short practice (spec: usually 30–120 seconds) so later per-region
preparation stays bounded. Watch position is presentation state, never learning Evidence.
"""
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.modules.content.domain.catalog import TranscriptSegment

MAX_POSITION_MS = 86_400_000
MAX_REGION_SEGMENTS = 40
MAX_REGION_MS = 300_000


class LearnerVideoWorkspace(BaseModel):
    library_item_id: UUID
    user_id: UUID
    position_ms: int | None = None
    region_transcript_id: UUID | None = None
    region_start_segment_id: UUID | None = None
    region_end_segment_id: UUID | None = None
    updated_at: datetime | None = None


class RegionRejected(ValueError):
    """The requested range is not a valid study region (order or size)."""


def region_bounds(start: TranscriptSegment, end: TranscriptSegment) -> tuple[int, int, int]:
    """(start_ms, end_ms, segment_count) of a region from its first to its last segment.

    Both segments must already be known to belong to the same transcript version.
    """
    if start.transcript_id != end.transcript_id:
        raise RegionRejected("Region segments belong to different transcripts.")
    count = end.sequence_number - start.sequence_number + 1
    if count < 1 or end.end_ms <= start.start_ms:
        raise RegionRejected("Region ends before it starts.")
    if count > MAX_REGION_SEGMENTS or end.end_ms - start.start_ms > MAX_REGION_MS:
        raise RegionRejected("Region is too long.")
    return start.start_ms, end.end_ms, count


def clamp_position(position_ms: int, duration_ms: int | None) -> int:
    """A requested watch position bounded to the video (the server's duration when known)."""
    bounded = max(0, min(position_ms, MAX_POSITION_MS))
    return min(bounded, duration_ms) if duration_ms and duration_ms > 0 else bounded
