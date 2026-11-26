"""Reference data for the notebook: ready-made word sets by level, a word's dictionary details and its picture."""
from __future__ import annotations

import logging
from typing import Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.modules.content.domain.pinyin import readable_pinyin

logger = logging.getLogger(__name__)

PAGE_SIZE = 50
MAX_IMAGES_PER_REQUEST = 24
SETS = (
    *[(f"hsk{level}", "zh", "hsk", f"HSK{level}", f"HSK {level}") for level in range(1, 7)],
    ("hsk7", "zh", "hsk", "HSK7", "HSK 7-9"),
    *[(f"cefr-{level.lower()}", "en", "cefr_j", level, level) for level in ("A1", "A2", "B1", "B2", "C1", "C2")],
)
_BY_KEY = {key: (language, field, value, name) for key, language, field, value, name in SETS}


class _View(BaseModel):
    model_config = ConfigDict(extra="forbid")


class WordSetView(_View):
    key: str
    language_code: str
    name: str
    word_count: int


class WordSetWordView(_View):
    entry_id: UUID
    sense_id: str
    text: str
    traditional: str | None
    reading: str | None
    meaning: str


class WordSetDetailView(WordSetView):
    offset: int
    words: list[WordSetWordView]


class SenseView(_View):
    text: str
    reading: str | None
    part_of_speech: str | None


class CharacterView(_View):
    character: str
    reading: str | None
    meaning: str | None


class CompoundView(_View):
    text: str
    reading: str | None
    meaning: str | None


class WordDetailsView(_View):
    concept_id: UUID
    text: str
    traditional: str | None
    reading: str | None
    level: str | None
    senses: list[SenseView]
    characters: list[CharacterView]
    compounds: list[CompoundView]


class ConceptImageView(_View):
    concept_id: UUID
    image_url: str
    thumbnail_url: str | None
    title: str | None
    creator: str | None
    license: str | None
    source_url: str | None


class WordReferenceError(Exception):
    def __init__(self, message: str, *, status_code: int, code: str):
        super().__init__(message)
        self.status_code, self.code = status_code, code


class DictionaryRows(Protocol):
    def count_by_level(self, language_code: str, field: str, value: str) -> int: ...

    def page_by_level(self, language_code: str, field: str, value: str, *, offset: int, limit: int) -> list[dict]: ...

    def rows_for_texts(self, language_code: str, texts: list[str]) -> list[dict]: ...

    def rows_containing(self, language_code: str, text: str, *, limit: int) -> list[dict]: ...


class ConceptReader(Protocol):
    def get_by_id(self, concept_id): ...

    def list_by_ids(self, concept_ids: list): ...


class ImageStore(Protocol):
    def list_for(self, concept_ids: list[UUID]) -> list[dict]: ...

    def save(self, row: dict) -> None: ...


class ImageSearch(Protocol):
    def search(self, term: str, *, index: int) -> dict | None: ...


def _senses(row: dict) -> list[dict]:
    return [sense for sense in row.get("definitions") or [] if isinstance(sense, dict) and sense.get("text")]


def _reading(row: dict) -> str | None:
    if row.get("language_code") == "zh":
        return readable_pinyin(row.get("pronunciation"))
    return row.get("pronunciation") or None


def _traditional(row: dict) -> str | None:
    return next((sense["traditional"] for sense in _senses(row) if sense.get("traditional")), None)


def _level(row: dict) -> str | None:
    metadata = row.get("provider_metadata") or {}
    return metadata.get("hsk") or metadata.get("cefr_j")


class WordReferenceService:
    _counts: dict[str, int] = {}  # Set sizes change only when the dictionary is re-imported.

    def __init__(self, *, dictionary: DictionaryRows, concepts: ConceptReader, images: ImageStore, image_search: ImageSearch | None):
        self.dictionary, self.concepts, self.images, self.image_search = dictionary, concepts, images, image_search

    # --- Sets -------------------------------------------------------------------------------------

    def sets(self) -> list[WordSetView]:
        return [WordSetView(key=key, language_code=language, name=name, word_count=self._count(key))
                for key, language, _field, _value, name in SETS]

    def set_detail(self, key: str, *, offset: int) -> WordSetDetailView:
        language, field, value, name = self._known(key)
        words = []
        for row in self.dictionary.page_by_level(language, field, value, offset=offset, limit=PAGE_SIZE):
            senses = _senses(row)
            if senses and senses[0].get("sense_id"):
                words.append(WordSetWordView(
                    entry_id=row["id"], sense_id=senses[0]["sense_id"], text=row["headword"],
                    traditional=_traditional(row), reading=_reading(row), meaning=senses[0]["text"]))
        return WordSetDetailView(key=key, language_code=language, name=name, offset=offset, words=words,
                                 word_count=self._count(key))

    def _count(self, key: str) -> int:
        if key not in self._counts:
            language, field, value, _name = _BY_KEY[key]
            self._counts[key] = self.dictionary.count_by_level(language, field, value)
        return self._counts[key]

    @staticmethod
    def _known(key: str) -> tuple[str, str, str, str]:
        if key not in _BY_KEY:
            raise WordReferenceError("Word set not found.", status_code=404, code="word_set_not_found")
        return _BY_KEY[key]

    # --- One word ---------------------------------------------------------------------------------

    def details(self, concept_id: UUID) -> WordDetailsView:
        concept = self.concepts.get_by_id(concept_id)
        if concept is None:
            raise WordReferenceError("Word not found.", status_code=404, code="word_not_found")
        language, text = concept.language_code, concept.canonical_text
        rows = self.dictionary.rows_for_texts(language, [text])
        main = rows[0] if rows else {"language_code": language}
        senses = [SenseView(text=sense["text"], reading=readable_pinyin(sense.get("reading")) if language == "zh" else sense.get("reading"),
                            part_of_speech=row.get("part_of_speech") or None)
                  for row in rows for sense in _senses(row)]
        characters: list[CharacterView] = []
        compounds: list[CompoundView] = []
        if language == "zh":
            unique = list(dict.fromkeys(text))
            by_text = {row["headword"]: row for row in self.dictionary.rows_for_texts(language, unique)}
            characters = [CharacterView(character=char, reading=_reading(by_text[char]) if char in by_text else None,
                                        meaning=_first_meaning(by_text.get(char))) for char in unique]
            compounds = [CompoundView(text=row["headword"], reading=_reading(row), meaning=_first_meaning(row))
                         for row in self.dictionary.rows_containing(language, text, limit=12)]
        return WordDetailsView(concept_id=concept_id, text=text, traditional=_traditional(main), reading=_reading(main),
                               level=_level(main), senses=senses, characters=characters, compounds=compounds)

    # --- Pictures ---------------------------------------------------------------------------------

    def images_for(self, concept_ids: list[UUID], *, refresh: UUID | None = None) -> list[ConceptImageView]:
        ids = list(dict.fromkeys(concept_ids))[:MAX_IMAGES_PER_REQUEST]
        stored = {UUID(str(row["concept_id"])): row for row in self.images.list_for(ids)}
        missing = [concept_id for concept_id in ids if concept_id not in stored or concept_id == refresh]
        if missing and self.image_search is not None:
            concepts = {concept.id: concept for concept in self.concepts.list_by_ids(missing)}
            for concept_id in missing:
                concept = concepts.get(concept_id)
                if concept is None:
                    continue
                previous = stored.get(concept_id)
                row = self._fetch(concept, previous)
                if row is not None:
                    stored[concept_id] = row
        return [ConceptImageView(**{name: stored[concept_id].get(name) for name in
                                    ("image_url", "thumbnail_url", "title", "creator", "license", "source_url")},
                                 concept_id=concept_id) for concept_id in ids if concept_id in stored]

    def _fetch(self, concept, previous: dict | None) -> dict | None:
        term = previous["search_term"] if previous else self._term(concept)
        index = previous["result_index"] + 1 if previous else 0
        try:
            found = self.image_search.search(term, index=index)
            if found is None and index:  # Past the last result: start again.
                index, found = 0, self.image_search.search(term, index=0)
            if found is None:
                return previous
            row = {**found, "concept_id": str(concept.id), "search_term": term, "result_index": index}
            self.images.save(row)
            return row
        except Exception as exc:
            logger.warning("word image unavailable error=%s", type(exc).__name__)
            return previous

    def _term(self, concept) -> str:
        """Picture search works best in English; a Chinese word is searched by its first dictionary meaning."""
        if concept.language_code != "zh":
            return concept.canonical_text
        rows = self.dictionary.rows_for_texts("zh", [concept.canonical_text])
        meaning = _first_meaning(rows[0]) if rows else None
        return _clean_term(meaning) or concept.canonical_text


def _first_meaning(row: dict | None) -> str | None:
    if not row:
        return None
    senses = _senses(row)
    return senses[0]["text"] if senses else None


def _clean_term(meaning: str | None) -> str | None:
    if not meaning:
        return None
    cleaned = meaning.split(";")[0].split("(")[0].strip()
    return cleaned.removeprefix("to ").strip() or None
