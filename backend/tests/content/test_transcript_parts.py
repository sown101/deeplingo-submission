"""Study parts cut by AI (2026-11-05). No live AI: the provider is a mock."""
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.bootstrap.wiring.content import get_transcript_parts_service, get_word_lookup_limiter
from app.bootstrap.wiring.identity import get_jwt_verifier
from app.main import app
from app.modules.content.application.library import LearnerLibraryError
from app.modules.content.application.transcript_parts import (
    VERSION, PartsAnswer, TranscriptPartsService, fallback_parts, parts_from_answer,
)
from app.modules.content.domain.catalog import TranscriptSegment
from app.modules.content.domain.workspace import MAX_REGION_SEGMENTS
from app.modules.identity.contracts import CurrentUser


class Cache:
    def __init__(self):
        self.rows, self.writes = {}, []

    def get(self, transcript_id, version):
        return self.rows.get((transcript_id, version))

    def save(self, transcript_id, version, parts):
        self.rows[(transcript_id, version)] = parts
        self.writes.append((transcript_id, version))


def segments(track, count, step_ms=5000):
    return [TranscriptSegment(id=uuid4(), transcript_id=track, sequence_number=index, start_ms=index * step_ms,
                              end_ms=index * step_ms + step_ms - 100, text=f"Sentence {index}.")
            for index in range(count)]


def answer(*starts):
    return PartsAnswer.model_validate({"parts": [{"start": start, "title": f"Phần {n}"} for n, start in enumerate(starts, 1)]})


@pytest.fixture
def source():
    owner, item, video_id, track = [uuid4() for _ in range(4)]
    library, videos, transcripts, store, preferences, provider = [Mock() for _ in range(6)]
    allowed = {owner}
    library.get_for_user.side_effect = lambda **kw: SimpleNamespace(video_id=video_id) if kw["user_id"] in allowed else None
    videos.get_by_id.return_value = SimpleNamespace(id=video_id, processing_status="transcript_ready",
                                                    original_language_code="en")
    transcripts.list_for_video.return_value = [SimpleNamespace(id=track, is_original=True, language_code="en",
                                                               source="caption_track")]
    rows = segments(track, 30)
    store.list_for_transcript.return_value = rows
    preferences.get_by_language_for_user.return_value = SimpleNamespace(support_language_code="vi")
    provider.generate_structured.return_value = answer(1, 9, 21)
    cache = Cache()
    service = TranscriptPartsService(library=library, videos=videos, transcripts=transcripts, segments=store,
                                     preferences=preferences, cache=cache, provider=provider)
    return SimpleNamespace(service=service, user=CurrentUser(id=owner), item=item, track=track, rows=rows,
                           provider=provider, cache=cache, allowed=allowed, store=store)


def test_the_model_cuts_by_meaning_and_the_server_turns_starts_into_exact_ranges(source):
    view = source.service.parts(source.user, source.item)
    assert view.source == "ai"
    assert [(p.start_segment_id, p.end_segment_id, p.segment_count, p.title) for p in view.parts] == [
        (source.rows[0].id, source.rows[7].id, 8, "Phần 1"),
        (source.rows[8].id, source.rows[19].id, 12, "Phần 2"),
        (source.rows[20].id, source.rows[29].id, 10, "Phần 3")]
    prompt = source.provider.generate_structured.call_args.args[0]
    assert "[1] (0:00) Sentence 0." in prompt and '"support_language": "vi"' in prompt


def test_parts_are_cached_per_transcript_so_a_video_costs_one_model_call(source):
    source.service.parts(source.user, source.item)
    again = source.service.parts(source.user, source.item)
    assert again.source == "ai" and len(again.parts) == 3
    assert source.provider.generate_structured.call_count == 1
    assert source.cache.writes == [(source.track, VERSION)]


def test_a_cached_cut_that_no_longer_matches_the_transcript_is_asked_again(source):
    source.service.parts(source.user, source.item)
    source.store.list_for_transcript.return_value = segments(source.track, 30)  # a new transcript version
    source.service.parts(source.user, source.item)
    assert source.provider.generate_structured.call_count == 2


def test_an_empty_answer_is_rejected(source):
    assert parts_from_answer(PartsAnswer(parts=[]), source.rows) is None


@pytest.mark.parametrize("starts", [(2, 9), (1, 9, 9), (1, 12, 9), (1, 31)])
def test_an_answer_that_does_not_describe_the_transcript_is_rejected(source, starts):
    assert parts_from_answer(answer(*starts), source.rows) is None


def test_an_unusable_answer_falls_back_to_sentence_count_and_is_not_cached(source):
    source.provider.generate_structured.return_value = answer(2, 9)
    view = source.service.parts(source.user, source.item)
    assert view.source == "fallback" and sum(p.segment_count for p in view.parts) == 30
    assert all(p.title is None for p in view.parts) and source.cache.writes == []


def test_a_model_failure_never_blocks_the_learner(source):
    source.provider.generate_structured.side_effect = RuntimeError("provider down")
    view = source.service.parts(source.user, source.item)
    assert view.source == "fallback" and view.parts[0].start_segment_id == source.rows[0].id


def test_a_part_the_model_made_too_long_is_cut_within_the_region_limits(source):
    rows = segments(source.track, 90, step_ms=3000)
    parts = parts_from_answer(answer(1), rows)
    assert sum(p.segment_count for p in parts) == 90
    assert all(p.segment_count <= MAX_REGION_SEGMENTS for p in parts) and {p.title for p in parts} == {"Phần 1"}


def test_a_part_longer_than_two_and_a_half_minutes_is_split_evenly_keeping_its_title(source):
    rows = segments(source.track, 40, step_ms=5000)  # 200 seconds
    parts = parts_from_answer(answer(1), rows)
    assert [p.segment_count for p in parts] == [20, 20] and {p.title for p in parts} == {"Phần 1"}


def test_the_fallback_keeps_parts_of_about_a_minute():
    parts = fallback_parts(segments(uuid4(), 30))
    assert [p.segment_count for p in parts] == [12, 12, 6]


def test_another_learner_never_reaches_the_cache_or_the_model(source):
    with pytest.raises(LearnerLibraryError):
        source.service.parts(CurrentUser(id=uuid4()), source.item)
    assert source.provider.generate_structured.call_count == 0 and source.cache.writes == []


def test_the_route_returns_the_parts():
    owner, part = uuid4(), uuid4()
    service = Mock()
    service.parts.return_value = {"transcript_id": str(uuid4()), "source": "ai", "parts": [{
        "start_segment_id": str(part), "end_segment_id": str(part), "start_ms": 0, "end_ms": 900,
        "segment_count": 1, "title": "Chào hỏi"}]}
    limiter = Mock()
    limiter.allow.return_value = True
    verifier = Mock()
    verifier.verify.return_value = CurrentUser(id=owner)
    app.dependency_overrides.update({get_transcript_parts_service: lambda: service,
                                     get_word_lookup_limiter: lambda: limiter, get_jwt_verifier: lambda: verifier})
    try:
        response = TestClient(app).get(f"/api/v1/v3/learner/me/library/videos/{uuid4()}/parts",
                                       headers={"Authorization": "Bearer parts.test.jwt"})
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200 and response.json()["parts"][0]["title"] == "Chào hỏi"


@pytest.mark.parametrize("method, path, service_dependency, call", [
    ("get", "parts", get_transcript_parts_service, "parts"),
    ("post", "translations", "translations", "ensure"),
    ("post", "grammar-explanations", "grammar", "explain"),
])
def test_an_on_demand_endpoint_that_fails_answers_503_and_logs_the_failure_type(
        method, path, service_dependency, call, caplog):
    from app.bootstrap.wiring.content import get_segment_translation_service, get_transcript_grammar_service
    dependency = {"translations": get_segment_translation_service,
                  "grammar": get_transcript_grammar_service}.get(service_dependency, service_dependency)
    service = Mock()
    getattr(service, call).side_effect = RuntimeError("provider body with learner text")
    limiter = Mock()
    limiter.allow.return_value = True
    verifier = Mock()
    verifier.verify.return_value = CurrentUser(id=uuid4())
    app.dependency_overrides.update({dependency: lambda: service, get_word_lookup_limiter: lambda: limiter,
                                     get_jwt_verifier: lambda: verifier})
    body = {"json": {"segment_id": str(uuid4()), "start_codepoint": 0, "end_codepoint": 3}} if call == "explain" else {}
    try:
        response = getattr(TestClient(app), method)(f"/api/v1/v3/learner/me/library/videos/{uuid4()}/{path}",
                                                    headers={"Authorization": "Bearer parts.test.jwt"}, **body)
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 503
    assert "RuntimeError" in caplog.text and "learner text" not in caplog.text
