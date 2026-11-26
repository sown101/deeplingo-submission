"""Daily study plan composition, wording, choices and HTTP surface."""
from datetime import UTC, date, datetime
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.bootstrap.wiring.identity import get_jwt_verifier
from app.bootstrap.wiring.study_plan import get_study_plan_service
from app.main import app
from app.modules.identity.contracts import CurrentUser
from app.modules.learning.application.study_plan import (
    StoredPlan,
    StoredPlanItem,
    StudyPlanError,
    StudyPlanService,
)
from app.modules.learning.domain.study_plan import (
    DAILY_MINUTES,
    MAX_PROPOSALS,
    TEMPLATE_INTRO,
    PlanItemKind,
    PlanItemStatus,
    PlanSignals,
    PlanVideo,
    acceptable_text,
    compose_plan,
)
from app.modules.learning.infrastructure.study_plans import StudyPlanRepository

OWNER, OTHER = uuid4(), uuid4()
USER = CurrentUser(id=OWNER)
TODAY = date(2026, 10, 17)
NOW = datetime(2026, 10, 17, 3, 0, tzinfo=UTC)
ITEM, VIDEO = uuid4(), uuid4()
VIDEO_SIGNAL = PlanVideo(library_item_id=ITEM, title="Neil's difficult summer job")


# --- Composition ----------------------------------------------------------------------------

def kinds(items):
    return [item.kind for item in items]


def test_a_new_learner_is_asked_to_add_a_video_first():
    items = compose_plan(PlanSignals(reviews_ready=0, latest_video=None, saved_words=0))
    assert kinds(items) == [PlanItemKind.ADD_VIDEO, PlanItemKind.CONVERSATION]


def test_review_comes_first_then_the_video_then_a_topic_within_the_budget():
    items = compose_plan(PlanSignals(reviews_ready=4, latest_video=VIDEO_SIGNAL, saved_words=6))
    assert kinds(items) == [PlanItemKind.REVIEW, PlanItemKind.VIDEO_PRACTICE, PlanItemKind.CONVERSATION]
    assert items[0].item_count == 4 and items[0].minutes == 2
    assert items[1].library_item_id == ITEM
    assert items[2].companion_entry == "home" and items[2].library_item_id is None
    assert len(items) <= MAX_PROPOSALS and sum(item.minutes for item in items) <= DAILY_MINUTES


def test_a_long_review_leaves_room_only_for_what_fits():
    items = compose_plan(PlanSignals(reviews_ready=20, latest_video=VIDEO_SIGNAL, saved_words=2))
    assert kinds(items) == [PlanItemKind.REVIEW, PlanItemKind.VIDEO_PRACTICE]  # 10 + 5 minutes
    assert sum(item.minutes for item in items) <= DAILY_MINUTES


def test_the_video_conversation_and_saved_words_fill_the_plan_when_there_is_no_review():
    items = compose_plan(PlanSignals(reviews_ready=0, latest_video=VIDEO_SIGNAL, saved_words=3))
    assert kinds(items) == [PlanItemKind.VIDEO_PRACTICE, PlanItemKind.CONVERSATION, PlanItemKind.CONVERSATION]
    assert [item.companion_entry for item in items[1:]] == ["home", "video"]


def test_a_recurring_error_is_mentioned_on_the_conversation_only():
    items = compose_plan(PlanSignals(reviews_ready=0, latest_video=VIDEO_SIGNAL, saved_words=0,
                                     has_recurring_error=True))
    video_talk = next(item for item in items if item.companion_entry == "video")
    assert "lỗi hay gặp" in video_talk.reason
    assert all("lỗi" not in item.reason for item in items if item is not video_talk)


@pytest.mark.parametrize("text, ok", [
    ("Ôn 4 từ hôm nay giúp bạn nhớ lâu hơn.", True),
    ("Bạn sẽ được 10 điểm!", False),
    ("Your score will go up.", False),
    ("Xem thêm tại https://example.com", False),
    ("x" * 161, False),
    ("   ", False),
])
def test_model_text_must_be_short_and_make_no_grading_claim(text, ok):
    assert acceptable_text(text, max_chars=160) is ok


# --- Service ---------------------------------------------------------------------------------

class FakeStore:
    def __init__(self):
        self.plans: dict[tuple, StoredPlan] = {}
        self.owners: dict[UUID, UUID] = {}
        self.created = []

    def get_plan(self, user_id, *, language_code, plan_day):
        return self.plans.get((user_id, language_code, plan_day))

    def create_plan(self, user_id, *, language_code, plan_day, intro, text_source, model, prompt_version, items):
        self.created.append({"text_source": text_source, "model": model, "prompt_version": prompt_version,
                             "intro": intro, "items": items})
        key = (user_id, language_code, plan_day)
        if key not in self.plans:
            stored = tuple(StoredPlanItem(
                id=uuid4(), plan_day=plan_day, position=index, kind=item.kind, status=PlanItemStatus.OPEN,
                minutes=item.minutes, reason=item.reason, library_item_id=item.library_item_id,
                video_title=item.video_title, companion_entry=item.companion_entry, item_count=item.item_count,
            ) for index, item in enumerate(items))
            for item in stored:
                self.owners[item.id] = user_id
            self.plans[key] = StoredPlan(id=uuid4(), plan_day=plan_day, language_code=language_code, intro=intro,
                                         items=stored)
        return self.plans[key].id

    def _find(self, item_id):
        for key, plan in self.plans.items():
            for item in plan.items:
                if item.id == item_id:
                    return key, plan, item
        return None

    def get_item(self, user_id, item_id):
        found = self._find(item_id)
        return found[2] if found and self.owners[item_id] == user_id else None

    def decide(self, user_id, item_id, *, status):
        found = self._find(item_id)
        if not found or self.owners[item_id] != user_id or found[2].status != PlanItemStatus.OPEN:
            return False
        key, plan, item = found
        updated = StoredPlanItem(**{**vars(item), "status": status})
        self.plans[key] = StoredPlan(id=plan.id, plan_day=plan.plan_day, language_code=plan.language_code,
                                     intro=plan.intro,
                                     items=tuple(updated if other.id == item_id else other for other in plan.items))
        return True


class FakeModel:
    provider_name, model_name = "fake", "fake-plan"

    def __init__(self, output=None, error=None):
        self.output, self.error, self.prompts = output, error, []

    def generate_structured(self, prompt, response_model, **kwargs):
        self.prompts.append(prompt)
        if self.error:
            raise self.error
        return response_model.model_validate(self.output)


def make_service(*, reviews=4, saved=0, videos=True, model=None, recurring=None, store=None, profile=True):
    preferences = Mock()
    preferences.get_profile_for_user.return_value = (
        SimpleNamespace(language_code="en", support_language_code="vi") if profile else None)
    library = Mock()
    association = SimpleNamespace(id=ITEM, video_id=VIDEO)
    library.list_for_user.return_value = [association] if videos else []
    library.get_for_user.side_effect = lambda library_item_id, user_id: (
        association if (library_item_id, user_id) == (ITEM, OWNER) else None)
    video_repo = Mock()
    video_repo.get_many_by_ids.side_effect = lambda ids: {VIDEO: SimpleNamespace(
        id=VIDEO, title="Neil's difficult summer job", original_language_code="en", learning_status="ready")}
    review_reader = Mock()
    review_reader.ready_count.return_value = reviews
    saved_reader = Mock()
    saved_reader.saved_to_practise.return_value = saved
    return StudyPlanService(preferences=preferences, library=library, videos=video_repo, reviews=review_reader,
                            saved_words=saved_reader, recurring=recurring, model=model, store=store or FakeStore(),
                            clock=lambda: NOW)


def error_of(callable_):
    with pytest.raises(StudyPlanError) as raised:
        callable_()
    return raised.value.kind, raised.value.code


def test_first_open_composes_and_stores_template_plan_then_reads_it_back():
    service = make_service()
    plan = service.today(USER, TODAY)

    assert [item.kind for item in plan.items] == [PlanItemKind.REVIEW, PlanItemKind.VIDEO_PRACTICE,
                                                  PlanItemKind.CONVERSATION]
    assert plan.intro == TEMPLATE_INTRO and plan.language_code == "en" and plan.day == TODAY
    assert service.store.created[0]["text_source"] == "template" and service.store.created[0]["model"] is None
    service.reviews.ready_count.reset_mock()
    again = service.today(USER, TODAY)
    assert again.plan_id == plan.plan_id
    service.reviews.ready_count.assert_not_called()  # a stored plan is never recomposed


def test_model_wording_replaces_reasons_but_never_the_choice_or_order():
    output = {"intro": "Chào bạn! Hôm nay mình có ba gợi ý nhỏ.",
              "reasons": [{"index": 0, "reason": "Ôn 4 mục này để nhớ lâu hơn."},
                          {"index": 1, "reason": "Kể cho mình nghe về công việc mùa hè của Neil nhé."},
                          {"index": 2, "reason": "Chọn một chủ đề rồi nói với mình nhé."}]}
    model = FakeModel(output)
    service = make_service(model=model)
    plan = service.today(USER, TODAY)

    assert plan.intro == "Chào bạn! Hôm nay mình có ba gợi ý nhỏ."
    assert [item.reason for item in plan.items][1] == "Kể cho mình nghe về công việc mùa hè của Neil nhé."
    assert [item.kind for item in plan.items][0] == PlanItemKind.REVIEW
    created = service.store.created[0]
    assert created["text_source"] == "model" and created["model"] == "fake-plan"
    assert created["prompt_version"] == "companion-plan-v1"
    assert "<tasks>" in model.prompts[0] and "Neil's difficult summer job" in model.prompts[0]


@pytest.mark.parametrize("output, error", [
    ({"intro": "Chào bạn!", "reasons": [{"index": 0, "reason": "Ôn đi."}]}, None),  # missing positions
    ({"intro": "Bạn sẽ được 10 điểm!", "reasons": [{"index": i, "reason": "Tốt."} for i in range(3)]}, None),
    ({"intro": "Chào", "reasons": [], "extra": 1}, None),  # extra field rejected by the schema
    (None, RuntimeError("provider down")),
])
def test_bad_or_missing_wording_falls_back_to_templates(output, error):
    service = make_service(model=FakeModel(output, error))
    plan = service.today(USER, TODAY)
    assert plan.intro == TEMPLATE_INTRO
    assert service.store.created[0]["text_source"] == "template"


def test_one_unsafe_reason_keeps_its_template_while_the_others_are_used():
    output = {"intro": "Chào bạn!", "reasons": [
        {"index": 0, "reason": "Ôn để được 10 điểm."}, {"index": 1, "reason": "Nói chuyện về video nhé."},
        {"index": 2, "reason": "Làm bài ngắn nhé."}]}
    plan = make_service(model=FakeModel(output)).today(USER, TODAY)
    assert "điểm" not in plan.items[0].reason and plan.items[1].reason == "Nói chuyện về video nhé."


def test_recurring_kinds_of_mistake_reach_the_prompt_only_as_codes_and_a_failing_reader_is_ignored():
    recurring = Mock()
    recurring.recurring.return_value = ["verb_tense"]
    reasons = {"intro": "Chào!", "reasons": [{"index": i, "reason": "Tốt."} for i in range(3)]}
    model = FakeModel(reasons)
    make_service(model=model, recurring=recurring).today(USER, TODAY)
    assert "verb_tense" in model.prompts[0]

    recurring.recurring.return_value = []
    model_none = FakeModel(reasons)
    make_service(model=model_none, recurring=recurring).today(USER, TODAY)
    assert "verb_tense" not in model_none.prompts[0]

    recurring.recurring.side_effect = RuntimeError("database down")
    assert make_service(recurring=recurring).today(USER, TODAY).items


def test_failed_signal_read_stores_nothing():
    service = make_service()
    service.reviews.ready_count.side_effect = RuntimeError("database")
    with pytest.raises(RuntimeError):
        service.today(USER, TODAY)
    assert service.store.created == []


def test_day_far_from_today_and_missing_language_are_refused():
    assert error_of(lambda: make_service().today(USER, date(2026, 10, 20))) == ("invalid_input", "plan_day_invalid")
    assert error_of(lambda: make_service(profile=False).today(USER, TODAY)) == (
        "conflict", "language_profile_required")


def test_plans_are_per_learner():
    store = FakeStore()
    make_service(store=store).today(USER, TODAY)
    other = make_service(store=store, videos=False, reviews=0).today(CurrentUser(id=OTHER), TODAY)
    assert [item.kind for item in other.items] == [PlanItemKind.ADD_VIDEO, PlanItemKind.CONVERSATION]


# --- Choices ---------------------------------------------------------------------------------

def test_accept_rechecks_ownership_and_is_idempotent():
    service = make_service()
    conversation = service.today(USER, TODAY).items[1]

    accepted = service.decide(USER, conversation.id, PlanItemStatus.ACCEPTED)
    assert accepted.status == PlanItemStatus.ACCEPTED
    service.library.get_for_user.assert_called_with(library_item_id=ITEM, user_id=OWNER)
    assert service.decide(USER, conversation.id, PlanItemStatus.ACCEPTED).status == PlanItemStatus.ACCEPTED
    assert error_of(lambda: service.decide(USER, conversation.id, PlanItemStatus.DISMISSED)) == (
        "conflict", "plan_item_decided")


def test_another_learner_cannot_see_or_decide_a_proposal():
    service = make_service()
    item = service.today(USER, TODAY).items[0]
    assert error_of(lambda: service.decide(CurrentUser(id=OTHER), item.id, PlanItemStatus.ACCEPTED)) == (
        "not_found", "plan_item_not_found")
    assert service.store.get_item(OWNER, item.id).status == PlanItemStatus.OPEN


def test_a_video_removed_from_the_library_cannot_be_accepted():
    service = make_service()
    practice = service.today(USER, TODAY).items[1]
    service.library.get_for_user.side_effect = lambda library_item_id, user_id: None
    assert error_of(lambda: service.decide(USER, practice.id, PlanItemStatus.ACCEPTED)) == (
        "not_found", "plan_item_unavailable")
    assert service.decide(USER, practice.id, PlanItemStatus.DISMISSED).status == PlanItemStatus.DISMISSED


def test_proposals_from_an_earlier_day_expire():
    store = FakeStore()
    old = make_service(store=store).today(USER, date(2026, 10, 16)).items[0]
    later = make_service(store=store)
    later.clock = lambda: datetime(2026, 10, 19, 3, 0, tzinfo=UTC)
    assert error_of(lambda: later.decide(USER, old.id, PlanItemStatus.ACCEPTED)) == ("conflict", "plan_item_expired")


# --- Repository mapping --------------------------------------------------------------------

def test_repository_creates_plan_and_items_in_one_rpc():
    client = Mock()
    client.schema.return_value.rpc.return_value.execute.return_value = SimpleNamespace(data=str(uuid4()))
    items = compose_plan(PlanSignals(reviews_ready=2, latest_video=VIDEO_SIGNAL, saved_words=0))
    StudyPlanRepository(client).create_plan(OWNER, language_code="en", plan_day=TODAY, intro="Chào",
                                            text_source="template", model=None, prompt_version=None, items=items)
    name, payload = client.schema.return_value.rpc.call_args.args
    assert name == "create_companion_plan" and payload["p_user_id"] == str(OWNER)
    assert payload["p_plan_day"] == "2026-10-17"
    assert [item["kind"] for item in payload["p_items"]] == ["review", "video_practice", "conversation"]
    assert payload["p_items"][1]["library_item_id"] == str(ITEM)
    assert payload["p_items"][2]["companion_entry"] == "home" and payload["p_items"][2]["library_item_id"] is None


# --- HTTP surface ----------------------------------------------------------------------------

class AuthVerifier:
    def verify(self, token):
        return CurrentUser(id=OWNER)


@pytest.fixture
def api():
    service = make_service()
    app.dependency_overrides[get_jwt_verifier] = lambda: AuthVerifier()
    app.dependency_overrides[get_study_plan_service] = lambda: service
    try:
        yield SimpleNamespace(client=TestClient(app), service=service,
                              headers={"Authorization": "Bearer a.b.c"})
    finally:
        app.dependency_overrides.clear()


def test_plan_routes_require_authentication():
    client = TestClient(app)
    assert client.get("/api/v1/v3/learner/me/plan", params={"day": "2026-10-17"}).status_code == 401
    assert client.post(f"/api/v1/v3/learner/me/plan/items/{uuid4()}/accept").status_code == 401


def test_plan_round_trip_over_http(api):
    url = "/api/v1/v3/learner/me/plan"
    body = api.client.get(url, params={"day": "2026-10-17"}, headers=api.headers).json()
    assert [item["kind"] for item in body["items"]] == ["review", "video_practice", "conversation"]
    assert set(body) == {"plan_id", "day", "language_code", "intro", "items", "yesterday"}
    item_id = body["items"][1]["id"]
    accepted = api.client.post(f"{url}/items/{item_id}/accept", headers=api.headers)
    assert accepted.status_code == 200 and accepted.json()["status"] == "accepted"
    again = api.client.post(f"{url}/items/{item_id}/dismiss", headers=api.headers)
    assert again.status_code == 409 and again.json()["detail"]["code"] == "plan_item_decided"
    assert api.client.get(url, params={"day": "2026-11-30"}, headers=api.headers).status_code == 422
    assert api.client.get(url, headers=api.headers).status_code == 422  # day is required
    assert api.client.post(f"{url}/items/{uuid4()}/accept", headers=api.headers).status_code == 404


# --- Home suggestions (FR-4.2) ------------------------------------------------------------

RESUME_SIGNAL = PlanVideo(library_item_id=uuid4(), title="A half-watched talk")


def test_a_half_watched_video_is_proposed_before_the_newest_one():
    items = compose_plan(PlanSignals(reviews_ready=0, latest_video=VIDEO_SIGNAL, saved_words=0,
                                     resume_video=RESUME_SIGNAL))
    assert items[0].kind == PlanItemKind.VIDEO_PRACTICE and items[0].library_item_id == RESUME_SIGNAL.library_item_id
    assert "Tiếp tục" in items[0].reason and "A half-watched talk" in items[0].reason


def test_a_topic_to_talk_about_needs_no_video_and_names_no_video():
    items = compose_plan(PlanSignals(reviews_ready=0, latest_video=None, saved_words=0))
    topic = next(item for item in items if item.kind == PlanItemKind.CONVERSATION)
    assert topic.companion_entry == "home" and topic.library_item_id is None and topic.video_title is None
    assert kinds(items) == [PlanItemKind.ADD_VIDEO, PlanItemKind.CONVERSATION]


def test_home_never_gets_more_than_three_suggestions():
    items = compose_plan(PlanSignals(reviews_ready=2, latest_video=VIDEO_SIGNAL, saved_words=9,
                                     resume_video=RESUME_SIGNAL, has_recurring_error=True))
    assert len(items) == MAX_PROPOSALS == 3


def make_resume_service(*, resume):
    service = make_service(reviews=0)
    service.resume = Mock()
    service.resume.latest.return_value = resume
    return service


def test_the_service_proposes_the_video_the_learner_stopped_in_when_it_is_still_theirs():
    service = make_resume_service(resume=SimpleNamespace(library_item_id=ITEM, title="Neil's difficult summer job"))
    plan = service.today(USER, TODAY)
    assert plan.items[0].kind == PlanItemKind.VIDEO_PRACTICE and "Tiếp tục" in plan.items[0].reason


def test_a_resume_video_that_left_the_library_is_ignored():
    gone = make_resume_service(resume=SimpleNamespace(library_item_id=uuid4(), title="Gone"))
    assert all("Tiếp tục" not in item.reason for item in gone.today(USER, TODAY).items)


def test_a_failing_resume_read_never_blocks_the_plan():
    service = make_resume_service(resume=None)
    service.resume.latest.side_effect = RuntimeError("database")
    assert service.today(USER, TODAY).items
