"""A cached profile must describe the current text/timing of its transcript."""
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.modules.content.infrastructure.repositories.lexical_profiles import LexicalProfileRepository
from tests.content.test_lexical_profile import (
    OWNER, TRANSCRIPT, by_lexeme, library, make, word,
)


@pytest.mark.parametrize("before,after", [
    ([(0, 40_000, "Cats sleep.")], [(0, 40_000, "Dogs run.")]),
    ([(0, 40_000, "Cats sleep.")], [(0, 40_000, "Cats sleep."), (40_000, 60_000, "Dogs run.")]),
    ([(0, 40_000, "Cats sleep."), (40_000, 60_000, "Dogs run.")], [(0, 40_000, "Dogs run.")]),
])
def test_replacing_adding_or_removing_segments_rebuilds_the_same_transcript(before, after):
    service, store, dictionary = make(before, *(word(w, "A1") for w in ["cats", "sleep", "dogs", "run"]))
    service.get_or_build(TRANSCRIPT, "en")
    old_reads = len(dictionary.calls)
    service.segments.rows = after

    assert service.cached(TRANSCRIPT) is None
    fresh = service.get_or_build(TRANSCRIPT, "en")
    expected = {w.lower() for _, _, text in after for w in text.rstrip(".").split()}
    assert set(by_lexeme(fresh)) == expected
    assert store.writes == 2 and len(dictionary.calls) > old_reads


def test_chinese_text_replacement_rebuilds_words_without_changing_segmentation_rules():
    service, store, _ = make([(0, 40_000, "我喜欢学习中文。")],
        *(word(w, "HSK1", "zh") for w in ["我", "喜欢", "学习", "中文", "分享", "主意"]))
    first = service.get_or_build(TRANSCRIPT, "zh")
    service.segments.rows = [(0, 40_000, "我喜欢分享主意。")]

    assert service.cached(TRANSCRIPT) is None
    fresh = service.get_or_build(TRANSCRIPT, "zh")
    assert set(by_lexeme(first)) == {"我", "喜欢", "学习", "中文"}
    assert set(by_lexeme(fresh)) == {"我", "喜欢", "分享", "主意"}
    assert all(item.level == "HSK1" for item in fresh.lexemes)
    assert store.writes == 2


def test_timing_changes_recompute_speech_rate_even_when_the_words_are_identical():
    service, store, _ = make([(0, 40_000, "Cats sleep.")], word("cats"), word("sleep"))
    service.get_or_build(TRANSCRIPT, "en")
    service.segments.rows = [(0, 80_000, "Cats sleep.")]
    assert service.cached(TRANSCRIPT) is None
    assert service.get_or_build(TRANSCRIPT, "en").profile.speech_ms == 80_000
    assert store.writes == 2


def test_empty_transcript_never_serves_its_previous_nonempty_profile():
    service, _, _ = make([(0, 40_000, "Cats sleep.")], word("cats"), word("sleep"))
    service.get_or_build(TRANSCRIPT, "en")
    service.segments.rows = []
    assert service.cached(TRANSCRIPT) is None
    assert service.get_or_build(TRANSCRIPT, "en") is None


def test_unchanged_source_reuses_cache_without_reading_the_dictionary_again():
    service, store, dictionary = make([(0, 40_000, "Cats sleep.")], word("cats"), word("sleep"))
    first = service.get_or_build(TRANSCRIPT, "en")
    reads = len(dictionary.calls)
    assert service.get_or_build(TRANSCRIPT, "en") == first
    assert store.writes == 1 and len(dictionary.calls) == reads


def test_preexisting_cache_without_source_hash_is_rebuilt_once():
    service, store, _ = make([(0, 40_000, "Cats sleep.")], word("cats"), word("sleep"))
    service.get_or_build(TRANSCRIPT, "en")
    store.profile = replace(store.profile, source_hash=None)
    assert service.cached(TRANSCRIPT) is None
    fresh = service.get_or_build(TRANSCRIPT, "en")
    assert len(fresh.profile.source_hash) == 64 and store.writes == 2


def test_recommendations_do_not_serve_stale_cache_when_the_build_budget_is_zero():
    service, store, _ = make([(0, 40_000, "Cats sleep.")], word("cats"), word("sleep"))
    service.get_or_build(TRANSCRIPT, "en")
    service.segments.rows = [(0, 80_000, "Cats sleep.")]
    path = library(service)
    assert path.for_library(SimpleNamespace(id=OWNER), build_budget=0)[0][1] is None
    assert store.writes == 1
    assert path.for_library(SimpleNamespace(id=OWNER), build_budget=1)[0][1].profile.speech_ms == 80_000
    assert store.writes == 2


def test_changed_track_language_cannot_reuse_a_profile_built_for_another_language():
    service, store, _ = make([(0, 40_000, "中文")], word("中文", "HSK1", "zh"))
    service.get_or_build(TRANSCRIPT, "en")
    assert service.get_or_build(TRANSCRIPT, "zh").profile.language_code == "zh"
    assert store.writes == 2


def test_profile_repository_preserves_the_source_hash_across_writes_and_reads():
    service, _, _ = make([(0, 40_000, "Cats sleep.")], word("cats"), word("sleep"))
    profile = service.build(TRANSCRIPT, "en")
    client = Mock()
    table = client.schema.return_value.table.return_value
    row = {"transcript_id":str(TRANSCRIPT), "language_code":"en", "profile_version":profile.profile.version,
        "token_count":2, "proper_noun_count":0, "speech_ms":40_000, "source_hash":profile.profile.source_hash}
    table.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = [row]
    repo = LexicalProfileRepository(client)
    repo.replace(profile.profile, profile.lexemes)
    assert table.upsert.call_args.args[0]["source_hash"] == profile.profile.source_hash
    assert repo.get(TRANSCRIPT).source_hash == profile.profile.source_hash


def test_recommendations_respect_a_track_language_change_even_with_the_same_text():
    from tests.content.test_lexical_profile import VIDEO
    service, store, _ = make([(0, 40_000, "中文")], word("中文", "HSK1", "zh"))
    service.get_or_build(TRANSCRIPT, "en")
    path = library(service, transcripts=[SimpleNamespace(id=TRANSCRIPT, language_code="zh", is_original=True, source="caption_track")])
    path.videos.get_by_id = lambda video_id: SimpleNamespace(id=VIDEO, processing_status="transcript_ready", original_language_code="zh")
    assert path.for_library(SimpleNamespace(id=OWNER), build_budget=0)[0][1] is None
    fresh = path.for_library(SimpleNamespace(id=OWNER), build_budget=1)[0][1]
    assert fresh.profile.language_code == "zh" and store.writes == 2


def test_personal_coverage_uses_new_words_after_the_owned_transcript_changes():
    from app.bootstrap.wiring.learner import _LibraryVideoProfiles
    from app.modules.identity.contracts import CurrentUser
    from app.modules.learner.application.video_coverage import VideoCoverageService
    from tests.content.test_lexical_profile import ITEM
    from tests.learner.test_video_coverage import FakeKnown
    service, _, _ = make([(0, 40_000, "Cats sleep.")],
        *(word(w) for w in ["cats", "sleep", "dogs", "run"]))
    known = FakeKnown("cats", "sleep")
    targets = SimpleNamespace(settings=lambda user_id, language: SimpleNamespace(declared_level=None))
    coverage = VideoCoverageService(profiles=_LibraryVideoProfiles(library(service)), known=known, targets=targets)
    before = coverage.coverage(CurrentUser(id=OWNER), ITEM)
    service.segments.rows = [(0, 40_000, "Dogs run.")]
    after = coverage.coverage(CurrentUser(id=OWNER), ITEM)
    assert before.coverage == 1 and before.label == "suitable"
    assert after.coverage == 0 and after.label == "hard"
    assert {w.text for w in after.top_unknown} == {"dogs", "run"}


def test_a_profile_with_identical_timestamps_but_changed_chinese_text_has_a_different_hash():
    service, _, _ = make([(0, 40_000, "我喜欢中文")], *(word(w, "HSK1", "zh") for w in ["我", "喜欢", "中文", "学习"]))
    first = service.build(TRANSCRIPT, "zh")
    service.segments.rows = [(0, 40_000, "我学习中文")]
    second = service.build(TRANSCRIPT, "zh")
    assert first.profile.source_hash != second.profile.source_hash
