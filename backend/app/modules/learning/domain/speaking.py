"""Speaking-practice values and deterministic policies.

Speaking practice is non-evidential: nothing here creates Attempts,
Assessments, Evidence, mastery, skill or review effects.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from enum import Enum


class PronunciationErrorType(str, Enum):
    NONE = "none"
    MISPRONUNCIATION = "mispronunciation"
    OMISSION = "omission"
    INSERTION = "insertion"
    UNEXPECTED_BREAK = "unexpected_break"
    MISSING_BREAK = "missing_break"
    MONOTONE = "monotone"
    OTHER = "other"


@dataclass(frozen=True)
class PronunciationPhoneme:
    phoneme: str
    accuracy: float


@dataclass(frozen=True)
class PronunciationWord:
    word: str
    accuracy: float
    error_type: PronunciationErrorType
    start_ms: int | None = None
    end_ms: int | None = None
    phonemes: tuple[PronunciationPhoneme, ...] = ()


@dataclass(frozen=True)
class PronunciationScores:
    pronunciation: float
    accuracy: float
    fluency: float
    completeness: float
    prosody: float | None = None


@dataclass(frozen=True)
class PronunciationResult:
    recognized_text: str
    scores: PronunciationScores
    words: tuple[PronunciationWord, ...] = field(default_factory=tuple)


class FeedbackBand(str, Enum):
    EXCELLENT = "excellent"
    GOOD = "good"
    FAIR = "fair"
    RETRY = "retry"


def feedback_band(pronunciation_score: float) -> FeedbackBand:
    if pronunciation_score >= 90:
        return FeedbackBand.EXCELLENT
    if pronunciation_score >= 75:
        return FeedbackBand.GOOD
    if pronunciation_score >= 55:
        return FeedbackBand.FAIR
    return FeedbackBand.RETRY


def spoken_span_ms(words: tuple[PronunciationWord, ...]) -> int | None:
    timed = [word for word in words if word.start_ms is not None and word.end_ms is not None
             and word.error_type != PronunciationErrorType.OMISSION]
    if not timed:
        return None
    return max(word.end_ms for word in timed) - min(word.start_ms for word in timed)


# Scripts written without spaces between words: match by substring instead of
# whole words. Everything else is matched on word boundaries.
_UNSPACED_LANGUAGES = frozenset({"zh", "ja", "th", "lo", "km", "my"})


def primary_language(language_code: str) -> str:
    return (language_code or "").split("-")[0].casefold()


def normalize_for_matching(text: str) -> str:
    folded = unicodedata.normalize("NFKC", text or "").casefold()
    cleaned = "".join(
        character if (character.isalnum() or unicodedata.category(character).startswith("M")
                      or character in "'’") else " "
        for character in folded
    )
    return " ".join(cleaned.replace("’", "'").split())


def contains_form(text: str, form: str, language_code: str) -> bool:
    """True when ``form`` occurs in ``text`` as a whole word or word sequence."""
    haystack, needle = normalize_for_matching(text), normalize_for_matching(form)
    if not haystack or not needle:
        return False
    if primary_language(language_code) in _UNSPACED_LANGUAGES:
        return needle.replace(" ", "") in haystack.replace(" ", "")
    return f" {needle} " in f" {haystack} "


@dataclass(frozen=True)
class HintMatcher:
    """Deterministic detection of whether the learner used one offered item."""

    hint_id: str
    forms: tuple[str, ...]

    def used_in(self, text: str, language_code: str) -> bool:
        return any(contains_form(text, form, language_code) for form in self.forms)


def used_hint_ids(text: str, hints: list[HintMatcher], language_code: str) -> list[str]:
    return [hint.hint_id for hint in hints if hint.used_in(text, language_code)]


def spoken_unit_count(text: str, language_code: str) -> int:
    """Words for spaced scripts, characters for unspaced scripts."""
    normalized = normalize_for_matching(text)
    if primary_language(language_code) in _UNSPACED_LANGUAGES:
        return len(normalized.replace(" ", ""))
    return len(normalized.split())


_WORD_RE = re.compile(r"\w+", re.UNICODE)


def is_grounded_quote(quote: str, transcript: str) -> bool:
    """A model quote must be an exact (whitespace/case-insensitive) transcript span."""
    if not quote or not _WORD_RE.search(quote):
        return False
    collapse = lambda value: " ".join(unicodedata.normalize("NFKC", value).casefold().split())
    return collapse(quote) in collapse(transcript)
