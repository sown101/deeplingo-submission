from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.bootstrap.wiring.identity import get_jwt_verifier
from app.bootstrap.wiring.content import get_concept_interaction_service
from app.modules.identity.contracts import CurrentUser
from app.modules.content.domain.knowledge import Concept, ConceptType, LearningObject
from app.modules.content.domain.catalog import TranscriptSegment, VideoTranscript
from app.modules.content.application.concept_interaction import ConceptInteractionService
from app.main import app


def _enrichment(concept, meaning, explanation="Context-specific explanation."):
    return {
        "concept_id": str(concept.id), "concept_sense_key": concept.sense_key,
        "source_language_code": "en", "target_language_code": "vi",
        "contextual_meaning": meaning, "explanation": explanation,
        "provider": "internal", "model": "fixture", "rubric": "never expose",
    }


@pytest.fixture
def fixture():
    owner, other, item, video_id, transcript_id, segment_id = [uuid4() for _ in range(6)]
    source = "The bank is beside the bank. I put it off, then put it off again."
    finance = Concept(id=uuid4(), language_code="en", type=ConceptType.VOCABULARY,
                      canonical_text="bank", normalized_text="bank", sense_key="financial institution")
    river = Concept(id=uuid4(), language_code="en", type=ConceptType.VOCABULARY,
                    canonical_text="bank", normalized_text="bank", sense_key="river edge")
    delay = Concept(id=uuid4(), language_code="en", type=ConceptType.PHRASAL_VERB,
                    canonical_text="put something off", normalized_text="put something off",
                    sense_key="to delay")
    concepts_by_id = {concept.id: concept for concept in (finance, river, delay)}
    segment = TranscriptSegment(id=segment_id, transcript_id=transcript_id,
                                sequence_number=1, start_ms=0, end_ms=5000, text=source)
    transcript = VideoTranscript(id=transcript_id, video_id=video_id,
                                 language_code="en", source="manual", is_original=True)
    objects = {}
    for concept, text, start, meaning in [
        (finance, "bank", 4, "a financial institution"),
        (river, "bank", 23, "the edge of a river"),
        (delay, "put it off", source.index("put it off"), "to delay doing something"),
        (delay, "put it off", source.rindex("put it off"), "to delay doing something"),
    ]:
        lo = LearningObject(
            id=uuid4(), concept_id=concept.id, video_id=video_id,
            transcript_segment_id=segment_id, evidence_text=text,
            start_codepoint=start, end_codepoint=start + len(text),
            start_ms=0, end_ms=5000,
            raw_ai_diagnostics={"enrichment": _enrichment(concept, meaning),
                                "secret": "hidden diagnostic"},
        )
        objects[lo.id] = lo
    library, learning_objects, segments, transcripts, concepts, preferences = [Mock() for _ in range(6)]
    library.get_for_user.side_effect = lambda library_item_id, user_id: (
        SimpleNamespace(video_id=video_id) if library_item_id == item and user_id == owner else None)
    learning_objects.get_by_id.side_effect = objects.get
    segments.get_by_id.side_effect = lambda value: segment if value == segment_id else None
    transcripts.get_by_id.side_effect = lambda value: transcript if value == transcript_id else None
    concepts.get_by_id.side_effect = concepts_by_id.get
    preferences.get_by_language_for_user.side_effect = lambda user_id, language_code: (
        SimpleNamespace(support_language_code="vi") if user_id == owner and language_code == "en" else None)
    service = ConceptInteractionService(
        library=library, learning_objects=learning_objects, segments=segments,
        transcripts=transcripts, concepts=concepts, preferences=preferences,
    )
    verifier = Mock()
    verifier.verify.side_effect = lambda token: CurrentUser(id=other if token == "other.test.jwt" else owner)
    app.dependency_overrides[get_jwt_verifier] = lambda: verifier
    app.dependency_overrides[get_concept_interaction_service] = lambda: service
    client = TestClient(app)
    try:
        yield SimpleNamespace(
            client=client, url=f"/api/v1/v3/learner/me/library/videos/{item}/learning-objects",
            owner=owner, other=other, item=item, video_id=video_id, segment=segment,
            finance=finance, river=river, delay=delay, objects=objects,
            library=library, learning_objects=learning_objects, preferences=preferences,
        )
    finally:
        app.dependency_overrides.clear()


def _get(fixture, learning_object_id, *, token="owner.test.jwt"):
    return fixture.client.get(
        f"{fixture.url}/{learning_object_id}/concept",
        headers={"Authorization": f"Bearer {token}"},
    )


def test_auth_ownership_missing_and_wrong_video_all_fail_without_enumeration(fixture):
    first_id = next(iter(fixture.objects))
    assert fixture.client.get(f"{fixture.url}/{first_id}/concept").status_code == 401
    denied = _get(fixture, first_id, token="other.test.jwt")
    assert denied.status_code == 404
    fixture.learning_objects.get_by_id.assert_not_called()
    assert _get(fixture, uuid4()).status_code == 404
    fixture.objects[first_id].video_id = uuid4()
    assert _get(fixture, first_id).status_code == 404


def test_polysemy_returns_distinct_contextual_meanings_without_internal_authority(fixture):
    finance_id = next(id for id, row in fixture.objects.items() if row.concept_id == fixture.finance.id)
    river_id = next(id for id, row in fixture.objects.items() if row.concept_id == fixture.river.id)
    finance = _get(fixture, finance_id)
    river = _get(fixture, river_id)
    assert finance.status_code == river.status_code == 200
    assert finance.json()["contextual_meaning"] == "a financial institution"
    assert river.json()["contextual_meaning"] == "the edge of a river"
    assert finance.json()["occurrence_text"] == river.json()["occurrence_text"] == "bank"
    assert finance.json()["start_codepoint"] != river.json()["start_codepoint"]
    for response in (finance, river):
        assert set(response.json()) == {
            "library_item_id", "learning_object_id", "expression", "occurrence_text",
            "source_segment_text", "start_codepoint", "end_codepoint",
            "learning_language_code", "support_language_code", "contextual_meaning", "explanation",
            "meaning_provenance", "dictionary_sense",
        }
        # Items prepared before prompt v2 carry no dictionary sense.
        assert response.json()["meaning_provenance"] == "unverified"
        assert response.json()["dictionary_sense"] is None
        for hidden in ("concept_id", "sense_key", "raw_ai_diagnostics", "rubric", "provider", "model",
                       "review_state", "mastery", "confidence", "secret"):
            assert hidden not in response.text


def test_repeated_same_concept_preserves_selected_occurrence_and_overlap(fixture):
    delays = [(id, row) for id, row in fixture.objects.items() if row.concept_id == fixture.delay.id]
    responses = [_get(fixture, id) for id, _ in delays]
    assert all(response.status_code == 200 for response in responses)
    assert len({response.json()["learning_object_id"] for response in responses}) == 2
    assert len({response.json()["start_codepoint"] for response in responses}) == 2
    assert {response.json()["contextual_meaning"] for response in responses} == {"to delay doing something"}
    # A second valid overlapping LearningObject remains independently addressable.
    outer = fixture.objects[delays[0][0]]
    nested_concept = fixture.delay
    nested = LearningObject(
        id=uuid4(), concept_id=nested_concept.id, video_id=fixture.video_id,
        transcript_segment_id=fixture.segment.id, evidence_text="it off",
        start_codepoint=outer.start_codepoint + 4, end_codepoint=outer.end_codepoint,
        start_ms=0, end_ms=5000,
        raw_ai_diagnostics={"enrichment": _enrichment(nested_concept, "the delayed action")},
    )
    fixture.objects[nested.id] = nested
    assert _get(fixture, outer.id).status_code == 200
    nested_response = _get(fixture, nested.id)
    assert nested_response.status_code == 200
    assert nested_response.json()["occurrence_text"] == "it off"


def test_missing_or_wrong_language_context_is_not_guessed(fixture):
    object_id = next(iter(fixture.objects))
    fixture.objects[object_id].raw_ai_diagnostics = {}
    response = _get(fixture, object_id)
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "concept_context_unavailable"
    fixture.objects[object_id].raw_ai_diagnostics = {
        "enrichment": _enrichment(fixture.finance, "a financial institution")}
    fixture.objects[object_id].raw_ai_diagnostics["enrichment"]["target_language_code"] = "ja"
    assert _get(fixture, object_id).status_code == 409
    fixture.preferences.get_by_language_for_user.return_value = None
    fixture.preferences.get_by_language_for_user.side_effect = None
    assert _get(fixture, object_id).json()["detail"]["code"] == "support_language_unavailable"


def test_optional_missing_explanation_and_stale_span(fixture):
    object_id = next(iter(fixture.objects))
    fixture.objects[object_id].raw_ai_diagnostics["enrichment"]["explanation"] = None
    assert _get(fixture, object_id).json()["explanation"] is None
    fixture.objects[object_id].evidence_text = "not in source"
    assert _get(fixture, object_id).status_code == 404


def test_support_language_selects_matching_prepared_context(fixture):
    object_id = next(iter(fixture.objects))
    row = fixture.objects[object_id]
    row.raw_ai_diagnostics = {
        "enrichments": {
            "vi": _enrichment(fixture.finance, "ngân hàng"),
            "ja": {**_enrichment(fixture.finance, "銀行"), "target_language_code": "ja"},
        }
    }
    assert _get(fixture, object_id).json()["contextual_meaning"] == "ngân hàng"
    fixture.preferences.get_by_language_for_user.side_effect = lambda **_: SimpleNamespace(
        support_language_code="ja")
    assert _get(fixture, object_id).json()["contextual_meaning"] == "銀行"


def _dictionary_enrichment(concept, meaning, *, provider="en-wiktionary", headword="put off"):
    return {**_enrichment(concept, meaning), "meaning_provenance": "translated_from_sense",
            "sense_id": "enwikt:00000000000000d1",
            "dictionary_sense": {"sense_id": "enwikt:00000000000000d1", "dictionary_entry_id": str(uuid4()),
                                 "headword": headword, "text": "To delay doing something; to postpone.",
                                 "pos": "verb", "reading": None, "provider": provider}}


def test_dictionary_meaning_carries_its_sense_and_licence_credit(fixture):
    object_id = next(id for id, row in fixture.objects.items() if row.concept_id == fixture.delay.id)
    fixture.objects[object_id].raw_ai_diagnostics = {
        "enrichment": _dictionary_enrichment(fixture.delay, "trì hoãn", headword="put off")}

    body = _get(fixture, object_id).json()

    assert body["meaning_provenance"] == "dictionary"
    assert body["dictionary_sense"] == {
        "headword": "put off", "reading": None, "part_of_speech": "verb",
        "definition": "To delay doing something; to postpone.",
        "source_name": "Wiktionary", "source_url": "https://en.wiktionary.org/wiki/put_off",
        "license_name": "CC BY-SA 4.0", "license_url": "https://creativecommons.org/licenses/by-sa/4.0/",
    }
    for hidden in ("sense_id", "dictionary_entry_id", "enwikt:"):
        assert hidden not in str(body)


def test_chinese_dictionary_sense_shows_reading_and_cedict_credit(fixture):
    object_id = next(iter(fixture.objects))
    enrichment = _dictionary_enrichment(fixture.finance, "ngân hàng", provider="cc-cedict", headword="银行")
    enrichment["dictionary_sense"].update(text="bank", pos=None, reading="yin2 hang2")
    fixture.objects[object_id].raw_ai_diagnostics = {"enrichment": enrichment}

    sense = _get(fixture, object_id).json()["dictionary_sense"]

    assert (sense["reading"], sense["source_name"], sense["part_of_speech"]) == ("yin2 hang2", "CC-CEDICT", None)
    assert sense["source_url"] == "https://www.mdbg.net/chinese/dictionary?page=cc-cedict"


@pytest.mark.parametrize("change", [
    {"meaning_provenance": "ai_unverified"},
    {"dictionary_sense": None},
    {"dictionary_sense": {"headword": "put off", "text": "delay", "provider": "unknown-dictionary"}},
])
def test_unverified_or_uncredited_meanings_are_never_shown_as_dictionary(fixture, change):
    object_id = next(iter(fixture.objects))
    fixture.objects[object_id].raw_ai_diagnostics = {
        "enrichment": {**_dictionary_enrichment(fixture.finance, "ngân hàng"), **change}}

    body = _get(fixture, object_id).json()

    assert body["meaning_provenance"] == "unverified" and body["dictionary_sense"] is None
    assert body["contextual_meaning"] == "ngân hàng"


def test_overlong_dictionary_text_is_clipped_not_dropped(fixture):
    object_id = next(iter(fixture.objects))
    enrichment = _dictionary_enrichment(fixture.finance, "ngân hàng")
    enrichment["dictionary_sense"]["text"] = "word " * 400
    fixture.objects[object_id].raw_ai_diagnostics = {"enrichment": enrichment}

    sense = _get(fixture, object_id).json()["dictionary_sense"]

    assert len(sense["definition"]) == 1000 and sense["definition"].endswith("…")
