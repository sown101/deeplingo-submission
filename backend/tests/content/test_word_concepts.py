"""The Concept of a saved word is resolved on the server, never taken from the client."""
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.modules.content.application.library import LearnerLibraryError
from app.modules.content.application.word_concepts import WordConceptService
from app.modules.content.domain.knowledge import Concept, ConceptType, LearningObject
from tests.content.test_word_lookup import GAVE, GIVE, GIVE_UP, ITEM, OTHER, OWNER, VIDEO, service


class FakeConcepts:
    def __init__(self, *concepts):
        self.rows = {item.id: item for item in concepts}
        self.upserts = []

    def get_by_id(self, concept_id):
        return self.rows.get(concept_id)

    def list_by_ids(self, ids):
        return [self.rows[item] for item in ids if item in self.rows]

    def find_by_identity(self, *, language_code, concept_type, normalized_text, sense_key):
        return next((item for item in self.rows.values() if (item.language_code, item.type.value,
                     item.normalized_text, item.sense_key) == (language_code, concept_type, normalized_text,
                                                               sense_key)), None)

    def upsert_by_identity(self, data):
        concept = Concept(id=uuid4(), **data)
        self.rows[concept.id] = concept
        self.upserts.append(data)
        return concept


class FakeLinks:
    def __init__(self):
        self.links = []

    def upsert_link(self, *, concept_id, dictionary_entry_id, relation_type="supports"):
        self.links.append((concept_id, dictionary_entry_id))


def words(text, *entries, objects=(), concepts=()):
    lookup, segment = service(text, *entries)
    store = FakeConcepts(*concepts)
    by_id = {item.id: item for item in entries}
    built = WordConceptService(
        lookup=lookup,
        learning_objects=SimpleNamespace(list_for_video=lambda video_id: list(objects) if video_id == VIDEO else [],
                                         get_by_id=lambda object_id: next(
                                             (item for item in objects if item.id == object_id), None)),
        concepts=store,
        dictionary=SimpleNamespace(get_by_id=by_id.get, list_by_headwords=lookup.dictionary.list_by_headwords),
        links=FakeLinks(),
    )
    return built, segment, store


def save(built, segment, start, end, sense_id=None, user=OWNER):
    return built.from_lookup(SimpleNamespace(id=user), ITEM, segment_id=segment.id, start_codepoint=start,
                             end_codepoint=end, sense_id=sense_id)


def test_a_looked_up_phrase_becomes_one_dictionary_sense_concept_with_a_link():
    built, segment, store = words("I never gave up.", GIVE_UP, GAVE, GIVE)

    concept = save(built, segment, 13, 15, "enwikt:giveup2")  # "up" -> "give up"

    assert (concept.canonical_text, concept.type, concept.language_code) == ("give up", ConceptType.EXPRESSION, "en")
    assert concept.metadata["source"] == "dictionary_sense"
    assert concept.metadata["dictionary_sense_id"] == "enwikt:giveup2"
    assert concept.metadata["sense_gloss"] == "To surrender."
    assert built.links.links == [(concept.id, GIVE_UP.id)]
    # Saving the same sense again reuses the Concept.
    assert save(built, segment, 8, 15, "enwikt:giveup2").id == concept.id and len(store.upserts) == 1


def test_a_sense_the_dictionary_did_not_offer_for_this_span_is_rejected():
    built, segment, store = words("I never gave up.", GIVE_UP, GAVE, GIVE)

    with pytest.raises(LearnerLibraryError) as error:
        save(built, segment, 13, 15, "enwikt:give1")  # a real sense, but of another unit
    assert error.value.code == "sense_not_offered" and not store.upserts

    bare, bare_segment, _ = words("Zorbly words.")
    with pytest.raises(LearnerLibraryError) as missing:
        save(bare, bare_segment, 0, 6)
    assert missing.value.code == "no_dictionary_sense"


def test_another_learners_video_looks_missing():
    built, segment, store = words("I never gave up.", GIVE_UP, GAVE, GIVE)
    with pytest.raises(LearnerLibraryError) as error:
        save(built, segment, 13, 15, user=OTHER)
    assert error.value.status_code == 404 and not store.upserts


def test_the_videos_own_prepared_concept_is_reused_so_it_can_be_practised():
    trusted = Concept(id=uuid4(), language_code="en", type=ConceptType.PHRASAL_VERB, canonical_text="give up",
                      normalized_text="give up", sense_key="stop trying")
    # The occurrence's meaning was translated from this very dictionary sense.
    occurrence = LearningObject(id=uuid4(), concept_id=trusted.id, video_id=VIDEO, transcript_segment_id=uuid4(),
                                evidence_text="give up", start_codepoint=0, end_codepoint=7, start_ms=0, end_ms=1,
                                raw_ai_diagnostics={"enrichments": {"vi": {
                                    "meaning_provenance": "translated_from_sense",
                                    "dictionary_sense": {"dictionary_entry_id": str(GIVE_UP.id),
                                                         "sense_id": "enwikt:giveup1"}}}})
    built, segment, store = words("I never gave up.", GIVE_UP, GAVE, GIVE, objects=[occurrence],
                                  concepts=[trusted])

    assert save(built, segment, 13, 15, "enwikt:giveup1").id == trusted.id
    assert not store.upserts


def test_another_sense_of_the_same_headword_is_never_the_videos_concept():
    """M1 S7d: a lookup of "give up" = surrender must not be recorded as "give up" = stop trying."""
    trusted = Concept(id=uuid4(), language_code="en", type=ConceptType.PHRASAL_VERB, canonical_text="give up",
                      normalized_text="give up", sense_key="stop trying")
    occurrence = LearningObject(id=uuid4(), concept_id=trusted.id, video_id=VIDEO, transcript_segment_id=uuid4(),
                                evidence_text="give up", start_codepoint=0, end_codepoint=7, start_ms=0, end_ms=1,
                                raw_ai_diagnostics={"enrichments": {"vi": {
                                    "meaning_provenance": "translated_from_sense",
                                    "dictionary_sense": {"dictionary_entry_id": str(GIVE_UP.id),
                                                         "sense_id": "enwikt:giveup1"}}}})
    built, segment, store = words("I never gave up.", GIVE_UP, GAVE, GIVE, objects=[occurrence],
                                  concepts=[trusted])
    concept = save(built, segment, 13, 15, "enwikt:giveup2")
    assert concept.id != trusted.id
    assert concept.metadata["dictionary_sense_id"] == "enwikt:giveup2"
    unrecorded = LearningObject(id=uuid4(), concept_id=trusted.id, video_id=VIDEO, transcript_segment_id=uuid4(),
                                evidence_text="give up", start_codepoint=0, end_codepoint=7, start_ms=0, end_ms=1)
    built2, segment2, _ = words("I never gave up.", GIVE_UP, GAVE, GIVE, objects=[unrecorded], concepts=[trusted])
    assert save(built2, segment2, 13, 15, "enwikt:giveup1").id != trusted.id  # no recorded sense: not reused


def test_manual_add_takes_one_sense_of_a_dictionary_entry():
    built, _, store = words("x", GIVE_UP, GIVE)

    concept = built.from_dictionary(language_code="en", entry_id=GIVE.id, sense_id="enwikt:give1")
    assert (concept.canonical_text, concept.type) == ("give", ConceptType.VOCABULARY)

    with pytest.raises(LearnerLibraryError):
        built.from_dictionary(language_code="en", entry_id=GIVE.id, sense_id="enwikt:giveup1")
    with pytest.raises(LearnerLibraryError):
        built.from_dictionary(language_code="zh", entry_id=GIVE.id, sense_id="enwikt:give1")


def test_search_offers_the_base_form_of_an_inflection():
    built, _, _ = words("x", GAVE, GIVE)

    found = built.search(language_code="en", query="  gave ")

    assert [item.headword for item in found] == ["give"]  # "gave" has only an inflection sense
    assert found[0].level == "A1" and found[0].senses[0].text == "To transfer possession."
    assert built.search(language_code="en", query="   ") == []


def test_an_occurrence_outside_the_learners_library_is_not_found():
    trusted = Concept(id=uuid4(), language_code="en", type=ConceptType.VOCABULARY, canonical_text="give",
                      normalized_text="give", sense_key="give")
    elsewhere = LearningObject(id=uuid4(), concept_id=trusted.id, video_id=uuid4(), transcript_segment_id=uuid4(),
                               evidence_text="give", start_codepoint=0, end_codepoint=4, start_ms=0, end_ms=1)
    built, _, _ = words("x", GIVE, objects=[elsewhere], concepts=[trusted])

    with pytest.raises(LearnerLibraryError) as error:
        built.from_occurrence(SimpleNamespace(id=OWNER), ITEM, elsewhere.id)
    assert error.value.status_code == 404

