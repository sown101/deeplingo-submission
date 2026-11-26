"""Learner speech audio as a validated, vendor-neutral value.

Clients upload 16 kHz, 16-bit, mono PCM WAV. Audio is processed in memory
and never persisted; only derived, bounded feedback leaves the request.
"""
from __future__ import annotations

import math
import struct
from dataclasses import dataclass

SAMPLE_RATE = 16_000
BYTES_PER_SAMPLE = 2
_FRAME_MS = 30


class SpeechAudioError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class SpeechAudio:
    pcm: bytes
    sample_rate: int = SAMPLE_RATE

    @property
    def duration_ms(self) -> int:
        return len(self.pcm) * 1000 // (BYTES_PER_SAMPLE * self.sample_rate)

    def to_wav(self) -> bytes:
        """Canonical RIFF/WAVE bytes, independent of the uploaded header layout."""
        header = struct.pack(
            "<4sI4s4sIHHIIHH4sI",
            b"RIFF", 36 + len(self.pcm), b"WAVE", b"fmt ", 16, 1, 1,
            self.sample_rate, self.sample_rate * BYTES_PER_SAMPLE, BYTES_PER_SAMPLE, 16,
            b"data", len(self.pcm),
        )
        return header + self.pcm


@dataclass(frozen=True)
class VoiceActivity:
    speech_ms: int
    longest_pause_ms: int
    long_pause_count: int
    span_ms: int = 0  # First to last voiced frame, pauses included.

    @property
    def has_speech(self) -> bool:
        return self.speech_ms >= 300


def parse_wav(data: bytes, *, max_duration_ms: int, min_duration_ms: int = 300) -> SpeechAudio:
    """Accept only PCM 16-bit mono 16 kHz WAV within the duration bounds."""
    if len(data) < 12 or data[0:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise SpeechAudioError("audio_format_unsupported", "Audio must be a WAV file.")
    offset, fmt, pcm = 12, None, None
    while offset + 8 <= len(data):
        chunk_id = data[offset:offset + 4]
        size = struct.unpack_from("<I", data, offset + 4)[0]
        body_start = offset + 8
        if chunk_id == b"fmt ":
            if size < 16 or body_start + 16 > len(data):
                raise SpeechAudioError("audio_format_unsupported", "Audio format header is invalid.")
            fmt = struct.unpack_from("<HHIIHH", data, body_start)
        elif chunk_id == b"data":
            # Streaming recorders may declare an open-ended size; take what was sent.
            pcm = data[body_start:min(len(data), body_start + size)]
            break
        offset = body_start + size + (size % 2)
    if fmt is None or pcm is None:
        raise SpeechAudioError("audio_format_unsupported", "Audio is missing format or data.")
    audio_format, channels, sample_rate, _, _, bits = fmt
    if audio_format != 1 or channels != 1 or bits != 16 or sample_rate != SAMPLE_RATE:
        raise SpeechAudioError(
            "audio_format_unsupported", "Audio must be 16 kHz, 16-bit, mono PCM.",
        )
    if len(pcm) % BYTES_PER_SAMPLE:
        pcm = pcm[:-1]
    audio = SpeechAudio(pcm=pcm, sample_rate=sample_rate)
    if audio.duration_ms < min_duration_ms:
        raise SpeechAudioError("audio_too_short", "The recording is too short.")
    if audio.duration_ms > max_duration_ms:
        raise SpeechAudioError("audio_too_long", "The recording is too long.")
    return audio


def _voiced_frames(audio: SpeechAudio) -> list[bool]:
    """One flag per 30 ms frame: is it louder than the background (energy only)?"""
    frame_bytes = audio.sample_rate * _FRAME_MS // 1000 * BYTES_PER_SAMPLE
    levels = []
    for start in range(0, len(audio.pcm) - frame_bytes + 1, frame_bytes):
        frame = audio.pcm[start:start + frame_bytes]
        samples = struct.unpack(f"<{len(frame) // 2}h", frame)
        levels.append(math.sqrt(sum(sample * sample for sample in samples) / len(samples)))
    if not levels:
        return []
    ordered = sorted(levels)
    loud = ordered[int(len(ordered) * 0.95) - 1] if len(ordered) > 1 else ordered[0]
    threshold = max(400.0, loud * 0.12)
    return [level >= threshold for level in levels]


def trim_to_speech(audio: SpeechAudio, *, pad_ms: int = 200) -> SpeechAudio | None:
    """The first to the last voiced frame with a little margin, or None when there is no speech."""
    voiced = _voiced_frames(audio)
    if sum(voiced) * _FRAME_MS < 300:
        return None
    frame_bytes = audio.sample_rate * _FRAME_MS // 1000 * BYTES_PER_SAMPLE
    pad = audio.sample_rate * pad_ms // 1000 * BYTES_PER_SAMPLE
    first = voiced.index(True)
    last = len(voiced) - 1 - voiced[::-1].index(True)
    return SpeechAudio(pcm=audio.pcm[max(0, first * frame_bytes - pad):min(len(audio.pcm), (last + 1) * frame_bytes + pad)],
                       sample_rate=audio.sample_rate)


def voice_activity(audio: SpeechAudio, *, long_pause_ms: int = 2000) -> VoiceActivity:
    """Energy-based speech/pause estimate; a coarse fluency signal, not ASR."""
    voiced = _voiced_frames(audio)
    if not voiced:
        return VoiceActivity(0, 0, 0, 0)
    first = next((index for index, flag in enumerate(voiced) if flag), None)
    if first is None:
        return VoiceActivity(0, 0, 0, 0)
    last = len(voiced) - 1 - next(index for index, flag in enumerate(reversed(voiced)) if flag)
    speech_frames, longest, pauses, run = 0, 0, 0, 0
    for flag in voiced[first:last + 1]:
        if flag:
            speech_frames += 1
            if run * _FRAME_MS >= long_pause_ms:
                pauses += 1
            longest = max(longest, run)
            run = 0
        else:
            run += 1
    return VoiceActivity(
        speech_ms=speech_frames * _FRAME_MS,
        longest_pause_ms=longest * _FRAME_MS,
        long_pause_count=pauses,
        span_ms=(last - first + 1) * _FRAME_MS,
    )


# A recording that is too quiet, clipped or too short gets a pronunciation score that says more about the
# microphone than the learner (OpenPronounce's `reliable` flag): it is not shown. Thresholds on 16-bit PCM.
QUIET_LEVEL = 300.0  # loud frames below about -40 dBFS
CLIPPED_SAMPLE = 32_000
MAX_CLIPPED_SHARE = 0.005
MIN_SCORED_SPEECH_MS = 600


def audio_quality_issues(audio: SpeechAudio) -> list[str]:
    """"too_quiet", "clipped", "too_short" for a recording whose score should not be shown; [] when it is fine."""
    samples = struct.unpack(f"<{len(audio.pcm) // 2}h", audio.pcm[:len(audio.pcm) // 2 * 2]) if audio.pcm else ()
    if not samples:
        return ["too_short"]
    issues = []
    frame = audio.sample_rate * _FRAME_MS // 1000
    levels = sorted(math.sqrt(sum(value * value for value in samples[start:start + frame]) / frame)
                    for start in range(0, len(samples) - frame + 1, frame))
    if not levels or levels[max(0, int(len(levels) * 0.95) - 1)] < QUIET_LEVEL:
        issues.append("too_quiet")
    if sum(1 for value in samples if abs(value) >= CLIPPED_SAMPLE) > MAX_CLIPPED_SHARE * len(samples):
        issues.append("clipped")
    if voice_activity(audio).speech_ms < MIN_SCORED_SPEECH_MS:
        issues.append("too_short")
    return issues
