"""Example sentences for My words.

Order of sources for a saved word: the dictionary's own example for the chosen sense, then a
generated sentence (written in the learner's target language, at beginner level). Generated
sentences pass deterministic checks and a separate model sense check, and they are always
labelled as written by AI. Nothing here changes learner state; examples are shared content.
"""
from __future__ import annotations

import logging
from typing import Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.modules.content.application.library import LearnerLibraryError
from app.modules.content.application.prompts import (
    EXAMPLE_SENSE_CHECK_PROMPT_VERSION,
    EXAMPLE_SENTENCE_PROMPT_VERSION,
    build_example_sense_check_prompt,
    build_example_sentence_prompt,
)
from app.modules.content.application.word_lookup import LANGUAGE_NAMES, real_senses
from app.modules.content.domain.dictionary_sources import DICTIONARY_SOURCES
from app.modules.content.domain.example_sentences import (
    TATOEBA_LICENSE,
    TATOEBA_LICENSE_URL,
    TATOEBA_NAME,
    TATOEBA_SENTENCE_URL,
    ExampleSentence,
    ExampleSourceKind,
    clean_text,
    find_form_span,
    rejection_reason,
    text_key,
)
from app.modules.content.domain.knowledge import Concept, DictionaryEntry
from app.platform.llm.port import LLMProvider, LLMProviderError

logger = logging.getLogger(__name__)

GENERATED_COUNT = 3
CORPUS_CANDIDATES = 9
MAX_STORED_GENERATED = 2
# A sense check below this confidence is not a pass (fail closed).
SENSE_CHECK_MIN_CONFIDENCE = 0.8
DEFAULT_SUPPORT_LANGUAGE = "vi"


class ExampleSentenceError(LearnerLibraryError):
    pass


class GeneratedSentence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=240)
    translation: str = Field(min_length=1, max_length=300)


class GeneratedSentencesOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sentences: list[GeneratedSentence] = Field(min_length=1, max_length=GENERATED_COUNT)


class SenseVerdict(BaseModel):
    model_config = ConfigDict(extra="forbid")

    index: int = Field(ge=0, le=GENERATED_COUNT - 1)
    uses_sense: bool
    natural: bool
    names_real_person: bool
    confidence: float = Field(ge=0.0, le=1.0)


class SenseCheckOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verdicts: list[SenseVerdict] = Field(min_length=1, max_length=GENERATED_COUNT)


class ExampleSentenceView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    text: str
    start_codepoint: int | None
    end_codepoint: int | None
    translation: str | None
    translation_language_code: str | None
    source_kind: ExampleSourceKind
    ai_generated: bool
    source_name: str | None
    license_name: str | None
    license_url: str | None
    source_url: str | None
    author: str | None


class ExampleSentencesView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    concept_id: UUID
    examples: list[ExampleSentenceView]


class SavedWords(Protocol):
    def concept_ids_for(self, user_id: UUID, concept_ids: list[UUID]) -> set[UUID]: ...


class ExampleStore(Protocol):
    def list_for_concept(self, concept_id: UUID) -> list[ExampleSentence]: ...
    def add(self, sentence: ExampleSentence) -> ExampleSentence: ...


class CorpusSearch(Protocol):
    def find_candidates(self, *, language_code: str, form: str, translation_language: str,
                        limit: int = 20) -> list[dict]: ...


class ExampleSentenceService:
    def __init__(self, *, saved: SavedWords, concepts, dictionary, examples: ExampleStore, preferences,
                 provider: LLMProvider, corpus: CorpusSearch | None = None):
        self.corpus = corpus
        self.saved = saved
        self.concepts = concepts
        self.dictionary = dictionary
        self.examples = examples
        self.preferences = preferences
        self.provider = provider

    def list(self, user, concept_id: UUID, *, read_only: bool = False) -> ExampleSentencesView:
        """Stored examples; read_only also prevents seeding the dictionary example."""
        concept = self._saved_concept(user, concept_id)
        stored = self.examples.list_for_concept(concept_id)
        if not read_only and not any(item.source_kind == ExampleSourceKind.DICTIONARY for item in stored):
            added = self._dictionary_example(concept)
            if added is not None:
                stored = self.examples.list_for_concept(concept_id)
        return self._view(concept_id, stored)

    def generate(self, user, concept_id: UUID) -> ExampleSentencesView:
        """Writes AI examples when the word has none yet. Fails closed; learner state is untouched."""
        concept = self._saved_concept(user, concept_id)
        stored = self.examples.list_for_concept(concept_id)
        if not stored:
            self._dictionary_example(concept)
            stored = self.examples.list_for_concept(concept_id)
        if stored:
            return self._view(concept_id, stored)
        self._write(user, concept)
        return self._view(concept_id, self.examples.list_for_concept(concept_id))

    # -- internals ---------------------------------------------------------------------------

    def _write(self, user, concept: Concept) -> None:
        gloss = (concept.metadata or {}).get("sense_gloss")
        if not isinstance(gloss, str) or not gloss.strip():
            raise ExampleSentenceError("This word has no dictionary meaning to write an example for.",
                                       status_code=422, code="no_dictionary_sense")
        profile = self.preferences.get_by_language_for_user(user_id=user.id, language_code=concept.language_code)
        support = (profile.support_language_code if profile else None) or DEFAULT_SUPPORT_LANGUAGE
        accepted = self._corpus(concept, gloss, support) or self._generate(concept, gloss, support)
        if not accepted:
            raise ExampleSentenceError("An example could not be written right now.",
                                       status_code=503, code="example_unavailable")
        for sentence in accepted[:MAX_STORED_GENERATED]:
            self.examples.add(sentence)

    def _saved_concept(self, user, concept_id: UUID) -> Concept:
        concept = self.concepts.get_by_id(concept_id) if concept_id in self.saved.concept_ids_for(
            user.id, [concept_id]) else None
        if concept is None:
            # The same answer for another learner's word and for a missing one.
            raise ExampleSentenceError("Word not found.", status_code=404, code="word_not_found")
        return concept

    def _dictionary_example(self, concept: Concept) -> ExampleSentence | None:
        metadata = concept.metadata or {}
        entry_id, sense_id = metadata.get("dictionary_entry_id"), metadata.get("dictionary_sense_id")
        if not entry_id or not sense_id:
            return None
        try:
            entry: DictionaryEntry | None = self.dictionary.get_by_id(UUID(str(entry_id)))
        except ValueError:
            return None
        sense = next((item for item in real_senses(entry) if item["sense_id"] == sense_id), None)
        example = sense.get("example") if sense else None
        if entry is None or not isinstance(example, str) or not clean_text(example):
            return None
        text = clean_text(example)
        if len(text) > 240:
            return None
        span = find_form_span(text, concept.canonical_text, concept.language_code) or \
            find_form_span(text, entry.headword, concept.language_code)
        source = DICTIONARY_SOURCES.get(entry.provider or "")
        if source is None:
            return None  # a source that cannot be credited is never shown
        return self.examples.add(ExampleSentence(
            concept_id=concept.id, language_code=concept.language_code, text=text, text_key=text_key(text),
            target_form=concept.canonical_text,
            start_codepoint=span[0] if span else None, end_codepoint=span[1] if span else None,
            source_kind=ExampleSourceKind.DICTIONARY, source_ref=source.entry_url(entry.headword),
            license=source.license_name, validation={"provider": source.provider},
        ))

    def _corpus(self, concept: Concept, gloss: str, support: str) -> list[ExampleSentence]:
        """Real sentences from the licensed corpus that use this word in this sense (source 3)."""
        if self.corpus is None:
            return []
        language, form = concept.language_code, concept.canonical_text
        try:
            rows = self.corpus.find_candidates(language_code=language, form=form, translation_language=support,
                                               limit=CORPUS_CANDIDATES * 2)
        except Exception as exc:  # a search failure falls through to the next source
            logger.warning("corpus search unavailable error=%s", type(exc).__name__)
            return []
        candidates = []
        for row in rows:
            text = clean_text(str(row.get("text") or ""))
            span = find_form_span(text, form, language)
            if span is None or not text or len(text) > 240 or row.get("source") != "tatoeba":
                continue
            candidates.append((text, span, row))
            if len(candidates) == CORPUS_CANDIDATES:
                break
        accepted: list[ExampleSentence] = []
        for start in range(0, len(candidates), GENERATED_COUNT):
            batch = candidates[start:start + GENERATED_COUNT]
            prompt = build_example_sense_check_prompt(
                source_language=LANGUAGE_NAMES.get(language, language), target_form=form, sense_gloss=gloss,
                sentences=[text for text, _, _ in batch],
            )
            try:
                verdicts = self.provider.generate_structured(prompt, SenseCheckOutput, temperature=0.0)
            except (LLMProviderError, ValidationError) as exc:
                logger.warning("corpus sense check unavailable prompt=%s error=%s",
                               EXAMPLE_SENSE_CHECK_PROMPT_VERSION, type(exc).__name__)
                return accepted
            passed = {item.index: item for item in verdicts.verdicts}
            for index, (text, span, row) in enumerate(batch):
                verdict = passed.get(index)
                # Human-written text: the real-person flag is for AI sentences, so names such as Tom are fine.
                if verdict is None or not (verdict.uses_sense and verdict.natural
                                           and verdict.confidence >= SENSE_CHECK_MIN_CONFIDENCE):
                    continue
                translation = row.get("translation")
                has_translation = isinstance(translation, str) and bool(translation.strip())
                accepted.append(ExampleSentence(
                    concept_id=concept.id, language_code=language, text=text, text_key=text_key(text),
                    target_form=form, start_codepoint=span[0], end_codepoint=span[1],
                    translation=clean_text(translation) if has_translation else None,
                    translation_language_code=support if has_translation else None,
                    source_kind=ExampleSourceKind.CORPUS,
                    source_ref=TATOEBA_SENTENCE_URL.format(row["source_id"]), license=TATOEBA_LICENSE,
                    prompt_version=EXAMPLE_SENSE_CHECK_PROMPT_VERSION, model_name=self.provider.model_name,
                    validation={"provider": "tatoeba", "tatoeba_id": row["source_id"], "author": row.get("author"),
                                "checks": ["deterministic", "sense_check"], "confidence": verdict.confidence},
                ))
                if len(accepted) >= MAX_STORED_GENERATED:
                    return accepted
        return accepted

    def _generate(self, concept: Concept, gloss: str, support: str) -> list[ExampleSentence]:
        language = concept.language_code
        form = concept.canonical_text
        prompt = build_example_sentence_prompt(
            source_language=LANGUAGE_NAMES.get(language, language),
            support_language=LANGUAGE_NAMES.get(support, support),
            target_form=form, part_of_speech=None, sense_gloss=gloss, count=GENERATED_COUNT,
        )
        try:
            written = self.provider.generate_structured(prompt, GeneratedSentencesOutput, temperature=0.7)
        except (LLMProviderError, ValidationError) as exc:
            logger.warning("example generation unavailable prompt=%s error=%s",
                           EXAMPLE_SENTENCE_PROMPT_VERSION, type(exc).__name__)
            return []
        candidates: list[tuple[str, str, tuple[int, int]]] = []
        seen: set[str] = set()
        for item in written.sentences:
            text = clean_text(item.text)
            reason = rejection_reason(text, form, language, gloss=gloss)
            span = find_form_span(text, form, language)
            if reason is not None or span is None or text_key(text) in seen:
                logger.info("example rejected prompt=%s reason=%s", EXAMPLE_SENTENCE_PROMPT_VERSION,
                            reason or "duplicate")
                continue
            seen.add(text_key(text))
            candidates.append((text, clean_text(item.translation), span))
        if not candidates:
            return []
        check_prompt = build_example_sense_check_prompt(
            source_language=LANGUAGE_NAMES.get(language, language), target_form=form, sense_gloss=gloss,
            sentences=[text for text, _, _ in candidates],
        )
        try:
            verdicts = self.provider.generate_structured(check_prompt, SenseCheckOutput, temperature=0.0)
        except (LLMProviderError, ValidationError) as exc:
            logger.warning("example sense check unavailable prompt=%s error=%s",
                           EXAMPLE_SENSE_CHECK_PROMPT_VERSION, type(exc).__name__)
            return []
        passed = {item.index: item for item in verdicts.verdicts}
        accepted = []
        for index, (text, translation, span) in enumerate(candidates):
            verdict = passed.get(index)
            if verdict is None or not (verdict.uses_sense and verdict.natural and not verdict.names_real_person
                                       and verdict.confidence >= SENSE_CHECK_MIN_CONFIDENCE):
                continue
            accepted.append(ExampleSentence(
                concept_id=concept.id, language_code=language, text=text, text_key=text_key(text),
                target_form=form, start_codepoint=span[0], end_codepoint=span[1],
                translation=translation, translation_language_code=support,
                source_kind=ExampleSourceKind.GENERATED,
                prompt_version=f"{EXAMPLE_SENTENCE_PROMPT_VERSION}+{EXAMPLE_SENSE_CHECK_PROMPT_VERSION}",
                model_name=self.provider.model_name,
                validation={"checks": ["deterministic", "sense_check"], "confidence": verdict.confidence},
            ))
        return accepted

    def _view(self, concept_id: UUID, stored: list[ExampleSentence]) -> ExampleSentencesView:
        # Human-written examples first (dictionary, then corpus), AI-written ones last.
        order = {ExampleSourceKind.DICTIONARY: 0, ExampleSourceKind.CORPUS: 1}
        ordered = sorted(stored, key=lambda item: order.get(item.source_kind, 2))
        return ExampleSentencesView(concept_id=concept_id, examples=[self._example_view(item) for item in ordered
                                                                      if item.id is not None])

    def _example_view(self, item: ExampleSentence) -> ExampleSentenceView:
        credit = None
        if item.source_kind == ExampleSourceKind.CORPUS:
            author = item.validation.get("author")
            return ExampleSentenceView(
                id=item.id, text=item.text, start_codepoint=item.start_codepoint, end_codepoint=item.end_codepoint,
                translation=item.translation, translation_language_code=item.translation_language_code,
                source_kind=item.source_kind, ai_generated=False, source_name=TATOEBA_NAME,
                license_name=TATOEBA_LICENSE, license_url=TATOEBA_LICENSE_URL, source_url=item.source_ref,
                author=author if isinstance(author, str) else None,
            )
        if item.source_kind == ExampleSourceKind.DICTIONARY:
            credit = DICTIONARY_SOURCES.get(str(item.validation.get("provider")))
        return ExampleSentenceView(
            id=item.id, text=item.text, start_codepoint=item.start_codepoint, end_codepoint=item.end_codepoint,
            translation=item.translation, translation_language_code=item.translation_language_code,
            source_kind=item.source_kind, ai_generated=item.source_kind == ExampleSourceKind.GENERATED,
            source_name=credit.name if credit else None, license_name=item.license,
            license_url=credit.license_url if credit else None,
            source_url=item.source_ref if item.source_kind == ExampleSourceKind.DICTIONARY else None,
            author=None,
        )
