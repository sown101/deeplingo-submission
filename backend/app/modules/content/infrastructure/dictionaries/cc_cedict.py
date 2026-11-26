"""CC-CEDICT parser producing `v3.dictionary_entries` rows.

One row per simplified headword with `part_of_speech=""`, which is how
`DictionaryEntryResolver` looks entries up. Traditional forms are kept per sense; a
traditional-to-simplified lookup step is separate work, so traditional headwords are
not duplicated as rows (that doubled the import to ~160 MB of JSON). Every
gloss is a sense with a deterministic `sense_id`, so re-imports keep IDs stable and the
enrichment model can select one exact sense instead of writing its own meaning.
"""
import hashlib
import re
from dataclasses import dataclass
from typing import Iterable

from app.modules.content.domain.dictionary_sources import DICTIONARY_SOURCES
from app.modules.content.application.knowledge_resolution import normalize_reference_text

SOURCE = "cc-cedict"
LICENSE_URL = DICTIONARY_SOURCES[SOURCE].license_url
ATTRIBUTION = "CC-CEDICT, MDBG (https://www.mdbg.net/chinese/dictionary?page=cc-cedict), CC BY-SA 4.0"

_LINE = re.compile(r"^(\S+) (\S+) \[([^\]]*)\] /(.*)/\s*$")
_VARIANT = re.compile(r"\b(?:old |archaic |erhua |Japanese |used as |also written )?variant of\b", re.IGNORECASE)


@dataclass(frozen=True)
class CedictLine:
    traditional: str
    simplified: str
    reading: str
    glosses: tuple[str, ...]
    classifiers: tuple[str, ...]


def parse_line(line: str) -> CedictLine | None:
    """Parse one CC-CEDICT line; comments and malformed lines return None."""
    if not line or line.startswith("#"):
        return None
    match = _LINE.match(line.rstrip("\n"))
    if not match:
        return None
    traditional, simplified, reading, body = match.groups()
    glosses, classifiers = [], []
    for part in (piece.strip() for piece in body.split("/")):
        if not part:
            continue
        if part.startswith("CL:"):
            classifiers.extend(item.strip() for item in part[3:].split(",") if item.strip())
        else:
            glosses.append(part)
    if not glosses:
        return None
    return CedictLine(traditional, simplified, " ".join(reading.split()), tuple(glosses), tuple(classifiers))


def sense_id(*, simplified: str, traditional: str, reading: str, gloss: str) -> str:
    digest = hashlib.sha1(f"{SOURCE}|{simplified}|{traditional}|{reading}|{gloss}".encode("utf-8")).hexdigest()
    return f"cedict:{digest[:16]}"


def build_rows(lines: Iterable[str], *, source_date: str | None = None) -> list[dict]:
    """Group parsed lines into one row per headword; deterministic order."""
    senses_by_headword: dict[str, list[dict]] = {}
    readings_by_headword: dict[str, list[str]] = {}
    for raw in lines:
        entry = parse_line(raw)
        if entry is None:
            continue
        senses = []
        for gloss in entry.glosses:
            sense = {"sense_id": sense_id(simplified=entry.simplified, traditional=entry.traditional,
                                          reading=entry.reading, gloss=gloss),
                     "text": gloss, "reading": entry.reading}
            if entry.traditional != entry.simplified:
                sense["traditional"] = entry.traditional
            if entry.classifiers:
                sense["classifiers"] = list(entry.classifiers)
            if _VARIANT.search(gloss):
                sense["is_variant_reference"] = True
            senses.append(sense)
        headword = entry.simplified
        senses_by_headword.setdefault(headword, []).extend(senses)
        readings = readings_by_headword.setdefault(headword, [])
        if entry.reading not in readings:
            readings.append(entry.reading)

    rows = []
    for headword in sorted(senses_by_headword):
        unique = list({sense["sense_id"]: sense for sense in senses_by_headword[headword]}.values())
        # Licence and attribution live once in this module (LICENSE_URL, ATTRIBUTION), keyed by
        # `provider`; repeating them per row added ~24 MB to the import.
        metadata = {"source": SOURCE, "source_date": source_date}
        rows.append({
            "language_code": "zh",
            "headword": headword,
            "normalized_headword": normalize_reference_text(headword, language_code="zh"),
            "part_of_speech": "",
            "pronunciation": "; ".join(readings_by_headword[headword]),
            "definitions": unique,
            "examples": [],
            "provider": SOURCE,
            "provider_metadata": metadata,
        })
    return rows


def header_value(lines: Iterable[str], key: str) -> str | None:
    """Read a `#! key=value` header value, e.g. `date`."""
    prefix = f"#! {key}="
    for line in lines:
        if not line.startswith("#"):
            break
        if line.startswith(prefix):
            return line[len(prefix):].strip()
    return None
