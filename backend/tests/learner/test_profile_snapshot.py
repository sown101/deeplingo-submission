from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.modules.learner.application.profile_snapshot import LearnerProfileSnapshotService
from app.modules.learner.domain.profile_snapshot import (
    HIGH_FROM,
    MEDIUM_FROM,
    ActivitySection,
    Confidence,
    GrammarSection,
    LearnerProfileSnapshot,
    ReviewSection,
    SignalsSection,
    UsageSection,
    VocabularySection,
    confidence_for,
)

USER = SimpleNamespace(id=uuid4())


class _Level:
    def __init__(self, level="B1"):
        self.level = level

    def declared_level(self, user, language_code):
        return self.level


class _Vocabulary:
    def vocabulary(self, user, language_code):
        return VocabularySection(known_words=420, library_words=900)


class _Usage:
    def __init__(self, counts):
        self.counts = counts

    def words_by_rung(self, user, language_code):
        return self.counts


class _Review:
    def review_summary(self, user, language_code):
        return ReviewSection.build(cards=60, due_now=7, lapses=4)


class _Grammar:
    def grammar_summary(self, user, language_code):
        return GrammarSection(practised_points=3, total_points=40, practised_by_level={"A1": 3})


class _Signals:
    def signals(self, user, language_code):
        return SignalsSection(error_kinds=("past_tense",), interests=("travel",), goals=("speak_fluently",))


class _Activity:
    def activity_summary(self, user, language_code):
        return ActivitySection(streak_days=5, minutes_last_7_days=82)


class _Broken:
    def vocabulary(self, user, language_code):
        raise RuntimeError("secret learner text must not be logged")


def _full(**overrides):
    parts = dict(declared_level=_Level(), vocabulary=_Vocabulary(), usage=_Usage({1: 12, 3: 4, 5: 1}),
                 review=_Review(), grammar=_Grammar(), signals=_Signals(), activity=_Activity())
    parts.update(overrides)
    return LearnerProfileSnapshotService(**parts)


def test_a_full_snapshot_carries_every_section_and_nothing_is_unavailable():
    snapshot = _full().snapshot(USER, "en")
    assert snapshot.declared_level == "B1"
    assert snapshot.vocabulary.known_words == 420
    assert snapshot.usage.words_by_rung == {1: 12, 3: 4, 5: 1}
    assert snapshot.review.due_now == 7 and snapshot.grammar.total_points == 40
    assert snapshot.signals.error_kinds == ("past_tense",) and snapshot.activity.streak_days == 5
    assert snapshot.unavailable == ()


def test_a_missing_source_is_named_and_the_rest_is_still_returned():
    snapshot = _full(vocabulary=None, grammar=None).snapshot(USER, "en")
    assert snapshot.vocabulary is None and snapshot.grammar is None
    assert snapshot.review is not None
    assert snapshot.unavailable == ("grammar", "vocabulary")


def test_a_failing_source_is_named_and_does_not_break_the_snapshot(caplog):
    snapshot = _full(vocabulary=_Broken()).snapshot(USER, "en")
    assert snapshot.vocabulary is None and "vocabulary" in snapshot.unavailable
    assert snapshot.review is not None
    assert "secret learner text" not in caplog.text


def test_an_undeclared_level_is_not_a_missing_source():
    snapshot = _full(declared_level=_Level(None)).snapshot(USER, "en")
    assert snapshot.declared_level is None
    assert "declared_level" not in snapshot.unavailable


def test_the_version_is_stable_for_the_same_facts_and_changes_with_them():
    first = _full().snapshot(USER, "en")
    assert _full().snapshot(USER, "en").version == first.version
    assert len(first.version) == 16
    assert _full(usage=_Usage({1: 13})).snapshot(USER, "en").version != first.version
    assert _full().snapshot(USER, "zh").version != first.version


def test_usage_ignores_rungs_outside_the_ladder_and_empty_counts():
    section = UsageSection.from_counts({0: 0, 2: 3, 9: 5, -1: 2})
    assert section.words_by_rung == {2: 3}


@pytest.mark.parametrize("observations, expected", [
    (0, Confidence.LOW), (MEDIUM_FROM - 1, Confidence.LOW), (MEDIUM_FROM, Confidence.MEDIUM),
    (HIGH_FROM - 1, Confidence.MEDIUM), (HIGH_FROM, Confidence.HIGH),
])
def test_confidence_rises_with_the_number_of_observations(observations, expected):
    assert confidence_for(observations) == expected


def test_the_snapshot_cannot_carry_unexpected_fields():
    with pytest.raises(ValidationError):
        LearnerProfileSnapshot(language_code="en", transcript="free text")
    with pytest.raises(ValidationError):
        SignalsSection(free_text="I like cats")


def test_the_brief_has_counts_and_codes_only_and_stays_short():
    text = _full().snapshot(USER, "en").brief()
    assert text.startswith("LEARNER PROFILE")
    for fragment in ("declared level: B1", "R1: 12", "R5: 1", "7 due now", "3 of 40", "past_tense",
                     "travel", "speak_fluently", "streak: 5 days"):
        assert fragment in text
    assert "Never quote these figures" in text and len(text) <= 700


def test_an_empty_snapshot_has_no_brief():
    assert LearnerProfileSnapshot(language_code="en").brief() == ""


def test_a_thin_usage_section_is_marked_as_thin():
    snapshot = LearnerProfileSnapshot(language_code="en", usage=UsageSection.from_counts({1: 2}))
    assert "few words so far" in snapshot.brief()
