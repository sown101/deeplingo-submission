from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from app.modules.content.domain.knowledge import (
    Concept,
    ConceptType,
    DictionaryEntry,
    LLMLearningObjectEnrichment,
    LearningObject,
)
from app.modules.content.domain.catalog import (
    SegmentTranslation,
    TranscriptSegment,
    VideoTranscript,
)
from app.modules.content.application.enrichment import (
    LearningObjectEnrichmentError,
    LearningObjectEnrichmentService,
)
from app.platform.llm.port import LLMProviderError


LO_ID = UUID("11111111-1111-1111-1111-111111111111")
CONCEPT_ID = UUID("22222222-2222-2222-2222-222222222222")
SEGMENT_ID = UUID("33333333-3333-3333-3333-333333333333")
TRANSCRIPT_ID = UUID("44444444-4444-4444-4444-444444444444")
VIDEO_ID = UUID("55555555-5555-5555-5555-555555555555")
USER_ID = UUID("66666666-6666-6666-6666-666666666666")


def make_learning_object(**overrides):
    data = {
        "id": LO_ID,
        "concept_id": CONCEPT_ID,
        "video_id": VIDEO_ID,
        "transcript_segment_id": SEGMENT_ID,
        "occurrence_index": 1,
        "evidence_text": "putting it off",
        "start_ms": 1000,
        "end_ms": 3500,
        "raw_ai_diagnostics": {},
    }
    data.update(overrides)
    return LearningObject(**data)


def make_concept(concept_type=ConceptType.PHRASAL_VERB, **overrides):
    data = {
        "id": CONCEPT_ID,
        "language_code": "en",
        "type": concept_type,
        "canonical_text": "put something off",
        "normalized_text": "put something off",
        "sense_key": "to delay doing something",
    }
    data.update(overrides)
    return Concept(**data)


def make_segment(**overrides):
    data = {
        "id": SEGMENT_ID,
        "transcript_id": TRANSCRIPT_ID,
        "sequence_number": 2,
        "start_ms": 1000,
        "end_ms": 3500,
        "text": "I kept putting it off for weeks.",
    }
    data.update(overrides)
    return TranscriptSegment(**data)


def make_transcript(language_code="en"):
    return VideoTranscript(id=TRANSCRIPT_ID, video_id=VIDEO_ID, language_code=language_code, source="caption_track")


def valid_ai(**overrides):
    data = {
        "sense_id": None,
        "contextual_meaning": "to delay doing something",
        "explanation": "Here, 'put something off' means delaying the task in this situation.",
        "difficulty": {"framework": "CEFR", "level": "B1", "score": 0.45, "confidence": 0.72},
        "learning_value": {"score": 0.86, "confidence": 0.8, "rationale": "Common and useful in conversation."},
        "confidence": 0.78,
    }
    data.update(overrides)
    return LLMLearningObjectEnrichment.model_validate(data)


class FakeProvider:
    provider_name = "fake_provider"
    model_name = "fake_model"

    def __init__(self, response=None, error=None):
        self.response = response or valid_ai()
        self.error = error
        self.calls = 0
        self.last_prompt = None

    def enrich(self, prompt):
        self.calls += 1
        self.last_prompt = prompt
        if self.error:
            raise self.error
        return self.response


class FakeLearningObjects:
    def __init__(self, row=None):
        self.row = row or make_learning_object()
        self.update_count = 0

    def get_by_id(self, learning_object_id):
        return self.row if learning_object_id == self.row.id else None

    def update_enrichment(self, learning_object_id, data):
        self.update_count += 1
        self.row = self.row.model_copy(update=data)
        return self.row

    def record_sense_review(self, learning_object_id, *, target_language_code, review, raw_ai_diagnostics):
        self.update_count += 1
        self.last_review = (target_language_code, review)
        self.row = self.row.model_copy(update={"raw_ai_diagnostics": raw_ai_diagnostics})
        return self.row


class FakeConcepts:
    def __init__(self, row=None):
        self.row = row or make_concept()

    def get_by_id(self, concept_id):
        return self.row if concept_id == self.row.id else None


class FakeSegments:
    def __init__(self, row=None, previous=None, next_=None):
        self.row = row or make_segment()
        self.previous = previous or make_segment(id=uuid4(), sequence_number=1, text="The deadline was near.")
        self.next = next_ or make_segment(id=uuid4(), sequence_number=3, text="Then I finally finished it.")

    def get_by_id(self, segment_id):
        return self.row if segment_id == self.row.id else None

    def get_neighbor(self, *, transcript_id, sequence_number, offset):
        if transcript_id != self.row.transcript_id or sequence_number != self.row.sequence_number:
            return None
        return self.previous if offset == -1 else self.next if offset == 1 else None


class FakeTranscripts:
    def __init__(self, row=None):
        self.row = row or make_transcript()

    def get_by_id(self, transcript_id):
        return self.row if transcript_id == self.row.id else None


class FakeTranslations:
    def __init__(self, row=None):
        self.row = row

    def get_by_segment_language(self, transcript_segment_id, language_code):
        if self.row and transcript_segment_id == self.row.transcript_segment_id and language_code == self.row.language_code:
            return self.row
        return None


class FakeLinks:
    def __init__(self, dictionary_entry_id=None):
        self.dictionary_entry_id = dictionary_entry_id

    def list_for_concept(self, concept_id):
        if self.dictionary_entry_id is None:
            return []
        from app.modules.content.domain.knowledge import ConceptDictionaryLink

        return [ConceptDictionaryLink(concept_id=concept_id, dictionary_entry_id=self.dictionary_entry_id)]


class FakeDictionaryEntries:
    def __init__(self, row=None):
        self.row = row

    def get_by_id(self, dictionary_entry_id):
        return self.row if self.row and dictionary_entry_id == self.row.id else None

    def get_many_by_ids(self, entry_ids):
        return {key: self.row for key in entry_ids if self.row and key == self.row.id}


def make_service(
    *,
    learning_object=None,
    concept=None,
    segment=None,
    transcript=None,
    translation=None,
    dictionary_entry=None,
    provider=None,
):
    entry_id = dictionary_entry.id if dictionary_entry else None
    objects = FakeLearningObjects(learning_object)
    service = LearningObjectEnrichmentService(
        learning_objects=objects,
        concepts=FakeConcepts(concept),
        segments=FakeSegments(segment),
        transcripts=FakeTranscripts(transcript),
        translations=FakeTranslations(translation),
        concept_dictionary_links=FakeLinks(entry_id),
        dictionary_entries=FakeDictionaryEntries(dictionary_entry),
        provider=provider or FakeProvider(),
    )
    return service, objects, service.provider


def test_existing_learning_object_can_be_loaded_and_enriched():
    service, objects, provider = make_service()

    result = service.enrich(LO_ID, target_language_code="vi")

    assert result.learning_object_id == LO_ID
    assert result.contextual_meaning == "to delay doing something"
    assert objects.row.difficulty_score == 0.45
    assert objects.row.learning_value_score == 0.86
    assert provider.calls == 1


def test_missing_learning_object_returns_none():
    service, _, provider = make_service()

    result = service.enrich(uuid4(), target_language_code="vi")

    assert result is None
    assert provider.calls == 0


def test_missing_concept_fails_safely_without_update():
    service, objects, _ = make_service(concept=make_concept(id=uuid4()))

    with pytest.raises(LearningObjectEnrichmentError):
        service.enrich(LO_ID, target_language_code="vi")

    assert objects.update_count == 0


def test_missing_transcript_segment_fails_safely_without_update():
    service, objects, _ = make_service(segment=make_segment(id=uuid4()))

    with pytest.raises(LearningObjectEnrichmentError):
        service.enrich(LO_ID, target_language_code="vi")

    assert objects.update_count == 0


def test_existing_translation_is_reused_and_provider_still_gets_it_as_context():
    translation = SegmentTranslation(
        transcript_segment_id=SEGMENT_ID,
        language_code="vi",
        text="Tôi cứ trì hoãn việc đó suốt nhiều tuần.",
        source="manual",
    )
    service, objects, provider = make_service(translation=translation)

    result = service.enrich(LO_ID, target_language_code="vi")

    assert result.translation == translation.text
    assert result.translation_source == "manual"
    assert translation.text in provider.last_prompt
    assert objects.row.raw_ai_diagnostics["enrichment"]["translation_source"] == "manual"


def test_no_translation_does_not_create_hallucinated_authoritative_translation():
    service, _, provider = make_service()

    result = service.enrich(LO_ID, target_language_code="vi")

    assert result.translation is None
    assert "Do not invent one" in provider.last_prompt


def test_provider_receives_bounded_context_concept_evidence_translation_and_dictionary():
    entry = DictionaryEntry(
        id=uuid4(),
        language_code="en",
        headword="put off",
        normalized_headword="put something off",
        definitions=[{"sense_id": "test:00000000000000aa", "text": "delay", "pos": "verb"}],
        provider="trusted-test",
    )
    translation = SegmentTranslation(transcript_segment_id=SEGMENT_ID, language_code="vi", text="Bản dịch.", source="manual")
    provider = FakeProvider(valid_ai(sense_id="test:00000000000000aa"))
    service, _, provider = make_service(dictionary_entry=entry, translation=translation, provider=provider)

    service.enrich(LO_ID, target_language_code="vi")

    assert "Concept canonical form: put something off" in provider.last_prompt
    assert "LearningObject source evidence: putting it off" in provider.last_prompt
    assert "The deadline was near." in provider.last_prompt
    assert "Then I finally finished it." in provider.last_prompt
    assert "- [test:00000000000000aa] put off (verb): delay" in provider.last_prompt
    assert "Bản dịch." in provider.last_prompt


SENSE_DELAY = "enwikt:00000000000000d1"
SENSE_DISCOURAGE = "enwikt:00000000000000d2"
SENSE_PAST = "enwikt:00000000000000f1"


def make_entry(definitions, headword="put off", normalized="put something off"):
    return DictionaryEntry(id=uuid4(), language_code="en", headword=headword, normalized_headword=normalized,
                           definitions=definitions, provider="en-wiktionary")


PUT_OFF = [
    {"sense_id": SENSE_DISCOURAGE, "text": "To cause somebody to dislike something.", "pos": "verb"},
    {"sense_id": SENSE_DELAY, "text": "To delay doing something; to postpone.", "pos": "verb"},
]


def test_selected_offered_sense_is_recorded_as_translated_from_sense():
    provider = FakeProvider(valid_ai(sense_id=SENSE_DELAY, contextual_meaning="trì hoãn"))
    service, objects, _ = make_service(dictionary_entry=make_entry(PUT_OFF), provider=provider)

    result = service.enrich(LO_ID, target_language_code="vi")

    stored = objects.row.raw_ai_diagnostics["enrichments"]["vi"]
    assert stored["sense_id"] == SENSE_DELAY and stored["meaning_provenance"] == "translated_from_sense"
    assert stored["dictionary_sense"]["text"] == "To delay doing something; to postpone."
    assert stored["dictionary_sense"]["provider"] == "en-wiktionary"
    assert stored["prompt_version"] == "learning_object_enrichment_v2_dictionary_sense"
    assert result.diagnostics["meaning_provenance"] == "translated_from_sense"
    # Senses sharing words with the Concept sense ("to delay doing something") are offered first.
    assert provider.last_prompt.index(SENSE_DELAY) < provider.last_prompt.index(SENSE_DISCOURAGE)


def test_cefr_j_headword_level_replaces_the_ai_level():
    entry = make_entry(PUT_OFF).model_copy(update={"provider_metadata": {"source": "en-wiktionary", "cefr_j": "B2"}})
    service, objects, _ = make_service(dictionary_entry=entry, provider=FakeProvider(valid_ai(sense_id=SENSE_DELAY)))

    service.enrich(LO_ID, target_language_code="vi")

    difficulty = objects.row.raw_ai_diagnostics["enrichments"]["vi"]["difficulty"]
    assert (difficulty["level"], difficulty["provenance"], difficulty["score"]) == ("B2", "cefr_j_headword", 0.45)


def test_concept_difficulty_still_outranks_the_word_list_level():
    entry = make_entry(PUT_OFF).model_copy(update={"provider_metadata": {"cefr_j": "B2"}})
    service, objects, _ = make_service(concept=make_concept(difficulty_level="C1", difficulty_score=0.8),
                                       dictionary_entry=entry, provider=FakeProvider(valid_ai(sense_id=SENSE_DELAY)))

    service.enrich(LO_ID, target_language_code="vi")

    difficulty = objects.row.raw_ai_diagnostics["enrichments"]["vi"]["difficulty"]
    assert (difficulty["level"], difficulty["provenance"]) == ("C1", "concept")


def test_unoffered_or_invented_sense_id_fails_closed_without_persistence():
    provider = FakeProvider(valid_ai(sense_id="enwikt:ffffffffffffffff"))
    service, objects, _ = make_service(dictionary_entry=make_entry(PUT_OFF), provider=provider)

    with pytest.raises(LearningObjectEnrichmentError, match="not offered"):
        service.enrich(LO_ID, target_language_code="vi")
    assert objects.update_count == 0

    service, objects, _ = make_service(provider=FakeProvider(valid_ai(sense_id=SENSE_DELAY)))
    with pytest.raises(LearningObjectEnrichmentError, match="not offered"):
        service.enrich(LO_ID, target_language_code="vi")
    assert objects.update_count == 0


def test_sense_id_format_and_extra_fields_are_schema_violations():
    with pytest.raises(ValidationError):
        valid_ai(sense_id="go: to move")
    with pytest.raises(ValidationError):
        valid_ai(definition="AI-written definition")
    data = valid_ai().model_dump()
    data.pop("sense_id")
    with pytest.raises(ValidationError):
        LLMLearningObjectEnrichment.model_validate(data)


def test_no_fitting_sense_excludes_occurrence_and_records_it_for_review():
    from app.modules.content.application.enrichment import DictionarySenseMismatch

    prepared = {"target_language_code": "vi", "concept_id": str(CONCEPT_ID), "contextual_meaning": "cũ"}
    learning_object = make_learning_object(raw_ai_diagnostics={"enrichments": {"vi": prepared, "ja": {"x": 1}},
                                                               "enrichment": prepared})
    service, objects, _ = make_service(learning_object=learning_object, dictionary_entry=make_entry(PUT_OFF))

    with pytest.raises(DictionarySenseMismatch):
        service.enrich(LO_ID, target_language_code="vi", force=True)

    diagnostics = objects.row.raw_ai_diagnostics
    assert "vi" not in diagnostics["enrichments"] and "enrichment" not in diagnostics
    assert diagnostics["enrichments"]["ja"] == {"x": 1}
    review = diagnostics["dictionary_review"]["vi"]
    assert review["status"] == "no_matching_sense"
    assert review["offered_sense_ids"] == [SENSE_DELAY, SENSE_DISCOURAGE]


def test_missing_dictionary_entry_is_labelled_ai_unverified():
    service, objects, provider = make_service()

    service.enrich(LO_ID, target_language_code="vi")

    assert "No dictionary senses are available" in provider.last_prompt
    stored = objects.row.raw_ai_diagnostics["enrichments"]["vi"]
    assert stored["sense_id"] is None and stored["dictionary_sense"] is None
    assert stored["meaning_provenance"] == "ai_unverified"


def test_inflection_entry_offers_its_lemma_senses():
    went = make_entry([{"sense_id": SENSE_PAST, "text": "simple past of go", "pos": "verb", "form_of": ["go"]}],
                      headword="went", normalized="went")
    lemma = make_entry([{"sense_id": SENSE_DELAY, "text": "To move through space.", "pos": "verb"}],
                       headword="go", normalized="go")

    class Entries(FakeDictionaryEntries):
        def list_by_headwords(self, *, language_code, normalized_headwords):
            assert (language_code, normalized_headwords) == ("en", ["go"])
            return [lemma]

    provider = FakeProvider(valid_ai(sense_id=SENSE_DELAY))
    service, objects, _ = make_service(dictionary_entry=went, provider=provider)
    service.dictionary_entries = Entries(went)

    service.enrich(LO_ID, target_language_code="vi")

    assert SENSE_PAST not in provider.last_prompt and "go (verb): To move through space." in provider.last_prompt
    assert objects.row.raw_ai_diagnostics["enrichments"]["vi"]["dictionary_sense"]["headword"] == "go"


@pytest.mark.parametrize("language, expected", [
    ("zh", "difficulty.level exactly one of: HSK1, HSK2, HSK3, HSK4, HSK5, HSK6"),
    ("en", "difficulty.level exactly one of: A1, A2, B1, B2, C1, C2"),
    ("ja", "difficulty.level exactly one of: N5, N4, N3, N2, N1"),
])
def test_prompt_names_the_exact_difficulty_levels_for_the_source_language(language, expected):
    # Chinese preparation failed every item when the model answered "HSK 5" or "3".
    service, _, provider = make_service(transcript=make_transcript(language))
    try:
        service.enrich(LO_ID, target_language_code="vi")
    except LearningObjectEnrichmentError:
        pass
    assert expected in provider.last_prompt


def test_offered_senses_are_capped():
    many = [{"sense_id": f"enwikt:{index:016x}", "text": f"Sense {index}."} for index in range(30)]
    service, _, provider = make_service(dictionary_entry=make_entry(many))

    with pytest.raises(LearningObjectEnrichmentError):
        service.enrich(LO_ID, target_language_code="vi")

    assert provider.last_prompt.count("[enwikt:") == 12


def test_structured_ai_output_validation_rejects_invalid_scores_and_empty_text():
    with pytest.raises(ValidationError):
        valid_ai(learning_value={"score": 1.2, "confidence": 0.8})
    with pytest.raises(ValidationError):
        valid_ai(difficulty={"framework": "CEFR", "level": "B1", "score": -0.1, "confidence": 0.8})
    with pytest.raises(ValidationError):
        valid_ai(contextual_meaning="")


def test_unknown_difficulty_framework_is_rejected_without_persistence():
    provider = FakeProvider(valid_ai(difficulty={"framework": "MADEUP", "level": "X1", "score": 0.4, "confidence": 0.8}))
    service, objects, _ = make_service(provider=provider)

    with pytest.raises(LearningObjectEnrichmentError):
        service.enrich(LO_ID, target_language_code="vi")

    assert objects.update_count == 0


def test_invalid_difficulty_level_and_language_framework_are_rejected():
    bad_level = FakeProvider(valid_ai(difficulty={"framework": "CEFR", "level": "Z9", "score": 0.4, "confidence": 0.8}))
    service, _, _ = make_service(provider=bad_level)
    with pytest.raises(LearningObjectEnrichmentError):
        service.enrich(LO_ID, target_language_code="vi")

    ja_cefr = FakeProvider(valid_ai(difficulty={"framework": "CEFR", "level": "A1", "score": 0.4, "confidence": 0.8}))
    service, _, _ = make_service(provider=ja_cefr, transcript=make_transcript("ja"))
    with pytest.raises(LearningObjectEnrichmentError):
        service.enrich(LO_ID, target_language_code="vi")


def test_authoritative_concept_difficulty_takes_priority_over_ai_estimate():
    concept = make_concept(difficulty_level="B2", difficulty_score=0.7)
    provider = FakeProvider(valid_ai(difficulty={"framework": "CEFR", "level": "A1", "score": 0.2, "confidence": 0.4}))
    service, objects, _ = make_service(concept=concept, provider=provider)

    result = service.enrich(LO_ID, target_language_code="vi")

    assert result.difficulty.level == "B2"
    assert result.difficulty.score == 0.7
    assert result.difficulty.provenance == "concept"
    assert objects.row.difficulty_score == 0.7


@pytest.mark.parametrize(
    ("concept_type", "framework", "level", "language"),
    [
        (ConceptType.VOCABULARY, "CEFR", "A2", "en"),
        (ConceptType.EXPRESSION, "CEFR", "B1", "en"),
        (ConceptType.COLLOCATION, "CEFR", "B2", "en"),
        (ConceptType.PHRASAL_VERB, "CEFR", "B1", "en"),
        (ConceptType.IDIOM, "CEFR", "C1", "en"),
        (ConceptType.GRAMMAR, "CEFR", "A2", "en"),
    ],
)
def test_required_concept_types_enrich_without_forced_dictionary(concept_type, framework, level, language):
    provider = FakeProvider(valid_ai(difficulty={"framework": framework, "level": level, "score": 0.4, "confidence": 0.8}))
    service, _, _ = make_service(concept=make_concept(concept_type=concept_type), transcript=make_transcript(language), provider=provider)

    result = service.enrich(LO_ID, target_language_code="vi")

    assert result.status == "created"


def test_idempotent_reuse_skips_provider_and_no_duplicate_state():
    service, objects, first_provider = make_service()
    first = service.enrich(LO_ID, target_language_code="vi")
    second_provider = FakeProvider(valid_ai(contextual_meaning="changed"))
    service.provider = second_provider

    second = service.enrich(LO_ID, target_language_code="vi")

    assert first.contextual_meaning == second.contextual_meaning
    assert second.status == "reused"
    assert second_provider.calls == 0
    assert first_provider.calls == 1
    assert objects.update_count == 1


def test_force_reenrichment_overwrites_same_row_explicitly():
    service, objects, _ = make_service()
    service.enrich(LO_ID, target_language_code="vi")
    service.provider = FakeProvider(valid_ai(contextual_meaning="new contextual meaning"))

    result = service.enrich(LO_ID, target_language_code="vi", force=True)

    assert result.status == "updated"
    assert result.contextual_meaning == "new contextual meaning"
    assert objects.update_count == 2


def test_enrichment_keeps_separate_support_language_contexts():
    service, objects, _ = make_service()
    service.enrich(LO_ID, target_language_code="vi")
    service.provider = FakeProvider(valid_ai(contextual_meaning="Japanese context"))
    service.enrich(LO_ID, target_language_code="ja")

    diagnostics = objects.get_by_id(LO_ID).raw_ai_diagnostics
    assert diagnostics["enrichments"]["vi"]["target_language_code"] == "vi"
    assert diagnostics["enrichments"]["ja"]["contextual_meaning"] == "Japanese context"
    assert service.enrich(LO_ID, target_language_code="vi").status == "reused"
    assert objects.update_count == 2


def test_ai_cannot_alter_object_identity():
    service, objects, _ = make_service()

    result = service.enrich(LO_ID, target_language_code="vi")

    assert result.learning_object_id == LO_ID
    assert result.concept_id == CONCEPT_ID
    assert result.transcript_segment_id == SEGMENT_ID
    assert objects.row.concept_id == CONCEPT_ID
    assert objects.row.transcript_segment_id == SEGMENT_ID


def test_provider_failures_fail_closed_without_persistence():
    service, objects, _ = make_service(provider=FakeProvider(error=LLMProviderError("timeout")))

    with pytest.raises(LearningObjectEnrichmentError):
        service.enrich(LO_ID, target_language_code="vi")

    assert objects.update_count == 0


# A26 (found by the M2.2 phase B run, 2026-10-21): under a worker claim, a "no fitting sense" answer
# reached ClaimedLearningObjects.update_enrichment without an "enrichment" key; the KeyError was classified
# unknown_failure and failed the whole video or region preparation instead of excluding one occurrence.
def test_no_fitting_sense_under_a_claim_excludes_the_occurrence_instead_of_failing():
    from types import SimpleNamespace

    from app.modules.content.application.enrichment import DictionarySenseMismatch
    from app.modules.content.infrastructure.repositories.content_claims import ClaimedLearningObjects

    class FakeRpc:
        def __init__(self):
            self.calls = []

        def schema(self, name):
            return self

        def rpc(self, name, params):
            self.calls.append((name, params))
            return SimpleNamespace(execute=lambda: SimpleNamespace(data=make_learning_object().model_dump(mode="json")))

    class ClaimedOverFake(FakeLearningObjects):
        update_enrichment = ClaimedLearningObjects.update_enrichment
        record_sense_review = ClaimedLearningObjects.record_sense_review

    service, objects, _ = make_service(dictionary_entry=make_entry(PUT_OFF),
                                       provider=FakeProvider(valid_ai(sense_id=None)))
    claimed = ClaimedOverFake(objects.row)
    claimed.client, claimed.claim = FakeRpc(), SimpleNamespace(intent_id=uuid4(), token=uuid4(), epoch=1)
    service.learning_objects = claimed

    with pytest.raises(DictionarySenseMismatch):
        service.enrich(LO_ID, target_language_code="vi")
    [(name, params)] = claimed.client.calls
    assert name == "record_claimed_sense_review"
    assert params["p_learning_object_id"] == str(LO_ID) and params["p_target_language_code"] == "vi"
    review = params["p_review"]
    assert review["status"] == "no_matching_sense" and review["concept_id"] == str(CONCEPT_ID)
    assert review["offered_sense_ids"] == [SENSE_DELAY, SENSE_DISCOURAGE]
    # Only this language's review is sent, never the worker's JSONB snapshot.
    assert "raw_ai_diagnostics" not in params and "p_raw_ai_diagnostics" not in params
