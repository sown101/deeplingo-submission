from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import Mock
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.bootstrap.wiring.identity import get_jwt_verifier
from app.bootstrap.wiring.content import get_learner_library_service
from app.modules.identity.contracts import CurrentUser
from app.modules.content.domain.library import LearnerVideo
from app.modules.content.domain.catalog import Video, VideoTranscript
from app.modules.content.application.library import (
    ImportBudgetDecision,
    LearnerLibraryError,
    LearnerLibraryService,
)
from app.modules.content.domain.work_intents import AdmittedVideoWork, VideoWorkIntent
from app.main import app
from app.modules.content.infrastructure.youtube import YouTubeService


USER_A = UUID("11111111-1111-1111-1111-111111111111")
USER_B = UUID("22222222-2222-2222-2222-222222222222")
MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "supabase"
    / "migrations"
    / "20260922044507_v6a1_content_library_contracts.sql"
)


class FakeVerifier:
    def __init__(self, user_id: UUID):
        self.user_id = user_id

    def verify(self, token: str) -> CurrentUser:
        return CurrentUser(id=self.user_id, role="authenticated", claims={"app_metadata": {}})


class FakeVideos:
    def __init__(self):
        self.by_id: dict[UUID, Video] = {}
        self.by_external: dict[tuple[str, str], UUID] = {}

    def create(self, external_video_id: str) -> Video:
        video = Video(
            id=uuid4(),
            source="youtube",
            external_video_id=external_video_id,
            original_language_code="ja",
            title="Safe title",
            description="Safe description",
            thumbnail_url="https://example.test/thumb.jpg",
            duration_ms=120000,
            processing_status="pending",
            metadata={"provider_secret": "must-not-leak"},
        )
        self.by_id[video.id] = video
        self.by_external[(video.source, external_video_id)] = video.id
        return video

    def get_by_id(self, video_id: UUID):
        return self.by_id.get(video_id)

    def get_many_by_ids(self, video_ids: list[UUID]):
        return {video_id: self.by_id[video_id] for video_id in video_ids if video_id in self.by_id}

    def get_by_source_external(self, source: str, external_video_id: str):
        video_id = self.by_external.get((source, external_video_id))
        return self.by_id.get(video_id) if video_id else None

    def update_status(
        self,
        video_id: UUID,
        status: str,
        *,
        failure_code: str | None = None,
        retryable: bool = False,
    ):
        current = self.by_id.get(video_id)
        if current is None:
            return None
        updated = current.model_copy(
            update={
                "processing_status": status,
                "processing_error": None,
                "processing_error_code": failure_code,
                "processing_retryable": retryable,
            }
        )
        self.by_id[video_id] = updated
        return updated

    def reset_failed_for_retry(self, video_id: UUID):
        current = self.by_id.get(video_id)
        if current is None or current.processing_status != "failed" or not current.processing_retryable:
            return None
        return self.update_status(video_id, "pending")

    def reset_failed_learning_for_retry(self, video_id: UUID):
        current = self.by_id.get(video_id)
        if current is None or current.learning_status != "failed" or not current.learning_retryable:
            return None
        updated = current.model_copy(update={"learning_status": "not_started", "learning_retryable": False})
        self.by_id[video_id] = updated
        return updated

    def mark_learning_dispatch_failed(self, video_id: UUID):
        current = self.by_id.get(video_id)
        updated = current.model_copy(update={"learning_status": "failed", "learning_retryable": True})
        self.by_id[video_id] = updated
        return updated


class FakeIngestion:
    def __init__(self, videos: FakeVideos):
        self.videos = videos

    def prepare_video(self, url: str):
        external_id = _external_id(url)
        existing = self.videos.get_by_source_external("youtube", external_id)
        if existing is not None:
            return existing, False
        return self.videos.create(external_id), True


class FakeLibrary:
    def __init__(self):
        self.rows: dict[tuple[UUID, UUID], LearnerVideo] = {}
        self.clock = datetime(2026, 9, 22, tzinfo=UTC)

    def upsert_for_user(self, *, user_id: UUID, video_id: UUID):
        key = (user_id, video_id)
        if key not in self.rows:
            created_at = self.clock + timedelta(seconds=len(self.rows))
            self.rows[key] = LearnerVideo(
                id=uuid4(),
                user_id=user_id,
                video_id=video_id,
                created_at=created_at,
                updated_at=created_at,
            )
        return self.rows[key]

    def get_for_user(self, *, library_item_id: UUID, user_id: UUID):
        return next(
            (row for row in self.rows.values() if row.id == library_item_id and row.user_id == user_id),
            None,
        )

    def list_for_user(self, user_id: UUID, *, limit: int = 50):
        rows = [row for row in self.rows.values() if row.user_id == user_id]
        return sorted(rows, key=lambda row: row.created_at, reverse=True)[:limit]


class FakeTranscripts:
    def __init__(self):
        self.ready_video_ids: set[UUID] = set()

    def list_for_video(self, video_id: UUID):
        if video_id not in self.ready_video_ids:
            return []
        return [
            VideoTranscript(
                id=uuid4(),
                video_id=video_id,
                language_code="ja",
                is_original=True,
            )
        ]


class FakeDispatcher:
    def __init__(self, intents):
        self.intents = intents
        self.video_ids: list[UUID] = []

    def dispatch(self, intent_id: UUID):
        self.video_ids.append(self.intents.rows[intent_id].video_id)
        return True


class FakeWorkIntents:
    def __init__(self, videos: FakeVideos, library: FakeLibrary):
        self.videos = videos
        self.library = library
        self.rows: dict[UUID, VideoWorkIntent] = {}

    def admit(self, *, user_id, video_id, action, library_item_id=None):
        video = self.videos.get_by_id(video_id)
        if action == "import":
            association = self.library.upsert_for_user(user_id=user_id, video_id=video_id)
        else:
            association = self.library.get_for_user(library_item_id=library_item_id, user_id=user_id)
            if association is None or association.video_id != video_id:
                raise ValueError("Library item not found")
        command = "reused"
        stage = None
        if action == "retry_transcript" or (action == "import" and video.processing_status == "failed" and video.processing_retryable):
            video = self.videos.reset_failed_for_retry(video_id)
            stage = "transcript"
            command = "retry_accepted"
        elif action == "retry_preparation":
            video = self.videos.reset_failed_learning_for_retry(video_id)
            stage = "learning_preparation"
            command = "learning_retry_accepted"
        elif video.processing_status == "pending":
            stage = "transcript"
        elif video.processing_status in {"transcript_ready", "learning_objects_ready"} and video.learning_status == "not_started":
            stage = "learning_preparation"
        active = next((row for row in self.rows.values() if row.video_id == video_id and row.stage == stage and row.state == "pending"), None)
        if command != "reused" and active is not None:
            self.rows[active.id] = VideoWorkIntent(active.id, active.video_id, active.stage, active.generation, "failed")
            active = None
        created = stage is not None and active is None
        if created:
            generation = 1 + max((row.generation for row in self.rows.values() if row.video_id == video_id and row.stage == stage), default=0)
            active = VideoWorkIntent(uuid4(), video_id, stage, generation, "pending")
            self.rows[active.id] = active
            if command == "reused" and stage == "transcript":
                command = "accepted"
        return AdmittedVideoWork(association, video, active.id if active else None, command, created)


def _external_id(url: str) -> str:
    if "watch?v=shared123" in url or "youtu.be/shared123" in url:
        return "shared123"
    raise ValueError("invalid video url")


def make_service():
    videos = FakeVideos()
    library = FakeLibrary()
    transcripts = FakeTranscripts()
    intents = FakeWorkIntents(videos, library)
    dispatcher = FakeDispatcher(intents)
    service = LearnerLibraryService(
        library=library,
        videos=videos,
        transcripts=transcripts,
        ingestion=FakeIngestion(videos),
        work_intents=intents,
        dispatcher=dispatcher,
        import_budget=Mock(charge=Mock(return_value=ImportBudgetDecision(True, False, 0, 5, None))),
    )
    return service, videos, library, transcripts, dispatcher


def user(user_id: UUID) -> CurrentUser:
    return CurrentUser(id=user_id, role="authenticated", claims={"app_metadata": {}})


def test_same_learner_and_youtube_identity_are_idempotent():
    service, videos, library, _, dispatcher = make_service()

    first = service.import_video(user(USER_A), "https://youtube.com/watch?v=shared123")
    second = service.import_video(user(USER_A), "https://youtu.be/shared123")

    assert first.item.library_item_id == second.item.library_item_id
    assert first.item.video_id == second.item.video_id
    assert first.command_status == "accepted"
    assert second.command_status == "reused"
    assert len(videos.by_id) == 1
    assert len(library.rows) == 1
    assert dispatcher.video_ids == [first.item.video_id]


def test_new_pending_video_with_no_prior_intent_is_admitted_on_import():
    service, videos, _, _, dispatcher = make_service()
    video = videos.create("shared123")
    assert service.work_intents.rows == {}

    response = service.import_video(user(USER_A), "https://youtube.com/watch?v=shared123")
    assert response.command_status == "accepted"
    assert dispatcher.video_ids == [video.id]
    assert len(service.work_intents.rows) == 1


def test_broker_failure_after_admission_still_returns_accepted_pending():
    service, videos, library, _, _ = make_service()

    class DownDispatcher:
        def dispatch(self, intent_id):
            raise ConnectionError("broker unavailable")

    service.dispatcher = DownDispatcher()
    result = service.import_video(user(USER_A), "https://youtube.com/watch?v=shared123")
    assert result.command_status == "accepted"
    assert result.item.processing_status.value == "pending"
    assert len(service.work_intents.rows) == 1
    assert len(videos.by_id) == 1 and len(library.rows) == 1


def test_explicit_retry_creates_distinct_generation_without_new_library_membership():
    service, videos, library, _, dispatcher = make_service()
    first = service.import_video(user(USER_A), "https://youtube.com/watch?v=shared123")
    video_id = first.item.video_id
    videos.update_status(video_id, "failed", failure_code="processing_failed", retryable=True)

    second = service.retry_video(user(USER_A), first.item.library_item_id)
    assert second.command_status == "retry_accepted"
    assert {row.generation for row in service.work_intents.rows.values()} == {1, 2}
    assert len(library.rows) == 1
    assert dispatcher.video_ids == [video_id, video_id]


def test_supported_youtube_url_shapes_normalize_to_one_external_identity():
    youtube = YouTubeService()

    identities = {
        youtube.extract_video_id("https://www.youtube.com/watch?v=shared12345&feature=youtu.be"),
        youtube.extract_video_id("https://youtu.be/shared12345?t=10"),
        youtube.extract_video_id("https://www.youtube.com/embed/shared12345"),
        youtube.extract_video_id("https://www.youtube.com/shorts/shared12345"),
    }

    assert identities == {"shared12345"}


def test_two_learners_share_one_video_and_receive_two_associations():
    service, videos, library, _, dispatcher = make_service()

    learner_a = service.import_video(user(USER_A), "https://youtube.com/watch?v=shared123")
    learner_b = service.import_video(user(USER_B), "https://youtu.be/shared123")

    assert learner_a.item.video_id == learner_b.item.video_id
    assert learner_a.item.library_item_id != learner_b.item.library_item_id
    assert len(videos.by_id) == 1
    assert len(library.rows) == 2
    assert len(dispatcher.video_ids) == 1


def test_failed_retry_reuses_video_and_library_item():
    service, videos, library, _, dispatcher = make_service()
    imported = service.import_video(user(USER_A), "https://youtube.com/watch?v=shared123")
    videos.update_status(
        imported.item.video_id,
        "failed",
        failure_code="processing_failed",
        retryable=True,
    )

    retried = service.retry_video(user(USER_A), imported.item.library_item_id)

    assert retried.command_status == "retry_accepted"
    assert retried.item.library_item_id == imported.item.library_item_id
    assert retried.item.video_id == imported.item.video_id
    assert retried.item.processing_status == "pending"
    assert len(library.rows) == 1
    assert dispatcher.video_ids == [imported.item.video_id, imported.item.video_id]


def test_detail_maps_content_ready_and_transcript_without_internal_fields():
    service, videos, _, transcripts, _ = make_service()
    imported = service.import_video(user(USER_A), "https://youtube.com/watch?v=shared123")
    transcripts.ready_video_ids.add(imported.item.video_id)
    videos.update_status(imported.item.video_id, "transcript_ready")

    detail = service.get_video(user(USER_A), imported.item.library_item_id)
    payload = detail.model_dump(mode="json")

    assert payload["processing_status"] == "ready"
    assert payload["transcript_available"] is True
    assert payload["description"] == "Safe description"
    for forbidden in (
        "user_id",
        "metadata",
        "processing_error",
        "processing_error_code",
        "processing_retryable",
        "provider_metadata",
    ):
        assert forbidden not in payload


def test_library_list_is_scoped_and_recent_first():
    service, videos, library, _, _ = make_service()
    first = service.import_video(user(USER_A), "https://youtube.com/watch?v=shared123")
    second_video = videos.create("second456")
    second = library.upsert_for_user(user_id=USER_A, video_id=second_video.id)
    library.upsert_for_user(user_id=USER_B, video_id=first.item.video_id)

    rows = service.list_videos(user(USER_A))

    assert [row.library_item_id for row in rows] == [second.id, first.item.library_item_id]
    assert all(row.library_item_id != next(row.id for row in library.rows.values() if row.user_id == USER_B) for row in rows)


def test_library_list_loads_videos_in_one_batch():
    service, videos, library, _, _ = make_service()
    for external_id in ("batch001", "batch002", "batch003"):
        library.upsert_for_user(user_id=USER_A, video_id=videos.create(external_id).id)
    batches = []
    original = videos.get_many_by_ids
    videos.get_many_by_ids = lambda ids: batches.append(list(ids)) or original(ids)
    videos.get_by_id = lambda video_id: pytest.fail("list must not load videos one by one")

    rows = service.list_videos(user(USER_A))

    assert len(rows) == 3
    assert len(batches) == 1 and len(batches[0]) == 3


def test_learner_import_requires_auth_and_rejects_authority_fields():
    service, _, _, _, _ = make_service()
    app.dependency_overrides.clear()
    app.dependency_overrides[get_learner_library_service] = lambda: service
    client = TestClient(app)

    unauthenticated = client.post(
        "/api/v1/v3/learner/me/library/videos",
        json={"url": "https://youtube.com/watch?v=shared123"},
    )
    assert unauthenticated.status_code == 401

    app.dependency_overrides[get_jwt_verifier] = lambda: FakeVerifier(USER_A)
    injected = client.post(
        "/api/v1/v3/learner/me/library/videos",
        json={
            "url": "https://youtube.com/watch?v=shared123",
            "user_id": str(USER_B),
        },
        headers={"Authorization": "Bearer a.b.c"},
    )
    assert injected.status_code == 422
    app.dependency_overrides.clear()


def test_cross_user_detail_lookup_returns_404_without_leaking_existence():
    service, _, _, _, _ = make_service()
    item_b = service.import_video(user(USER_B), "https://youtube.com/watch?v=shared123")
    app.dependency_overrides.clear()
    app.dependency_overrides[get_jwt_verifier] = lambda: FakeVerifier(USER_A)
    app.dependency_overrides[get_learner_library_service] = lambda: service
    client = TestClient(app)

    response = client.get(
        f"/api/v1/v3/learner/me/library/videos/{item_b.item.library_item_id}",
        headers={"Authorization": "Bearer a.b.c"},
    )

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "library_item_not_found"
    app.dependency_overrides.clear()


def test_import_response_is_accepted_and_safe():
    service, _, _, _, _ = make_service()
    app.dependency_overrides.clear()
    app.dependency_overrides[get_jwt_verifier] = lambda: FakeVerifier(USER_A)
    app.dependency_overrides[get_learner_library_service] = lambda: service
    client = TestClient(app)

    response = client.post(
        "/api/v1/v3/learner/me/library/videos",
        json={"url": "https://youtube.com/watch?v=shared123"},
        headers={"Authorization": "Bearer a.b.c"},
    )

    assert response.status_code == 202
    item = response.json()["item"]
    assert item["processing_status"] == "pending"
    assert set(item) == {
        "library_item_id", "video_id", "title", "thumbnail_url", "duration_ms",
        "source", "processing_status", "learning_status", "learning_object_count",
        "learning_prepared_language_code", "language_code", "added_at", "failure",
        "description", "transcript_available",
    }
    app.dependency_overrides.clear()


def test_ready_existing_video_dispatches_global_learning_without_affecting_watch_status():
    service, videos, library, transcripts, content_dispatcher = make_service()
    video = videos.create("shared123")
    videos.update_status(video.id, "transcript_ready")
    transcripts.ready_video_ids.add(video.id)

    response = service.import_video(user(USER_A), "https://youtube.com/watch?v=shared123")
    assert response.item.processing_status.value == "ready"
    assert response.item.learning_status.value == "not_started"
    assert response.item.learning_object_count == 0
    assert content_dispatcher.video_ids == [video.id]
    assert library.get_for_user(library_item_id=response.item.library_item_id, user_id=USER_B) is None


def test_learning_retry_is_authorized_and_does_not_reset_video_playback():
    service, videos, _, transcripts, _ = make_service()
    video = videos.create("shared123")
    videos.update_status(video.id, "transcript_ready")
    videos.by_id[video.id] = videos.by_id[video.id].model_copy(update={
        "learning_status": "failed", "learning_retryable": True,
    })
    transcripts.ready_video_ids.add(video.id)
    dispatcher = service.dispatcher
    item = service.import_video(user(USER_A), "https://youtube.com/watch?v=shared123").item

    with pytest.raises(LearnerLibraryError) as denied:
        service.retry_learning(user(USER_B), item.library_item_id)
    assert denied.value.status_code == 404
    retry = service.retry_learning(user(USER_A), item.library_item_id)
    assert retry.command_status == "learning_retry_accepted"
    assert retry.item.processing_status.value == "ready"
    assert dispatcher.video_ids == [video.id]


def test_learning_retry_endpoint_uses_only_authorized_library_identity():
    service, videos, _, transcripts, _ = make_service()
    video = videos.create("shared123")
    videos.update_status(video.id, "transcript_ready")
    videos.by_id[video.id] = videos.by_id[video.id].model_copy(update={
        "learning_status": "failed", "learning_retryable": True,
    })
    transcripts.ready_video_ids.add(video.id)
    item = service.import_video(user(USER_A), "https://youtube.com/watch?v=shared123").item
    app.dependency_overrides.clear()
    app.dependency_overrides[get_learner_library_service] = lambda: service
    app.dependency_overrides[get_jwt_verifier] = lambda: FakeVerifier(USER_B)
    client = TestClient(app)
    url = f"/api/v1/v3/learner/me/library/videos/{item.library_item_id}/learning/retry"
    assert client.post(url, headers={"Authorization": "Bearer a.b.c"}).status_code == 404
    app.dependency_overrides[get_jwt_verifier] = lambda: FakeVerifier(USER_A)
    response = client.post(url, headers={"Authorization": "Bearer a.b.c"})
    assert response.status_code == 202
    assert response.json()["item"]["processing_status"] == "ready"
    assert "provider" not in response.text and "failure_code" not in response.text
    app.dependency_overrides.clear()


def test_migration_enforces_idempotency_service_writes_and_own_row_reads():
    sql = MIGRATION.read_text(encoding="utf-8").casefold()

    assert "constraint learner_videos_unique_membership unique (user_id, video_id)" in sql
    assert "alter table v3.learner_videos enable row level security" in sql
    assert "grant select on v3.learner_videos to authenticated" in sql
    assert "revoke insert, update, delete on v3.learner_videos from authenticated" in sql
    assert "using ((select auth.uid()) = user_id)" in sql
    assert "learner_videos_user_recent_idx" in sql
    assert "learner_videos_video_id_idx" in sql
    assert "processing_error_code" in sql
    assert "processing_retryable" in sql
    assert "add value if not exists 'processing'" in sql


@pytest.mark.parametrize("url", [
    "https://youtu.be/abc/../x",  # not an 11-character id
    "https://evil.example/?q=youtube.com/watch?v=AAAAAAAAAAA",  # another host that only mentions YouTube
    "https://www.youtube.com/watch?v=short",
    "https://www.youtube.com/@channel",
    "ftp://www.youtube.com/watch?v=dQw4w9WgXcQ",
])
def test_a_url_that_is_not_one_youtube_video_is_refused(url):
    with pytest.raises(ValueError):
        YouTubeService().extract_video_id(url)
    assert YouTubeService().extract_video_id("youtube.com/watch?v=dQw4w9WgXcQ") == "dQw4w9WgXcQ"
