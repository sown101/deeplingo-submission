"""Pronunciation feedback inside a conversation (PRD FR-3.8).

The learner's audio of one turn is held in memory only, scored once against the words the learner said
(the two-pass method for free speech) and dropped. What leaves is the turn's overall pronunciation number
with its few weak words on the learner's screen, and the weak words in the end-of-session summary: practice
feedback, never the usage ladder.
"""
from __future__ import annotations

from collections.abc import Iterable

from app.modules.learning.domain.speaking import PronunciationErrorType, PronunciationResult
from app.modules.learning.domain.speech_audio import BYTES_PER_SAMPLE, SAMPLE_RATE

# Azure's short-audio REST API advises at most 30 s for pronunciation assessment.
MAX_TURN_AUDIO_MS = 30_000
MAX_SCORED_TURNS = 20
MAX_TURN_TEXT_CHARS = 300
MAX_WEAK_WORDS = 6
WEAK_ACCURACY = 60.0
_BUFFER_BYTES = 2 * MAX_TURN_AUDIO_MS * SAMPLE_RATE * BYTES_PER_SAMPLE // 1000


class TurnAudioBuffer:
    """Microphone audio since the last turn, newest last, bounded. Never written anywhere."""

    def __init__(self, max_bytes: int = _BUFFER_BYTES):
        self.max_bytes = max_bytes
        self._data = bytearray()
        self._truncated = False

    def add(self, pcm: bytes) -> None:
        self._data += pcm
        if len(self._data) > self.max_bytes:
            del self._data[:len(self._data) - self.max_bytes]
            self._truncated = True

    def take(self) -> tuple[bytes, bool]:
        """The audio so far and whether its start was dropped; the buffer is empty afterwards."""
        data, truncated = bytes(self._data), self._truncated
        self.clear()
        return data, truncated

    def clear(self) -> None:
        self._data = bytearray()
        self._truncated = False


def weak_words(results: Iterable[PronunciationResult]) -> list[str]:
    """Words that sounded wrong, worst first. Omissions and insertions are ignored: the reference is the
    recognised transcript, so they usually mean the two recognisers disagreed, not that the learner erred."""
    worst: dict[str, float] = {}
    for result in results:
        for word in result.words:
            weak = word.error_type == PronunciationErrorType.MISPRONUNCIATION or (
                word.error_type == PronunciationErrorType.NONE and word.accuracy < WEAK_ACCURACY)
            key = " ".join(word.word.casefold().split())
            if weak and key:
                worst[key] = min(worst.get(key, 100.0), word.accuracy)
    return [key for key, _ in sorted(worst.items(), key=lambda item: (item[1], item[0]))][:MAX_WEAK_WORDS]
