from uuid import UUID, uuid4

import pytest

from app.modules.content.domain.extraction import (
    Candidate,
    CandidateType,
)
from app.modules.content.domain.knowledge import (
    Concept,
    ConceptType,
    DictionaryEntry,
    DictionaryEntryDraft,
    LearningObject,
)
from app.modules.content.domain.catalog import TranscriptSegment, VideoTranscript
from app.modules.content.application.knowledge_resolution import (
    CandidateResolutionError,
    CandidateResolutionService,
    concept_type_for_candidate,
    normalize_concept_text,
)


SEGMENT_A_ID = UUID("11111111-1111-1111-1111-111111111111")
SEGMENT_B_ID = UUID("22222222-2222-2222-2222-222222222222")
TRANSCRIPT_ID = UUID("33333333-3333-3333-3333-333333333333")
VIDEO_ID = UUID("44444444-4444-4444-4444-444444444444")
USER_ID = UUID("55555555-5555-5555-5555-555555555555")


def make_candidate(
    *,
    segment_id: UUID = SEGMENT_A_ID,
    surface_form: str = "putting it off",
    normalized_form: str = "put something off",
    sense_gloss: str = "to delay doing something",
    sense_evidence: str = "putting it off",
    candidate_type: CandidateType = CandidateType.PHRASAL_VERB,
    start: int | None = None,
    end: int | None = None,
) -> Candidate:
    return Candidate(
        surface_form=surface_form,
        normalized_form=normalized_form,
        sense_gloss=sense_gloss,
        sense_evidence=sense_evidence,
        candidate_type=candidate_type,
        evidence_start=start,
        evidence_end=end,
        source_segment_id=segment_id,
        confidence=0.91,
        rationale="Useful phrasing.",
        context="I kept putting it off for weeks.",
    )


def make_segment(
    segment_id: UUID = SEGMENT_A_ID,
    text: str = "I kept putting it off for weeks.",
) -> TranscriptSegment:
    return TranscriptSegment(
        id=segment_id,
        transcript_id=TRANSCRIPT_ID,
        sequence_number=1,
        start_ms=1000,
        end_ms=3500,
        text=text,
    )


def make_transcript(language_code: str = "en") -> VideoTranscript:
    return VideoTranscript(
        id=TRANSCRIPT_ID,
        video_id=VIDEO_ID,
        language_code=language_code,
        source="caption_track",
        is_original=True,
    )


class FakeDictionaryProvider:
    def __init__(self, draft: DictionaryEntryDraft | None = None):
        self.draft = draft
        self.calls = 0

    def lookup(self, *, language_code: str, candidate: Candidate):
        self.calls += 1
        return self.draft


class FakeDictionaryEntries:
    def __init__(self):
        self.rows: dict[tuple[str, str, str], DictionaryEntry] = {}

    def get_by_normalized(self, *, language_code: str, normalized_headword: str, part_of_speech: str = ""):
        return self.rows.get((language_code, normalized_headword, part_of_speech))

    def upsert_by_lookup(self, data: dict):
        key = (data["language_code"], data["normalized_headword"], data["part_of_speech"])
        row = self.rows.get(key) or DictionaryEntry(id=uuid4(), **data)
        self.rows[key] = row
        return row


class FakeConcepts:
    def __init__(self):
        self.rows: dict[tuple[str, str, str, str], Concept] = {}

    def find_by_identity(self, *, language_code: str, concept_type: str, normalized_text: str, sense_key: str):
        return self.rows.get((language_code, concept_type, normalized_text, sense_key))

    def upsert_by_identity(self, data: dict):
        key = (data["language_code"], data["type"], data["normalized_text"], data["sense_key"])
        row = self.rows.get(key) or Concept(id=uuid4(), **data)
        self.rows[key] = row
        return row


class FakeLinks:
    def __init__(self):
        self.rows = {}

    def get_by_ids(self, concept_id, dictionary_entry_id):
        return self.rows.get((concept_id, dictionary_entry_id))

    def upsert_link(self, *, concept_id, dictionary_entry_id, relation_type="supports"):
        from app.modules.content.domain.knowledge import ConceptDictionaryLink

        key = (concept_id, dictionary_entry_id)
        row = self.rows.get(key) or ConceptDictionaryLink(
            concept_id=concept_id,
            dictionary_entry_id=dictionary_entry_id,
            relation_type=relation_type,
        )
        self.rows[key] = row
        return row


class FakeLearningObjects:
    def __init__(self):
        self.rows: dict[tuple[UUID, UUID, int], LearningObject] = {}

    def get_by_occurrence(self, *, concept_id, transcript_segment_id, occurrence_index):
        return self.rows.get((concept_id, transcript_segment_id, occurrence_index))

    def get_by_span(self, *, concept_id, transcript_segment_id, start_codepoint, end_codepoint):
        return next((row for row in self.rows.values()
                     if row.concept_id == concept_id
                     and row.transcript_segment_id == transcript_segment_id
                     and row.start_codepoint == start_codepoint
                     and row.end_codepoint == end_codepoint), None)

    def list_for_segment_concept(self, *, concept_id, transcript_segment_id):
        return [row for row in self.rows.values()
                if row.concept_id == concept_id and row.transcript_segment_id == transcript_segment_id]

    def upsert_by_occurrence(self, data: dict):
        key = (
            UUID(data["concept_id"]),
            UUID(data["transcript_segment_id"]),
            data["occurrence_index"],
        )
        row = LearningObject(id=self.rows[key].id, **data) if key in self.rows else LearningObject(id=uuid4(), **data)
        self.rows[key] = row
        return row


def make_service(provider=None):
    dictionaries = FakeDictionaryEntries()
    concepts = FakeConcepts()
    links = FakeLinks()
    objects = FakeLearningObjects()
    service = CandidateResolutionService(
        concepts=concepts,
        dictionary_entries=dictionaries,
        concept_dictionary_links=links,
        learning_objects=objects,
        dictionary_provider=provider or FakeDictionaryProvider(),
    )
    return service, dictionaries, concepts, links, objects


def resolve_one(service, candidate=None, transcript=None, segment=None):
    return service.resolve_candidates(
        candidates=[candidate or make_candidate()],
        segment=segment or make_segment(),
        transcript=transcript or make_transcript(),
        previous_context="Before.",
        next_context="After.",
    )


def test_existing_dictionary_entry_is_reused():
    service, dictionaries, _, _, _ = make_service()
    existing = DictionaryEntry(
        id=uuid4(),
        language_code="en",
        headword="put",
        normalized_headword="put something off",
    )
    dictionaries.rows[("en", "put something off", "")] = existing

    result = resolve_one(service)

    assert result.resolved[0].dictionary_entry == existing
    assert result.resolved[0].status["dictionary_entry"] == "reused"


def test_missing_authoritative_dictionary_source_does_not_hallucinate_entry():
    service, dictionaries, _, _, _ = make_service(provider=FakeDictionaryProvider(None))

    result = resolve_one(service)

    assert result.resolved[0].dictionary_entry is None
    assert result.resolved[0].status["dictionary_entry"] == "missing_authoritative_source"
    assert dictionaries.rows == {}


def test_authoritative_dictionary_draft_can_create_entry_and_link_concept():
    draft = DictionaryEntryDraft(
        headword="put",
        normalized_headword="put something off",
        definitions=[{"text": "to delay doing something"}],
        provider="trusted-test-dictionary",
    )
    service, _, _, links, _ = make_service(provider=FakeDictionaryProvider(draft))

    result = resolve_one(service)

    resolved = result.resolved[0]
    assert resolved.dictionary_entry.provider == "trusted-test-dictionary"
    assert resolved.concept_dictionary_link is not None
    assert len(links.rows) == 1


def test_grammar_candidate_resolves_without_dictionary_entry():
    service, _, _, links, _ = make_service()
    candidate = make_candidate(
        surface_form="used to",
        normalized_form="used to + base verb",
        candidate_type=CandidateType.GRAMMAR_PATTERN,
    )

    result = resolve_one(service, candidate, segment=make_segment(text="I used to swim."))

    assert result.resolved[0].dictionary_entry is None
    assert result.resolved[0].concept.type == ConceptType.GRAMMAR
    assert links.rows == {}


def test_one_dictionary_entry_can_support_multiple_distinct_concepts():
    service, dictionaries, _, links, _ = make_service()
    entry = DictionaryEntry(id=uuid4(), language_code="en", headword="put", normalized_headword="put")
    dictionaries.rows[("en", "put", "")] = entry

    first = make_candidate(surface_form="put up", normalized_form="put")
    second = make_candidate(surface_form="put off", normalized_form="put", candidate_type=CandidateType.IDIOM)

    source = make_segment(text="I put up a sign and put off the task.")
    service.resolve_candidates(candidates=[first], segment=source, transcript=make_transcript())
    service.resolve_candidates(candidates=[second], segment=source, transcript=make_transcript())

    assert len(links.rows) == 2


def test_new_concept_is_created_and_same_normalized_form_is_reused():
    service, _, _, _, _ = make_service()

    first = resolve_one(service)
    second = resolve_one(service)

    assert first.resolved[0].status["concept"] == "created"
    assert second.resolved[0].status["concept"] == "reused"
    assert first.resolved[0].concept.id == second.resolved[0].concept.id


def test_same_form_and_type_with_different_senses_create_distinct_concepts():
    service, _, concepts, _, _ = make_service()
    financial = make_candidate(
        surface_form="bank",
        normalized_form="bank",
        sense_gloss="financial institution",
        candidate_type=CandidateType.WORD,
        start=4, end=8,
    )
    river = make_candidate(
        surface_form="bank",
        normalized_form="bank",
        sense_gloss="river edge",
        candidate_type=CandidateType.WORD,
        start=29, end=33,
    )
    segment = make_segment(text="The bank discussed the river bank.")

    result = service.resolve_candidates(candidates=[financial, river], segment=segment, transcript=make_transcript())

    assert len(concepts.rows) == 2
    assert result.resolved[0].concept.id != result.resolved[1].concept.id
    assert {item.concept.sense_key for item in result.resolved} == {"financial institution", "river edge"}


def test_same_sense_gloss_normalization_deduplicates_across_occurrences():
    service, _, concepts, _, objects = make_service()
    first = resolve_one(service, make_candidate(sense_gloss="  TO delay  doing something "))
    second = resolve_one(
        service,
        make_candidate(
            segment_id=SEGMENT_B_ID,
            surface_form="put it off",
            sense_gloss="to delay doing something",
        ),
        segment=make_segment(SEGMENT_B_ID, "Why do you always put it off?"),
    )

    assert first.resolved[0].concept.id == second.resolved[0].concept.id
    assert len(concepts.rows) == 1
    assert len(objects.rows) == 2


def test_different_surface_same_canonical_reuses_concept():
    service, _, _, _, _ = make_service()
    first = make_candidate(surface_form="putting it off", normalized_form="Put Something Off")
    second = make_candidate(surface_form="put it off", normalized_form="put something off")

    result = service.resolve_candidates(
        candidates=[first, second],
        segment=make_segment(text="I kept putting it off, then put it off again."),
        transcript=make_transcript(),
    )

    assert result.resolved[0].concept.id == result.resolved[1].concept.id


def test_language_isolation_for_same_normalized_concept():
    service, _, _, _, _ = make_service()
    en = resolve_one(service, transcript=make_transcript("en"))
    de = resolve_one(service, transcript=make_transcript("de"))

    assert en.resolved[0].concept.id != de.resolved[0].concept.id


def test_candidate_type_mapping_and_unsupported_type_failure():
    assert concept_type_for_candidate(make_candidate(candidate_type=CandidateType.WORD)) == ConceptType.VOCABULARY
    assert concept_type_for_candidate(make_candidate(candidate_type=CandidateType.COLLOCATION)) == ConceptType.COLLOCATION
    with pytest.raises(CandidateResolutionError):
        concept_type_for_candidate(make_candidate().model_copy(update={"candidate_type": "BROKEN"}))


def test_canonicalization_is_deterministic_and_safe():
    assert normalize_concept_text("  Put   Something  Off ", language_code="en") == "put something off"
    assert normalize_concept_text("  食べて  いる ", language_code="ja") == "食べて いる"


def test_learning_object_preserves_contextual_evidence_not_canonical_text():
    service, _, _, _, _ = make_service()
    candidate = make_candidate(surface_form="putting it off", normalized_form="put something off")

    result = resolve_one(service, candidate)

    learning_object = result.resolved[0].learning_object
    assert learning_object.evidence_text == "putting it off"
    assert learning_object.evidence_text != result.resolved[0].concept.canonical_text
    assert learning_object.previous_context == "Before."
    assert learning_object.next_context == "After."
    assert learning_object.concept_id == result.resolved[0].concept.id


def test_same_occurrence_reuses_learning_object_and_different_segment_creates_new_one():
    service, _, _, _, _ = make_service()
    first = resolve_one(service)
    second = resolve_one(service)
    segment_b = make_segment(SEGMENT_B_ID, "Why do you always put it off?")
    third = resolve_one(
        service,
        make_candidate(segment_id=SEGMENT_B_ID, surface_form="put it off", start=18, end=28),
        segment=segment_b,
    )

    assert first.resolved[0].learning_object.id == second.resolved[0].learning_object.id
    assert first.resolved[0].learning_object.id != third.resolved[0].learning_object.id


def test_multiple_occurrences_in_one_segment_use_occurrence_index():
    service, _, _, _, objects = make_service()
    candidates = [
        make_candidate(surface_form="put it off", normalized_form="put something off", start=2, end=12),
        make_candidate(surface_form="put it off", normalized_form="put something off", start=19, end=29),
    ]

    result = service.resolve_candidates(
        candidates=candidates,
        segment=make_segment(text="I put it off, then put it off again."),
        transcript=make_transcript(),
    )

    assert [item.learning_object.occurrence_index for item in result.resolved] == [1, 2]
    assert len({item.learning_object.id for item in result.resolved}) == 2
    assert len({item.concept.id for item in result.resolved}) == 1
    assert [(item.learning_object.start_codepoint, item.learning_object.end_codepoint)
            for item in result.resolved] == [(2, 12), (19, 29)]
    assert len(objects.rows) == 2


def test_e2e_repeated_resolution_creates_no_duplicates():
    service, _, concepts, links, objects = make_service()

    resolve_one(service)
    resolve_one(service)

    assert len(concepts.rows) == 1
    assert len(links.rows) == 0
    assert len(objects.rows) == 1


def test_multiple_contexts_share_one_concept_and_two_learning_objects():
    service, _, concepts, _, objects = make_service()
    segment_a = make_segment(SEGMENT_A_ID, "I kept putting it off for weeks.")
    segment_b = make_segment(SEGMENT_B_ID, "Why do you always put it off?")

    service.resolve_candidates(
        candidates=[make_candidate(segment_id=SEGMENT_A_ID, surface_form="putting it off", start=7, end=21)],
        segment=segment_a,
        transcript=make_transcript(),
    )
    service.resolve_candidates(
        candidates=[make_candidate(segment_id=SEGMENT_B_ID, surface_form="put it off", start=18, end=28)],
        segment=segment_b,
        transcript=make_transcript(),
    )

    assert len(concepts.rows) == 1
    assert len(objects.rows) == 2


def test_mismatched_segment_id_fails_without_orphan_learning_object():
    service, _, concepts, _, objects = make_service()

    result = resolve_one(service, make_candidate(segment_id=SEGMENT_B_ID))

    assert result.resolved == []
    assert result.errors
    assert concepts.rows == {}
    assert objects.rows == {}


def test_a_catalogue_grammar_point_is_one_concept_across_glosses_and_videos():
    from app.modules.content.application.knowledge_resolution import ConceptResolver
    concepts = FakeConcepts()
    resolver = ConceptResolver(concepts=concepts)
    first = make_candidate(surface_form="我是学生", normalized_form="A 是 B", sense_gloss="identity statement",
                           sense_evidence="我是学生", candidate_type=CandidateType.GRAMMAR_PATTERN)
    other_wording = make_candidate(surface_form="他是老师", normalized_form="S 是 N", sense_gloss="classification",
                                   sense_evidence="他是老师", candidate_type=CandidateType.GRAMMAR_PATTERN,
                                   segment_id=SEGMENT_B_ID)
    keyed = [item.model_copy(update={"grammar_key": "zh.shi_sentence", "grammar_label": "Câu với 是"})
             for item in (first, other_wording)]
    (concept, outcome), (again, second_outcome) = (resolver.resolve(language_code="zh", candidate=item)
                                                    for item in keyed)
    assert (outcome, second_outcome) == ("created", "reused") and again.id == concept.id
    assert (concept.type, concept.normalized_text, concept.sense_key, concept.canonical_text) == (
        ConceptType.GRAMMAR, "zh.shi_sentence", "zh.shi_sentence", "Câu với 是")
    assert concept.metadata["sense_identity_version"] == "grammar-key-v1"
