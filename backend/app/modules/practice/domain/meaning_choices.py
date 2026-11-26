"""Meaning-choice helpers for the practice exercises: usable meanings, plain dictionary examples and
distractor meanings (never this headword, never close to the answer or to each other)."""
from __future__ import annotations

import hashlib
import re
import unicodedata

# Two meanings sharing this share of their words are too close to be told apart.
MAX_MEANING_OVERLAP = 0.5
DONT_KNOW = "Không nhớ"
MEANINGS_PER_QUESTION = 3
MAX_OPTION_CHARS = 160


class QuickReviewQuestionUnavailable(ValueError):
    pass


def _key(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split()).rstrip(".")


def _words(text: str) -> set[str]:
    return {word for word in _key(text).replace(",", " ").replace(";", " ").split() if word}


def _too_close(a: str, b: str) -> bool:
    """Equal, one inside the other, or mostly the same words: could both be right."""
    key_a, key_b = _key(a), _key(b)
    if not key_a or not key_b or key_a in key_b or key_b in key_a:
        return True
    words_a, words_b = _words(a), _words(b)
    if words_a and words_b and len(words_a & words_b) / len(words_a | words_b) >= MAX_MEANING_OVERLAP:
        return True
    # A list of gloss alternatives must not hide a shared meaning behind extra words.
    # Keep multiword alternatives intact (Vietnamese syllables are not separate meanings).
    for part_a in re.split(r"[,;，；/]", key_a):
        for part_b in re.split(r"[,;，；/]", key_b):
            part_a, part_b = part_a.strip(), part_b.strip()
            if not part_a or not part_b:
                continue
            if part_a == part_b:
                return True
            words_a, words_b = _words(part_a), _words(part_b)
            if words_a and words_b and len(words_a & words_b) / len(words_a | words_b) >= MAX_MEANING_OVERLAP:
                return True
    return False


# Dictionaries quote old literature; a learner should not meet Shakespeare's spelling in a review card.
MAX_DICTIONARY_EXAMPLE_CHARS = 120
_ARCHAIC_WORDS = {"thou", "thee", "thy", "thine", "hath", "doth", "ye", "whilst", "wherefore"}


def plain_dictionary_example(text: str) -> bool:
    """False for a dictionary example that reads like an old quotation (verse line breaks, long s, archaic words)."""
    words = set(re.findall(r"[^\W\d_]+", text.casefold()))
    return len(text) <= MAX_DICTIONARY_EXAMPLE_CHARS and "/" not in text and "\u017f" not in text \
        and not (words & _ARCHAIC_WORDS)


def usable_distractor_meaning(meaning: str, support_language: str) -> bool:
    """A Vietnamese option written only in plain ASCII is most likely an English word left untranslated."""
    return support_language != "vi" or not meaning.isascii()


def pick_meaning_distractors(*, correct: str, headword: str, pool: list[tuple], order_seed: str,
                             part_of_speech: str | None = None) -> list[str]:
    """Two other words' meanings in the answer's language: never this headword, never close to the
    answer or to each other, same part of speech first, in a stable order. `pool` rows are
    (headword, meaning) or (headword, meaning, part_of_speech)."""
    own = _key(headword)
    pos = _key(part_of_speech or "")
    candidates: list[tuple[str, str]] = []
    for row in pool:
        other_headword, gloss = row[0], row[1]
        other_pos = _key(row[2] or "") if len(row) > 2 else ""
        text = " ".join(str(gloss).split())
        if not text or len(text) > MAX_OPTION_CHARS or _key(other_headword) == own or _too_close(text, correct) \
                or _too_close(text, DONT_KNOW):
            continue
        candidates.append((text, other_pos))
    candidates.sort(key=lambda item: (0 if pos and item[1] == pos else 1,
                                      hashlib.sha256(f"{order_seed}:{item[0]}".encode()).hexdigest()))
    chosen: list[str] = []
    for text, _ in candidates:
        if all(not _too_close(text, other) for other in chosen):
            chosen.append(text)
        if len(chosen) == MEANINGS_PER_QUESTION - 1:
            return chosen
    raise QuickReviewQuestionUnavailable("not_enough_distractors")
