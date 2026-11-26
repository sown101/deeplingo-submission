"""Real HTTP/composition gates, injected persistence only; never live DB/Auth/AI."""
import ast
import importlib
import importlib.util
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.bootstrap.wiring.identity import get_jwt_verifier
from app.bootstrap.wiring.content import get_learner_library_service
from app.bootstrap.wiring.learner import get_learner_model_service
from app.main import app
from tests.content.test_library import FakeVerifier, USER_A, USER_B, make_service, user


ROOT = Path(__file__).resolve().parents[2]
AUTH = {"Authorization": "Bearer a.b.c"}
LEGACY = "/api/v1"
# Exact old paths/methods: include both Library slash variants and GET side effects.
RETIRED = [
    ("POST", "/library/add"), ("GET", "/library"), ("GET", "/library/"),
    ("GET", "/library/favorites"), ("PUT", "/library/{video_id}"),
    ("POST", "/library/{video_id}/progress"),
    ("POST", "/library/{video_id}/favorite"), ("DELETE", "/library/{video_id}"),
    ("GET", "/vocabulary/groups"), ("POST", "/vocabulary/groups"),
    ("PATCH", "/vocabulary/groups/{group_id}"), ("DELETE", "/vocabulary/groups/{group_id}"),
    ("GET", "/vocabulary/groups/smart"), ("GET", "/vocabulary/saved"),
    ("POST", "/vocabulary/saved"), ("DELETE", "/vocabulary/saved/{saved_word_id}"),
    ("POST", "/vocabulary/saved/{saved_word_id}/groups/{group_id}"),
    ("DELETE", "/vocabulary/saved/{saved_word_id}/groups/{group_id}"),
    ("GET", "/vocabulary/flashcards/due"), ("POST", "/vocabulary/flashcards/rate"),
    ("GET", "/dictionary/lookup"), ("GET", "/dictionary/ai-enrich"),
    ("POST", "/dictionary/ai-chat"), ("POST", "/shadowing/score"),
    ("POST", "/videos/import"), ("POST", "/videos/{video_id}/retry"),
    ("DELETE", "/videos/{video_id}"), ("POST", "/channels/add"),
    ("POST", "/channels/{channel_id}/sync"), ("DELETE", "/channels/{channel_id}"),
    ("POST", "/subtitles/{subtitle_id}/explain"),
    ("POST", "/subtitles/{subtitle_id}/update-analysis"),
]


@pytest.fixture(autouse=True)
def reset_overrides():
    previous = dict(app.dependency_overrides)
    app.dependency_overrides.clear()
    yield
    app.dependency_overrides.clear()
    app.dependency_overrides.update(previous)


def mounted():
    return {(method, route.path) for route in app.routes for method in getattr(route, "methods", [])}


def test_unsafe_routes_are_not_mounted_or_in_openapi():
    unsafe = {(method, LEGACY + path) for method, path in RETIRED}
    assert not (unsafe & mounted())
    schema = app.openapi()
    assert not any(method.lower() in schema["paths"].get(path, {}) for method, path in unsafe)


@pytest.mark.parametrize("method,path", RETIRED)
@pytest.mark.parametrize("authenticated", [False, True])
def test_retired_routes_fail_closed_even_with_identity_rating_and_correctness(method, path, authenticated):
    # Fail before HTTP if a regression remounts a handler: no accidental live I/O.
    assert (method, LEGACY + path) not in mounted()
    app.dependency_overrides[get_jwt_verifier] = lambda: FakeVerifier(USER_A)
    concrete = path
    for field in ("video_id", "group_id", "saved_word_id", "channel_id", "subtitle_id"):
        concrete = concrete.replace("{" + field + "}", str(USER_B))
    response = TestClient(app).request(
        method, LEGACY + concrete, headers=AUTH if authenticated else {},
        params={"user_id": str(USER_B), "word": "word", "language": "en", "rating": 4},
        json={"user_id": str(USER_B), "video_id": str(USER_B), "flashcard_id": str(USER_B),
              "rating": 4, "is_correct": True, "correct": True, "due_at": "2099-01-01"},
    )
    assert response.status_code == 404
    assert response.json() == {"detail": "Not Found"}


def test_legacy_feature_packages_are_deleted():
    # Legacy features/* and the non-V3 content GET compatibility routes are removed.
    assert importlib.util.find_spec("app.features") is None
    assert not (ROOT / "app" / "features").exists()


def test_only_v3_and_process_routes_are_mounted():
    allowed_prefixes = (LEGACY + "/v3/", "/docs", "/redoc", "/openapi.json")
    for method, path in mounted():
        assert path in {"/", "/health"} or path.startswith(allowed_prefixes), (method, path)


def test_fsrs_math_has_one_production_sdk_boundary():
    users = []
    for source in (ROOT / "app").rglob("*.py"):
        tree = ast.parse(source.read_text(encoding="utf-8-sig"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] == "fsrs":
                users.append(source.relative_to(ROOT).as_posix())
            elif isinstance(node, ast.Import) and any(alias.name.split(".")[0] == "fsrs" for alias in node.names):
                users.append(source.relative_to(ROOT).as_posix())
    assert set(users) == {"app/modules/review/infrastructure/fsrs_adapter.py"}


def test_active_v3_library_mutation_requires_auth_and_rejects_body_identity():
    service, _, library, _, _ = make_service()
    app.dependency_overrides[get_learner_library_service] = lambda: service
    app.dependency_overrides[get_jwt_verifier] = lambda: FakeVerifier(USER_A)
    client = TestClient(app)
    path = "/api/v1/v3/learner/me/library/videos"
    assert client.post(path, json={"url": "https://youtu.be/shared123"}).status_code == 401
    assert client.post(path, headers=AUTH, json={"url": "https://youtu.be/shared123", "user_id": str(USER_B)}).status_code == 422
    own = client.post(path, headers=AUTH, json={"url": "https://youtu.be/shared123"})
    assert own.status_code == 202
    item_id = own.json()["item"]["library_item_id"]
    from uuid import UUID
    assert library.get_for_user(library_item_id=UUID(item_id), user_id=USER_A) is not None
    assert library.get_for_user(library_item_id=UUID(item_id), user_id=USER_B) is None


def test_cross_user_library_retry_cannot_mutate_resource_but_owner_can_retry():
    service, videos, _, _, dispatcher = make_service()
    item = service.import_video(user(USER_B), "https://youtu.be/shared123").item
    videos.by_id[item.video_id] = videos.by_id[item.video_id].model_copy(update={
        "processing_status": "failed", "processing_retryable": True,
    })
    app.dependency_overrides[get_learner_library_service] = lambda: service
    app.dependency_overrides[get_jwt_verifier] = lambda: FakeVerifier(USER_A)
    client = TestClient(app)
    path = f"/api/v1/v3/learner/me/library/videos/{item.library_item_id}/retry"
    before = len(dispatcher.video_ids)
    assert client.post(path, headers=AUTH).status_code == 404
    assert len(dispatcher.video_ids) == before
    assert videos.by_id[item.video_id].processing_status == "failed"
    app.dependency_overrides[get_jwt_verifier] = lambda: FakeVerifier(USER_B)
    assert client.post(path, headers=AUTH).status_code == 202
    assert len(dispatcher.video_ids) == before + 1


SELF_ROUTES = [("GET", "/learner/me/language-profile"), ("PUT", "/learner/me/language-profile")]


@pytest.mark.parametrize("method,path", SELF_ROUTES)
@pytest.mark.parametrize("query", [f"user_id={USER_A}", f"user_id={USER_B}", "user_id=", f"user_id={USER_A}&user_id={USER_B}"])
def test_retired_v3_identity_query_is_rejected_before_service_even_if_matching(method, path, query):
    def forbidden_service():
        pytest.fail("Rejected identity must not reach persistence")
    app.dependency_overrides[get_jwt_verifier] = lambda: FakeVerifier(USER_A)
    app.dependency_overrides[get_learner_model_service] = forbidden_service
    response = TestClient(app).request(method, "/api/v1/v3" + path + "?" + query,
        headers=AUTH, json={"learning_language": "en", "support_language": "vi"})
    assert response.status_code == 422
    assert "identity comes from authentication" in response.json()["detail"]


@pytest.mark.parametrize("method,path", SELF_ROUTES)
def test_self_identity_query_does_not_bypass_auth(method, path):
    response = TestClient(app).request(method, "/api/v1/v3" + path + f"?user_id={USER_A}",
        json={"learning_language": "en", "support_language": "vi"})
    assert response.status_code == 401


def test_retired_identity_fields_are_absent_from_active_openapi_contracts():
    schema = app.openapi()
    for method, path in SELF_ROUTES:
        operation = schema["paths"]["/api/v1/v3" + path][method.lower()]
        assert not any(p["name"] == "user_id" for p in operation.get("parameters", []))
