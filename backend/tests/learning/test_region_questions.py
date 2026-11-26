"""M1 S6: learners answer region questions; the server checks them and writes the learning log only."""
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.bootstrap.wiring.identity import get_jwt_verifier
from app.bootstrap.wiring.speaking import _RegionQuestions, get_practice_log_limiter, get_region_question_service
from app.main import app
from app.modules.content.application.library import LearnerLibraryError
from app.modules.content.application.workspace import CurrentRegionQuestions
from app.modules.content.domain.region_questions import RegionQuestion
from app.modules.identity.contracts import CurrentUser
from app.modules.learning.application.practice_log import PracticeLogError
from app.modules.learning.application.region_questions import (
    CurrentRegionQuestionSet,
    RegionQuestionAnswerRequest,
    RegionQuestionItem,
    RegionQuestionService,
)
from app.modules.learning.application.agent.context import practice_line
from app.platform.rate_limit import SlidingWindowLimiter
from tests.activity.fakes import make_activity

OWNER, ITEM, TRACK, SEGMENT = uuid4(), uuid4(), uuid4(), uuid4()
USER = SimpleNamespace(id=OWNER)
QUESTION = RegionQuestionItem(id=uuid4(), position=1, question="Người nói đi bằng gì?",
                              options=("Taxi", "Xe buýt", "Tàu", "Xe đạp"), correct_index=0,
                              evidence_segment_id=SEGMENT, evidence_quote="taking a taxi", explanation="Câu s1.")


class Reader:
    def __init__(self, current=None):
        self.current_set = current or CurrentRegionQuestionSet(status="ready", transcript_id=TRACK,
                                                               questions=(QUESTION,))

    def current(self, user, library_item_id):
        if (user.id, library_item_id) != (OWNER, ITEM):
            raise PracticeLogError(404, "library_item_not_found", "Library item not found.")
        return self.current_set


def make(current=None):
    activity, log, _, _ = make_activity()
    transcripts = SimpleNamespace(get_by_id=lambda transcript_id: SimpleNamespace(language_code="en"))
    service = RegionQuestionService(questions=Reader(current), transcripts=transcripts, learning_log=activity)
    return service, log


def test_questions_are_listed_without_their_answer_key():
    service, _ = make()
    view = service.list(USER, ITEM)
    assert view.status == "ready" and view.questions[0].options == ["Taxi", "Xe buýt", "Tàu", "Xe đạp"]
    dumped = view.model_dump_json()
    assert "correct" not in dumped and "taking a taxi" not in dumped and "Câu s1." not in dumped


def test_the_server_checks_the_answer_and_logs_a_practice_fact_only():
    service, log = make()
    wrong = service.answer(USER, ITEM, QUESTION.id, RegionQuestionAnswerRequest(id=uuid4(), selected_option=2))
    assert not wrong.correct and wrong.correct_index == 0 and wrong.evidence_quote == "taking a taxi"
    right = service.answer(USER, ITEM, QUESTION.id, RegionQuestionAnswerRequest(id=uuid4(), selected_option=0))
    assert right.correct and right.status == "created"
    row = next(entry for entry in log.of("region_question") if entry.client_event_id == f"region_question:{right.id}")
    assert (row.outcome, row.item_type, row.item_id, row.language_code) == ("correct", "segment", str(SEGMENT), "en")
    assert row.detail == {"question_id": str(QUESTION.id)}


def test_a_retried_answer_is_logged_once():
    service, log = make()
    event_id = uuid4()
    first = service.answer(USER, ITEM, QUESTION.id, RegionQuestionAnswerRequest(id=event_id, selected_option=1))
    again = service.answer(USER, ITEM, QUESTION.id, RegionQuestionAnswerRequest(id=event_id, selected_option=1))
    assert (first.status, again.status) == ("created", "reused") and len(log.of("region_question")) == 1
    assert (first.correct, again.correct) == (False, False)  # checked again, the same answer


def test_unknown_foreign_or_unavailable_questions_are_refused():
    service, log = make()
    with pytest.raises(PracticeLogError) as error:
        service.answer(USER, ITEM, uuid4(), RegionQuestionAnswerRequest(id=uuid4(), selected_option=0))
    assert error.value.status_code == 404 and error.value.code == "question_not_found"
    with pytest.raises(PracticeLogError) as error:
        service.answer(SimpleNamespace(id=uuid4()), ITEM, QUESTION.id,
                       RegionQuestionAnswerRequest(id=uuid4(), selected_option=0))
    assert error.value.code == "library_item_not_found"
    preparing, _ = make(CurrentRegionQuestionSet(status="preparing", transcript_id=TRACK))
    with pytest.raises(PracticeLogError) as error:
        preparing.answer(USER, ITEM, QUESTION.id, RegionQuestionAnswerRequest(id=uuid4(), selected_option=0))
    assert error.value.code == "questions_unavailable"
    assert log.entries == []


@pytest.mark.parametrize("body", [
    {"id": str(uuid4()), "selected_option": 4},
    {"id": str(uuid4()), "selected_option": "0"},
    {"id": str(uuid4()), "selected_option": 0, "correct": True},
])
def test_the_answer_request_carries_only_the_chosen_option(body):
    with pytest.raises(ValidationError):
        RegionQuestionAnswerRequest(**body)


def test_the_companion_sees_the_answer_as_one_factual_line_from_the_learning_log():
    row = {"kind": "region_question", "outcome": "incorrect", "segment_id": str(SEGMENT)}
    assert practice_line(row, "s2") == "comprehension question answered from s2: wrong"
    assert practice_line({**row, "outcome": "done"}, "s2") is None


def test_the_adapter_maps_content_questions_and_library_errors():
    workspace = Mock()
    row = RegionQuestion(id=QUESTION.id, region_preparation_id=uuid4(), position=1, question="Q?",
                         options=["a", "b", "c", "d"], correct_index=3, evidence_segment_id=SEGMENT,
                         evidence_quote="taxi", explanation="E.", generation_version="v")
    workspace.current_region_questions.return_value = CurrentRegionQuestions(
        status="ready", transcript_id=TRACK, questions=(row,))
    current = _RegionQuestions(workspace).current(USER, ITEM)
    assert current.status == "ready" and current.questions[0].correct_index == 3
    assert current.questions[0].options == ("a", "b", "c", "d")
    workspace.current_region_questions.side_effect = LearnerLibraryError(
        "This video is not ready yet.", status_code=409, code="video_not_ready")
    with pytest.raises(PracticeLogError) as error:
        _RegionQuestions(workspace).current(USER, ITEM)
    assert (error.value.status_code, error.value.code) == (409, "video_not_ready")


@pytest.fixture
def api():
    verifier = Mock()
    verifier.verify.side_effect = lambda token: CurrentUser(id=OWNER)
    service, log = make()
    limiter = SlidingWindowLimiter({"practice_event": (2, 60)})
    app.dependency_overrides[get_jwt_verifier] = lambda: verifier
    app.dependency_overrides[get_region_question_service] = lambda: service
    app.dependency_overrides[get_practice_log_limiter] = lambda: limiter
    try:
        yield SimpleNamespace(client=TestClient(app), log=log,
                              headers={"Authorization": "Bearer owner.test.jwt"})
    finally:
        app.dependency_overrides.clear()


def test_the_api_lists_answers_and_rejects_client_authority(api):
    base = f"/api/v1/v3/learner/me/library/videos/{ITEM}/region-questions"
    listed = api.client.get(base, headers=api.headers)
    assert listed.status_code == 200 and "correct" not in listed.text
    assert api.client.get(base).status_code in (401, 403)
    answer = f"{base}/{QUESTION.id}/answer"
    forged = api.client.post(answer, headers=api.headers,
                             json={"id": str(uuid4()), "selected_option": 1, "correct": True})
    assert forged.status_code == 422
    ok = api.client.post(answer, headers=api.headers, json={"id": str(uuid4()), "selected_option": 0})
    assert ok.status_code == 200 and ok.json()["correct"] is True
    missing = api.client.post(f"{base}/{uuid4()}/answer", headers=api.headers,
                              json={"id": str(uuid4()), "selected_option": 0})
    assert missing.status_code == 404 and missing.json()["detail"]["code"] == "question_not_found"
    limited = api.client.post(answer, headers=api.headers, json={"id": str(uuid4()), "selected_option": 0})
    assert limited.status_code == 429
    assert len(api.log.of("region_question")) == 1
