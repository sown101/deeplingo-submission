"""Readable pinyin from CC-CEDICT's numbered syllables ("yin2 hang2" -> "yínháng")."""
from __future__ import annotations

import re

HANYU_PINYIN = "hanyu-pinyin"

_MARKS = {
    "a": "āáǎà", "e": "ēéěè", "i": "īíǐì", "o": "ōóǒò", "u": "ūúǔù", "ü": "ǖǘǚǜ",
}
_SYLLABLE = re.compile(r"^([a-zA-Zü:]+)([1-5])$")


def _marked(syllable: str, tone: int) -> str:
    text = syllable.replace("u:", "ü").replace("U:", "Ü")
    if tone == 5:
        return text
    lowered = text.lower()
    for vowel in ("a", "e"):
        position = lowered.find(vowel)
        if position >= 0:
            break
    else:
        position = lowered.find("ou")
        if position < 0:
            position = max(lowered.rfind(vowel) for vowel in "iouü")
    if position < 0:
        return text
    mark = _MARKS[lowered[position]][tone - 1]
    return text[:position] + (mark.upper() if text[position].isupper() else mark) + text[position + 1:]


def readable_pinyin(numbered: str | None) -> str | None:
    """The first reading of an entry, tone marks in place of numbers. Non-syllables are kept as they are."""
    if not numbered:
        return None
    first = numbered.split(";")[0].strip()
    if not first:
        return None
    parts = []
    for token in first.split():
        match = _SYLLABLE.match(token)
        parts.append(_marked(match.group(1), int(match.group(2))) if match else token)
    return "".join(parts)
