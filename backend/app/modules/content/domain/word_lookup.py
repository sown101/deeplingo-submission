"""Tap-or-select word lookup on a transcript segment: spans and candidate units (pure rules).

The learner selects any span of one segment. Spaced languages snap the selection to whole
words; unspaced ones (Chinese, Japanese, Thai) keep the selected characters. Candidate
units are every window of the segment that contains the selection, longest first, so a
dictionary phrase ("give up", 起床) is found when the learner selected only part of it.
Offsets are Unicode code points, as for LearningObject spans.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

UNSPACED_LANGUAGES = frozenset({"zh", "ja", "th"})
MAX_SELECTION_CHARS = 60
MAX_WINDOW_TOKENS = 4  # spaced languages: "look forward to", "take care of"
MAX_WINDOW_CHARS = 6  # unspaced languages: 一路平安, 不好意思
_WORD = re.compile(r"[^\W_]+(?:['’\-][^\W_]+)*")


class LookupSpanError(ValueError):
    pass


@dataclass(frozen=True)
class Token:
    start: int
    end: int
    text: str


@dataclass(frozen=True)
class Window:
    start: int
    end: int
    text: str
    size: int  # tokens (spaced) or characters (unspaced)
    tokens: tuple[Token, ...] = ()


def is_unspaced(language_code: str) -> bool:
    return language_code.casefold() in UNSPACED_LANGUAGES


def tokenize(text: str) -> list[Token]:
    return [Token(match.start(), match.end(), match.group()) for match in _WORD.finditer(text)]


def snap_selection(text: str, start: int, end: int, language_code: str) -> tuple[int, int]:
    """Validate the span and widen it to whole words (spaced) or trim spaces and punctuation."""
    if not 0 <= start < end <= len(text) or end - start > MAX_SELECTION_CHARS:
        raise LookupSpanError("selection_out_of_range")
    if is_unspaced(language_code):
        while start < end and not text[start].isalnum():
            start += 1
        while end > start and not text[end - 1].isalnum():
            end -= 1
        if start >= end:
            raise LookupSpanError("no_word_selected")
        return start, end
    covered = [token for token in tokenize(text) if token.start < end and token.end > start]
    if not covered:
        raise LookupSpanError("no_word_selected")
    return covered[0].start, covered[-1].end


def candidate_windows(text: str, start: int, end: int, language_code: str) -> list[Window]:
    """Windows of the segment containing the snapped selection, longest first."""
    if is_unspaced(language_code):
        windows = []
        for left in range(max(0, end - MAX_WINDOW_CHARS), start + 1):
            for right in range(end, min(len(text), left + MAX_WINDOW_CHARS) + 1):
                piece = text[left:right]
                if right > left and all(character.isalnum() for character in piece):
                    windows.append(Window(left, right, piece, right - left))
        return sorted(windows, key=lambda window: (-window.size, window.start))
    tokens = tokenize(text)
    first = next(index for index, token in enumerate(tokens) if token.start == start)
    last = next(index for index, token in enumerate(tokens) if token.end == end)
    windows = []
    for left in range(max(0, last - MAX_WINDOW_TOKENS + 1), first + 1):
        for right in range(last, min(len(tokens), left + MAX_WINDOW_TOKENS)):
            span = tokens[left:right + 1]
            windows.append(Window(span[0].start, span[-1].end, " ".join(token.text for token in span),
                                  len(span), tuple(span)))
    return sorted(windows, key=lambda window: (-window.size, window.start))
