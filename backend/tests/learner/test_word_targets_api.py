"""L1a: My words with target status, immediate eligibility and the level warning, through the HTTP API."""
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.bootstrap.wiring.identity import get_jwt_verifier
from app.bootstrap.wiring.learner import get_my_words_service
from app.main import app
from app.modules.identity.contracts import CurrentUser
from app.modules.learner.application.my_words import MyWordsService
from tests.learner.test_word_targets import USER_ID, build, concept

URL = "/api/v1/v3/learner/me/words"
ITEM = uuid4()


def occurrence_body(**extra):
    return {"source": "occurrence", "library_item_id": str(ITEM), "learning_object_id": str(uuid4()), **extra}


@pytest.fixture
def api():
    env = build(declared="A2")
    resolved = {"concept": concept("rely on", level="A2")}
    resolver = Mock()
    resolver.from_occurrence.side_effect = lambda *a, **k: resolved["concept"]
    words = MyWordsService(
        saved=env.targets, resolver=resolver,
        concepts=SimpleNamespace(list_by_ids=lambda ids: [resolved["concept"]] if resolved["concept"].id in ids else []),
        reviews=SimpleNamespace(next_due_by_concept=lambda **_: {}),
        preferences=SimpleNamespace(get_by_language_for_user=lambda **kw: object()),
        targets=env.service,
    )
    verifier = Mock()
    verifier.verify.side_effect = lambda token: CurrentUser(id=USER_ID)
    app.dependency_overrides[get_jwt_verifier] = lambda: verifier
    app.dependency_overrides[get_my_words_service] = lambda: words
    try:
        yield SimpleNamespace(client=TestClient(app), env=env, resolved=resolved,
                              headers={"Authorization": "Bearer owner.test.jwt"})
    finally:
        app.dependency_overrides.clear()


def test_a_saved_word_starts_active_and_lists_with_its_target_fields(api):
    saved = api.client.post(URL, json=occurrence_body(), headers=api.headers)
    assert saved.status_code == 200
    body = saved.json()
    assert (body["status"], body["saved"], body["explicit"], body["rung"], body["priority"], body["above_level"],
            body["level_label"]) == ("active", True, True, 0, 100, False, "A2")
    listed = api.client.get(f"{URL}?language_code=en", headers=api.headers).json()
    assert [row["status"] for row in listed["words"]] == ["active"]
    assert listed["summary"]["backlog"] == 0 and listed["summary"]["active"] == 1 and listed["summary"]["daily_new_limit"] == 10
    assert listed["summary"]["declared_level"] == "A2"


def test_a_word_above_the_learners_level_asks_once_then_is_added_and_flagged(api):
    api.resolved["concept"] = concept("ubiquitous", level="C1")
    first = api.client.post(URL, json=occurrence_body(), headers=api.headers)
    assert first.status_code == 409
    assert first.json()["detail"] == {"code": "above_level", "message": "This word is above your level.",
                                      "level": "C1", "declared_level": "A2"}
    second = api.client.post(URL, json=occurrence_body(acknowledge_above_level=True), headers=api.headers)
    assert second.status_code == 200 and second.json()["above_level"] is True
    assert api.client.post(URL, json=occurrence_body(), headers=api.headers).status_code == 200  # already a target


@pytest.mark.parametrize("forged", [{"status": "active"}, {"priority": 1000}, {"rung": 5}, {"explicit": False}])
def test_clients_cannot_choose_status_priority_or_rung_when_saving(api, forged):
    response = api.client.post(URL, json=occurrence_body(**forged), headers=api.headers)
    assert response.status_code == 422 and not api.env.targets.rows


def test_the_learner_can_activate_pause_and_return_a_word(api):
    api.client.post(URL, json=occurrence_body(), headers=api.headers)
    concept_id = api.resolved["concept"].id
    for status in ("active", "suspended", "backlog"):
        response = api.client.put(f"{URL}/{concept_id}/status", json={"status": status}, headers=api.headers)
        assert response.status_code == 200 and response.json()["status"] == ("active" if status == "backlog" else status)
    assert api.client.put(f"{URL}/{concept_id}/status", json={"status": "known"}, headers=api.headers).status_code == 422
    assert api.client.put(f"{URL}/{concept_id}/status", json={"status": "active", "x": 1},
                          headers=api.headers).status_code == 422


def test_unlisted_words_refuse_status_changes(api):
    api.client.post(URL, json=occurrence_body(), headers=api.headers)
    concept_id = api.resolved["concept"].id
    missing = api.client.put(f"{URL}/{uuid4()}/status", json={"status": "active"}, headers=api.headers)
    assert missing.status_code == 404


def test_the_daily_activation_route_is_removed(api):
    assert api.client.post(f"{URL}/activate-today?language_code=en", headers=api.headers).status_code == 405
    paths = app.openapi()["paths"]
    assert "/api/v1/v3/learner/me/words/activate-today" not in paths


def test_legacy_backlog_is_reported_as_active_without_rewriting_storage(api):
    api.client.post(URL, json=occurrence_body(), headers=api.headers)
    row = api.env.targets.rows[api.resolved["concept"].id]
    row["status"], row["activated_at"] = "backlog", None
    listed = api.client.get(f"{URL}?language_code=en", headers=api.headers).json()
    assert listed["words"][0]["status"] == "active"
    assert listed["summary"]["backlog"] == 0 and listed["summary"]["active"] == 1
    assert row["status"] == "backlog" and row["activated_at"] is None


def test_the_new_routes_need_a_signed_in_learner(api):
    concept_id = uuid4()
    assert api.client.put(f"{URL}/{concept_id}/status", json={"status": "active"}).status_code == 401
