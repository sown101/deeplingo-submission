import logging
import unicodedata
from uuid import UUID

from pydantic import ValidationError

from app.modules.content.domain.extraction import (
    Candidate,
    CandidateExtractionResult,
    CandidateType,
    LearningUnit,
    LLMCandidate,
    LLMCandidateResponse,
)
from app.modules.content.domain.catalog import TranscriptSegment
from app.modules.content.domain.occurrence_spans import OccurrenceSpanError, resolve_occurrence_span
from app.modules.content.application.grammar_selection import GrammarSelectionService
from app.modules.content.application.prompts import (
    CANDIDATE_EXTRACTION_PROMPT_VERSION,
    GRAMMAR_SELECTION_PROMPT_VERSION,
    build_candidate_extraction_prompt,
)
from app.platform.llm.port import LLMProvider, LLMProviderError
from app.modules.content.application.store_ports import TranscriptSegmentStore, VideoTranscriptStore

logger = logging.getLogger(__name__)


# Defaults mirror Settings.AI_EXTRACTION_MAX_CANDIDATES_PER_SEGMENT / AI_EXTRACTION_MAX_RETRIES;
# production wiring passes the configured values.
DEFAULT_MAX_CANDIDATES_PER_SEGMENT = 8
DEFAULT_EXTRACTION_MAX_RETRIES = 2


class CandidateValidationError(ValueError):
    pass


class CandidateExtractionService:
    def __init__(
        self,
        *,
        provider: LLMProvider,
        max_candidates_per_segment: int | None = None,
        max_retries: int | None = None,
        propagate_failures: bool = False,
        grammar_selection: GrammarSelectionService | None = None,
    ):
        self.provider = provider
        self.grammar_selection = grammar_selection
        self.max_candidates_per_segment = max_candidates_per_segment or DEFAULT_MAX_CANDIDATES_PER_SEGMENT
        self.max_retries = max_retries if max_retries is not None else DEFAULT_EXTRACTION_MAX_RETRIES
        self.propagate_failures = propagate_failures

    def extract_segment(
        self,
        *,
        segment: TranscriptSegment,
        source_language: str,
        previous_context: str | None = None,
        next_context: str | None = None,
    ) -> CandidateExtractionResult:
        original_text = segment.text
        prompt = build_candidate_extraction_prompt(
            source_language=source_language,
            transcript_text=original_text,
            max_candidates=self.max_candidates_per_segment,
            previous_context=previous_context,
            next_context=next_context,
        )
        errors: list[str] = []
        response = None
        attempts = max(self.max_retries, 0) + 1

        for attempt in range(1, attempts + 1):
            try:
                response = self.provider.generate_structured(prompt, LLMCandidateResponse)
                break
            except (LLMProviderError, ValidationError) as exc:
                if self.propagate_failures:
                    raise
                errors.append(type(exc).__name__)
                logger.warning(
                    "candidate extraction provider attempt failed segment_id=%s provider=%s attempt=%s",
                    segment.id,
                    self.provider.provider_name,
                    attempt,
                )

        if response is None:
            return self._failure_result(segment.id, errors, attempts)

        # Output validation is permanent for this segment only. It never propagates,
        # so one ungrounded candidate cannot fail a whole claimed preparation.
        skipped = sum(1 for item in response.candidates if item.learning_unit != LearningUnit.REUSABLE)
        # Grammar comes only from the separate selection pass.
        free_grammar = sum(1 for item in response.candidates if item.candidate_type == CandidateType.GRAMMAR_PATTERN)
        try:
            candidates, rejected = self._validate_and_normalize(
                response=response,
                source_text=original_text,
                source_segment_id=segment.id,
                word_delimited=_is_word_delimited(source_language),
            )
        except CandidateValidationError as exc:
            return self._failure_result(segment.id, [*errors, str(exc)], attempts)

        model_metadata = {
            "provider": self.provider.provider_name,
            "model": self.provider.model_name,
            "prompt_version": CANDIDATE_EXTRACTION_PROMPT_VERSION,
        }
        metadata = {
            "attempts": attempts if errors else 1,
            "max_candidates_per_segment": self.max_candidates_per_segment,
            "rejected_candidate_count": len(rejected),
            "low_value_skipped_count": skipped,
            "free_grammar_skipped_count": free_grammar,
        }
        if self.grammar_selection is not None:
            grammar = self.grammar_selection.select(
                segment=segment, source_language=source_language,
                previous_context=previous_context, next_context=next_context,
            )
            candidates = [*candidates, *grammar.candidates]
            rejected = [*rejected, *grammar.errors]
            model_metadata["grammar_prompt_version"] = GRAMMAR_SELECTION_PROMPT_VERSION
            metadata.update({
                "grammar_candidate_count": len(grammar.candidates),
                "grammar_split_skipped_count": grammar.split_skipped,
                "grammar_form_mismatch_skipped_count": grammar.form_mismatch_skipped,
                "grammar_failed_closed": grammar.failed_closed,
            })
        if rejected and not candidates:
            return self._failure_result(segment.id, [*errors, *rejected], attempts)
        metadata["candidate_count"] = len(candidates)

        return CandidateExtractionResult(
            source_segment_id=segment.id,
            candidates=candidates,
            model_metadata=model_metadata,
            extraction_metadata=metadata,
            errors=[*errors, *rejected],
        )

    def extract_segments(
        self,
        *,
        segments: list[TranscriptSegment],
        source_language: str,
    ) -> list[CandidateExtractionResult]:
        return [
            self.extract_segment(segment=segment, source_language=source_language)
            for segment in segments
        ]

    def _validate_and_normalize(
        self,
        *,
        response: LLMCandidateResponse,
        source_text: str,
        source_segment_id: UUID,
        word_delimited: bool = False,
    ) -> tuple[list[Candidate], list[str]]:
        """Return grounded candidates and the reasons for individually rejected ones."""
        if len(response.candidates) > self.max_candidates_per_segment:
            raise CandidateValidationError("Candidate count exceeded limit")

        candidates: list[Candidate] = []
        rejected: list[str] = []
        seen: set[tuple[str, str, str, int, int]] = set()
        for item in response.candidates:
            if item.learning_unit != LearningUnit.REUSABLE:
                # Names, titles, free combinations and filler are not learning targets (DEBT A20).
                continue
            if item.candidate_type == CandidateType.GRAMMAR_PATTERN:
                # Grammar is never named freely; the selection pass picks catalogue points.
                continue
            try:
                candidate = self._candidate_from_llm(
                    item, source_text, source_segment_id, word_delimited=word_delimited,
                )
            except CandidateValidationError as exc:
                rejected.append(str(exc))
                continue
            key = (
                candidate.normalized_form.casefold(),
                candidate.candidate_type.value,
                _normalize_sense_gloss(candidate.sense_gloss),
                candidate.evidence_start,
                candidate.evidence_end,
            )
            if key in seen:
                continue
            seen.add(key)
            candidates.append(candidate)
        return candidates, rejected

    def _candidate_from_llm(
        self,
        item: LLMCandidate,
        source_text: str,
        source_segment_id: UUID,
        *,
        word_delimited: bool = False,
    ) -> Candidate:
        surface_form = item.surface_form
        normalized_form = _mechanical_normalize(item.normalized_form)
        sense_gloss = _mechanical_normalize(item.sense_gloss)
        sense_evidence = _mechanical_normalize(item.sense_evidence)
        context = _mechanical_normalize(item.context) if item.context else None

        anchored = _anchor_occurrence_by_evidence(source_text, surface_form, item.sense_evidence)
        occurrence_index = item.surface_occurrence_index
        try:
            evidence_start, evidence_end = resolve_occurrence_span(
                source_text,
                surface_form,
                occurrence_ordinal=occurrence_index,
            )
        except OccurrenceSpanError as exc:
            if anchored is None or occurrence_index is not None:
                raise CandidateValidationError(
                    "Candidate surface form is not uniquely grounded in source segment"
                ) from exc
            evidence_start, evidence_end, occurrence_index = anchored
        if anchored is not None and anchored[:2] != (evidence_start, evidence_end):
            raise CandidateValidationError("Candidate occurrence conflicts with its exact sense evidence")
        if word_delimited and _splits_word(source_text, evidence_start, evidence_end):
            raise CandidateValidationError("Candidate surface form is only part of a longer source word")
        if not _is_grounded(sense_evidence, source_text) or not _is_grounded(surface_form, sense_evidence):
            raise CandidateValidationError("Candidate sense evidence is not grounded in source segment")

        return Candidate(
            surface_form=surface_form,
            normalized_form=normalized_form,
            sense_gloss=sense_gloss,
            sense_evidence=sense_evidence,
            candidate_type=item.candidate_type,
            evidence_start=evidence_start,
            evidence_end=evidence_end,
            surface_occurrence_index=occurrence_index,
            source_segment_id=source_segment_id,
            confidence=item.confidence,
            rationale=_mechanical_normalize(item.rationale) if item.rationale else None,
            context=context,
        )

    def _failure_result(
        self,
        source_segment_id: UUID,
        errors: list[str],
        attempts: int,
    ) -> CandidateExtractionResult:
        return CandidateExtractionResult(
            source_segment_id=source_segment_id,
            candidates=[],
            model_metadata={
                "provider": self.provider.provider_name,
                "model": self.provider.model_name,
                "prompt_version": CANDIDATE_EXTRACTION_PROMPT_VERSION,
            },
            extraction_metadata={
                "attempts": attempts,
                "max_candidates_per_segment": self.max_candidates_per_segment,
                "candidate_count": 0,
                "failed_closed": True,
            },
            errors=errors or ["candidate extraction failed"],
        )


class V3CandidateExtractionService:
    def __init__(
        self,
        *,
        segments: TranscriptSegmentStore,
        transcripts: VideoTranscriptStore,
        extraction: CandidateExtractionService,
    ):
        self.segments = segments
        self.transcripts = transcripts
        self.extraction = extraction

    def extract_by_segment_id(
        self,
        transcript_segment_id: UUID,
        previous_context: str | None = None,
        next_context: str | None = None,
    ) -> CandidateExtractionResult | None:
        segment = self.segments.get_by_id(transcript_segment_id)
        if segment is None:
            return None
        transcript = self.transcripts.get_by_id(segment.transcript_id)
        source_language = transcript.language_code if transcript else "en"
        return self.extraction.extract_segment(
            segment=segment,
            source_language=source_language,
            previous_context=previous_context,
            next_context=next_context,
        )


def _mechanical_normalize(value: str) -> str:
    text = unicodedata.normalize("NFC", value or "")
    text = " ".join(text.strip().strip("\"'“”‘’").split())
    if not text:
        raise CandidateValidationError("Candidate text is empty after normalization")
    return text


def _normalize_for_grounding(value: str) -> str:
    return " ".join(unicodedata.normalize("NFC", value or "").casefold().split())


def _normalize_sense_gloss(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value or "").strip().casefold().split())


def _is_grounded(surface_form: str, source_text: str) -> bool:
    return _normalize_for_grounding(surface_form) in _normalize_for_grounding(source_text)


# Languages written with spaces between words and without productive suffix
# agglutination, where a span inside a longer word is never the intended form.
_WORD_BOUNDARY_LANGUAGES = frozenset({"en", "fr", "es", "it", "pt", "de", "nl", "vi"})


def _is_word_delimited(language_code: str) -> bool:
    return (language_code or "").split("-")[0].casefold() in _WORD_BOUNDARY_LANGUAGES


def _is_word_char(character: str) -> bool:
    return bool(character) and (character.isalnum() or unicodedata.category(character).startswith("M"))


def _splits_word(text: str, start: int, end: int) -> bool:
    before = text[start - 1] if start > 0 else ""
    after = text[end] if end < len(text) else ""
    return (
        (_is_word_char(before) and _is_word_char(text[start]))
        or (_is_word_char(after) and _is_word_char(text[end - 1]))
    )


def _exact_match_starts(text: str, needle: str) -> list[int]:
    starts, cursor = [], 0
    while (start := text.find(needle, cursor)) >= 0:
        starts.append(start)
        cursor = start + 1  # Count overlapping matches like resolve_occurrence_span.
    return starts


def _anchor_occurrence_by_evidence(
    source_text: str, surface_form: str, sense_evidence: str,
) -> tuple[int, int, int] | None:
    """Pin a repeated surface form through its exact, unique evidence span.

    Only an evidence string found exactly once in the source, containing the
    surface form exactly once, identifies the occurrence; anything else stays
    ambiguous. Returns the verified span and its one-based ordinal.
    """
    if not sense_evidence or not surface_form:
        return None
    evidence_starts = _exact_match_starts(source_text, sense_evidence)
    inner_starts = _exact_match_starts(sense_evidence, surface_form)
    if len(evidence_starts) != 1 or len(inner_starts) != 1:
        return None
    start = evidence_starts[0] + inner_starts[0]
    try:
        span = resolve_occurrence_span(
            source_text, surface_form, start_codepoint=start, end_codepoint=start + len(surface_form),
        )
    except OccurrenceSpanError:
        return None
    return span[0], span[1], _exact_match_starts(source_text, surface_form).index(span[0]) + 1
