from app.modules.content.application.transcript_grammar import GrammarExplanation
from tests.content.test_transcript_grammar import request, source  # noqa: F401  (fixtures)


def _model_titles():
    return GrammarExplanation.model_validate({
        "sentence_structure": {"title": "Cấu trúc của câu", "text": "Chủ ngữ + động từ."},
        "grammar": {"title": "Điểm ngữ pháp", "text": "Dùng am với I."},
        "important_words": {"title": "Từ vựng quan trọng", "text": "happy: vui."},
    })


def test_ai_explanations_for_a_vietnamese_learner_carry_the_three_agreed_titles(source):  # noqa: F811
    f = source
    f.points.for_keys.return_value = []
    f.provider.generate_structured.return_value = _model_titles()
    view = f.service.explain(f.user, f.item, request(f))
    assert view.source == "ai_unverified"
    assert [view.explanation.sentence_structure.title, view.explanation.grammar.title,
            view.explanation.important_words.title] == ["Cấu trúc câu", "Ngữ pháp", "Từ và cụm quan trọng"]
    assert view.explanation.grammar.text == "Dùng am với I."


def test_an_older_cached_explanation_gets_the_same_titles(source):  # noqa: F811
    f = source
    f.points.for_keys.return_value = []
    f.provider.generate_structured.return_value = _model_titles()
    f.service.explain(f.user, f.item, request(f))
    f.provider.generate_structured.reset_mock()
    f.cache.rows = {key: _model_titles().model_dump() for key in f.cache.rows}
    view = f.service.explain(f.user, f.item, request(f))
    f.provider.generate_structured.assert_not_called()
    assert view.explanation.important_words.title == "Từ và cụm quan trọng"


def test_other_support_languages_keep_the_titles_the_model_wrote(source):  # noqa: F811
    f = source
    f.points.for_keys.return_value = []
    f.preferences.get_by_language_for_user.return_value = type("P", (), {"support_language_code": "en"})()
    f.provider.generate_structured.return_value = GrammarExplanation.model_validate({
        "sentence_structure": {"title": "Sentence structure", "text": "a"}, "grammar": {"title": "Grammar", "text": "b"},
        "important_words": {"title": "Key words", "text": "c"}})
    view = f.service.explain(f.user, f.item, request(f))
    assert view.explanation.important_words.title == "Key words"
