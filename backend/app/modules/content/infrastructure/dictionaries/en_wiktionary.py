"""English Wiktionary (kaikki.org wiktextract JSONL) to `v3.dictionary_entries` rows.

The full English dump is ~3 GB, so only learner-relevant headwords are kept:

- core lemmas from open word lists (CEFR-J 1.5, Octanove C1/C2, NGSL 1.2);
- inflected forms whose Wiktionary entry is a `form_of` a core lemma ("went" -> "go");
- multiword expressions (phrasal verbs, idioms, compounds, set phrases) made of core lemmas,
  their inflected forms and generic placeholders ("break the ice", "get started", "bus stop");
  interjections, phrases and proverbs may contain one word outside the lists ("oh well").
  Expressions that are only inflections of another ("gave up", "bus stops") are skipped
  because candidates are normalized to lemma form.

When a lower-case entry exists, differently cased entries of the same key are dropped
("GO", graphene oxide, does not join "go").

Like CC-CEDICT, there is one row per normalized headword with `part_of_speech=""`
(the resolver's lookup key); each sense carries its own `pos`. Obsolete/archaic senses,
misspellings and proper names are dropped. Every sense has a deterministic `sense_id`,
so re-imports of the same gloss keep their IDs for the enrichment model to select.
"""
import csv
import gzip
import hashlib
import json
from dataclasses import dataclass, field
from typing import Iterable, Iterator

from app.modules.content.domain.dictionary_sources import DICTIONARY_SOURCES
from app.modules.content.application.knowledge_resolution import CandidateResolutionError, normalize_reference_text

SOURCE = "en-wiktionary"
LICENSE_URL = DICTIONARY_SOURCES[SOURCE].license_url
ATTRIBUTION = ("Wiktionary (https://en.wiktionary.org), extracted by wiktextract/kaikki.org, CC BY-SA 4.0 and GFDL; "
               "headword selection uses CEFR-J Wordlist 1.5 (Tono Laboratory, TUFS), Octanove Vocabulary Profile "
               "C1/C2 (CC BY-SA 4.0) and the New General Service List 1.2 (CC BY-SA 4.0)")

_SKIPPED_POS = {"name", "character", "symbol", "prefix", "suffix", "infix", "interfix", "affix", "circumfix",
                "punct", "romanization", "abbrev"}
_SKIPPED_SENSE_TAGS = {"obsolete", "archaic", "misspelling", "no-gloss", "nonstandard", "pronunciation-spelling"}
_PLACEHOLDERS = {"one", "one's", "oneself", "someone", "someone's", "somebody", "somebody's", "something",
                 "something's", "somewhere", "sb", "sth", "the", "a", "an", "to"}
_CEFR_ORDER = ["A1", "A2", "B1", "B2", "C1", "C2"]
MAX_EXPRESSION_TOKENS = 5
_PHRASE_POS = {"intj", "phrase", "proverb", "prep_phrase"}
MAX_EXAMPLE_CHARS = 200


def _norm(text: str) -> str:
    """Resolver-compatible key; headwords that normalize to nothing (e.g. a bare quote) give ""."""
    try:
        return normalize_reference_text(text, language_code="en")
    except CandidateResolutionError:
        return ""


@dataclass
class CoreWordList:
    """Learner word lists: normalized lemma -> CEFR level (None when only in NGSL)."""

    levels: dict[str, str | None] = field(default_factory=dict)

    def add(self, headword: str, level: str | None) -> None:
        for variant in headword.split("/"):
            key = _norm(variant)
            if not key:
                continue
            current = self.levels.get(key)
            if current is None or (level in _CEFR_ORDER and _CEFR_ORDER.index(level) < _CEFR_ORDER.index(current)):
                self.levels[key] = level if level in _CEFR_ORDER else current

    def __contains__(self, key: str) -> bool:
        return key in self.levels

    def add_frequency_list(self, path: str, *, max_rank: int) -> None:
        """Add lemmas from a ranked frequency list (NGSL 31K: `Lemma`, `RawFreq_Rank`) up to `max_rank`."""
        with open(path, encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                try:
                    rank = int(float(row.get("RawFreq_Rank") or 0))
                except ValueError:
                    continue
                lemma = (row.get("Lemma") or "").strip()
                if 0 < rank <= max_rank and lemma and lemma.isalpha() and lemma == lemma.lower():
                    self.add(lemma, None)

    @classmethod
    def from_files(cls, *, cefrj: Iterable[str] = (), ngsl: Iterable[str] = (),
                   frequency: Iterable[str] = (), max_rank: int = 0) -> "CoreWordList":
        words = cls()
        for path in frequency:
            words.add_frequency_list(path, max_rank=max_rank)
        for path in cefrj:
            with open(path, encoding="utf-8", newline="") as handle:
                for row in csv.DictReader(handle):
                    words.add(row["headword"], (row.get("CEFR") or "").strip().upper() or None)
        for path in ngsl:
            with open(path, encoding="utf-8", newline="") as handle:
                for row in csv.DictReader(handle):
                    words.add(row["Lemma"], None)
        return words


def iter_entries(path: str) -> Iterator[dict]:
    """Stream English entries from a kaikki JSONL file (plain or gzip)."""
    opener = gzip.open if path.endswith(".gz") else open
    with opener(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            entry = json.loads(line)
            if entry.get("lang_code") == "en" and entry.get("pos") not in _SKIPPED_POS:
                yield entry


def _tokens(word: str) -> list[str]:
    return [token for token in _norm(word).replace("-", " ").split() if token]


def form_of_targets(entry: dict) -> set[str]:
    return {_norm(target["word"]) for sense in entry.get("senses", ())
            for target in sense.get("form_of", ()) if target.get("word")}


def is_relevant(entry: dict, core: CoreWordList, forms: set[str]) -> bool:
    """Decide whether an entry belongs to the learner subset (see module docstring)."""
    key = _norm(entry.get("word", ""))
    if not key:
        return False
    if key in core or key in forms:
        return True
    tokens = _tokens(key)
    if len(tokens) < 2 or len(tokens) > MAX_EXPRESSION_TOKENS:
        return False
    if all(sense.get("form_of") for sense in entry.get("senses", ())):
        return False
    known = [token for token in tokens if token not in _PLACEHOLDERS]
    if not known:
        return False
    outside = sum(1 for token in known if token not in core and token not in forms)
    # Phrase-like entries ("oh well", proverbs) may carry one word the frequency lists omit.
    return outside == 0 or (outside == 1 and len(known) > 1 and entry.get("pos") in _PHRASE_POS)


def collect_forms(entries: Iterable[dict], core: CoreWordList) -> set[str]:
    """First pass: single-word headwords whose entry is an inflection of a core lemma."""
    forms = set()
    for entry in entries:
        key = _norm(entry.get("word", ""))
        if key and " " not in key and key not in core and form_of_targets(entry) & core.levels.keys():
            forms.add(key)
    return forms


def sense_id(*, word: str, pos: str, gloss: str) -> str:
    digest = hashlib.sha1(f"{SOURCE}|{_norm(word)}|{pos}|{gloss}".encode("utf-8")).hexdigest()
    return f"enwikt:{digest[:16]}"


def _senses(entry: dict) -> list[dict]:
    word, pos = entry["word"], entry["pos"]
    senses = []
    for raw in entry.get("senses", ()):
        tags = set(raw.get("tags", ()))
        glosses = [gloss.strip() for gloss in raw.get("glosses", ()) if gloss and gloss.strip()]
        if not glosses or tags & _SKIPPED_SENSE_TAGS:
            continue
        sense = {"sense_id": sense_id(word=word, pos=pos, gloss=" | ".join(glosses)), "text": glosses[-1], "pos": pos}
        if len(glosses) > 1:
            sense["parent"] = glosses[-2]
        labels = sorted(tags - {"form-of", "alt-of"})
        if labels:
            sense["tags"] = labels
        if raw.get("form_of"):
            sense["form_of"] = sorted({target["word"] for target in raw["form_of"] if target.get("word")})
        if raw.get("alt_of"):
            sense["is_variant_reference"] = True
        example = next((ex.get("text", "").strip() for ex in raw.get("examples", ())
                        if 0 < len(ex.get("text", "").strip()) <= MAX_EXAMPLE_CHARS), None)
        if example:
            sense["example"] = example
        senses.append(sense)
    return senses


def _pronunciation(entries: list[dict]) -> str | None:
    found: dict[str, str] = {}
    for entry in entries:
        for sound in entry.get("sounds", ()):
            ipa = sound.get("ipa")
            if not ipa:
                continue
            tags = set(sound.get("tags", ()))
            accent = "US" if tags & {"US", "General-American"} else "UK" if tags & {"UK", "Received-Pronunciation"} else ""
            found.setdefault(accent, ipa)
    parts = [f"{accent} {found[accent]}" for accent in ("US", "UK") if accent in found]
    if not parts and "" in found:
        parts.append(found[""])
    return "; ".join(parts) or None


def build_rows(entries: Iterable[dict], core: CoreWordList, forms: set[str], *,
               source_date: str | None = None) -> list[dict]:
    """Second pass: group relevant entries into one row per normalized headword."""
    grouped: dict[str, list[dict]] = {}
    for entry in entries:
        if is_relevant(entry, core, forms):
            grouped.setdefault(_norm(entry["word"]), []).append(entry)

    rows = []
    for key in sorted(grouped):
        entries_for_key = [entry for entry in grouped[key] if entry["word"] == key] or grouped[key]
        senses = list({sense["sense_id"]: sense for entry in entries_for_key for sense in _senses(entry)}.values())
        if not senses:
            continue
        # Prefer the lower-case spelling as the display headword ("may" over "May").
        headword = min((entry["word"] for entry in entries_for_key), key=lambda word: (word != word.lower(), word))
        metadata = {"source": SOURCE, "source_date": source_date}
        if core.levels.get(key):
            metadata["cefr_j"] = core.levels[key]
        rows.append({
            "language_code": "en",
            "headword": headword,
            "normalized_headword": key,
            "part_of_speech": "",
            "pronunciation": _pronunciation(entries_for_key),
            "definitions": senses,
            "examples": [],
            "provider": SOURCE,
            "provider_metadata": metadata,
        })
    return rows
