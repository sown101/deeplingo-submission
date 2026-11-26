"""Which videos are within reach (L1c): personal lexical coverage of the learner's own Library videos.

Everything here is an estimate from a transcript and a dictionary. The learner sends only a Library item
id; the server resolves ownership, the profile, the learner's declared level and recognised words. Coverage
never changes learner state.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.modules.identity.contracts import CurrentUser
from app.modules.learner.application.ports import KnownLexemes, VideoProfileSource
from app.modules.learner.application.word_targets import WordTargetsService
from app.modules.learner.domain.video_coverage import (
    TARGET_COVERAGE,
    VideoProfile,
    known_by_level,
    label_for,
    lexeme_level,
    level_distribution,
    words_per_minute,
    words_to_reach,
)

MAX_TOP_UNKNOWN = 20
RECOMMENDATION_BUILD_BUDGET = 3

Label = Literal["suitable", "challenging", "hard"]


class VideoCoverageError(ValueError):
    def __init__(self, message: str, *, status_code: int, code: str):
        self.status_code = status_code
        self.code = code
        super().__init__(message)


class LevelShare(BaseModel):
    model_config = ConfigDict(extra="forbid")

    level: str  # a level label, "unlisted" or "unmatched"
    tokens: int
    share: float


class UnknownWord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str
    occurrences: int
    level: str | None
    level_derived: bool = False


class CoverageView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    library_item_id: UUID
    language_code: str
    is_estimate: bool = True
    coverage: float
    label: Label
    token_count: int
    known_tokens: int
    declared_level: str | None
    speech_rate_wpm: float | None
    distribution: list[LevelShare]
    top_unknown: list[UnknownWord]
    words_to_target: int | None
    target_coverage: float = TARGET_COVERAGE
    unmatched_share: float
    derived_share: float = 0.0  # share of tokens whose level was inferred, not named by the dictionary


class RecommendationView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    library_item_id: UUID
    language_code: str | None = None
    is_estimate: bool = True
    coverage: float | None = None
    label: Label | None = None
    speech_rate_wpm: float | None = None
    words_to_target: int | None = None


class VocabularyView(BaseModel):
    """How many different dictionary words of the learner's own videos they probably know (an estimate)."""
    model_config = ConfigDict(extra="forbid")

    language_code: str
    is_estimate: bool = True
    known_words: int
    library_words: int
    videos: int


@dataclass
class _Measure:
    declared_level: str | None
    known: dict[str, bool]  # lexeme -> known
    known_tokens: int


class VideoCoverageService:
    def __init__(self, *, profiles: VideoProfileSource, known: KnownLexemes, targets: WordTargetsService):
        self.profiles = profiles
        self.known = known
        self.targets = targets

    def coverage(self, user: CurrentUser, library_item_id: UUID) -> CoverageView:
        profile = self.profiles.for_item(user, library_item_id)
        if profile.token_count == 0:
            raise VideoCoverageError("No word profile for this video.", status_code=404, code="profile_unavailable")
        measure = self._measure(user.id, profile)
        total = profile.token_count
        unknown = [item for item in profile.lexemes if not measure.known[item.lexeme]]
        learnable = [item for item in unknown if item.matched]
        learnable.sort(key=lambda item: (-item.occurrences, item.lexeme))
        coverage = measure.known_tokens / total
        language = profile.language_code
        unmatched = sum(item.occurrences for item in profile.lexemes if not item.matched)
        return CoverageView(
            library_item_id=library_item_id, language_code=language, coverage=round(coverage, 3),
            label=label_for(coverage), token_count=total, known_tokens=measure.known_tokens,
            declared_level=measure.declared_level,
            speech_rate_wpm=words_per_minute(total, profile.speech_ms),
            distribution=[LevelShare(level=key, tokens=tokens, share=round(tokens / total, 3))
                          for key, tokens in level_distribution(language, profile.lexemes)],
            top_unknown=[UnknownWord(text=item.lexeme, occurrences=item.occurrences, level=lexeme_level(language, item),
                                     level_derived=item.level_derived) for item in learnable[:MAX_TOP_UNKNOWN]],
            words_to_target=words_to_reach(total, measure.known_tokens, [item.occurrences for item in learnable]),
            unmatched_share=round(unmatched / total, 3),
            derived_share=round(sum(item.occurrences for item in profile.lexemes if item.level_derived) / total, 3),
        )

    def recommendations(self, user: CurrentUser) -> list[RecommendationView]:
        """Comfortable videos first (the nearest the 95% line first: some stretch), then challenging, then hard,
        then those without a profile yet."""
        views: list[RecommendationView] = []
        for item_id, profile in self.profiles.for_library(user, build_budget=RECOMMENDATION_BUILD_BUDGET):
            if profile is None or profile.token_count == 0:
                views.append(RecommendationView(library_item_id=item_id))
                continue
            measure = self._measure(user.id, profile)
            if measure.declared_level is None:
                # Without a level only proven words count, so nearly every video would read "hard, 0%":
                # no estimate is shown until the learner sets a level (2026-11-06).
                views.append(RecommendationView(library_item_id=item_id, language_code=profile.language_code))
                continue
            coverage = measure.known_tokens / profile.token_count
            learnable = sorted((item.occurrences for item in profile.lexemes
                                if item.matched and not measure.known[item.lexeme]), reverse=True)
            views.append(RecommendationView(
                library_item_id=item_id, language_code=profile.language_code, coverage=round(coverage, 3),
                label=label_for(coverage), speech_rate_wpm=words_per_minute(profile.token_count, profile.speech_ms),
                words_to_target=words_to_reach(profile.token_count, measure.known_tokens, learnable),
            ))
        rank = {"suitable": 0, "challenging": 1, "hard": 2, None: 3}
        return sorted(views, key=lambda view: (rank[view.label], abs((view.coverage or 0) - TARGET_COVERAGE)))

    def vocabulary(self, user: CurrentUser) -> list[VocabularyView]:
        """Per language, the distinct dictionary words across the learner's already profiled videos and how many of
        them count as known under the same rule as video coverage. Videos without a profile are left out (nothing is
        built here)."""
        words: dict[str, set[str]] = {}
        known: dict[str, set[str]] = {}
        videos: dict[str, int] = {}
        for _, profile in self.profiles.for_library(user, build_budget=0):
            if profile is None or profile.token_count == 0:
                continue
            language = profile.language_code
            measure = self._measure(user.id, profile)
            matched = [item.lexeme for item in profile.lexemes if item.matched]
            words.setdefault(language, set()).update(matched)
            known.setdefault(language, set()).update(lexeme for lexeme in matched if measure.known[lexeme])
            videos[language] = videos.get(language, 0) + 1
        return [VocabularyView(language_code=language, known_words=len(known[language]),
                               library_words=len(words[language]), videos=videos[language])
                for language in sorted(words)]

    def _measure(self, user_id: UUID, profile: VideoProfile) -> _Measure:
        language = profile.language_code
        declared = self.targets.settings(user_id, language).declared_level
        by_level = {item.lexeme: known_by_level(language, item, declared) for item in profile.lexemes}
        # The learner's own words only matter for words the declared level does not already cover.
        remaining = [item.lexeme for item in profile.lexemes if item.matched and not by_level[item.lexeme]]
        proven = self.known.known_among(user_id, language, remaining) if remaining else set()
        known = {item.lexeme: by_level[item.lexeme] or item.lexeme in proven for item in profile.lexemes}
        known_tokens = sum(item.occurrences for item in profile.lexemes if known[item.lexeme])
        return _Measure(declared, known, known_tokens)
