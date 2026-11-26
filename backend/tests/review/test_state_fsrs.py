from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from app.modules.identity.contracts import CurrentUser
from app.modules.review.domain.models import (
    FSRSState,
    ReviewEvent,
    ReviewMode,
    ReviewRating,
    ReviewState,
    initial_review_state,
    serialize_review_event_for_insert,
)
from app.modules.review.infrastructure.review_states import ReviewStateRepository


USER_A = UUID("11111111-1111-1111-1111-111111111111")
USER_B = UUID("22222222-2222-2222-2222-222222222222")
CONCEPT_ID = UUID("33333333-3333-3333-3333-333333333333")


def current_user(user_id=USER_A):
    return CurrentUser(id=user_id, role="authenticated", claims={"app_metadata": {}})


def test_review_state_identity_includes_user_concept_and_review_mode():
    due = datetime(2026, 1, 1, tzinfo=UTC)
    state = ReviewState(
        user_id=USER_A,
        concept_id=CONCEPT_ID,
        review_mode=ReviewMode.AUDIO_TO_TEXT,
        due_at=due,
        fsrs_state=FSRSState.NEW,
    )

    assert state.user_id == USER_A
    assert state.concept_id == CONCEPT_ID
    assert state.review_mode == ReviewMode.AUDIO_TO_TEXT
    assert state.state == FSRSState.NEW


def test_initial_review_state_is_conservative_and_not_fake_mature_state():
    state = initial_review_state(user_id=USER_A, concept_id=CONCEPT_ID)

    assert state.state == FSRSState.NEW
    assert state.review_mode == ReviewMode.CONCEPT_TO_MEANING
    assert state.reps == 0
    assert state.lapses == 0
    assert state.elapsed_days == 0
    assert state.scheduled_days == 0
    assert state.stability == 0
    assert state.difficulty == 0
    assert state.last_reviewed_at is None
    assert state.due_at.tzinfo is not None


@pytest.mark.parametrize(
    "field,value",
    [
        ("stability", -0.1),
        ("difficulty", -0.1),
        ("difficulty", 10.1),
        ("elapsed_days", -1),
        ("scheduled_days", -1),
        ("reps", -1),
        ("lapses", -1),
    ],
)
def test_fsrs_field_ranges_are_validated(field, value):
    data = {
        "user_id": USER_A,
        "concept_id": CONCEPT_ID,
        "review_mode": ReviewMode.CONCEPT_TO_MEANING,
        "due_at": datetime.now(UTC),
        field: value,
    }

    with pytest.raises(ValidationError):
        ReviewState(**data)


def test_new_review_state_rejects_existing_review_history_fields():
    with pytest.raises(ValidationError):
        ReviewState(
            user_id=USER_A,
            concept_id=CONCEPT_ID,
            review_mode=ReviewMode.CONCEPT_TO_MEANING,
            due_at=datetime.now(UTC),
            fsrs_state=FSRSState.NEW,
            reps=1,
        )
    with pytest.raises(ValidationError):
        ReviewState(
            user_id=USER_A,
            concept_id=CONCEPT_ID,
            review_mode=ReviewMode.CONCEPT_TO_MEANING,
            due_at=datetime.now(UTC),
            fsrs_state=FSRSState.NEW,
            last_reviewed_at=datetime.now(UTC),
        )


def test_review_state_is_separate_from_concept_mastery_fields():
    fields = set(ReviewState.model_fields)

    assert "overall" not in fields
    assert "recognition" not in fields
    assert "comprehension" not in fields
    assert "listening" not in fields
    assert "recall" not in fields
    assert "production" not in fields
    assert "speaking" not in fields
    assert "confidence" not in fields
    assert "sample_count" not in fields
    assert "last_assessed_at" not in fields


def test_review_state_is_separate_from_attempt_and_assessment_payloads():
    fields = set(ReviewState.model_fields)

    assert "response_payload" not in fields
    assert "feedback" not in fields
    assert "overall_score" not in fields
    assert "raw_ai_diagnostics" not in fields
    assert "assessor_type" not in fields


def test_review_event_is_append_only_and_rejects_answer_prompt_leakage():
    event = ReviewEvent(
        review_state_id=uuid4(),
        assessment_id=uuid4(),
        attempt_id=uuid4(),
        review_mode=ReviewMode.CONCEPT_TO_MEANING,
        rating=ReviewRating.GOOD,
        previous_scheduling_state={"fsrs_state": "new", "reps": 0},
        resulting_scheduling_state={"fsrs_state": "learning", "reps": 1},
        reviewed_at=datetime.now(UTC),
    )

    payload = serialize_review_event_for_insert(event)

    assert payload["rating"] == 3
    assert "review_state_id" in payload
    assert "answer" not in payload["previous_scheduling_state"]
    with pytest.raises(ValidationError):
        ReviewEvent(
            review_state_id=uuid4(),
            assessment_id=uuid4(),
            review_mode=ReviewMode.CONCEPT_TO_MEANING,
            rating=ReviewRating.GOOD,
            previous_scheduling_state={"prompt": "hidden"},
            resulting_scheduling_state={"fsrs_state": "review"},
            reviewed_at=datetime.now(UTC),
        )


class Result:
    def __init__(self, data):
        self.data = data


class FakeQuery:
    def __init__(self, data):
        self.data = data
        self.calls = []

    def select(self, value):
        self.calls.append(("select", value))
        return self

    def eq(self, field, value):
        self.calls.append(("eq", field, value))
        return self

    def lte(self, field, value):
        self.calls.append(("lte", field, value))
        return self

    def in_(self, field, values):
        self.calls.append(("in", field, values))
        return self

    def order(self, field, **kwargs):
        self.calls.append(("order", field, kwargs))
        return self

    def limit(self, value):
        self.calls.append(("limit", value))
        return self

    def insert(self, payload):
        self.calls.append(("insert", payload))
        self.data = [{**payload, "id": str(uuid4())}]
        return self

    def execute(self):
        return Result(self.data)


class FakeSupabaseClient:
    def __init__(self, data=None):
        self.data = data or []
        self.schema_name = None
        self.table_name = None
        self.query = None

    def schema(self, name):
        self.schema_name = name
        return self

    def table(self, name):
        self.table_name = name
        self.query = FakeQuery(self.data)
        return self.query


def test_review_state_repository_targets_v3_and_scopes_identity():
    row = initial_review_state(user_id=USER_A, concept_id=CONCEPT_ID).model_dump(mode="json")
    row["id"] = str(uuid4())
    client = FakeSupabaseClient([row])
    repo = ReviewStateRepository(client)

    state = repo.get_for_user(user_id=USER_A, concept_id=CONCEPT_ID, review_mode=ReviewMode.CONCEPT_TO_MEANING)

    assert client.schema_name == "v3"
    assert client.table_name == "review_states"
    assert ("eq", "user_id", str(USER_A)) in client.query.calls
    assert ("eq", "concept_id", str(CONCEPT_ID)) in client.query.calls
    assert ("eq", "review_mode", "concept_to_meaning") in client.query.calls
    assert state.user_id == USER_A


def test_due_query_repository_uses_user_due_at_and_limit():
    client = FakeSupabaseClient([])
    repo = ReviewStateRepository(client)
    due_at = datetime.now(UTC)

    rows = repo.list_due_for_user(user_id=USER_A, due_at=due_at, limit=25)

    assert rows == []
    assert ("eq", "user_id", str(USER_A)) in client.query.calls
    assert any(call[0] == "lte" and call[1] == "due_at" for call in client.query.calls)
    assert ("order", "due_at", {}) in client.query.calls
    assert ("limit", 25) in client.query.calls
    assert not any(call[:2] == ("eq", "review_mode") for call in client.query.calls)


def test_due_query_can_ask_for_one_review_mode_before_the_limit():
    client = FakeSupabaseClient([])
    repo = ReviewStateRepository(client)

    repo.list_due_for_user(user_id=USER_A, due_at=datetime.now(UTC), limit=10,
                           review_mode=ReviewMode.CONCEPT_TO_MEANING)

    assert ("eq", "review_mode", "concept_to_meaning") in client.query.calls
    assert ("limit", 10) in client.query.calls


def test_due_query_can_ask_for_one_language_before_the_limit():
    client = FakeSupabaseClient([])
    ReviewStateRepository(client).list_due_for_user(user_id=USER_A, due_at=datetime.now(UTC), limit=10,
                                                    language_code="en")
    calls = client.query.calls
    assert calls.index(("eq", "language_code", "en")) < calls.index(("limit", 10))


def test_due_query_filters_notebook_members_before_the_limit():
    client = FakeSupabaseClient([])
    repo = ReviewStateRepository(client)
    ids = [uuid4(), uuid4()]
    repo.list_due_for_user(user_id=USER_A, due_at=datetime.now(UTC), limit=10,
                           review_mode=ReviewMode.CONCEPT_TO_MEANING, concept_ids=ids)
    calls = client.query.calls
    assert ("eq", "user_id", str(USER_A)) in calls
    assert calls.index(("in", "concept_id", [str(value) for value in ids])) < calls.index(("limit", 10))
    empty = FakeSupabaseClient([])
    assert ReviewStateRepository(empty).list_due_for_user(
        user_id=USER_A, due_at=datetime.now(UTC), concept_ids=[]) == []
    assert empty.query is None


def test_next_due_can_read_just_recognition_without_mixing_other_modes():
    due = datetime(2026, 10, 20, tzinfo=UTC)
    client = FakeSupabaseClient([{"concept_id": str(CONCEPT_ID), "due_at": due.isoformat()}])
    repo = ReviewStateRepository(client)
    assert repo.next_due_by_concept(user_id=USER_A, concept_ids=[CONCEPT_ID], recognition_only=True) == {CONCEPT_ID: due}
    assert ("eq", "user_id", str(USER_A)) in client.query.calls
    assert ("eq", "review_mode", "concept_to_meaning") in client.query.calls
    repo.next_due_by_concept(user_id=USER_A, concept_ids=[CONCEPT_ID])
    assert not any(call[:2] == ("eq", "review_mode") for call in client.query.calls)


def test_no_legacy_flashcard_dependency_in_review_state_foundation():
    sources = [
        "app/modules/review/domain/models.py",
        "app/modules/review/infrastructure/review_states.py",
    ]
    for path in sources:
        text = open(path, encoding="utf-8").read()
        for forbidden in ["flashcards", "flashcard_reviews", "user_vocabulary_progress", "public."]:
            assert forbidden not in text
