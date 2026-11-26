"""HSK 3.0 vocabulary levels (GF 0025-2021) for CC-CEDICT entries.

Reads the community extraction `ivankra/hsk30` (`hsk30.csv`) and imports only the
word-to-level mapping: each CC-CEDICT entry whose headword and reading match an HSK word
gets `provider_metadata.hsk` (its lowest level). Meanings stay CC-CEDICT's. Levels 7-9 are
one band in the standard and are recorded as HSK7.
"""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field

from app.modules.content.infrastructure.dictionaries.grammar_inventories import hsk_level

SOURCE = "gf0025-2021"
SOURCE_DETAIL = "HSK 3.0 (GF 0025-2021), Ministry of Education of the PRC; text via ivankra/hsk30"
_CEDICT_REF = re.compile(r"^[^|\[\]]+\|(?P<simplified>[^\[\]]+)\[(?P<reading>[^\]]+)\]$")


@dataclass
class HskWord:
    simplified: str
    level: str
    readings: set[str] = field(default_factory=set)


@dataclass
class LevelReport:
    matched: int = 0
    unmatched_headword: list[str] = field(default_factory=list)
    unmatched_reading: list[str] = field(default_factory=list)


def level_rank(level: str) -> int:
    return int(level.removeprefix("HSK"))


def parse_word_levels(path: str) -> dict[str, HskWord]:
    """One HskWord per simplified headword at its lowest level, with the CC-CEDICT readings."""
    with open(path, encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows or not {"Simplified", "Level", "CEDICT"} <= set(rows[0]):
        raise ValueError("expected hsk30.csv with Simplified, Level and CEDICT columns")
    words: dict[str, HskWord] = {}
    for row in rows:
        level = hsk_level(row["Level"])
        references = [_CEDICT_REF.match(part.strip()) for part in row["CEDICT"].split("/") if part.strip()]
        for simplified in headword_forms(row["Simplified"]):
            readings = {" ".join(match["reading"].casefold().split())
                        for match in references if match and match["simplified"] == simplified}
            current = words.get(simplified)
            if current is None or level_rank(level) < level_rank(current.level):
                words[simplified] = HskWord(simplified, level, readings)
            elif level == current.level:
                current.readings |= readings
    return words


_ANNOTATION = re.compile(r"（([^（）]*)）")


def headword_forms(value: str) -> list[str]:
    """`哥哥|哥` lists two forms; `们（朋友们）` annotates an example; `有（一）些` marks an optional part."""
    forms: list[str] = []
    for part in (piece.strip() for piece in value.split("|")):
        if not part:
            continue
        bare = _ANNOTATION.sub("", part).strip()
        inline = _ANNOTATION.sub(r"\1", part).strip()
        trailing = part.endswith("）")  # a trailing annotation is an example, not part of the word
        for form in (bare,) if trailing else (bare, inline):
            if form and form not in forms:
                forms.append(form)
    return forms


def apply_levels(rows: list[dict], words: dict[str, HskWord]) -> tuple[list[dict], LevelReport]:
    """Rows to write back: entries whose headword and a reading match get `hsk` metadata."""
    by_headword = {row["normalized_headword"]: row for row in rows}
    report, updated = LevelReport(), []
    for simplified, word in sorted(words.items()):
        row = by_headword.get(simplified)
        if row is None:
            report.unmatched_headword.append(simplified)
            continue
        readings = {" ".join(str(sense.get("reading", "")).casefold().split())
                    for sense in row.get("definitions") or [] if isinstance(sense, dict)}
        if word.readings and not word.readings & readings:
            report.unmatched_reading.append(simplified)
            continue
        metadata = dict(row.get("provider_metadata") or {})
        if metadata.get("hsk") == word.level and metadata.get("hsk_source") == SOURCE:
            report.matched += 1
            continue
        metadata.update({"hsk": word.level, "hsk_source": SOURCE})
        updated.append({**row, "provider_metadata": metadata})
        report.matched += 1
    return updated, report
