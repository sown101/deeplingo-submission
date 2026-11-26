"""Builds the learner profile snapshot from the readers other modules provide.

Every source is optional and isolated: one that is missing or fails is named in `unavailable` and the rest of
the snapshot is still returned. Nothing is written and no model is called.
"""
from __future__ import annotations

import logging
from typing import Callable, Protocol

from app.modules.learner.domain.profile_snapshot import (
    ActivitySection,
    GrammarSection,
    LearnerProfileSnapshot,
    ReviewSection,
    SignalsSection,
    UsageSection,
    VocabularySection,
)

logger = logging.getLogger(__name__)


class DeclaredLevelReader(Protocol):
    def declared_level(self, user, language_code: str) -> str | None: ...


class VocabularyReader(Protocol):
    def vocabulary(self, user, language_code: str) -> VocabularySection | None: ...


class UsageReader(Protocol):
    def words_by_rung(self, user, language_code: str) -> dict[int, int]: ...


class ReviewReader(Protocol):
    def review_summary(self, user, language_code: str) -> ReviewSection: ...


class GrammarReader(Protocol):
    def grammar_summary(self, user, language_code: str) -> GrammarSection | None: ...


class SignalsReader(Protocol):
    def signals(self, user, language_code: str) -> SignalsSection: ...


class ActivityReader(Protocol):
    def activity_summary(self, user, language_code: str) -> ActivitySection | None: ...


class LearnerProfileSnapshotService:
    def __init__(self, *, declared_level: DeclaredLevelReader | None = None,
                 vocabulary: VocabularyReader | None = None, usage: UsageReader | None = None,
                 review: ReviewReader | None = None, grammar: GrammarReader | None = None,
                 signals: SignalsReader | None = None, activity: ActivityReader | None = None):
        self.declared_level = declared_level
        self.vocabulary = vocabulary
        self.usage = usage
        self.review = review
        self.grammar = grammar
        self.signals = signals
        self.activity = activity

    def snapshot(self, user, language_code: str) -> LearnerProfileSnapshot:
        unavailable: list[str] = []

        def read(name: str, source: object | None, call: Callable[[], object], *, none_ok: bool = False):
            if source is None:
                unavailable.append(name)
                return None
            try:
                value = call()
            except Exception as exc:  # a source must never break the picture; log the type only
                logger.warning("learner profile section unavailable section=%s error=%s", name, type(exc).__name__)
                unavailable.append(name)
                return None
            if value is None and not none_ok:
                unavailable.append(name)
            return value

        # A learner who has not declared a level is a normal state, not a missing source.
        level = read("declared_level", self.declared_level,
                     lambda: self.declared_level.declared_level(user, language_code), none_ok=True)
        counts = read("usage", self.usage, lambda: self.usage.words_by_rung(user, language_code))
        snapshot = LearnerProfileSnapshot(
            language_code=language_code,
            declared_level=level,
            vocabulary=read("vocabulary", self.vocabulary, lambda: self.vocabulary.vocabulary(user, language_code)),
            usage=UsageSection.from_counts(counts) if counts is not None else None,
            review=read("review", self.review, lambda: self.review.review_summary(user, language_code)),
            grammar=read("grammar", self.grammar, lambda: self.grammar.grammar_summary(user, language_code)),
            signals=read("signals", self.signals, lambda: self.signals.signals(user, language_code)),
            activity=read("activity", self.activity, lambda: self.activity.activity_summary(user, language_code)),
            unavailable=tuple(sorted(set(unavailable))),
        )
        return snapshot.with_version()
