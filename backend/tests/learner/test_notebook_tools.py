"""The notebook's learner marks, reference data and word speech (the memory rating is in tests/practice)."""
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.modules.content.application.word_reference import WordReferenceError, WordReferenceService
from app.modules.content.domain.pinyin import readable_pinyin
from app.modules.learning.application.speaking_ports import SpeakingPracticeError
from app.modules.learning.application.word_speech import WordSpeechService


@pytest.mark.parametrize("numbered,expected", [
    ("yin2 hang2", "yínháng"), ("ka3; qia3", "kǎ"), ("ma1 ma5", "māma"), ("nu:3 er2", "nǚér"),
    ("xiu1", "xiū"), ("gou3", "gǒu"), ("lei4", "lèi"), (None, None), ("", None),
])
def test_readable_pinyin(numbered, expected):
    assert readable_pinyin(numbered) == expected


class FakeDictionary:
    def count_by_level(self, language_code, field, value):
        return 7

    def page_by_level(self, language_code, field, value, *, offset, limit):
        return [{"id": uuid4(), "headword": "银行", "language_code": "zh", "pronunciation": "yin2 hang2",
                 "definitions": [{"text": "bank", "sense_id": "s1", "traditional": "銀行"}]},
                {"id": uuid4(), "headword": "no-sense", "language_code": "zh", "pronunciation": None, "definitions": []}]

    def rows_for_texts(self, language_code, texts):
        return [{"headword": text, "language_code": language_code, "pronunciation": "yin2", "part_of_speech": "",
                 "definitions": [{"text": "to bank (of a river); x", "reading": "yin2", "sense_id": "a"}],
                 "provider_metadata": {"hsk": "HSK2"}} for text in texts]

    def rows_containing(self, language_code, text, *, limit):
        return []


class FakeImages:
    def __init__(self, rows=()):
        self.rows, self.saved = list(rows), []

    def list_for(self, concept_ids):
        return self.rows

    def save(self, row):
        self.saved.append(row)


class FakeSearch:
    def __init__(self):
        self.calls = []

    def search(self, term, *, index):
        self.calls.append((term, index))
        return {"image_url": f"https://img/{index}", "thumbnail_url": None, "title": None, "creator": None,
                "license": "cc0", "source_url": None}


class FakeConcepts:
    def __init__(self, concept):
        self.concept = concept

    def get_by_id(self, concept_id):
        return self.concept if concept_id == self.concept.id else None

    def list_by_ids(self, concept_ids):
        return [self.concept] if self.concept.id in concept_ids else []


def reference(concept=None, images=None, search=None):
    concept = concept or SimpleNamespace(id=uuid4(), language_code="zh", canonical_text="银行")
    return WordReferenceService(dictionary=FakeDictionary(), concepts=FakeConcepts(concept), images=images or FakeImages(),
                                image_search=search), concept


def test_a_set_lists_words_with_a_sense_and_readable_pinyin():
    service, _ = reference()
    detail = service.set_detail("hsk1", offset=0)
    assert [(word.text, word.reading, word.traditional, word.meaning) for word in detail.words] == [("银行", "yínháng", "銀行", "bank")]


def test_an_unknown_set_is_not_found():
    service, _ = reference()
    with pytest.raises(WordReferenceError) as error:
        service.set_detail("hsk99", offset=0)
    assert error.value.status_code == 404


def test_a_picture_is_searched_once_by_the_english_meaning_then_reused():
    images, search = FakeImages(), FakeSearch()
    service, concept = reference(images=images, search=search)
    views = service.images_for([concept.id])
    assert search.calls == [("bank", 0)]
    assert views[0].image_url == "https://img/0"
    images.rows = images.saved
    service.images_for([concept.id])
    assert len(search.calls) == 1


def test_refresh_asks_for_the_next_picture():
    concept = SimpleNamespace(id=uuid4(), language_code="en", canonical_text="harbour")
    images = FakeImages([{"concept_id": concept.id, "image_url": "old", "search_term": "harbour", "result_index": 1}])
    search = FakeSearch()
    service, _ = reference(concept=concept, images=images, search=search)
    views = service.images_for([concept.id], refresh=concept.id)
    assert search.calls == [("harbour", 2)]
    assert views[0].image_url == "https://img/2"


class FakeSynth:
    provider_name = "fake"

    def __init__(self):
        self.calls = 0

    def supports(self, language_code):
        return True

    def synthesize(self, text, *, language_code):
        self.calls += 1
        return SimpleNamespace(audio=b"mp3", mime_type="audio/mpeg", characters=len(text))


def speech(known=True, synth=None):
    return WordSpeechService(dictionary=SimpleNamespace(has_headword=lambda language, text: known),
                             synthesizer=synth, assessor=None, consent=None, scores=None)


def test_word_audio_is_synthesised_once():
    synth = FakeSynth()
    service = speech(synth=synth)
    assert service.audio("zh", "银行") == b"mp3"
    assert service.audio("zh", "银行") == b"mp3"
    assert synth.calls == 1


def test_only_dictionary_words_are_read_aloud():
    synth = FakeSynth()
    with pytest.raises(SpeakingPracticeError) as error:
        speech(known=False, synth=synth).audio("en", "anything a client sends")
    assert error.value.code == "word_not_in_dictionary"
    assert synth.calls == 0


def test_a_saved_word_is_read_aloud_even_when_the_dictionary_lacks_it():
    synth = FakeSynth()
    assert speech(known=False, synth=synth).audio("en", "book club", saved=True) == b"mp3"
    assert synth.calls == 1


def test_the_word_audio_route_has_its_own_rate_limit():
    """Regression (owner feedback 2026-11-14, "Từ này chưa có âm thanh" for "book"): the route asked the limiter for
    an action it did not know, so every request failed before any audio was made."""
    from fastapi.testclient import TestClient

    from app.bootstrap.wiring.speaking import get_speaking_rate_limiter, get_word_speech_service
    from app.main import app
    from app.modules.identity.api.dependencies import require_authenticated_user
    from app.modules.identity.contracts import CurrentUser

    get_speaking_rate_limiter.cache_clear()
    app.dependency_overrides[get_word_speech_service] = lambda: speech(synth=FakeSynth())
    app.dependency_overrides[require_authenticated_user] = lambda: CurrentUser(id=uuid4())
    try:
        response = TestClient(app).get("/api/v1/v3/learner/me/dictionary/audio",
                                       params={"language_code": "en", "text": "book"})
    finally:
        app.dependency_overrides.pop(get_word_speech_service, None)
        app.dependency_overrides.pop(require_authenticated_user, None)
    assert response.status_code == 200 and response.content == b"mp3"
