"""Grammar selection pass (`grammar_selection_v1`): catalogue keys, exact spans, split sentences."""
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.modules.content.application.grammar_selection import GrammarSelectionService, touches_open_boundary
from app.modules.content.application.prompts import GRAMMAR_SELECTION_PROMPT_VERSION, build_grammar_selection_prompt
from app.modules.content.domain.catalog import TranscriptSegment
from app.modules.content.domain.extraction import CandidateType, GrammarCatalogueItem, LLMGrammarResponse
from app.platform.llm.port import LLMProviderError

SHI = GrammarCatalogueItem(key="zh.shi_sentence", title="Câu với 是", pattern="A + 是 + B")
MA = GrammarCatalogueItem(key="zh.ma_question", title="Câu hỏi với 吗", pattern="câu + 吗？")
THERE = GrammarCatalogueItem(key="en.there_is_are", title="There is / There are", pattern="There is + N")


class FakeCatalogue:
    def __init__(self, *items):
        self.items, self.calls = list(items), 0

    def catalogue_for_language(self, language_code):
        self.calls += 1
        return [item for item in self.items if item.key.startswith(f"{language_code}.")]


class FakeProvider:
    provider_name, model_name = "fake", "fake-model"

    def __init__(self, *responses):
        self.responses, self.prompts = list(responses), []

    def generate_structured(self, prompt, schema):
        self.prompts.append(prompt)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return schema.model_validate(response)


def segment(text):
    return TranscriptSegment(id=uuid4(), transcript_id=uuid4(), sequence_number=1, start_ms=0, end_ms=1000, text=text)


def use(key, surface, evidence, status="complete", confidence=0.9):
    return {"grammar_key": key, "surface_form": surface, "sense_evidence": evidence, "span_status": status,
            "confidence": confidence}


def select(text, *uses, previous=None, following=None, language="zh", provider=None, **kwargs):
    provider = provider or FakeProvider({"uses": list(uses)})
    service = GrammarSelectionService(provider=provider, catalogue=FakeCatalogue(SHI, MA, THERE), **kwargs)
    return service.select(segment=segment(text), source_language=language,
                          previous_context=previous, next_context=following), provider


def test_an_offered_grammar_point_becomes_an_exact_keyed_candidate():
    selection, _ = select("我是学生。你呢？", use("zh.shi_sentence", "是", "我是学生"))
    (shi,) = selection.candidates
    assert (shi.candidate_type, shi.grammar_key, shi.grammar_label) == (
        CandidateType.GRAMMAR_PATTERN, "zh.shi_sentence", "Câu với 是")
    assert (shi.evidence_start, shi.evidence_end, shi.normalized_form) == (1, 2, "A + 是 + B")
    assert selection.errors == [] and not selection.failed_closed


def test_the_model_reads_neighbours_to_rebuild_split_sentences():
    prompt = build_grammar_selection_prompt(source_language="zh", transcript_text="我是", catalogue=[SHI],
                                            max_uses=3, previous_context="昨天", next_context="坐飞机来的。")
    assert GRAMMAR_SELECTION_PROMPT_VERSION == "grammar_selection_v1"
    for part in ("Subtitles often split one sentence", "是……的", "PREVIOUS (context only):\n昨天",
                 "TARGET:\n我是", "NEXT (context only):\n坐飞机来的。", '"split"', "never from PREVIOUS or NEXT",
                 "- zh.shi_sentence: A + 是 + B — Câu với 是", "Never invent a key"):
        assert part in prompt


def test_a_use_the_model_marks_split_is_skipped_not_kept():
    selection, _ = select("我是坐飞机", use("zh.shi_sentence", "是", "我是坐飞机", status="split"),
                          following="来的。")
    assert selection.candidates == [] and selection.split_skipped == 1 and selection.errors == []


@pytest.mark.parametrize("text, previous, following, kept", [
    ("我是学生", None, "你呢？", False),            # span reaches an open end: the sentence continues
    ("我是学生。", None, "你呢？", True),            # the segment ends a sentence
    ("我是学生", None, None, True),                 # last segment of the transcript
    ("是学生。", "我", None, False),                # starts inside a sentence begun before
    ("是学生。", "你好。", None, True),             # the previous segment ended its sentence
    ("I think there is", None, "a problem.", False),  # the construction ends exactly at the cut
    ("I think there is a bed and", None, "a chair.", True),  # the construction is whole; only the sentence goes on
])
def test_the_server_refuses_spans_on_an_open_segment_boundary(text, previous, following, kept):
    surface, language, key = ("there is", "en", "en.there_is_are") if text.startswith("I think") else (
        "是学生" if text.startswith("是") else "我是学生", "zh", "zh.shi_sentence")
    evidence = surface
    selection, _ = select(text, use(key, surface, evidence), previous=previous, following=following,
                          language=language)
    assert bool(selection.candidates) is kept
    assert selection.split_skipped == (0 if kept else 1)


def test_boundary_guard_ignores_closing_quotes_and_trailing_spaces():
    assert not touches_open_boundary("他说：“我是学生。” ", 4, 8, None, "下一句")
    assert touches_open_boundary("我是学生，", 0, 4, None, "你呢？")


@pytest.mark.parametrize("bad, error", [
    (use("zh.made_up", "是", "我是学生"), "names a grammar key that was not offered"),
    (use("zh.shi_sentence", "是", "他是老师"), "not uniquely grounded"),
    (use("zh.shi_sentence", "吗", "我是学生"), "does not contain its surface form"),
])
def test_invented_keys_and_ungrounded_spans_are_rejected(bad, error):
    selection, _ = select("我是学生。", bad)
    assert selection.candidates == [] and any(error in item for item in selection.errors)


def test_repeated_evidence_is_ambiguous_and_each_point_is_kept_once():
    ambiguous, _ = select("我是学生，我是学生。", use("zh.shi_sentence", "是", "我是学生"))
    assert ambiguous.candidates == [] and "not uniquely grounded" in ambiguous.errors[0]
    twice, _ = select("我是学生，他是老师。", use("zh.shi_sentence", "是", "我是学生"),
                      use("zh.shi_sentence", "是", "他是老师"))
    assert [c.evidence_start for c in twice.candidates] == [1]


def test_too_many_uses_or_a_provider_failure_fail_closed():
    many, _ = select("我是学生。", *[use("zh.shi_sentence", "是", "我是学生")] * 4, max_uses=3)
    assert many.candidates == [] and many.failed_closed
    failed, _ = select("我是学生。", provider=FakeProvider(LLMProviderError("down")))
    assert failed.candidates == [] and failed.failed_closed and failed.errors == ["LLMProviderError"]
    with pytest.raises(LLMProviderError):
        select("我是学生。", provider=FakeProvider(LLMProviderError("down")), propagate_failures=True)


def test_no_catalogue_means_no_call_and_the_catalogue_is_read_once():
    provider = FakeProvider()
    service = GrammarSelectionService(provider=provider, catalogue=FakeCatalogue(SHI))
    assert service.select(segment=segment("こんにちは。"), source_language="ja").candidates == []
    assert provider.prompts == []
    catalogue = FakeCatalogue(SHI)
    service = GrammarSelectionService(provider=FakeProvider({"uses": []}, {"uses": []}), catalogue=catalogue)
    for _ in range(2):
        service.select(segment=segment("我是学生。"), source_language="zh")
    assert catalogue.calls == 1


PRONOUNS = GrammarCatalogueItem(key="zh.personal_pronouns", title="Đại từ", pattern="我 / 你 / 他",
                                forms=("我", "你", "他", "我们"))
BE = GrammarCatalogueItem(key="en.be_present", title="to be", pattern="I am …", forms=("am", "is", "are", "'m"))


@pytest.mark.parametrize("language, text, item, surface, kept", [
    ("zh", "李明，你好！", PRONOUNS, "李明", False),     # a name is not a pronoun
    ("zh", "我们每天都很忙。", PRONOUNS, "我们", True),
    ("en", "I'm very well.", BE, "I'm", True),          # contraction
    ("en", "The room is small.", BE, "is", True),
    ("en", "I like this island.", BE, "island", False),  # "is" inside a longer word does not count
])
def test_a_point_with_forms_needs_one_of_them_in_the_span(language, text, item, surface, kept):
    provider = FakeProvider({"uses": [use(item.key, surface, surface)]})
    service = GrammarSelectionService(provider=provider, catalogue=FakeCatalogue(item))
    selection = service.select(segment=segment(text), source_language=language)
    assert bool(selection.candidates) is kept
    assert selection.form_mismatch_skipped == (0 if kept else 1)
    assert "(forms: " in provider.prompts[0]


def test_the_schema_is_strict():
    with pytest.raises(ValidationError):
        LLMGrammarResponse.model_validate({"uses": [{**use("zh.shi_sentence", "是", "我是学生"), "level": "HSK1"}]})
    with pytest.raises(ValidationError):
        LLMGrammarResponse.model_validate({"uses": [use("zh.shi_sentence", "是", "我是学生", status="maybe")]})
    with pytest.raises(ValidationError):
        LLMGrammarResponse.model_validate({"uses": [use("zh.shi_sentence", "是", "我是学生", confidence=1.5)]})


def test_an_english_surface_is_grounded_on_a_whole_word_not_inside_a_longer_one():
    article = GrammarCatalogueItem(key="en.article_a", title="Mạo từ a", pattern="a + danh từ số ít")
    text = "they're looking at a photo of their romantic partner,"
    provider = FakeProvider({"uses": [use("en.article_a", "a", "looking at a photo")]})
    service = GrammarSelectionService(provider=provider, catalogue=FakeCatalogue(article))
    selection = service.select(segment=segment(text), source_language="en", previous_context=None, next_context=None)
    (candidate,) = selection.candidates
    assert text[candidate.evidence_start:candidate.evidence_end] == "a"
    assert candidate.evidence_start == text.index(" a ") + 1
