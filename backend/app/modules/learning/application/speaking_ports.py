"""Ports and typed failures for speaking practice."""
from __future__ import annotations

from typing import Protocol, TypeVar

from pydantic import BaseModel

from app.modules.learning.domain.speaking import PronunciationResult
from app.modules.learning.domain.speech_audio import SpeechAudio

TModel = TypeVar("TModel", bound=BaseModel)


class SpeakingPracticeError(Exception):
    """Learner-safe failure. ``kind`` is mapped to HTTP by the API layer."""

    def __init__(self, kind: str, code: str, message: str):
        super().__init__(message)
        self.kind = kind
        self.code = code


class SpeechProviderFailure(Exception):
    """A speech provider could not produce a result; never learner evidence."""

    def __init__(self, category: str):
        super().__init__(f"Speech provider failure: {category}")
        self.category = category


class NoSpeechDetected(Exception):
    pass


class PronunciationAssessor(Protocol):
    provider_name: str

    def supports(self, language_code: str) -> bool: ...

    def assess(self, audio: SpeechAudio, *, reference_text: str, language_code: str) -> PronunciationResult: ...


class StructuredAudioModel(Protocol):
    provider_name: str
    model_name: str

    def generate_structured_with_audio(
        self, prompt: str, wav_audio: bytes, response_model: type[TModel], *,
        system_prompt: str, temperature: float = 0.0, max_tokens: int = 1000,
    ) -> TModel: ...


class StructuredTextModel(Protocol):
    provider_name: str
    model_name: str

    def generate_structured(
        self, prompt: str, response_model: type[TModel], *,
        system_prompt: str | None = None, temperature: float = 0.2, max_tokens: int = 2000,
    ) -> TModel: ...
