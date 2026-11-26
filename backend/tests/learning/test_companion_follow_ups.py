"""Next steps added to today's plan when a conversation ends."""
from datetime import date
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

from app.modules.learning.application.study_plan import (
    ConversationFollowUpService,
    StoredPlanItem,
    StudyPlanItemView,
)
from app.modules.learning.domain.companion import CompanionEntry
from app.modules.learning.domain.study_plan import (
    MAX_FOLLOW_UPS,
    PlanItemKind,
    PlanItemStatus,
    PlanVideo,
    compose_follow_ups,
)
from app.modules.learning.infrastructure.study_plans import StudyPlanRepository
from tests.learning.test_companion import ITEM_ID, OWNER, USER, make_service, speech, turn_output
from tests.learning.test_study_plan import NOW, TODAY, FakeStore, make_service as make_plan_service

VIDEO = PlanVideo(library_item_id=ITEM_ID, title="Neil's difficult summer job")


# --- Composition -------------------------------------------------------------------------

def test_follow_ups_are_review_then_the_video_and_at_most_two():
    items = compose_follow_ups(reviews_ready=6, video=VIDEO)
    assert [item.kind for item in items] == [PlanItemKind.REVIEW, PlanItemKind.VIDEO_PRACTICE]
    assert len(items) <= MAX_FOLLOW_UPS and items[0].item_count == 6 and items[1].library_item_id == ITEM_ID
    assert compose_follow_ups(reviews_ready=0, video=None) == []
    assert [item.kind for item in compose_follow_ups(reviews_ready=0, video=VIDEO)] == [PlanItemKind.VIDEO_PRACTICE]


# --- Service --------------------------------------------------------------------------------

class AppendingStore(FakeStore):
    def append_items(self, user_id, plan_id, items):
        key, plan = next((key, plan) for key, plan in self.plans.items() if plan.id == plan_id)
        assert key[0] == user_id
        existing = {(item.kind, item.library_item_id, item.companion_entry) for item in plan.items}
        added = []
        stored = list(plan.items)
        for draft in items:
            if (draft.kind, draft.library_item_id, draft.companion_entry) in existing:
                continue
            item = StoredPlanItem(id=uuid4(), plan_day=plan.plan_day, position=len(stored), kind=draft.kind,
                                  status=PlanItemStatus.OPEN, minutes=draft.minutes, reason=draft.reason,
                                  library_item_id=draft.library_item_id, video_title=draft.video_title,
                                  companion_entry=draft.companion_entry, item_count=draft.item_count)
            self.owners[item.id] = user_id
            stored.append(item)
            added.append(item.id)
        self.plans[key] = type(plan)(id=plan.id, plan_day=plan.plan_day, language_code=plan.language_code,
                                    intro=plan.intro, items=tuple(stored))
        return added


def follow_up_service(*, store, reviews=3, video_ready=True):
    plan_service = make_plan_service(store=store, reviews=0)
    reviews_reader = Mock()
    reviews_reader.ready_count.return_value = reviews
    video = SimpleNamespace(id=uuid4(), title="Neil's difficult summer job", original_language_code="en",
                            learning_status="ready" if video_ready else "processing")
    library = Mock()
    library.get_for_user.side_effect = lambda library_item_id, user_id: (
        SimpleNamespace(video_id=video.id) if (library_item_id, user_id) == (ITEM_ID, OWNER) else None)
    videos = Mock()
    videos.get_by_id.side_effect = lambda video_id: video if video_id == video.id else None
    return ConversationFollowUpService(preferences=plan_service.preferences, library=library, videos=videos,
                                       reviews=reviews_reader, store=store, clock=lambda: NOW)


def plan_today(store, user=USER):
    """The plan the learner got on Home today (review dismissed earlier is irrelevant here)."""
    make_plan_service(store=store, reviews=0, videos=False).today(user, TODAY)


def test_follow_ups_join_todays_plan_once():
    store = AppendingStore()
    plan_today(store)
    service = follow_up_service(store=store)

    added = service.after_conversation(USER, TODAY, library_item_id=ITEM_ID)
    assert [item.kind for item in added] == [PlanItemKind.REVIEW, PlanItemKind.VIDEO_PRACTICE]
    assert added[0].item_count == 3 and added[1].library_item_id == ITEM_ID
    assert service.after_conversation(USER, TODAY, library_item_id=ITEM_ID) == []  # already in the plan
    plan = store.get_plan(OWNER, language_code="en", plan_day=TODAY)
    assert [item.kind for item in plan.items] == [PlanItemKind.ADD_VIDEO, PlanItemKind.CONVERSATION,
                                                  PlanItemKind.REVIEW, PlanItemKind.VIDEO_PRACTICE]


def test_no_plan_no_day_or_a_far_day_means_no_follow_ups():
    store = AppendingStore()
    service = follow_up_service(store=store)
    assert service.after_conversation(USER, TODAY, library_item_id=ITEM_ID) == []  # Home not opened today
    plan_today(store)
    assert service.after_conversation(USER, None, library_item_id=ITEM_ID) == []
    assert service.after_conversation(USER, date(2026, 10, 25), library_item_id=ITEM_ID) == []
    assert len(store.get_plan(OWNER, language_code="en", plan_day=TODAY).items) == 2


def test_only_an_owned_ready_video_is_proposed():
    store = AppendingStore()
    plan_today(store)
    not_ready = follow_up_service(store=store, reviews=0, video_ready=False)
    assert not_ready.after_conversation(USER, TODAY, library_item_id=ITEM_ID) == []
    other = SimpleNamespace(id=uuid4())
    plan_today(store, user=other)
    assert follow_up_service(store=store, reviews=0).after_conversation(other, TODAY, library_item_id=ITEM_ID) == []


def test_a_failure_means_no_follow_ups():
    store = AppendingStore()
    plan_today(store)
    service = follow_up_service(store=store)
    service.reviews.ready_count.side_effect = RuntimeError("database")
    assert service.after_conversation(USER, TODAY, library_item_id=ITEM_ID) == []


# --- Conversation -------------------------------------------------------------------------

class FakeFollowUps:
    def __init__(self, error=None):
        self.calls, self.error = [], error

    def after_conversation(self, user, day, *, library_item_id):
        self.calls.append((user.id, day, library_item_id))
        if self.error:
            raise self.error
        return [StudyPlanItemView(id=uuid4(), kind=PlanItemKind.REVIEW, status=PlanItemStatus.OPEN, minutes=2,
                                  reason="Ôn 2 mục.", item_count=2, library_item_id=None, video_title=None,
                                  companion_entry=None)]


def closing(follow_ups, *, texts=("I like my job",), outputs=None):
    service = make_service(outputs=outputs or (turn_output(), turn_output(next="close")), texts=list(texts))
    service.follow_ups = follow_ups
    return service, service.start(USER, CompanionEntry.VIDEO, ITEM_ID).session_ticket


def test_a_closing_turn_returns_follow_ups_for_the_learners_day():
    follow_ups = FakeFollowUps()
    service, ticket = closing(follow_ups)
    view = service.turn(USER, ticket, speech(), day=TODAY)
    assert view.finished and len(view.follow_ups) == 1
    assert follow_ups.calls == [(OWNER, TODAY, ITEM_ID)]


def test_follow_ups_need_an_ended_conversation_a_day_and_never_break_the_turn():
    follow_ups = FakeFollowUps()
    service, ticket = closing(follow_ups, outputs=(turn_output(), turn_output()))
    assert service.turn(USER, ticket, speech(), day=TODAY).follow_ups == [] and follow_ups.calls == []

    service, ticket = closing(follow_ups)
    assert service.turn(USER, ticket, speech()).follow_ups == []  # no day sent

    broken = FakeFollowUps(error=RuntimeError("down"))
    service, ticket = closing(broken)
    view = service.turn(USER, ticket, speech(), day=TODAY)
    assert view.finished and view.follow_ups == []


def test_finishing_after_speaking_returns_follow_ups_but_not_before():
    follow_ups = FakeFollowUps()
    service, ticket = closing(follow_ups, outputs=(turn_output(), turn_output()))
    ticket = service.turn(USER, ticket, speech(), day=TODAY).session_ticket
    assert len(service.finish(USER, ticket, day=TODAY).follow_ups) == 1

    silent = FakeFollowUps()
    service, ticket = closing(silent)
    assert service.finish(USER, ticket, day=TODAY).follow_ups == [] and silent.calls == []


def test_repository_appends_through_one_rpc():
    client = Mock()
    added = uuid4()
    client.schema.return_value.rpc.return_value.execute.return_value = SimpleNamespace(data=[str(added)])
    ids = StudyPlanRepository(client).append_items(OWNER, uuid4(), compose_follow_ups(reviews_ready=2, video=VIDEO))
    name, payload = client.schema.return_value.rpc.call_args.args
    assert name == "append_companion_proposals" and ids == [added]
    assert [item["kind"] for item in payload["p_items"]] == ["review", "video_practice"]


def test_the_turn_route_passes_the_learners_day_and_rejects_a_bad_one():
    from fastapi.testclient import TestClient

    from app.bootstrap.wiring.identity import get_jwt_verifier
    from app.bootstrap.wiring.speaking import get_companion_service, get_speaking_rate_limiter
    from app.main import app
    from app.modules.identity.contracts import CurrentUser
    from app.platform.rate_limit import SlidingWindowLimiter
    from tests.learning.speaking_fixtures import speech_like_wav

    follow_ups = FakeFollowUps()
    service, ticket = closing(follow_ups)
    verifier = Mock()
    verifier.verify.side_effect = lambda token: CurrentUser(id=OWNER)
    app.dependency_overrides[get_jwt_verifier] = lambda: verifier
    app.dependency_overrides[get_companion_service] = lambda: service
    app.dependency_overrides[get_speaking_rate_limiter] = lambda: SlidingWindowLimiter({"companion_turn": (5, 60)})
    try:
        client = TestClient(app)
        url = "/api/v1/v3/learner/me/companion/turns"
        headers = {"Authorization": "Bearer owner.test.jwt"}
        bad = client.post(url, headers=headers, data={"session_ticket": ticket, "day": "tomorrow"},
                          files={"audio": ("t.wav", speech_like_wav(), "audio/wav")})
        assert bad.status_code == 422
        good = client.post(url, headers=headers, data={"session_ticket": ticket, "day": TODAY.isoformat()},
                           files={"audio": ("t.wav", speech_like_wav(), "audio/wav")})
        assert good.status_code == 200 and good.json()["follow_ups"][0]["kind"] == "review"
        assert follow_ups.calls == [(OWNER, TODAY, ITEM_ID)]
    finally:
        app.dependency_overrides.clear()
