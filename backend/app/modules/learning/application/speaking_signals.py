"""How the learner speaks, as coarse levels (PRD FR-3.6): pace and the size of their turns.

Both are rough, language-specific buckets from counts only; no speech and no words are kept. They only
tune how the agent talks to the learner and never reach grading, the usage ladder or review.
"""
from __future__ import annotations

import re
from collections.abc import Sequence

from app.modules.learning.domain.speaking import primary_language

_WORD = re.compile(r"[^\W_]+")
_CJK = re.compile(r"[\u4e00-\u9fff]")
MIN_SPEECH_MS = 3_000
MIN_TURNS = 2
# Words per minute for spaced languages, characters per minute for Chinese: (slow below, fast from).
_PACE = {"zh": (130.0, 230.0), "default": (90.0, 150.0)}
# Average words or characters per turn: (short below, medium below).
_LENGTH = {"zh": (8.0, 20.0), "default": (6.0, 15.0)}


def turn_units(text: str, language_code: str) -> int:
    return len(_CJK.findall(text)) if primary_language(language_code) == "zh" else len(_WORD.findall(text))


def pace_code(units: int, speech_ms: int, language_code: str) -> str | None:
    if speech_ms < MIN_SPEECH_MS:
        return None
    slow, fast = _PACE.get(primary_language(language_code), _PACE["default"])
    per_minute = units * 60_000 / speech_ms
    return "slow" if per_minute < slow else "fast" if per_minute >= fast else "steady"


def turn_length_code(sizes: Sequence[int], language_code: str) -> str | None:
    if len(sizes) < MIN_TURNS:
        return None
    short, medium = _LENGTH.get(primary_language(language_code), _LENGTH["default"])
    average = sum(sizes) / len(sizes)
    return "short" if average < short else "medium" if average < medium else "long"
