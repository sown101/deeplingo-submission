"""Grammar selection pass (`grammar_selection_v1`).

After vocabulary extraction, each segment is asked one narrow question: which curriculum
grammar points does it use? The model reads the previous and next segment to reconstruct
sentences that subtitles split, and must mark a use `split` when it continues outside the
target segment. The server also refuses a use whose span touches a segment boundary that is
not a sentence end, so a fragment never becomes a grammar occurrence. When a grammar point
lists closed-class `forms` (pronouns, 是, am/is/are ...), the span must contain one of them, so
a name is never taken for a pronoun. Every kept use is an exact span of the target segment, as
for any LearningObject.
"""
from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass, field

from pydantic import ValidationError

from app.modules.content.application.prompts import build_grammar_selection_prompt
from app.modules.content.application.store_ports import GrammarCatalogueStore
from app.modules.content.domain.extraction import (
    Candidate,
    CandidateType,
    GrammarCatalogueItem,
    GrammarSpanStatus,
    LLMGrammarResponse,
    LLMGrammarUse,
)
from app.modules.content.domain.catalog import TranscriptSegment
from app.modules.content.domain.occurrence_spans import OccurrenceSpanError, resolve_occurrence_span
from app.platform.llm.port import LLMProvider, LLMProviderError

logger = logging.getLogger(__name__)

DEFAULT_MAX_GRAMMAR_USES = 3
SENTENCE_END = set(".!?。！？…")
CLOSING = set("\"'”’）)」』】]")
UNSPACED_LANGUAGES = {"zh", "ja", "th"}


class GrammarUseRejected(ValueError):
    pass


@dataclass
class GrammarSelection:
    candidates: list[Candidate] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    split_skipped: int = 0
    form_mismatch_skipped: int = 0
    failed_closed: bool = False


class GrammarSelectionService:
    def __init__(self, *, provider: LLMProvider, catalogue: GrammarCatalogueStore,
                 max_uses: int = DEFAULT_MAX_GRAMMAR_USES, max_retries: int = 0, propagate_failures: bool = False):
        self.provider = provider
        self.catalogue = catalogue
        self.max_uses = max_uses
        self.max_retries = max_retries
        self.propagate_failures = propagate_failures
        self._catalogues: dict[str, list[GrammarCatalogueItem]] = {}

    def select(self, *, segment: TranscriptSegment, source_language: str,
               previous_context: str | None = None, next_context: str | None = None) -> GrammarSelection:
        catalogue = self._catalogue(source_language)
        if not catalogue:
            return GrammarSelection()
        prompt = build_grammar_selection_prompt(
            source_language=source_language, transcript_text=segment.text, catalogue=catalogue,
            max_uses=self.max_uses, previous_context=previous_context, next_context=next_context,
        )
        response, errors = None, []
        for attempt in range(1, max(self.max_retries, 0) + 2):
            try:
                response = self.provider.generate_structured(prompt, LLMGrammarResponse)
                break
            except (LLMProviderError, ValidationError) as exc:
                if self.propagate_failures:
                    raise
                errors.append(type(exc).__name__)
                logger.warning("grammar selection attempt failed segment_id=%s attempt=%s", segment.id, attempt)
        if response is None:
            return GrammarSelection(errors=errors, failed_closed=True)
        if len(response.uses) > self.max_uses:
            return GrammarSelection(errors=[*errors, "Grammar use count exceeded limit"], failed_closed=True)

        by_key = {item.key: item for item in catalogue}
        selection = GrammarSelection(errors=errors)
        seen: set[str] = set()
        for use in response.uses:
            if use.grammar_key in seen:
                continue
            if use.span_status == GrammarSpanStatus.SPLIT:
                selection.split_skipped += 1
                continue
            try:
                grammar = by_key.get(use.grammar_key)
                if grammar is None:
                    raise GrammarUseRejected("Grammar use names a grammar key that was not offered")
                spaced = source_language not in UNSPACED_LANGUAGES
                start, end, ordinal = _ground(segment.text, use, spaced=spaced)
                if grammar.forms and not uses_form(use.surface_form, grammar.forms, spaced=spaced):
                    selection.form_mismatch_skipped += 1
                    continue
                if touches_open_boundary(segment.text, start, end, previous_context, next_context):
                    selection.split_skipped += 1
                    continue
            except GrammarUseRejected as exc:
                selection.errors.append(str(exc))
                continue
            seen.add(use.grammar_key)
            selection.candidates.append(Candidate(
                surface_form=use.surface_form,
                normalized_form=grammar.pattern,
                sense_gloss=grammar.pattern,
                sense_evidence=" ".join(use.sense_evidence.split()),
                candidate_type=CandidateType.GRAMMAR_PATTERN,
                evidence_start=start,
                evidence_end=end,
                surface_occurrence_index=ordinal,
                source_segment_id=segment.id,
                confidence=use.confidence,
                grammar_key=grammar.key,
                grammar_label=grammar.title,
            ))
        return selection

    def _catalogue(self, language_code: str) -> list[GrammarCatalogueItem]:
        if language_code not in self._catalogues:
            self._catalogues[language_code] = list(self.catalogue.catalogue_for_language(language_code))
        return self._catalogues[language_code]


def _surface_start(text: str, surface: str, lo: int, hi: int, *, spaced: bool) -> int:
    """First start of `surface` inside text[lo:hi]; in spaced languages never inside a longer word."""
    if not spaced:
        return text.find(surface, lo, hi)
    before = r"(?<!\w)" if re.match(r"\w", surface[:1]) else ""
    after = r"(?!\w)" if re.match(r"\w", surface[-1:]) else ""
    for match in re.finditer(before + re.escape(surface) + after, text):
        if lo <= match.start() and match.end() <= hi:
            return match.start()
    return -1


def _ground(text: str, use: LLMGrammarUse, *, spaced: bool) -> tuple[int, int, int | None]:
    """The surface is located through its evidence, both copied exactly from the target segment."""
    evidence = use.sense_evidence
    if use.surface_form not in evidence:
        raise GrammarUseRejected("Grammar evidence does not contain its surface form")
    evidence_start = text.find(evidence)
    if evidence_start < 0 or text.find(evidence, evidence_start + 1) >= 0:
        raise GrammarUseRejected("Grammar evidence is not uniquely grounded in the target segment")
    start = _surface_start(text, use.surface_form, evidence_start, evidence_start + len(evidence), spaced=spaced)
    if start < 0:
        raise GrammarUseRejected("Grammar surface form is not a whole word in its evidence")
    end = start + len(use.surface_form)
    ordinal = text[:start].count(use.surface_form) + 1
    try:
        resolved = resolve_occurrence_span(text, use.surface_form, occurrence_ordinal=ordinal)
    except OccurrenceSpanError as exc:
        raise GrammarUseRejected("Grammar surface form is not grounded in the target segment") from exc
    if resolved != (start, end):
        raise GrammarUseRejected("Grammar surface form is not grounded in the target segment")
    return start, end, ordinal if text.count(use.surface_form) > 1 else None


def uses_form(surface: str, forms: tuple[str, ...], *, spaced: bool) -> bool:
    """The span contains one listed form; in spaced languages as a whole word (case ignored)."""
    text = surface.casefold()
    for form in forms:
        needle = form.casefold()
        if not spaced:
            if needle in text:
                return True
            continue
        before = "" if needle[:1] in "'’" else r"(?<![\w'’])"
        if re.search(before + re.escape(needle) + r"(?![\w])", text):
            return True
    return False


def touches_open_boundary(text: str, start: int, end: int, previous: str | None, following: str | None) -> bool:
    """A span reaching a segment edge that is not a sentence boundary may be part of a split sentence."""
    if following is not None and not _has_word(text[end:]) and not _ends_sentence(text):
        return True
    if previous is not None and not _has_word(text[:start]) and not _ends_sentence(previous):
        return True
    return False


def _has_word(value: str) -> bool:
    return any(unicodedata.category(character)[0] in "LN" for character in value)


def _ends_sentence(value: str) -> bool:
    stripped = value.rstrip()
    while stripped and stripped[-1] in CLOSING:
        stripped = stripped[:-1].rstrip()
    return bool(stripped) and stripped[-1] in SENTENCE_END
