"""Azure Speech pronunciation assessment over the REST API for short audio.

The subscription key stays on the server. Audio is posted once per request and
not stored by DeepLingo. Provider payloads are validated before use and are
never logged.
"""
from __future__ import annotations

import base64
import json
import logging
import math

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.modules.learning.application.speaking_ports import NoSpeechDetected, SpeechProviderFailure
from app.modules.learning.domain.speaking import (
    PronunciationErrorType,
    PronunciationPhoneme,
    PronunciationResult,
    PronunciationScores,
    PronunciationWord,
    primary_language,
)
from app.modules.learning.domain.speech_audio import SpeechAudio
from app.platform.ai_budget import daily_budget, speech_cost

logger = logging.getLogger(__name__)

AZURE_PRONUNCIATION_LOCALES = {
    "en": "en-US", "zh": "zh-CN", "ja": "ja-JP", "ko": "ko-KR", "fr": "fr-FR",
    "de": "de-DE", "es": "es-ES", "it": "it-IT", "pt": "pt-BR", "vi": "vi-VN",
}
_ERROR_TYPES = {
    "None": PronunciationErrorType.NONE,
    "Mispronunciation": PronunciationErrorType.MISPRONUNCIATION,
    "Omission": PronunciationErrorType.OMISSION,
    "Insertion": PronunciationErrorType.INSERTION,
    "UnexpectedBreak": PronunciationErrorType.UNEXPECTED_BREAK,
    "MissingBreak": PronunciationErrorType.MISSING_BREAK,
    "Monotone": PronunciationErrorType.MONOTONE,
}
_NO_SPEECH = {"NoMatch", "InitialSilenceTimeout", "BabbleTimeout"}
_TICKS_PER_MS = 10_000
_MAX_WORDS = 200


class _Vendor(BaseModel):
    model_config = ConfigDict(extra="ignore")


class _AzurePhoneme(_Vendor):
    Phoneme: str = ""
    AccuracyScore: float = 0.0


class _AzureWord(_Vendor):
    Word: str
    AccuracyScore: float = 0.0
    ErrorType: str = "None"
    Offset: int | None = None
    Duration: int | None = None
    Phonemes: list[_AzurePhoneme] = Field(default_factory=list)


class _AzureBest(_Vendor):
    Display: str = ""
    AccuracyScore: float
    FluencyScore: float
    CompletenessScore: float
    PronScore: float
    ProsodyScore: float | None = None
    Words: list[_AzureWord] = Field(default_factory=list)


class _AzureResponse(_Vendor):
    RecognitionStatus: str
    DisplayText: str | None = None
    NBest: list[_AzureBest] = Field(default_factory=list)


def _score(value: float | None) -> float | None:
    if value is None:
        return None
    if not math.isfinite(value) or not 0 <= value <= 100:
        raise ValueError("Score outside 0..100")
    return round(float(value), 1)


class AzurePronunciationAssessor:
    provider_name = "azure_speech"

    def __init__(self, *, key: str, region: str, client: httpx.Client | None = None,
                 timeout_seconds: float = 20.0):
        self._key = key
        self._url = (f"https://{region}.stt.speech.microsoft.com/speech/recognition/"
                     "conversation/cognitiveservices/v1")
        self._client = client or httpx.Client(timeout=timeout_seconds)
        self._timeout = timeout_seconds

    def supports(self, language_code: str) -> bool:
        return bool(self._key) and primary_language(language_code) in AZURE_PRONUNCIATION_LOCALES

    def assess(self, audio: SpeechAudio, *, reference_text: str, language_code: str) -> PronunciationResult:
        locale = AZURE_PRONUNCIATION_LOCALES.get(primary_language(language_code))
        if locale is None or not self._key:
            raise SpeechProviderFailure("unsupported")
        budget = daily_budget()
        cost = speech_cost(audio.duration_ms / 1000)
        reservation = budget.reserve(cost)
        if reservation is None:
            raise SpeechProviderFailure("budget")
        config = {
            "ReferenceText": reference_text, "GradingSystem": "HundredMark", "Granularity": "Phoneme",
            "Dimension": "Comprehensive", "EnableMiscue": True,
        }
        if locale == "en-US":
            config.update(EnableProsodyAssessment=True, PhonemeAlphabet="IPA")
        try:
            response = self._client.post(
                self._url,
                params={"language": locale, "format": "detailed"},
                headers={
                    "Ocp-Apim-Subscription-Key": self._key,
                    "Content-Type": "audio/wav; codecs=audio/pcm; samplerate=16000",
                    "Accept": "application/json",
                    "Pronunciation-Assessment": base64.b64encode(
                        json.dumps(config, ensure_ascii=False).encode("utf-8")).decode("ascii"),
                },
                content=audio.to_wav(),
                timeout=self._timeout,
            )
        except httpx.HTTPError as exc:
            logger.warning("azure pronunciation transport failure error=%s", type(exc).__name__)
            raise SpeechProviderFailure("transport") from exc
        budget.charge(cost, reservation=reservation)  # billed once Azure received the audio

        if response.status_code != 200:
            logger.warning("azure pronunciation rejected status=%s", response.status_code)
            raise SpeechProviderFailure(
                "configuration" if response.status_code in {401, 403}
                else "busy" if response.status_code == 429
                else "transport" if response.status_code >= 500
                else "rejected"
            )
        try:
            payload = _AzureResponse.model_validate(response.json())
        except (ValueError, ValidationError) as exc:
            raise SpeechProviderFailure("rejected") from exc
        if payload.RecognitionStatus in _NO_SPEECH:
            raise NoSpeechDetected()
        if payload.RecognitionStatus != "Success" or not payload.NBest:
            raise SpeechProviderFailure("rejected")
        best = payload.NBest[0]
        try:
            scores = PronunciationScores(
                pronunciation=_score(best.PronScore), accuracy=_score(best.AccuracyScore),
                fluency=_score(best.FluencyScore), completeness=_score(best.CompletenessScore),
                prosody=_score(best.ProsodyScore),
            )
            words = tuple(
                PronunciationWord(
                    word=word.Word,
                    accuracy=_score(word.AccuracyScore),
                    error_type=_ERROR_TYPES.get(word.ErrorType, PronunciationErrorType.OTHER),
                    start_ms=word.Offset // _TICKS_PER_MS if word.Offset is not None else None,
                    end_ms=(word.Offset + word.Duration) // _TICKS_PER_MS
                    if word.Offset is not None and word.Duration is not None else None,
                    phonemes=tuple(PronunciationPhoneme(phoneme=item.Phoneme, accuracy=_score(item.AccuracyScore))
                                   for item in word.Phonemes if item.Phoneme),
                )
                for word in best.Words[:_MAX_WORDS] if word.Word.strip()
            )
        except ValueError as exc:
            raise SpeechProviderFailure("rejected") from exc
        return PronunciationResult(
            recognized_text=(payload.DisplayText or best.Display or "").strip(),
            scores=scores, words=words,
        )
