import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.modules.content.domain.extraction import Candidate, CandidateType
from app.modules.content.domain.knowledge import Concept, ConceptType, LearningObject
from app.modules.content.domain.catalog import TranscriptSegment, VideoTranscript
from app.modules.content.application.knowledge_resolution import LearningObjectFactory
from app.modules.content.domain.occurrence_spans import OccurrenceSpanError, resolve_occurrence_span
from app.modules.content.infrastructure.repositories.learning_objects import (
    LearningObjectRepository,
)


@pytest.mark.parametrize("source,phrase,expected", [
    ("I kept putting it off.", "putting it off", (7, 21)),
    ("(take care of)!", "take care of", (1, 13)),
    ("aaaa", "aaa", None),  # overlapping matches are ambiguous
    ("café", "cafe", None),  # normalization is not an offset authority
    ("e\u0301", "é", None),
    ("No match", "missing", None),
])
def test_exact_match_or_fail_closed(source, phrase, expected):
    if expected is None:
        with pytest.raises(OccurrenceSpanError):
            resolve_occurrence_span(source, phrase)
    else:
        assert resolve_occurrence_span(source, phrase) == expected


def test_repeated_exact_occurrences_have_distinct_half_open_spans():
    source = "I put it off, then put it off again."
    assert resolve_occurrence_span(source, "put it off", occurrence_ordinal=1) == (2, 12)
    assert resolve_occurrence_span(source, "put it off", occurrence_ordinal=2) == (19, 29)
    with pytest.raises(OccurrenceSpanError):
        resolve_occurrence_span(source, "put it off")
    with pytest.raises(OccurrenceSpanError):
        resolve_occurrence_span(source, "put it off", occurrence_ordinal=3)
    with pytest.raises(OccurrenceSpanError):
        resolve_occurrence_span(source, "put it off", start_codepoint=2, end_codepoint=12, occurrence_ordinal=2)


def test_nested_and_overlapping_candidates_preserve_independent_spans():
    source = "take care of"
    assert resolve_occurrence_span(source, "take care of") == (0, 12)
    assert resolve_occurrence_span(source, "care of") == (5, 12)
    assert resolve_occurrence_span("aaaa", "aaa", occurrence_ordinal=2) == (1, 4)


def test_cross_runtime_unicode_fixture_uses_python_codepoints():
    fixture = json.loads((Path(__file__).parent / "fixtures" / "occurrence_unicode_v6a4.json").read_text(encoding="utf-8"))
    source = fixture["source_text"]
    for item in fixture["occurrences"]:
        start, end = resolve_occurrence_span(source, item["text"])
        assert (start, end) == (item["start_codepoint"], item["end_codepoint"])
        assert source[start:end] == item["text"]
    assert len(source) == 17
    assert len(source.encode("utf-16-le")) // 2 == 20


def test_factory_requires_verified_source_span_and_keeps_concept_identity_separate():
    concept = Concept(id=uuid4(), language_code="en", type=ConceptType.PHRASAL_VERB,
                      canonical_text="put something off", normalized_text="put something off",
                      sense_key="to delay")
    transcript = VideoTranscript(id=uuid4(), video_id=uuid4(), language_code="en",
                                 source="manual", is_original=True)
    segment = TranscriptSegment(id=uuid4(), transcript_id=transcript.id,
                                sequence_number=1, start_ms=0, end_ms=1000,
                                text="I put it off, then put it off again.")
    factory = LearningObjectFactory()
    data = []
    for ordinal in (1, 2):
        candidate = Candidate(surface_form="put it off", normalized_form="put something off",
                              sense_gloss="to delay", sense_evidence="put it off",
                              candidate_type=CandidateType.PHRASAL_VERB,
                              source_segment_id=segment.id, confidence=0.9,
                              surface_occurrence_index=ordinal)
        data.append(factory.build(candidate=candidate, concept=concept,
                                  transcript=transcript, segment=segment,
                                  occurrence_index=ordinal))
    assert [(row["start_codepoint"], row["end_codepoint"]) for row in data] == [(2, 12), (19, 29)]
    assert {row["concept_id"] for row in data} == {str(concept.id)}
    assert LearningObject(id=uuid4(), **data[0]).start_codepoint == 2


class _MemoryLearningObjects:
    def __init__(self):
        self.rows = []
        self.filters = {}
        self.pending = None

    def schema(self, _):
        return self

    def table(self, _):
        return self

    def select(self, _):
        self.filters = {}
        return self

    def eq(self, key, value):
        self.filters[key] = value
        return self

    def limit(self, _):
        return self

    def upsert(self, data, on_conflict):
        assert on_conflict == "concept_id,transcript_segment_id,occurrence_index"
        self.pending = {"id": str(uuid4()), **data}
        return self

    def execute(self):
        if self.pending is not None:
            row, self.pending = self.pending, None
            self.rows.append(row)
            return SimpleNamespace(data=[row])
        return SimpleNamespace(data=[row for row in self.rows
                                     if all(row[key] == value for key, value in self.filters.items())])


def test_learning_object_repository_roundtrip_preserves_span_and_rejects_movement():
    memory = _MemoryLearningObjects()
    repository = LearningObjectRepository(memory)
    concept_id, segment_id, video_id = uuid4(), uuid4(), uuid4()
    data = {
        "concept_id": str(concept_id), "transcript_segment_id": str(segment_id),
        "video_id": str(video_id), "occurrence_index": 1,
        "evidence_text": "put it off", "start_codepoint": 2, "end_codepoint": 12,
        "start_ms": 0, "end_ms": 1000,
    }
    inserted = repository.upsert_by_occurrence(data)
    retrieved = repository.get_by_span(concept_id=concept_id, transcript_segment_id=segment_id,
                                       start_codepoint=2, end_codepoint=12)
    assert retrieved.id == inserted.id
    assert (retrieved.start_codepoint, retrieved.end_codepoint) == (2, 12)
    with pytest.raises(ValueError, match="cannot move|Cannot move"):
        repository.upsert_by_occurrence({**data, "start_codepoint": 3, "end_codepoint": 13})
    with pytest.raises(ValueError, match="requires a valid"):
        repository.upsert_by_occurrence({**data, "start_codepoint": None})
