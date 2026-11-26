"""L1c: counting the words of a transcript, caching the profile and the learner-owned path to it."""
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.modules.content.application.library import LearnerLibraryError
from app.modules.content.application.lexical_profile import (
    Lexeme,
    LexicalProfileService,
    LibraryLexicalProfiles,
    StoredProfile,
)
from app.modules.content.domain.knowledge import DictionaryEntry
from app.modules.content.domain.lexical_profile import (
    PROFILE_VERSION,
    candidate_cjk_words,
    cjk_runs,
    cut_cjk_run,
    derive_compound_level,
    spaced_words,
    split_contraction,
    spoken_milliseconds,
)

OWNER, OTHER = uuid4(), uuid4()
ITEM, VIDEO, TRANSCRIPT = uuid4(), uuid4(), uuid4()


def entry(headword, *senses, language="en", metadata=None):
    return DictionaryEntry(id=uuid4(), language_code=language, headword=headword, normalized_headword=headword,
                           definitions=list(senses), provider="test", provider_metadata=metadata or {})


def word(headword, level=None, language="en"):
    return entry(headword, {"sense_id": f"s:{headword}", "text": f"meaning of {headword}"}, language=language,
                 metadata={("hsk" if language == "zh" else "cefr_j"): level} if level else None)


def inflected(headword, base):
    return entry(headword, {"sense_id": f"f:{headword}", "text": f"form of {base}", "form_of": [base]})


class FakeDictionary:
    def __init__(self, *entries):
        self.entries = [item for item in entries]
        self.calls = []

    def list_by_headwords(self, *, language_code, normalized_headwords):
        self.calls.append(list(normalized_headwords))
        return [item for item in self.entries
                if item.language_code == language_code and item.normalized_headword in normalized_headwords]


class FakeSegments:
    def __init__(self, rows):
        self.rows = rows

    def spans_and_texts(self, transcript_id):
        return self.rows if transcript_id == TRANSCRIPT else []

    def spans_and_texts_for_many(self, transcript_ids):
        return {key: self.spans_and_texts(key) for key in transcript_ids}


class FakeStore:
    def __init__(self):
        self.profile, self.items, self.writes = None, [], 0

    def get(self, transcript_id):
        return self.profile

    def lexemes(self, transcript_id):
        return list(self.items)

    def get_many(self, transcript_ids):
        return {key: self.profile for key in transcript_ids if self.profile and self.profile.transcript_id == key}

    def lexemes_for_many(self, transcript_ids):
        return {key: self.lexemes(key) for key in transcript_ids}

    def replace(self, profile, lexemes):
        self.profile, self.items, self.writes = profile, list(lexemes), self.writes + 1


def make(rows, *entries):
    store, dictionary = FakeStore(), FakeDictionary(*entries)
    return LexicalProfileService(store=store, segments=FakeSegments(rows), dictionary=dictionary), store, dictionary


def by_lexeme(profile):
    return {item.lexeme: item for item in profile.lexemes}


# --- pure rules ---------------------------------------------------------------------------------

@pytest.mark.parametrize("written,base", [
    ("don't", "do"), ("It's", "it"), ("can’t", "can"), ("won't", "will"), ("they're", "they"),
    ("I'll", "i"), ("rock", "rock"), ("n't", "n't"),
])
def test_a_contraction_is_counted_as_the_word_it_is_built_on(written, base):
    assert split_contraction(written) == base


def test_names_digits_and_the_word_i_in_a_sentence():
    words = spaced_words("Yesterday I met Anna in 2024, and I'm happy. NASA called.")
    assert [token.form for token in words.tokens] == ["yesterday", "i", "met", "in", "and", "i", "happy", "nasa", "called"]
    assert words.proper_nouns == 1  # Anna; the first word of a caption is never treated as a name


def test_chinese_runs_are_cut_by_longest_match_and_other_characters_split_them():
    assert cjk_runs("我喜欢 learn 中文, 2 个") == ["我喜欢", "中文", "个"]
    known = {"我", "喜欢", "喜", "欢", "学习", "中文"}
    assert cut_cjk_run("我喜欢学习中文", known) == ["我", "喜欢", "学习", "中文"]
    assert cut_cjk_run("龘我", known) == ["龘", "我"]
    assert {"我喜", "我喜欢", "喜欢"} <= candidate_cjk_words(["我喜欢"])


def test_speaking_time_is_the_union_of_caption_spans():
    assert spoken_milliseconds([(0, 4000), (3000, 6000), (10_000, 12_000), (5, 5)]) == 8000


# --- English ------------------------------------------------------------------------------------

def test_english_words_are_counted_by_lemma_with_their_level():
    rows = [(0, 4000, "She went to London."), (4000, 8000, "She said the xylophone is nice, so go!")]
    service, _, _ = make(rows, word("she", "A1"), inflected("went", "go"), word("go", "A1"), word("to", "A1"),
                         word("said"), word("the"), word("is"), word("nice", "A2"), word("so"))
    profile = service.get_or_build(TRANSCRIPT, "en")
    items = by_lexeme(profile)
    assert items["go"] == Lexeme("go", "A1", True, 2)  # "went" and "go"
    assert items["she"].occurrences == 2 and items["she"].level == "A1"
    assert items["nice"].level == "A2" and items["said"].level is None and items["said"].matched
    assert items["xylophone"] == Lexeme("xylophone", None, False, 1)
    assert "london" not in items
    assert profile.profile.proper_noun_count == 1
    assert profile.profile.token_count == sum(item.occurrences for item in profile.lexemes) == 11
    assert profile.profile.speech_ms == 8000 and profile.profile.version == PROFILE_VERSION


def test_an_inflection_with_senses_but_no_level_counts_as_its_base_form():
    going = entry("going", {"sense_id": "s:going", "text": "a departure"}, {"sense_id": "f:going", "text": "form of go", "form_of": ["go"]})
    rows = [(0, 40_000, "We are going, so go and keep going. It is a means to an end.")]
    service, _, _ = make(rows, going, word("go", "A1"), word("we"), word("are"), word("so"), word("and"), word("keep"),
                         word("it"), word("is"), word("a"), word("means", "B2"), word("to"), word("an"), word("end"))
    items = by_lexeme(service.get_or_build(TRANSCRIPT, "en"))
    assert items["go"] == Lexeme("go", "A1", True, 3)
    assert "going" not in items and items["means"].level == "B2"  # a form with a level of its own stays


def test_a_word_with_two_entries_takes_the_lowest_level():
    rows = [(0, 40_000, "Bank on it.")]
    service, _, _ = make(rows, word("bank", "B1"), word("bank", "A2"), word("on"), word("it"))
    assert by_lexeme(service.get_or_build(TRANSCRIPT, "en"))["bank"].level == "A2"


def test_dictionary_reads_are_batched_not_one_per_word():
    text = " ".join(chr(97 + n // 26) + chr(97 + n % 26) for n in range(250))
    service, _, dictionary = make([(0, 60_000, text)])
    service.get_or_build(TRANSCRIPT, "en")
    assert [len(call) for call in dictionary.calls] == [100, 100, 50]


# --- Chinese ------------------------------------------------------------------------------------

def test_chinese_words_are_cut_against_the_dictionary_and_unknown_characters_stay_alone():
    rows = [(0, 5000, "我喜欢学习中文。"), (5000, 9000, "我喜欢龘")]
    service, _, _ = make(rows, *(word(w, level, "zh") for w, level in
                                 [("我", "HSK1"), ("喜欢", "HSK1"), ("学习", "HSK1"), ("中文", "HSK2"), ("喜", None)]))
    items = by_lexeme(service.get_or_build(TRANSCRIPT, "zh"))
    assert items["我"].occurrences == 2 and items["喜欢"].occurrences == 2
    assert items["中文"] == Lexeme("中文", "HSK2", True, 1)
    assert items["龘"] == Lexeme("龘", None, False, 1)


# --- Cache and edges ----------------------------------------------------------------------------

def test_a_second_request_reads_the_cache_and_a_new_version_rebuilds():
    service, store, dictionary = make([(0, 40_000, "She is nice.")], word("she"), word("is"), word("nice"))
    first = service.get_or_build(TRANSCRIPT, "en")
    reads = len(dictionary.calls)
    assert service.get_or_build(TRANSCRIPT, "en").lexemes == first.lexemes
    assert len(dictionary.calls) == reads and store.writes == 1
    store.profile = StoredProfile(TRANSCRIPT, "en", PROFILE_VERSION - 1, 1, 0, 1)
    service.get_or_build(TRANSCRIPT, "en")
    assert store.writes == 2


def test_unsupported_language_and_empty_transcripts_have_no_profile():
    service, store, _ = make([(0, 40_000, "Bonjour tout le monde")])
    assert service.get_or_build(TRANSCRIPT, "fr") is None
    assert service.get_or_build(uuid4(), "en") is None
    assert service.get_or_build(TRANSCRIPT, "en-US") is not None  # a region tag is the same language
    assert store.writes == 1


# --- The learner's own Library ------------------------------------------------------------------

def library(profiles, *, transcripts=None, status="transcript_ready"):
    video = SimpleNamespace(id=VIDEO, processing_status=status, original_language_code="en")
    track = SimpleNamespace(id=TRANSCRIPT, language_code="en", is_original=True, source="caption_track")
    tracks = [track] if transcripts is None else transcripts
    for row in tracks:
        row.video_id = VIDEO
    videos = SimpleNamespace(get_by_id=lambda video_id: video if video_id == VIDEO else None)
    videos.get_many_by_ids = lambda ids: {key: videos.get_by_id(key) for key in ids if key == VIDEO}
    return LibraryLexicalProfiles(
        library=SimpleNamespace(
            get_for_user=lambda library_item_id, user_id: SimpleNamespace(id=ITEM, video_id=VIDEO)
            if (library_item_id, user_id) == (ITEM, OWNER) else None,
            list_for_user=lambda user_id, limit=50: [SimpleNamespace(id=ITEM, video_id=VIDEO)] if user_id == OWNER else []),
        videos=videos,
        transcripts=SimpleNamespace(list_for_video=lambda video_id: tracks, list_for_videos=lambda ids: tracks if VIDEO in ids else []),
        profiles=profiles,
    )


def test_a_profile_is_only_given_for_the_learners_own_ready_video():
    service, _, _ = make([(0, 40_000, "She is nice.")], word("she"), word("is"), word("nice"))
    path = library(service)
    assert path.for_item(SimpleNamespace(id=OWNER), ITEM).profile.token_count == 3
    with pytest.raises(LearnerLibraryError) as other:
        path.for_item(SimpleNamespace(id=OTHER), ITEM)
    assert other.value.status_code == 404
    with pytest.raises(LearnerLibraryError) as not_ready:
        library(service, status="processing").for_item(SimpleNamespace(id=OWNER), ITEM)
    assert (not_ready.value.status_code, not_ready.value.code) == (409, "video_not_ready")


def test_the_library_list_builds_at_most_the_budget_of_missing_profiles():
    service, store, _ = make([(0, 40_000, "She is nice.")], word("she"), word("is"), word("nice"))
    path = library(service)
    assert path.for_library(SimpleNamespace(id=OWNER), build_budget=0)[0][1] is None
    assert store.writes == 0
    assert path.for_library(SimpleNamespace(id=OWNER), build_budget=1)[0][1].profile.token_count == 3
    assert store.writes == 1
    assert path.for_library(SimpleNamespace(id=OTHER), build_budget=1) == []


# --- Inferred compound levels (Chinese) ---------------------------------------------------------

def test_a_compound_without_a_level_takes_the_highest_level_of_its_characters_only_when_all_have_one():
    assert derive_compound_level("每天", {"每": "HSK1", "天": "HSK1"}) == "HSK1"
    assert derive_compound_level("一般", {"一": "HSK1", "般": "HSK4"}) == "HSK4"
    assert derive_compound_level("一般", {"一": "HSK1", "般": None}) is None
    assert derive_compound_level("一般", {"一": "HSK1"}) is None
    assert derive_compound_level("天", {"天": "HSK1"}) is None  # a single character is never derived


def test_the_service_marks_an_inferred_level_and_leaves_a_named_one_alone():
    rows = [(0, 40_000, "每天一起聊天。每天好")]
    entries = [word("每", "HSK1", "zh"), word("天", "HSK1", "zh"), word("每天", None, "zh"), word("一起", "HSK2", "zh"),
               word("聊天", None, "zh"), word("聊", "HSK6", "zh"), word("好", "HSK1", "zh")]
    service, _, _ = make(rows, *entries)
    items = by_lexeme(service.get_or_build(TRANSCRIPT, "zh"))
    assert items["每天"] == Lexeme("每天", "HSK1", True, 2, True)
    assert items["一起"] == Lexeme("一起", "HSK2", True, 1, False)
    assert items["聊天"] == Lexeme("聊天", "HSK6", True, 1, True)  # the highest of 聊 (HSK6) and 天 (HSK1)


def test_library_uses_batch_reads_and_preserves_its_order():
    from unittest.mock import Mock

    path = library(Mock())
    second_item, second_video, second_track = uuid4(), uuid4(), uuid4()
    path.library.list_for_user = Mock(return_value=[SimpleNamespace(id=second_item, video_id=second_video),
                                                   SimpleNamespace(id=ITEM, video_id=VIDEO)])
    path.videos.get_many_by_ids = Mock(return_value={key: SimpleNamespace(id=key, processing_status="transcript_ready",
        original_language_code="en") for key in (VIDEO, second_video)})
    path.transcripts.list_for_videos = Mock(return_value=[
        SimpleNamespace(id=key, video_id=video, source="caption_track", language_code="en", is_original=True)
        for key, video in [(TRANSCRIPT, VIDEO), (second_track, second_video)]
    ])
    path.profiles.cached_many.return_value = {}

    assert path.for_library(SimpleNamespace(id=OWNER), build_budget=0) == [(second_item, None), (ITEM, None)]
    path.videos.get_many_by_ids.assert_called_once_with([second_video, VIDEO])
    path.transcripts.list_for_videos.assert_called_once_with([VIDEO, second_video])
    path.profiles.cached_many.assert_called_once_with([TRANSCRIPT, second_track])
    path.profiles.get_or_build.assert_not_called()
