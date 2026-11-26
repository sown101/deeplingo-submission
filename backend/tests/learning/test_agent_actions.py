"""Agent v2 phase 4 (PRD 8.12 point 4): the agent acts for the learner.

`open_review` and `open_video_region` only prepare a card (the learner taps one button); `edit_today` changes today's
tasks at once and the card carries an Undo. Also the text channel's help-button request. No live AI, no database.
"""
import asyncio
from datetime import date
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.bootstrap.wiring.agent import LearnerFacts, VideoRegions
from app.bootstrap.wiring.identity import get_jwt_verifier
from app.bootstrap.wiring.speaking import get_companion_service, get_speaking_rate_limiter
from app.bootstrap.wiring.study_plan import get_study_plan_service
from app.main import app
from app.modules.identity.contracts import CurrentUser
from app.modules.learning.application.agent.ports import RegionTarget
from app.modules.learning.application.agent.prompts import (
    ACTION_RULES,
    AGENT_TEXT_PROMPT_VERSION,
    VOICE_PROMPT_VERSION,
    build_agent_system_prompt,
    build_voice_instruction,
    learner_request,
)
from app.modules.learning.application.agent.session import AgentSession
from app.modules.learning.application.agent.tools import TOOL_SPECS, ToolRegistry
from app.modules.learning.application.speaking_ports import SpeakingPracticeError
from app.modules.learning.application.study_plan import (
    PlanEdit,
    StoredPlan,
    StoredPlanItem,
    StudyPlanError,
)
from app.modules.learning.domain.companion import MAX_HELP_REQUESTS, CompanionEntry, level_policy
from app.modules.learning.domain.study_plan import PlanItemKind, PlanItemStatus
from app.platform.llm.port import ChatReply, ToolCall
from app.platform.rate_limit import SlidingWindowLimiter
from tests.learning.test_companion import OWNER, USER, Turn, make_service
from tests.learning.test_study_plan import FakeStore as PlanStore
from tests.learning.test_study_plan import ITEM, TODAY
from tests.learning.test_study_plan import OWNER as PLAN_OWNER
from tests.learning.test_study_plan import make_service as make_plan_service

OTHER_USER = uuid4()
MINE = [uuid4() for _ in range(25)]
FOREIGN = uuid4()
LIBRARY_ITEM = uuid4()
SEGMENTS = (uuid4(), uuid4())
REGION = f"{SEGMENTS[0]}_{SEGMENTS[1]}"


def run(coroutine):
    return asyncio.run(coroutine)


def session_for(user_id=OWNER, *, day=TODAY, **ticket_fields):
    fields = dict(items=[], language_code="en", support_language_code="vi", scenario_id=None, region_lines=(),
                  excerpt=None, region_id=None, library_item_id=None)
    fields.update(ticket_fields)
    return AgentSession(user=CurrentUser(id=user_id), prepared=SimpleNamespace(ticket=SimpleNamespace(**fields)),
                        day=day)


def call(tools, session, name, args=None):
    return run(tools.call(session, name, args or {}))


class Facts:
    """Saved words per learner; records whose words were asked about."""

    def __init__(self):
        self.asked = []

    def owned_saved_ids(self, user_id, language_code, concept_ids):
        self.asked.append((user_id, language_code, list(concept_ids)))
        own = set(MINE) if user_id == OWNER else {FOREIGN}
        return [str(value) for value in concept_ids if value in own]


# --- open_review ---------------------------------------------------------------------------------------

def test_open_review_keeps_only_the_learners_own_saved_words_and_shows_one_card():
    facts = Facts()
    result = call(ToolRegistry(facts=facts), session_for(), "open_review",
                  {"concept_ids": [str(MINE[0]), str(FOREIGN), "not-an-id", 7, str(MINE[1]), str(MINE[0])]})
    assert result.events == [{"type": "action", "action": "open_review", "language_code": "en",
                              "concept_ids": [str(MINE[0]), str(MINE[1])]}]
    assert result.response == {"opened": True, "words": 2, "dropped": 1}
    # The server asked about this learner and this language only, once, with the ids that parsed.
    assert facts.asked == [(OWNER, "en", [MINE[0], FOREIGN, MINE[1]])]


def test_open_review_refuses_ids_of_another_learner_and_never_raises():
    registry = ToolRegistry(facts=Facts())
    other = call(registry, session_for(), "open_review", {"concept_ids": [str(FOREIGN)]})
    assert other.response == {"opened": False} and other.events == []
    for args in ({}, {"concept_ids": "x"}, {"concept_ids": []}, {"concept_ids": [None, 3, {}]}, {"concept_ids": None}):
        assert call(registry, session_for(), "open_review", args).response == {"opened": False}
    assert call(ToolRegistry(), session_for(), "open_review", {"concept_ids": [str(MINE[0])]}).response == {
        "opened": False}  # nothing to read from


def test_open_review_takes_at_most_twenty_words():
    result = call(ToolRegistry(facts=Facts()), session_for(), "open_review", {"concept_ids": [str(v) for v in MINE]})
    assert len(result.events[0]["concept_ids"]) == 20 and result.response["words"] == 20


def test_a_failing_read_means_no_card():
    facts = Mock()
    facts.owned_saved_ids.side_effect = RuntimeError("database")
    assert call(ToolRegistry(facts=facts), session_for(), "open_review", {"concept_ids": [str(MINE[0])]}).events == []


def test_get_due_cards_and_get_region_give_the_agent_the_ids_it_passes_back():
    decks = Mock()
    decks.deck_cards.return_value = [{"concept_id": MINE[0], "is_new": False}, {"concept_id": MINE[1], "is_new": True}]
    concepts = Mock()
    concepts.list_by_ids.return_value = [SimpleNamespace(id=MINE[0], canonical_text="airport")]
    facts = LearnerFacts(activity=Mock(), decks=decks, concepts=concepts, brief=lambda *a: "", grammar_points=None,
                         grammar_menu=None)
    assert facts.due_cards(OWNER, "en", limit=10) == [{"id": str(MINE[0]), "text": "airport"}]
    # open_review's check asks the deck query, which is scoped to this learner's saved words in this language.
    decks.deck_cards.return_value = [{"concept_id": MINE[0], "is_new": False}]
    assert facts.owned_saved_ids(OWNER, "en", [MINE[0], FOREIGN]) == [str(MINE[0])]
    assert decks.deck_cards.call_args.kwargs["concept_ids"] == [MINE[0], FOREIGN]
    session = session_for(region_lines=("line",), excerpt="[s1] Hi.", region_id=REGION, library_item_id=LIBRARY_ITEM)
    found = call(ToolRegistry(), session, "get_region").response
    assert found["library_item_id"] == str(LIBRARY_ITEM) and found["region_id"] == REGION


# --- open_video_region ---------------------------------------------------------------------------------

class Regions:
    def __init__(self):
        self.asked = []

    def check(self, user_id, library_item_id, region_id):
        self.asked.append((user_id, library_item_id, region_id))
        if user_id == OWNER and library_item_id == LIBRARY_ITEM and region_id == REGION:
            return RegionTarget(title="Airport talk", start_ms=1200)
        return None


def test_open_video_region_shows_a_card_for_the_learners_own_video():
    regions = Regions()
    ok = call(ToolRegistry(video_regions=regions), session_for(), "open_video_region",
              {"library_item_id": str(LIBRARY_ITEM), "region_id": REGION})
    assert ok.events == [{"type": "action", "action": "open_video_region", "library_item_id": str(LIBRARY_ITEM),
                          "region_id": REGION, "title": "Airport talk", "start_ms": 1200}]
    assert ok.response == {"opened": True} and regions.asked[-1][0] == OWNER


def test_open_video_region_refuses_another_learners_video_and_bad_ids_without_raising():
    registry = ToolRegistry(video_regions=Regions())
    stranger = call(registry, session_for(OTHER_USER), "open_video_region",
                    {"library_item_id": str(LIBRARY_ITEM), "region_id": REGION})
    assert stranger.response == {"opened": False} and stranger.events == []
    for args in ({}, {"library_item_id": "x", "region_id": REGION}, {"library_item_id": str(LIBRARY_ITEM)},
                 {"library_item_id": str(LIBRARY_ITEM), "region_id": "a" * 200}, {"library_item_id": 3, "region_id": 4},
                 {"library_item_id": str(LIBRARY_ITEM), "region_id": f"{SEGMENTS[0]}_{uuid4()}"}):
        assert call(registry, session_for(), "open_video_region", args).response == {"opened": False}
    assert call(ToolRegistry(), session_for(), "open_video_region", {
        "library_item_id": str(LIBRARY_ITEM), "region_id": REGION}).response == {"opened": False}


def test_the_region_adapter_checks_ownership_and_that_the_region_is_well_formed_for_that_item():
    video_id, track_id = uuid4(), uuid4()
    library = Mock()
    library.get_for_user.side_effect = lambda library_item_id, user_id: (
        SimpleNamespace(video_id=video_id) if (library_item_id, user_id) == (LIBRARY_ITEM, OWNER) else None)
    videos = Mock()
    videos.get_by_id.return_value = SimpleNamespace(id=video_id, title=" Airport  talk ", original_language_code="en")
    transcripts = Mock()
    transcripts.list_for_video.return_value = [SimpleNamespace(id=track_id, is_original=True, language_code="en")]
    rows = {SEGMENTS[0]: SimpleNamespace(transcript_id=track_id, sequence_number=3, start_ms=1200),
            SEGMENTS[1]: SimpleNamespace(transcript_id=track_id, sequence_number=9, start_ms=9000)}
    segments = Mock()
    segments.get_by_id.side_effect = lambda segment_id: rows.get(segment_id)
    checker = VideoRegions(library=library, videos=videos, transcripts=transcripts, segments=segments)

    assert checker.check(OWNER, LIBRARY_ITEM, REGION) == RegionTarget(title="Airport talk", start_ms=1200)
    assert checker.check(OTHER_USER, LIBRARY_ITEM, REGION) is None  # not their video
    assert checker.check(OWNER, LIBRARY_ITEM, "nonsense") is None  # not a region id
    assert checker.check(OWNER, LIBRARY_ITEM, f"{SEGMENTS[1]}_{SEGMENTS[0]}") is None  # end before start
    rows[SEGMENTS[1]] = SimpleNamespace(transcript_id=uuid4(), sequence_number=9, start_ms=9000)
    assert checker.check(OWNER, LIBRARY_ITEM, REGION) is None  # an end in another transcript
    rows[SEGMENTS[1]] = SimpleNamespace(transcript_id=track_id, sequence_number=3 + 400, start_ms=9000)
    assert checker.check(OWNER, LIBRARY_ITEM, REGION) is None  # longer than a study region may be


# --- edit_today ----------------------------------------------------------------------------------------

class Plan:
    def __init__(self, fail=None):
        self.calls, self.fail = [], fail

    def add_item(self, user, day, *, kind, library_item_id):
        self.calls.append(("add", user.id, day, kind, library_item_id))
        if self.fail:
            raise self.fail
        return PlanEdit(change="added", item_id=uuid4(), kind=kind, minutes=5)

    def remove_item(self, user, day, *, kind, library_item_id):
        self.calls.append(("remove", user.id, day, kind, library_item_id))
        return PlanEdit(change="removed", item_id=uuid4(), kind=kind, minutes=3, video_title="V")


def test_edit_today_applies_at_once_and_shows_what_changed_with_the_item_to_undo():
    plan = Plan()
    session = session_for()
    added = call(ToolRegistry(plan=plan), session, "edit_today", {"change": "add", "kind": "review"})
    assert added.response == {"edited": True, "change": "added", "kind": "review"}
    event = added.events[0]
    assert event["type"] == "action" and event["action"] == "today_edited" and event["change"] == "added"
    assert event["kind"] == "review" and event["minutes"] == 5 and UUID(event["item_id"])
    removed = call(ToolRegistry(plan=plan), session, "edit_today", {"change": "remove", "kind": "my_words"})
    assert removed.events[0]["change"] == "removed" and removed.events[0]["title"] == "V"
    # Always this learner and the conversation's day.
    assert [(call_[1], call_[2]) for call_ in plan.calls] == [(OWNER, TODAY), (OWNER, TODAY)]


def test_edit_today_is_limited_to_three_edits_per_conversation():
    plan, session = Plan(), session_for()
    registry = ToolRegistry(plan=plan)
    for _ in range(3):
        assert call(registry, session, "edit_today", {"change": "add", "kind": "review"}).response["edited"] is True
    fourth = call(registry, session, "edit_today", {"change": "add", "kind": "my_words"})
    assert fourth.response == {"edited": False, "reason": "limit"} and len(plan.calls) == 3


def test_a_refused_edit_returns_a_result_and_never_raises_or_counts():
    session = session_for()
    refused = call(ToolRegistry(plan=Plan(fail=StudyPlanError("conflict", "plan_item_exists", "x"))), session,
                   "edit_today", {"change": "add", "kind": "review"})
    assert refused.response == {"edited": False, "reason": "plan_item_exists"} and refused.events == []
    broken = call(ToolRegistry(plan=Plan(fail=RuntimeError("database"))), session, "edit_today",
                  {"change": "add", "kind": "review"})
    assert broken.response == {"edited": False, "reason": "unavailable"}
    assert session.today_edits == 0
    registry = ToolRegistry(plan=Plan())
    for args in ({}, {"change": "swap", "kind": "review"}, {"change": "add", "kind": "add_video"},
                 {"change": "add", "kind": "review", "library_item_id": "nope"}, {"change": 1, "kind": 2}):
        assert call(registry, session_for(), "edit_today", args).response["edited"] is False
    assert call(ToolRegistry(), session_for(), "edit_today", {"change": "add", "kind": "review"}).response == {
        "edited": False, "reason": "unavailable"}
    assert call(registry, session_for(day=None), "edit_today", {"change": "add", "kind": "review"}).response[
        "reason"] == "unavailable"  # no day, no plan to edit


def test_the_three_new_tools_are_declared_for_both_channels_as_actions():
    specs = {spec.name: spec for spec in TOOL_SPECS}
    for name in ("open_review", "open_video_region", "edit_today"):
        assert specs[name].kind == "action"
    assert "offer_activity" in specs  # plain navigation stays
    assert specs["open_review"].parameters["properties"]["concept_ids"]["type"] == "array"


# --- The study-plan service: add, remove, undo ----------------------------------------------------------

class EditableStore(PlanStore):
    """The plan test store plus what an edit needs: appending one proposal and reopening a dismissed one."""

    def append_items(self, user_id, plan_id, items):
        key = next(key for key, plan in self.plans.items() if plan.id == plan_id)
        plan = self.plans[key]
        added = []
        for draft in items[: 10 - len(plan.items)]:
            item = StoredPlanItem(id=uuid4(), plan_day=plan.plan_day, position=len(plan.items), kind=draft.kind,
                                  status=PlanItemStatus.OPEN, minutes=draft.minutes, reason=draft.reason,
                                  library_item_id=draft.library_item_id, video_title=draft.video_title,
                                  companion_entry=draft.companion_entry, item_count=draft.item_count)
            self.owners[item.id] = user_id
            plan = StoredPlan(id=plan.id, plan_day=plan.plan_day, language_code=plan.language_code,
                              intro=plan.intro, items=(*plan.items, item))
            added.append(item.id)
        self.plans[key] = plan
        return added

    def reopen(self, user_id, item_id):
        found = self._find(item_id)
        if not found or self.owners[item_id] != user_id or found[2].status != PlanItemStatus.DISMISSED:
            return False
        key, plan, item = found
        updated = StoredPlanItem(**{**vars(item), "status": PlanItemStatus.OPEN})
        self.plans[key] = StoredPlan(id=plan.id, plan_day=plan.plan_day, language_code=plan.language_code,
                                     intro=plan.intro,
                                     items=tuple(updated if other.id == item_id else other for other in plan.items))
        return True


def planned(**kwargs):
    """A service whose plan for today exists (Home composed it), with a review and a video task."""
    store = EditableStore()
    service = make_plan_service(store=store, **kwargs)
    service.today(CurrentUser(id=PLAN_OWNER), TODAY)
    # Words were saved after Home composed the plan; the video behind the library item is ready and in English.
    service.saved_words.saved_to_practise.return_value = 3
    service.videos.get_by_id.return_value = SimpleNamespace(
        id=uuid4(), title="Neil's difficult summer job", original_language_code="en", learning_status="ready")
    return service, store


def status_of(store, item_id):
    return store.get_item(PLAN_OWNER, item_id).status


def error_code(callable_):
    with pytest.raises(StudyPlanError) as raised:
        callable_()
    return raised.value.code


def test_adding_a_task_stores_one_open_item_and_undo_dismisses_exactly_that_item():
    service, store = planned(reviews=0, saved=0, videos=False)
    before = [item.id for item in store.get_plan(PLAN_OWNER, language_code="en", plan_day=TODAY).items]
    edit = service.add_item(CurrentUser(id=PLAN_OWNER), TODAY, kind="my_words")
    plan = store.get_plan(PLAN_OWNER, language_code="en", plan_day=TODAY)
    assert edit.change == "added" and edit.kind == "my_words"
    assert [item.id for item in plan.items] == [*before, edit.item_id]
    assert status_of(store, edit.item_id) == PlanItemStatus.OPEN
    undone = service.undo_edit(CurrentUser(id=PLAN_OWNER), edit.item_id, "added")
    assert undone.status == PlanItemStatus.DISMISSED and undone.id == edit.item_id
    # Nothing else moved, and a second undo is harmless.
    assert [item.status for item in store.get_plan(PLAN_OWNER, language_code="en", plan_day=TODAY).items
            if item.id in before] == [PlanItemStatus.OPEN] * len(before)
    assert service.undo_edit(CurrentUser(id=PLAN_OWNER), edit.item_id, "added").status == PlanItemStatus.DISMISSED


def test_removing_a_task_dismisses_the_first_open_one_of_that_kind_and_undo_opens_it_again():
    service, store = planned()
    user = CurrentUser(id=PLAN_OWNER)
    edit = service.remove_item(user, TODAY, kind="review")
    assert edit.change == "removed" and status_of(store, edit.item_id) == PlanItemStatus.DISMISSED
    assert error_code(lambda: service.remove_item(user, TODAY, kind="review")) == "plan_item_not_found"
    reopened = service.undo_edit(user, edit.item_id, "removed")
    assert reopened.status == PlanItemStatus.OPEN
    assert service.undo_edit(user, edit.item_id, "removed").status == PlanItemStatus.OPEN  # idempotent
    other_kinds = [item for item in store.get_plan(PLAN_OWNER, language_code="en", plan_day=TODAY).items
                   if item.id != edit.item_id]
    assert all(item.status == PlanItemStatus.OPEN for item in other_kinds)  # only that one item moved


def test_adding_a_dismissed_task_reopens_it_and_an_open_one_is_refused():
    service, store = planned()
    user = CurrentUser(id=PLAN_OWNER)
    assert error_code(lambda: service.add_item(user, TODAY, kind="review")) == "plan_item_exists"
    removed = service.remove_item(user, TODAY, kind="review")
    again = service.add_item(user, TODAY, kind="review")
    assert again.item_id == removed.item_id and status_of(store, again.item_id) == PlanItemStatus.OPEN


def test_add_checks_what_the_task_points_at_and_which_kinds_are_allowed():
    service, _ = planned(reviews=0, saved=0, videos=False)
    service.saved_words.saved_to_practise.return_value = 0
    user = CurrentUser(id=PLAN_OWNER)
    assert error_code(lambda: service.add_item(user, TODAY, kind="review")) == "plan_nothing_to_add"
    assert error_code(lambda: service.add_item(user, TODAY, kind="my_words")) == "plan_nothing_to_add"
    assert error_code(lambda: service.add_item(user, TODAY, kind="add_video")) == "plan_kind_invalid"
    assert error_code(lambda: service.add_item(user, TODAY, kind="nope")) == "plan_kind_invalid"
    assert error_code(lambda: service.add_item(user, TODAY, kind="video_practice")) == "plan_video_required"
    # A video that is not in the learner's Library cannot be added, and one that is can.
    assert error_code(lambda: service.add_item(user, TODAY, kind="video_practice",
                                               library_item_id=uuid4())) == "plan_item_unavailable"
    video_task = service.add_item(user, TODAY, kind="video_practice", library_item_id=ITEM)
    assert video_task.video_title


def test_an_edit_never_composes_a_plan_and_must_be_for_today():
    store = EditableStore()
    service = make_plan_service(store=store)
    user = CurrentUser(id=PLAN_OWNER)
    assert error_code(lambda: service.add_item(user, TODAY, kind="review")) == "plan_not_ready"
    assert store.created == []  # no model call, no plan made by an edit
    assert error_code(lambda: service.add_item(user, date(2026, 10, 25), kind="review")) == "plan_day_invalid"


def test_undo_is_only_for_the_learners_own_item_and_not_for_a_started_task():
    service, store = planned()
    user = CurrentUser(id=PLAN_OWNER)
    plan = store.get_plan(PLAN_OWNER, language_code="en", plan_day=TODAY)
    review = next(item for item in plan.items if item.kind == PlanItemKind.REVIEW)
    assert error_code(lambda: service.undo_edit(CurrentUser(id=uuid4()), review.id, "added")) == "plan_item_not_found"
    assert error_code(lambda: service.undo_edit(user, uuid4(), "added")) == "plan_item_not_found"
    assert error_code(lambda: service.undo_edit(user, review.id, "sideways")) == "plan_edit_invalid"
    service.decide(user, review.id, PlanItemStatus.ACCEPTED)
    assert error_code(lambda: service.undo_edit(user, review.id, "added")) == "plan_item_decided"
    assert status_of(store, review.id) == PlanItemStatus.ACCEPTED


@pytest.fixture
def plan_api():
    class AuthVerifier:
        def verify(self, token):
            return CurrentUser(id=PLAN_OWNER)

    service, store = planned()
    app.dependency_overrides[get_jwt_verifier] = lambda: AuthVerifier()
    app.dependency_overrides[get_study_plan_service] = lambda: service
    try:
        yield SimpleNamespace(client=TestClient(app), service=service, store=store,
                              headers={"Authorization": "Bearer a.b.c"})
    finally:
        app.dependency_overrides.clear()


def test_the_undo_route_needs_a_login_validates_the_body_and_is_idempotent(plan_api):
    url = "/api/v1/v3/learner/me/plan/items"
    edit = plan_api.service.add_item(CurrentUser(id=PLAN_OWNER), TODAY, kind="my_words")
    assert TestClient(app).post(f"{url}/{edit.item_id}/undo", json={"change": "added"}).status_code == 401
    assert plan_api.client.post(f"{url}/{edit.item_id}/undo", headers=plan_api.headers, json={}).status_code == 422
    assert plan_api.client.post(f"{url}/{edit.item_id}/undo", headers=plan_api.headers,
                                json={"change": "added", "extra": 1}).status_code == 422
    for _ in range(2):
        response = plan_api.client.post(f"{url}/{edit.item_id}/undo", headers=plan_api.headers,
                                        json={"change": "added"})
        assert response.status_code == 200 and response.json()["status"] == "dismissed"
    assert plan_api.client.post(f"{url}/{uuid4()}/undo", headers=plan_api.headers,
                                json={"change": "added"}).status_code == 404


# --- The text channel: action cards and help requests ---------------------------------------------------

DAY = date(2026, 11, 15)


def text_service(outputs, *, plan=None, facts=None, **kwargs):
    service = make_service(outputs=outputs, **kwargs)
    service.plan = plan
    if facts is not None:
        service.facts = facts
    return service


def opened(service):
    return service.start(USER, CompanionEntry.HOME, None)


def tool(name, **args):
    return ChatReply(None, (ToolCall("t1", name, args),))


def test_an_action_card_reaches_the_text_turn_and_the_same_event_shape_is_used_for_voice():
    plan = Plan()
    service = text_service([Turn("Hello! What shall we do?"), tool("edit_today", change="add", kind="review"),
                            Turn("Done. It is in your tasks.")], plan=plan)
    first = opened(service)
    view = service.turn(USER, first.session_ticket, text="Add a review to my tasks today", day=DAY)
    assert [card.action for card in view.actions] == ["today_edited"]
    card = view.actions[0]
    assert card.change == "added" and card.kind == "review" and card.minutes == 5 and card.item_id is not None
    assert plan.calls[0][1:3] == (OWNER, DAY)
    # The wire shape is the voice event without its `type`.
    wire = card.model_dump(mode="json", exclude_none=True)
    assert set(wire) == {"action", "change", "item_id", "kind", "minutes", "concept_ids"}


def test_a_turn_without_an_action_has_an_empty_list():
    service = text_service([Turn("Hello! What shall we do?"), Turn("Nice!")])
    first = opened(service)
    assert service.turn(USER, first.session_ticket, text="I like flying", day=DAY).actions == []


def test_the_edit_budget_is_kept_with_the_conversation_across_turns():
    plan = Plan()
    script = [Turn("Hello!")]
    for index in range(4):
        script += [tool("edit_today", change="add", kind="review"), Turn(f"Done {index}.")]
    service = text_service(script, plan=plan)
    view = opened(service)
    results = []
    for _ in range(4):
        view = service.turn(USER, view.session_ticket, text="Add a review please", day=DAY)
        results.append(len(view.actions))
    assert results == [1, 1, 1, 0] and len(plan.calls) == 3  # the fourth edit was refused by the server


@pytest.mark.parametrize("kind", ["hint", "explain", "natural", "suggest"])
def test_a_help_request_reaches_the_agent_as_the_same_message_the_voice_buttons_send(kind):
    service = text_service([Turn("Hello!"), Turn("Here you go.")])
    first = opened(service)
    service.turn(USER, first.session_ticket, text="I like flying", day=DAY, request=kind)
    last_message = service.model.calls[-1][0][-1]["content"]
    assert "<learner_said>I like flying</learner_said>" in last_message
    assert learner_request(kind) in last_message
    assert service.model.calls[-1][1]  # the agent had its tools to answer with


def test_a_help_request_works_without_any_words_and_counts_as_a_turn():
    service = text_service([Turn("Hello! Do you like flying?"), tool("show_hint", question="Bạn thích gì?"),
                            Turn("Take your time.")])
    first = opened(service)
    view = service.turn(USER, first.session_ticket, day=DAY, request="hint")
    last_message = [m for m in service.model.calls[1][0] if m["role"] == "user"][-1]["content"]
    assert "<learner_said>" not in last_message and learner_request("hint") in last_message
    assert view.learner_transcript is None and view.turn == 1 and view.hints.question == "Bạn thích gì?"
    # The conversation goes on: the next turn works with the new ticket.
    assert view.session_ticket


def test_a_wrong_request_or_empty_input_without_a_request_is_refused():
    service = text_service([Turn("Hello!")])
    first = opened(service)
    with pytest.raises(SpeakingPracticeError) as bad:
        service.turn(USER, first.session_ticket, text="hi", day=DAY, request="solve")
    assert bad.value.code == "companion_request_invalid"
    with pytest.raises(SpeakingPracticeError) as empty:
        service.turn(USER, first.session_ticket, text="  ", day=DAY)
    assert empty.value.code == "companion_text_invalid"


def test_help_requests_are_capped_per_conversation_like_the_voice_channel():
    service = text_service([Turn("Hello!")])
    first = opened(service)
    session = service.load(USER, first.session_ticket)
    session.help_requests = MAX_HELP_REQUESTS
    token, _ = service.save(session)
    with pytest.raises(SpeakingPracticeError) as limited:
        service.turn(USER, token, day=DAY, request="hint")
    assert limited.value.code == "companion_help_limit"
    # Ordinary turns are not affected by the cap.
    service.model.queue.append(ChatReply("Nice!"))
    assert service.turn(USER, token, text="I like flying", day=DAY).reply == "Nice!"


def test_the_turn_route_takes_a_request_with_or_without_words(monkeypatch):
    verifier = Mock()
    verifier.verify.side_effect = lambda token: CurrentUser(id=OWNER)
    service = text_service([Turn("Hello!"), Turn("A hint is on screen."), Turn("And another.")])
    limiter = SlidingWindowLimiter({"companion_start": (5, 60), "companion_turn": (20, 60)})
    app.dependency_overrides[get_jwt_verifier] = lambda: verifier
    app.dependency_overrides[get_companion_service] = lambda: service
    app.dependency_overrides[get_speaking_rate_limiter] = lambda: limiter
    try:
        client, headers = TestClient(app), {"Authorization": "Bearer owner.test.jwt"}
        url = "/api/v1/v3/learner/me/companion"
        ticket = client.post(f"{url}/sessions", headers=headers, json={"entry": "home"}).json()["session_ticket"]
        bare = client.post(f"{url}/turns", headers=headers, data={"session_ticket": ticket, "request": "hint"})
        assert bare.status_code == 200 and bare.json()["actions"] == []
        wrong = client.post(f"{url}/turns", headers=headers, data={"session_ticket": ticket, "request": "cheat"})
        assert wrong.status_code == 422 and wrong.json()["detail"]["code"] == "companion_request_invalid"
        nothing = client.post(f"{url}/turns", headers=headers, data={"session_ticket": ticket})
        assert nothing.status_code == 422  # no words, no audio and no request
        both = client.post(f"{url}/turns", headers=headers, data={"session_ticket": ticket, "text": "hi"},
                           files={"audio": ("t.wav", b"x", "audio/wav")})
        assert both.status_code == 422
        with_words = client.post(f"{url}/turns", headers=headers, data={
            "session_ticket": bare.json()["session_ticket"], "request": "natural", "text": "I like fly"})
        assert with_words.status_code == 200
    finally:
        app.dependency_overrides.clear()


# --- Prompt --------------------------------------------------------------------------------------------

def test_both_prompts_carry_the_action_rules_and_the_versions_moved():
    assert VOICE_PROMPT_VERSION == "agent-voice-v16" and AGENT_TEXT_PROMPT_VERSION == "agent-text-v10"
    text = build_agent_system_prompt(learning_language="en", support_language="vi", policy=level_policy("en"),
                                     topic="t", mode="topic", items=[], excerpt=None, region=False)
    voice = build_voice_instruction(mode="topic", learning_language="en", topic="t", items=[], excerpt=None)
    for prompt in (text, voice):
        assert ACTION_RULES in prompt
        assert "Never invent an id" in prompt and "one action card" in prompt
    assert "open_review, open_video_region, edit_today" in voice


def test_the_text_channel_offers_each_new_tool_only_when_it_can_work():
    bare = text_service([Turn("Hello!")])
    assert {"open_review", "edit_today", "open_video_region"}.isdisjoint(spec.name for spec in bare._specs())
    wired = text_service([Turn("Hello!")], plan=Plan(), facts=Facts())
    wired.video_regions = Regions()
    assert {"open_review", "edit_today", "open_video_region"} <= {spec.name for spec in wired._specs()}


def test_a_due_word_tells_the_agent_how_far_the_learner_has_got_with_it():
    decks = Mock()
    decks.deck_cards.return_value = [{"concept_id": MINE[0], "is_new": False}, {"concept_id": MINE[1], "is_new": False}]
    concepts = Mock()
    concepts.list_by_ids.return_value = [SimpleNamespace(id=MINE[0], canonical_text="airport"),
                                         SimpleNamespace(id=MINE[1], canonical_text="ticket")]
    saved = Mock()
    saved.list_for_user.return_value = [{"concept_id": str(MINE[0]), "rung": 3}]
    facts = LearnerFacts(activity=Mock(), decks=decks, concepts=concepts, brief=lambda *a: "", grammar_points=None,
                         grammar_menu=None, saved=saved)
    assert facts.due_cards(OWNER, "en", limit=10) == [{"id": str(MINE[0]), "text": "airport", "use": "used with help"},
                                                      {"id": str(MINE[1]), "text": "ticket"}]
    assert saved.list_for_user.call_args.kwargs == {"language_code": "en"}
    saved.list_for_user.side_effect = RuntimeError("database")
    assert facts.due_cards(OWNER, "en", limit=10)[0] == {"id": str(MINE[0]), "text": "airport"}
