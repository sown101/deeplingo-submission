"""Ports of the agent: the outside world it reads and speaks through. Implementations are chosen in bootstrap."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal, Protocol
from uuid import UUID, uuid4

from app.modules.learning.application.study_plan import PlanEdit

from app.modules.learning.domain.companion import (
    CompanionEntry,
    CompanionItem,
    RegionLine,
    StudyRegionContext,
)


@dataclass(frozen=True)
class SynthesizedSpeech:
    audio: bytes
    mime_type: str
    characters: int


class SpeechSynthesisUnavailable(Exception):
    """Synthesis failed; the turn is still shown as text."""


class SpeechSynthesizer(Protocol):
    provider_name: str

    def supports(self, language_code: str) -> bool: ...

    def synthesize(self, text: str, *, language_code: str) -> SynthesizedSpeech: ...


@dataclass(frozen=True)
class DictionarySense:
    text: str
    part_of_speech: str | None = None
    sense_id: str | None = None  # M1 S7d: identifies the sense when the word is recorded


@dataclass(frozen=True)
class DictionaryWord:
    """A dictionary entry (source of truth) with its attribution."""

    headword: str
    senses: tuple[DictionarySense, ...]
    source_name: str | None = None
    source_license: str | None = None
    source_url: str | None = None
    entry_id: UUID | None = None


class WordLookup(Protocol):
    """Read-only dictionary search for one word (content module data)."""

    def lookup(self, word: str, *, language_code: str) -> list[DictionaryWord]: ...


class ConversationFollowUps(Protocol):
    """Next steps added to the learner's plan for ``day`` when a conversation ends."""

    def after_conversation(self, user, day, *, library_item_id: UUID | None) -> list: ...


class StudyRegionReader(Protocol):
    """M1 S3: the learner's saved study region of an owned Library video (content module data).

    Returns None when there is no region or it no longer matches the current transcript.
    Each line carries its segment ID, used to offer the items that occur in the region.
    """

    def for_learner(self, user_id: UUID, library_item_id: UUID) -> StudyRegionContext | None: ...


class DueConceptReader(Protocol):
    """Read-only: Concept IDs currently due for review for this learner (review module data)."""

    def due_concept_ids(self, user_id: UUID, *, language_code: str, limit: int) -> list[str]: ...


@dataclass(frozen=True)
class CompanionTicket:
    """The server-built context of one conversation, fixed when it starts (both channels).

    What changes from turn to turn is the session's (`AgentSession`); the text channel keeps it in a
    `SessionStore` between requests. The name stays from when this context travelled in a signed ticket.
    """

    user_id: UUID
    language_code: str
    support_language_code: str
    entry: CompanionEntry
    library_item_id: UUID | None
    topic: str
    items: tuple[CompanionItem, ...]
    # Server-built excerpt of the learner's own video, kept with the conversation so a turn does
    # not re-read the transcript; ownership of the video is still rechecked every turn.
    excerpt: str | None = None
    # M1 S3: the study-region lines the excerpt shows, so a practice suggestion can be checked
    # against them (by ref) without re-reading the transcript.
    region_lines: tuple[RegionLine, ...] = ()
    session_id: UUID = field(default_factory=uuid4)
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    scenario_id: str | None = None
    swap_roles: bool = False
    # The study region in use (`<first segment>_<last segment>`), so the agent can read the learner's results in it.
    region_id: str | None = None


@dataclass(frozen=True)
class SessionToken:
    """What the client's opaque `session_ticket` says: which conversation, whose, and which turn of it (`token_id`,
    single use), until when. Everything else about the conversation is on the server."""

    conversation_id: UUID
    user_id: UUID
    token_id: str
    expires_at: datetime


class InvalidCompanionTicket(Exception):
    pass


class CompanionTicketCodec(Protocol):
    def issue(self, conversation_id: UUID, user_id: UUID, *, started_at: datetime) -> tuple[str, SessionToken]:
        """A new signed reference to the conversation; it expires with the conversation."""
        ...

    def read(self, token: str) -> SessionToken:
        """Raises InvalidCompanionTicket for a forged, malformed or expired token."""
        ...


class SessionStoreUnavailable(Exception):
    """The conversation store could not be read or written. Never a reason to start a new conversation silently."""


class SessionStore(Protocol):
    """Server-side state of a text conversation, keyed by conversation id and learner id; values are JSON-ready dicts.

    Every value has a time-to-live. Failures raise SessionStoreUnavailable; values are never logged.
    """

    def get(self, conversation_id: UUID, user_id: UUID) -> dict | None: ...

    def put(self, conversation_id: UUID, user_id: UUID, state: dict, *, ttl_seconds: int) -> None: ...

    def delete(self, conversation_id: UUID, user_id: UUID) -> None: ...

    def claim(self, conversation_id: UUID, user_id: UUID, token_id: str, *, ttl_seconds: int) -> bool:
        """Atomically mark one token of the conversation used; False when it was already used (a replayed turn)."""
        ...

    def release(self, conversation_id: UUID, user_id: UUID, token_id: str) -> None:
        """Undo a claim whose turn failed, so the same token may be used again."""
        ...


class AgentFacts(Protocol):
    """Everything the agent may read about the learner who is talking, and the study requests it may create.

    Every call names that learner and one language; every list is capped by the caller. Any failure is
    the app's, never the learner's: the core treats it as "nothing found".
    """

    def profile_brief(self, user_id: UUID, language_code: str) -> str:
        """Counts and closed codes only (declared level, words by usage rung, signals); empty when unknown."""
        ...

    def declared_level(self, user_id: UUID, language_code: str) -> str | None:
        """The level the learner declared for this language (CEFR or HSK label), or None."""
        ...

    def recent_activity(self, user_id: UUID, language_code: str, *, kind: str | None, since: datetime | None,
                        limit: int) -> list[dict]:
        """Newest first: {kind, outcome, score, item, when, source}; `item` names a word or grammar point."""
        ...

    def region_activity(self, user_id: UUID, region_id: str, *, limit: int) -> list[dict]:
        """The learner's own rows of one study region, newest first, in the same short form."""
        ...

    def due_counts(self, user_id: UUID) -> dict[str, int]:
        """Words due for review now, per language the learner studies."""
        ...

    def due_cards(self, user_id: UUID, language_code: str, *, limit: int) -> list[dict]:
        """A few due words of one language: {id, text}; `id` is what `open_review` takes back."""
        ...

    def owned_saved_ids(self, user_id: UUID, language_code: str, concept_ids: list[UUID]) -> list[str]:
        """Of these ids, the ones that are this learner's saved words in this language, in the order given."""
        ...

    def study_requests(self, user_id: UUID, language_code: str, *, limit: int) -> list[dict]:
        """Open study requests: {kind, item, reason, created}."""
        ...

    def create_request(self, user_id: UUID, language_code: str, support_language_code: str | None, *, kind: str,
                       item_id: str, reason: str | None) -> Literal["created", "exists", "invalid"]:
        """Validates that the grammar point or word exists for this language before storing anything; the same open
        request from the last seven days is not created twice."""
        ...

    def grammar_menu(self, user_id: UUID, language_code: str, support_language_code: str):
        """The approved grammar lessons up to the learner's declared level (a LessonMenu), or None."""
        ...


class AgentMemory(Protocol):
    """What the agent remembers about the learner who is talking, across conversations (PRD 8.12 point 3).

    Every call names that learner. A failure is the app's, never the learner's: reads give an empty list and a
    write reports False, so a conversation goes on without memory.
    """

    def list_for_learner(self, user_id: UUID, *, limit: int) -> list[dict]:
        """Newest first: {id, kind, text, language_code, created_at} and, where stored, evidence (the kept turns a row
        came from: [{session_id, turn_index}]) and source ("agent" or "consolidated")."""
        ...

    def add(self, user_id: UUID, *, kind: str, text: str, language_code: str | None,
            evidence: list[dict] | None = None, source: str = "agent") -> bool: ...

    def delete_one(self, user_id: UUID, memory_id: UUID) -> bool:
        """True only when this learner's own row was removed."""
        ...

    def delete_all(self, user_id: UUID) -> bool:
        """True when the learner's rows are gone (also when there were none)."""
        ...


class TodayPlanEditor(Protocol):
    """Adds or removes one item of the learner's plan for a day (the study-plan service).

    A refusal raises `StudyPlanError` (its `code` says why); a success returns what changed. Both changes can be undone
    by item id (`undo_edit`), which is idempotent.
    """

    def add_item(self, user, day, *, kind: str, library_item_id: UUID | None) -> PlanEdit: ...

    def remove_item(self, user, day, *, kind: str, library_item_id: UUID | None) -> PlanEdit: ...


class VideoRegionChecker(Protocol):
    """Checks that a study region is one the learner can open: an own Library video and a well-formed region of it."""

    def check(self, user_id: UUID, library_item_id: UUID, region_id: str) -> "RegionTarget | None": ...


@dataclass(frozen=True)
class RegionTarget:
    title: str | None
    start_ms: int
