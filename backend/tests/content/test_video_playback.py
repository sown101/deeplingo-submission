from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.bootstrap.wiring.identity import get_jwt_verifier
from app.bootstrap.wiring.content import get_video_playback_service
from app.modules.identity.contracts import CurrentUser
from app.modules.content.application.playback_views import TranscriptSegmentView
from app.modules.content.application.playback import VideoPlaybackService
from app.main import app
from app.modules.content.infrastructure.repositories.playback_transcripts import (
    PlaybackTranscriptRepository,
)
from app.modules.content.infrastructure.sources import LocalRomanizationProvider


@pytest.fixture
def fixture():
    owner, other, item, video_id, track_id = [uuid4() for _ in range(5)]
    video = SimpleNamespace(id=video_id, source="youtube", external_video_id="jNQXAC9IVRw",
                            title="Video", original_language_code="ja", duration_ms=3000,
                            processing_status="transcript_ready", metadata={"secret": "hidden"})
    library, videos, tracks, aggregate, preferences = [Mock() for _ in range(5)]
    library.get_for_user.side_effect = lambda library_item_id, user_id: (
        SimpleNamespace(video_id=video_id) if user_id == owner and library_item_id == item else None)
    videos.get_by_id.return_value = video
    tracks.list_for_video.return_value = [SimpleNamespace(id=track_id, is_original=True,
        language_code="ja", source="caption_track")]
    preferences.get_by_language_for_user.return_value = SimpleNamespace(support_language_code="vi")
    rows = [dict(id=str(uuid4()), sequence_number=i + 1, text=f"Text {i}", start_ms=i * 1000,
        end_ms=(i + 1) * 1000, metadata={"secret": "hidden"},
        segment_translations=[dict(language_code="en", text="Not selected"),
                              dict(language_code="vi", text="Translation")],
        segment_romanizations=[dict(text="reading", romanization_systems=dict(code="romaji", is_active=True)),
                               dict(text="hidden", romanization_systems=dict(code="old", is_active=False))])
        for i in range(3)]
    aggregate.list_aggregate.return_value = list(reversed(rows))
    service = VideoPlaybackService(library=library, videos=videos, transcripts=tracks,
                                   aggregate=aggregate, preferences=preferences,
                                   romanization_provider=LocalRomanizationProvider(), romanization_systems=Mock())
    verifier = Mock()
    verifier.verify.side_effect = lambda token: CurrentUser(id=other if token == "other.test.jwt" else owner)
    app.dependency_overrides[get_jwt_verifier] = lambda: verifier
    app.dependency_overrides[get_video_playback_service] = lambda: service
    client = TestClient(app)
    try:
        yield SimpleNamespace(client=client, url=f"/api/v1/v3/learner/me/library/videos/{item}",
            owner=owner, item=item, video=video, videos=videos, tracks=tracks,
            aggregate=aggregate, rows=rows, service=service, preferences=preferences)
    finally:
        app.dependency_overrides.clear()


@pytest.mark.parametrize("endpoint", ["playback", "transcript"])
def test_access_requires_auth_and_membership(fixture, endpoint):
    f = fixture
    assert f.client.get(f"{f.url}/{endpoint}").status_code == 401
    assert f.client.get(f"{f.url}/{endpoint}", headers={"Authorization": "Bearer other.test.jwt"}).status_code == 404
    f.videos.get_by_id.assert_not_called()
    response = f.client.get(f"{f.url}/{endpoint}", headers={"Authorization": "Bearer owner.test.jwt"})
    assert response.status_code == 200
    assert "secret" not in response.text and "metadata" not in response.text


def test_aggregate_order_translation_romanization_and_exact_dto(fixture):
    result = fixture.service.transcript(CurrentUser(id=fixture.owner), fixture.item)
    assert [segment.start_ms for segment in result.segments] == [0, 1000, 2000]
    assert result.segments[0].translation.text == "Translation"
    assert [entry.system for entry in result.segments[0].romanizations] == ["romaji"]
    assert set(result.segments[0].model_dump()) == {
        "segment_id", "sequence", "text", "start_ms", "end_ms", "translation", "romanizations", "learning_objects"}


def test_older_chinese_captions_get_pinyin_when_the_active_system_has_no_saved_reading(fixture):
    f = fixture
    f.video.original_language_code = "zh"
    f.tracks.list_for_video.return_value[0].language_code = "zh"
    f.service.romanization_systems.get_by_language_and_code.return_value = SimpleNamespace(is_active=True)
    f.rows[0].update(text="你好", segment_romanizations=[])
    f.rows[1].update(segment_romanizations=[
        dict(text="curated", romanization_systems=dict(code="hanyu-pinyin", is_active=True))])

    result = f.service.transcript(CurrentUser(id=f.owner), f.item)
    assert [(entry.system, entry.text) for entry in result.segments[0].romanizations] == [("hanyu-pinyin", "nǐ hǎo")]
    assert result.segments[1].romanizations[0].text == "curated"
    f.service.romanization_systems.get_by_language_and_code.assert_called_once_with("zh", "hanyu-pinyin")


def test_occurrence_annotations_are_ordered_safe_and_preserve_overlap(fixture):
    first_id, second_id = uuid4(), uuid4()
    concept_id = uuid4()
    context = {"concept_id": str(concept_id), "concept_sense_key": "sample sense",
               "source_language_code": "ja", "target_language_code": "vi",
               "contextual_meaning": "nghĩa trong ngữ cảnh"}
    concept = {"id": str(concept_id), "sense_key": "sample sense", "language_code": "ja"}
    fixture.rows[0]["learning_objects"] = [
        {"id": str(second_id), "start_codepoint": 1, "end_codepoint": 4,
         "evidence_text": "ext", "concept_id": str(concept_id), "concepts": concept,
         "raw_ai_diagnostics": {"rubric": "hidden", "enrichment": context}},
        {"id": str(first_id), "start_codepoint": 0, "end_codepoint": 4,
         "evidence_text": "Text", "concept_id": str(concept_id), "concepts": concept,
         "raw_ai_diagnostics": {"enrichment": context}},
        {"id": str(uuid4()), "start_codepoint": 0, "end_codepoint": 4,
         "evidence_text": "Wrong"},
        {"id": str(uuid4()), "start_codepoint": None, "end_codepoint": None,
         "evidence_text": "Text"},
        {"id": str(uuid4()), "start_codepoint": 0, "end_codepoint": 4,
         "evidence_text": "Text", "concept_id": str(concept_id), "concepts": concept,
         "raw_ai_diagnostics": {}},
    ]
    response = fixture.client.get(f"{fixture.url}/transcript", headers={"Authorization": "Bearer owner.test.jwt"})
    assert response.status_code == 200
    annotations = response.json()["segments"][0]["learning_objects"]
    assert annotations == [
        {"learning_object_id": str(first_id), "start_codepoint": 0, "end_codepoint": 4},
        {"learning_object_id": str(second_id), "start_codepoint": 1, "end_codepoint": 4},
    ]
    assert "concept_id" not in response.text
    assert "raw_ai_diagnostics" not in response.text
    assert "rubric" not in response.text
    denied = fixture.client.get(f"{fixture.url}/transcript", headers={"Authorization": "Bearer other.test.jwt"})
    assert denied.status_code == 404


@pytest.mark.parametrize("change", [{"end_ms": 0}, {"end_ms": 1, "start_ms": 2},
                                   {"text": " "}, {"start_ms": -1}, {"sequence_number": 0}])
def test_malformed_timing_returns_recoverable_contract_error(fixture, change):
    fixture.rows[0].update(change)
    response = fixture.client.get(f"{fixture.url}/transcript", headers={"Authorization": "Bearer owner.test.jwt"})
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "transcript_unavailable"


@pytest.mark.parametrize("missing", ["tracks", "segments", "duplicate", "not_ready", "video"])
def test_missing_duplicate_and_unready_content_safe(fixture, missing):
    f = fixture
    if missing == "tracks":
        f.tracks.list_for_video.return_value = []
    elif missing == "segments":
        f.aggregate.list_aggregate.return_value = []
    elif missing == "duplicate":
        f.aggregate.list_aggregate.return_value = [f.rows[0], f.rows[0]]
    elif missing == "not_ready":
        f.video.processing_status = "processing"
    else:
        f.videos.get_by_id.return_value = None
    response = f.client.get(f"{f.url}/transcript", headers={"Authorization": "Bearer owner.test.jwt"})
    assert response.status_code == (404 if missing == "video" else 409)


def test_optional_support_data_and_safe_server_error(fixture):
    f = fixture
    f.preferences.get_by_language_for_user.return_value = None
    for row in f.rows:
        row["segment_romanizations"] = []
    result = f.service.transcript(CurrentUser(id=f.owner), f.item)
    assert result.translation_language_code is None
    assert all(s.translation is None and s.romanizations == [] for s in result.segments)
    f.aggregate.list_aggregate.side_effect = RuntimeError("provider secret raw diagnostic")
    response = f.client.get(f"{f.url}/transcript", headers={"Authorization": "Bearer owner.test.jwt"})
    assert response.status_code == 503
    assert "secret" not in response.text


def test_unsupported_media_and_extra_fields_rejected(fixture):
    fixture.video.external_video_id = "https://unsafe.test"
    response = fixture.client.get(f"{fixture.url}/playback", headers={"Authorization": "Bearer owner.test.jwt"})
    assert response.status_code == 422
    with pytest.raises(ValueError):
        TranscriptSegmentView(segment_id=uuid4(), sequence=1, text="x", start_ms=0, end_ms=1, metadata={})


def test_aggregate_pagination_is_joined_and_bounded():
    query = Mock()
    for method in ("schema", "table", "select", "eq", "order", "range"):
        getattr(query, method).return_value = query
    query.execute.side_effect = [SimpleNamespace(data=[{}] * 500), SimpleNamespace(data=[{}])]
    assert len(PlaybackTranscriptRepository(query).list_aggregate(uuid4())) == 501
    assert query.execute.call_count == 2
    assert "segment_translations" in query.select.call_args.args[0]
    query.execute.side_effect = None
    query.execute.return_value = SimpleNamespace(data=[{}] * 500)
    with pytest.raises(ValueError, match="supported size"):
        PlaybackTranscriptRepository(query).list_aggregate(uuid4())
