"""My words: saving is a request, the server resolves the concept."""
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.bootstrap.wiring.identity import get_jwt_verifier
from app.bootstrap.wiring.learner import get_my_words_service
from app.main import app
from app.modules.content.domain.knowledge import Concept, ConceptType
from app.modules.identity.contracts import CurrentUser
from app.modules.learner.application.my_words import (
    MyWordsError,
    MyWordsService,
    SaveFromDictionary,
    SaveFromLookup,
    SaveFromOccurrence,
)
from app.modules.learner.domain.concept_lists import ConceptList, SaveSource

USER = UUID("11111111-1111-1111-1111-111111111111")
ITEM = uuid4()


class FakeSaved:
    def __init__(self):
        self.rows: dict[UUID, dict] = {}

    def list_for_user(self, user_id):
        return list(self.rows.values()) if user_id == USER else []

    def save(self, user_id, *, concept_id, save_source, source_learning_object_id=None):
        self.rows.setdefault(concept_id, {"concept_id": concept_id, "save_source": save_source,
                                          "created_at": datetime(2026, 10, 16, tzinfo=UTC)})
        return self.rows[concept_id]

    def remove(self, user_id, *, concept_id):
        return self.rows.pop(concept_id, None) is not None


def concept(text="give up"):
    return Concept(id=uuid4(), language_code="en", type=ConceptType.EXPRESSION, canonical_text=text,
                   normalized_text=text, sense_key=text, metadata={"sense_gloss": "To stop trying."})


def service(resolved=None, *, learns_en=True):
    resolved = resolved or concept()
    resolver = Mock()
    resolver.from_lookup.return_value = resolved
    resolver.from_dictionary.return_value = resolved
    resolver.from_occurrence.return_value = resolved
    due = datetime(2026, 10, 20, tzinfo=UTC)
    return MyWordsService(
        saved=FakeSaved(), resolver=resolver,
        concepts=SimpleNamespace(list_by_ids=lambda ids: [resolved] if resolved.id in ids else []),
        reviews=SimpleNamespace(next_due_by_concept=lambda **kwargs: {resolved.id: due}),
        preferences=SimpleNamespace(get_by_language_for_user=lambda **kwargs: (
            object() if learns_en and kwargs["language_code"] == "en" else None)),
    ), resolved


def me():
    return CurrentUser(id=USER, role="authenticated", claims={})


def test_saving_from_a_lookup_passes_only_selectors_to_the_content_resolver():
    words, resolved = service()
    view = words.save(me(), SaveFromLookup(source="lookup", library_item_id=ITEM, segment_id=uuid4(),
                                           start_codepoint=8, end_codepoint=15, sense_id="enwikt:giveup1"))
    assert (view.text, view.list, view.save_source, view.gloss) == ("give up", ConceptList.SAVED,
                                                                   SaveSource.LOOKUP, "To stop trying.")
    assert view.next_review_at is not None
    assert words.resolver.from_lookup.call_args.args[1] == ITEM


def test_saving_a_word_lists_it_and_removing_it_clears_it():
    words, resolved = service()
    view = words.save(me(), SaveFromOccurrence(source="occurrence", library_item_id=ITEM,
                                               learning_object_id=uuid4()))
    assert view.list == ConceptList.SAVED and view.saved is True
    assert [row.list for row in words.list(me(), "en").words] == [ConceptList.SAVED]
    words.remove(me(), resolved.id)
    assert not words.saved.rows


def test_manual_words_need_a_language_the_learner_studies():
    words, _ = service(learns_en=False)
    with pytest.raises(MyWordsError) as error:
        words.save(me(), SaveFromDictionary(source="dictionary", language_code="EN", entry_id=uuid4(),
                                            sense_id="enwikt:give1"))
    assert error.value.code == "language_not_learned"
    words.resolver.from_dictionary.assert_not_called()


def test_content_request_errors_keep_their_status_and_code():
    words, _ = service()
    failure = ValueError("That meaning is not offered for this word.")
    failure.status_code, failure.code = 422, "sense_not_offered"
    words.resolver.from_lookup.side_effect = failure
    with pytest.raises(MyWordsError) as error:
        words.save(me(), SaveFromLookup(source="lookup", library_item_id=ITEM, segment_id=uuid4(),
                                        start_codepoint=0, end_codepoint=2))
    assert (error.value.status_code, error.value.code) == (422, "sense_not_offered")


def test_removing_a_word_that_is_not_listed_is_not_found():
    words, _ = service()
    with pytest.raises(MyWordsError) as error:
        words.remove(me(), uuid4())
    assert error.value.status_code == 404


@pytest.fixture
def api():
    verifier = Mock()
    verifier.verify.side_effect = lambda token: CurrentUser(id=USER)
    words, resolved = service()
    app.dependency_overrides[get_jwt_verifier] = lambda: verifier
    app.dependency_overrides[get_my_words_service] = lambda: words
    try:
        yield SimpleNamespace(client=TestClient(app), words=words, concept=resolved,
                              headers={"Authorization": "Bearer owner.test.jwt"})
    finally:
        app.dependency_overrides.clear()


def test_words_api_saves_lists_and_removes(api):
    url = "/api/v1/v3/learner/me/words"
    assert api.client.get(url).status_code == 401
    body = {"source": "occurrence", "library_item_id": str(ITEM), "learning_object_id": str(uuid4())}
    saved = api.client.post(url, json=body, headers=api.headers)
    assert saved.status_code == 200 and saved.json()["list"] == "saved"
    assert [row["text"] for row in api.client.get(url, headers=api.headers).json()["words"]] == ["give up"]
    assert api.client.delete(f"{url}/{api.concept.id}", headers=api.headers).status_code == 204
    assert api.client.delete(f"{url}/{api.concept.id}", headers=api.headers).status_code == 404


@pytest.mark.parametrize("forged", [
    {"list": "known"}, {"concept_id": str(uuid4())}, {"user_id": str(uuid4())}, {"source": "quick_check"},
    {"known": True},
])
def test_clients_cannot_claim_known_or_choose_the_concept(api, forged):
    body = {"source": "occurrence", "library_item_id": str(ITEM), "learning_object_id": str(uuid4()), **forged}
    response = api.client.post("/api/v1/v3/learner/me/words", json=body, headers=api.headers)
    assert response.status_code == 422
    assert not api.words.saved.rows


def test_familiarization_can_read_only_the_recognition_schedule_on_existing_words_api(api):
    api.words.saved.save(USER, concept_id=api.concept.id, save_source="manual")
    api.words.reviews = Mock()
    due = datetime(2026, 10, 20, tzinfo=UTC)
    api.words.reviews.next_due_by_concept.return_value = {api.concept.id: due}
    response = api.client.get("/api/v1/v3/learner/me/words?language_code=en&recognition_only=true", headers=api.headers)
    assert response.status_code == 200 and response.json()["words"][0]["next_review_at"].startswith("2026-10-20")
    api.words.reviews.next_due_by_concept.assert_called_once_with(
        user_id=USER, concept_ids=[api.concept.id], recognition_only=True)
    assert api.client.get("/api/v1/v3/learner/me/words?recognition_only=invalid", headers=api.headers).status_code == 422
