from pydantic import ValidationError

from app.modules.content.application.playback_views import (
    GrammarOccurrenceView,
    LearningObjectOccurrenceView,
    PlayableVideo,
    SegmentRomanizationView,
    SegmentTranslationView,
    TranscriptSegmentView,
    VideoTranscriptView,
)
from app.modules.content.application.library import LearnerLibraryError
from app.modules.content.domain.pinyin import HANYU_PINYIN
from app.modules.content.domain.prepared_context import prepared_context


def owned_ready_video(library, videos, user, item_id):
    """The playable Video behind the learner's own Library item (404 for anyone else's)."""
    association = library.get_for_user(library_item_id=item_id, user_id=user.id)
    if association is None:
        raise LearnerLibraryError("Library item not found.", status_code=404, code="library_item_not_found")
    video = videos.get_by_id(association.video_id)
    if video is None:
        raise LearnerLibraryError("Library item not found.", status_code=404, code="library_item_not_found")
    if video.processing_status not in {"transcript_ready", "learning_objects_ready"}:
        raise LearnerLibraryError("This video is not ready yet.", status_code=409, code="video_not_ready")
    return video


def original_track(transcripts, video):
    """The transcript version the learner sees: the original-language track, captions first."""
    track = select_original_track(transcripts.list_for_video(video.id), video.original_language_code)
    if track is None:
        raise LearnerLibraryError("Transcript is temporarily unavailable.", status_code=409, code="transcript_unavailable")
    return track


def select_original_track(tracks, language_code):
    return min(
        (track for track in tracks if track.is_original and track.language_code == language_code),
        key=lambda track: (track.source != "caption_track", str(track.id)), default=None,
    )


class VideoPlaybackService:
    def __init__(self, *, library, videos, transcripts, aggregate, preferences, romanization_provider,
                 romanization_systems):
        self.library = library
        self.videos = videos
        self.transcripts = transcripts
        self.aggregate = aggregate
        self.preferences = preferences
        self.romanization_provider = romanization_provider
        self.romanization_systems = romanization_systems

    def _owned_video(self, user, item_id):
        return owned_ready_video(self.library, self.videos, user, item_id)

    def playable(self, user, item_id):
        video = self._owned_video(user, item_id)
        try:
            return PlayableVideo(
                library_item_id=item_id, video_id=video.id, provider=video.source,
                external_video_id=video.external_video_id, title=video.title,
                language_code=video.original_language_code, duration_ms=video.duration_ms,
            )
        except ValidationError as exc:
            raise LearnerLibraryError("Video playback is unavailable.", status_code=422, code="media_unavailable") from exc

    def transcript(self, user, item_id):
        video = self._owned_video(user, item_id)
        tracks = [original_track(self.transcripts, video)]
        profile = self.preferences.get_by_language_for_user(
            user_id=user.id, language_code=tracks[0].language_code,
        )
        support_language = profile.support_language_code if profile else None
        try:
            rows = self.aggregate.list_aggregate(tracks[0].id)
            segments = []
            include_pinyin = None
            for row in rows:
                occurrences = []
                for item in row.get("learning_objects") or []:
                    try:
                        start, end = item["start_codepoint"], item["end_codepoint"]
                        if (type(start) is not int or type(end) is not int
                                or not 0 <= start < end <= len(row["text"])
                                or row["text"][start:end] != item["evidence_text"]):
                            continue
                        concept = item.get("concepts")
                        if (isinstance(concept, dict) and concept.get("type") == "grammar"
                                and concept.get("language_code") == tracks[0].language_code):
                            metadata = concept.get("metadata")
                            key = metadata.get("grammar_key") if isinstance(metadata, dict) else None
                            if (isinstance(key, str) and key == concept.get("sense_key")
                                    and key.startswith(tracks[0].language_code + ".")):
                                occurrences.append(GrammarOccurrenceView(
                                    learning_object_id=item["id"], start_codepoint=start, end_codepoint=end,
                                    grammar_key=key,
                                ))
                            continue
                        if (not isinstance(concept, dict)
                                or concept.get("language_code") != tracks[0].language_code
                                or prepared_context(
                                    item.get("raw_ai_diagnostics"),
                                    concept_id=str(item["concept_id"]),
                                    sense_key=concept.get("sense_key"),
                                    source_language_code=tracks[0].language_code,
                                    support_language_code=support_language,
                                ) is None):
                            continue
                        occurrences.append(LearningObjectOccurrenceView(
                            learning_object_id=item["id"],
                            start_codepoint=start, end_codepoint=end,
                        ))
                    except (ValidationError, KeyError, TypeError, ValueError):
                        # Legacy unresolved or corrupted annotations cannot
                        # become learner-visible authority.
                        continue
                occurrences.sort(key=lambda item: (
                    item.start_codepoint, item.end_codepoint, str(item.learning_object_id),
                ))
                translation = next((item for item in row.get("segment_translations", [])
                                    if item["language_code"] == support_language and item["text"].strip()), None)
                romanizations = []
                for item in row.get("segment_romanizations", []):
                    system = item.get("romanization_systems")
                    if system and system["is_active"] and item["text"].strip():
                        romanizations.append(SegmentRomanizationView(system=system["code"], text=item["text"]))
                if tracks[0].language_code == "zh" and not any(entry.system == HANYU_PINYIN for entry in romanizations):
                    if include_pinyin is None:
                        include_pinyin = self.romanization_systems.get_by_language_and_code("zh", HANYU_PINYIN) is not None
                    if include_pinyin:
                        pinyin = self.romanization_provider.romanize(row["text"], "zh").get(HANYU_PINYIN)
                        if pinyin:
                            romanizations.append(SegmentRomanizationView(system=HANYU_PINYIN, text=pinyin))
                segments.append(TranscriptSegmentView(
                    segment_id=row["id"], sequence=row["sequence_number"], text=row["text"],
                    start_ms=row["start_ms"], end_ms=row["end_ms"],
                    translation=SegmentTranslationView(**translation) if translation else None,
                    romanizations=sorted(romanizations, key=lambda item: item.system),
                    learning_objects=occurrences,
                ))
            segments.sort(key=lambda segment: (segment.start_ms, segment.sequence))
            if not segments or len({segment.segment_id for segment in segments}) != len(segments):
                raise ValueError("Missing or duplicate segments")
            return VideoTranscriptView(
                library_item_id=item_id, language_code=tracks[0].language_code,
                translation_language_code=support_language, segments=segments,
            )
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            raise LearnerLibraryError("Transcript is temporarily unavailable.", status_code=409, code="transcript_unavailable") from exc
