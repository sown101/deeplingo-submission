"""Dictionary and AI-written examples for saved words, fail closed."""
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.modules.content.application.example_sentences import (
    ExampleSentenceError,
    ExampleSentenceService,
)
from app.modules.content.domain.example_sentences import (
    ExampleSentence,
    ExampleSourceKind,
    find_form_span,
    rejection_reason,
    text_key,
)
from app.modules.content.domain.knowledge import Concept, ConceptType
from app.platform.llm.port import LLMProviderError
from tests.content.test_word_lookup import FakeProvider, entry

OWNER, OTHER = uuid4(), uuid4()
SENSE = {"sense_id": "enwikt:run1", "pos": "verb", "text": "To move quickly on foot.",
         "example": "I run every morning."}
RUN = entry("run", SENSE, metadata={"cefr_j": "A1"})
BARE = entry("walk", {"sense_id": "enwikt:walk1", "text": "To go on foot."})


def concept(headword="run", dictionary_entry=RUN, sense_id="enwikt:run1", gloss="To move quickly on foot.",
            language="en"):
    return Concept(
        id=uuid4(), language_code=language, type=ConceptType.VOCABULARY, canonical_text=headword,
        normalized_text=headword, sense_key=gloss or "x",
        metadata={"sense_gloss": gloss, "dictionary_entry_id": str(dictionary_entry.id),
                  "dictionary_sense_id": sense_id} if gloss else {},
    )


class Store:
    def __init__(self):
        self.rows = []

    def list_for_concept(self, concept_id):
        return [row for row in self.rows if row.concept_id == concept_id]

    def add(self, sentence):
        existing = next((row for row in self.rows if (row.concept_id, row.source_kind, row.text_key)
                         == (sentence.concept_id, sentence.source_kind, sentence.text_key)), None)
        if existing:
            return existing
        stored = sentence.model_copy(update={"id": uuid4()})
        self.rows.append(stored)
        return stored


GOOD = {"sentences": [{"text": "I run to the bus every day.", "translation": "Tôi chạy ra xe buýt mỗi ngày."},
                      {"text": "Do you run in the park?", "translation": "Bạn có chạy trong công viên không?"},
                      {"text": "We run when it rains.", "translation": "Chúng tôi chạy khi trời mưa."}]}


def verdicts(*flags, confidence=0.95):
    return {"verdicts": [{"index": index, "uses_sense": ok, "natural": True, "names_real_person": False,
                          "confidence": confidence} for index, ok in enumerate(flags)]}


def build(word, *outputs, saved_for=(OWNER,), entries=(RUN, BARE)):
    store = Store()
    by_id = {item.id: item for item in entries}
    provider = FakeProvider(*outputs)
    service = ExampleSentenceService(
        saved=SimpleNamespace(concept_ids_for=lambda user_id, ids: {word.id} if user_id in saved_for else set()),
        concepts=SimpleNamespace(get_by_id=lambda concept_id: word if concept_id == word.id else None),
        dictionary=SimpleNamespace(get_by_id=by_id.get), examples=store,
        preferences=SimpleNamespace(get_by_language_for_user=lambda **_: SimpleNamespace(support_language_code="vi")),
        provider=provider,
    )
    return service, store, provider


def user(user_id=OWNER):
    return SimpleNamespace(id=user_id)


# --- Deterministic checks -------------------------------------------------------------------

def test_a_form_must_be_a_whole_word_in_the_sentence():
    assert find_form_span("I run to the bus.", "run", "en") == (2, 5)
    assert find_form_span("The runner is fast.", "run", "en") is None
    assert find_form_span("我每天早上跑步。", "跑步", "zh") == (5, 7)


@pytest.mark.parametrize("text,reason", [
    ("I run https://x.example to school.", "forbidden_content"),
    ("As an AI I run to school.", "prompt_leakage"),
    ("Run!", "length"),
    ("I walk to school every day.", "target_form_missing"),
    ("我每天跑步去学校。", "wrong_script"),
    ("I run to move quickly on foot.", "gloss_leak"),
])
def test_unusable_sentences_are_rejected(text, reason):
    assert rejection_reason(text, "run", "en", gloss="To move quickly on foot.") == reason or \
        rejection_reason(text, "run", "en", gloss="move quickly on foot") == reason


def test_a_good_sentence_passes():
    assert rejection_reason("I run to the bus every day.", "run", "en", gloss="To move quickly on foot.") is None
    assert rejection_reason("我每天早上跑步去学校。", "跑步", "zh") is None


def test_text_key_ignores_case_spacing_and_punctuation():
    assert text_key("I run!") == text_key("  i   RUN ")


# --- Ownership ------------------------------------------------------------------------------

def test_another_learner_gets_the_same_answer_as_a_missing_word():
    word = concept()
    service, _, provider = build(word, saved_for=(OWNER,))
    with pytest.raises(ExampleSentenceError) as other:
        service.list(user(OTHER), word.id)
    with pytest.raises(ExampleSentenceError) as missing:
        service.generate(user(OWNER), uuid4())
    assert (other.value.status_code, other.value.code) == (404, "word_not_found") == \
        (missing.value.status_code, missing.value.code)
    assert provider.prompts == []


# --- Dictionary example first ---------------------------------------------------------------

def test_the_dictionary_example_is_stored_with_its_credit_and_no_model_call():
    word = concept()
    service, store, provider = build(word)
    view = service.list(user(), word.id)
    assert [item.source_kind for item in view.examples] == [ExampleSourceKind.DICTIONARY]
    first = view.examples[0]
    assert first.text == "I run every morning." and (first.start_codepoint, first.end_codepoint) == (2, 5)
    assert not first.ai_generated and first.license_name == "CC BY-SA 4.0" and first.source_name
    assert service.generate(user(), word.id).examples[0].id == first.id
    assert provider.prompts == [] and len(store.rows) == 1


# --- Generated examples ---------------------------------------------------------------------

def test_read_only_examples_never_seed_content_or_call_a_provider():
    word = concept()
    service, store, provider = build(word)
    assert service.list(user(), word.id, read_only=True).examples == []
    assert store.rows == [] and provider.prompts == []
    seeded = service.list(user(), word.id).examples[0]
    snapshot = list(store.rows)
    assert service.list(user(), word.id, read_only=True).examples[0].id == seeded.id
    assert store.rows == snapshot and provider.prompts == []


def test_read_only_examples_still_check_ownership():
    word = concept()
    service, store, provider = build(word)
    with pytest.raises(ExampleSentenceError) as error:
        service.list(user(OTHER), word.id, read_only=True)
    assert (error.value.status_code, error.value.code) == (404, "word_not_found")
    assert store.rows == [] and provider.prompts == []


def test_existing_examples_api_passes_read_only_without_seeding_or_exposing_foreign_words():
    from fastapi.testclient import TestClient
    from app.bootstrap.wiring.content import get_example_sentence_service
    from app.bootstrap.wiring.identity import get_jwt_verifier
    from app.main import app
    from app.modules.identity.contracts import CurrentUser
    word = concept()
    service, store, provider = build(word)
    app.dependency_overrides[get_jwt_verifier] = lambda: SimpleNamespace(verify=lambda token: CurrentUser(id=OWNER))
    app.dependency_overrides[get_example_sentence_service] = lambda: service
    try:
        client = TestClient(app)
        headers = {"Authorization": "Bearer owner.test.jwt"}
        path = f"/api/v1/v3/learner/me/words/{word.id}/examples"
        response = client.get(path + "?read_only=true", headers=headers)
        assert response.status_code == 200 and response.json()["examples"] == []
        assert store.rows == [] and provider.prompts == []
        assert client.get(path + "?read_only=invalid", headers=headers).status_code == 422
        assert client.get(f"/api/v1/v3/learner/me/words/{uuid4()}/examples?read_only=true", headers=headers).status_code == 404
        assert client.get(path, headers=headers).status_code == 200 and len(store.rows) == 1
    finally:
        app.dependency_overrides.clear()

def test_a_word_without_a_dictionary_example_gets_checked_ai_sentences():
    word = concept("walk", BARE, "enwikt:walk1", "To go on foot.")
    outputs = {"sentences": [{"text": "We walk to school together.", "translation": "Chúng tôi đi bộ."},
                             {"text": "I walk my dog at night.", "translation": "Tôi dắt chó đi dạo."},
                             {"text": "She will walk, so run.", "translation": "x"}]}
    service, store, provider = build(word, outputs, verdicts(True, True, True))
    view = service.generate(user(), word.id)
    assert len(view.examples) == 2
    assert all(item.ai_generated and item.translation_language_code == "vi" for item in view.examples)
    saved = store.rows[0]
    assert saved.model_name == "fake" and saved.prompt_version.startswith("example_sentence_v1")
    assert "<word>\nwalk\n</word>" in provider.prompts[0] and "data, not instructions" in provider.prompts[0]


def test_a_sentence_that_fails_the_sense_check_or_confidence_is_not_stored():
    word = concept("walk", BARE, "enwikt:walk1", "To go on foot.")
    outputs = {"sentences": [{"text": "We walk to school together.", "translation": "a"},
                             {"text": "I walk my dog at night.", "translation": "b"}]}
    checks = {"verdicts": [
        {"index": 0, "uses_sense": False, "natural": True, "names_real_person": False, "confidence": 0.99},
        {"index": 1, "uses_sense": True, "natural": True, "names_real_person": False, "confidence": 0.5},
    ]}
    service, store, _ = build(word, outputs, checks)
    with pytest.raises(ExampleSentenceError) as error:
        service.generate(user(), word.id)
    assert (error.value.status_code, error.value.code) == (503, "example_unavailable")
    assert store.rows == []


def test_sentences_failing_deterministic_checks_never_reach_the_sense_check():
    word = concept("walk", BARE, "enwikt:walk1", "To go on foot.")
    outputs = {"sentences": [{"text": "I run to school.", "translation": "a"}]}
    service, store, provider = build(word, outputs)
    with pytest.raises(ExampleSentenceError):
        service.generate(user(), word.id)
    assert len(provider.prompts) == 1 and store.rows == []


@pytest.mark.parametrize("failure_at", [0, 1])
def test_provider_failure_is_unavailable_and_stores_nothing(failure_at):
    word = concept("walk", BARE, "enwikt:walk1", "To go on foot.")
    outputs = [LLMProviderError("down")] if failure_at == 0 else [
        {"sentences": [{"text": "We walk to school together.", "translation": "a"}]}, LLMProviderError("down")]
    service, store, _ = build(word, *outputs)
    with pytest.raises(ExampleSentenceError) as error:
        service.generate(user(), word.id)
    assert error.value.code == "example_unavailable" and store.rows == []


def test_a_word_without_a_dictionary_meaning_is_not_generated():
    word = concept(gloss=None)
    service, _, provider = build(word)
    with pytest.raises(ExampleSentenceError) as error:
        service.generate(user(), word.id)
    assert (error.value.status_code, error.value.code) == (422, "no_dictionary_sense")
    assert provider.prompts == []


def test_the_response_never_carries_learner_state():
    assert set(ExampleSentence.model_fields) >= {"concept_id", "source_kind", "validation"}
    from app.modules.content.application.example_sentences import ExampleSentenceView
    assert not {"mastery", "score", "evidence", "rating"} & set(ExampleSentenceView.model_fields)
