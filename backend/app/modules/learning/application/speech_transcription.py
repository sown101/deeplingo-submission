"""Verbatim learner-speech transcription through the configured audio model."""
from __future__ import annotations

import logging
from dataclasses import dataclass

from app.modules.learning.application.speaking_ports import (
    NoSpeechDetected,
    SpeechProviderFailure,
    StructuredAudioModel,
)
from app.modules.learning.application.speaking_prompts import (
    SPEAKING_TRANSCRIPTION_PROMPT_VERSION,
    TRANSCRIPTION_SYSTEM_PROMPT,
    TranscriptionOutput,
    build_transcription_prompt,
)
from app.modules.learning.domain.speech_audio import SpeechAudio

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SpeechTranscript:
    text: str
    model: str
    prompt_version: str = SPEAKING_TRANSCRIPTION_PROMPT_VERSION


class SpeechTranscriber:
    def __init__(self, model: StructuredAudioModel):
        self.model = model

    def transcribe(self, audio: SpeechAudio, *, language_code: str) -> SpeechTranscript:
        try:
            output = self.model.generate_structured_with_audio(
                build_transcription_prompt(language_code),
                audio.to_wav(),
                TranscriptionOutput,
                system_prompt=TRANSCRIPTION_SYSTEM_PROMPT,
                temperature=0.0,
                max_tokens=1500,
            )
        except Exception as exc:
            # Transcript bodies and provider errors are never logged.
            logger.warning("speech transcription failed error=%s category=%s",
                           type(exc).__name__, getattr(getattr(exc, "category", None), "value", None))
            raise SpeechProviderFailure("transcription_unavailable") from exc
        text = " ".join(output.transcript.split())
        if not output.contains_speech or not text:
            raise NoSpeechDetected()
        return SpeechTranscript(text=text, model=self.model.model_name)
