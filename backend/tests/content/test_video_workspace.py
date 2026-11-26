"""M1 S1: per-Library-item watch position and study region, owner-checked end to end."""
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.bootstrap.wiring.content import get_video_workspace_limiter, get_video_workspace_service
from app.bootstrap.wiring.identity import get_jwt_verifier
from app.main import app
from app.modules.content.application.workspace import VideoWorkspaceService
from app.modules.content.domain.catalog import TranscriptSegment
from app.modules.content.domain.workspace import LearnerVideoWorkspace
from app.modules.content.infrastructure.repositories.learner_video_workspaces import (
    LearnerVideoWorkspaceRepository,
)
from app.modules.identity.contracts import CurrentUser
from app.platform.rate_limit import SlidingWindowLimiter

OWNER = {"Authorization": "Bearer owner.test.jwt"}
OTHER = {"Authorization": "Bearer other.test.jwt"}


class MemoryWorkspaces:
    """Row-per-Library-item store that, like PostgREST merge-duplicates, keeps unsent columns."""

    def __init__(self):
        self.rows: dict = {}
        self.calls: list = []

    def get_for_user(self, *, library_item_id, user_id):
        self.calls.append("get")
        row = self.rows.get(library_item_id)
        return LearnerVideoWorkspace(**row) if row and row["user_id"] == user_id else None

    def list_recent_for_user(self, *, user_id, limit):
        self.calls.append("recent")
        rows = sorted((row for row in self.rows.values() if row["user_id"] == user_id),
                      key=lambda row: row["updated_at"], reverse=True)
        return [LearnerVideoWorkspace(**row) for row in rows[:limit]]

    def _save(self, library_item_id, user_id, **columns):
        row = self.rows.setdefault(library_item_id, {"library_item_id": library_item_id, "user_id": user_id})
        row.update(columns, updated_at=datetime.now(UTC))
        return LearnerVideoWorkspace(**row)

    def save_position(self, *, library_item_id, user_id, position_ms):
        self.calls.append("position")
        return self._save(library_item_id, user_id, position_ms=position_ms)

    def save_region(self, *, library_item_id, user_id, transcript_id, start_segment_id, end_segment_id):
        self.calls.append("region")
        return self._save(library_item_id, user_id, region_transcript_id=transcript_id,
                          region_start_segment_id=start_segment_id, region_end_segment_id=end_segment_id)


def _segments(transcript_id, count, length_ms=4000):
    return [TranscriptSegment(id=uuid4(), transcript_id=transcript_id, sequence_number=i + 1,
                              start_ms=i * length_ms, end_ms=(i + 1) * length_ms, text=f"Sentence {i}")
            for i in range(count)]


@pytest.fixture
def ws():
    owner, other, item, other_item, video_id, track_id = [uuid4() for _ in range(6)]
    video = SimpleNamespace(id=video_id, original_language_code="en", duration_ms=120_000,
                            processing_status="learning_objects_ready", title="Me at the zoo", thumbnail_url=None)
    library, videos, transcripts, segments = Mock(), Mock(), Mock(), Mock()
    owned = {(owner, item), (other, other_item)}
    library.get_for_user.side_effect = lambda library_item_id, user_id: (
        SimpleNamespace(video_id=video_id) if (user_id, library_item_id) in owned else None)
    videos.get_by_id.return_value = video
    transcripts.list_for_video.return_value = [
        SimpleNamespace(id=track_id, is_original=True, language_code="en", source="caption_track")]
    # Longer than the 20-segment preparation head: a region near the end must still work.
    rows = _segments(track_id, 30)
    foreign = _segments(uuid4(), 2)
    by_id = {segment.id: segment for segment in rows + foreign}
    segments.get_by_id.side_effect = lambda segment_id: by_id.get(segment_id)
    store = MemoryWorkspaces()
    service = VideoWorkspaceService(library=library, videos=videos, transcripts=transcripts,
                                    segments=segments, workspaces=store)
    verifier = Mock()
    verifier.verify.side_effect = lambda token: CurrentUser(id=other if token == "other.test.jwt" else owner)
    app.dependency_overrides[get_jwt_verifier] = lambda: verifier
    app.dependency_overrides[get_video_workspace_service] = lambda: service
    app.dependency_overrides[get_video_workspace_limiter] = lambda: SlidingWindowLimiter(
        {"position": (1000, 3600.0), "region": (1000, 3600.0)})
    try:
        yield SimpleNamespace(client=TestClient(app), url=f"/api/v1/v3/learner/me/library/videos/{item}/workspace",
                              owner=owner, item=item, video=video, transcripts=transcripts, track_id=track_id,
                              rows=rows, foreign=foreign, store=store, segments=segments, owned=owned,
                              service=service, other=other)
    finally:
        app.dependency_overrides.clear()


def _region(f, start, end):
    return {"start_segment_id": str(start.id), "end_segment_id": str(end.id)}


def test_requires_auth_and_rejects_wrong_owner_on_every_route(ws):
    f = ws
    body = _region(f, f.rows[0], f.rows[2])
    assert f.client.get(f.url).status_code == 401
    assert f.client.put(f"{f.url}/position", json={"position_ms": 1}).status_code == 401
    # Another learner sending this Library item ID is refused before any workspace or segment read.
    assert f.client.get(f.url, headers=OTHER).status_code == 404
    assert f.client.put(f"{f.url}/position", json={"position_ms": 1000}, headers=OTHER).status_code == 404
    response = f.client.put(f"{f.url}/region", json=body, headers=OTHER)
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "library_item_not_found"
    assert f.store.calls == [] and f.store.rows == {}
    f.segments.get_by_id.assert_not_called()


def test_wrong_owner_cannot_read_a_saved_workspace(ws):
    f = ws
    assert f.client.put(f"{f.url}/position", json={"position_ms": 30_000}, headers=OWNER).status_code == 200
    denied = f.client.get(f.url, headers=OTHER)
    assert denied.status_code == 404 and "30000" not in denied.text


def test_saved_position_resumes_on_the_next_read(ws):
    f = ws
    assert f.client.get(f.url, headers=OWNER).json() == {
        "library_item_id": str(f.item), "position_ms": None, "region": None, "updated_at": None}
    saved = f.client.put(f"{f.url}/position", json={"position_ms": 52_400}, headers=OWNER)
    assert saved.status_code == 200 and saved.json()["position_ms"] == 52_400
    # A later request (a reload or another device) resumes the same position.
    assert f.client.get(f.url, headers=OWNER).json()["position_ms"] == 52_400
    f.client.put(f"{f.url}/position", json={"position_ms": 60_000}, headers=OWNER)
    assert f.client.get(f.url, headers=OWNER).json()["position_ms"] == 60_000


def test_position_is_bounded_to_the_video_and_strictly_typed(ws):
    f = ws
    assert f.client.put(f"{f.url}/position", json={"position_ms": 999_000}, headers=OWNER).json()["position_ms"] == 120_000
    for bad in ({"position_ms": -1}, {"position_ms": "100"}, {"position_ms": 1.5}, {},
                {"position_ms": 1, "user_id": str(f.owner)}, {"position_ms": 86_400_001}):
        assert f.client.put(f"{f.url}/position", json=bad, headers=OWNER).status_code == 422, bad


def test_region_near_the_end_of_a_long_video_and_position_keep_each_other(ws):
    f = ws
    f.client.put(f"{f.url}/position", json={"position_ms": 10_000}, headers=OWNER)
    response = f.client.put(f"{f.url}/region", json=_region(f, f.rows[25], f.rows[28]), headers=OWNER)
    assert response.status_code == 200
    body = response.json()
    assert body["position_ms"] == 10_000
    assert body["region"] == {
        "transcript_id": str(f.track_id), "start_segment_id": str(f.rows[25].id),
        "end_segment_id": str(f.rows[28].id), "start_ms": 100_000, "end_ms": 116_000, "segment_count": 4,
            "preparation": None}
    f.client.put(f"{f.url}/position", json={"position_ms": 101_000}, headers=OWNER)
    resumed = f.client.get(f.url, headers=OWNER).json()
    assert resumed["position_ms"] == 101_000 and resumed["region"]["segment_count"] == 4
    one = f.client.put(f"{f.url}/region", json=_region(f, f.rows[3], f.rows[3]), headers=OWNER)
    assert one.json()["region"]["segment_count"] == 1


@pytest.mark.parametrize("case", ["foreign_start", "foreign_end", "unknown"])
def test_region_segments_must_belong_to_the_current_transcript(ws, case):
    f = ws
    start, end = f.rows[0], f.rows[1]
    if case == "foreign_start":
        start = f.foreign[0]
    elif case == "foreign_end":
        end = f.foreign[1]
    body = _region(f, start, end) if case != "unknown" else {
        "start_segment_id": str(uuid4()), "end_segment_id": str(end.id)}
    response = f.client.put(f"{f.url}/region", json=body, headers=OWNER)
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "region_unavailable"
    assert "region" not in f.store.calls


@pytest.mark.parametrize("case", ["reversed", "too_many_segments", "too_long"])
def test_region_order_and_size_are_server_checked(ws, case):
    f = ws
    rows = f.rows
    if case != "reversed":
        rows = _segments(f.track_id, 45, length_ms=4000 if case == "too_many_segments" else 30_000)
        f.segments.get_by_id.side_effect = lambda segment_id: {s.id: s for s in rows}.get(segment_id)
    start, end = {"reversed": (5, 4), "too_many_segments": (0, 40), "too_long": (0, 10)}[case]
    response = f.client.put(f"{f.url}/region", json=_region(f, rows[start], rows[end]), headers=OWNER)
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "region_invalid"
    assert "region" not in f.store.calls


def test_region_of_an_old_transcript_version_reads_as_none(ws):
    f = ws
    f.client.put(f"{f.url}/position", json={"position_ms": 8_000}, headers=OWNER)
    f.client.put(f"{f.url}/region", json=_region(f, f.rows[1], f.rows[2]), headers=OWNER)
    f.transcripts.list_for_video.return_value = [
        SimpleNamespace(id=uuid4(), is_original=True, language_code="en", source="caption_track")]
    resumed = f.client.get(f.url, headers=OWNER).json()
    assert resumed["region"] is None and resumed["position_ms"] == 8_000


def test_unready_video_and_store_failure_are_safe(ws):
    f = ws
    f.store.get_for_user = Mock(side_effect=RuntimeError("db password=hunter2"))
    response = f.client.get(f.url, headers=OWNER)
    assert response.status_code == 503 and "hunter2" not in response.text
    f.video.processing_status = "processing"
    assert f.client.get(f.url, headers=OWNER).status_code == 409


def test_position_saves_are_rate_limited(ws):
    f = ws
    limiter = SlidingWindowLimiter({"position": (1, 3600.0), "region": (1, 3600.0)})
    app.dependency_overrides[get_video_workspace_limiter] = lambda: limiter
    assert f.client.put(f"{f.url}/position", json={"position_ms": 1}, headers=OWNER).status_code == 200
    limited = f.client.put(f"{f.url}/position", json={"position_ms": 2}, headers=OWNER)
    assert limited.status_code == 429 and limited.json()["detail"]["code"] == "workspace_rate_limited"


class _Capture:
    def __init__(self):
        self.payloads = []

    def schema(self, _):
        return self

    def table(self, _):
        return self

    def upsert(self, payload, on_conflict):
        self.payloads.append((payload, on_conflict))
        return self

    def execute(self):
        payload = self.payloads[-1][0]
        return SimpleNamespace(data=[{**payload, "updated_at": payload["updated_at"]}])


def test_repository_sends_only_the_columns_of_each_save():
    client, item, user = _Capture(), uuid4(), uuid4()
    repository = LearnerVideoWorkspaceRepository(client)
    repository.save_position(library_item_id=item, user_id=user, position_ms=5)
    repository.save_region(library_item_id=item, user_id=user, transcript_id=uuid4(),
                           start_segment_id=uuid4(), end_segment_id=uuid4())
    position, region = (payload for payload, _ in client.payloads)
    assert set(position) == {"library_item_id", "user_id", "position_ms", "updated_at"}
    assert set(region) == {"library_item_id", "user_id", "region_transcript_id",
                           "region_start_segment_id", "region_end_segment_id", "updated_at"}
    assert {conflict for _, conflict in client.payloads} == {"library_item_id"}


def test_migration_is_owner_scoped_read_only_for_learners_and_forward_only():
    from pathlib import Path
    sql = (Path(__file__).resolve().parents[2] / "supabase" / "migrations"
           / "20261019090000_library_video_workspace_m1s1.sql").read_text(encoding="utf-8").lower()
    assert "enable row level security" in sql
    assert "revoke all privileges on v3.learner_video_workspaces from anon, authenticated" in sql
    assert "grant select on v3.learner_video_workspaces to authenticated" in sql
    assert "grant insert" not in sql and "grant update" not in sql and "grant delete" not in sql
    assert "using ((select auth.uid()) = user_id)" in sql
    assert "references v3.learner_videos (id, user_id) on delete cascade" in sql
    for destructive in ("drop table", "drop column", "truncate", "delete from"):
        assert destructive not in sql


# --- M2.2: "Tiếp tục học" ---------------------------------------------------------------------------

def _continue(f, user_id):
    """What Home's study plan reads to offer "continue learning" (no HTTP route of its own)."""
    return f.service.continue_learning(CurrentUser(id=user_id)).model_dump(mode="json")


def test_continue_learning_is_empty_before_any_workspace(ws):
    assert _continue(ws, ws.owner) == {"item": None}


def test_continue_learning_returns_the_saved_position_and_region_only_to_their_owner(ws):
    f = ws
    f.client.put(f"{f.url}/position", json={"position_ms": 52_400}, headers=OWNER)
    f.client.put(f"{f.url}/region", json=_region(f, f.rows[5], f.rows[9]), headers=OWNER)
    body = _continue(f, f.owner)["item"]
    assert body["library_item_id"] == str(f.item) and body["title"] == "Me at the zoo"
    assert body["position_ms"] == 52_400 and body["duration_ms"] == 120_000
    assert (body["region"]["start_ms"], body["region"]["end_ms"], body["region"]["segment_count"]) == (20_000, 40_000, 5)
    # Another learner never sees it.
    assert _continue(f, f.other) == {"item": None}


def test_continue_learning_skips_a_video_no_longer_in_the_library(ws):
    f = ws
    f.client.put(f"{f.url}/position", json={"position_ms": 1_000}, headers=OWNER)
    f.owned.discard((f.owner, f.item))  # removed from the Library after watching
    assert _continue(f, f.owner) == {"item": None}


def _new_transcript_version(f):
    f.transcripts.list_for_video.return_value = [
        SimpleNamespace(id=uuid4(), is_original=True, language_code="en", source="caption_track")]


def test_continue_learning_drops_a_region_of_an_older_transcript_version_but_keeps_the_position(ws):
    f = ws
    f.client.put(f"{f.url}/position", json={"position_ms": 9_000}, headers=OWNER)
    f.client.put(f"{f.url}/region", json=_region(f, f.rows[0], f.rows[2]), headers=OWNER)
    _new_transcript_version(f)
    body = _continue(f, f.owner)["item"]
    assert body["library_item_id"] == str(f.item) and body["region"] is None and body["position_ms"] == 9_000


def test_continue_learning_skips_a_workspace_left_with_only_a_stale_region(ws):
    f = ws
    older = uuid4()
    f.owned.add((f.owner, older))
    f.store.save_position(library_item_id=older, user_id=f.owner, position_ms=4_000)
    f.store.rows[older]["updated_at"] = datetime(2026, 1, 1, tzinfo=UTC)
    f.client.put(f"{f.url}/region", json=_region(f, f.rows[0], f.rows[2]), headers=OWNER)
    assert _continue(f, f.owner)["item"]["library_item_id"] == str(f.item)
    # The transcript changes: the newest workspace has nothing left to resume, so the older one is chosen.
    _new_transcript_version(f)
    body = _continue(f, f.owner)["item"]
    assert body["library_item_id"] == str(older) and body["position_ms"] == 4_000 and body["region"] is None
    # With no other workspace there is no item, never an empty one.
    f.owned.discard((f.owner, older))
    assert _continue(f, f.owner) == {"item": None}


def test_recent_workspaces_are_read_newest_first_for_one_learner():
    query, client = Mock(), Mock()
    for method in ("select", "eq", "order", "limit"):
        getattr(query, method).return_value = query
    query.execute.return_value = SimpleNamespace(data=[])
    client.schema.return_value.table.return_value = query
    user = uuid4()
    assert LearnerVideoWorkspaceRepository(client).list_recent_for_user(user_id=user, limit=5) == []
    query.eq.assert_called_once_with("user_id", str(user))
    query.order.assert_called_once_with("updated_at", desc=True)
    query.limit.assert_called_once_with(5)
