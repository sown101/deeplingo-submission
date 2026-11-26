"""The word profile of a transcript: counted word tokens and rules to find them (pure rules).

A profile answers "what words does this video use, how often, and how fast is it spoken". Spaced
languages (English) are split into words; unspaced ones (Chinese) are cut by greedy longest match
against the dictionary's headwords. These are estimates, not linguistic truth: a name or an
ASR error is counted as a word the dictionary does not know, and Chinese cutting can pick a
longer word where a shorter pair was meant. Callers always present the numbers as estimates.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from app.modules.content.domain.word_lookup import tokenize

PROFILE_VERSION = 3  # 2: an inflection with no level counts as its base form; 3: derived compound levels
MAX_CJK_WORD_CHARS = 4
_CJK_RUN = re.compile(r"[一-鿿㐀-䶿]+")
_APOSTROPHES = str.maketrans({"’": "'", "‘": "'"})
_IRREGULAR_CONTRACTIONS = {"can't": "can", "won't": "will", "shan't": "shall", "ain't": "be"}
_CONTRACTION_ENDINGS = ("'s", "'re", "'ve", "'ll", "'d", "'m")


@dataclass(frozen=True)
class WordToken:
    form: str  # the surface form as written, lower-cased for spaced languages


@dataclass(frozen=True)
class SegmentWords:
    tokens: list[WordToken]
    proper_nouns: int


def split_contraction(word: str) -> str:
    """"don't" -> "do", "it's" -> "it": the word a contraction is built on. Other words are unchanged."""
    lowered = word.translate(_APOSTROPHES).casefold()
    if lowered in _IRREGULAR_CONTRACTIONS:
        return _IRREGULAR_CONTRACTIONS[lowered]
    if lowered.endswith("n't") and len(lowered) > 3:
        return lowered[:-3]
    for ending in _CONTRACTION_ENDINGS:
        if lowered.endswith(ending) and len(lowered) > len(ending):
            return lowered[: -len(ending)]
    return lowered


def spaced_words(text: str) -> SegmentWords:
    """English-like text: words without digits. A capitalised word inside a sentence is a name and is
    left out of the count (as lexical-coverage studies do), not treated as an unknown word."""
    tokens: list[WordToken] = []
    proper = 0
    for index, token in enumerate(tokenize(text.translate(_APOSTROPHES))):
        word = token.text
        if any(character.isdigit() for character in word):
            continue
        stem = word.split("'")[0]
        if index > 0 and stem != "I" and stem[:1].isupper() and not stem.isupper():
            proper += 1
            continue
        tokens.append(WordToken(split_contraction(word)))
    return SegmentWords(tokens, proper)


def cjk_runs(text: str) -> list[str]:
    """The runs of Chinese characters; Latin letters, digits and punctuation split them and are skipped."""
    return _CJK_RUN.findall(text)


def candidate_cjk_words(runs: list[str]) -> set[str]:
    """Every 1..4 character piece of every run: the keys to look up in the dictionary."""
    pieces: set[str] = set()
    for run in runs:
        for start in range(len(run)):
            for size in range(1, MAX_CJK_WORD_CHARS + 1):
                if start + size <= len(run):
                    pieces.add(run[start:start + size])
    return pieces


def cut_cjk_run(run: str, known: set[str]) -> list[str]:
    """Greedy longest match from the left. A character no dictionary word starts with stands alone."""
    words: list[str] = []
    position = 0
    while position < len(run):
        size = min(MAX_CJK_WORD_CHARS, len(run) - position)
        while size > 1 and run[position:position + size] not in known:
            size -= 1
        words.append(run[position:position + size])
        position += size
    return words


def derive_compound_level(word: str, char_levels: dict[str, str | None]) -> str | None:
    """The level of a multi-character word the level list does not name: the highest level among its
    characters, only when every character has one ("每天" = 每 + 天). None otherwise. The caller marks the
    result as inferred; it is a reading aid, not a dictionary fact."""
    if len(word) < 2:
        return None
    levels = [char_levels.get(character) for character in word]
    if any(level is None for level in levels):
        return None
    ranked = [(_level_number(level), level) for level in levels]
    if any(number is None for number, _ in ranked):
        return None
    return max(ranked)[1]


def _level_number(label: str | None) -> int | None:
    digits = "".join(character for character in label or "" if character.isdigit())
    return int(digits) if digits else None


def spoken_milliseconds(spans: list[tuple[int, int]]) -> int:
    """Time with a caption on screen: the union of the (start, end) spans, so overlaps and silence between
    captions do not change a speech rate."""
    total = 0
    current_start = current_end = None
    for start, end in sorted(spans):
        if end <= start:
            continue
        if current_end is None or start > current_end:
            if current_end is not None:
                total += current_end - current_start
            current_start, current_end = start, end
        else:
            current_end = max(current_end, end)
    if current_end is not None:
        total += current_end - current_start
    return total

