from uuid import UUID

import pytest
from pydantic import ValidationError

from app.modules.content.domain.extraction import CandidateType, LLMCandidateResponse
from app.modules.content.domain.catalog import TranscriptSegment, VideoTranscript
from app.modules.content.application.candidate_extraction import (
    CandidateExtractionService,
    V3CandidateExtractionService,
)
from app.platform.llm.port import LLMProviderError


SEGMENT_ID = UUID("11111111-1111-1111-1111-111111111111")
OTHER_SEGMENT_ID = UUID("22222222-2222-2222-2222-222222222222")
TRANSCRIPT_ID = UUID("33333333-3333-3333-3333-333333333333")
USER_ID = UUID("44444444-4444-4444-4444-444444444444")
MODEL_SEGMENT_ID = UUID("55555555-5555-5555-5555-555555555555")


def make_segment(segment_id: UUID = SEGMENT_ID, text: str = "I kept putting it off for weeks.") -> TranscriptSegment:
    return TranscriptSegment(
        id=segment_id,
        transcript_id=TRANSCRIPT_ID,
        sequence_number=1,
        start_ms=0,
        end_ms=2500,
        text=text,
    )


class FakeProvider:
    provider_name = "fake"
    model_name = "fake-model"

    def __init__(self, responses=None, failures=None):
        self.responses = list(responses or [])
        self.failures = list(failures or [])
        self.calls = 0

    def generate_structured(self, prompt: str, response_model=None, **kwargs):
        self.calls += 1
        if self.failures:
            raise self.failures.pop(0)
        return LLMCandidateResponse.model_validate(self.responses.pop(0))


def valid_response(**overrides):
    candidate = {
        "surface_form": "putting it off",
        "normalized_form": "put something off",
        "sense_gloss": "to delay doing something",
        "sense_evidence": "putting it off",
        "candidate_type": "PHRASAL_VERB",
        "confidence": 0.91,
        "rationale": "Useful conversational phrasal verb.",
        "context": "I kept putting it off for weeks.",
        "learning_unit": "reusable",
    }
    candidate.update(overrides)
    return {"candidates": [candidate]}


def extract(response, *, text: str = "I kept putting it off for weeks.", max_candidates=8, language="en"):
    service = CandidateExtractionService(
        provider=FakeProvider(responses=[response]),
        max_candidates_per_segment=max_candidates,
        max_retries=0,
    )
    return service.extract_segment(segment=make_segment(text=text), source_language=language)


def test_valid_structured_candidate_parses_and_is_grounded():
    result = extract(valid_response())

    assert not result.errors
    assert len(result.candidates) == 1
    candidate = result.candidates[0]
    assert candidate.candidate_type == CandidateType.PHRASAL_VERB
    assert candidate.source_segment_id == SEGMENT_ID
    assert candidate.evidence_start == 7
    assert candidate.evidence_end == 21


def test_invalid_candidate_type_is_rejected():
    with pytest.raises(ValidationError):
        LLMCandidateResponse.model_validate(valid_response(candidate_type="MADE_UP"))


def test_empty_surface_form_is_rejected_fail_closed():
    result = extract(valid_response(surface_form=" "))

    assert result.candidates == []
    assert result.errors
    assert result.extraction_metadata["failed_closed"] is True


def test_empty_normalized_form_is_rejected_fail_closed():
    result = extract(valid_response(normalized_form=" "))

    assert result.candidates == []
    assert result.errors


def test_empty_sense_gloss_is_rejected_fail_closed():
    result = extract(valid_response(sense_gloss=" "))

    assert result.candidates == []


def test_ungrounded_sense_evidence_is_rejected_fail_closed():
    result = extract(valid_response(sense_evidence="a financial institution"))

    assert result.candidates == []
    assert any("sense evidence" in error.casefold() for error in result.errors)
    assert result.errors


def test_confidence_below_zero_is_rejected():
    with pytest.raises(ValidationError):
        LLMCandidateResponse.model_validate(valid_response(confidence=-0.1))


def test_confidence_above_one_is_rejected():
    with pytest.raises(ValidationError):
        LLMCandidateResponse.model_validate(valid_response(confidence=1.1))


def test_surface_form_not_grounded_in_source_text_fails():
    result = extract(valid_response(surface_form="procrastinate", normalized_form="procrastinate"))

    assert result.candidates == []
    assert "grounded" in " ".join(result.errors)


def test_case_normalization_mismatch_fails_closed_for_exact_occurrence():
    result = extract(valid_response(surface_form="PUTTING IT OFF"))

    assert result.candidates == []
    assert result.extraction_metadata["failed_closed"] is True


def test_surface_whitespace_mismatch_fails_closed():
    result = extract(valid_response(surface_form=" putting   it\noff ", normalized_form=" put   something off "))

    assert result.candidates == []
    assert result.extraction_metadata["failed_closed"] is True


def test_decomposed_unicode_surface_keeps_exact_codepoint_span():
    result = extract(valid_response(surface_form="e\u0301", normalized_form="é",
                                    sense_evidence="e\u0301"), text="Try e\u0301 now.")
    assert [(item.evidence_start, item.evidence_end) for item in result.candidates] == [(4, 6)]


def test_duplicate_candidates_are_removed_within_one_result():
    response = {
        "candidates": [
            valid_response()["candidates"][0],
            valid_response(surface_form="putting it off", confidence=0.7)["candidates"][0],
        ]
    }

    result = extract(response)

    assert len(result.candidates) == 1


def test_repeated_expression_requires_verified_occurrence_hint():
    source = "I put it off, then put it off again."
    item = valid_response(surface_form="put it off", sense_evidence="put it off")["candidates"][0]
    ambiguous = extract({"candidates": [item]}, text=source)
    assert ambiguous.candidates == []
    assert ambiguous.extraction_metadata["failed_closed"] is True

    first = {**item, "surface_occurrence_index": 1}
    second = {**item, "surface_occurrence_index": 2}
    resolved = extract({"candidates": [first, second]}, text=source)
    assert [(c.evidence_start, c.evidence_end) for c in resolved.candidates] == [(2, 12), (19, 29)]
    assert len(resolved.candidates) == 2


def test_invalid_occurrence_hint_fails_closed():
    source = "I put it off, then put it off again."
    result = extract(valid_response(surface_form="put it off", sense_evidence="put it off",
                                    surface_occurrence_index=3), text=source)
    assert result.candidates == []


def test_repeated_surface_is_anchored_by_unique_exact_evidence():
    source = "I love autumn - 'autumn' is my season."
    result = extract(valid_response(surface_form="autumn", normalized_form="autumn",
                                    sense_evidence="'autumn' is my season", candidate_type="WORD"),
                     text=source)

    assert not result.errors
    [candidate] = result.candidates
    assert (candidate.evidence_start, candidate.evidence_end) == (17, 23)
    assert candidate.surface_occurrence_index == 2


def test_explicit_wrong_occurrence_hint_is_not_rescued_by_evidence():
    source = "I love autumn - 'autumn' is my season."
    result = extract(valid_response(surface_form="autumn", normalized_form="autumn",
                                    sense_evidence="'autumn' is my season", candidate_type="WORD",
                                    surface_occurrence_index=3), text=source)

    assert result.candidates == []
    assert result.extraction_metadata["failed_closed"] is True


def test_evidence_with_repeated_surface_does_not_anchor():
    source = "Fall, fall, and then fall again."
    result = extract(valid_response(surface_form="fall", normalized_form="fall",
                                    sense_evidence="fall, and then fall", candidate_type="WORD"),
                     text=source)

    assert result.candidates == []


def test_one_ungrounded_candidate_does_not_discard_grounded_siblings():
    source = "And I love these autumnal colours - so, 'autumnal' being the adjective."
    grounded = valid_response(surface_form="colours", normalized_form="colour",
                              sense_evidence="autumnal colours", candidate_type="WORD")["candidates"][0]
    ambiguous = valid_response(surface_form="autumnal", normalized_form="autumnal",
                               sense_evidence="autumnal being the adjective",
                               candidate_type="WORD")["candidates"][0]

    result = extract({"candidates": [ambiguous, grounded]}, text=source)

    assert [candidate.surface_form for candidate in result.candidates] == ["colours"]
    assert result.extraction_metadata["rejected_candidate_count"] == 1
    assert "failed_closed" not in result.extraction_metadata
    assert any("grounded" in error for error in result.errors)


def test_surface_inside_longer_word_is_rejected_for_word_delimited_language():
    source = "These autumnal colours relate to autumn."
    inside = extract(valid_response(surface_form="autumn", normalized_form="autumn", sense_evidence="autumn",
                                    candidate_type="WORD", surface_occurrence_index=1), text=source)
    whole = extract(valid_response(surface_form="autumn", normalized_form="autumn", sense_evidence="autumn",
                                   candidate_type="WORD", surface_occurrence_index=2), text=source)

    assert inside.candidates == []
    assert any("longer source word" in error for error in inside.errors)
    assert [(c.evidence_start, c.evidence_end) for c in whole.candidates] == [(33, 39)]


def test_occurrence_hint_conflicting_with_exact_evidence_is_rejected():
    source = "I love autumn - 'autumn' is my season."
    result = extract(valid_response(surface_form="autumn", normalized_form="autumn",
                                    sense_evidence="'autumn' is my season", candidate_type="WORD",
                                    surface_occurrence_index=1), text=source)

    assert result.candidates == []
    assert any("conflicts" in error for error in result.errors)


def test_agglutinative_language_keeps_stem_inside_word():
    result = extract(valid_response(surface_form="학교", normalized_form="학교", sense_evidence="학교에 갔어요",
                                    candidate_type="WORD"), text="학교에 갔어요.", language="ko")

    assert [(c.evidence_start, c.evidence_end) for c in result.candidates] == [(0, 2)]


def test_claimed_extraction_contains_output_validation_to_the_segment():
    source = "I put it off, then put it off again."
    service = CandidateExtractionService(
        provider=FakeProvider(responses=[valid_response(surface_form="put it off", sense_evidence="put it off")]),
        max_candidates_per_segment=8,
        max_retries=0,
        propagate_failures=True,
    )

    result = service.extract_segment(segment=make_segment(text=source), source_language="en")

    assert result.candidates == []
    assert result.extraction_metadata["failed_closed"] is True


def test_claimed_extraction_still_propagates_provider_failures():
    service = CandidateExtractionService(
        provider=FakeProvider(failures=[LLMProviderError("provider down")]),
        max_retries=0,
        propagate_failures=True,
    )

    with pytest.raises(LLMProviderError):
        service.extract_segment(segment=make_segment(), source_language="en")


def test_same_form_different_senses_are_not_deduplicated():
    response = {
        "candidates": [
            valid_response(sense_gloss="financial institution")["candidates"][0],
            valid_response(sense_gloss="river edge")["candidates"][0],
        ]
    }

    result = extract(response)

    assert [item.sense_gloss for item in result.candidates] == ["financial institution", "river edge"]


def test_same_expression_in_different_segments_is_not_globally_deduplicated():
    provider = FakeProvider(responses=[valid_response(), valid_response()])
    service = CandidateExtractionService(provider=provider, max_retries=0)

    results = service.extract_segments(
        segments=[
            make_segment(SEGMENT_ID, "I kept putting it off for weeks."),
            make_segment(OTHER_SEGMENT_ID, "She was putting it off again."),
        ],
        source_language="en",
    )

    assert [item.source_segment_id for item in results] == [SEGMENT_ID, OTHER_SEGMENT_ID]
    assert sum(len(item.candidates) for item in results) == 2


def test_candidate_count_limit_fails_closed():
    response = {"candidates": [valid_response(surface_form="putting it off")["candidates"][0], valid_response(surface_form="for weeks", normalized_form="for weeks", candidate_type="PHRASE")["candidates"][0]]}

    result = extract(response, max_candidates=1)

    assert result.candidates == []
    assert "limit" in " ".join(result.errors)


def test_invalid_json_provider_failure_is_rejected():
    provider = FakeProvider(failures=[LLMProviderError("malformed json")])
    service = CandidateExtractionService(provider=provider, max_retries=0)

    result = service.extract_segment(segment=make_segment(), source_language="en")

    assert result.candidates == []
    assert result.errors == ["LLMProviderError"]


def test_provider_timeout_or_rate_limit_produces_typed_failure():
    provider = FakeProvider(failures=[LLMProviderError("rate limit")])
    service = CandidateExtractionService(provider=provider, max_retries=0)

    result = service.extract_segment(segment=make_segment(), source_language="en")

    assert result.extraction_metadata["failed_closed"] is True
    assert result.candidates == []


def test_retry_success_is_bounded():
    provider = FakeProvider(
        responses=[valid_response()],
        failures=[LLMProviderError("temporary network failure")],
    )
    service = CandidateExtractionService(provider=provider, max_retries=1)

    result = service.extract_segment(segment=make_segment(), source_language="en")

    assert provider.calls == 2
    assert len(result.candidates) == 1
    assert result.errors == ["LLMProviderError"]


def test_retry_exhaustion_is_bounded():
    provider = FakeProvider(
        failures=[LLMProviderError("timeout"), LLMProviderError("timeout"), LLMProviderError("timeout")]
    )
    service = CandidateExtractionService(provider=provider, max_retries=2)

    result = service.extract_segment(segment=make_segment(), source_language="en")

    assert provider.calls == 3
    assert result.candidates == []


def test_transcript_text_is_never_modified():
    segment = make_segment()
    original = segment.text

    extract(valid_response(), text=segment.text)

    assert segment.text == original


def test_source_segment_id_is_controlled_by_application_not_model_output():
    result = extract(valid_response())

    assert result.candidates[0].source_segment_id == SEGMENT_ID
    # The model cannot even propose an identity: extra fields are a schema violation.
    with pytest.raises(ValidationError):
        LLMCandidateResponse.model_validate(valid_response(source_segment_id=str(MODEL_SEGMENT_ID)))
    with pytest.raises(ValidationError):
        LLMCandidateResponse.model_validate({**valid_response(), "notes": "extra"})


def test_learning_unit_is_required_and_enumerated():
    data = valid_response()
    del data["candidates"][0]["learning_unit"]
    with pytest.raises(ValidationError):
        LLMCandidateResponse.model_validate(data)
    with pytest.raises(ValidationError):
        LLMCandidateResponse.model_validate(valid_response(learning_unit="important"))


@pytest.mark.parametrize("unit", ["proper_name", "title_or_brand", "free_combination", "filler"])
def test_low_value_candidates_are_skipped_without_failing_the_segment(unit):
    text = "Welcome to 6 Minute English. I kept putting it off for weeks."
    response = {"candidates": [
        valid_response(surface_form="6 Minute English", normalized_form="6 Minute English",
                       sense_gloss="programme name", sense_evidence="6 Minute English",
                       candidate_type="PHRASE", learning_unit=unit)["candidates"][0],
        valid_response()["candidates"][0],
    ]}

    result = extract(response, text=text)

    assert [c.surface_form for c in result.candidates] == ["putting it off"]
    assert result.errors == []
    assert result.extraction_metadata["low_value_skipped_count"] == 1
    assert result.extraction_metadata["rejected_candidate_count"] == 0


def test_segment_with_only_low_value_candidates_is_an_empty_success():
    result = extract(valid_response(learning_unit="filler"))

    assert result.candidates == [] and result.errors == []
    assert result.extraction_metadata.get("failed_closed") is not True


def test_extraction_prompt_v7_is_vocabulary_only():
    from app.modules.content.application.prompts import (
        CANDIDATE_EXTRACTION_PROMPT_VERSION, build_candidate_extraction_prompt,
    )
    prompt = build_candidate_extraction_prompt(source_language="zh", transcript_text="我是李明。", max_candidates=2)
    assert CANDIDATE_EXTRACTION_PROMPT_VERSION == "candidate_extraction_v7_vocabulary"
    for rule in ("learning_unit is required", "names of people", "free combinations",
                 "Do not return grammar patterns; grammar is selected in a separate step."):
        assert rule in prompt
    assert "GRAMMAR_PATTERN" not in prompt


def test_grammar_from_vocabulary_extraction_is_skipped_never_kept():
    response = {"candidates": [
        valid_response(surface_form="我是学生", normalized_form="A 是 B", sense_gloss="identity",
                       sense_evidence="我是学生", candidate_type="GRAMMAR_PATTERN")["candidates"][0],
        valid_response(surface_form="学生", normalized_form="学生", sense_gloss="student",
                       sense_evidence="学生", candidate_type="WORD")["candidates"][0],
    ]}
    result = extract(response, text="我是学生。", language="zh")
    assert [c.surface_form for c in result.candidates] == ["学生"] and result.errors == []
    assert result.extraction_metadata["free_grammar_skipped_count"] == 1


class FakeGrammarSelection:
    def __init__(self, selection):
        self.selection, self.calls = selection, []

    def select(self, **kwargs):
        self.calls.append(kwargs)
        return self.selection


def test_selected_grammar_is_added_after_vocabulary_with_the_same_context():
    from app.modules.content.application.grammar_selection import GrammarSelection
    from app.modules.content.domain.extraction import Candidate
    segment = make_segment(text="我是学生。")
    shi = Candidate(surface_form="是", normalized_form="A + 是 + B", sense_gloss="A + 是 + B", sense_evidence="我是学生",
                    candidate_type=CandidateType.GRAMMAR_PATTERN, evidence_start=1, evidence_end=2,
                    source_segment_id=segment.id, confidence=0.9, grammar_key="zh.shi_sentence",
                    grammar_label="Câu với 是")
    selection = FakeGrammarSelection(GrammarSelection(candidates=[shi], split_skipped=1))
    word = valid_response(surface_form="学生", normalized_form="学生", sense_gloss="student",
                          sense_evidence="学生", candidate_type="WORD")
    service = CandidateExtractionService(provider=FakeProvider(responses=[word]), max_retries=0,
                                         grammar_selection=selection)
    result = service.extract_segment(segment=segment, source_language="zh", previous_context="你好！",
                                     next_context="你呢？")
    assert [c.grammar_key for c in result.candidates] == [None, "zh.shi_sentence"]
    assert selection.calls[0]["previous_context"] == "你好！" and selection.calls[0]["next_context"] == "你呢？"
    assert result.model_metadata["grammar_prompt_version"] == "grammar_selection_v1"
    assert result.extraction_metadata["grammar_split_skipped_count"] == 1
    assert result.extraction_metadata["candidate_count"] == 2


def test_context_segments_cannot_become_source_evidence():
    provider = FakeProvider(
        responses=[valid_response(surface_form="previous phrase", normalized_form="previous phrase", candidate_type="PHRASE")]
    )
    service = CandidateExtractionService(provider=provider, max_retries=0)

    result = service.extract_segment(
        segment=make_segment(text="Target text only."),
        source_language="en",
        previous_context="previous phrase",
    )

    assert result.candidates == []
    assert "grounded" in " ".join(result.errors)


class FakeSegmentRepo:
    def __init__(self):
        self.write_called = False

    def get_by_id(self, segment_id):
        return make_segment(segment_id)


class FakeTranscriptRepo:
    def __init__(self):
        self.write_called = False

    def get_by_id(self, transcript_id):
        return VideoTranscript(
            id=transcript_id,
            video_id=UUID("66666666-6666-6666-6666-666666666666"),
            language_code="en",
            source="caption_track",
        )


def test_v3_adapter_reads_segment_and_does_not_write_database_rows():
    provider = FakeProvider(responses=[valid_response()])
    segment_repo = FakeSegmentRepo()
    transcript_repo = FakeTranscriptRepo()
    service = V3CandidateExtractionService(
        segments=segment_repo,
        transcripts=transcript_repo,
        extraction=CandidateExtractionService(provider=provider, max_retries=0),
    )

    result = service.extract_by_segment_id(SEGMENT_ID)

    assert len(result.candidates) == 1
    assert segment_repo.write_called is False
    assert transcript_repo.write_called is False
