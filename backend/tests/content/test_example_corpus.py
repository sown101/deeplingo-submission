"""Licensed corpus examples sit between the dictionary and AI sentences."""
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.modules.content.application.example_sentences import ExampleSentenceError
from app.modules.content.domain.example_sentences import ExampleSourceKind
from app.platform.llm.port import LLMProviderError
from tests.content.test_example_sentences import BARE, RUN, build, concept, user, verdicts


def corpus_row(source_id, text, author="alice", translation="Tôi bỏ cuộc."):
    return {"id": str(uuid4()), "source": "tatoeba", "source_id": source_id, "text": text, "author": author,
            "license": "CC BY 2.0 FR", "translation": translation}


class FakeCorpus:
    def __init__(self, rows, error=None):
        self.rows, self.error, self.calls = rows, error, []

    def find_candidates(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.rows


def walk():
    return concept("walk", BARE, "enwikt:walk1", "To go on foot.")


def with_corpus(word, corpus, *outputs, entries=(BARE,)):
    service, store, provider = build(word, *outputs, entries=entries)
    service.corpus = corpus
    return service, store, provider


AI = {"sentences": [{"text": "I walk my dog at night.", "translation": "b"}]}


def test_a_checked_corpus_sentence_is_stored_with_author_and_licence_and_beats_ai():
    word = walk()
    corpus = FakeCorpus([corpus_row(11, "We walk to school together."), corpus_row(12, "He walks fast.")])
    service, store, provider = with_corpus(word, corpus, verdicts(True))

    view = service.generate(user(), word.id)

    assert [item.source_kind for item in view.examples] == [ExampleSourceKind.CORPUS]
    shown = view.examples[0]
    assert shown.text == "We walk to school together." and not shown.ai_generated
    assert (shown.source_name, shown.license_name, shown.author) == ("Tatoeba", "CC BY 2.0 FR", "alice")
    assert shown.license_url.endswith("/by/2.0/fr/") and shown.source_url.endswith("/sentences/show/11")
    assert shown.translation == "Tôi bỏ cuộc." and (shown.start_codepoint, shown.end_codepoint) == (3, 7)
    assert corpus.calls[0]["translation_language"] == "vi"
    assert len(provider.prompts) == 1  # one sense check, no AI sentence was written
    assert store.rows[0].source_ref.startswith("https://tatoeba.org/")


def test_a_sentence_that_fails_the_sense_check_falls_back_to_an_ai_sentence():
    word = walk()
    corpus = FakeCorpus([corpus_row(11, "We walk to school together.")])
    service, store, provider = with_corpus(word, corpus, verdicts(False), AI, verdicts(True))

    view = service.generate(user(), word.id)

    assert [item.source_kind for item in view.examples] == [ExampleSourceKind.GENERATED]
    assert view.examples[0].ai_generated and view.examples[0].author is None


def test_corpus_text_without_the_exact_word_is_never_checked_or_stored():
    word = walk()
    corpus = FakeCorpus([corpus_row(11, "He walks fast."), corpus_row(12, "Run to the bus now please.")])
    service, store, provider = with_corpus(word, corpus, AI, verdicts(True))

    service.generate(user(), word.id)

    assert all("He walks fast." not in prompt for prompt in provider.prompts)
    assert [row.source_kind for row in store.rows] == [ExampleSourceKind.GENERATED]


def test_a_search_failure_falls_through_and_a_model_outage_stores_nothing():
    word = walk()
    broken, _, _ = with_corpus(word, FakeCorpus([], error=RuntimeError("down")), AI, verdicts(True))
    assert broken.generate(user(), word.id).examples[0].ai_generated

    other = walk()
    outage, store, _ = with_corpus(other, FakeCorpus([corpus_row(11, "We walk to school together.")]),
                                   LLMProviderError("down"), LLMProviderError("down"))
    with pytest.raises(ExampleSentenceError) as error:
        outage.generate(user(), other.id)
    assert error.value.code == "example_unavailable" and store.rows == []


def test_the_dictionary_example_comes_first_and_no_corpus_search_happens():
    word = concept()
    corpus = FakeCorpus([corpus_row(11, "We run to school together.")])
    service, _, provider = with_corpus(word, corpus, entries=(RUN,))
    view = service.generate(user(), word.id)
    assert view.examples[0].source_kind == ExampleSourceKind.DICTIONARY
    assert corpus.calls == [] and provider.prompts == []


def test_only_the_owner_reaches_the_corpus():
    word = walk()
    corpus = FakeCorpus([corpus_row(11, "We walk to school together.")])
    service, _, provider = with_corpus(word, corpus, verdicts(True))
    other = SimpleNamespace(id=uuid4())
    with pytest.raises(ExampleSentenceError) as error:
        service.generate(other, word.id)
    assert error.value.code == "word_not_found" and corpus.calls == [] and provider.prompts == []
