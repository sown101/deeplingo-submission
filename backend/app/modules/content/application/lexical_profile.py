"""The cached word profile of a video transcript (L1c) and the learner-owned Library path to it.

Building reads the stored segments and the dictionary in batches (never the network, never an LLM) and
counts dictionary words (lemmas) with their level label. The result is stored once per transcript and
is the same for every learner; a learner's own coverage is computed elsewhere from these rows.
"""
from __future__ import annotations

import hashlib
import json
import logging
from collections import defaultdict
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from app.modules.content.application.knowledge_resolution import normalize_reference_text
from app.modules.content.application.library import LearnerLibraryError
from app.modules.content.application.playback import original_track, owned_ready_video, select_original_track
from app.modules.content.application.word_lookup import real_senses
from app.modules.content.domain.knowledge import DictionaryEntry
from app.modules.content.domain.lexical_profile import (
    PROFILE_VERSION,
    candidate_cjk_words,
    cjk_runs,
    cut_cjk_run,
    derive_compound_level,
    spaced_words,
    spoken_milliseconds,
)
from app.modules.content.domain.word_lookup import is_unspaced

logger = logging.getLogger(__name__)

SUPPORTED_LANGUAGES = frozenset({"en", "zh"})
LOOKUP_BATCH = 100
MAX_CJK_LOOKUP_KEYS = 12_000  # about 120 reads; longer pieces are dropped first on a very long video


@dataclass(frozen=True)
class Lexeme:
    lexeme: str
    level: str | None
    matched: bool
    occurrences: int
    level_derived: bool = False  # the level was inferred from the characters, not named by the dictionary


@dataclass(frozen=True)
class StoredProfile:
    transcript_id: UUID
    language_code: str
    version: int
    token_count: int
    proper_noun_count: int
    speech_ms: int
    source_hash: str | None = None


@dataclass(frozen=True)
class LexicalProfile:
    profile: StoredProfile
    lexemes: list[Lexeme]


class ProfileStore(Protocol):
    def get(self, transcript_id: UUID) -> StoredProfile | None: ...

    def get_many(self, transcript_ids: list[UUID]) -> dict[UUID, StoredProfile]: ...

    def lexemes(self, transcript_id: UUID) -> list[Lexeme]: ...

    def lexemes_for_many(self, transcript_ids: list[UUID]) -> dict[UUID, list[Lexeme]]: ...

    def replace(self, profile: StoredProfile, lexemes: list[Lexeme]) -> None: ...


class SegmentTexts(Protocol):
    def spans_and_texts(self, transcript_id: UUID) -> list[tuple[int, int, str]]: ...

    def spans_and_texts_for_many(self, transcript_ids: list[UUID]) -> dict[UUID, list[tuple[int, int, str]]]: ...


class ProfileDictionary(Protocol):
    def list_by_headwords(self, *, language_code: str, normalized_headwords: list[str]) -> list[DictionaryEntry]: ...


class LexicalProfileService:
    def __init__(self, *, store: ProfileStore, segments: SegmentTexts, dictionary: ProfileDictionary):
        self.store = store
        self.segments = segments
        self.dictionary = dictionary

    def cached(self, transcript_id: UUID) -> LexicalProfile | None:
        stored = self.store.get(transcript_id)
        if stored is None or stored.version != PROFILE_VERSION or stored.source_hash is None:
            return None
        rows = self.segments.spans_and_texts(transcript_id)
        if stored.source_hash != _source_hash(rows):
            return None
        return LexicalProfile(stored, self.store.lexemes(transcript_id))

    def cached_many(self, transcript_ids: list[UUID]) -> dict[UUID, LexicalProfile]:
        # Keep a bounded set of transcripts in each segment and lexeme read.
        ids = list(dict.fromkeys(transcript_ids))
        profiles: dict[UUID, LexicalProfile] = {}
        batch_size = 10
        for start in range(0, len(ids), batch_size):
            stored = {key: value for key, value in self.store.get_many(ids[start:start + batch_size]).items()
                      if value.version == PROFILE_VERSION and value.source_hash is not None}
            segments = self.segments.spans_and_texts_for_many(list(stored))
            fresh = {key: value for key, value in stored.items()
                     if value.source_hash == _source_hash(segments.get(key, []))}
            lexemes = self.store.lexemes_for_many(list(fresh))
            profiles.update({key: LexicalProfile(value, lexemes.get(key, [])) for key, value in fresh.items()})
        return profiles

    def get_or_build(self, transcript_id: UUID, language_code: str) -> LexicalProfile | None:
        """None when the language is not supported or the transcript has no words."""
        language = (language_code or "").casefold().split("-")[0]
        if language not in SUPPORTED_LANGUAGES:
            return None
        found = self.cached(transcript_id)
        if found is not None and found.profile.language_code == language:
            return found
        built = self.build(transcript_id, language)
        if built is not None:
            self.store.replace(built.profile, built.lexemes)
        return built

    def build(self, transcript_id: UUID, language: str) -> LexicalProfile | None:
        rows = self.segments.spans_and_texts(transcript_id)
        if not rows:
            return None
        speech_ms = spoken_milliseconds([(start, end) for start, end, _ in rows])
        texts = [text for _, _, text in rows]
        counts, proper = (self._count_unspaced(texts, language) if is_unspaced(language)
                          else self._count_spaced(texts, language))
        lexemes = [Lexeme(lexeme, level, matched, occurrences, derived)
                   for (lexeme, level, matched, derived), occurrences in sorted(
                       counts.items(), key=lambda item: (-item[1], item[0][0]))]
        if not lexemes:
            return None
        profile = StoredProfile(transcript_id, language, PROFILE_VERSION, sum(item.occurrences for item in lexemes),
                                proper, speech_ms, _source_hash(rows))
        return LexicalProfile(profile, lexemes)

    # --- English-like text -------------------------------------------------------

    def _count_spaced(self, texts: list[str], language: str) -> tuple[dict[tuple, int], int]:
        forms: list[str] = []
        proper = 0
        for text in texts:
            words = spaced_words(text)
            proper += words.proper_nouns
            forms.extend(token.form for token in words.tokens)
        keys = {form: normalize_reference_text(form, language_code=language) for form in set(forms)}
        found = self._entries(language, list(keys.values()))
        # An inflected form ("went") has no sense of its own; its base form ("go") carries the level.
        base_names = {base for entries in found.values()
                      if not any(real_senses(entry) for entry in entries) or _best_level(entries) is None
                      for entry in entries for base in _base_forms(entry)}
        base_keys = {normalize_reference_text(base, language_code=language) for base in base_names}
        bases = self._entries(language, sorted(base_keys - set(found)))
        resolved = {form: (*self._resolve(key, found, bases, language), False) for form, key in keys.items()}
        counts: dict[tuple, int] = defaultdict(int)
        for form in forms:
            counts[resolved[form]] += 1
        return counts, proper

    def _resolve(self, key: str, found: dict, bases: dict, language: str) -> tuple[str, str | None, bool]:
        entries = found.get(key)
        if not entries:
            return key, None, False
        if any(real_senses(entry) for entry in entries) and _best_level(entries) is not None:
            return key, _best_level(entries), True
        # No level of its own: an inflection ("going", "got") counts as its base form ("go", "get") when the
        # dictionary names one that has a level; a form with its own senses and no base stays as it is.
        for entry in entries:
            for base in _base_forms(entry):
                base_key = normalize_reference_text(base, language_code=language)
                base_entries = found.get(base_key) or bases.get(base_key)
                if base_entries and _best_level(base_entries) is not None:
                    return base_key, _best_level(base_entries), True
        if any(real_senses(entry) for entry in entries):
            return key, None, True
        for entry in entries:
            for base in _base_forms(entry):
                base_key = normalize_reference_text(base, language_code=language)
                base_entries = found.get(base_key) or bases.get(base_key)
                if base_entries:
                    return base_key, _best_level(base_entries) or _best_level(entries), True
        return key, _best_level(entries), True

    # --- Chinese text --------------------------------------------------------------

    def _count_unspaced(self, texts: list[str], language: str) -> tuple[dict[tuple, int], int]:
        runs = [run for text in texts for run in cjk_runs(text)]
        pieces = sorted(candidate_cjk_words(runs), key=lambda piece: (len(piece), piece))[:MAX_CJK_LOOKUP_KEYS]
        found = self._entries(language, [normalize_reference_text(piece, language_code=language) for piece in pieces])
        known = {key for key, entries in found.items() if any(real_senses(entry) for entry in entries)}
        char_levels = {character: _best_level(found.get(normalize_reference_text(character, language_code=language)))
                       for character in {character for run in runs for character in run}}
        counts: dict[tuple, int] = defaultdict(int)
        for run in runs:
            for word in cut_cjk_run(run, known):
                entries = found.get(normalize_reference_text(word, language_code=language))
                matched = bool(entries) and any(real_senses(entry) for entry in entries)
                level = _best_level(entries) if matched else None
                derived = False
                if matched and level is None:
                    level = derive_compound_level(word, char_levels)
                    derived = level is not None
                counts[(word, level, matched, derived)] += 1
        return counts, 0

    def _entries(self, language: str, keys: list[str]) -> dict[str, list[DictionaryEntry]]:
        unique = [key for key in dict.fromkeys(keys) if key]
        grouped: dict[str, list[DictionaryEntry]] = defaultdict(list)
        for start in range(0, len(unique), LOOKUP_BATCH):
            for entry in self.dictionary.list_by_headwords(
                    language_code=language, normalized_headwords=unique[start:start + LOOKUP_BATCH]):
                grouped[entry.normalized_headword].append(entry)
        return grouped


def _source_hash(rows: list[tuple[int, int, str]]) -> str:
    """Exact text, segment order and timings; no raw transcript is added to the cache row."""
    source = json.dumps(rows, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(source).hexdigest()


def _base_forms(entry: DictionaryEntry) -> list[str]:
    return [word for sense in entry.definitions if isinstance(sense, dict)
            for word in sense.get("form_of") or [] if isinstance(word, str)]


def _entry_level(entry: DictionaryEntry) -> str | None:
    metadata = entry.provider_metadata or {}
    value = metadata.get("hsk") or metadata.get("cefr_j")
    return value.strip().upper() if isinstance(value, str) and value.strip() else None


def _best_level(entries: list[DictionaryEntry] | None) -> str | None:
    """The level of a word that has several entries (noun and verb): the lowest one named."""
    levels = sorted({level for entry in entries or [] if (level := _entry_level(entry))})
    return levels[0] if levels else None


class LibraryLexicalProfiles:
    """A learner's own Library items and their profiles (404 for anyone else's video)."""

    def __init__(self, *, library, videos, transcripts, profiles: LexicalProfileService):
        self.library = library
        self.videos = videos
        self.transcripts = transcripts
        self.profiles = profiles

    def for_item(self, user, item_id: UUID) -> LexicalProfile:
        video = owned_ready_video(self.library, self.videos, user, item_id)
        track = original_track(self.transcripts, video)
        profile = self.profiles.get_or_build(track.id, track.language_code)
        if profile is None:
            raise LearnerLibraryError("No word profile for this video.", status_code=404, code="profile_unavailable")
        return profile

    def for_library(self, user, *, build_budget: int, limit: int = 50) -> list[tuple[UUID, LexicalProfile | None]]:
        """Profiles of the learner's ready videos. Missing ones are built, at most `build_budget` per call."""
        items = self.library.list_for_user(user.id, limit=limit)
        videos = self.videos.get_many_by_ids(list(dict.fromkeys(item.video_id for item in items)))
        ready = {key: video for key, video in videos.items()
                 if video.processing_status in {"transcript_ready", "learning_objects_ready"}}
        by_video = defaultdict(list)
        for track in self.transcripts.list_for_videos(list(ready)):
            by_video[track.video_id].append(track)
        originals = {}
        for video in ready.values():
            track = select_original_track(by_video[video.id], video.original_language_code)
            if track is not None and track.language_code.casefold().split("-")[0] in SUPPORTED_LANGUAGES:
                originals[video.id] = track
        cached = self.profiles.cached_many([track.id for track in originals.values()])

        result: list[tuple[UUID, LexicalProfile | None]] = []
        budget = build_budget
        for item in items:
            track = originals.get(item.video_id)
            if track is None:
                continue
            profile = cached.get(track.id)
            if profile is not None and profile.profile.language_code != track.language_code.casefold().split("-")[0]:
                profile = None
            if profile is None and budget > 0:
                budget -= 1
                try:
                    profile = self.profiles.get_or_build(track.id, track.language_code)
                except Exception:  # noqa: BLE001 - one video never blocks the list
                    logger.warning("lexical profile build failed for video %s", video.id, exc_info=True)
            result.append((item.id, profile))
        return result
