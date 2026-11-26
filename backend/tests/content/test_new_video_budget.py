"""O12: importing a video that still needs AI work spends a per-learner budget."""
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.bootstrap.wiring.content import get_learner_library_service, get_library_import_limiter
from app.modules.content.api.library import router
from app.modules.content.application.library import (
    ImportBudgetDecision,
    LearnerLibraryError,
)
from app.modules.content.infrastructure.repositories.new_video_import_budget import NewVideoImportBudgetRepository
from app.modules.identity.api.dependencies import require_authenticated_user
from app.modules.identity.contracts import CurrentUser
from app.platform.rate_limit import SlidingWindowLimiter
from tests.content.test_library import USER_A, USER_B, make_service, user


class Ledger:
    """Python model of v3.charge_new_video_import (the real function is checked on the dev database)."""

    def __init__(self, limit):
        self.limit, self.rows, self.calls = limit, {}, []

    def charge(self, *, user_id, video_id):
        self.calls.append((user_id, video_id))
        used = sum(1 for key in self.rows if key[0] == user_id)
        if (user_id, video_id) in self.rows:
            return ImportBudgetDecision(True, False, used, self.limit, None)
        if used >= self.limit:
            return ImportBudgetDecision(False, False, used, self.limit, datetime.now(UTC) + timedelta(hours=3))
        self.rows[(user_id, video_id)] = True
        return ImportBudgetDecision(True, True, used + 1, self.limit, None)


def with_ledger(limit):
    service, videos, library, transcripts, dispatcher = make_service()
    service.import_budget = Ledger(limit)
    return service, videos, dispatcher


def url(number):
    return f"https://youtube.com/watch?v=shared{number}"


def test_a_learner_is_refused_past_the_limit_and_nothing_is_admitted_or_dispatched():
    service, videos, dispatcher = with_ledger(1)
    # make_service's FakeIngestion only knows "shared123"; this one accepts any video.
    service.ingestion.prepare_video = lambda link: (_video(videos, link), True)
    service.import_video(user(USER_A), url(1))
    dispatched = list(dispatcher.video_ids)

    with pytest.raises(LearnerLibraryError) as error:
        service.import_video(user(USER_A), url(2))

    assert (error.value.status_code, error.value.code) == (429, "new_video_budget_exhausted")
    assert error.value.retry_after_seconds and error.value.retry_after_seconds > 3 * 3600 - 5
    assert dispatcher.video_ids == dispatched  # the refused import started no AI work


def _video(videos, link):
    existing = next((item for item in videos.by_id.values() if item.external_video_id == link[-7:]), None)
    if existing:
        return existing
    video = videos.create(link[-7:])
    videos.by_id[video.id] = video
    return video


def test_importing_the_same_video_again_is_free():
    service, videos, dispatcher = with_ledger(1)
    first = service.import_video(user(USER_A), "https://youtube.com/watch?v=shared123")
    again = service.import_video(user(USER_A), "https://youtu.be/shared123")
    assert first.item.video_id == again.item.video_id
    assert again.command_status == "reused"


def test_one_learner_using_the_budget_does_not_block_another():
    service, _, _ = with_ledger(1)
    service.import_video(user(USER_A), "https://youtube.com/watch?v=shared123")
    other = service.import_video(user(USER_B), "https://youtu.be/shared123")
    assert other.item.video_id  # B pays for the same video with B's own budget


def test_a_prepared_video_costs_nothing_and_never_touches_the_ledger():
    service, videos, _ = with_ledger(1)
    ledger = service.import_budget
    first = service.import_video(user(USER_A), "https://youtube.com/watch?v=shared123")
    videos.by_id[first.item.video_id] = videos.by_id[first.item.video_id].model_copy(
        update={"learning_status": "ready"})
    ledger.rows.clear()
    ledger.calls.clear()

    service.import_video(user(USER_B), "https://youtu.be/shared123")

    assert ledger.calls == [] and ledger.rows == {}


def test_a_failing_ledger_fails_closed_instead_of_admitting_free_work():
    service, _, dispatcher = with_ledger(5)
    service.import_budget = Mock(charge=Mock(side_effect=RuntimeError("database down")))
    with pytest.raises(RuntimeError):
        service.import_video(user(USER_A), "https://youtube.com/watch?v=shared123")
    assert dispatcher.video_ids == []


def test_repository_calls_the_atomic_function_with_the_configured_policy():
    calls = []

    class Client:
        def schema(self, name):
            return self

        def rpc(self, name, payload):
            calls.append((name, payload))
            return SimpleNamespace(execute=lambda: SimpleNamespace(data={
                "allowed": False, "charged": False, "used": 5, "limit": 5,
                "reset_at": "2026-10-17T03:00:00+00:00"}))

    repository = NewVideoImportBudgetRepository(Client(), limit=5, window_seconds=86400)
    decision = repository.charge(user_id=USER_A, video_id=USER_B)

    assert calls[0][0] == "charge_new_video_import"
    assert calls[0][1] == {"p_user_id": str(USER_A), "p_video_id": str(USER_B), "p_limit": 5,
                           "p_window_seconds": 86400}
    assert decision.allowed is False and decision.reset_at.tzinfo is not None


def test_the_route_answers_429_with_retry_after_and_rate_limits_import_requests():
    app = FastAPI()
    app.include_router(router)
    service = Mock()
    service.import_video.side_effect = LearnerLibraryError(
        "limit", status_code=429, code="new_video_budget_exhausted", retry_after_seconds=7200)
    limiter = SlidingWindowLimiter({"import": (2, 3600.0)})
    app.dependency_overrides[get_learner_library_service] = lambda: service
    app.dependency_overrides[get_library_import_limiter] = lambda: limiter
    app.dependency_overrides[require_authenticated_user] = lambda: CurrentUser(
        id=USER_A, role="authenticated", claims={"app_metadata": {}})
    client = TestClient(app)

    refused = client.post("/learner/me/library/videos", json={"url": "https://youtube.com/watch?v=abcdefghijk"})
    assert refused.status_code == 429 and refused.headers["Retry-After"] == "7200"
    assert refused.json()["detail"]["code"] == "new_video_budget_exhausted"

    client.post("/learner/me/library/videos", json={"url": "https://youtube.com/watch?v=abcdefghijk"})
    limited = client.post("/learner/me/library/videos", json={"url": "https://youtube.com/watch?v=abcdefghijk"})
    assert limited.status_code == 429 and limited.json()["detail"]["code"] == "import_rate_limited"
    assert service.import_video.call_count == 2  # the third request never reached the service
