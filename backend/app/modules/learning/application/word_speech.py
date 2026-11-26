"""A word read aloud, and one attempt at saying it.

Text a client sends is accepted only when the dictionary holds it. A learner's saved word, chosen by id on the server
(`saved=True`), is read and assessed whatever the dictionary holds, so every saved word has audio.
"""
from __future__ import annotations

from collections import OrderedDict
from threading import Lock
from typing import Protocol

from uuid import uuid4

from pydantic import BaseModel, ConfigDict

from app.modules.activity.contracts import log_activity, outcome_from_band
from app.modules.learning.application.agent.ports import SpeechSynthesisUnavailable, SpeechSynthesizer
from app.modules.learning.application.shadowing import provider_failure_error, require_voice_consent
from app.modules.learning.application.speaking_activity import record_pronunciation
from app.modules.learning.application.speaking_ports import (
    NoSpeechDetected,
    PronunciationAssessor,
    SpeakingPracticeError,
    SpeechProviderFailure,
)
from app.modules.learning.domain.speaking import FeedbackBand, PronunciationResult, feedback_band
from app.modules.learning.domain.speech_audio import SpeechAudio, voice_activity

MAX_WORD_CHARS = 60
MAX_CACHED_AUDIO = 500


class WordPronunciationView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str
    band: FeedbackBand
    pronunciation: float
    accuracy: float
    fluency: float


class HeadwordCheck(Protocol):
    def has_headword(self, language_code: str, text: str) -> bool: ...


class WordSpeechService:
    def __init__(self, *, dictionary: HeadwordCheck, synthesizer: SpeechSynthesizer | None,
                 assessor: PronunciationAssessor | None, consent, scores, learning_log=None):
        self.learning_log = learning_log  # the learning log (activity module); None = not recording
        self.dictionary, self.synthesizer, self.assessor = dictionary, synthesizer, assessor
        self.consent, self.scores = consent, scores
        self._cache: OrderedDict[tuple[str, str], bytes] = OrderedDict()
        self._lock = Lock()

    def _checked(self, language_code: str, text: str, saved: bool = False) -> str:
        cleaned = " ".join(text.split())
        if not cleaned or len(cleaned) > MAX_WORD_CHARS or (
                not saved and not self.dictionary.has_headword(language_code, cleaned)):
            raise SpeakingPracticeError("not_found", "word_not_in_dictionary", "This word is not in the dictionary.")
        return cleaned

    def audio(self, language_code: str, text: str, *, saved: bool = False) -> bytes:
        cleaned = self._checked(language_code, text, saved)
        key = (language_code, cleaned.casefold())
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                return self._cache[key]
        if self.synthesizer is None or not self.synthesizer.supports(language_code):
            raise SpeakingPracticeError("unavailable", "speech_service_unavailable", "Audio is temporarily unavailable.")
        try:
            data = self.synthesizer.synthesize(cleaned, language_code=language_code).audio
        except SpeechSynthesisUnavailable as exc:
            raise SpeakingPracticeError("unavailable", "speech_service_unavailable", "Audio is temporarily unavailable.") from exc
        with self._lock:
            self._cache[key] = data
            while len(self._cache) > MAX_CACHED_AUDIO:
                self._cache.popitem(last=False)
        return data

    def assess(self, user, language_code: str, text: str, audio: SpeechAudio) -> WordPronunciationView:
        cleaned, band, result = self.assess_result(user, language_code, text, audio)
        return WordPronunciationView(text=cleaned, band=band,
                                     pronunciation=result.scores.pronunciation, accuracy=result.scores.accuracy,
                                     fluency=result.scores.fluency)

    def assess_result(self, user, language_code: str, text: str, audio: SpeechAudio, *,
                      saved: bool = False) -> tuple[str, FeedbackBand, PronunciationResult]:
        """The whole Azure result (every score, each word with its error type and phonemes) and its band."""
        require_voice_consent(self.consent, user.id)
        cleaned = self._checked(language_code, text, saved)
        if self.assessor is None or not self.assessor.supports(language_code):
            raise SpeakingPracticeError("unavailable", "speech_service_unavailable", "Pronunciation is temporarily unavailable.")
        if not voice_activity(audio).has_speech:
            raise SpeakingPracticeError("invalid_input", "no_speech_detected", "No speech was detected.")
        try:
            result = self.assessor.assess(audio, reference_text=cleaned, language_code=language_code)
        except NoSpeechDetected as exc:
            raise SpeakingPracticeError("invalid_input", "no_speech_detected", "No speech was detected.") from exc
        except SpeechProviderFailure as exc:
            raise provider_failure_error(exc) from exc
        band = feedback_band(result.scores.pronunciation)
        # Every assessment is a new attempt: nothing the client sends identifies a retry of one.
        log_activity(self.learning_log, user_id=user.id, language_code=language_code,
                     client_event_id=f"pronunciation:{uuid4()}", kind="pronunciation",
                     outcome=outcome_from_band(band), score=result.scores.pronunciation,
                     detail={"text": cleaned, "accuracy": result.scores.accuracy, "fluency": result.scores.fluency,
                             "seconds": audio.duration_ms // 1000})
        record_pronunciation(self.scores, user.id, language_code=language_code, source="shadowing", results=[result])
        return cleaned, band, result
