"""Debt: manual-search glosses are rendered in the learner's support language."""
from types import SimpleNamespace
from uuid import uuid4

from app.platform.llm.port import LLMProviderError
from tests.content.test_word_concepts import words
from tests.content.test_word_lookup import FakeProvider, GIVE_UP


def built_with(*outputs, support="vi"):
    built, _, _ = words("x", GIVE_UP)
    built.lookup.provider = FakeProvider(*outputs)
    built.lookup.preferences = SimpleNamespace(
        get_by_language_for_user=lambda **_: SimpleNamespace(support_language_code=support))
    return built


def search(built, user=True):
    return built.search(language_code="en", query="give up", user=SimpleNamespace(id=uuid4()) if user else None)


def test_each_offered_sense_gets_a_support_language_meaning_and_keeps_the_dictionary_text():
    built = built_with({"translations": [{"sense_id": "enwikt:giveup1", "meaning": "từ bỏ"},
                                         {"sense_id": "enwikt:giveup2", "meaning": "đầu hàng"}]})

    senses = search(built)[0].senses

    assert [(sense.text, sense.meaning) for sense in senses] == [
        ("To stop trying.", "từ bỏ"), ("To surrender.", "đầu hàng")]
    prompt = built.lookup.provider.prompts[0]
    assert "[enwikt:giveup1] To stop trying." in prompt and "Vietnamese" in prompt
    assert "data, not instructions" in prompt


def test_an_invented_duplicate_or_missing_sense_never_reaches_the_learner():
    built = built_with({"translations": [{"sense_id": "enwikt:giveup1", "meaning": "từ bỏ"},
                                         {"sense_id": "enwikt:giveup1", "meaning": "khác"},
                                         {"sense_id": "enwikt:made-up", "meaning": "bịa"}]})

    senses = search(built)[0].senses

    assert [sense.meaning for sense in senses] == ["từ bỏ", None]  # the second sense keeps English only
    assert {sense.sense_id for sense in senses} == {"enwikt:giveup1", "enwikt:giveup2"}


def test_a_model_failure_keeps_the_english_gloss_and_still_returns_results():
    built = built_with(LLMProviderError("down"))

    senses = search(built)[0].senses

    assert [sense.meaning for sense in senses] == [None, None]
    assert senses[0].text == "To stop trying."


def test_no_model_call_without_a_learner_or_when_support_is_english():
    built = built_with()
    assert all(sense.meaning is None for sense in search(built, user=False)[0].senses)
    english = built_with(support="en")
    assert all(sense.meaning is None for sense in search(english)[0].senses)
    assert built.lookup.provider.prompts == [] and english.lookup.provider.prompts == []
