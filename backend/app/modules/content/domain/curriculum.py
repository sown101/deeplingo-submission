"""Curriculum file contract (`deeplingo-curriculum-v1`).

A curriculum level is authored as a reviewed TOML file in the repository: DeepLingo-written
grammar points and an ordered list of units, each with Vietnamese can-do statements and
target items. Vocabulary targets name one dictionary sense by `sense_id`; the
`gloss` is the start of that sense's text, kept so a reviewer can read the file and so a
stale sense is detected at load. Grammar targets name a grammar point of the same file.
"""
from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

CURRICULUM_FORMAT = "deeplingo-curriculum-v1"
FRAMEWORK_LEVELS = {
    ("en", "CEFR"): ("A1", "A2", "B1", "B2", "C1", "C2"),
    ("zh", "HSK"): tuple(f"HSK{number}" for number in range(1, 10)),
}
# Grammar inventories by language: what is taught comes from the inventory; the
# explanation and examples are DeepLingo's. "deeplingo" marks a point no inventory lists.
GRAMMAR_INVENTORIES = {"zh": "gf0025-2021", "en": "cefrj-grammar-profile-20180315"}
DEEPLINGO_GRAMMAR = "deeplingo"
MAX_UNIT_WORDS = 12
MAX_UNIT_GRAMMAR = 2
_GRAMMAR_KEY = re.compile(r"^[a-z]{2,3}(\.[a-z0-9_]+)+$")
_UNIT_KEY = re.compile(r"^[a-z]{2,3}\.[a-z0-9]+\.u[0-9]{2}(-[a-z0-9-]+)?$")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class GrammarExample(_Strict):
    text: str = Field(min_length=1, max_length=200)
    translation: str = Field(min_length=1, max_length=200)


class GrammarPointSpec(_Strict):
    key: str = Field(max_length=80)
    title: str = Field(min_length=1, max_length=120)
    pattern: str = Field(min_length=1, max_length=160)
    explanation: str = Field(min_length=1, max_length=1200)
    examples: list[GrammarExample] = Field(min_length=2, max_length=6)
    # Closed-class words a use must contain (pronouns, 是, am/is/are ...); empty for open patterns.
    forms: list[str] = Field(default_factory=list, max_length=40)
    source: str = Field(min_length=1, max_length=40)
    source_ref: str | None = Field(default=None, min_length=1, max_length=40)

    @field_validator("key")
    @classmethod
    def _key(cls, value: str) -> str:
        if not _GRAMMAR_KEY.match(value):
            raise ValueError("grammar key must look like 'en.be_present'")
        return value

    @field_validator("forms")
    @classmethod
    def _forms(cls, value: list[str]) -> list[str]:
        cleaned = [" ".join(item.split()) for item in value]
        if any(not item or len(item) > 40 for item in cleaned) or len(set(cleaned)) != len(cleaned):
            raise ValueError("forms must be distinct, non-empty and at most 40 characters")
        return cleaned


class WordTarget(_Strict):
    headword: str = Field(min_length=1, max_length=80)
    sense_id: str = Field(min_length=1, max_length=80)
    gloss: str = Field(min_length=1, max_length=200)


class UnitSpec(_Strict):
    key: str = Field(max_length=80)
    title: str = Field(min_length=1, max_length=120)
    topic: str = Field(min_length=1, max_length=160)
    can_do: list[str] = Field(min_length=1, max_length=3)
    grammar: list[str] = Field(default_factory=list, max_length=MAX_UNIT_GRAMMAR)
    words: list[WordTarget] = Field(min_length=1, max_length=MAX_UNIT_WORDS)

    @field_validator("key")
    @classmethod
    def _key(cls, value: str) -> str:
        if not _UNIT_KEY.match(value):
            raise ValueError("unit key must look like 'en.a1.u01-greetings'")
        return value

    @field_validator("can_do")
    @classmethod
    def _can_do(cls, value: list[str]) -> list[str]:
        cleaned = [" ".join(item.split()) for item in value]
        if any(not item or len(item) > 200 for item in cleaned):
            raise ValueError("each can_do statement needs 1-200 characters")
        return cleaned


class CurriculumFile(_Strict):
    format: str
    language: str
    framework: str
    level: str
    version: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=120)
    grammar: list[GrammarPointSpec] = Field(default_factory=list, max_length=60)
    units: list[UnitSpec] = Field(min_length=1, max_length=40)

    @model_validator(mode="after")
    def _consistent(self) -> "CurriculumFile":
        if self.format != CURRICULUM_FORMAT:
            raise ValueError(f"format must be {CURRICULUM_FORMAT!r}")
        levels = FRAMEWORK_LEVELS.get((self.language, self.framework))
        if levels is None:
            raise ValueError(f"unsupported language/framework: {self.language}/{self.framework}")
        if self.level not in levels:
            raise ValueError(f"level {self.level!r} is not a {self.framework} level")
        prefix = f"{self.language}."
        unit_prefix = f"{self.language}.{self.level.lower()}.u"
        grammar_keys = [point.key for point in self.grammar]
        _no_duplicates(grammar_keys, "grammar key")
        _no_duplicates([unit.key for unit in self.units], "unit key")
        allowed_sources = {GRAMMAR_INVENTORIES[self.language], DEEPLINGO_GRAMMAR}
        for point in self.grammar:
            if not point.key.startswith(prefix):
                raise ValueError(f"grammar key {point.key!r} must start with {prefix!r}")
            if point.source not in allowed_sources:
                raise ValueError(f"grammar {point.key!r}: source must be one of {sorted(allowed_sources)}")
            if (point.source == DEEPLINGO_GRAMMAR) != (point.source_ref is None):
                raise ValueError(f"grammar {point.key!r}: source_ref is required for an inventory source only")
        known = set(grammar_keys)
        used: set[str] = set()
        for unit in self.units:
            if not unit.key.startswith(unit_prefix):
                raise ValueError(f"unit key {unit.key!r} must start with {unit_prefix!r}")
            _no_duplicates(unit.grammar, f"grammar in {unit.key}")
            _no_duplicates([word.sense_id for word in unit.words], f"sense in {unit.key}")
            for key in unit.grammar:
                if key not in known:
                    raise ValueError(f"{unit.key} uses unknown grammar point {key!r}")
            used.update(unit.grammar)
        unused = sorted(known - used)
        if unused:
            raise ValueError(f"grammar points not used by any unit: {', '.join(unused)}")
        return self


def _no_duplicates(values: list[str], label: str) -> None:
    seen: set[str] = set()
    for value in values:
        if value in seen:
            raise ValueError(f"duplicate {label}: {value!r}")
        seen.add(value)


def gloss_matches(gloss: str, sense_text: str) -> bool:
    """The file's gloss must be the start of the dictionary sense (case and spacing ignored)."""
    def fold(value: str) -> str:
        return " ".join(value.casefold().split())
    return bool(fold(gloss)) and fold(sense_text).startswith(fold(gloss))
