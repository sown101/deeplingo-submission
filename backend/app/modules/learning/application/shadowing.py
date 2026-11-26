"""Shadowing practice: repeat one trusted transcript segment and get feedback.

The backend chooses the reference text from the learner's own Library video;
the client sends only the segment selector and raw audio. Results are
non-evidential practice feedback and nothing is persisted.
"""
from __future__ import annotations

from uuid import UUID, uuid4

from app.modules.activity.contracts import log_activity, outcome_from_band
from app.modules.learning.application.region_source import region_source
from app.modules.learning.application.speaking_activity import record_pronunciation
from app.modules.learning.application.speaking_ports import (
    NoSpeechDetected,
    PronunciationAssessor,
    SpeakingPracticeError,
    SpeechProviderFailure,
)
from app.modules.learning.application.speaking_views import (
    ShadowingAssessmentView,
    SpeakingPhonemeView,
    SpeakingScoresView,
    SpeakingWordView,
)
from app.modules.learning.domain.speaking import (
    PronunciationResult,
    feedback_band,
    spoken_span_ms,
)
from app.modules.learning.domain.speech_audio import SpeechAudio, voice_activity

READY_VIDEO_STATES = frozenset({"transcript_ready", "learning_objects_ready"})
MAX_REFERENCE_CHARS = 600
MIN_ATTEMPT_CEILING_MS = 15_000


def provider_failure_error(exc: SpeechProviderFailure) -> SpeakingPracticeError:
    if exc.category == "busy":
        return SpeakingPracticeError("unavailable", "speech_service_busy",
                                     "Speech practice is busy. Please try again shortly.")
    return SpeakingPracticeError("unavailable", "speech_service_unavailable",
                                 "Speech practice is temporarily unavailable.")


def scores_view(result: PronunciationResult) -> SpeakingScoresView:
    scores = result.scores
    return SpeakingScoresView(
        pronunciation=scores.pronunciation, accuracy=scores.accuracy, fluency=scores.fluency,
        completeness=scores.completeness, prosody=scores.prosody,
    )



def require_voice_consent(consent, user_id) -> None:
    """PRD FR-3.4: audio is sent to a speech service only with the learner's voice consent.

    `consent` is the learner's consent reader; None means the composition root gave none (tests only).
    A failed read refuses rather than sends audio.
    """
    if consent is None:
        return
    try:
        granted = consent.has_consent(user_id) is True
    except Exception:
        granted = False
    if not granted:
        raise SpeakingPracticeError("conflict", "voice_consent_required",
                                    "Allow voice processing in Profile to practise speaking.")

class ShadowingPracticeService:
    def __init__(self, *, library, videos, transcripts, segments, assessor: PronunciationAssessor | None, scores=None, consent=None, learning_log=None):
        self.learning_log = learning_log  # the learning log (activity module); None = not recording
        self.library = library
        self.consent = consent  # Codex review 2026-11-05: voice consent before any audio is assessed
        self.videos = videos
        self.transcripts = transcripts
        self.segments = segments
        self.assessor = assessor
        self.scores = scores

    def assess(self, user, library_item_id: UUID, segment_id: UUID, audio: SpeechAudio,
               region_id: str | None = None) -> ShadowingAssessmentView:
        require_voice_consent(self.consent, user.id)
        association = self.library.get_for_user(library_item_id=library_item_id, user_id=user.id)
        video = self.videos.get_by_id(association.video_id) if association is not None else None
        if video is None:
            raise SpeakingPracticeError("not_found", "library_item_not_found", "Library item not found.")
        if video.processing_status not in READY_VIDEO_STATES:
            raise SpeakingPracticeError("conflict", "video_not_ready", "This video is not ready yet.")

        segment = self.segments.get_by_id(segment_id)
        track = self.transcripts.get_by_id(segment.transcript_id) if segment is not None else None
        if (segment is None or track is None or track.video_id != video.id or not track.is_original
                or track.language_code != video.original_language_code):
            raise SpeakingPracticeError("not_found", "segment_not_found", "Sentence not found.")
        reference = " ".join(segment.text.split())
        if not reference or len(reference) > MAX_REFERENCE_CHARS:
            raise SpeakingPracticeError("conflict", "segment_unavailable",
                                        "This sentence cannot be used for shadowing.")

        if self.assessor is None:
            raise SpeakingPracticeError("unavailable", "speech_service_unavailable",
                                        "Speech practice is temporarily unavailable.")
        if not self.assessor.supports(track.language_code):
            raise SpeakingPracticeError("unsupported", "speaking_language_unsupported",
                                        "Shadowing is not available for this language yet.")

        reference_ms = max(segment.end_ms - segment.start_ms, 0)
        if audio.duration_ms > max(MIN_ATTEMPT_CEILING_MS, 3 * reference_ms):
            raise SpeakingPracticeError("invalid_input", "audio_too_long", "The recording is too long.")
        if not voice_activity(audio).has_speech:
            raise SpeakingPracticeError("invalid_input", "no_speech_detected", "No speech was detected.")

        try:
            result = self.assessor.assess(audio, reference_text=reference, language_code=track.language_code)
        except NoSpeechDetected as exc:
            raise SpeakingPracticeError("invalid_input", "no_speech_detected",
                                        "No speech was detected.") from exc
        except SpeechProviderFailure as exc:
            raise provider_failure_error(exc) from exc

        band = feedback_band(result.scores.pronunciation)
        # Every assessment is a new attempt: nothing the client sends identifies a retry of one.
        log_activity(
            self.learning_log, user_id=user.id, language_code=track.language_code,
            client_event_id=f"shadowing:{uuid4()}", kind="shadowing", outcome=outcome_from_band(band),
            item_type="segment", item_id=str(segment.id), source_type="video_region",
            source_id=region_source(self.segments, segment, library_item_id, region_id),
            score=result.scores.pronunciation,
            detail={"accuracy": result.scores.accuracy, "fluency": result.scores.fluency,
                    "seconds": audio.duration_ms // 1000})
        record_pronunciation(self.scores, user.id, language_code=track.language_code, source="shadowing", results=[result])
        return ShadowingAssessmentView(
            library_item_id=library_item_id,
            segment_id=segment_id,
            language_code=track.language_code,
            reference_text=reference,
            recognized_text=result.recognized_text,
            band=band,
            scores=scores_view(result),
            words=[
                SpeakingWordView(
                    word=word.word, accuracy=word.accuracy, error_type=word.error_type,
                    start_ms=word.start_ms, end_ms=word.end_ms,
                    phonemes=[SpeakingPhonemeView(phoneme=item.phoneme, accuracy=item.accuracy)
                              for item in word.phonemes],
                )
                for word in result.words
            ],
            attempt_duration_ms=audio.duration_ms,
            reference_duration_ms=reference_ms,
            spoken_duration_ms=spoken_span_ms(result.words),
        )
