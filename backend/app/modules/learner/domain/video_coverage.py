"""How much of a video a learner is likely to understand: lexical coverage (pure rules).

Coverage is the share of a video's word tokens the learner knows. A word counts as known when it is at or
below the level the learner declared, or when they have already recognised it in practice (rung R1 or higher). About 95% coverage is the usual comfort line for
following spoken video; below 90% it is mostly hard. These are estimates from a transcript and a
dictionary, never a promise, and the callers always say so.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.modules.learner.domain.levels import level_rank, normalize_level

TARGET_COVERAGE = 0.95
CHALLENGING_FROM = 0.90
UNLISTED = "unlisted"  # a dictionary word with no level label
UNMATCHED = "unmatched"  # a form the dictionary does not know (a name, a slip of the speaker or of the captions)


@dataclass(frozen=True)
class ProfileLexeme:
    lexeme: str
    level: str | None
    matched: bool
    occurrences: int
    level_derived: bool = False  # the level was inferred from the word's characters


@dataclass(frozen=True)
class VideoProfile:
    language_code: str
    token_count: int
    proper_noun_count: int
    speech_ms: int
    lexemes: list[ProfileLexeme]


def words_per_minute(token_count: int, speech_ms: int) -> float | None:
    """None when there is too little speech to say anything (under 30 seconds)."""
    if speech_ms < 30_000:
        return None
    return round(token_count / (speech_ms / 60_000), 1)


def label_for(coverage: float) -> str:
    if coverage >= TARGET_COVERAGE:
        return "suitable"
    if coverage >= CHALLENGING_FROM:
        return "challenging"
    return "hard"


def lexeme_level(language_code: str, lexeme: ProfileLexeme) -> str | None:
    """The canonical level label, or None when the dictionary gave none this scale understands."""
    return normalize_level(language_code, lexeme.level) if lexeme.matched else None


def known_by_level(language_code: str, lexeme: ProfileLexeme, declared_level: str | None) -> bool:
    word, declared = level_rank(language_code, lexeme.level if lexeme.matched else None), level_rank(language_code, declared_level)
    return word is not None and declared is not None and word <= declared


def level_distribution(language_code: str, lexemes: list[ProfileLexeme]) -> list[tuple[str, int]]:
    """Tokens per level label, easiest level first, then the dictionary words without a level, then the
    forms the dictionary does not know."""
    totals: dict[str, int] = {}
    for item in lexemes:
        key = lexeme_level(language_code, item) or (UNLISTED if item.matched else UNMATCHED)
        totals[key] = totals.get(key, 0) + item.occurrences
    leveled = sorted((key for key in totals if key not in (UNLISTED, UNMATCHED)),
                     key=lambda key: level_rank(language_code, key) or 0)
    ordered = [*leveled, *(key for key in (UNLISTED, UNMATCHED) if key in totals)]
    return [(key, totals[key]) for key in ordered]


def words_to_reach(total_tokens: int, known_tokens: int, unknown_occurrences: list[int],
                   target: float = TARGET_COVERAGE) -> int | None:
    """How many of the most frequent unknown words, learned, bring coverage to `target`.

    0 when it is already reached; None when even every unknown dictionary word would not be enough."""
    needed = target * total_tokens - known_tokens
    if needed <= 0:
        return 0
    gained = 0
    for count, occurrences in enumerate(sorted(unknown_occurrences, reverse=True), start=1):
        gained += occurrences
        if gained >= needed:
            return count
    return None
