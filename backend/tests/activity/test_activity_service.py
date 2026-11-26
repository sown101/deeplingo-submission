"""The learning log and study requests: recording, bounded reads, auto-closing, the API, export and agent tools."""
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.bootstrap.wiring.activity import get_activity_service
from app.bootstrap.wiring.agent import LearnerFacts
from app.bootstrap.wiring.identity import get_jwt_verifier
from app.main import app
from app.modules.activity.application.service import MAX_READ_ROWS
from app.modules.activity.contracts import ActivityEntry, ActivityError, log_activity
from app.modules.activity.infrastructure.data_export import ActivityDataSection
from app.modules.activity.infrastructure.repositories import ActivityLogRepository
from app.modules.identity.contracts import CurrentUser
from app.modules.learning.application.agent.session import AgentSession
from app.modules.learning.application.agent.tools import (
    MAX_ACTIVITY_ROWS,
    MAX_STUDY_REQUESTS_PER_SESSION,
    ToolRegistry,
)
from tests.activity.fakes import BrokenLog, make_activity
from tests.learner.test_data_export import FakeClient
from tests.learning.test_realtime_companion import run

ANNA, BEN = uuid4(), uuid4()
POINT = "en.past_simple.regular"
WORD = str(uuid4())


def entry(user=ANNA, event="e1", **overrides):
    fields = dict(user_id=user, language_code="en", client_event_id=event, kind="dictation", outcome="correct")
    fields.update(overrides)
    return ActivityEntry(**fields)


# --- Recording ------------------------------------------------------------------------------------------------

def test_a_retried_event_is_stored_once_and_a_new_one_is_added():
    service, log, _, _ = make_activity()
    assert service.record(entry()) is True
    assert service.record(entry()) is False
    assert service.record(entry(event="e2")) is True
    assert len(log.entries) == 2
    # The same event id from another learner is that learner's own row.
    assert service.record(entry(user=BEN)) is True


def test_recording_never_fails_the_action_when_the_store_or_the_entry_is_bad():
    broken, _, _, _ = make_activity(BrokenLog())
    assert broken.record(entry()) is False
    assert log_activity(broken, user_id=ANNA, language_code="en", client_event_id="x", kind="dictation",
                        outcome="correct") is False  # the store is down: False, no exception
    good, log, _, _ = make_activity()
    assert log_activity(good, user_id=ANNA, language_code="en", client_event_id="x", kind="not_a_kind",
                        outcome="correct") is False
    assert log_activity(None, user_id=ANNA, language_code="en", client_event_id="x", kind="dictation",
                        outcome="correct") is False
    assert log.entries == []


def test_an_entry_is_small_and_consistent():
    with pytest.raises(ValueError):
        entry(detail={"text": "x" * 2000})
    with pytest.raises(ValueError):
        entry(item_type="concept")  # an item type needs its id
    with pytest.raises(ValueError):
        entry(score=101)


def test_the_repository_inserts_once_by_client_event_id():
    calls = []

    class Table:
        def upsert(self, row, **options):
            calls.append((row, options))
            return self

        def execute(self):
            return SimpleNamespace(data=[{"id": "1"}] if len(calls) == 1 else [])

    repo = ActivityLogRepository(SimpleNamespace(schema=lambda name: SimpleNamespace(table=lambda table: Table())))
    assert repo.insert_once(entry(score=87.26)) is True
    assert repo.insert_once(entry(score=87.26)) is False
    row, options = calls[0]
    assert options == {"on_conflict": "user_id,client_event_id", "ignore_duplicates": True}
    assert row["user_id"] == str(ANNA) and row["score"] == 87.3 and row["language_code"] == "en"


# --- Bounded reads --------------------------------------------------------------------------------------------

def test_reads_are_for_one_learner_one_language_and_capped():
    service, log, _, _ = make_activity()
    for index in range(MAX_READ_ROWS + 20):
        service.record(entry(event=f"e{index}"))
    service.record(entry(event="zh", language_code="zh"))
    service.record(entry(event="ben", user=BEN))
    rows = service.recent(ANNA, language_code="en", limit=10_000)
    assert len(rows) == MAX_READ_ROWS and {row.language_code for row in rows} == {"en"}
    assert [row.language_code for row in service.recent(ANNA, language_code="zh")] == ["zh"]
    assert service.recent(ANNA, language_code="en", kinds=["flashcard"]) == []
    cutoff = log.times[-1] - timedelta(seconds=1)
    assert len(service.recent(ANNA, language_code="en", since=cutoff, limit=500)) <= 2


# --- Study requests -------------------------------------------------------------------------------------------

def test_a_correct_result_for_the_item_closes_the_open_request_and_a_wrong_one_does_not():
    service, _, requests, _ = make_activity()
    asked, created = service.create_study_request(ANNA, language_code="en", kind="grammar_redo", item_id=POINT,
                                                  reason="  past   tense  ", created_by="agent")
    assert created and asked.reason == "past tense" and asked.item_type == "grammar_point"
    service.record(entry(event="w", kind="grammar_exercise", outcome="incorrect", item_type="grammar_point",
                         item_id=POINT))
    assert requests.rows[0].status == "open"
    service.record(entry(event="r", kind="grammar_exercise", outcome="correct", item_type="grammar_point",
                         item_id=POINT))
    assert requests.rows[0].status == "done" and requests.rows[0].closed_at is not None
    # Another learner's or another language's correct result closes nothing.
    other, _, others, _ = make_activity()
    other.create_study_request(ANNA, language_code="en", kind="grammar_redo", item_id=POINT, reason=None,
                               created_by="system")
    other.record(entry(event="b", user=BEN, kind="grammar_exercise", item_type="grammar_point", item_id=POINT))
    other.record(entry(event="z", language_code="zh", kind="grammar_exercise", item_type="grammar_point",
                       item_id=POINT))
    assert others.rows[0].status == "open"


def test_a_correct_result_closes_only_the_requests_of_the_kind_it_answers():
    service, _, requests, _ = make_activity()
    word = str(uuid4())
    service.create_study_request(ANNA, language_code="en", kind="pronunciation_retry", item_id=word, reason=None,
                                 created_by="agent")
    service.create_study_request(ANNA, language_code="en", kind="word_review", item_id=word, reason=None,
                                 created_by="agent")
    service.record(entry(event="f", kind="flashcard", outcome="correct", item_type="concept", item_id=word))
    assert {row.kind: row.status for row in requests.rows} == {"pronunciation_retry": "open", "word_review": "done"}
    service.record(entry(event="l", kind="lookup", outcome="correct", item_type="concept", item_id=word))
    assert requests.rows[0].status == "open"  # a kind that answers no request closes nothing
    service.record(entry(event="p", kind="pronunciation", outcome="correct", item_type="concept", item_id=word))
    assert requests.rows[0].status == "done"


def test_the_same_open_request_within_seven_days_is_not_added_again():
    service, _, requests, clock = make_activity()
    first, created = service.create_study_request(ANNA, language_code="en", kind="grammar_redo", item_id=POINT,
                                                  reason=None, created_by="agent")
    again, created_again = service.create_study_request(ANNA, language_code="en", kind="grammar_redo",
                                                        item_id=POINT, reason="later", created_by="agent")
    assert created and not created_again and again.id == first.id and len(requests.rows) == 1
    clock.advance(days=8)
    _, after_a_week = service.create_study_request(ANNA, language_code="en", kind="grammar_redo", item_id=POINT,
                                                   reason=None, created_by="agent")
    assert after_a_week and len(requests.rows) == 2
    with pytest.raises(ActivityError):
        service.create_study_request(ANNA, language_code="en", kind="nonsense", item_id=POINT, reason=None,
                                     created_by="agent")


def test_only_the_owner_can_dismiss_and_a_closed_request_stays_closed():
    service, _, _, _ = make_activity()
    asked, _ = service.create_study_request(ANNA, language_code="en", kind="word_review", item_id=str(uuid4()),
                                            reason=None, created_by="agent")
    with pytest.raises(ActivityError) as foreign:
        service.dismiss(BEN, asked.id)
    assert foreign.value.status_code == 404
    assert service.dismiss(ANNA, asked.id).status == "dismissed"
    assert service.dismiss(ANNA, asked.id).status == "dismissed"


# --- API ------------------------------------------------------------------------------------------------------

@pytest.fixture
def api():
    service, log, requests, _ = make_activity()
    tokens = {"anna.test.jwt": ANNA, "ben.test.jwt": BEN}
    verifier = SimpleNamespace(verify=lambda token: CurrentUser(id=tokens[token]))
    app.dependency_overrides[get_jwt_verifier] = lambda: verifier
    app.dependency_overrides[get_activity_service] = lambda: service
    try:
        yield SimpleNamespace(
            client=TestClient(app), service=service, log=log, requests=requests,
            anna={"Authorization": "Bearer anna.test.jwt"}, ben={"Authorization": "Bearer ben.test.jwt"})
    finally:
        app.dependency_overrides.clear()


URL = "/api/v1/v3/learner/me"


def test_a_study_request_is_dismissed_by_its_owner_only(api):
    # The list lives in the agent screen (`GET /learner/me/agent/study-requests`, tests/learning); dismissing stays here.
    asked, _ = api.service.create_study_request(ANNA, language_code="en", kind="grammar_redo", item_id=POINT,
                                                reason="Past tense", created_by="agent")
    assert api.client.post(f"{URL}/study-requests/{asked.id}/dismiss", headers=api.ben).status_code == 404
    done = api.client.post(f"{URL}/study-requests/{asked.id}/dismiss", headers=api.anna)
    assert done.status_code == 200 and done.json()["status"] == "dismissed" and "user_id" not in done.text
    assert [row.status for row in api.service.study_requests(ANNA, language_code="en")] == ["dismissed"]
    assert api.client.post(f"{URL}/study-requests/{uuid4()}/dismiss", headers=api.anna).status_code == 404


# --- Export and deletion --------------------------------------------------------------------------------------

def test_the_export_carries_only_the_learners_log_and_requests():
    other = str(uuid4())
    db = FakeClient({
        "learner_activity_log": [
            {"user_id": str(ANNA), "id": "1", "language_code": "en", "kind": "dictation", "outcome": "correct"},
            {"user_id": other, "id": "2", "language_code": "en", "kind": "dictation", "outcome": "correct"}],
        "learner_study_requests": [
            {"user_id": str(ANNA), "id": "3", "language_code": "en", "kind": "grammar_redo", "status": "open"},
            {"user_id": other, "id": "4", "language_code": "en", "kind": "grammar_redo", "status": "open"}]})
    exported = ActivityDataSection(db).export(ANNA)
    assert [row["id"] for row in exported["activity_log"]] == ["1"]
    assert [row["id"] for row in exported["study_requests"]] == ["3"]
    assert "client_event_id" not in str(exported)


def test_the_learner_export_service_is_wired_with_the_activity_section(monkeypatch):
    from app.bootstrap.wiring import learner as learner_wiring

    class Client:
        def schema(self, name):
            return self

    monkeypatch.setattr(learner_wiring, "service_client", lambda: Client())
    names = [section.name for section in learner_wiring.get_learner_data_export_service().sections]
    assert "activity" in names


# --- Agent tools ----------------------------------------------------------------------------------------------

class FakeConcepts:
    def __init__(self, languages):
        self.languages = languages  # concept id -> language code

    def get_by_id(self, concept_id):
        language = self.languages.get(str(concept_id))
        return SimpleNamespace(language_code=language) if language else None

    def list_by_ids(self, ids):
        return [SimpleNamespace(id=value, canonical_text=f"word-{str(value)[:4]}") for value in ids
                if str(value) in self.languages]


def make_facts(activity, *, points=frozenset({POINT}), words=None):
    return LearnerFacts(activity=activity, decks=SimpleNamespace(deck_counts=lambda user: []),
                        concepts=FakeConcepts({WORD: "en"} if words is None else words), brief=lambda *_: "",
                        grammar_points=lambda language, support: set(points) if language == "en" else set(),
                        grammar_menu=lambda *_: None)


def make_tools(**kwargs):
    activity, log, requests, _ = make_activity()
    return ToolRegistry(facts=make_facts(activity, **kwargs)), activity, log, requests


def tool_session():
    ticket = SimpleNamespace(items=[], language_code="en", support_language_code="vi", scenario_id=None,
                             region_lines=(), excerpt=None, region_id=None)
    return AgentSession(user=CurrentUser(id=ANNA), prepared=SimpleNamespace(ticket=ticket))


def call(tools, session, name, args):
    return run(tools.call(session, name, args)).response


def test_the_agent_reads_a_short_bounded_list_for_the_conversations_language_only():
    tools, activity, _, _ = make_tools()
    for index in range(30):
        activity.record(entry(event=f"e{index}", item_type="segment", item_id=str(uuid4())))
    activity.record(entry(event="zh", language_code="zh"))
    activity.record(entry(event="ben", user=BEN))
    activity.record(entry(event="word", kind="flashcard", item_type="concept", item_id=WORD))
    session = tool_session()
    answer = call(tools, session, "get_recent_activity", {})
    assert answer["found"] and len(answer["activity"]) == MAX_ACTIVITY_ROWS
    assert {"kind", "outcome", "score", "item", "when"} <= set(answer["activity"][0])
    # A word row names the word, never its id.
    assert answer["activity"][0]["item"] == f"word-{WORD[:4]}"
    assert len(call(tools, session, "get_recent_activity", {"limit": 3})["activity"]) == 3
    assert len(call(tools, session, "get_recent_activity", {"limit": 10_000})["activity"]) == MAX_ACTIVITY_ROWS
    assert call(tools, session, "get_recent_activity", {"limit": "many", "kind": 7})["found"] is True  # bad types ignored
    assert call(tools, session, "get_recent_activity", {"kind": "cloze"}) == {"found": False, "activity": []}
    assert call(ToolRegistry(), session, "get_recent_activity", {}) == {"found": False}


def test_the_agent_can_create_a_request_only_for_a_point_or_word_that_exists_in_the_language():
    tools, _, _, requests = make_tools()
    session = tool_session()
    assert call(tools, session, "create_study_request", {"kind": "grammar_redo", "item": "en.made.up"}) \
        == {"created": False, "already_open": False}
    assert call(tools, session, "create_study_request", {"kind": "word_review", "item": str(uuid4())})["created"] is False
    assert call(tools, session, "create_study_request", {"kind": "delete_account", "item": POINT}) == {"created": False}
    assert call(tools, session, "create_study_request", {"kind": "grammar_redo"}) == {"created": False}
    assert call(tools, session, "create_study_request", {"kind": "grammar_redo", "item": ["x"]}) == {"created": False}
    assert requests.rows == []
    made = run(tools.call(session, "create_study_request", {"kind": "grammar_redo", "item": POINT, "reason": "x" * 1000}))
    assert made.response == {"created": True, "already_open": False}
    # The learner sees it on screen (and can dismiss it in the notebook).
    assert made.events == [{"type": "study_request", "kind": "grammar_redo", "item": POINT, "title": None}]
    assert len(requests.rows[0].reason) == 300 and requests.rows[0].created_by == "agent"
    # An identical open request is not added again, even from a later conversation.
    again = call(tools, tool_session(), "create_study_request", {"kind": "grammar_redo", "item": POINT})
    assert again == {"created": False, "already_open": True} and len(requests.rows) == 1
    assert call(tools, session, "create_study_request", {"kind": "word_review", "item": WORD})["created"] is True


def test_a_conversation_can_create_only_a_few_requests():
    points = {f"en.p.k{index}" for index in range(10)}
    tools, _, _, requests = make_tools(points=points)
    session = tool_session()
    results = [call(tools, session, "create_study_request", {"kind": "grammar_redo", "item": key})["created"]
               for key in sorted(points)[:MAX_STUDY_REQUESTS_PER_SESSION + 2]]
    assert results == [True] * MAX_STUDY_REQUESTS_PER_SESSION + [False] * 2
    assert len(requests.rows) == MAX_STUDY_REQUESTS_PER_SESSION


def test_a_slow_or_failing_store_gives_the_agent_a_plain_no():
    class Broken:
        def recent_activity(self, *args, **kwargs):
            raise TimeoutError

        def create_request(self, *args, **kwargs):
            raise ConnectionError

    tools = ToolRegistry(facts=Broken())
    session = tool_session()
    assert call(tools, session, "get_recent_activity", {}) == {"found": False}
    assert call(tools, session, "create_study_request", {"kind": "grammar_redo", "item": POINT}) == {"created": False}


def test_the_tools_are_declared_to_the_provider_with_closed_kinds():
    from app.modules.learning.infrastructure.speech.gemini_live import TOOLS
    declared = {fn["name"]: fn for fn in TOOLS[0]["functionDeclarations"]}
    assert {"get_recent_activity", "create_study_request", "get_region", "get_due_cards", "get_study_requests",
            "get_grammar_lesson", "get_progress_summary", "save_word"} <= set(declared)
    assert declared["create_study_request"]["parameters"]["properties"]["kind"]["enum"] == ["grammar_redo",
                                                                                          "word_review"]
    assert declared["create_study_request"]["parameters"]["type"] == "OBJECT"
    assert "dictation" in declared["get_recent_activity"]["parameters"]["properties"]["kind"]["enum"]


def test_wiring_checks_words_and_grammar_points_against_the_real_sources(monkeypatch):
    from app.bootstrap.wiring import agent as wiring
    monkeypatch.setattr("app.modules.content.infrastructure.repositories.concepts.ConceptRepository.get_by_id",
                        lambda self, concept_id: SimpleNamespace(language_code="zh"))
    monkeypatch.setattr(wiring, "_profile_brief", lambda: (lambda *_: ""))
    facts = wiring.build_learner_facts(SimpleNamespace())
    assert facts._concept_language("not-a-uuid") is None
    assert facts._concept_language(str(uuid4())) == "zh"
    english = facts._grammar_points("en", "vi")
    assert english and "en.made.up" not in english and facts._grammar_points("xx", "vi") == set()
