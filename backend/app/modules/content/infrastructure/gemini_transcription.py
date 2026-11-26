"""Gemini YouTube-URL transcription source.

Gemini fetches the public video itself, so no YouTube page or caption request leaves
DeepLingo. Each fixed clip is transcribed under a strict schema and validated; one clip
that still fails after its bounded retry fails the whole transcript (no gapped tracks).
"""
import json
import logging
import threading
import time
from collections import Counter
from concurrent.futures import FIRST_EXCEPTION, ThreadPoolExecutor, wait
from dataclasses import dataclass
from typing import Callable, Iterable

import httpx
from pydantic import BaseModel, ConfigDict, ValidationError

from app.modules.content.application.ports import (
    ContentProviderFailure,
    UnsupportedSourceContent,
)
from app.modules.content.application.prompts import (
    YOUTUBE_TRANSCRIPTION_PROMPT_VERSION,
    build_youtube_transcription_prompt,
)
from app.modules.content.domain.ingestion import (
    SourceTranscriptSegment,
    SourceTranscriptTrack,
    SourceVideoMetadata,
)
from app.modules.content.infrastructure.youtube import YouTubeService
from app.modules.content.infrastructure.youtube_data_api import YouTubeDataApiClient, YouTubeVideoInfo
from app.platform.ai_budget import daily_budget, text_cost

logger = logging.getLogger(__name__)

GEMINI_GENERATE_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
TRANSCRIPTION_METHOD = "gemini_youtube_url"
# Models round clip-relative end times; tolerate a little overshoot past the clip end.
_CLIP_END_TOLERANCE_SECONDS = 2.0
_MIN_SEGMENT_SECONDS = 0.1
_CLIP_OUTPUT_TOKENS = 8192
_ESTIMATED_VIDEO_TOKENS_PER_SECOND = 512


class _ClipSegment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    start: str
    end: str
    text: str


class _ClipResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    language: str
    segments: list[_ClipSegment]


@dataclass(frozen=True)
class TranscribedSegment:
    start: float
    end: float
    text: str


@dataclass(frozen=True)
class _ClipResult:
    language: str
    segments: list[TranscribedSegment]
    model_version: str | None


class _Usage:
    """Billed tokens across every attempt, including retried and rejected responses."""

    def __init__(self):
        self._lock = threading.Lock()
        self.requests = self.prompt_tokens = self.output_tokens = self.thinking_tokens = 0

    def add(self, metadata: dict) -> None:
        with self._lock:
            self.requests += 1
            self.prompt_tokens += int(metadata.get("promptTokenCount") or 0)
            self.output_tokens += int(metadata.get("candidatesTokenCount") or 0)
            self.thinking_tokens += int(metadata.get("thoughtsTokenCount") or 0)

    def as_dict(self) -> dict[str, int]:
        return {"requests": self.requests, "prompt_tokens": self.prompt_tokens,
                "output_tokens": self.output_tokens, "thinking_tokens": self.thinking_tokens}


@dataclass(frozen=True)
class Transcription:
    language: str | None
    segments: list[TranscribedSegment]
    model_versions: tuple[str, ...]
    usage: dict[str, int] | None = None


def parse_clock(value: str) -> float:
    """Parse `MM:SS.s`, `H:MM:SS.s` or plain seconds; raises ValueError otherwise."""
    parts = [float(part) for part in str(value).strip().split(":")]
    if not 1 <= len(parts) <= 3 or any(part < 0 for part in parts):
        raise ValueError("invalid clock value")
    seconds = 0.0
    for part in parts:
        seconds = seconds * 60 + part
    return seconds


class GeminiYouTubeTranscriber:
    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        catalog_languages: Callable[[], Iterable[str]],
        timeout_seconds: float = 180.0,
        clip_seconds: int = 60,
        max_parallel: int = 4,
        max_attempts: int = 2,
        deadline_seconds: float = 900.0,
        thinking_level: str | None = None,
        transport: httpx.BaseTransport | None = None,
        clock: Callable[[], float] = time.monotonic,
    ):
        if not api_key or not model.strip():
            raise ValueError("Gemini transcription requires an API key and an explicit model")
        self.model = model.strip()
        self.clip_seconds = clip_seconds
        self.max_parallel = max_parallel
        self.max_attempts = max_attempts
        self.deadline_seconds = deadline_seconds
        # Transcription is listening, not reasoning; thinking tokens are billed as output.
        self.thinking_level = thinking_level or None
        # The schema enum is the whole supported catalog, not the enabled subset, so a
        # video in another supported language is reported truthfully and then rejected.
        self._catalog_languages = catalog_languages
        self._languages: list[str] | None = None
        self._api_key = api_key
        self._clock = clock
        self._client = httpx.Client(timeout=timeout_seconds, transport=transport)

    def transcribe(self, video_id: str, duration_seconds: int) -> Transcription:
        if duration_seconds <= 0:
            raise UnsupportedSourceContent("Video duration is unknown")
        if self._languages is None:
            self._languages = sorted({code.strip().lower() for code in self._catalog_languages() if code.strip()})
            if not self._languages:
                raise ContentProviderFailure("configuration_error", transient=False)
        clips = [(start, min(start + self.clip_seconds, duration_seconds))
                 for start in range(0, duration_seconds, self.clip_seconds)]
        deadline = self._clock() + self.deadline_seconds
        usage = _Usage()
        executor = ThreadPoolExecutor(max_workers=min(self.max_parallel, len(clips)))
        try:
            futures = [executor.submit(self._clip_with_retry, video_id, start, end, deadline, usage)
                       for start, end in clips]
            done, pending = wait(futures, timeout=max(0.0, deadline - self._clock()), return_when=FIRST_EXCEPTION)
            for future in done:
                if future.exception() is not None:
                    raise future.exception()
            if pending:
                raise ContentProviderFailure("transient_timeout", transient=True)
            results = [future.result() for future in futures]
        finally:
            executor.shutdown(wait=False, cancel_futures=True)
            totals = usage.as_dict()
            logger.info(
                "gemini_transcription_usage model=%s thinking_level=%s requests=%s prompt_tokens=%s "
                "output_tokens=%s thinking_tokens=%s", self.model, self.thinking_level, totals["requests"],
                totals["prompt_tokens"], totals["output_tokens"], totals["thinking_tokens"],
            )

        segments = sorted((segment for result in results for segment in result.segments), key=lambda s: (s.start, s.end))
        # Clips with speech vote; the transcript language is the most common answer.
        votes = Counter(result.language for result in results if result.segments)
        versions = tuple(sorted({result.model_version for result in results if result.model_version}))
        logger.info("Gemini transcription complete clips=%s segments=%s", len(clips), len(segments))
        return Transcription(language=votes.most_common(1)[0][0] if votes else None,
                             segments=segments, model_versions=versions, usage=usage.as_dict())

    def detect_language(self, video_id: str, duration_seconds: int, *, max_clips: int = 3) -> str | None:
        """Spoken language of the first clips that contain speech, using the transcription request itself.

        Used only when YouTube declares no audio language and several languages are enabled.
        Reuses prompt `youtube-transcription-v1`, so no new prompt contract is introduced; the
        transcript stage still verifies the language over the whole video.
        """
        if duration_seconds <= 0:
            raise UnsupportedSourceContent("Video duration is unknown")
        if self._languages is None:
            self._languages = sorted({code.strip().lower() for code in self._catalog_languages() if code.strip()})
            if not self._languages:
                raise ContentProviderFailure("configuration_error", transient=False)
        deadline = self._clock() + self.deadline_seconds
        usage = _Usage()
        try:
            for start in range(0, min(duration_seconds, max_clips * self.clip_seconds), self.clip_seconds):
                result = self._clip_with_retry(video_id, start, min(start + self.clip_seconds, duration_seconds),
                                               deadline, usage)
                if result.segments:
                    return result.language
            return None
        finally:
            totals = usage.as_dict()
            logger.info(
                "gemini_language_detection_usage model=%s requests=%s prompt_tokens=%s output_tokens=%s "
                "thinking_tokens=%s", self.model, totals["requests"], totals["prompt_tokens"],
                totals["output_tokens"], totals["thinking_tokens"],
            )

    def _clip_with_retry(self, video_id: str, start: int, end: int, deadline: float, usage: _Usage) -> _ClipResult:
        last: ContentProviderFailure | None = None
        for _ in range(self.max_attempts):
            if self._clock() >= deadline:
                raise ContentProviderFailure("transient_timeout", transient=True)
            try:
                return self._clip(video_id, start, end, usage)
            except ContentProviderFailure as failure:
                if not failure.transient:
                    raise
                last = failure
        assert last is not None
        raise last

    def _clip(self, video_id: str, start: int, end: int, usage: _Usage | None = None) -> _ClipResult:
        clip_length = float(end - start)
        body = {
            "contents": [{"parts": [
                {"file_data": {"file_uri": f"https://www.youtube.com/watch?v={video_id}"},
                 "video_metadata": {"start_offset": f"{start}s", "end_offset": f"{end}s"}},
                {"text": build_youtube_transcription_prompt(clip_seconds=clip_length)},
            ]}],
            "generationConfig": {"responseMimeType": "application/json", "responseSchema": self._schema(),
                                 "maxOutputTokens": _CLIP_OUTPUT_TOKENS},
        }
        if self.thinking_level:
            body["generationConfig"]["thinkingConfig"] = {"thinkingLevel": self.thinking_level}
        budget = daily_budget()
        prompt_estimate = len(json.dumps(body)) + int(clip_length * _ESTIMATED_VIDEO_TOKENS_PER_SECOND)
        reservation = budget.reserve(text_cost(self.model, prompt_estimate, _CLIP_OUTPUT_TOKENS))
        if reservation is None:
            raise ContentProviderFailure("provider_rate_limit", transient=False)
        try:
            response = self._client.post(
                GEMINI_GENERATE_URL.format(model=self.model), json=body, headers={"x-goog-api-key": self._api_key},
            )
        except httpx.TimeoutException as exc:
            raise ContentProviderFailure("transient_timeout", transient=True) from exc
        except httpx.TransportError as exc:
            raise ContentProviderFailure("transient_network", transient=True) from exc
        if response.status_code == 429:
            raise ContentProviderFailure("provider_rate_limit", transient=True)
        if response.status_code >= 500:
            raise ContentProviderFailure("provider_temporary", transient=True)
        if response.status_code != 200:
            # 400/403/404 here are request or configuration problems; retrying cannot fix them.
            raise ContentProviderFailure("configuration_error", transient=False)
        try:
            payload = response.json()
            metadata = payload.get("usageMetadata")
            if isinstance(metadata, dict):
                prompt_tokens = metadata.get("promptTokenCount")
                output_tokens = metadata.get("candidatesTokenCount")
                if isinstance(prompt_tokens, int) and isinstance(output_tokens, int):
                    cost = text_cost(self.model, prompt_tokens, output_tokens + int(metadata.get("thoughtsTokenCount") or 0))
                    budget.charge(cost, reservation=reservation)
                if usage is not None:
                    usage.add(metadata)
            candidate = payload["candidates"][0]
            if candidate.get("finishReason") != "STOP":
                raise ValueError("incomplete generation")
            parsed = _ClipResponse.model_validate(json.loads(candidate["content"]["parts"][0]["text"]))
            language = parsed.language.strip().lower()
            if language not in self._languages:
                raise ValueError("language outside schema")
            segments = [self._segment(item, start, clip_length) for item in parsed.segments]
        except (KeyError, IndexError, TypeError, ValueError, ValidationError) as exc:
            # Off-schema or incomplete output is a provider failure, never a transcript fact.
            raise ContentProviderFailure("provider_temporary", transient=True) from exc
        return _ClipResult(language=language, segments=segments, model_version=payload.get("modelVersion"))

    @staticmethod
    def _segment(item: _ClipSegment, clip_start: int, clip_length: float) -> TranscribedSegment:
        relative_start, relative_end = parse_clock(item.start), parse_clock(item.end)
        text = " ".join(item.text.split())
        if not text or relative_end < relative_start or relative_start > clip_length:
            raise ValueError("invalid clip segment")
        if relative_end > clip_length + _CLIP_END_TOLERANCE_SECONDS:
            raise ValueError("segment ends outside the clip")
        relative_end = min(max(relative_end, relative_start + _MIN_SEGMENT_SECONDS), clip_length + _CLIP_END_TOLERANCE_SECONDS)
        return TranscribedSegment(start=clip_start + relative_start, end=clip_start + relative_end, text=text)

    def _schema(self) -> dict:
        return {
            "type": "OBJECT",
            "properties": {
                "language": {"type": "STRING", "enum": self._languages},
                "segments": {"type": "ARRAY", "items": {
                    "type": "OBJECT",
                    "properties": {"start": {"type": "STRING"}, "end": {"type": "STRING"}, "text": {"type": "STRING"}},
                    "required": ["start", "end", "text"],
                }},
            },
            "required": ["language", "segments"],
        }


class GeminiYouTubeContentProvider:
    """VideoSourceProvider + TranscriptSourceProvider backed by the Data API and Gemini."""

    source = "youtube"

    def __init__(
        self,
        *,
        data_api: YouTubeDataApiClient,
        transcriber: GeminiYouTubeTranscriber,
        allowed_languages: Iterable[str],
        max_duration_seconds: int,
    ):
        self.data_api = data_api
        self.transcriber = transcriber
        self.allowed_languages = frozenset(code.strip().lower() for code in allowed_languages if code.strip())
        self.max_duration_seconds = max_duration_seconds
        self._ids = YouTubeService()

    def extract_external_video_id(self, url: str) -> str:
        return self._ids.extract_video_id(url)

    def get_video_metadata(self, url: str) -> SourceVideoMetadata:
        video_id = self.extract_external_video_id(url)
        info = self._checked_info(video_id)
        watch_url = f"https://www.youtube.com/watch?v={video_id}"
        return SourceVideoMetadata(
            source=self.source,
            external_video_id=video_id,
            watch_url=watch_url,
            title=info.title,
            description=info.description,
            thumbnail_url=info.thumbnail_url,
            duration_ms=info.duration_seconds * 1000,
            published_at=info.published_at,
            original_language_code=self._original_language(info),
            external_channel_id=info.channel_id or "unknown",
            channel_name=info.channel_title or "Unknown Channel",
            channel_url=f"https://www.youtube.com/channel/{info.channel_id}" if info.channel_id else None,
            metadata={
                "iframe_url": f"https://www.youtube.com/embed/{video_id}",
                "watch_url": watch_url,
                "provider": "youtube_data_api",
                "default_audio_language": info.default_audio_language,
            },
        )

    def get_original_transcript(self, external_video_id: str, language_code: str) -> SourceTranscriptTrack:
        if language_code not in self.allowed_languages:
            raise UnsupportedSourceContent("Language is not enabled for AI transcription")
        # Re-check bounds at execution time: the video may have changed since admission.
        info = self._checked_info(external_video_id)
        result = self.transcriber.transcribe(external_video_id, info.duration_seconds)
        if result.language is None or not result.segments:
            raise UnsupportedSourceContent("No speech was transcribed")
        if result.language != language_code:
            raise UnsupportedSourceContent("Spoken language does not match the video language")
        return SourceTranscriptTrack(
            language_code=language_code,
            source="ai",
            is_original=True,
            provider_metadata={
                "method": TRANSCRIPTION_METHOD,
                "model_requested": self.transcriber.model,
                "model_versions": list(result.model_versions),
                "prompt_version": YOUTUBE_TRANSCRIPTION_PROMPT_VERSION,
                "clip_seconds": self.transcriber.clip_seconds,
                "thinking_level": self.transcriber.thinking_level,
                "detected_language": result.language,
                "usage": result.usage or {},
            },
            segments=[
                SourceTranscriptSegment(
                    sequence_number=index,
                    start_seconds=segment.start,
                    duration_seconds=segment.end - segment.start,
                    text=segment.text,
                )
                for index, segment in enumerate(result.segments, start=1)
            ],
        )

    def get_translated_transcript(self, external_video_id: str, target_language_code: str) -> SourceTranscriptTrack | None:
        return None  # This source produces no translated tracks.

    def _checked_info(self, video_id: str) -> YouTubeVideoInfo:
        info = self.data_api.get_video(video_id)
        if info.privacy_status != "public":
            raise UnsupportedSourceContent("Only public videos are supported")
        if info.live_broadcast_content in {"live", "upcoming"}:
            raise UnsupportedSourceContent("Live videos are not supported")
        if not info.duration_seconds:
            raise UnsupportedSourceContent("Video duration is unknown")
        if info.duration_seconds > self.max_duration_seconds:
            raise UnsupportedSourceContent("Video is longer than the supported maximum")
        return info

    def _original_language(self, info: YouTubeVideoInfo) -> str:
        declared = (info.default_audio_language or "").strip().lower().split("-")[0]
        if declared:
            if declared not in self.allowed_languages:
                raise UnsupportedSourceContent("Declared audio language is not enabled")
            return declared
        if len(self.allowed_languages) == 1:
            # Provisional; the transcript stage verifies it against the spoken language.
            return next(iter(self.allowed_languages))
        # Several languages are enabled and YouTube declares none: listen to the opening clips.
        # Also provisional; the transcript stage verifies the whole video.
        detected = self.transcriber.detect_language(info.video_id, info.duration_seconds)
        if detected is None:
            raise UnsupportedSourceContent("No speech was detected at the start of the video")
        if detected not in self.allowed_languages:
            raise UnsupportedSourceContent("Spoken language is not enabled")
        return detected
