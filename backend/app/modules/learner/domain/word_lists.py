"""Named word lists and the bulk import text (L1b).

A learner pastes one word per line, optionally with their own meaning after a tab, comma or semicolon.
The text is parsed here; the server resolves every word against the dictionary and never lets the
text, or a client, choose a Concept or a meaning.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from uuid import UUID

MAX_LIST_NAME_CHARS = 60
MAX_GROUPS_PER_LEARNER = 50
MAX_WORD_CHARS = 120
MAX_GLOSS_CHARS = 300
MAX_BATCH_LINES = 50  # lines read from one import request; the client sends a longer text in batches
MAX_LIST_ROWS = 500  # words plus waiting lines in one list
MAX_CANDIDATES = 15

_QUOTES = "\"'“”‘’`"
_INVISIBLE = re.compile("[​‌‍⁠﻿]")


@dataclass(frozen=True)
class ImportLine:
    word: str
    gloss: str | None = None


@dataclass(frozen=True)
class ParsedBatch:
    lines: list[ImportLine] = field(default_factory=list)
    blank: int = 0
    duplicates: int = 0
    too_long: int = 0
    over_limit: int = 0


@dataclass(frozen=True)
class SenseCandidate:
    """One dictionary meaning a word could be, as the server found it."""

    entry_id: UUID
    sense_id: str
    headword: str
    text: str
    part_of_speech: str | None = None

    def as_json(self) -> dict:
        return {"entry_id": str(self.entry_id), "sense_id": self.sense_id, "headword": self.headword,
                "text": self.text, "part_of_speech": self.part_of_speech}

    @classmethod
    def from_json(cls, data: dict) -> "SenseCandidate":
        return cls(entry_id=UUID(str(data["entry_id"])), sense_id=str(data["sense_id"]), headword=str(data["headword"]),
                   text=str(data["text"]), part_of_speech=data.get("part_of_speech"))


def validate_list_name(name: str) -> str:
    cleaned = " ".join((name or "").split())
    if not cleaned or len(cleaned) > MAX_LIST_NAME_CHARS:
        raise ValueError(f"A list name has 1 to {MAX_LIST_NAME_CHARS} characters.")
    return cleaned


def _clean(value: str) -> str:
    return " ".join(_INVISIBLE.sub("", value).split()).strip(_QUOTES + " ")


def _split_line(line: str) -> tuple[str, str | None]:
    for separator in ("\t", ",", ";"):
        if separator in line:
            word, _, rest = line.partition(separator)
            return word, rest or None
    return line, None


def parse_import_batch(text: str, *, max_lines: int = MAX_BATCH_LINES) -> ParsedBatch:
    """Reads up to `max_lines` non-empty lines. Blank lines and lines starting with # are ignored."""
    lines: list[ImportLine] = []
    seen: set[str] = set()
    blank = duplicates = too_long = over_limit = 0
    taken = 0
    for raw in (text or "").splitlines():
        stripped = _INVISIBLE.sub("", raw).strip()
        if not stripped or stripped.startswith("#"):
            blank += 1
            continue
        if taken >= max_lines:
            over_limit += 1
            continue
        taken += 1
        word_part, gloss_part = _split_line(stripped)
        word = _clean(word_part)
        if not word or len(word) > MAX_WORD_CHARS:
            too_long += 1
            continue
        key = word.casefold()
        if key in seen:
            duplicates += 1
            continue
        seen.add(key)
        gloss = _clean(gloss_part)[:MAX_GLOSS_CHARS] if gloss_part else None
        lines.append(ImportLine(word=word, gloss=gloss or None))
    return ParsedBatch(lines=lines, blank=blank, duplicates=duplicates, too_long=too_long, over_limit=over_limit)
