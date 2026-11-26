"""M1 S7b: one trusted occurrence per word in the learner's own Library videos (Quick review sentences).

Only videos in this learner's Library, only the current original transcript, and only an occurrence
whose exact span still matches its sentence; the earliest occurrence in the video comes first. The
reads are batched: Library, the occurrences of the asked Concepts, their videos and transcripts, then
the sentences of each word's earliest candidate (one more round only for words whose candidate no
longer matches), whatever the number of videos or occurrences.
"""
from __future__ import annotations

from uuid import UUID

from app.modules.content.application.store_ports import (
    LearnerVideoStore,
    LearningObjectStore,
    TranscriptSegmentStore,
    VideoStore,
    VideoTranscriptStore,
)
from app.modules.content.domain.library import LibraryOccurrence
from app.modules.content.domain.occurrence_spans import is_trusted_occurrence
from app.modules.content.domain.prepared_context import sense_translated_meaning

LIBRARY_SCAN_LIMIT = 100
# Ids per `in` filter, so a long list never makes one oversized request.
READ_CHUNK = 100


class LibraryOccurrenceService:
    def __init__(self, *, library: LearnerVideoStore, videos: VideoStore, transcripts: VideoTranscriptStore,
                 objects: LearningObjectStore, segments: TranscriptSegmentStore):
        self.library = library
        self.videos = videos
        self.transcripts = transcripts
        self.objects = objects
        self.segments = segments

    def sentences_for(self, user_id: UUID, concept_ids: list[UUID], *,
                      support_language_code: str | None = None) -> dict[UUID, LibraryOccurrence]:
        wanted = list(dict.fromkeys(concept_ids))
        if not wanted:
            return {}
        items: dict[UUID, UUID] = {}
        for association in self.library.list_for_user(user_id, limit=LIBRARY_SCAN_LIMIT):
            items.setdefault(association.video_id, association.id)
        if not items:
            return {}
        rows = sorted(
            (row for chunk in _chunks(wanted)
             for row in self.objects.list_for_videos_concepts(list(items), chunk)),
            key=lambda row: (str(row.video_id), row.start_ms or 0, row.start_codepoint or 0),
        )
        if not rows:
            return {}
        video_ids = list(dict.fromkeys(row.video_id for row in rows))
        videos = self.videos.get_many_by_ids(video_ids)
        tracks = _original_tracks(videos, self.transcripts.list_for_videos(video_ids))
        candidates: dict[UUID, list] = {}
        for row in rows:  # earliest first, only in a video with an original transcript
            if tracks.get(row.video_id) is not None:
                candidates.setdefault(row.concept_id, []).append(row)
        found: dict[UUID, LibraryOccurrence] = {}
        # Each round reads the segments of every word's next candidate at once; a word moves to its
        # next candidate only when the current one no longer matches its sentence.
        while candidates:
            heads = {concept_id: rows_[0] for concept_id, rows_ in candidates.items()}
            segments = {segment.id: segment for chunk in _chunks(list(dict.fromkeys(
                row.transcript_segment_id for row in heads.values()))) for segment in self.segments.list_by_ids(chunk)}
            for concept_id, row in heads.items():
                candidates[concept_id].pop(0)
                if is_trusted_occurrence(row, video_id=row.video_id, transcript_id=tracks[row.video_id],
                                         segment_for=segments.get):
                    segment = segments[row.transcript_segment_id]
                    meaning, pos = sense_translated_meaning(row.raw_ai_diagnostics, support_language_code)
                    found[concept_id] = LibraryOccurrence(
                        learning_object_id=row.id, transcript_segment_id=segment.id, sentence=segment.text,
                        target_form=row.evidence_text, library_item_id=items.get(row.video_id),
                        start_ms=segment.start_ms, meaning=meaning, part_of_speech=pos,
                    )
                    del candidates[concept_id]
                elif not candidates[concept_id]:
                    del candidates[concept_id]
        return found


def _original_tracks(videos: dict, transcripts: list) -> dict[UUID, UUID]:
    """Each video's original-language transcript (a caption track before an automatic one)."""
    tracks: dict[UUID, UUID] = {}
    for track in sorted(transcripts, key=lambda item: (item.source != "caption_track", str(item.id))):
        video = videos.get(track.video_id)
        if (video is not None and track.is_original and track.language_code == video.original_language_code
                and track.video_id not in tracks):
            tracks[track.video_id] = track.id
    return tracks


def _chunks(ids: list) -> list[list]:
    return [ids[start:start + READ_CHUNK] for start in range(0, len(ids), READ_CHUNK)]
