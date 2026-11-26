"""What the exercise engine knows about a saved word, read from content data on the server.

The meaning is the word's dictionary sense in the learner's support language (the dictionary's own English
gloss, else its stored translation); a word with no meaning in that language gets none rather than another
language's. The sentence is the word's occurrence in one of the learner's own Library videos first, else a stored
example sentence (human-written before AI-written; dictionary quotations last). No model is called.
"""
from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from app.modules.content.contracts import ExampleSourceKind
from app.modules.practice.domain.meaning_choices import plain_dictionary_example, usable_distractor_meaning
from app.modules.practice.domain.exercises import SentenceSource, WordCard

logger = logging.getLogger(__name__)

DICTIONARY_LANGUAGE = "en"
POOL_SIZE = 200
DEFAULT_SUPPORT = "vi"
_SOURCE_ORDER = {ExampleSourceKind.CORPUS: 0, ExampleSourceKind.GENERATED: 1, ExampleSourceKind.DICTIONARY: 2}


def _is_dictionary_language(code: str) -> bool:
    return code.strip().casefold().split("-")[0] == DICTIONARY_LANGUAGE


def _gloss(concept) -> str | None:
    gloss = (concept.metadata or {}).get("sense_gloss")
    return " ".join(gloss.split()) or None if isinstance(gloss, str) else None


def _sense(concept) -> tuple[UUID, str] | None:
    metadata = concept.metadata or {}
    entry, sense = metadata.get("dictionary_entry_id"), metadata.get("dictionary_sense_id")
    try:
        return (UUID(str(entry)), str(sense)) if entry and sense else None
    except ValueError:
        return None


class WordCards:
    def __init__(self, *, profiles, concepts, meanings, examples, occurrences=None, readings=None):
        self.profiles, self.concepts, self.meanings = profiles, concepts, meanings
        self.examples, self.occurrences, self.readings = examples, occurrences, readings

    def support_language(self, user_id: UUID) -> str:
        profile = self.profiles.get_profile_for_user(user_id)
        return (getattr(profile, "support_language_code", None) or DEFAULT_SUPPORT).strip()

    def cards(self, user_id: UUID, language_code: str, concept_ids: list[UUID]) -> dict[UUID, WordCard]:
        if not concept_ids:
            return {}
        support = self.support_language(user_id)
        concepts = [concept for concept in self.concepts.list_by_ids(list(dict.fromkeys(concept_ids)))
                    if concept.language_code == language_code and concept.id is not None]
        if not concepts:
            return {}
        ids = [concept.id for concept in concepts]
        translated = self._translations(concepts, support)
        occurrences = self._occurrences(user_id, ids, support)
        examples = self._examples([concept_id for concept_id in ids if concept_id not in occurrences])
        readings = self._readings(language_code, [concept.canonical_text for concept in concepts])
        cards: dict[UUID, WordCard] = {}
        for concept in concepts:
            meaning, pos = (_gloss(concept), None) if _is_dictionary_language(support) else translated.get(
                concept.id, (None, None))
            occurrence = occurrences.get(concept.id)
            sentence = None
            if occurrence is not None:
                sentence = SentenceSource(text=occurrence.sentence, target_form=occurrence.target_form, origin="video",
                                          library_item_id=occurrence.library_item_id, start_ms=occurrence.start_ms)
                if not _is_dictionary_language(support):
                    meaning = meaning or occurrence.meaning
                pos = pos or occurrence.part_of_speech
            else:
                sentence = self._example(concept, examples.get(concept.id, ()))
            reading, traditional = readings.get(concept.canonical_text, (None, None))
            cards[concept.id] = WordCard(
                concept_id=concept.id, language_code=concept.language_code, text=concept.canonical_text,
                reading=reading, meaning=meaning, part_of_speech=pos, sentence=sentence,
                other_forms=tuple(form for form in (traditional,) if form))
        return cards

    def meaning_pool(self, user_id: UUID, language_code: str) -> list[tuple]:
        """Other words' meanings, in the same language as the answers."""
        support = self.support_language(user_id)
        try:
            if _is_dictionary_language(support):
                return [(text, gloss) for text, gloss in self.concepts.sample_sense_glosses(
                    language_code=language_code, limit=POOL_SIZE)]
            return [(row["headword"], row["meaning"], row.get("part_of_speech")) for row in self.meanings.sample(
                language_code=language_code, support_language_code=support, limit=POOL_SIZE)
                if usable_distractor_meaning(row["meaning"], support)]
        except Exception as exc:  # a missing pool only makes choice questions fall back to flashcards
            logger.warning("meaning pool unavailable language=%s error=%s", language_code, type(exc).__name__)
            return []

    def word_pool(self, language_code: str) -> list[str]:
        """Other words of the same language, for "hear it and choose it"."""
        try:
            return [text for text, _ in self.concepts.sample_sense_glosses(language_code=language_code,
                                                                            limit=POOL_SIZE)]
        except Exception as exc:
            logger.warning("word pool unavailable language=%s error=%s", language_code, type(exc).__name__)
            return []

    def _translations(self, concepts, support: str) -> dict[UUID, tuple[str | None, str | None]]:
        if _is_dictionary_language(support) or self.meanings is None:
            return {}
        senses = {concept.id: sense for concept in concepts if (sense := _sense(concept)) is not None}
        if not senses:
            return {}
        found = self.meanings.for_senses(list(dict.fromkeys(senses.values())), support_language_code=support)
        return {concept_id: (found[sense]["meaning"], found[sense].get("part_of_speech"))
                for concept_id, sense in senses.items() if sense in found}

    def _occurrences(self, user_id: UUID, ids: list[UUID], support: str) -> dict[UUID, Any]:
        if self.occurrences is None:
            return {}
        try:
            return self.occurrences.sentences_for(user_id, ids, support_language_code=support)
        except Exception as exc:  # the stored examples are the fallback
            logger.warning("video sentences unavailable error=%s", type(exc).__name__)
            return {}

    def _readings(self, language_code: str, texts: list[str]) -> dict[str, tuple[str | None, str | None]]:
        if self.readings is None:
            return {}
        try:
            return self.readings.readings_for(language_code, texts)
        except Exception as exc:
            logger.warning("readings unavailable error=%s", type(exc).__name__)
            return {}

    def _examples(self, concept_ids: list[UUID]) -> dict:
        if not concept_ids:
            return {}
        try:
            return self.examples.list_for_concepts(concept_ids)
        except Exception as exc:  # the cards are still usable without a sentence
            logger.warning("examples unavailable error=%s", type(exc).__name__)
            return {}

    @staticmethod
    def _example(concept, examples) -> SentenceSource | None:
        usable = sorted((item for item in examples
                         if item.source_kind in _SOURCE_ORDER and item.language_code == concept.language_code
                         and (item.source_kind != ExampleSourceKind.DICTIONARY or plain_dictionary_example(item.text))),
                        key=lambda item: _SOURCE_ORDER[item.source_kind])
        if not usable:
            return None
        return SentenceSource(text=usable[0].text, target_form=usable[0].target_form or concept.canonical_text,
                              origin="example")
