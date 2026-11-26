"""Synthetic audio helpers for speaking-practice tests (no real recordings)."""
import math
import struct


def pcm_tone(duration_ms: int, *, amplitude: int = 8000, frequency: float = 220.0, rate: int = 16_000) -> bytes:
    count = rate * duration_ms // 1000
    return struct.pack(f"<{count}h", *(
        int(amplitude * math.sin(2 * math.pi * frequency * index / rate)) for index in range(count)))


def pcm_silence(duration_ms: int, rate: int = 16_000) -> bytes:
    return b"\x00\x00" * (rate * duration_ms // 1000)


def wav_bytes(pcm: bytes, *, rate: int = 16_000, channels: int = 1, bits: int = 16, audio_format: int = 1,
              extra_chunk: bytes = b"", declared_data_size: int | None = None) -> bytes:
    block = channels * bits // 8
    fmt = struct.pack("<4sIHHIIHH", b"fmt ", 16, audio_format, channels, rate, rate * block, block, bits)
    data = struct.pack("<4sI", b"data", len(pcm) if declared_data_size is None else declared_data_size) + pcm
    body = b"WAVE" + fmt + extra_chunk + data
    return struct.pack("<4sI", b"RIFF", len(body)) + body


def speech_like_wav(duration_ms: int = 2000) -> bytes:
    return wav_bytes(pcm_tone(duration_ms))
