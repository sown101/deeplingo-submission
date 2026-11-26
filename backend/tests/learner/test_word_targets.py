"""L1a learner targets: immediate review eligibility, the out-of-level warning and the ladder events."""
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID, uuid4

import pytest

from app.modules.content.domain.knowledge import Concept, ConceptType
from app.modules.content.infrastructure.repositories.saved_concepts import SavedConceptRepository
from app.modules.identity.contracts import CurrentUser
from app.modules.learner.application.word_targets import WordTargetsError, WordTargetsService
from app.modules.learner.domain.ladder import EventKind, Outcome
from app.modules.learner.domain.word_targets import PRIORITY_EXPLICIT, PRIORITY_LOOKUP, TargetStatus

USER_ID = UUID("11111111-1111-1111-1111-111111111111")
USER = CurrentUser(id=USER_ID, role="authenticated", claims={})
# 21:00 UTC on 1 Oct is 04:00 on 2 Oct in Ho Chi Minh City.
START = datetime(2026, 10, 1, 21, 0, tzinfo=UTC)


def test_repository_new_save_is_active_with_an_activation_time():
    table = Mock()
    repository = SavedConceptRepository(Mock())
    repository.table = Mock(return_value=table)
    repository.get = Mock(return_value={"status": "active"})
    repository.save(USER_ID, concept_id=uuid4(), save_source="manual")
    inserted = table.upsert.call_args.args[0]
    assert inserted["status"] == "active"
    assert datetime.fromisoformat(inserted["activated_at"]).tzinfo is not None
    assert inserted["activated_at"] == inserted["updated_at"]


@pytest.mark.parametrize("status", ["active", "backlog", "suspended"])
def test_repository_repeat_save_preserves_the_original_row_and_evidence(status):
    original = {"status": status, "rung": 4, "activated_at": START.isoformat(), "save_source": "import"}
    table = Mock()
    repository = SavedConceptRepository(Mock())
    repository.table = Mock(return_value=table)
    repository.get = Mock(return_value=original)
    assert repository.save(USER_ID, concept_id=uuid4(), save_source="manual") == original
    assert table.upsert.call_args.kwargs == {"on_conflict": "user_id,concept_id", "ignore_duplicates": True}
    assert all(set(call.args[0]) <= {"explicit", "priority"} for call in table.update.call_args_list)


class FakeTargets:
    """In-memory `saved_concepts` with the repository's contract (compare-and-set, ordering)."""

    def __init__(self):
        self.rows: dict[UUID, dict] = {}
        self.counter = 0

    def list_for_user(self, user_id, *, language_code=None, status=None):
        return [dict(row) for row in self.rows.values()
                if (language_code is None or row["language_code"] == language_code)
                and (status is None or row["status"] == status)]

    def get(self, user_id, concept_id):
        row = self.rows.get(concept_id)
        return dict(row) if row else None

    def concept_ids_for(self, user_id, concept_ids):
        return {item for item in concept_ids if item in self.rows}

    def save(self, user_id, *, concept_id, save_source, source_learning_object_id=None, language_code=None,
             level_label=None, priority=100, explicit=True):
        row = self.rows.get(concept_id)
        if row is None:
            self.counter += 1
            row = {"id": str(uuid4()), "concept_id": str(concept_id), "save_source": save_source, "status": "active",
                   "explicit": explicit,
                   "priority": priority, "level_label": level_label, "rung": 0, "activated_at": START.isoformat(),
                   "language_code": language_code, "created_at": (START + timedelta(minutes=self.counter)).isoformat()}
            self.rows[concept_id] = row
        else:
            row["priority"] = max(row["priority"], priority)
            row["explicit"] = row["explicit"] or explicit
        return dict(row)

    def set_status(self, user_id, *, concept_id, status, now, only_from=None):
        row = self.rows.get(concept_id)
        if row is None or (only_from and row["status"] != only_from):
            return None
        row["status"] = status
        if status == "active":
            row["activated_at"] = now.isoformat()
        return dict(row)

    def count_activated_since(self, user_id, *, language_code, since):
        return sum(1 for row in self.rows.values() if row["language_code"] == language_code and row["activated_at"]
                   and datetime.fromisoformat(row["activated_at"]) >= since)

    def list_backlog(self, user_id, *, language_code, limit):
        rows = [dict(row) for row in self.rows.values() if row["status"] == "backlog"
                and row["language_code"] == language_code]
        return sorted(rows, key=lambda row: (-row["priority"], row["created_at"]))[:limit]

    def set_rung(self, user_id, *, concept_id, rung):
        self.rows[concept_id]["rung"] = rung

    def remove(self, user_id, *, concept_id):
        return self.rows.pop(concept_id, None) is not None


class FakeEvents:
    def __init__(self):
        self.rows: dict[str, dict] = {}
        self.fail = False

    def record(self, user_id, *, concept_id, kind, outcome, event_key, occurred_at, context_key=None, quote=None,
               error_type=None, judge=None):
        if self.fail:
            raise RuntimeError("database unavailable")
        self.rows.setdefault(event_key, {"concept_id": concept_id, "kind": kind, "outcome": outcome,
                                         "occurred_at": occurred_at.isoformat(), "context_key": context_key})

    def list_for_concept(self, user_id, concept_id):
        return sorted((row for row in self.rows.values() if row["concept_id"] == concept_id),
                      key=lambda row: row["occurred_at"])


def concept(text="give up", *, level="B1", language="en"):
    return Concept(id=uuid4(), language_code=language, type=ConceptType.EXPRESSION, canonical_text=text,
                   normalized_text=text, sense_key=text, difficulty_level=level)


class Env(SimpleNamespace):
    pass


def build(*, declared="A2", limit=10):
    clock = {"now": START}
    targets, events = FakeTargets(), FakeEvents()
    preference = SimpleNamespace(declared_level=declared, daily_new_limit=limit)
    service = WordTargetsService(
        targets=targets, events=events,
        preferences=SimpleNamespace(get_by_language_for_user=lambda **kw: preference if kw["language_code"] in ("en", "zh") else None),
        profiles=SimpleNamespace(get_by_user_id=lambda user_id: SimpleNamespace(timezone="Asia/Ho_Chi_Minh")),
        clock=lambda: clock["now"],
    )
    return Env(service=service, targets=targets, events=events, clock=clock, preference=preference)


def add_backlog(env, count, *, priority=PRIORITY_EXPLICIT, language="en"):
    items = [concept(f"word{n}", level="A2", language=language) for n in range(count)]
    for item in items:
        env.service.register(USER, item, save_source="manual", explicit=True, priority=priority)
    return items


# --- Registering and the out-of-level warning ---------------------------------------------------

def test_an_explicit_save_is_active_with_priority_level_and_language():
    env = build()
    word = concept("rely on", level="b1")
    row = env.service.register(USER, word, save_source="lookup", explicit=True, priority=PRIORITY_EXPLICIT)
    assert (row["status"], row["priority"], row["level_label"], row["language_code"], row["explicit"]) == (
        "active", PRIORITY_EXPLICIT, "B1", "en", True)


def test_a_word_more_than_one_band_above_the_declared_level_needs_one_confirmation_and_is_never_blocked():
    env = build(declared="A2")
    hard = concept("ubiquitous", level="C1")
    with pytest.raises(WordTargetsError) as error:
        env.service.register(USER, hard, save_source="manual", explicit=True, priority=PRIORITY_EXPLICIT)
    assert (error.value.status_code, error.value.code) == (409, "above_level")
    assert error.value.extra == {"level": "C1", "declared_level": "A2"}
    assert env.targets.rows == {}
    row = env.service.register(USER, hard, save_source="manual", explicit=True, priority=PRIORITY_EXPLICIT,
                               acknowledge_above_level=True)
    assert row["status"] == "active"
    # An existing target is never asked about again.
    assert env.service.register(USER, hard, save_source="manual", explicit=True, priority=PRIORITY_EXPLICIT)["status"] == "active"


@pytest.mark.parametrize("declared, level", [(None, "C1"), ("A2", None), ("A2", "B1"), ("B2", "A1")])
def test_no_warning_without_a_declared_level_a_word_level_or_when_not_above(declared, level):
    env = build(declared=declared)
    env.service.register(USER, concept("x", level=level), save_source="manual", explicit=True, priority=PRIORITY_EXPLICIT)


def test_lookups_queued_by_the_system_never_ask_for_confirmation():
    env = build(declared="A2")
    hard = concept("ubiquitous", level="C1")
    env.service.register(USER, hard, save_source="lookup", explicit=False, priority=PRIORITY_LOOKUP)
    assert env.targets.rows[hard.id]["explicit"] is False


def test_saving_a_queued_lookup_explicitly_raises_its_priority_and_marks_it_explicit():
    env = build()
    word = concept("rely on", level="A2")
    env.service.register(USER, word, save_source="lookup", explicit=False, priority=PRIORITY_LOOKUP)
    row = env.service.register(USER, word, save_source="lookup", explicit=True, priority=PRIORITY_EXPLICIT)
    assert (row["priority"], row["explicit"]) == (PRIORITY_EXPLICIT, True)


# --- No daily activation gate ------------------------------------------------------------------


def test_all_saves_are_active_even_beyond_the_legacy_daily_limit():
    env = build(limit=1)
    words = add_backlog(env, 12)
    assert all(env.targets.rows[word.id]["status"] == "active" for word in words)
    assert not hasattr(env.service, "activate_for_today")


# --- The learner's own status choices ------------------------------------------------------------

def test_pausing_resuming_and_legacy_backlog_requests_work():
    env = build(limit=1)
    words = add_backlog(env, 3)
    row = env.service.set_status(USER, words[2].id, TargetStatus.ACTIVE)
    assert row["status"] == "active"
    assert env.service.set_status(USER, words[2].id, TargetStatus.SUSPENDED)["status"] == "suspended"
    assert env.service.set_status(USER, words[2].id, TargetStatus.BACKLOG)["status"] == "active"


def test_setting_the_status_of_an_unknown_word_is_refused():
    env = build()
    with pytest.raises(WordTargetsError) as missing:
        env.service.set_status(USER, uuid4(), TargetStatus.ACTIVE)
    assert (missing.value.status_code, missing.value.code) == (404, "word_not_found")


def test_the_summary_treats_legacy_backlog_as_active_and_keeps_compatibility_fields():
    env = build(limit=2)
    words = add_backlog(env, 4)
    env.targets.rows[words[0].id]["status"] = "backlog"
    env.targets.rows[words[0].id]["activated_at"] = None
    summary = env.service.summary(USER_ID, "en", [row["status"] for row in env.targets.rows.values()])
    assert (summary.backlog, summary.active, summary.activated_today, summary.daily_new_limit) == (0, 4, 3, 2)
    assert summary.declared_level == "A2"


# --- Events and the ladder -----------------------------------------------------------------------

def test_refreshing_the_rung_follows_the_stored_events_and_never_raises():
    """A graded Quick review answer stores its event inside the atomic commit; the rung is only a projection."""
    env = build()
    word = add_backlog(env, 1)[0]
    env.events.record(USER_ID, concept_id=word.id, kind=EventKind.RECOGNITION.value, outcome=Outcome.CORRECT.value,
                      event_key=f"quick_review:{uuid4()}", occurred_at=datetime.now(UTC))
    env.service.refresh_rung(USER_ID, word.id)
    assert env.targets.rows[word.id]["rung"] == 1
    env.targets.rows[word.id]["rung"] = 0  # a projection that fell behind is repaired by the next refresh
    env.service.refresh_rung(USER_ID, word.id)
    assert env.targets.rows[word.id]["rung"] == 1
    env.service.events = SimpleNamespace(list_for_concept=lambda *_: (_ for _ in ()).throw(RuntimeError("down")))
    env.service.refresh_rung(USER_ID, word.id)  # must not raise
