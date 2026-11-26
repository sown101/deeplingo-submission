"""Look up any word or phrase a learner taps or selects in an owned video's transcript.

Read-only: nothing is written and no learner state changes. The server derives the text from
the trusted segment and the learner's span. Meanings come from the dictionary: the entry
of the longest dictionary unit containing the selection supplies the senses, the model only
chooses one offered `sense_id` and renders it in the support language. Without an entry the
meaning is marked `ai_unverified`; when the model is unavailable the dictionary gloss is
still returned (`dictionary_only`).
"""
from __future__ import annotations

import logging
from typing import Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.modules.content.application.knowledge_resolution import normalize_reference_text
from app.modules.content.application.library import LearnerLibraryError
from app.modules.content.application.prompts import WORD_LOOKUP_PROMPT_VERSION, build_word_lookup_prompt
from app.modules.content.domain.dictionary_sources import DICTIONARY_SOURCES
from app.modules.content.domain.knowledge import DictionaryEntry
from app.modules.content.domain.word_lookup import (
    LookupSpanError,
    Window,
    candidate_windows,
    is_unspaced,
    snap_selection,
)
from app.platform.llm.port import LLMProvider, LLMProviderError
from app.platform.llm.usage import usage_scope

logger = logging.getLogger(__name__)

MAX_OFFERED_SENSES = 15
LANGUAGE_NAMES = {"en": "English", "zh": "Chinese", "vi": "Vietnamese", "ja": "Japanese", "ko": "Korean"}


class WordLookupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    segment_id: UUID
    start_codepoint: int = Field(ge=0)
    end_codepoint: int = Field(gt=0)


class LookupExample(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=200)
    translation: str = Field(min_length=1, max_length=240)


class LookupSenseOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sense_id: str | None = Field(max_length=80)
    meaning: str = Field(min_length=1, max_length=160)
    note: str | None = Field(default=None, max_length=240)
    pattern: list[str] = Field(default_factory=list, max_length=6)
    pattern_explanation: str | None = Field(default=None, max_length=400)
    examples: list[LookupExample] = Field(default_factory=list, max_length=2)


class LookupSourceView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    license_name: str
    license_url: str
    entry_url: str


class WordLookupView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    segment_id: UUID
    selection_start: int
    selection_end: int
    unit_start: int
    unit_end: int
    unit_text: str
    unit_kind: Literal["word", "phrase"]
    selection_is_part: bool
    headword: str | None
    reading: str | None
    part_of_speech: str | None
    dictionary_gloss: str | None
    sense_id: str | None
    meaning: str | None
    note: str | None
    # Explanation written by the model for this sentence; empty when the model gave none.
    pattern: list[str] = Field(default_factory=list)
    pattern_explanation: str | None = None
    examples: list[LookupExample] = Field(default_factory=list)
    context_before: str | None = None
    context_after: str | None = None
    meaning_provenance: Literal["translated_from_sense", "ai_unverified", "dictionary_only", "unavailable"]
    level: str | None
    source: LookupSourceView | None


class LookupDictionary(Protocol):
    def list_by_headwords(self, *, language_code: str, normalized_headwords: list[str]) -> list[DictionaryEntry]: ...


class WordLookupService:
    def __init__(self, *, library, videos, transcripts, segments, preferences, dictionary: LookupDictionary,
                 provider: LLMProvider, translations=None):
        self.library = library
        self.videos = videos
        self.transcripts = transcripts
        self.segments = segments
        self.preferences = preferences
        self.dictionary = dictionary
        self.provider = provider
        # M1 S7d: a sense rendered in the support language is stored once for Quick review.
        self.translations = translations

    def save_translations(self, rows: list[dict]) -> None:
        """Best effort: a failed write never fails a lookup or a search."""
        if self.translations is None or not rows:
            return
        try:
            self.translations.save(rows)
        except Exception as exc:
            logger.warning("sense translations not stored error=%s", type(exc).__name__)

    def lookup(self, user, library_item_id: UUID, request: WordLookupRequest) -> WordLookupView:
        video, segment, language = self.owned_segment(user, library_item_id, request.segment_id)
        try:
            start, end = snap_selection(segment.text, request.start_codepoint, request.end_codepoint, language)
        except LookupSpanError as exc:
            raise LearnerLibraryError("Select a word in this sentence.", status_code=422, code=str(exc)) from exc
        window, entries = self.best_unit(segment.text, start, end, language)
        profile = self.preferences.get_by_language_for_user(user_id=user.id, language_code=language)
        support = profile.support_language_code if profile else "vi"
        offered: dict[str, tuple[dict, DictionaryEntry]] = {}
        for item in entries:
            for sense in real_senses(item):
                offered.setdefault(sense["sense_id"], (sense, item))
        pairs = list(offered.values())[:MAX_OFFERED_SENSES]
        senses = [sense for sense, _ in pairs]
        before, after = self._neighbours(segment)
        with usage_scope("lookup", library_item_id):  # M1 S7: cost per session
            output = self._choose_sense(language, support, segment.text, window.text, senses, before, after)

        chosen_pair = next((pair for pair in pairs if output and pair[0]["sense_id"] == output.sense_id), None)
        if chosen_pair is not None and chosen_pair[1].id is not None and not _is_english(support):
            self.save_translations([{
                "dictionary_entry_id": chosen_pair[1].id, "sense_id": chosen_pair[0]["sense_id"],
                "support_language_code": support, "language_code": language,
                "headword": chosen_pair[1].headword, "part_of_speech": chosen_pair[0].get("pos"),
                "meaning": " ".join(output.meaning.split()), "origin": "lookup",
                "prompt_version": WORD_LOOKUP_PROMPT_VERSION,
            }])
        if output is None:
            provenance = "dictionary_only" if senses else "unavailable"
        else:
            provenance = "translated_from_sense" if chosen_pair else "ai_unverified"
        shown_pair = chosen_pair or (pairs[0] if pairs and output is None else None)
        chosen = chosen_pair[0] if chosen_pair else None
        shown = shown_pair[0] if shown_pair else None
        entry = shown_pair[1] if shown_pair else (entries[0] if entries else None)
        source = DICTIONARY_SOURCES.get(entry.provider or "") if entry and shown else None
        unspaced = is_unspaced(language)
        return WordLookupView(
            segment_id=segment.id, selection_start=start, selection_end=end,
            unit_start=window.start, unit_end=window.end, unit_text=segment.text[window.start:window.end],
            unit_kind="phrase" if not unspaced and window.size > 1 else "word",
            selection_is_part=(window.start, window.end) != (start, end),
            headword=entry.headword if entry else None,
            reading=(shown or {}).get("reading") if unspaced else None,
            part_of_speech=(shown or {}).get("pos"),
            # Dictionary text is shown only with its licence credit.
            dictionary_gloss=(shown or {}).get("text") if source else None,
            sense_id=chosen["sense_id"] if chosen else None,
            meaning=output.meaning if output else None,
            note=output.note if output else None,
            pattern=[part.strip()[:40] for part in output.pattern if part.strip()][:5] if output else [],
            pattern_explanation=output.pattern_explanation if output and output.pattern else None,
            examples=output.examples if output else [],
            context_before=before, context_after=after,
            meaning_provenance=provenance,
            level=_level(entry, language),
            source=LookupSourceView(name=source.name, license_name=source.license_name,
                                    license_url=source.license_url, entry_url=source.entry_url(entry.headword))
            if source else None,
        )

    def owned_segment(self, user, library_item_id: UUID, segment_id: UUID):
        association = self.library.get_for_user(library_item_id=library_item_id, user_id=user.id)
        video = self.videos.get_by_id(association.video_id) if association else None
        segment = self.segments.get_by_id(segment_id) if video else None
        transcript = self.transcripts.get_by_id(segment.transcript_id) if segment else None
        if video is None or segment is None or transcript is None or transcript.video_id != video.id:
            # The same answer for another learner's video and for a missing one.
            raise LearnerLibraryError("Library item not found.", status_code=404, code="library_item_not_found")
        return video, segment, transcript.language_code

    def best_unit(self, text: str, start: int, end: int, language: str) -> tuple[Window, list[DictionaryEntry]]:
        """The longest window with a dictionary meaning, with its entries.

        A phrase has one entry. A single word has its own entry and, when it is an inflected
        form ("putting"), the base form's entry ("put"), so both sets of senses are offered.
        """
        windows = candidate_windows(text, start, end, language)
        keys = {window: normalize_reference_text(window.text, language_code=language) for window in windows}
        # Every word of every window is looked up too, so an inflected neighbour ("gave" in
        # "gave up" when "up" is selected) can be reduced to its lemma.
        words = [normalize_reference_text(token.text, language_code=language)
                 for window in windows for token in window.tokens]
        found = self._entries(language, [*keys.values(), *words])
        lemma_keys = {}
        if not is_unspaced(language):
            lemmas = {token.text: _base_form(found.get(normalize_reference_text(token.text, language_code=language)))
                      for window in windows for token in window.tokens}
            for window in windows:
                variants = []
                for index, token in enumerate(window.tokens):
                    lemma = lemmas.get(token.text)
                    if lemma:
                        words = [item.text for item in window.tokens]
                        words[index] = lemma
                        variants.append(" ".join(words))
                if window.size == 3:
                    # A separable phrasal verb: "putting it off" -> "put off".
                    first, last = window.tokens[0].text, window.tokens[-1].text
                    variants += [f"{first} {last}", f"{lemmas.get(first) or first} {last}"]
                lemma_keys[window] = [normalize_reference_text(variant, language_code=language)
                                      for variant in dict.fromkeys(variants)]
            missing = [key for values in lemma_keys.values() for key in values if key not in found]
            found.update(self._entries(language, missing))
        for window in windows:
            entries = []
            for key in [keys[window], *lemma_keys.get(window, [])]:
                entry = found.get(key)
                if entry is None or not real_senses(entry) or entry in entries:
                    continue
                if window.size > 1 and _is_sum_of_parts(entry):
                    continue  # "cup of coffee": the words carry the meaning
                entries.append(entry)
                if window.size > 1:
                    break  # a phrase is one entry; a word also offers its base form's senses
            if entries:
                return window, entries
        selection = next(window for window in windows if (window.start, window.end) == (start, end))
        return selection, []

    def _entries(self, language: str, keys: list[str]) -> dict[str, DictionaryEntry]:
        unique = [key for key in dict.fromkeys(keys) if key]
        if not unique:
            return {}
        return {entry.normalized_headword: entry
                for entry in self.dictionary.list_by_headwords(language_code=language, normalized_headwords=unique)}

    def _neighbours(self, segment) -> tuple[str | None, str | None]:
        """The subtitles just before and after, so a phrase is read in its context. Best effort."""
        neighbour = getattr(self.segments, "get_neighbor", None)
        sequence = getattr(segment, "sequence_number", None)
        if neighbour is None or sequence is None:
            return None, None
        try:
            found = [neighbour(transcript_id=segment.transcript_id, sequence_number=sequence, offset=offset)
                     for offset in (-1, 1)]
        except Exception as exc:
            logger.warning("lookup context unavailable error=%s", type(exc).__name__)
            return None, None
        return tuple(item.text if item else None for item in found)  # type: ignore[return-value]

    def _choose_sense(self, language: str, support: str, sentence: str, unit: str,
                      senses: list[dict], before: str | None = None, after: str | None = None) -> LookupSenseOutput | None:
        prompt = build_word_lookup_prompt(
            source_language=LANGUAGE_NAMES.get(language, language),
            support_language=LANGUAGE_NAMES.get(support, support),
            sentence=sentence, unit_text=unit,
            senses=[(sense["sense_id"], _sense_label(sense)) for sense in senses],
            before=before, after=after,
        )
        offered = {sense["sense_id"] for sense in senses}
        for _ in range(2):
            try:
                output = self.provider.generate_structured(prompt, LookupSenseOutput)
            except (LLMProviderError, ValidationError) as exc:
                logger.warning("word lookup model unavailable prompt=%s error=%s",
                               WORD_LOOKUP_PROMPT_VERSION, type(exc).__name__)
                return None
            if output.sense_id is None or output.sense_id in offered:
                return output
            logger.warning("word lookup returned an unoffered sense prompt=%s", WORD_LOOKUP_PROMPT_VERSION)
        return None


def _is_english(language_code: str | None) -> bool:
    return (language_code or "").strip().casefold().split("-")[0] == "en"


def real_senses(entry: DictionaryEntry | None) -> list[dict]:
    if entry is None:
        return []
    return [sense for sense in entry.definitions
            if isinstance(sense, dict) and sense.get("sense_id") and sense.get("text") and not sense.get("form_of")
            and not str(sense["text"]).startswith(_LITERAL_SENSE)]


# Wiktionary keeps sum-of-parts entries ("cup of coffee") whose only sense points back to the
# words; such a phrase is not a dictionary unit, so the lookup falls back to the word.
_LITERAL_SENSE = "Used other than figuratively or idiomatically"


def _base_form(entry: DictionaryEntry | None) -> str | None:
    """The base form named by any inflection sense ("putting" -> "put"), for building phrases only."""
    if entry is None:
        return None
    for sense in entry.definitions:
        if isinstance(sense, dict):
            forms = [word for word in sense.get("form_of") or [] if isinstance(word, str)]
            if forms:
                return forms[0]
    return None


def _is_sum_of_parts(entry: DictionaryEntry) -> bool:
    return any(isinstance(sense, dict) and str(sense.get("text", "")).startswith(_LITERAL_SENSE)
               for sense in entry.definitions)


def _sense_label(sense: dict) -> str:
    parts = [f"({sense['pos']})" if sense.get("pos") else "", f"[{sense['reading']}]" if sense.get("reading") else "",
             sense["text"]]
    return " ".join(part for part in parts if part)


def _level(entry: DictionaryEntry | None, language: str) -> str | None:
    if entry is None:
        return None
    metadata = entry.provider_metadata or {}
    value = metadata.get("hsk") if is_unspaced(language) else metadata.get("cefr_j")
    return value if isinstance(value, str) else None
