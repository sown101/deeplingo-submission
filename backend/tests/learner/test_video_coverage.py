"""L1c: personal lexical coverage of the learner's own videos (rules, service and routes)."""
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.bootstrap.wiring.identity import get_jwt_verifier
from app.bootstrap.wiring.learner import get_video_coverage_service
from app.main import app
from app.modules.identity.contracts import CurrentUser
from app.modules.learner.application.video_coverage import VideoCoverageError, VideoCoverageService
from app.modules.learner.application.word_targets import TargetSettings
from app.modules.learner.domain.video_coverage import (
    ProfileLexeme,
    VideoProfile,
    known_by_level,
    label_for,
    level_distribution,
    words_per_minute,
    words_to_reach,
)

USER = CurrentUser(id=uuid4())
OTHER = CurrentUser(id=uuid4())
ITEM, EMPTY_ITEM = uuid4(), uuid4()


def lexeme(text, level, occurrences, matched=True):
    return ProfileLexeme(text, level, matched, occurrences)


def profile(*lexemes, language="en", speech_ms=600_000):
    return VideoProfile(language, sum(item.occurrences for item in lexemes), 0, speech_ms, list(lexemes))


# A hundred word tokens: 90 at or below A2, 4 unlisted ("ubiquitous"), 4 at B2, 2 the dictionary does not know.
VIDEO = profile(lexeme("the", "A1", 50), lexeme("go", "A1", 30), lexeme("nice", "A2", 10),
                lexeme("bank", "B2", 4), lexeme("ubiquitous", None, 4), lexeme("xyz", None, 2, matched=False))


# --- Rules --------------------------------------------------------------------------------------

@pytest.mark.parametrize("coverage,label", [(1.0, "suitable"), (0.95, "suitable"), (0.9499, "challenging"),
                                            (0.90, "challenging"), (0.8999, "hard"), (0.0, "hard")])
def test_labels_follow_the_ninety_five_and_ninety_lines(coverage, label):
    assert label_for(coverage) == label


def test_words_needed_to_reach_the_line_use_the_most_frequent_unknown_words_first():
    assert words_to_reach(100, 95, [3, 2]) == 0
    assert words_to_reach(100, 90, [2, 4, 1, 3]) == 2  # 4 + 3 reaches 95
    assert words_to_reach(100, 80, [2, 1]) is None
    assert words_to_reach(100, 94, []) is None


def test_a_word_is_known_by_level_only_when_both_levels_are_on_the_same_scale():
    assert known_by_level("en", lexeme("go", "A1", 1), "A2")
    assert known_by_level("en", lexeme("go", "A2", 1), "A2")
    assert not known_by_level("en", lexeme("go", "B1", 1), "A2")
    assert not known_by_level("en", lexeme("go", "A1", 1), None)
    assert not known_by_level("en", lexeme("go", "A1", 1, matched=False), "B2")
    assert not known_by_level("en", lexeme("你好", "HSK1", 1), "B2")  # HSK is never read as CEFR
    assert known_by_level("zh", lexeme("你好", "HSK1", 1), "HSK3")


def test_the_distribution_lists_levels_easiest_first_then_unlisted_then_unmatched():
    assert level_distribution("en", VIDEO.lexemes) == [("A1", 80), ("A2", 10), ("B2", 4), ("unlisted", 4), ("unmatched", 2)]


def test_a_speech_rate_needs_half_a_minute_of_speech():
    assert words_per_minute(150, 60_000) == 150.0
    assert words_per_minute(10, 29_999) is None


# --- Service ------------------------------------------------------------------------------------

class FakeProfiles:
    def __init__(self, items=None):
        self.items = items if items is not None else {ITEM: VIDEO}
        self.budgets = []

    def for_item(self, user, library_item_id):
        if user.id != USER.id or library_item_id not in self.items:
            raise VideoCoverageError("Library item not found.", status_code=404, code="library_item_not_found")
        return self.items[library_item_id]

    def for_library(self, user, *, build_budget):
        self.budgets.append(build_budget)
        return list(self.items.items()) if user.id == USER.id else []


class FakeKnown:
    def __init__(self, *known):
        self.known, self.calls = set(known), []

    def known_among(self, user_id, language_code, lexemes):
        self.calls.append(list(lexemes))
        return self.known & set(lexemes)


def service(profiles=None, known=None, declared="A2"):
    targets = SimpleNamespace(settings=lambda user_id, language: TargetSettings(declared_level=declared))
    return VideoCoverageService(profiles=profiles or FakeProfiles(), known=known or FakeKnown(), targets=targets)


def test_coverage_counts_words_at_or_below_the_declared_level_and_words_the_learner_proved():
    view = service(known=FakeKnown("ubiquitous", "bank")).coverage(USER, ITEM)
    assert (view.known_tokens, view.token_count, view.coverage, view.label) == (98, 100, 0.98, "suitable")
    assert view.is_estimate and view.declared_level == "A2" and view.target_coverage == 0.95
    assert view.words_to_target == 0
    assert view.speech_rate_wpm == 10.0
    assert view.unmatched_share == 0.02


def test_coverage_below_the_line_names_the_words_to_learn_and_how_many_reach_it():
    view = service(known=FakeKnown("ubiquitous")).coverage(USER, ITEM)
    assert (view.coverage, view.label) == (0.94, "challenging")
    assert [(word.text, word.occurrences, word.level) for word in view.top_unknown] == [("bank", 4, "B2")]
    assert view.words_to_target == 1
    assert [(share.level, share.tokens, share.share) for share in view.distribution][:2] == [("A1", 80, 0.8), ("A2", 10, 0.1)]


def test_without_a_declared_level_only_the_learners_own_words_count_and_the_service_says_so():
    known = FakeKnown("the", "go")
    view = service(known=known, declared=None).coverage(USER, ITEM)
    assert view.declared_level is None and view.known_tokens == 80 and view.label == "hard"
    assert "xyz" not in known.calls[0]  # a form the dictionary does not know is never offered as known


def test_the_known_check_is_skipped_when_the_level_already_covers_everything():
    only_easy = profile(lexeme("the", "A1", 50), lexeme("go", "A1", 50))
    known = FakeKnown()
    view = service(FakeProfiles({ITEM: only_easy}), known).coverage(USER, ITEM)
    assert view.coverage == 1.0 and known.calls == []


def test_another_learners_item_is_the_same_error_as_a_missing_one():
    with pytest.raises(VideoCoverageError) as other:
        service().coverage(OTHER, ITEM)
    with pytest.raises(VideoCoverageError) as missing:
        service().coverage(USER, uuid4())
    assert (other.value.status_code, other.value.code) == (missing.value.status_code, missing.value.code) == (404, "library_item_not_found")


def test_recommendations_list_comfortable_videos_nearest_the_line_first_and_unprofiled_ones_last():
    easy = profile(lexeme("the", "A1", 100))  # 100%
    stretch = profile(lexeme("the", "A1", 96), lexeme("bank", "B2", 4))  # 96%
    near = profile(lexeme("the", "A1", 94), lexeme("bank", "B2", 6))  # 94%
    far = profile(lexeme("the", "A1", 60), lexeme("bank", "B2", 40))  # 60%
    ids = [uuid4() for _ in range(5)]
    profiles = FakeProfiles({ids[0]: far, ids[1]: None, ids[2]: easy, ids[3]: near, ids[4]: stretch})
    views = service(profiles).recommendations(USER)
    assert [view.library_item_id for view in views] == [ids[4], ids[2], ids[3], ids[0], ids[1]]
    assert [view.label for view in views] == ["suitable", "suitable", "challenging", "hard", None]
    assert views[2].words_to_target == 1 and views[4].coverage is None
    assert profiles.budgets == [3]


# --- Routes -------------------------------------------------------------------------------------

@pytest.fixture
def api():
    verifier = Mock()
    verifier.verify.side_effect = lambda token: USER
    app.dependency_overrides[get_jwt_verifier] = lambda: verifier
    app.dependency_overrides[get_video_coverage_service] = lambda: service(known=FakeKnown("ubiquitous"))
    try:
        yield SimpleNamespace(client=TestClient(app), headers={"Authorization": "Bearer owner.test.jwt"})
    finally:
        app.dependency_overrides.clear()


URL = "/api/v1/v3/learner/me/video-coverage"


def test_coverage_routes_need_a_signed_in_learner(api):
    assert api.client.get(URL).status_code == 401


def test_the_coverage_route_lists_the_learners_videos_with_an_estimate(api):
    listed = api.client.get(URL, headers=api.headers).json()
    assert [row["library_item_id"] for row in listed] == [str(ITEM)] and listed[0]["label"] == "challenging"
    assert api.client.get(f"{URL}?user_id={uuid4()}", headers=api.headers).status_code == 200  # ignored, never trusted


def test_an_inferred_level_counts_as_known_and_is_reported_as_inferred():
    zh = profile(lexeme("我", "HSK1", 60), ProfileLexeme("每天", "HSK1", True, 30, True), lexeme("聊", "HSK6", 10), language="zh")
    view = service(FakeProfiles({ITEM: zh}), declared="HSK2").coverage(USER, ITEM)
    assert (view.coverage, view.label) == (0.9, "challenging")
    assert view.derived_share == 0.3
    unknown = service(FakeProfiles({ITEM: profile(ProfileLexeme("聊天", "HSK6", True, 5, True), lexeme("我", "HSK1", 95),
                                                  language="zh")}), declared="HSK2").coverage(USER, ITEM)
    assert [(word.text, word.level, word.level_derived) for word in unknown.top_unknown] == [("聊天", "HSK6", True)]


# --- Vocabulary estimate --------------------------------------------------------------------------

def test_the_vocabulary_estimate_counts_distinct_matched_words_across_profiled_videos_per_language():
    second = profile(lexeme("the", "A1", 50), lexeme("river", "B1", 30), lexeme("bank", "B2", 10), lexeme("qq", None, 2, matched=False))
    zh = profile(lexeme("我", "HSK1", 60), lexeme("聊天", "HSK6", 5), language="zh")
    profiles = FakeProfiles({ITEM: VIDEO, uuid4(): second, uuid4(): None, uuid4(): zh})
    views = service(profiles, FakeKnown("bank"), declared="A2").vocabulary(USER)
    by_language = {view.language_code: view for view in views}
    # English: the, go, nice, bank, ubiquitous, river are matched (xyz and qq are not); A1/A2 words and the proved
    # "bank" are known; "river" (B1) and "ubiquitous" (unlisted) are not.
    assert (by_language["en"].known_words, by_language["en"].library_words, by_language["en"].videos) == (4, 6, 2)
    # The declared level here is A2, which is never read as HSK, so no Chinese word counts as known.
    assert (by_language["zh"].known_words, by_language["zh"].library_words, by_language["zh"].videos) == (0, 2, 1)
    assert [view.language_code for view in views] == ["en", "zh"] and all(view.is_estimate for view in views)
    assert profiles.budgets == [0]  # nothing is built just to answer this


def test_the_vocabulary_estimate_is_empty_without_profiled_videos_and_never_shows_another_learners_words():
    assert service(FakeProfiles({ITEM: None})).vocabulary(USER) == []
    assert service().vocabulary(OTHER) == []


def test_without_a_declared_level_the_library_shows_no_coverage_label_instead_of_a_false_zero():
    # Live check 2026-11-06: with no level, common words counted as unknown and every video read "Hard, 0%".
    ids = [uuid4(), uuid4()]
    profiles = FakeProfiles({ids[0]: VIDEO, ids[1]: None})
    views = service(profiles, declared=None).recommendations(USER)
    assert [view.library_item_id for view in views] == ids
    assert all(view.label is None and view.coverage is None for view in views)
    assert views[0].language_code == "en"
