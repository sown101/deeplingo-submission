"""L1b: the word list routes. The client sends names, text and a choice among stored meanings; nothing else."""
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.bootstrap.wiring.identity import get_jwt_verifier
from app.bootstrap.wiring.learner import get_word_list_service
from app.main import app
from app.modules.identity.contracts import CurrentUser
from tests.learner.test_word_lists import OTHER, candidate, make
from tests.learner.test_word_targets import USER_ID

URL = "/api/v1/v3/learner/me/lists"


@pytest.fixture
def api():
    ctx = make()
    verifier = Mock()
    verifier.verify.side_effect = lambda token: CurrentUser(id=USER_ID)
    app.dependency_overrides[get_jwt_verifier] = lambda: verifier
    app.dependency_overrides[get_word_list_service] = lambda: ctx.service
    try:
        yield SimpleNamespace(client=TestClient(app), ctx=ctx, headers={"Authorization": "Bearer owner.test.jwt"})
    finally:
        app.dependency_overrides.clear()


def create(api, name="Travel"):
    response = api.client.post(URL, json={"language_code": "en", "name": name}, headers=api.headers)
    assert response.status_code == 200
    return response.json()["id"]


def test_every_list_route_needs_a_signed_in_learner(api):
    some, line = uuid4(), uuid4()
    calls = [
        api.client.get(URL), api.client.post(URL, json={"language_code": "en", "name": "x"}),
        api.client.get(f"{URL}/{some}"), api.client.delete(f"{URL}/{some}"),
        api.client.post(f"{URL}/{some}/import", json={"text": "airport"}),
        api.client.put(f"{URL}/{some}/lines/{line}", json={"entry_id": str(uuid4()), "sense_id": "s1"}),
        api.client.delete(f"{URL}/{some}/lines/{line}"),
        api.client.put(f"{URL}/{some}/words/{line}"), api.client.delete(f"{URL}/{some}/words/{line}"),
    ]
    assert [call.status_code for call in calls] == [401] * 9


def test_create_list_import_choose_and_delete_through_the_api(api):
    list_id = create(api)
    options = [candidate("bank", "s1", "Where money is kept."), candidate("bank", "s2", "A river side.")]
    api.ctx.resolver.table = {"airport": [candidate("airport")], "bank": options}
    report = api.client.post(f"{URL}/{list_id}/import", json={"text": "airport\nbank\nzzz"}, headers=api.headers)
    assert report.status_code == 200
    assert report.json() == {"matched": 1, "ambiguous": 1, "unresolved": 1, "already_in_list": 0, "duplicates": 0,
                             "too_long": 0, "over_limit": 0, "above_level": 0, "list_full": False}
    detail = api.client.get(f"{URL}/{list_id}", headers=api.headers).json()
    assert [word["text"] for word in detail["words"]] == ["airport"]
    assert {line["text"]: line["resolution"] for line in detail["waiting"]} == {"bank": "ambiguous", "zzz": "unresolved"}
    bank = next(line for line in detail["waiting"] if line["text"] == "bank")
    chosen = api.client.put(f"{URL}/{list_id}/lines/{bank['id']}", headers=api.headers,
                            json={"entry_id": bank["candidates"][1]["entry_id"], "sense_id": "s2"})
    assert chosen.status_code == 200 and chosen.json()["text"] == "bank"
    zzz = next(line for line in detail["waiting"] if line["text"] == "zzz")
    assert api.client.delete(f"{URL}/{list_id}/lines/{zzz['id']}", headers=api.headers).status_code == 204
    after = api.client.get(f"{URL}/{list_id}", headers=api.headers).json()
    assert (after["word_count"], after["waiting_count"]) == (2, 0)
    assert [row["name"] for row in api.client.get(f"{URL}?language_code=en", headers=api.headers).json()] == ["Travel"]
    assert api.client.delete(f"{URL}/{list_id}", headers=api.headers).status_code == 204
    assert api.client.get(f"{URL}/{list_id}", headers=api.headers).status_code == 404
    assert len(api.ctx.env.targets.rows) == 2  # the words stay


def test_the_client_can_not_name_a_concept_a_user_or_a_meaning_text(api):
    list_id = create(api)
    forged = [
        (f"{URL}/{list_id}/import", "post", {"text": "airport", "concept_id": str(uuid4())}),
        (f"{URL}/{list_id}/import", "post", {"text": "airport", "user_id": str(uuid4())}),
        (f"{URL}/{list_id}/lines/{uuid4()}", "put", {"entry_id": str(uuid4()), "sense_id": "s1", "meaning": "free text"}),
        (URL, "post", {"language_code": "en", "name": "x", "user_id": str(uuid4())}),
    ]
    for path, method, body in forged:
        assert getattr(api.client, method)(path, json=body, headers=api.headers).status_code == 422


def test_an_unknown_language_name_or_other_learners_list_is_refused_with_a_code(api):
    assert api.client.post(URL, json={"language_code": "fr", "name": "x"}, headers=api.headers).json()["detail"][
        "code"] == "language_not_learned"
    create(api)
    taken = api.client.post(URL, json={"language_code": "en", "name": "TRAVEL"}, headers=api.headers)
    assert taken.status_code == 409 and taken.json()["detail"]["code"] == "list_name_taken"
    theirs = api.ctx.groups.create(OTHER.id, language_code="en", name="Theirs", description=None)["id"]
    for call in (api.client.get(f"{URL}/{theirs}", headers=api.headers),
                 api.client.post(f"{URL}/{theirs}/import", json={"text": "airport"}, headers=api.headers)):
        assert call.status_code == 404 and call.json()["detail"]["code"] == "list_not_found"
    assert api.client.post(f"{URL}/{theirs}/import", json={"text": ""}, headers=api.headers).status_code == 422
