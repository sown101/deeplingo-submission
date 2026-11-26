"""Load a reviewed curriculum file into global content.

Parsing and validation never write. Every vocabulary target must resolve to an existing
dictionary entry whose `sense_id` and gloss match, otherwise the whole file is
rejected with every problem listed. Writing replaces the level atomically through the
curriculum store; an unchanged file (same content hash) is skipped.
"""
from __future__ import annotations

import hashlib
import json
import tomllib
from dataclasses import dataclass, field
from typing import Any, Protocol

from pydantic import ValidationError

from app.modules.content.application.knowledge_resolution import normalize_reference_text
from app.modules.content.application.store_ports import DictionaryEntryStore
from app.modules.content.domain.curriculum import (
    DEEPLINGO_GRAMMAR,
    FRAMEWORK_LEVELS,
    CurriculumFile,
    gloss_matches,
)


class CurriculumFileError(ValueError):
    def __init__(self, problems: list[str]):
        super().__init__("; ".join(problems))
        self.problems = problems


class CurriculumStore(Protocol):
    def content_hash(self, *, language_code: str, framework: str, level: str) -> str | None: ...

    def load_level(self, payload: dict[str, Any]) -> dict[str, Any]: ...


@dataclass(frozen=True)
class CurriculumPlan:
    curriculum: CurriculumFile
    payload: dict[str, Any]
    warnings: list[str] = field(default_factory=list)

    @property
    def summary(self) -> dict[str, Any]:
        units = self.payload["units"]
        return {
            "level": f"{self.curriculum.language}/{self.curriculum.level}",
            "units": len(units),
            "words": sum(1 for unit in units for target in unit["targets"] if target["kind"] == "vocabulary"),
            "grammar_points": len(self.payload["grammar"]),
            "content_hash": self.payload["content_hash"],
        }


def parse_curriculum(text: str) -> CurriculumFile:
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise CurriculumFileError([f"TOML: {exc}"]) from exc
    try:
        return CurriculumFile.model_validate(data)
    except ValidationError as exc:
        raise CurriculumFileError([
            f"{'.'.join(str(part) for part in error['loc']) or 'file'}: {error['msg']}" for error in exc.errors()
        ]) from exc


class CurriculumLoader:
    def __init__(self, *, dictionary: DictionaryEntryStore, store: CurriculumStore):
        self.dictionary = dictionary
        self.store = store

    def plan(self, text: str, *, source_path: str,
             grammar_inventory: dict[str, str | None] | None = None) -> CurriculumPlan:
        """`grammar_inventory` maps the language's inventory item references to framework levels
        (None when the inventory lists the item without a level)."""
        curriculum = parse_curriculum(text)
        problems: list[str] = []
        warnings: list[str] = []
        self._check_grammar(curriculum, grammar_inventory, problems, warnings)
        units = []
        for position, unit in enumerate(curriculum.units, start=1):
            targets = []
            for word in unit.words:
                resolved = self._resolve(curriculum, unit.key, word, problems, warnings)
                if resolved:
                    targets.append({"position": len(targets) + 1, "kind": "vocabulary", **resolved})
            for key in unit.grammar:
                targets.append({"position": len(targets) + 1, "kind": "grammar", "grammar_key": key})
            units.append({"key": unit.key, "position": position, "title": unit.title, "topic": unit.topic,
                          "can_do": unit.can_do, "targets": targets})
        if problems:
            raise CurriculumFileError(problems)
        payload = {
            "language_code": curriculum.language,
            "framework": curriculum.framework,
            "level": curriculum.level,
            "title": curriculum.title,
            "version": curriculum.version,
            "content_hash": content_hash(curriculum),
            "source_path": source_path,
            "grammar": [point.model_dump() for point in curriculum.grammar],
            "units": units,
        }
        return CurriculumPlan(curriculum=curriculum, payload=payload, warnings=warnings)

    def is_unchanged(self, plan: CurriculumPlan) -> bool:
        current = self.store.content_hash(language_code=plan.curriculum.language,
                                          framework=plan.curriculum.framework, level=plan.curriculum.level)
        return current == plan.payload["content_hash"]

    def apply(self, plan: CurriculumPlan) -> dict[str, Any]:
        return self.store.load_level(plan.payload)

    def _check_grammar(self, curriculum: CurriculumFile, inventory: dict[str, str | None] | None,
                       problems: list[str], warnings: list[str]) -> None:
        listed = [point for point in curriculum.grammar if point.source != DEEPLINGO_GRAMMAR]
        if listed and inventory is None:
            warnings.append(f"grammar inventory not checked ({len(listed)} point(s)); pass --grammar-inventory")
            return
        for point in listed:
            if point.source_ref not in inventory:
                problems.append(f"grammar {point.key}: {point.source} item {point.source_ref} not found")
                continue
            level = inventory[point.source_ref]
            if level is None:
                warnings.append(f"grammar {point.key}: {point.source} item {point.source_ref} has no level")
            elif _rank(curriculum, level) > _rank(curriculum, curriculum.level):
                warnings.append(f"grammar {point.key}: {point.source} item {point.source_ref} is {level}")

    def _resolve(self, curriculum: CurriculumFile, unit_key: str, word, problems: list[str],
                 warnings: list[str]) -> dict[str, str] | None:
        where = f"{unit_key} '{word.headword}'"
        entry = self.dictionary.get_by_normalized(
            language_code=curriculum.language,
            normalized_headword=normalize_reference_text(word.headword, language_code=curriculum.language),
        )
        if entry is None or entry.id is None:
            problems.append(f"{where}: not in the dictionary")
            return None
        sense = next((item for item in entry.definitions
                      if isinstance(item, dict) and item.get("sense_id") == word.sense_id), None)
        if sense is None:
            problems.append(f"{where}: sense {word.sense_id} not found (dictionary changed?)")
            return None
        if sense.get("form_of"):
            problems.append(f"{where}: sense {word.sense_id} is an inflection, choose a lemma sense")
            return None
        if not gloss_matches(word.gloss, str(sense.get("text", ""))):
            problems.append(f"{where}: gloss does not match sense {word.sense_id}: {sense.get('text', '')!r}")
            return None
        level = _dictionary_level(curriculum, entry.provider_metadata)
        if level is not None and level > _rank(curriculum, curriculum.level):
            warnings.append(f"{where}: dictionary level is above {curriculum.level}")
        return {"dictionary_entry_id": str(entry.id), "sense_id": word.sense_id}


def content_hash(curriculum: CurriculumFile) -> str:
    canonical = json.dumps(curriculum.model_dump(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _rank(curriculum: CurriculumFile, level: str) -> int:
    return FRAMEWORK_LEVELS[(curriculum.language, curriculum.framework)].index(level)


def _dictionary_level(curriculum: CurriculumFile, metadata: dict) -> int | None:
    """Level recorded on the dictionary entry by the import (CEFR-J for English)."""
    value = metadata.get("cefr_j") if curriculum.framework == "CEFR" else metadata.get("hsk")
    levels = FRAMEWORK_LEVELS[(curriculum.language, curriculum.framework)]
    return levels.index(value) if value in levels else None
