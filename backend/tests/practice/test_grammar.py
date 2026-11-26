"""Grammar in the notebook: lessons and exercises from approved banks, graded on the server, no FSRS; the "redo"
list is the agent's grammar_redo requests, closed by a correct answer. The old Flutter endpoints keep their shapes."""
import copy
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.bootstrap.wiring.practice import get_grammar_service
from app.main import app
from app.modules.content.domain.grammar_bank import GrammarBank
from app.modules.content.infrastructure.grammar_banks import GrammarBanks
from app.modules.identity.api.dependencies import require_authenticated_user
from app.modules.identity.contracts import CurrentUser
from app.modules.practice.application.review import PracticeError
from app.modules.practice.infrastructure.data_export import PracticeDataSection
from tests.content.test_grammar_bank import approved, draft, lesson
from tests.learner.test_data_export import FakeClient
from tests.practice.fakes import USER, make_grammar

PREFIX = "/api/v1/v3"


def taught_bank() -> GrammarBank:
    value = copy.deepcopy(approved())
    value["points"][0]["lesson"] = lesson()
    value["approval"]["content_sha256"] = GrammarBank.model_validate({**value, "approval": None}).content_hash()
    return GrammarBank.model_validate(value)


@pytest.fixture
def env():
    bank = taught_bank()
    made = make_grammar([bank])
    made.bank = bank
    made.point = bank.points[0]
    made.question = bank.points[0].questions[0]
    return made


def answer(env, option="a", event=None, question=None):
    return env.service.answer(USER, "en", exercise_id=(question or env.question).id, option_id=option,
                              client_event_id=event or str(uuid4()))


def test_overview_has_lessons_and_results_but_no_answer_key(env):
    view = env.service.overview(USER, "en")
    assert view["levels"] == ["A1"] and view["points"][0]["lesson"]["summary"] == "Synthetic summary."
    assert view["points"][0]["attempts"] == 0 and view["redo"] == []
    exercises = env.service.exercises(USER, "en", grammar_key=env.point.key)["exercises"]
    assert len(exercises) == 2 and set(exercises[0]) == {"id", "grammar_key", "type", "prompt", "options"}
    assert "correct_option_id" not in str(view) + str(exercises) and "explanation" not in str(exercises)


def test_an_answer_is_graded_on_the_server_kept_per_point_and_logged_once(env):
    event = str(uuid4())
    first = answer(env, "a", event)
    again = answer(env, "a", event)
    assert first["correct"] is True and again["duplicate"] is True
    assert first["correct_option_id"] == env.question.correct_option_id and first["explanation"]
    rows = env.log.of("grammar_exercise")
    assert len(rows) == 1 and (rows[0].item_type, rows[0].item_id) == ("grammar_point", env.point.key)
    answer(env, "b")
    point = env.service.overview(USER, "en")["points"][0]
    assert (point["attempts"], point["correct_count"], point["incorrect_count"]) == (2, 1, 1)
    with pytest.raises(PracticeError) as conflict:
        answer(env, "b", event)
    assert conflict.value.code == "grammar_answer_conflict"


def test_a_grammar_redo_request_shows_in_the_redo_list_and_closes_on_a_correct_answer(env):
    env.activity.create_study_request(USER, language_code="en", kind="grammar_redo", item_id=env.point.key,
                                      reason="Nói sai thì", created_by="agent")
    redo = env.service.overview(USER, "en")["redo"]
    assert [(item["grammar_key"], item["title"], item["reason"]) for item in redo] == [
        (env.point.key, env.point.title, "Nói sai thì")]
    assert answer(env, "b")["redo_closed"] == 0
    assert env.requests.rows[0].status == "open"
    assert answer(env, "a")["redo_closed"] == 1
    assert env.requests.rows[0].status == "done" and env.service.overview(USER, "en")["redo"] == []


def test_learning_a_lesson_is_kept_once(env):
    first = env.service.lesson_learned(USER, "en", grammar_key=env.point.key, client_event_id="l1")
    again = env.service.lesson_learned(USER, "en", grammar_key=env.point.key, client_event_id="l1")
    assert first["lesson_learned_at"] == again["lesson_learned_at"] is not None
    assert len(env.log.of("grammar_lesson")) == 1
    with pytest.raises(PracticeError):
        env.service.lesson_learned(USER, "en", grammar_key="en.a1.unknown_point", client_event_id="l2")


def test_bad_selectors_write_nothing(env):
    with pytest.raises(PracticeError):
        env.service.answer(USER, "en", exercise_id="en.a1.unknown.1", option_id="a", client_event_id="x")
    with pytest.raises(PracticeError):
        answer(env, "zz")
    assert env.log.entries == [] and env.progress.rows == {}


def test_banks_are_per_language_and_unapproved_or_mismatched_banks_fail_closed(env):
    assert env.service.overview(USER, "zh")["levels"] == []
    env.service.banks.for_language = lambda *args: [GrammarBank.model_validate(draft())]
    with pytest.raises(ValueError, match="approval"):
        env.service.overview(USER, "en")
    env.service.banks.for_language = lambda *args: [env.bank]
    with pytest.raises(PracticeError):
        env.service.overview(USER, "zh")


def test_routes_auth_and_strict_bodies(env):
    user = CurrentUser(id=USER)
    app.dependency_overrides[get_grammar_service] = lambda: env.service
    try:
        client = TestClient(app)
        assert client.get(f"{PREFIX}/learner/me/grammar/en").status_code == 401
        app.dependency_overrides[require_authenticated_user] = lambda: user
        new = {"language_code": "en", "exercise_id": env.question.id, "option_id": "a", "client_event_id": "e-1"}
        assert client.post(f"{PREFIX}/learner/me/grammar/answers", json={**new, "correct": True}).status_code == 422
        assert client.post(f"{PREFIX}/learner/me/grammar/answers", json=new).json()["correct"] is True
        assert client.get(f"{PREFIX}/learner/me/grammar/en").json()["points"][0]["attempts"] == 1
        assert client.get(f"{PREFIX}/learner/me/grammar/en/exercises?level=A1").status_code == 200
        assert client.post(f"{PREFIX}/learner/me/grammar/lessons", json={
            "language_code": "en", "grammar_key": env.point.key, "client_event_id": "l-1"}).status_code == 200
    finally:
        app.dependency_overrides.pop(get_grammar_service, None)
        app.dependency_overrides.pop(require_authenticated_user, None)


# --- Banks on disk and the export ------------------------------------------------------------------------------

def test_owner_approved_banks_are_served_and_unsupported_languages_do_not_become_paths():
    banks = GrammarBanks()
    assert [bank.level for bank in banks.for_language("en", "vi")] == ["A1", "A2", "B1", "B2", "C1", "C2"]
    assert [bank.level for bank in banks.for_language("zh", "vi")] == [f"HSK{n}" for n in range(1, 7)]
    assert banks.for_language("zh", "en") == []
    assert banks.for_language("../../", "vi") == []


def test_filesystem_adapter_refuses_unapproved_banks(tmp_path):
    (tmp_path / "en").mkdir()
    (tmp_path / "en/a1.json").write_text(json.dumps(draft()), encoding="utf-8")
    assert GrammarBanks(tmp_path).for_language("en", "vi") == []


def test_export_holds_only_the_owners_grammar_progress():
    user, other = str(uuid4()), str(uuid4())
    db = FakeClient({"learner_grammar_progress": [{"user_id": owner, "grammar_key": owner} for owner in [user, other]]})
    rows = PracticeDataSection(db).export(user)["grammar_progress"]
    assert [row["grammar_key"] for row in rows] == [user]
    assert SimpleNamespace  # used by fakes
