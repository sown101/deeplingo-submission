"""The agent's voice consent and personalization signals (PRD FR-3.4, FR-3.6).

A signal is a closed code, never text: a topic group, a stated learning goal, a recurring
error type or a fluency level. Names, places, workplaces, relationships, health, quotes and
source text have no code, so they cannot be stored. Adding a code needs the owner's approval.
Nothing here is read by grading, the usage ladder, review or progression.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class SignalKind(str, Enum):
    TOPIC = "topic"
    GOAL = "goal"
    ERROR_TYPE = "error_type"
    PACE = "pace"
    TURN_LENGTH = "turn_length"


ALLOWED_CODES: dict[SignalKind, frozenset[str]] = {
    SignalKind.TOPIC: frozenset({
        "travel", "food", "technology", "work_career", "school", "sports", "music", "movies", "games",
        "books", "news", "shopping", "nature", "art", "daily_life", "culture", "business",
    }),
    SignalKind.GOAL: frozenset({
        "travel", "work", "study_abroad", "exam", "conversation", "watching_media", "reading", "hobby",
    }),
    SignalKind.ERROR_TYPE: frozenset({
        "verb_tense", "subject_verb_agreement", "articles", "prepositions", "word_order", "plural_forms",
        "pronouns", "conjunctions", "word_choice", "measure_words", "aspect_particles", "complements",
    }),
    SignalKind.PACE: frozenset({"slow", "steady", "fast"}),
    SignalKind.TURN_LENGTH: frozenset({"short", "medium", "long"}),
}

# Fluency is one current level per language, not a count of sightings.
SINGLE_VALUE_KINDS = frozenset({SignalKind.PACE, SignalKind.TURN_LENGTH})


def is_allowed(kind: SignalKind, code: str) -> bool:
    return code in ALLOWED_CODES[kind]


class AgentConsent(BaseModel):
    model_config = ConfigDict(extra="ignore")

    user_id: UUID
    # None = never asked, True = granted, False = revoked.
    voice_consent: bool | None = None
    decided_at: datetime | None = None
    # FR-3.11: the separate consent to keep spoken turns as text. Same three states; default off.
    transcript_consent: bool | None = None
    transcript_decided_at: datetime | None = None


class PersonalizationSignal(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: UUID | None = None
    user_id: UUID
    language_code: str
    kind: SignalKind
    code: str
    usage_count: int = Field(default=1, ge=1)
    updated_at: datetime | None = None


def consent_status(consent: AgentConsent | None) -> str:
    """"ask" until the learner decides, then "granted" or "revoked"."""
    if consent is None or consent.voice_consent is None:
        return "ask"
    return "granted" if consent.voice_consent else "revoked"


def transcript_consent_status(consent: AgentConsent | None) -> str:
    """The transcript consent on its own: "ask", "granted" or "revoked"."""
    if consent is None or consent.transcript_consent is None:
        return "ask"
    return "granted" if consent.transcript_consent else "revoked"


def may_keep_transcripts(consent: AgentConsent | None) -> bool:
    """FR-3.11: transcripts are kept only while both the voice consent and the transcript consent are granted."""
    return consent_status(consent) == "granted" and transcript_consent_status(consent) == "granted"
