"""Which study region a practice row belongs to, for the learning log.

The client names the region it practised in; the server only accepts it when both ends are sentences of the
practised sentence's transcript and the sentence lies between them. Anything else is logged against the Library item,
as before regions had an id.
"""
from uuid import UUID

from app.kernel.region_ids import split_region_id


def region_source(segments, segment, library_item_id: UUID, region_id: str | None) -> str:
    fallback = str(library_item_id)
    ends = split_region_id(region_id) if region_id else None
    if ends is None:
        return fallback
    try:
        start, end = (segments.get_by_id(segment_id) for segment_id in ends)
    except Exception:
        return fallback
    if start is None or end is None or not start.transcript_id == end.transcript_id == segment.transcript_id:
        return fallback
    return region_id if start.sequence_number <= segment.sequence_number <= end.sequence_number else fallback
