"""Ports the learner module consumes.

Each Protocol lists only the methods learner calls. bootstrap/wiring/learner.py
passes the concrete repositories, which satisfy them structurally.
"""
from __future__ import annotations

from typing import Protocol
from uuid import UUID

from app.modules.content.contracts import Concept, Language
from app.modules.identity.contracts import CurrentUser
from app.modules.learner.domain.models import Profile, UserLanguagePreference
from app.modules.learner.domain.video_coverage import VideoProfile
from app.modules.learner.domain.word_lists import SenseCandidate


# --- Learner-owned persistence ------------------------------------------------

class ProfileStore(Protocol):
    def get_by_user_id(self, user_id: UUID) -> Profile | None: ...

    def upsert_current_user(self, user_id: UUID, data: dict | None = None) -> Profile: ...


class LanguagePreferenceStore(Protocol):
    def list_for_user(self, user_id: UUID) -> list[UserLanguagePreference]: ...

    def get_for_user(self, preference_id: UUID, user_id: UUID) -> UserLanguagePreference | None: ...

    def get_by_language_for_user(self, *, user_id: UUID, language_code: str) -> UserLanguagePreference | None: ...

    def get_profile_for_user(self, user_id: UUID) -> UserLanguagePreference | None: ...

    def upsert_profile_for_user(
        self, *, user_id: UUID, learning_language: str, support_language: str, extra: dict | None = None,
    ) -> UserLanguagePreference: ...


# --- Content reads ------------------------------------------------------------

class ConceptListReader(Protocol):
    def list_by_ids(self, concept_ids: list) -> list[Concept]: ...


class ConceptReader(Protocol):
    def get_by_id(self, concept_id) -> Concept | None: ...


class LanguageReader(Protocol):
    def get_active(self, code: str) -> Language | None: ...


# --- Learner targets (L1a) -------------------------------------------------------

class TargetStore(Protocol):
    """The learner's targets: rows of `saved_concepts` with a lifecycle status (L1a)."""

    def list_for_user(self, user_id: UUID, *, language_code: str | None = None, status: str | None = None) -> list[dict]: ...

    def get(self, user_id: UUID, concept_id: UUID) -> dict | None: ...

    def concept_ids_for(self, user_id: UUID, concept_ids: list[UUID]) -> set[UUID]: ...

    def save(self, user_id: UUID, *, concept_id: UUID, save_source: str,
             source_learning_object_id: UUID | None = None, language_code: str | None = None,
             level_label: str | None = None, priority: int = 100, explicit: bool = True) -> dict: ...

    def set_status(self, user_id: UUID, *, concept_id: UUID, status: str, now,
                   only_from: str | None = None) -> dict | None: ...

    def count_activated_since(self, user_id: UUID, *, language_code: str, since) -> int: ...

    def set_rung(self, user_id: UUID, *, concept_id: UUID, rung: int) -> None: ...

    def remove(self, user_id: UUID, *, concept_id: UUID) -> bool: ...

    def update_personal(self, user_id: UUID, *, concept_id: UUID, fields: dict) -> dict | None: ...


class TargetEventStore(Protocol):
    def record(self, user_id: UUID, *, concept_id: UUID, kind: str, outcome: str, event_key: str, occurred_at,
               context_key: str | None = None, quote: str | None = None, error_type: str | None = None,
               judge: dict | None = None) -> None: ...

    def list_for_concept(self, user_id: UUID, concept_id: UUID) -> list[dict]: ...


# --- Named word lists and bulk import (L1b) --------------------------------------

class GroupStore(Protocol):
    def create(self, user_id: UUID, *, language_code: str, name: str, description: str | None) -> dict: ...

    def list_for_user(self, user_id: UUID, *, language_code: str | None = None) -> list[dict]: ...

    def get(self, user_id: UUID, group_id: UUID) -> dict | None: ...

    def delete(self, user_id: UUID, group_id: UUID) -> bool: ...


class GroupItemStore(Protocol):
    def add(self, group_id: UUID, saved_concept_id: UUID) -> bool: ...

    def saved_ids(self, group_id: UUID) -> list[UUID]: ...

    def remove(self, group_id: UUID, saved_concept_id: UUID) -> bool: ...

    def counts(self, group_ids: list[UUID]) -> dict[UUID, int]: ...


class ImportRowStore(Protocol):
    def add(self, group_id: UUID, user_id: UUID, *, position: int, raw_text: str, user_gloss: str | None,
            resolution: str, candidates: list[dict]) -> dict: ...

    def list(self, group_id: UUID) -> list[dict]: ...

    def get(self, group_id: UUID, row_id: UUID) -> dict | None: ...

    def delete(self, group_id: UUID, row_id: UUID) -> bool: ...

    def counts(self, group_ids: list[UUID]) -> dict[UUID, int]: ...

    def next_position(self, group_id: UUID) -> int: ...

    def raw_words(self, group_id: UUID) -> set[str]: ...


class HeadwordResolver(Protocol):
    """Dictionary meanings for typed words, found by the server (an inflected form also offers its base)."""

    def candidates_for(self, language_code: str, words: list[str]) -> dict[str, list[SenseCandidate]]: ...


class SenseConceptResolver(Protocol):
    def from_dictionary(self, *, language_code: str, entry_id: UUID, sense_id: str) -> Concept: ...


# --- Video coverage (L1c) -----------------------------------------------------------

class VideoProfileSource(Protocol):
    """The word profile of the learner's own Library videos (the content module owns building it)."""

    def for_item(self, user: CurrentUser, library_item_id: UUID) -> VideoProfile: ...

    def for_library(self, user: CurrentUser, *, build_budget: int) -> list[tuple[UUID, VideoProfile | None]]: ...


class KnownLexemes(Protocol):
    def known_among(self, user_id: UUID, language_code: str, lexemes: list[str]) -> set[str]:
        """Which of these words the learner has already recognised in practice (rung 1 or higher)."""
        ...
