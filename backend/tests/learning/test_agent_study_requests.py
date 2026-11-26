"""What Tata asked the learner to practise again, listed in the agent screen with a readable title (PRD 8.10).
Fakes only: no database, no model."""
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.bootstrap.wiring.agent import LearnerFacts, get_learner_facts
from app.bootstrap.wiring.identity import get_jwt_verifier
from app.main import app
from app.modules.identity.contracts import CurrentUser
from tests.activity.test_activity_service import ANNA, POINT, WORD, FakeConcepts, make_activity

URL = "/api/v1/v3/learner/me/agent/study-requests"


def make_facts(activity):
    return LearnerFacts(activity=activity, decks=SimpleNamespace(deck_counts=lambda user: []),
                        concepts=FakeConcepts({WORD: "en"}), brief=lambda *_: "",
                        grammar_points=lambda language, support: {POINT} if language == "en" else set(),
                        grammar_menu=lambda *_: None,
                        grammar_titles=lambda language, support: {POINT: f"Past tense ({support})"})


def test_open_requests_carry_the_word_or_the_grammar_title():
    activity, *_ = make_activity()
    activity.create_study_request(ANNA, language_code="en", kind="grammar_redo", item_id=POINT, reason="was/were",
                                  created_by="agent")
    activity.create_study_request(ANNA, language_code="en", kind="word_review", item_id=WORD, reason=None,
                                  created_by="agent")
    activity.create_study_request(ANNA, language_code="zh", kind="word_review", item_id=str(uuid4()), reason=None,
                                  created_by="agent")
    rows = make_facts(activity).open_requests(ANNA, "en", "vi")
    assert sorted((row["kind"], row["title"], row["reason"]) for row in rows) == [
        ("grammar_redo", "Past tense (vi)", "was/were"), ("word_review", f"word-{WORD[:4]}", None)]
    assert set(rows[0]) == {"id", "kind", "title", "reason", "created_at"}  # the other language is not there


def test_a_request_whose_item_is_gone_keeps_a_neutral_title():
    activity, *_ = make_activity()
    activity.create_study_request(ANNA, language_code="en", kind="word_review", item_id=str(uuid4()), reason=None,
                                  created_by="agent")
    assert make_facts(activity).open_requests(ANNA, "en", "vi")[0]["title"] is None


@pytest.fixture
def api():
    activity, *_ = make_activity()
    verifier = Mock()
    verifier.verify.side_effect = lambda token: CurrentUser(id=ANNA)
    app.dependency_overrides[get_jwt_verifier] = lambda: verifier
    app.dependency_overrides[get_learner_facts] = lambda: make_facts(activity)
    try:
        yield SimpleNamespace(client=TestClient(app), activity=activity,
                              headers={"Authorization": "Bearer anna.test.jwt"})
    finally:
        app.dependency_overrides.clear()


def test_the_route_lists_the_signed_in_learners_open_requests_in_one_language(api):
    asked, _ = api.activity.create_study_request(ANNA, language_code="en", kind="grammar_redo", item_id=POINT,
                                                 reason=None, created_by="agent")
    response = api.client.get(f"{URL}?language=en&support=vi", headers=api.headers)
    assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
    assert response.json() == {"items": [{"id": str(asked.id), "kind": "grammar_redo", "title": "Past tense (vi)",
                                          "reason": None, "created_at": response.json()["items"][0]["created_at"]}]}
    assert api.client.get(f"{URL}?language=nonsense!", headers=api.headers).status_code == 422
    assert TestClient(app).get(f"{URL}?language=en").status_code == 401
