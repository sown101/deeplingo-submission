"""The identity of a study region: its first and last sentence of one transcript version.

A region is not a stored row, so its id is made from the two segment ids. Every flow that practises in a
region logs it as `source_id` with `source_type="video_region"`, and the region result reads the log back by it.
"""
from uuid import UUID


def region_id(start_segment_id: UUID | str, end_segment_id: UUID | str) -> str:
    return f"{str(start_segment_id).lower()}_{str(end_segment_id).lower()}"


def split_region_id(value: str) -> tuple[UUID, UUID] | None:
    """(first segment, last segment), or None when the text is not a region id."""
    parts = value.split("_") if isinstance(value, str) else []
    if len(parts) != 2:
        return None
    try:
        start, end = UUID(parts[0]), UUID(parts[1])
    except ValueError:
        return None
    return (start, end) if region_id(start, end) == value else None
