"""Resolve exact, half-open Python/Unicode-codepoint source spans."""


class OccurrenceSpanError(ValueError):
    pass


def resolve_occurrence_span(
    source_text: str,
    occurrence_text: str,
    *,
    start_codepoint: int | None = None,
    end_codepoint: int | None = None,
    occurrence_ordinal: int | None = None,
) -> tuple[int, int]:
    """Return a verified span, never a normalized or guessed substring.

    An ordinal is a one-based hint among exact (including overlapping) matches.
    Explicit offsets are accepted only when the source slice matches exactly.
    """
    if not source_text or not occurrence_text:
        raise OccurrenceSpanError("Occurrence and source text must be non-empty")
    if (start_codepoint is None) != (end_codepoint is None):
        raise OccurrenceSpanError("Occurrence offsets must be supplied together")
    if occurrence_ordinal is not None and occurrence_ordinal < 1:
        raise OccurrenceSpanError("Occurrence ordinal must be positive")

    matches: list[tuple[int, int]] = []
    cursor = 0
    while True:
        start = source_text.find(occurrence_text, cursor)
        if start < 0:
            break
        matches.append((start, start + len(occurrence_text)))
        cursor = start + 1  # Preserve overlapping exact matches.

    if start_codepoint is not None:
        if not isinstance(start_codepoint, int) or not isinstance(end_codepoint, int):
            raise OccurrenceSpanError("Occurrence offsets must be integers")
        if not 0 <= start_codepoint < end_codepoint <= len(source_text):
            raise OccurrenceSpanError("Occurrence offsets are outside the source")
        selected = (start_codepoint, end_codepoint)
        if selected not in matches:
            raise OccurrenceSpanError("Occurrence offsets do not match exact source text")
        if occurrence_ordinal is not None and matches.index(selected) + 1 != occurrence_ordinal:
            raise OccurrenceSpanError("Occurrence ordinal conflicts with offsets")
        return selected

    if occurrence_ordinal is not None:
        if occurrence_ordinal > len(matches):
            raise OccurrenceSpanError("Occurrence ordinal is outside exact matches")
        return matches[occurrence_ordinal - 1]
    if len(matches) != 1:
        raise OccurrenceSpanError("Occurrence is missing or ambiguous in exact source text")
    return matches[0]


# DEBT A20: a Concept repeated across a video is prepared at most this many times (earliest first);
# later occurrences stay unprepared, which avoids duplicate practice and enrichment calls.
MAX_PREPARED_OCCURRENCES_PER_CONCEPT = 2


def is_trusted_occurrence(row, *, video_id, transcript_id, segment_for) -> bool:
    """An occurrence whose exact span still matches its source segment of this transcript.

    `segment_for(segment_id)` returns the stored segment or None; it is called only for a row whose
    own fields can still be trusted.
    """
    if (row.id is None or row.video_id != video_id or row.start_codepoint is None
            or row.end_codepoint is None):
        return False
    source = segment_for(row.transcript_segment_id)
    return bool(
        source is not None and source.transcript_id == transcript_id
        and 0 <= row.start_codepoint < row.end_codepoint <= len(source.text)
        and source.text[row.start_codepoint:row.end_codepoint] == row.evidence_text
    )


def first_occurrences_per_concept(rows, limit: int) -> list:
    """Ids of the earliest `limit` occurrences of each Concept, in video order."""
    kept: list = []
    per_concept: dict = {}
    for row in sorted(rows, key=lambda item: (item.start_ms or 0, item.start_codepoint or 0, str(item.id))):
        if per_concept.get(row.concept_id, 0) < limit:
            per_concept[row.concept_id] = per_concept.get(row.concept_id, 0) + 1
            kept.append(row.id)
    return kept
