import unicodedata
from typing import Protocol
from uuid import UUID

from app.modules.content.domain.extraction import (
    Candidate,
    CandidateExtractionResult,
    CandidateType,
)
from app.modules.content.domain.knowledge import (
    CandidateResolutionResult,
    Concept,
    ConceptDictionaryLink,
    ConceptType,
    DictionaryEntry,
    DictionaryEntryDraft,
    LearningObject,
    ResolvedCandidate,
)
from app.modules.content.domain.catalog import TranscriptSegment, VideoTranscript
from app.modules.content.domain.occurrence_spans import OccurrenceSpanError, resolve_occurrence_span
from app.modules.content.application.candidate_extraction import V3CandidateExtractionService
from app.modules.content.application.store_ports import (
    ConceptDictionaryLinkStore,
    ConceptStore,
    DictionaryEntryStore,
    LearningObjectStore,
    TranscriptSegmentStore,
    VideoTranscriptStore,
)


class CandidateResolutionError(ValueError):
    pass


class DictionaryProvider(Protocol):
    def lookup(self, *, language_code: str, candidate: Candidate) -> DictionaryEntryDraft | None:
        ...


class NoopDictionaryProvider:
    def lookup(self, *, language_code: str, candidate: Candidate) -> DictionaryEntryDraft | None:
        _ = language_code, candidate
        return None


CANDIDATE_TYPE_TO_CONCEPT_TYPE = {
    CandidateType.WORD: ConceptType.VOCABULARY,
    CandidateType.PHRASE: ConceptType.EXPRESSION,
    CandidateType.COLLOCATION: ConceptType.COLLOCATION,
    CandidateType.PHRASAL_VERB: ConceptType.PHRASAL_VERB,
    CandidateType.IDIOM: ConceptType.IDIOM,
    CandidateType.GRAMMAR_PATTERN: ConceptType.GRAMMAR,
    CandidateType.OTHER: ConceptType.EXPRESSION,
}


class DictionaryEntryResolver:
    def __init__(
        self,
        *,
        entries: DictionaryEntryStore,
        provider: DictionaryProvider | None = None,
    ):
        self.entries = entries
        self.provider = provider or NoopDictionaryProvider()

    def resolve(self, *, language_code: str, candidate: Candidate) -> tuple[DictionaryEntry | None, str]:
        if candidate.candidate_type == CandidateType.GRAMMAR_PATTERN:
            return None, "not_applicable"

        normalized = normalize_reference_text(candidate.normalized_form, language_code=language_code)
        existing = self._lookup(language_code, normalized)
        if existing is None:
            surface = normalize_reference_text(candidate.surface_form, language_code=language_code)
            existing = self._lookup(language_code, surface) if surface != normalized else None
        if existing:
            lemma = self._lemma_of(language_code, existing)
            return (lemma, "reused_lemma") if lemma else (existing, "reused")

        draft = self.provider.lookup(language_code=language_code, candidate=candidate)
        if draft is None:
            return None, "missing_authoritative_source"

        data = draft.model_dump()
        data["language_code"] = language_code
        entry = self.entries.upsert_by_lookup(data)
        return entry, "created"

    def _lookup(self, language_code: str, normalized_headword: str) -> DictionaryEntry | None:
        return self.entries.get_by_normalized(
            language_code=language_code,
            normalized_headword=normalized_headword,
            part_of_speech="",
        )

    def _lemma_of(self, language_code: str, entry: DictionaryEntry) -> DictionaryEntry | None:
        """An entry whose every sense is an inflection ("went": past of go) resolves to its lemma."""
        senses = [item for item in entry.definitions if isinstance(item, dict)]
        if not senses or not all(item.get("form_of") for item in senses):
            return None
        for target in dict.fromkeys(word for item in senses for word in item["form_of"]):
            lemma = self._lookup(language_code, normalize_reference_text(target, language_code=language_code))
            if lemma and lemma.normalized_headword != entry.normalized_headword:
                return lemma
        return None


class ConceptResolver:
    def __init__(self, *, concepts: ConceptStore):
        self.concepts = concepts

    def resolve(self, *, language_code: str, candidate: Candidate) -> tuple[Concept, str]:
        if candidate.grammar_key:
            return self._resolve_grammar(language_code=language_code, candidate=candidate)
        concept_type = concept_type_for_candidate(candidate)
        normalized_text = normalize_concept_text(candidate.normalized_form, language_code=language_code)
        sense_key = normalize_sense_key(candidate.sense_gloss)
        existing = self.concepts.find_by_identity(
            language_code=language_code,
            concept_type=concept_type.value,
            normalized_text=normalized_text,
            sense_key=sense_key,
        )
        if existing:
            return existing, "reused"

        concept = self.concepts.upsert_by_identity(
            {
                "language_code": language_code,
                "type": concept_type.value,
                "canonical_text": normalize_display_text(candidate.normalized_form),
                "normalized_text": normalized_text,
                "sense_key": sense_key,
                "metadata": {
                    "source": "candidate_resolution",
                    "candidate_type": candidate.candidate_type.value,
                    "sense_gloss": normalize_display_text(candidate.sense_gloss),
                    "sense_identity_version": "sense-key-v1",
                },
            }
        )
        return concept, "created"

    def _resolve_grammar(self, *, language_code: str, candidate: Candidate) -> tuple[Concept, str]:
        """A catalogue grammar point is one Concept identified by its key in every video."""
        key = candidate.grammar_key
        existing = self.concepts.find_by_identity(
            language_code=language_code, concept_type=ConceptType.GRAMMAR.value,
            normalized_text=key, sense_key=key,
        )
        if existing:
            return existing, "reused"
        concept = self.concepts.upsert_by_identity(
            {
                "language_code": language_code,
                "type": ConceptType.GRAMMAR.value,
                "canonical_text": normalize_display_text(candidate.grammar_label or candidate.normalized_form),
                "normalized_text": key,
                "sense_key": key,
                "metadata": {
                    "source": "grammar_catalogue",
                    "grammar_key": key,
                    "sense_identity_version": "grammar-key-v1",
                },
            }
        )
        return concept, "created"


class LearningObjectFactory:
    def build(
        self,
        *,
        candidate: Candidate,
        concept: Concept,
        transcript: VideoTranscript,
        segment: TranscriptSegment,
        occurrence_index: int,
        previous_context: str | None = None,
        next_context: str | None = None,
    ) -> dict:
        if concept.id is None:
            raise CandidateResolutionError("Cannot create learning object without persisted concept id")
        if transcript.video_id is None:
            raise CandidateResolutionError("Cannot create learning object without transcript video id")
        try:
            start_codepoint, end_codepoint = resolve_occurrence_span(
                segment.text,
                candidate.surface_form,
                start_codepoint=candidate.evidence_start,
                end_codepoint=candidate.evidence_end,
                occurrence_ordinal=candidate.surface_occurrence_index,
            )
        except OccurrenceSpanError as exc:
            raise CandidateResolutionError("LearningObject occurrence is not grounded in exact segment text") from exc
        return {
            "concept_id": str(concept.id),
            "video_id": str(transcript.video_id),
            "transcript_segment_id": str(segment.id),
            "occurrence_index": occurrence_index,
            "evidence_text": segment.text[start_codepoint:end_codepoint],
            "start_codepoint": start_codepoint,
            "end_codepoint": end_codepoint,
            "previous_context": previous_context,
            "next_context": next_context,
            "start_ms": segment.start_ms,
            "end_ms": segment.end_ms,
            "ai_confidence": candidate.confidence,
            "extraction_status": "candidate",
            "source": "ai",
            "raw_ai_diagnostics": {
                "candidate_type": candidate.candidate_type.value,
                "candidate_normalized_form": candidate.normalized_form,
                "candidate_sense_gloss": candidate.sense_gloss,
                "candidate_sense_evidence": candidate.sense_evidence,
                "concept_sense_key": concept.sense_key,
                "grammar_key": candidate.grammar_key,
                "evidence_start": candidate.evidence_start,
                "evidence_end": candidate.evidence_end,
                "rationale": candidate.rationale,
                "context": candidate.context,
            },
        }


class CandidateResolutionService:
    def __init__(
        self,
        *,
        concepts: ConceptStore,
        dictionary_entries: DictionaryEntryStore,
        concept_dictionary_links: ConceptDictionaryLinkStore,
        learning_objects: LearningObjectStore,
        dictionary_provider: DictionaryProvider | None = None,
        learning_object_factory: LearningObjectFactory | None = None,
    ):
        self.dictionary_resolver = DictionaryEntryResolver(
            entries=dictionary_entries,
            provider=dictionary_provider,
        )
        self.concept_resolver = ConceptResolver(concepts=concepts)
        self.concept_dictionary_links = concept_dictionary_links
        self.learning_objects = learning_objects
        self.learning_object_factory = learning_object_factory or LearningObjectFactory()

    def resolve_candidates(
        self,
        *,
        candidates: list[Candidate],
        segment: TranscriptSegment,
        transcript: VideoTranscript,
        previous_context: str | None = None,
        next_context: str | None = None,
    ) -> CandidateResolutionResult:
        if segment.id is None:
            raise CandidateResolutionError("Transcript segment must be persisted before resolution")

        resolved: list[ResolvedCandidate] = []
        errors: list[str] = []

        for candidate in candidates:
            if candidate.source_segment_id != segment.id:
                errors.append("Candidate source segment does not match requested segment")
                continue
            try:
                # Validate before any dictionary, Concept or LearningObject write.
                start, end = resolve_occurrence_span(
                    segment.text, candidate.surface_form,
                    start_codepoint=candidate.evidence_start,
                    end_codepoint=candidate.evidence_end,
                    occurrence_ordinal=candidate.surface_occurrence_index,
                )
                candidate = candidate.model_copy(update={"evidence_start": start, "evidence_end": end})
                dictionary_entry, dictionary_status = self.dictionary_resolver.resolve(
                    language_code=transcript.language_code,
                    candidate=candidate,
                )
                concept, concept_status = self.concept_resolver.resolve(
                    language_code=transcript.language_code,
                    candidate=candidate,
                )
                link, link_status = self._link_concept_dictionary(concept, dictionary_entry)
                learning_object, learning_object_status = self._upsert_learning_object(
                    candidate=candidate,
                    concept=concept,
                    transcript=transcript,
                    segment=segment,
                    previous_context=previous_context,
                    next_context=next_context,
                )
                resolved.append(
                    ResolvedCandidate(
                        candidate=candidate,
                        dictionary_entry=dictionary_entry,
                        concept=concept,
                        learning_object=learning_object,
                        concept_dictionary_link=link,
                        status={
                            "dictionary_entry": dictionary_status,
                            "concept": concept_status,
                            "concept_dictionary_link": link_status,
                            "learning_object": learning_object_status,
                        },
                    )
                )
            except (CandidateResolutionError, OccurrenceSpanError) as exc:
                errors.append(str(exc))

        return CandidateResolutionResult(
            source_segment_id=segment.id,
            language_code=transcript.language_code,
            resolved=resolved,
            errors=errors,
            metadata={
                "candidate_count": len(candidates),
                "resolved_count": len(resolved),
            },
        )

    def _link_concept_dictionary(
        self,
        concept: Concept,
        dictionary_entry: DictionaryEntry | None,
    ) -> tuple[ConceptDictionaryLink | None, str]:
        if dictionary_entry is None:
            return None, "not_applicable"
        if concept.id is None or dictionary_entry.id is None:
            raise CandidateResolutionError("Cannot link unpersisted concept or dictionary entry")
        existing = self.concept_dictionary_links.get_by_ids(concept.id, dictionary_entry.id)
        link = self.concept_dictionary_links.upsert_link(
            concept_id=concept.id,
            dictionary_entry_id=dictionary_entry.id,
            relation_type="supports",
        )
        return link, "reused" if existing else "created"

    def _upsert_learning_object(
        self,
        *,
        candidate: Candidate,
        concept: Concept,
        transcript: VideoTranscript,
        segment: TranscriptSegment,
        previous_context: str | None,
        next_context: str | None,
    ) -> tuple[LearningObject, str]:
        if concept.id is None or segment.id is None:
            raise CandidateResolutionError("Cannot persist learning object without concept and segment ids")
        existing = self.learning_objects.get_by_span(
            concept_id=concept.id,
            transcript_segment_id=segment.id,
            start_codepoint=candidate.evidence_start,
            end_codepoint=candidate.evidence_end,
        )
        if existing is not None:
            return existing, "reused"
        rows = self.learning_objects.list_for_segment_concept(
            concept_id=concept.id, transcript_segment_id=segment.id,
        )
        occurrence_index = max((row.occurrence_index for row in rows), default=0) + 1
        data = self.learning_object_factory.build(
            candidate=candidate,
            concept=concept,
            transcript=transcript,
            segment=segment,
            occurrence_index=occurrence_index,
            previous_context=previous_context,
            next_context=next_context,
        )
        learning_object = self.learning_objects.upsert_by_occurrence(data)
        return learning_object, "created"


class V3CandidateResolutionService:
    def __init__(
        self,
        *,
        segments: TranscriptSegmentStore,
        transcripts: VideoTranscriptStore,
        extraction: V3CandidateExtractionService,
        resolution: CandidateResolutionService,
    ):
        self.segments = segments
        self.transcripts = transcripts
        self.extraction = extraction
        self.resolution = resolution

    def extract_and_resolve_by_segment_id(
        self,
        transcript_segment_id: UUID,
        *,
        previous_context: str | None = None,
        next_context: str | None = None,
    ) -> CandidateResolutionResult | None:
        segment = self.segments.get_by_id(transcript_segment_id)
        if segment is None:
            return None
        transcript = self.transcripts.get_by_id(segment.transcript_id)
        if transcript is None:
            raise CandidateResolutionError("Transcript not found for segment")
        extraction_result = self.extraction.extract_by_segment_id(
            transcript_segment_id,
            previous_context=previous_context,
            next_context=next_context,
        )
        if extraction_result is None:
            return None
        return self.resolve_extraction_result(
            extraction_result=extraction_result,
            segment=segment,
            transcript=transcript,
            previous_context=previous_context,
            next_context=next_context,
        )

    def resolve_extraction_result(
        self,
        *,
        extraction_result: CandidateExtractionResult,
        segment: TranscriptSegment,
        transcript: VideoTranscript,
        previous_context: str | None = None,
        next_context: str | None = None,
    ) -> CandidateResolutionResult:
        # Retry diagnostics can remain in `errors` even after a later
        # structured provider attempt succeeds. Only terminal extraction
        # failure may prevent resolution of grounded candidates.
        if extraction_result.extraction_metadata.get("failed_closed"):
            return CandidateResolutionResult(
                source_segment_id=extraction_result.source_segment_id,
                language_code=transcript.language_code,
                resolved=[],
                errors=extraction_result.errors,
                metadata={
                    **extraction_result.extraction_metadata,
                    "failed_before_resolution": True,
                },
            )
        return self.resolution.resolve_candidates(
            candidates=extraction_result.candidates,
            segment=segment,
            transcript=transcript,
            previous_context=previous_context,
            next_context=next_context,
        )


def concept_type_for_candidate(candidate: Candidate) -> ConceptType:
    concept_type = CANDIDATE_TYPE_TO_CONCEPT_TYPE.get(candidate.candidate_type)
    if concept_type is None:
        raise CandidateResolutionError(f"Unsupported candidate type: {candidate.candidate_type}")
    return concept_type


def normalize_display_text(value: str) -> str:
    text = unicodedata.normalize("NFC", value or "")
    text = " ".join(text.strip().strip("\"'“”‘’").split())
    if not text:
        raise CandidateResolutionError("Cannot normalize empty text")
    return text


def normalize_concept_text(value: str, *, language_code: str) -> str:
    text = normalize_display_text(value)
    if language_code.casefold() in {"en", "fr", "de", "es", "it", "pt"}:
        text = text.casefold()
    return text


def normalize_reference_text(value: str, *, language_code: str) -> str:
    return normalize_concept_text(value, language_code=language_code)


def normalize_sense_key(value: str) -> str:
    """Normalize a source-language semantic label without erasing punctuation."""
    text = unicodedata.normalize("NFKC", value or "")
    text = " ".join(text.strip().strip("\"'“”‘’").casefold().split())
    if not text:
        raise CandidateResolutionError("Cannot normalize empty sense gloss")
    if len(text) > 500:
        raise CandidateResolutionError("Sense gloss is too long")
    return text
