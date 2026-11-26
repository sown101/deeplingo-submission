from datetime import UTC, datetime
from uuid import UUID

from app.modules.content.domain.knowledge import (
    Concept,
    DictionaryEntry,
    EnrichmentDifficulty,
    LearningObject,
    LearningObjectEnrichmentResult,
)
from app.modules.content.application.ports import LearningObjectEnrichmentProvider
from app.modules.content.application.prompts import (
    LEARNING_OBJECT_ENRICHMENT_PROMPT_VERSION,
    build_learning_object_enrichment_prompt,
)
from app.platform.llm.port import LLMProviderError
from app.modules.content.application.store_ports import (
    ConceptDictionaryLinkStore,
    ConceptStore,
    DictionaryEntryStore,
    LearningObjectStore,
    SegmentTranslationStore,
    TranscriptSegmentStore,
    VideoTranscriptStore,
)


class LearningObjectEnrichmentError(ValueError):
    pass


class DictionarySenseMismatch(LearningObjectEnrichmentError):
    """The dictionary has the headword but no offered sense fits.

    The occurrence is excluded from practice and recorded for review; it is not a provider failure.
    """


MAX_OFFERED_SENSES = 12
MAX_SENSE_LINE_CHARS = 240
MEANING_FROM_SENSE = "translated_from_sense"
MEANING_UNVERIFIED = "ai_unverified"


SUPPORTED_DIFFICULTY_LEVELS = {
    "CEFR": {
        "languages": {"en", "fr", "de", "es", "it", "pt"},
        "levels": {"A1", "A2", "B1", "B2", "C1", "C2"},
    },
    "HSK": {
        "languages": {"zh"},
        "levels": {"HSK1", "HSK2", "HSK3", "HSK4", "HSK5", "HSK6"},
    },
    "JLPT": {
        "languages": {"ja"},
        "levels": {"N5", "N4", "N3", "N2", "N1"},
    },
    "TOPIK": {
        "languages": {"ko"},
        "levels": {"TOPIK1", "TOPIK2", "TOPIK3", "TOPIK4", "TOPIK5", "TOPIK6"},
    },
}


class LearningObjectEnrichmentService:
    def __init__(
        self,
        *,
        learning_objects: LearningObjectStore,
        concepts: ConceptStore,
        segments: TranscriptSegmentStore,
        transcripts: VideoTranscriptStore,
        translations: SegmentTranslationStore,
        concept_dictionary_links: ConceptDictionaryLinkStore,
        dictionary_entries: DictionaryEntryStore,
        provider: LearningObjectEnrichmentProvider,
    ):
        self.learning_objects = learning_objects
        self.concepts = concepts
        self.segments = segments
        self.transcripts = transcripts
        self.translations = translations
        self.concept_dictionary_links = concept_dictionary_links
        self.dictionary_entries = dictionary_entries
        self.provider = provider

    def enrich(
        self,
        learning_object_id: UUID,
        *,
        target_language_code: str,
        force: bool = False,
    ) -> LearningObjectEnrichmentResult | None:
        target_language_code = target_language_code.strip().casefold()
        learning_object = self.learning_objects.get_by_id(learning_object_id)
        if learning_object is None:
            return None

        concept = self.concepts.get_by_id(learning_object.concept_id)
        if concept is None:
            raise LearningObjectEnrichmentError("Concept not found for LearningObject")
        existing = _existing_enrichment(learning_object, target_language_code, concept)
        if existing and not force:
            return _result_from_existing(learning_object, existing, "reused")

        segment = self.segments.get_by_id(learning_object.transcript_segment_id)
        if segment is None:
            raise LearningObjectEnrichmentError("TranscriptSegment not found for LearningObject")

        transcript = self.transcripts.get_by_id(segment.transcript_id)
        if transcript is None:
            raise LearningObjectEnrichmentError("VideoTranscript not found for LearningObject")

        previous_segment = self.segments.get_neighbor(
            transcript_id=segment.transcript_id,
            sequence_number=segment.sequence_number,
            offset=-1,
        )
        next_segment = self.segments.get_neighbor(
            transcript_id=segment.transcript_id,
            sequence_number=segment.sequence_number,
            offset=1,
        )
        translation = self.translations.get_by_segment_language(
            learning_object.transcript_segment_id,
            target_language_code,
        )
        dictionary_entries = self._dictionary_entries_for_concept(concept.id)
        offered = _rank_senses(
            self._offered_senses(dictionary_entries, transcript.language_code),
            f"{concept.sense_key} {concept.canonical_text}",
        )

        prompt = build_learning_object_enrichment_prompt(
            source_language=transcript.language_code,
            target_language=target_language_code,
            concept_type=concept.type.value if hasattr(concept.type, "value") else str(concept.type),
            concept_canonical_text=concept.canonical_text,
            concept_sense_key=concept.sense_key,
            evidence_text=learning_object.evidence_text,
            source_segment=segment.text,
            previous_segment=previous_segment.text if previous_segment else None,
            next_segment=next_segment.text if next_segment else None,
            translation=translation.text if translation else None,
            dictionary_senses=_format_offered_senses(offered),
            difficulty_framework=_default_framework_for_language(transcript.language_code),
            difficulty_levels=_difficulty_levels(transcript.language_code),
        )

        try:
            ai_output = self.provider.enrich(prompt)
        except LLMProviderError as exc:
            raise LearningObjectEnrichmentError(str(exc)) from exc

        offered_by_id = {sense["sense_id"]: (sense, entry) for sense, entry in offered}
        if ai_output.sense_id is not None and ai_output.sense_id not in offered_by_id:
            raise LearningObjectEnrichmentError("Enrichment selected a dictionary sense that was not offered")
        if offered and ai_output.sense_id is None:
            self._record_sense_mismatch(learning_object, target_language_code, concept, offered)
            raise DictionarySenseMismatch("No offered dictionary sense fits this occurrence")

        difficulty = _difficulty_with_authoritative_priority(ai_output.difficulty, concept, transcript.language_code)
        if ai_output.sense_id:
            difficulty = _difficulty_with_word_list_level(difficulty, offered_by_id[ai_output.sense_id][1])
        _validate_difficulty(difficulty, transcript.language_code)

        translation_text = translation.text if translation else None
        translation_source = translation.source if translation else None
        enrichment = {
            "concept_id": str(concept.id),
            "concept_sense_key": concept.sense_key,
            "source_language_code": transcript.language_code,
            "target_language_code": target_language_code,
            "contextual_meaning": ai_output.contextual_meaning,
            "explanation": ai_output.explanation,
            "translation": translation_text,
            "translation_source": translation_source,
            "difficulty": difficulty.model_dump(),
            "learning_value": ai_output.learning_value.model_dump(),
            "confidence": ai_output.confidence,
            "provider": self.provider.provider_name,
            "model": self.provider.model_name,
            "prompt_version": LEARNING_OBJECT_ENRICHMENT_PROMPT_VERSION,
            "generated_at": datetime.now(UTC).isoformat(),
            "dictionary_entry_ids": [str(entry.id) for entry in dictionary_entries if entry.id],
            "sense_id": ai_output.sense_id,
            "dictionary_sense": _sense_reference(*offered_by_id[ai_output.sense_id]) if ai_output.sense_id else None,
            "meaning_provenance": MEANING_FROM_SENSE if ai_output.sense_id else MEANING_UNVERIFIED,
        }
        raw_ai_diagnostics = dict(learning_object.raw_ai_diagnostics or {})
        per_language = dict(raw_ai_diagnostics.get("enrichments") or {})
        legacy = raw_ai_diagnostics.get("enrichment")
        if isinstance(legacy, dict) and isinstance(legacy.get("target_language_code"), str):
            per_language.setdefault(legacy["target_language_code"], legacy)
        per_language[target_language_code] = enrichment
        raw_ai_diagnostics["enrichments"] = per_language
        # Retain the last-written legacy field for older internal consumers.
        raw_ai_diagnostics["enrichment"] = enrichment

        updated = self.learning_objects.update_enrichment(
            learning_object.id,
            {
                "difficulty_score": difficulty.score,
                "learning_value_score": ai_output.learning_value.score,
                "ai_confidence": ai_output.confidence,
                "raw_ai_diagnostics": raw_ai_diagnostics,
            },
        )
        if updated is None:
            raise LearningObjectEnrichmentError("LearningObject enrichment update returned no row")
        # M1 S7b: under a claim the first meaning of this prompt version wins (overlapping regions
        # or the Video and a region may enrich the same occurrence); report what is stored.
        stored = _existing_enrichment(updated, target_language_code, concept)
        if stored is not None and stored.get("generated_at") != enrichment["generated_at"]:
            return _result_from_existing(updated, stored, "reused")
        return _result_from_existing(updated, enrichment, "updated" if force else "created")

    def _dictionary_entries_for_concept(self, concept_id: UUID | None) -> list[DictionaryEntry]:
        if concept_id is None:
            return []
        ids = [link.dictionary_entry_id for link in self.concept_dictionary_links.list_for_concept(concept_id)]
        entries = self.dictionary_entries.get_many_by_ids(ids)
        return [entries[key] for key in ids if key in entries][:3]

    def _offered_senses(
        self, entries: list[DictionaryEntry], language_code: str,
    ) -> list[tuple[dict, DictionaryEntry]]:
        """Senses with stable IDs; inflection senses ("went": past of go) offer the lemma's senses."""
        offered: dict[str, tuple[dict, DictionaryEntry]] = {}
        lemmas: list[str] = []
        for entry in entries:
            for sense in entry.definitions:
                if not isinstance(sense, dict) or not sense.get("sense_id") or not sense.get("text"):
                    continue
                if sense.get("form_of"):
                    lemmas.extend(word for word in sense["form_of"] if isinstance(word, str))
                    continue
                offered.setdefault(sense["sense_id"], (sense, entry))
        seen = {entry.normalized_headword for entry in entries}
        headwords = []
        for word in lemmas:
            normalized = " ".join(word.split())
            if language_code.casefold() in _CASEFOLD_LANGUAGES:
                normalized = normalized.casefold()
            if normalized and normalized not in seen:
                seen.add(normalized)
                headwords.append(normalized)
        entries_by_headword = {}
        for start in range(0, len(headwords), 100):
            entries_by_headword.update((entry.normalized_headword, entry) for entry in
                self.dictionary_entries.list_by_headwords(language_code=language_code,
                                                          normalized_headwords=headwords[start:start + 100]))
        for headword in headwords:
            lemma = entries_by_headword.get(headword)
            for sense in (lemma.definitions if lemma else []):
                if (isinstance(sense, dict) and sense.get("sense_id") and sense.get("text")
                        and not sense.get("form_of")):
                    offered.setdefault(sense["sense_id"], (sense, lemma))
        return list(offered.values())

    def _record_sense_mismatch(
        self, learning_object: LearningObject, target_language_code: str, concept: Concept,
        offered: list[tuple[dict, DictionaryEntry]],
    ) -> None:
        """Withdraw any prepared meaning for this language and record the occurrence for review."""
        diagnostics = dict(learning_object.raw_ai_diagnostics or {})
        per_language = dict(diagnostics.get("enrichments") or {})
        per_language.pop(target_language_code, None)
        diagnostics["enrichments"] = per_language
        legacy = diagnostics.get("enrichment")
        if isinstance(legacy, dict) and legacy.get("target_language_code") == target_language_code:
            diagnostics.pop("enrichment")
        review = {
            "status": "no_matching_sense",
            "concept_id": str(concept.id),
            "concept_sense_key": concept.sense_key,
            "offered_sense_ids": [sense["sense_id"] for sense, _ in offered],
            "provider": self.provider.provider_name,
            "model": self.provider.model_name,
            "prompt_version": LEARNING_OBJECT_ENRICHMENT_PROMPT_VERSION,
            "recorded_at": datetime.now(UTC).isoformat(),
        }
        reviews = dict(diagnostics.get("dictionary_review") or {})
        reviews[target_language_code] = review
        diagnostics["dictionary_review"] = reviews
        # A26: a claimed store records `review` under its fence; others write the prepared diagnostics.
        if self.learning_objects.record_sense_review(
            learning_object.id, target_language_code=target_language_code, review=review,
            raw_ai_diagnostics=diagnostics,
        ) is None:
            raise LearningObjectEnrichmentError("LearningObject dictionary review update returned no row")


def _existing_enrichment(
    learning_object: LearningObject, target_language_code: str, concept: Concept,
) -> dict | None:
    diagnostics = learning_object.raw_ai_diagnostics or {}
    per_language = diagnostics.get("enrichments")
    enrichment = per_language.get(target_language_code) if isinstance(per_language, dict) else None
    if enrichment is None:
        enrichment = diagnostics.get("enrichment")
    if not isinstance(enrichment, dict):
        return None
    if enrichment.get("target_language_code") != target_language_code:
        return None
    if enrichment.get("concept_id") != str(concept.id) or enrichment.get("concept_sense_key") != concept.sense_key:
        return None
    # M1 S7b: a meaning made with another prompt version is made again, never reused.
    if enrichment.get("prompt_version") != LEARNING_OBJECT_ENRICHMENT_PROMPT_VERSION:
        return None
    return enrichment


def _result_from_existing(
    learning_object: LearningObject,
    enrichment: dict,
    status: str,
) -> LearningObjectEnrichmentResult:
    return LearningObjectEnrichmentResult(
        learning_object_id=_require_uuid(learning_object.id, "LearningObject id is missing"),
        concept_id=learning_object.concept_id,
        transcript_segment_id=learning_object.transcript_segment_id,
        source_language_code=enrichment.get("source_language_code") or "",
        target_language_code=enrichment["target_language_code"],
        contextual_meaning=enrichment["contextual_meaning"],
        explanation=enrichment["explanation"],
        translation=enrichment.get("translation"),
        translation_source=enrichment.get("translation_source"),
        difficulty=EnrichmentDifficulty.model_validate(enrichment["difficulty"]),
        learning_value=enrichment["learning_value"],
        confidence=enrichment["confidence"],
        provider=enrichment["provider"],
        model=enrichment["model"],
        prompt_version=enrichment["prompt_version"],
        status=status,
        diagnostics={
            "dictionary_entry_ids": enrichment.get("dictionary_entry_ids", []),
            "generated_at": enrichment.get("generated_at"),
            "sense_id": enrichment.get("sense_id"),
            "meaning_provenance": enrichment.get("meaning_provenance"),
        },
    )


def _require_uuid(value: UUID | None, message: str) -> UUID:
    if value is None:
        raise LearningObjectEnrichmentError(message)
    return value


def _difficulty_with_authoritative_priority(
    ai_difficulty: EnrichmentDifficulty,
    concept: Concept,
    source_language_code: str,
) -> EnrichmentDifficulty:
    if concept.difficulty_score is None and not concept.difficulty_level:
        return ai_difficulty
    framework = _default_framework_for_language(source_language_code)
    if framework is None:
        return ai_difficulty
    level = concept.difficulty_level or ai_difficulty.level
    return EnrichmentDifficulty(
        framework=framework,
        level=level,
        score=concept.difficulty_score if concept.difficulty_score is not None else ai_difficulty.score,
        confidence=1.0 if concept.difficulty_score is not None else ai_difficulty.confidence,
        provenance="concept",
    )


def _difficulty_with_word_list_level(difficulty: EnrichmentDifficulty, entry: DictionaryEntry) -> EnrichmentDifficulty:
    """A curated word-list level (CEFR-J, recorded on the dictionary entry) replaces the AI's level.

    Concept-level authority still wins. The level belongs to the headword, not the exact sense,
    so the provenance says so; the AI score is kept.
    """
    level = (entry.provider_metadata or {}).get("cefr_j")
    if difficulty.provenance == "concept" or difficulty.framework.upper() != "CEFR" or not isinstance(level, str):
        return difficulty
    if level.upper() not in SUPPORTED_DIFFICULTY_LEVELS["CEFR"]["levels"]:
        return difficulty
    return difficulty.model_copy(update={"level": level.upper(), "provenance": "cefr_j_headword"})


def _default_framework_for_language(language_code: str) -> str | None:
    code = language_code.casefold()
    for framework, config in SUPPORTED_DIFFICULTY_LEVELS.items():
        if code in config["languages"]:
            return framework
    return None


def _difficulty_levels(language_code: str) -> tuple[str, ...]:
    framework = _default_framework_for_language(language_code)
    if framework is None:
        return ()
    order = {"CEFR": ["A1", "A2", "B1", "B2", "C1", "C2"], "JLPT": ["N5", "N4", "N3", "N2", "N1"]}
    levels = SUPPORTED_DIFFICULTY_LEVELS[framework]["levels"]
    return tuple(order.get(framework) or sorted(levels))


def _validate_difficulty(difficulty: EnrichmentDifficulty, source_language_code: str) -> None:
    framework = difficulty.framework.upper()
    config = SUPPORTED_DIFFICULTY_LEVELS.get(framework)
    if config is None:
        raise LearningObjectEnrichmentError(f"Unsupported difficulty framework: {difficulty.framework}")
    if source_language_code.casefold() not in config["languages"]:
        raise LearningObjectEnrichmentError(
            f"Difficulty framework {framework} is not supported for language {source_language_code}"
        )
    if difficulty.level and difficulty.level.upper() not in config["levels"]:
        raise LearningObjectEnrichmentError(f"Unsupported difficulty level: {difficulty.level}")
    difficulty.framework = framework
    if difficulty.level:
        difficulty.level = difficulty.level.upper()


_CASEFOLD_LANGUAGES = {"en", "fr", "de", "es", "it", "pt"}


def _rank_senses(senses: list[tuple[dict, DictionaryEntry]], hint: str) -> list[tuple[dict, DictionaryEntry]]:
    """Offer at most MAX_OFFERED_SENSES; senses sharing words with the Concept sense come first.

    Ties keep dictionary order, which in Wiktionary and CC-CEDICT lists common senses first.
    """
    words = {word for word in _words(hint) if len(word) > 2}

    def key(item: tuple[int, tuple[dict, DictionaryEntry]]) -> tuple[int, int]:
        index, (sense, _) = item
        return -len(words & _words(f"{sense.get('parent') or ''} {sense['text']}")), index

    return [item for _, item in sorted(enumerate(senses), key=key)[:MAX_OFFERED_SENSES]]


def _words(text: str) -> set[str]:
    return {word.strip(".,;:()[]\"'!?") for word in text.casefold().split()}


def _format_offered_senses(senses: list[tuple[dict, DictionaryEntry]]) -> str | None:
    if not senses:
        return None
    lines = []
    for sense, entry in senses:
        label = " ".join(part for part in (
            entry.headword,
            f"({sense['pos']})" if sense.get("pos") else "",
            f"[{sense['reading']}]" if sense.get("reading") else "",
        ) if part)
        text = f"{sense['parent'].rstrip(':')}: {sense['text']}" if sense.get("parent") else sense["text"]
        lines.append(f"- [{sense['sense_id']}] {label}: {text}"[:MAX_SENSE_LINE_CHARS])
    return "\n".join(lines)


def _sense_reference(sense: dict, entry: DictionaryEntry) -> dict:
    return {
        "sense_id": sense["sense_id"],
        "dictionary_entry_id": str(entry.id) if entry.id else None,
        "headword": entry.headword,
        "text": sense["text"],
        "pos": sense.get("pos"),
        "reading": sense.get("reading"),
        "provider": entry.provider,
    }
