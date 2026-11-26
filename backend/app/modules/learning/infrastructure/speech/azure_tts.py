"""Azure Speech text-to-speech over REST (default synthesizer).

Implements the learning module's SpeechSynthesizer port; replacing Azure is a new adapter
plus configuration. The subscription key stays on the server; text and audio are not
logged or stored, only character counts.
"""
from __future__ import annotations

import logging
from xml.sax.saxutils import escape, quoteattr

import httpx

from app.modules.learning.application.agent.ports import SpeechSynthesisUnavailable, SynthesizedSpeech
from app.modules.learning.domain.speaking import primary_language
from app.platform.ai_budget import daily_budget, tts_cost

logger = logging.getLogger(__name__)

# Neural voices per learning language; overridable through configuration.
DEFAULT_VOICES = {
    "en": ("en-US", "en-US-JennyNeural"),
    "zh": ("zh-CN", "zh-CN-XiaoxiaoNeural"),
    "vi": ("vi-VN", "vi-VN-HoaiMyNeural"),
}
OUTPUT_FORMAT = "audio-24khz-48kbitrate-mono-mp3"
MAX_TEXT_CHARS = 600


class AzureSpeechSynthesizer:
    provider_name = "azure"

    def __init__(self, *, key: str, region: str, client: httpx.Client,
                 voices: dict[str, tuple[str, str]] | None = None, rate: str = "-15%"):
        self._key = key
        self._url = f"https://{region}.tts.speech.microsoft.com/cognitiveservices/v1"
        self._client = client
        self._voices = {**DEFAULT_VOICES, **(voices or {})}
        self._rate = rate

    def supports(self, language_code: str) -> bool:
        return primary_language(language_code) in self._voices

    def synthesize(self, text: str, *, language_code: str) -> SynthesizedSpeech:
        voice = self._voices.get(primary_language(language_code))
        cleaned = " ".join(text.split())
        if voice is None or not cleaned or len(cleaned) > MAX_TEXT_CHARS:
            raise SpeechSynthesisUnavailable("unsupported text or language")
        budget = daily_budget()
        cost = tts_cost(len(cleaned))
        reservation = budget.reserve(cost)
        if reservation is None:
            raise SpeechSynthesisUnavailable("daily AI budget used up")
        locale, name = voice
        ssml = (
            f"<speak version='1.0' xml:lang={quoteattr(locale)}>"
            f"<voice name={quoteattr(name)}><prosody rate={quoteattr(self._rate)}>{escape(cleaned)}</prosody>"
            "</voice></speak>"
        )
        try:
            response = self._client.post(
                self._url,
                content=ssml.encode("utf-8"),
                headers={
                    "Ocp-Apim-Subscription-Key": self._key,
                    "Content-Type": "application/ssml+xml",
                    "X-Microsoft-OutputFormat": OUTPUT_FORMAT,
                    "User-Agent": "deeplingo-companion",
                },
            )
        except httpx.HTTPError as exc:
            logger.warning("speech synthesis failed provider=azure error=%s", type(exc).__name__)
            raise SpeechSynthesisUnavailable("transport") from exc
        if response.status_code != 200 or not response.content:
            logger.warning("speech synthesis failed provider=azure status=%s", response.status_code)
            raise SpeechSynthesisUnavailable(f"status {response.status_code}")
        logger.info("speech_synthesis_usage provider=azure characters=%s", len(cleaned))
        budget.charge(cost, reservation=reservation)
        return SynthesizedSpeech(audio=response.content, mime_type="audio/mpeg", characters=len(cleaned))
