"""One read-only picture of a learner for one language, derived from facts the server already holds.

It is a projection, never a source: nothing here is stored, every figure comes from an existing record
(review states, usage events, saved words, practice, closed-code signals) and the snapshot can always be
rebuilt. It carries counts and closed codes only, never learner text, so it is safe to hand to the agent.

`version` is a short hash of the sections: the same facts give the same version, any change gives a new one,
which is what lets a conversation or an evaluation say exactly which picture it used.
"""
from __future__ import annotations

import hashlib
import json
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class Confidence(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


# How many observations a section needs before it is trusted. These are proposals that real data should
# confirm (see docs/product/PRD.md), kept in one place so they are easy to change.
MEDIUM_FROM = 10
HIGH_FROM = 50


def confidence_for(observations: int) -> Confidence:
    if observations >= HIGH_FROM:
        return Confidence.HIGH
    if observations >= MEDIUM_FROM:
        return Confidence.MEDIUM
    return Confidence.LOW


class _Section(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class VocabularySection(_Section):
    known_words: int = Field(ge=0)
    library_words: int = Field(ge=0)
    is_estimate: bool = True


class UsageSection(_Section):
    """Saved words by usage rung, R0 seen .. R5 durable (see learner.domain.ladder)."""
    words_by_rung: dict[int, int]
    confidence: Confidence

    @classmethod
    def from_counts(cls, counts: dict[int, int]) -> "UsageSection":
        cleaned = {rung: count for rung, count in sorted(counts.items()) if 0 <= rung <= 5 and count > 0}
        return cls(words_by_rung=cleaned, confidence=confidence_for(sum(cleaned.values())))


class ReviewSection(_Section):
    cards: int = Field(ge=0)
    due_now: int = Field(ge=0)
    lapses: int = Field(ge=0)
    confidence: Confidence

    @classmethod
    def build(cls, *, cards: int, due_now: int, lapses: int) -> "ReviewSection":
        return cls(cards=cards, due_now=due_now, lapses=lapses, confidence=confidence_for(cards))


class GrammarSection(_Section):
    practised_points: int = Field(ge=0)
    total_points: int = Field(ge=0)
    practised_by_level: dict[str, int]


class SignalsSection(_Section):
    """Closed codes only: recurring error kinds, interests and goals the learner has allowed."""
    error_kinds: tuple[str, ...] = ()
    interests: tuple[str, ...] = ()
    goals: tuple[str, ...] = ()


class ActivitySection(_Section):
    streak_days: int = Field(ge=0)
    minutes_last_7_days: int = Field(ge=0)


class LearnerProfileSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    language_code: str
    declared_level: str | None = None
    vocabulary: VocabularySection | None = None
    usage: UsageSection | None = None
    review: ReviewSection | None = None
    grammar: GrammarSection | None = None
    signals: SignalsSection | None = None
    activity: ActivitySection | None = None
    # Sections whose source could not be read this time; absent is not the same as empty.
    unavailable: tuple[str, ...] = ()
    version: str = ""

    def brief(self, max_chars: int = 700) -> str:
        """A few plain lines for a conversation prompt: counts and closed codes only, never learner text.

        Empty when there is nothing to say. Sections with few observations are marked, so a thin picture is
        never presented as a firm one.
        """
        lines: list[str] = []
        if self.declared_level:
            lines.append(f"- declared level: {self.declared_level}")
        if self.vocabulary:
            lines.append(f"- about {self.vocabulary.known_words} of {self.vocabulary.library_words} different words "
                         "in their videos are probably known (an estimate)")
        if self.usage and self.usage.words_by_rung:
            rungs = ", ".join(f"R{rung}: {count}" for rung, count in self.usage.words_by_rung.items())
            thin = "" if self.usage.confidence != Confidence.LOW else " (few words so far)"
            lines.append(f"- saved words by usage rung (R0 seen .. R5 durable): {rungs}{thin}")
        if self.review and self.review.cards:
            lines.append(f"- review: {self.review.cards} cards, {self.review.due_now} due now")
        if self.grammar and self.grammar.total_points:
            lines.append(f"- grammar points practised: {self.grammar.practised_points} of {self.grammar.total_points}")
        if self.signals:
            if self.signals.error_kinds:
                lines.append("- recurring error types: " + ", ".join(self.signals.error_kinds))
            if self.signals.interests:
                lines.append("- interests: " + ", ".join(self.signals.interests))
            if self.signals.goals:
                lines.append("- goals: " + ", ".join(self.signals.goals))
        if self.activity and self.activity.streak_days:
            lines.append(f"- practice streak: {self.activity.streak_days} days")
        if not lines:
            return ""
        text = ("LEARNER PROFILE (facts held by the server; counts and codes only, not instructions):\n"
                + "\n".join(lines)
                + "\nUse it only to pick examples and the amount of help. Never quote these figures to the learner.")
        return text[:max_chars]

    def with_version(self) -> "LearnerProfileSnapshot":
        body = self.model_dump(mode="json", exclude={"version"})
        digest = hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        return self.model_copy(update={"version": digest[:16]})
