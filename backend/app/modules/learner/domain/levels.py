"""Level labels for words and for learners, and the out-of-level warning.

English uses CEFR (words A1..C2, learners may also say A2+, B1+, B2+); Chinese uses HSK
(HSK1..HSK6, words up to HSK7). There is no official mapping between HSK 3.0 and CEFR, so the two
scales are never converted into each other: a Chinese word is compared only with an HSK level.
"""
from __future__ import annotations

_CEFR_RANK = {"A1": 10, "A2": 20, "A2+": 25, "B1": 30, "B1+": 35, "B2": 40, "B2+": 45, "C1": 50, "C2": 60}
_HSK_RANK = {f"HSK{n}": n * 10 for n in range(1, 8)}

# A word is "above level" when it is more than one whole band above the declared level.
ABOVE_LEVEL_GAP = 15

CEFR_DECLARABLE = ("A1", "A2", "A2+", "B1", "B1+", "B2", "B2+")
HSK_DECLARABLE = tuple(f"HSK{n}" for n in range(1, 7))


def scale_for_language(language_code: str) -> str | None:
    code = (language_code or "").strip().casefold().split("-")[0]
    if code == "en":
        return "CEFR"
    if code == "zh":
        return "HSK"
    return None


def declarable_levels(language_code: str) -> tuple[str, ...]:
    scale = scale_for_language(language_code)
    return CEFR_DECLARABLE if scale == "CEFR" else HSK_DECLARABLE if scale == "HSK" else ()


def normalize_level(language_code: str, label: str | None) -> str | None:
    """The canonical label for this language's scale, or None when it is not a level of that scale."""
    if not label:
        return None
    text = label.strip().upper().replace(" ", "")
    if text.startswith("HSK") and text[3:].isdigit():
        text = f"HSK{int(text[3:])}"
    scale = scale_for_language(language_code)
    if scale == "CEFR" and text in _CEFR_RANK:
        return text
    if scale == "HSK" and text in _HSK_RANK:
        return text
    return None


def level_rank(language_code: str, label: str | None) -> int | None:
    normalized = normalize_level(language_code, label)
    if normalized is None:
        return None
    return _CEFR_RANK.get(normalized) or _HSK_RANK.get(normalized)


def is_above_level(language_code: str, word_label: str | None, declared_label: str | None) -> bool:
    """True only when both levels are known and the word is more than one band above the learner.

    An unclassified word or an undeclared level never warns.
    """
    word, declared = level_rank(language_code, word_label), level_rank(language_code, declared_label)
    if word is None or declared is None:
        return False
    return word - declared >= ABOVE_LEVEL_GAP
