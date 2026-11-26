from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.bootstrap.wiring.content import get_transcript_grammar_service, get_word_lookup_limiter
from app.bootstrap.wiring.identity import get_jwt_verifier
from app.main import app
from app.modules.content.application.library import LearnerLibraryError
from app.modules.content.application.transcript_grammar import (
    GrammarExplanation, TranscriptGrammarRequest, TranscriptGrammarService,
)
from app.modules.identity.contracts import CurrentUser


class Cache:
    def __init__(self):
        self.rows, self.reads, self.writes = {}, [], []

    def get(self, *key):
        self.reads.append(key)
        return self.rows.get(key)

    def save(self, *args):
        key, value = args[:3], args[3]
        self.rows[key] = value
        self.writes.append(args)


def explanation():
    return GrammarExplanation.model_validate({
        "sentence_structure": {"title": "Cấu trúc câu", "text": "Chủ ngữ + to be + tính từ."},
        "grammar": {"title": "Ngữ pháp", "text": "Dùng am với I."},
        "important_words": {"title": "Từ và cụm quan trọng", "text": "happy: vui."},
    })


@pytest.fixture
def source():
    owner, item, video_id, track, first, second = [uuid4() for _ in range(6)]
    library, videos, transcripts, aggregate, preferences, points, provider = [Mock() for _ in range(7)]
    allowed = {owner}
    library.get_for_user.side_effect = lambda **kw: SimpleNamespace(video_id=video_id) if kw["user_id"] in allowed else None
    videos.get_by_id.return_value = SimpleNamespace(id=video_id, processing_status="transcript_ready", original_language_code="en")
    transcripts.list_for_video.return_value = [SimpleNamespace(id=track, is_original=True, language_code="en", source="caption_track")]
    rows = [{"id": str(first), "sequence_number": 1, "text": "I am", "learning_objects": [{
        "id": str(uuid4()), "concept_id": str(uuid4()), "start_codepoint": 2, "end_codepoint": 4,
        "evidence_text": "am", "concepts": {"type": "grammar", "language_code": "en", "sense_key": "en.be_present",
            "metadata": {"grammar_key": "en.be_present"}}, "raw_ai_diagnostics": {},
    }]}, {"id": str(second), "sequence_number": 2, "text": "happy.", "learning_objects": []}]
    aggregate.list_aggregate.return_value = rows
    preferences.get_by_language_for_user.return_value = SimpleNamespace(support_language_code="vi")
    points.for_keys.return_value = [{"key": "en.be_present", "title": "Động từ to be", "pattern": "I am + tính từ",
                                    "explanation": "Dùng am với I.", "forms": ["am"], "examples": []}]
    provider.generate_structured.return_value = explanation()
    cache = Cache()
    service = TranscriptGrammarService(library=library, videos=videos, transcripts=transcripts, aggregate=aggregate,
        preferences=preferences, grammar_points=points, provider=provider, cache=cache)
    return SimpleNamespace(service=service, user=CurrentUser(id=owner), allowed=allowed, item=item, first=first,
        rows=rows, aggregate=aggregate, points=points, provider=provider, preferences=preferences, cache=cache)


def request(f, **changes):
    return TranscriptGrammarRequest(**({"segment_id": f.first, "start_codepoint": 2, "end_codepoint": 4} | changes))


def test_prepared_grammar_is_used_without_ai_cache_or_learner_writes(source):
    f = source
    view = f.service.explain(f.user, f.item, request(f))
    assert view.source == "curriculum_draft" and view.grammar_keys == ["en.be_present"]
    assert view.source_text == "am" and view.explanation.grammar.text == "Dùng am với I."
    f.provider.generate_structured.assert_not_called()
    assert f.cache.reads == [] and f.cache.writes == []


def test_whole_sentence_is_built_from_adjacent_trusted_segments(source):
    f = source
    view = f.service.explain(f.user, f.item, request(f, scope="sentence"))
    assert view.source_text == "I am happy."
    assert view.source == "curriculum_draft"


@pytest.mark.parametrize("first, second, start, end, expected", [
    ("I am Mr.", "Smith.", 0, 5, "I am Mr. Smith."),
    ("“Hello.” I am", "happy.", 0, 5, "I am happy."),
    ('"I am', 'happy."', 0, 5, '"I am happy."'),
])
def test_sentence_boundaries_keep_english_titles_and_exclude_previous_closing_quotes(source, first, second, start, end, expected):
    f = source
    f.rows[0]["text"], f.rows[1]["text"] = first, second
    view = f.service.explain(f.user, f.item, request(f, segment_id=f.rows[1]["id"],
                                                  start_codepoint=start, end_codepoint=end, scope="sentence"))
    assert view.source_text == expected


def test_missing_grammar_uses_one_ai_explanation_shared_across_learners(source):
    f = source
    f.points.for_keys.return_value = []
    first = f.service.explain(f.user, f.item, request(f))
    other = CurrentUser(id=uuid4())
    f.allowed.add(other.id)
    second = f.service.explain(other, f.item, request(f))
    assert first == second and first.source == "ai_unverified"
    f.provider.generate_structured.assert_called_once()
    assert len(f.cache.writes) == 1
    prompt = f.provider.generate_structured.call_args.args[0]
    assert '"selection": "am"' in prompt and '"context": "I am happy."' in prompt
    assert str(f.user.id) not in prompt and str(other.id) not in prompt
    assert all(str(f.user.id) not in str(key) for key in f.cache.rows)


def test_support_language_and_edited_source_have_separate_cache_keys(source):
    f = source
    f.points.for_keys.return_value = []
    f.service.explain(f.user, f.item, request(f))
    f.preferences.get_by_language_for_user.return_value.support_language_code = "en"
    f.service.explain(f.user, f.item, request(f))
    f.rows[1]["text"] = "sad."
    f.service.explain(f.user, f.item, request(f))
    assert len(f.cache.rows) == 3 and f.provider.generate_structured.call_count == 3
    assert {key[1] for key in f.cache.rows} == {"vi", "en"}


def test_same_sentence_selected_from_different_subtitles_shares_the_cache(source):
    f = source
    f.points.for_keys.return_value = []
    first = f.service.explain(f.user, f.item, request(f, scope="sentence"))
    second = f.service.explain(f.user, f.item, request(f, segment_id=f.rows[1]["id"],
                                                     start_codepoint=0, end_codepoint=5, scope="sentence"))
    assert first.source_text == second.source_text == "I am happy."
    assert first.segment_id != second.segment_id
    f.provider.generate_structured.assert_called_once()


def test_curriculum_is_not_returned_in_a_different_support_language(source):
    f = source
    f.preferences.get_by_language_for_user.return_value.support_language_code = "en"
    view = f.service.explain(f.user, f.item, request(f))
    assert view.source == "ai_unverified" and view.support_language_code == "en"
    assert '"support_language": "en"' in f.provider.generate_structured.call_args.args[0]


def test_ownership_is_checked_before_content_cache_or_ai(source):
    f = source
    with pytest.raises(LearnerLibraryError) as exc:
        f.service.explain(CurrentUser(id=uuid4()), f.item, request(f))
    assert exc.value.status_code == 404
    f.aggregate.list_aggregate.assert_not_called()
    assert f.cache.reads == []
    f.provider.generate_structured.assert_not_called()


@pytest.mark.parametrize("changes, code", [
    ({"segment_id": uuid4()}, "grammar_segment_not_found"),
    ({"end_codepoint": 100}, "grammar_invalid_span"),
])
def test_foreign_or_out_of_bounds_selection_never_calls_ai(source, changes, code):
    f = source
    with pytest.raises(LearnerLibraryError) as exc:
        f.service.explain(f.user, f.item, request(f, **changes))
    assert exc.value.code == code
    f.provider.generate_structured.assert_not_called()


@pytest.mark.parametrize("extra", [{"text": "fabricated"}, {"support_language_code": "en"}, {"score": 1}, {"user_id": str(uuid4())}])
def test_client_cannot_supply_text_language_or_learning_authority(source, extra):
    with pytest.raises(ValidationError):
        request(source, **extra)


def test_provider_failure_is_safe_and_not_cached(source):
    f = source
    f.points.for_keys.return_value = []
    f.provider.generate_structured.side_effect = RuntimeError("PRIVATE_PROVIDER_RESPONSE")
    with pytest.raises(LearnerLibraryError) as exc:
        f.service.explain(f.user, f.item, request(f))
    assert exc.value.status_code == 503 and "PRIVATE_PROVIDER_RESPONSE" not in str(exc.value)
    assert f.cache.writes == []


def test_unavailable_logs_the_failure_kind_without_its_text(source, caplog):
    f = source
    f.points.for_keys.return_value = []
    f.provider.generate_structured.side_effect = TimeoutError("PRIVATE_PROVIDER_RESPONSE")
    with caplog.at_level("WARNING"), pytest.raises(LearnerLibraryError):
        f.service.explain(f.user, f.item, request(f))
    assert "TimeoutError" in caplog.text and "PRIVATE_PROVIDER_RESPONSE" not in caplog.text


def test_malformed_model_output_is_not_cached(source):
    f = source
    f.points.for_keys.return_value = []
    f.provider.generate_structured.return_value = {"sentence_structure": "wrong schema"}
    with pytest.raises(LearnerLibraryError):
        f.service.explain(f.user, f.item, request(f))
    assert f.cache.writes == []


def test_chinese_sentence_reconstruction_does_not_insert_latin_spacing(source):
    f = source
    f.service.videos.get_by_id.return_value.original_language_code = "zh"
    f.service.transcripts.list_for_video.return_value[0].language_code = "zh"
    f.rows[0]["text"], f.rows[1]["text"] = "我喜欢", "学习中文。"
    view = f.service.explain(f.user, f.item, request(f, start_codepoint=0, end_codepoint=1, scope="sentence"))
    assert view.source_text == "我喜欢学习中文。" and view.source == "ai_unverified"


def test_cache_read_failure_does_not_start_a_paid_call(source):
    f = source
    f.points.for_keys.return_value = []
    f.service.cache = Mock()
    f.service.cache.get.side_effect = RuntimeError("cache unavailable")
    with pytest.raises(LearnerLibraryError):
        f.service.explain(f.user, f.item, request(f))
    f.provider.generate_structured.assert_not_called()


def test_valid_maximum_length_authored_explanation_needs_no_ai(source):
    f = source
    f.points.for_keys.return_value[0]["explanation"] = "a" * 1200
    assert f.service.explain(f.user, f.item, request(f)).source == "curriculum_draft"
    f.provider.generate_structured.assert_not_called()


@pytest.fixture
def api(source, monkeypatch):
    verifier, limiter = Mock(), Mock()
    verifier.verify.return_value = source.user
    limiter.allow.return_value = True
    monkeypatch.setitem(app.dependency_overrides, get_jwt_verifier, lambda: verifier)
    monkeypatch.setitem(app.dependency_overrides, get_transcript_grammar_service, lambda: source.service)
    monkeypatch.setitem(app.dependency_overrides, get_word_lookup_limiter, lambda: limiter)
    client = TestClient(app)
    yield SimpleNamespace(client=client, limiter=limiter, source=source,
        url=f"/api/v1/v3/learner/me/library/videos/{source.item}/grammar-explanations",
        headers={"Authorization": "Bearer grammar.test.jwt"}, payload=request(source).model_dump(mode="json"))
    client.close()


def test_route_accepts_only_positions_and_rejects_client_text(api):
    a = api
    response = a.client.post(a.url, json=a.payload, headers=a.headers)
    assert response.status_code == 200 and response.json()["source"] == "curriculum_draft"
    denied = a.client.post(a.url, json=a.payload | {"text": "fabricated"}, headers=a.headers)
    assert denied.status_code == 422
    a.source.provider.generate_structured.assert_not_called()


def test_route_requires_auth_and_library_ownership(api):
    a = api
    assert a.client.post(a.url, json=a.payload).status_code == 401
    a.source.allowed.clear()
    assert a.client.post(a.url, json=a.payload, headers=a.headers).status_code == 404
    assert a.source.cache.reads == []


def test_route_rate_limit_precedes_content_cache_and_ai(api):
    a = api
    a.limiter.allow.return_value = False
    assert a.client.post(a.url, json=a.payload, headers=a.headers).status_code == 429
    a.source.aggregate.list_aggregate.assert_not_called()
    a.source.provider.generate_structured.assert_not_called()
