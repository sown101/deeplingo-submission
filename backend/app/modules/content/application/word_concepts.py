"""Concepts for words a learner saves.

A saved word is always one dictionary sense, resolved on the server:

- from a lookup, the server re-grounds the learner's span in the trusted segment and accepts
  only a sense the dictionary offers for that unit. When this video already teaches the same
  word as a prepared occurrence, that trusted Concept is reused, so practice can use it;
- from a manual search, the learner picks one sense of a dictionary entry.

Nothing here writes learner state; the learner module stores the list.
"""
from __future__ import annotations

import logging
from typing import Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.modules.content.application.knowledge_resolution import (
    normalize_concept_text,
    normalize_display_text,
    normalize_reference_text,
    normalize_sense_key,
)
from app.modules.content.application.library import LearnerLibraryError
from app.modules.content.application.prompts import (
    SENSE_TRANSLATION_PROMPT_VERSION,
    build_sense_translation_prompt,
)
from app.modules.content.application.word_lookup import LANGUAGE_NAMES, WordLookupService, real_senses
from app.modules.content.domain.dictionary_sources import DICTIONARY_SOURCES
from app.modules.content.domain.knowledge import Concept, ConceptType, DictionaryEntry
from app.modules.content.domain.word_lookup import LookupSpanError, is_unspaced, snap_selection
from app.platform.llm.port import LLMProviderError

logger = logging.getLogger(__name__)

MAX_SEARCH_ENTRIES = 5
MAX_TRANSLATED_SENSES = 20
MAX_QUERY_CHARS = 80
DICTIONARY_SENSE_IDENTITY = "sense-key-v1"


class WordConceptError(LearnerLibraryError):
    pass


class ConceptStore(Protocol):
    def get_by_id(self, concept_id) -> Concept | None: ...
    def list_by_ids(self, concept_ids: list) -> list[Concept]: ...
    def find_by_identity(self, *, language_code: str, concept_type: str, normalized_text: str,
                         sense_key: str) -> Concept | None: ...
    def upsert_by_identity(self, data: dict) -> Concept: ...


class DictionaryStore(Protocol):
    def get_by_id(self, dictionary_entry_id) -> DictionaryEntry | None: ...
    def list_by_headwords(self, *, language_code: str, normalized_headwords: list[str]) -> list[DictionaryEntry]: ...


class ConceptLinkStore(Protocol):
    def upsert_link(self, *, concept_id: UUID, dictionary_entry_id: UUID, relation_type: str = "supports"): ...


class DictionarySenseView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sense_id: str
    text: str
    part_of_speech: str | None
    reading: str | None
    example: str | None
    # The dictionary's own text is English; this is the same sense in the learner's support
    # language (the model only renders an offered sense, it never adds one).
    meaning: str | None = None


class SenseTranslation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sense_id: str = Field(max_length=80)
    meaning: str = Field(min_length=1, max_length=160)


class SenseTranslationsOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    translations: list[SenseTranslation] = Field(max_length=MAX_TRANSLATED_SENSES)


class DictionarySearchEntryView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entry_id: UUID
    headword: str
    level: str | None
    senses: list[DictionarySenseView]
    source_name: str | None
    source_license: str | None
    source_url: str | None


class WordConceptService:
    def __init__(self, *, lookup: WordLookupService, learning_objects, concepts: ConceptStore,
                 dictionary: DictionaryStore, links: ConceptLinkStore):
        self.lookup = lookup
        self.learning_objects = learning_objects
        self.concepts = concepts
        self.dictionary = dictionary
        self.links = links

    def from_lookup(self, user, library_item_id: UUID, *, segment_id: UUID, start_codepoint: int,
                    end_codepoint: int, sense_id: str | None) -> Concept:
        video, segment, language = self.lookup.owned_segment(user, library_item_id, segment_id)
        try:
            start, end = snap_selection(segment.text, start_codepoint, end_codepoint, language)
        except LookupSpanError as exc:
            raise WordConceptError("Select a word in this sentence.", status_code=422, code=str(exc)) from exc
        window, entries = self.lookup.best_unit(segment.text, start, end, language)
        offered = [(sense, entry) for entry in entries for sense in real_senses(entry)]
        if not offered:
            raise WordConceptError("This word has no dictionary meaning to save yet.",
                                   status_code=422, code="no_dictionary_sense")
        if sense_id is None:
            sense, entry = offered[0]  # the sense the sheet showed when no model choice was made
        else:
            pair = next((pair for pair in offered if pair[0]["sense_id"] == sense_id), None)
            if pair is None:
                raise WordConceptError("That meaning is not offered for this word.",
                                       status_code=422, code="sense_not_offered")
            sense, entry = pair
        trusted = self._video_concept(video.id, segment.id, window.start, window.end, entry, language,
                                      sense_id=sense["sense_id"])
        if trusted is not None:
            return trusted
        unit_kind = "phrase" if not is_unspaced(language) and window.size > 1 else "word"
        return self._sense_concept(entry, sense, language, unit_kind)

    def from_dictionary(self, *, language_code: str, entry_id: UUID, sense_id: str) -> Concept:
        entry = self.dictionary.get_by_id(entry_id)
        if entry is None or entry.language_code != language_code:
            raise WordConceptError("Dictionary entry not found.", status_code=404, code="dictionary_entry_not_found")
        sense = next((item for item in real_senses(entry) if item["sense_id"] == sense_id), None)
        if sense is None:
            raise WordConceptError("That meaning is not in this entry.", status_code=422, code="sense_not_offered")
        kind = "phrase" if not is_unspaced(language_code) and " " in entry.headword.strip() else "word"
        return self._sense_concept(entry, sense, language_code, kind)

    def from_occurrence(self, user, library_item_id: UUID, learning_object_id: UUID) -> Concept:
        association = self.lookup.library.get_for_user(library_item_id=library_item_id, user_id=user.id)
        item = self.learning_objects.get_by_id(learning_object_id) if association else None
        concept = self.concepts.get_by_id(item.concept_id) if item and item.video_id == association.video_id else None
        if concept is None:
            # The same answer for another learner's video and for a missing occurrence.
            raise WordConceptError("Library item not found.", status_code=404, code="library_item_not_found")
        return concept

    def search(self, *, language_code: str, query: str, user=None) -> list[DictionarySearchEntryView]:
        text = " ".join(query.split())[:MAX_QUERY_CHARS]
        if not text:
            return []
        key = normalize_reference_text(text, language_code=language_code)
        found = self.dictionary.list_by_headwords(language_code=language_code, normalized_headwords=[key])
        # An inflected form ("went") also offers its base form ("go").
        bases = [word for entry in found for sense in entry.definitions if isinstance(sense, dict)
                 for word in (sense.get("form_of") or []) if isinstance(word, str)]
        if bases:
            keys = [normalize_reference_text(word, language_code=language_code) for word in dict.fromkeys(bases)]
            found += [entry for entry in self.dictionary.list_by_headwords(
                language_code=language_code, normalized_headwords=keys) if entry not in found]
        views = []
        for entry in found:
            senses = real_senses(entry)
            if not senses or entry.id is None:
                continue
            source = DICTIONARY_SOURCES.get(entry.provider or "")
            metadata = entry.provider_metadata or {}
            level = metadata.get("hsk") if is_unspaced(language_code) else metadata.get("cefr_j")
            views.append(DictionarySearchEntryView(
                entry_id=entry.id, headword=entry.headword,
                level=level if isinstance(level, str) else None,
                senses=[DictionarySenseView(
                    sense_id=sense["sense_id"], text=sense["text"], part_of_speech=sense.get("pos"),
                    reading=sense.get("reading"),
                    example=sense.get("example") if isinstance(sense.get("example"), str) else None,
                ) for sense in senses],
                source_name=source.name if source else None,
                source_license=source.license_name if source else None,
                source_url=source.entry_url(entry.headword) if source else None,
            ))
            if len(views) >= MAX_SEARCH_ENTRIES:
                break
        return self._with_meanings(views, language_code, user)

    def _with_meanings(self, views: list[DictionarySearchEntryView], language_code: str,
                       user) -> list[DictionarySearchEntryView]:
        """Fills `meaning` in the support language; on any failure the English gloss still shows."""
        if user is None or not views:
            return views
        profile = self.lookup.preferences.get_by_language_for_user(user_id=user.id, language_code=language_code)
        support = ((profile.support_language_code or "") if profile else "").strip().casefold()
        if not support or support == "en":
            return views
        offered = [(sense.sense_id, sense.text) for entry in views for sense in entry.senses][:MAX_TRANSLATED_SENSES]
        if not offered:
            return views
        prompt = build_sense_translation_prompt(
            headword=views[0].headword, source_language=LANGUAGE_NAMES.get(language_code, language_code),
            support_language=LANGUAGE_NAMES.get(support, support), senses=offered,
        )
        try:
            output = self.lookup.provider.generate_structured(prompt, SenseTranslationsOutput)
        except (LLMProviderError, ValidationError) as exc:
            logger.warning("sense translation unavailable prompt=%s error=%s",
                           SENSE_TRANSLATION_PROMPT_VERSION, type(exc).__name__)
            return views
        allowed = {sense_id for sense_id, _ in offered}
        meanings: dict[str, str] = {}
        for item in output.translations:
            text = " ".join(item.meaning.split())
            if item.sense_id in allowed and item.sense_id not in meanings and text:
                meanings[item.sense_id] = text
        # M1 S7d: keep these senses in the support language for Quick review (first writer wins).
        self.lookup.save_translations([{
            "dictionary_entry_id": entry.entry_id, "sense_id": sense.sense_id, "support_language_code": support,
            "language_code": language_code, "headword": entry.headword, "part_of_speech": sense.part_of_speech,
            "meaning": meanings[sense.sense_id], "origin": "search", "prompt_version": SENSE_TRANSLATION_PROMPT_VERSION,
        } for entry in views for sense in entry.senses if sense.sense_id in meanings])
        return [entry.model_copy(update={"senses": [
            sense.model_copy(update={"meaning": meanings.get(sense.sense_id)}) for sense in entry.senses]})
            for entry in views]

    def _video_concept(self, video_id, segment_id, start: int, end: int, entry: DictionaryEntry,
                       language: str, *, sense_id: str) -> Concept | None:
        """The video's own prepared Concept for this word, when it is unambiguous and is the very
        dictionary sense chosen (M1 S7d: the same headword in another sense is another Concept)."""
        objects = self.learning_objects.list_for_video(video_id)
        overlapping = [item for item in objects if item.transcript_segment_id == segment_id
                       and item.start_codepoint is not None and item.end_codepoint is not None
                       and item.start_codepoint < end and start < item.end_codepoint]
        concepts = {item.id: item for item in self.concepts.list_by_ids(
            list({row.concept_id for row in objects}))} if objects else {}
        normalized = normalize_concept_text(entry.headword, language_code=language)

        def same_sense(concept: Concept) -> bool:
            metadata = concept.metadata or {}
            if metadata.get("dictionary_sense_id"):
                return (metadata.get("dictionary_sense_id") == sense_id
                        and str(metadata.get("dictionary_entry_id")) == str(entry.id))
            # A video Concept records its dictionary sense on its prepared occurrences.
            return any(_occurrence_sense(row) == (str(entry.id), sense_id)
                       for row in objects if row.concept_id == concept.id)

        for item in overlapping:
            concept = concepts.get(item.concept_id)
            if concept is not None and concept.normalized_text == normalized and same_sense(concept):
                return concept
        same_word = {concept.id: concept for concept in concepts.values()
                     if concept.normalized_text == normalized and concept.type != ConceptType.GRAMMAR
                     and same_sense(concept)}
        return next(iter(same_word.values())) if len(same_word) == 1 else None

    def _sense_concept(self, entry: DictionaryEntry, sense: dict, language: str, unit_kind: str) -> Concept:
        concept_type = ConceptType.EXPRESSION if unit_kind == "phrase" else ConceptType.VOCABULARY
        normalized = normalize_concept_text(entry.headword, language_code=language)
        sense_key = normalize_sense_key(sense["text"])
        concept = self.concepts.find_by_identity(
            language_code=language, concept_type=concept_type.value,
            normalized_text=normalized, sense_key=sense_key,
        )
        if concept is None:
            concept = self.concepts.upsert_by_identity({
                "language_code": language,
                "type": concept_type.value,
                "canonical_text": normalize_display_text(entry.headword),
                "normalized_text": normalized,
                "sense_key": sense_key,
                "metadata": {
                    "source": "dictionary_sense",
                    "sense_gloss": normalize_display_text(sense["text"]),
                    "dictionary_entry_id": str(entry.id),
                    "dictionary_sense_id": sense["sense_id"],
                    "sense_identity_version": DICTIONARY_SENSE_IDENTITY,
                },
            })
        if concept.id is not None and entry.id is not None:
            self.links.upsert_link(concept_id=concept.id, dictionary_entry_id=entry.id)
        return concept


def _occurrence_sense(row) -> tuple[str, str] | None:
    """(dictionary entry, sense) an occurrence's meaning was translated from, in any language."""
    enrichments = (row.raw_ai_diagnostics or {}).get("enrichments") if getattr(row, "raw_ai_diagnostics", None) else None
    for enrichment in (enrichments or {}).values():
        sense = enrichment.get("dictionary_sense") if isinstance(enrichment, dict) else None
        if (isinstance(sense, dict) and enrichment.get("meaning_provenance") == "translated_from_sense"
                and sense.get("sense_id") and sense.get("dictionary_entry_id")):
            return str(sense["dictionary_entry_id"]), str(sense["sense_id"])
    return None
