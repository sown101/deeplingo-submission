"""M1 S4 practice log values: what the learner practised in one Library video.

Practice only. These summaries feed later turns of the companion and the learner's own history;
they never become Attempts, Evidence, mastery, skills or review scheduling. Dictation is re-checked
here against the server's transcript with the same rules as the web panel (words, or characters in
unspaced languages; case and punctuation ignored); the client's own result is never trusted.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any

from app.modules.learning.domain.speaking import primary_language

UNSPACED_LANGUAGES = frozenset({"zh", "ja", "th"})
MAX_ANSWER_CHARS = 600
MAX_MISSED_WORDS = 5
MAX_LOOKUP_CHARS = 40

_WORD = re.compile(r"[^\W_]+(?:['’-][^\W_]+)*")


def is_unspaced(language_code: str) -> bool:
    return primary_language(language_code) in UNSPACED_LANGUAGES


def dictation_tokens(text: str, unspaced: bool) -> list[str]:
    """Words to write: whole words, or single letters/digits in unspaced languages."""
    if unspaced:
        return [char for char in text if char.isalnum()]
    return _WORD.findall(text)


def _normalize(token: str) -> str:
    return unicodedata.normalize("NFKC", token).casefold().replace("’", "'")


def dictation_diff(expected: list[str], answered: list[str]) -> list[tuple[str, str | None, str | None]]:
    """(kind, expected, answered) items: correct, wrong, missing or extra (LCS alignment, as on the web)."""
    a, b = [_normalize(token) for token in expected], [_normalize(token) for token in answered]
    table = [[0] * (len(b) + 1) for _ in range(len(a) + 1)]
    for i in range(len(a) - 1, -1, -1):
        for j in range(len(b) - 1, -1, -1):
            table[i][j] = table[i + 1][j + 1] + 1 if a[i] == b[j] else max(table[i + 1][j], table[i][j + 1])
    items: list[tuple[str, str | None, str | None]] = []
    i = j = 0
    while i < len(a) or j < len(b):
        if i < len(a) and j < len(b) and a[i] == b[j]:
            items.append(("correct", expected[i], answered[j]))
            i, j = i + 1, j + 1
        elif i < len(a) and j < len(b) and table[i + 1][j + 1] == table[i][j]:
            items.append(("wrong", expected[i], answered[j]))
            i, j = i + 1, j + 1
        elif j < len(b) and (i >= len(a) or table[i][j + 1] >= table[i + 1][j]):
            items.append(("extra", None, answered[j]))
            j += 1
        else:
            items.append(("missing", expected[i], None))
            i += 1
    return items


def dictation_summary(reference: str, answer: str, *, unspaced: bool, level: str, hint_shown: bool) -> dict[str, Any]:
    """The stored summary of one checked answer: counts and a few missed words, never the answer."""
    expected = dictation_tokens(reference, unspaced)
    items = dictation_diff(expected, dictation_tokens(answer[:MAX_ANSWER_CHARS], unspaced))
    missed = [token for kind, token, _ in items if kind in ("missing", "wrong") and token]
    return {
        "total": len(expected),
        "correct": sum(1 for kind, _, _ in items if kind == "correct"),
        "missed": list(dict.fromkeys(missed))[:MAX_MISSED_WORDS],
        "extra": sum(1 for kind, _, _ in items if kind == "extra"),
        "level": level,
        # Reported by the client, kept as such: the server cannot see whether a hint was open.
        "client_reported": {"hint_shown": hint_shown},
    }
